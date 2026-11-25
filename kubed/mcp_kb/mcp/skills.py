"""kb's skills and agents, served by kubed-mcp's plugin layer (K3).

Each generation kb publishes a plugin set: every plugin of every library, in
config order and each library's plugin order, added as itself under its
library's namespace (``snapshot.namespace_for``) from kb's own address, through
the served-tree loader. kubed-mcp then serves each skill's files, its
``_manifest``, the Skills extension's entries and the folders inside a skill,
and the plugins' agents through its agents extension. kb keeps its indexes,
``_files.md``, library files, fallbacks and prompts.

Three hooks make what kubed-mcp serves kb's:

- **The view** is kb's scope: the set of plugins a request's scope admits, as
  ``(namespace, address)`` pairs, which is also the build key. Every scope that
  admits nothing shares ``EMPTY``.
- **The rewriter** is kb's text rewriting, applied when a build is made, never
  on a read: a root ``SKILL.md`` through ``Catalogue.instructions`` and an
  agent's body through ``Catalogue.agent_instructions``. Every other file is
  served as written. The gateway prefix is kubed-mcp's writer, after it.
- **``agent_meta``** adds kb's ``io.kubed.mcp-kb/agent`` key to an agent's
  ``_meta``. It never sees a scope, so its ``skills`` names the agent's own
  plugin's skills alone (N9).

Commands are skipped by ``read_command``: kb serves its prompts itself until K4.

**The parity guard.** After the set is staged, kb's catalogue is narrowed to
what kubed-mcp reports serving -- each added plugin's ``skills`` URIs, and its
``agent_files`` -- so no index, hint, listing or rewritten name points at a
skill or an agent that does not read. Anything either side has alone is logged
once, and a skill only kubed-mcp found is failed in the rewriter, so it is not
served either: kb never vetted it (N13). A plugin kubed-mcp refuses is a
conflict in its library, as LIB-28's are.

The rewriter reads the published state its request's view pinned, so a build
of one set never reads the next one's, whether a re-read, a refresh or a
``serve()`` that raises swaps it meanwhile; a build no view pinned reads the
state published now. ``agent_meta`` reads the generation entering the set. The
published state is set before ``serve()``: a build made between ``serve()`` and
the swap in ``KnowledgeBase`` must already see the generation it is a build of.
One window is left. kb swaps its state before ``serve()`` and kubed-mcp swaps
its own inside it, so a request that reads kubed-mcp's state before kubed-mcp
swaps it and kb's after kb swaps it pins N and N+1, and builds N against N+1.
That includes a publish on a worker thread that makes both swaps between
kubed-mcp pinning its state and the view reading kb's. If that
``serve()`` then raises, kubed-mcp keeps the build until the next publish that
serves. Either order of the swaps leaves such a window. Closing it needs
kubed-mcp to hand the pinned generation to the view and on ``Site``.

**A live plugin is re-read on view (D9).** What a live plugin's skill and agent
files held on disk is stamped as it enters the set. The view revalidates the
live plugins its request's scope admits and stamps them again; a plugin whose
stamp moved is added again, every other one is kept as served, and the set is
served and kb's catalogue narrowed afresh, under the generation it already had.
kubed-mcp pins a request's state before it calls the view, so the request that
re-adds still reads the copy it pinned and the next one reads the edit (N6).
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote

from kubed.mcp import QuickMCP
from kubed.mcp.plugins import Plugin as Served
from kubed.mcp.plugins import PluginError, PluginSet, Site, View

from ..catalogue.agents import Agent, AgentRoster, parse_agent
from ..catalogue.harvest import readable
from ..catalogue.names import split_frontmatter
from ..catalogue.skills import Skill
from ..catalogue.snapshot import Library, Snapshot, namespace_for, unrooted
from ..catalogue.uris import AGENT_META, MAIN_FILE, SCHEME, agent_path
from ..config import scrub
from ..plugins import Plugin
from ..sources import plugin_root
from ..sources.live import is_live
from .request import requested_scope
from .scope import Scope

if TYPE_CHECKING:
    from ..server import KnowledgeBase

log = logging.getLogger(__name__)

# The key of every view that admits nothing, shared so no bogus scope makes one.
EMPTY: frozenset[tuple[str, str]] = frozenset()
COMMANDS_ARE_KBS = "kb serves its prompts itself until K4"

_ENTRY = f"/{MAIN_FILE}"
# kubed-mcp's reason for an agent whose rename is taken (PLUG-64).
_RENAME_TAKEN = re.compile(r"^agent (?P<name>\S+) is already served by plugin .+$")


@dataclass(frozen=True)
class _Row:
    """One added plugin, as a scope admits it: kb's plugin in one library."""

    library: str
    plugin: Plugin
    library_categories: frozenset[str]

    def admitted(self, scope: Scope) -> bool:
        return scope.admits(
            self.library,
            self.plugin.category,
            self.plugin.labels,
            library_categories=self.library_categories,
        )


# An added plugin's key: what kubed-mcp's ``Plugin`` carries.
Key = tuple[str, str]

# Each added plugin by ``(namespace, address)``. ``(library, address)`` alone is
# not unique: grafana's root entries share one address, each with its own
# category, and so do declared plugins reading different folders of one tree.
Table = Mapping[Key, _Row]


@dataclass(frozen=True)
class _Watch:
    """A live plugin's skills and agent files, and what they held on disk when
    it entered the set (D9)."""

    skills: tuple[Skill, ...]
    agents: tuple[Path, ...]
    stamp: tuple
    # The folder the plugin was added from: a refresh points its fetch at a
    # new export before it publishes, and a re-read must not add from that.
    root: Path | None = None
    # Its agents as the add read them, by path from the root (N6).
    read: Mapping[str, Agent] = field(default_factory=dict)


@dataclass(frozen=True)
class _Published:
    """What one generation is served from: its snapshot, narrowed, and its table.

    ``hidden`` is the addresses of the skills holding a hidden path, which the
    rewriter fails in every build (N13). ``source`` is the snapshot as it was
    handed to ``publish``, which a re-read narrows again, and ``live`` each live
    plugin's watch, by key.
    """

    snapshot: Snapshot
    table: Table
    hidden: frozenset[str] = frozenset()
    source: Snapshot | None = None
    live: Mapping[Key, _Watch] = field(default_factory=dict)


def holds_hidden(folder: Path) -> bool:
    """Whether ``folder`` holds a hidden path at any depth: a file or a folder
    whose name starts with ``.``. FastMCP reads a skill folder whole, so a skill
    holding one would serve it (N13)."""
    for _, dirnames, filenames in os.walk(folder):
        if any(name.startswith(".") for name in (*dirnames, *filenames)):
            return True
    return False


# The published state of the set the current request's build belongs to, and
# the ``SkillServing`` whose ``view()`` set it. It rests on one invariant: every
# rewrite kubed-mcp makes follows a view in the same context, in ``_pin``, so a
# pin left set after a build is never read by another build. kubed-mcp running a
# build in a task copied before the view, or a rewriter on read, would break it.
_PINNED: ContextVar[tuple[SkillServing, _Published] | None] = ContextVar(
    "kb_pinned_published", default=None
)


def entry_for(plugin: Plugin) -> dict[str, object]:
    """The marketplace entry kubed-mcp reads ``plugin`` with (``manifest=``).

    A marketplace entry as published, less ``source``, its ``strict`` kept. A
    declared plugin's is its name and the ``skills:`` folders it declares. No
    empty component list is added, so ``strict: false`` beside a ``plugin.json``
    is never refused for one -- except ``"agents": []`` for a bare plugin, which
    has no ``plugin.json`` and no entry, so there is nothing for it to conflict
    with, and which serves no agents (AGT-4).
    """
    if plugin.manifest_entry is not None:
        entry = dict(plugin.manifest_entry)
    else:
        entry = {"name": plugin.name}
        if plugin.globs.skills:
            entry["skills"] = list(plugin.globs.skills)
    if not plugin.claude_format:
        entry["agents"] = []
    return entry


HIDDEN = "skill {} holds a hidden file, which kubed-mcp would serve; not served"


def _address_of(uri: str) -> str:
    """A ``SKILL.md`` URI's skill address."""
    return unquote(uri[len(SCHEME) : -len(_ENTRY)])


class SkillServing:
    """Publishes kb's plugin set each generation, and is its view and rewriter."""

    def __init__(self, mcp: QuickMCP, knowledge_base: KnowledgeBase) -> None:
        self._mcp = mcp
        self._knowledge_base = knowledge_base
        self._published = _Published(knowledge_base.snapshot, {})
        # The generation being published, while its plugins enter the set.
        self._entering: _Published | None = None
        # One publisher at a time; a live re-read takes it too, never blocking.
        # Always taken after ``KnowledgeBase._lock``, never before it.
        self._lock = threading.Lock()
        # What the parity guard has said, so a refresh does not say it again.
        self._noted: set[str] = set()
        # While a set is staged: the live watches of the plugins kept unread,
        # and the agents ``agent_meta`` read for those added, by key and path.
        self._carried: dict[Key, _Watch] = {}
        self._reads: dict[Key, dict[str, Agent]] = {}

    def attach(self) -> None:
        """Register the view, the rewriter, the command reader and ``agent_meta``,
        then publish the current snapshot and every one after it."""
        self._mcp.plugin_view(self.view)
        self._mcp.add_rewriter(self.rewrite)
        self._mcp.command_reader(self.read_command)
        self._mcp.agent_meta(self.agent_meta)
        self._knowledge_base.serve_through(self.publish)

    # -- publishing ----------------------------------------------------------

    def publish(self, snapshot: Snapshot) -> Snapshot:
        """Serve ``snapshot``'s plugin set, and return it narrowed to what serves."""
        with self._lock:
            return self._publish(snapshot)

    def _publish(
        self,
        snapshot: Snapshot,
        moved: Mapping[Key, _Watch] | None = None,
        current: Mapping[Key, Served] | None = None,
    ) -> Snapshot:
        """Stage ``snapshot``'s set, serve it and return ``snapshot`` narrowed.

        A re-read (D9) passes the live plugins that ``moved``, with their new
        watches, and the plugins served now by key: every plugin served now that
        did not move is kept unread, and one whose re-read is refused is kept as
        it was, logged once.
        """
        catalogue = snapshot.catalogue
        by_id = {plugin.id: plugin for plugin in snapshot.plugins}
        libraries = snapshot.status.get("libraries", {})
        plugins = snapshot.status.get("plugins", {})
        skills: dict[tuple[str, str], list[str]] = {}
        found: dict[tuple[str, str], list[Skill]] = {}
        for skill in catalogue.visible_skills():
            skills.setdefault((skill.library, skill.plugin), []).append(skill.address)
            found.setdefault((skill.library, skill.plugin), []).append(skill)
        agents: dict[tuple[str, str], list[Agent]] = {}
        for agent in catalogue.agents.visible():
            agents.setdefault((agent.library, agent.plugin), []).append(agent)

        noted: set[str] = set()
        table: dict[tuple[str, str], _Row] = {}
        live: dict[Key, _Watch] = {}
        self._entering = _Published(snapshot, table)
        self._carried, self._reads = {}, {}
        staged = self._mcp.plugin_set()
        added: list[tuple[Library, Plugin, Served]] = []
        refused: dict[str, dict[str, str]] = {}
        # Each moved plugin re-added, with the root its watch was added from.
        readded: list[tuple[Path | None, Served]] = []
        try:
            for lib in snapshot.libraries:
                failed = libraries.get(lib.name, {}).get("conflicts", {})
                for pid in lib.plugins:
                    plugin = by_id.get(pid)
                    if plugin is None or pid in failed:
                        continue
                    if plugins.get(pid, {}).get("status") != "ok":
                        continue
                    # An agent kb's roster left unserved still counts: the
                    # plugin layer has to name it to say so.
                    own = (lib.name, pid)
                    if own not in skills and not plugins[pid].get("agents"):
                        continue
                    if plugin.globs.skills == ():
                        # kubed-mcp reads skills/ whatever an entry says, so a
                        # plugin serving none is not added, and nor are its agents.
                        self._note(
                            noted,
                            f"plugin {pid} in library {lib.name} serves no skills"
                            " (skills: []), so its agents are not served either",
                        )
                        continue
                    namespace = namespace_for(lib, plugin)
                    key = (namespace, plugin.address)
                    served_now = None if current is None else current.get(key)
                    if current is not None and served_now is None:
                        # Refused at publish, so not served: a re-read leaves
                        # it so, its conflict as it was (D9).
                        was = self._published.snapshot.status.get("libraries", {})
                        prior = was.get(lib.name, {}).get("conflicts", {}).get(pid)
                        if prior is not None:
                            refused.setdefault(lib.name, {})[pid] = prior
                        continue
                    before = table.get(key)
                    table[key] = _Row(lib.name, plugin, frozenset(lib.categories))
                    last = self._published.live.get(key)
                    watch: _Watch | None = None
                    try:
                        if served_now is not None and key not in (moved or {}):
                            # Not moved: carried as served, unread (D9), its
                            # agents as its last add read them.
                            watch = last
                            served = self._keep(staged, key, served_now, last)
                        else:
                            if moved is not None and key in moved:
                                watch = moved[key]
                            elif is_live(plugin.fetch):
                                # Stamped first, so what is added is what it says.
                                watch = self._watch(
                                    snapshot,
                                    plugin,
                                    found.get(own, ()),
                                    agents.get(own, ()),
                                )
                            served, kept = self._add(
                                staged, key, plugin, served_now, last, lib, noted
                            )
                            if moved is not None and key in moved and not kept:
                                readded.append((moved[key].root, served))
                            if watch is not None:
                                read = (
                                    self._reads.get(key, {})
                                    if not kept
                                    else ({} if last is None else last.read)
                                )
                                watch = replace(watch, read=read)
                    except (PluginError, ValueError) as exc:
                        # A refused add leaves the set as it was, and the table.
                        if before is None:
                            del table[key]
                        else:
                            table[key] = before
                        reason = f"conflict: {self._clean(str(exc), plugin)}"
                        refused.setdefault(lib.name, {})[pid] = reason
                        continue
                    if watch is not None:
                        live[key] = watch
                    added.append((lib, plugin, served))
        finally:
            self._entering = None
            self._carried, self._reads = {}, {}

        for root, served in readded:
            if not _same_folder(root, served.root):
                # Read from another export than the one it was added from: a
                # refresh moved the fetch under this re-read, and publishes it.
                raise _Abandoned
        published, hidden = self._narrowed(
            snapshot, added, refused, skills, agents, noted, live
        )
        # Before serve(): a build of the new set must find its own generation.
        # A serve that raises serves nothing new, so what was published stays.
        previous = self._published
        self._published = _Published(published, table, hidden, snapshot, live)
        try:
            self._mcp.serve(staged)
        except BaseException:
            self._published = previous
            raise
        self._noted = noted
        return published

    def _add(
        self,
        staged: PluginSet,
        key: Key,
        plugin: Plugin,
        served_now: Served | None,
        last: _Watch | None,
        lib: Library,
        noted: set[str],
    ) -> tuple[Served, bool]:
        """``plugin`` read and added to ``staged``, and False. On a re-read, a
        refused one is kept as served instead, said once, and True (D9)."""
        try:
            served = staged.add(
                plugin.address, namespace=key[0], manifest=entry_for(plugin)
            )
            return served, False
        except (PluginError, ValueError) as exc:
            if served_now is None:
                raise
            self._reads.pop(key, None)
            self._note(
                noted,
                f"plugin {plugin.id} in library {lib.name} was not read again, so"
                f" it serves what it served: {self._clean(str(exc), plugin)}",
            )
            return self._keep(staged, key, served_now, last), True

    def _keep(
        self, staged: PluginSet, key: Key, served_now: Served, last: _Watch | None
    ) -> Served:
        """``served_now`` carried into ``staged`` unread: ``agent_meta`` answers
        its live agents from ``last``, what its last add read."""
        if last is not None:
            self._carried[key] = last
        return staged.keep(served_now)

    def _root_of(self, plugin: Plugin) -> Path | None:
        """The folder ``plugin`` is served from now, or None."""
        tree = self._knowledge_base.served_tree(plugin.fetch.key)
        return None if tree is None else plugin_root(tree, plugin.subdir)

    def _watch(
        self,
        snapshot: Snapshot,
        plugin: Plugin,
        skills: Sequence[Skill],
        harvested: Sequence[Agent],
    ) -> _Watch:
        """A live ``plugin``'s root, skills and agent files, stamped now.

        The agent files are the ones ``snapshot`` harvested for it, its roster's
        paths: what its ``plugin.json`` or entry lists decides them, and a fresh
        glob of the config's ``agents:`` would miss a listed file and watch an
        ignored one."""
        root = self._root_of(plugin)
        agents = (
            tuple(agent.path for agent in harvested) if plugin.claude_format else ()
        )
        stamp = _stamp(snapshot, tuple(skills), agents)
        return _Watch(tuple(skills), agents, stamp, root)

    def _clean(self, text: str, plugin: Plugin) -> str:
        """A kubed-mcp message with no cache path and no credential in it."""
        tree = self._knowledge_base.served_tree(plugin.fetch.key)
        if tree is not None:
            for root in (plugin_root(tree, plugin.subdir), tree):
                if root is None:
                    continue
                text = unrooted(text, root)
                for base in (root.resolve(), root):
                    text = text.replace(str(base), plugin.address)
        return scrub(text)

    def _cleaned(self, text: str, plugins: Sequence[Plugin]) -> str:
        """``text`` with every served tree of ``plugins`` named by kb's address:
        each plugin's own root by its address, a fetch's tree by its key, the
        deepest first, so a path is named by the plugin it is under."""
        names: dict[str, str] = {}
        for plugin in plugins:
            tree = self._knowledge_base.served_tree(plugin.fetch.key)
            if tree is None:
                continue
            root = plugin_root(tree, plugin.subdir)
            for base, name in ((root, plugin.address), (tree, plugin.fetch.key)):
                if base is not None:
                    for spelling in (base.resolve(), base):
                        names.setdefault(str(spelling), name)
        for base in sorted(names, key=len, reverse=True):
            text = text.replace(base, names[base])
        return scrub(text)

    def _note(self, noted: set[str], message: str) -> None:
        noted.add(message)
        if message not in self._noted:
            log.warning("%s", message)

    def _narrowed(
        self,
        snapshot: Snapshot,
        added: list[tuple[Library, Plugin, Served]],
        refused: dict[str, dict[str, str]],
        skills: dict[tuple[str, str], list[str]],
        agents: dict[tuple[str, str], list[Agent]],
        noted: set[str],
        live: Mapping[Key, _Watch],
    ) -> tuple[Snapshot, frozenset[str]]:
        """``snapshot`` less what kubed-mcp does not serve, with its ``/health``
        reading what it does: the parity guard (D3, D11). Also the skills
        holding a hidden path, which kb does not let it serve (N13)."""
        catalogue = snapshot.catalogue
        folders = {s.address: s.path for s in catalogue.visible_skills()}
        hidden: set[str] = set()
        kept = {(lib.name, plugin.id) for lib, plugin, _ in added}
        gone: list[str] = []
        for (library, pid), addresses in skills.items():
            if (library, pid) not in kept:
                gone += addresses

        roster: list[Agent] = []
        # Every served agent name across the set, to its kb plugin id.
        owners: dict[str, str] = {}
        renamed: dict[str, dict[str, str]] = {}
        unserved: dict[str, list[dict[str, str]]] = {}
        for lib, plugin, served in added:
            mine = set(skills.get((lib.name, plugin.id), ()))
            theirs = {_address_of(uri) for uri in served.skills}
            for address in sorted(mine & theirs):
                if holds_hidden(folders[address]):
                    hidden.add(address)
                    gone.append(address)
                    self._note(noted, HIDDEN.format(address))
            for address in sorted(mine - theirs):
                gone.append(address)
                self._note(
                    noted,
                    f"skill {address} is not served: the plugin layer refused it",
                )
            for address in sorted(theirs - mine):
                # Its SKILL.md fails in the rewriter, which finds no such skill.
                self._note(noted, f"skill {address} is not served: kb did not find it")
            matched: set[str] = set()
            for file in served.agent_files:
                if file.renamed:
                    base = file.name.rpartition("@")[0]
                    renamed.setdefault(lib.name, {})[file.name] = (
                        f"{base} is already served by plugin '{owners.get(base, '?')}'"
                    )
                owners[file.name] = plugin.id
                # A live one as its add read it, which a re-read is for.
                watch = live.get((served.namespace, served.address))
                agent = (
                    watch.read.get(file.path)
                    if watch is not None
                    else catalogue.agent(lib.name, plugin.id, file.path)
                )
                if agent is None:
                    # One kb's harvest did not read, a nameless one say (N10):
                    # read as kb's roster reads one, its stem its name.
                    agent = _read_agent(
                        lib.name,
                        frozenset(lib.categories),
                        plugin,
                        served.root,
                        file.path,
                    )
                if agent is None:
                    self._note(
                        noted,
                        f"agent {file.name} ({file.path} of plugin {plugin.id}) is"
                        " served by the plugin layer, but kb cannot read it",
                    )
                    continue
                matched.add(file.path)
                roster.append(replace(agent, name=file.name))
            for path, why in served.skipped:
                taken = _RENAME_TAKEN.match(why)
                if taken is None:
                    continue
                matched.add(path)
                unserved.setdefault(lib.name, []).append(
                    {
                        "plugin": plugin.id,
                        "path": path,
                        "reason": f"{taken['name']} is already served by plugin"
                        f" '{owners.get(taken['name'], '?')}'",
                    }
                )
            for agent in agents.get((lib.name, plugin.id), ()):
                path = agent_path(agent)
                if path not in matched:
                    self._note(
                        noted,
                        f"agent {agent.name} ({path} of plugin {plugin.id}) is not"
                        " served: the plugin layer refused it",
                    )

        narrowed = catalogue.without(sorted(set(gone)), AgentRoster(roster))
        status_libraries = {}
        for name, entry in snapshot.status.get("libraries", {}).items():
            entry = dict(entry)
            if name in refused:
                entry["conflicts"] = {**entry.get("conflicts", {}), **refused[name]}
            entry["skills"] = sum(
                1 for s in narrowed.visible_skills() if s.library == name
            )
            entry["agents"] = sum(1 for a in roster if a.library == name)
            for key, found in (("renamed", renamed), ("unserved", unserved)):
                if found.get(name):
                    entry[key] = found[name]
                else:
                    entry.pop(key, None)
            status_libraries[name] = entry
        published = replace(
            snapshot,
            index=snapshot.index.without(gone),
            catalogue=narrowed,
            status={**snapshot.status, "libraries": status_libraries},
        )
        return published, frozenset(hidden)

    # -- the hooks -----------------------------------------------------------

    def view(self) -> View:
        """The plugins the request's scope admits, which is also the build key.

        The live ones among them are revalidated first, and re-read when they
        moved (D9). The request builds against the state taken before that
        re-read, and pins it for the rewriter; the next request reads the
        re-read (N6).
        """
        scope = requested_scope()
        published = self._published
        self._reread_live(scope)
        table = published.table
        admitted = frozenset(key for key, row in table.items() if row.admitted(scope))
        key = admitted or EMPTY
        _PINNED.set((self, published))

        def admits(plugin: Served) -> bool:
            return (plugin.namespace, plugin.address) in key

        return View(key, admits)

    def _reread_live(self, scope: Scope) -> None:
        """Revalidate the live plugins ``scope`` admits, and serve again with
        each one whose files moved read afresh (D9).

        Under the serving lock, taken without blocking: a publish holding it
        serves a new set anyway, so this request reads what is served. Never
        takes the knowledge base's lock, which a refresh holds while it waits
        for this one. kubed-mcp has pinned the request's state already, so the
        edit reads from the next request on (N6).
        """
        if not self._published.live:
            return
        if not self._lock.acquire(blocking=False):
            return
        try:
            published = self._published
            source = published.source
            # A publish is served and not yet swapped in: leave it to land.
            if (
                source is None
                or self._knowledge_base.snapshot is not published.snapshot
            ):
                return
            moved: dict[Key, _Watch] = {}
            for key, watch in published.live.items():
                row = published.table.get(key)
                if row is None or not row.admitted(scope):
                    continue
                stamp = _stamp(source, watch.skills, watch.agents)
                if stamp != watch.stamp:
                    moved[key] = replace(watch, stamp=stamp)
            if not moved:
                return
            for key, watch in moved.items():
                if self._root_of(published.table[key].plugin) != watch.root:
                    # A refresh has moved the fetch to a new export and will
                    # publish it: adding from it now would mix two trees.
                    return
            current = {(p.namespace, p.address): p for p in self._mcp.plugins}
            try:
                narrowed = self._publish(source, moved, current)
            except _Abandoned:
                # Nothing served and nothing recorded: the refresh publishes.
                return
            except Exception as exc:  # noqa: BLE001 - a failed re-read serves what is served
                plugins = [row.plugin for row in published.table.values()]
                message = self._cleaned(str(exc), plugins)
                log.warning("re-reading live plugins failed: %s", message)
                # Not tried again until a file moves again.
                self._published = replace(published, live={**published.live, **moved})
                return
            self._knowledge_base.renarrowed(published.snapshot, narrowed)
        finally:
            self._lock.release()

    def rewrite(self, site: Site, text: str) -> str:
        """kb's rewriting: a root ``SKILL.md`` and an agent's body rendered, and
        every text file of a skill with LF line endings (SKL-22); anything else
        as written. Against the state its request's view pinned, else the
        current one."""
        pinned = _PINNED.get()
        published = (
            pinned[1] if pinned is not None and pinned[0] is self else self._published
        )
        row = published.table.get((site.namespace, site.plugin.address))
        if row is None:
            return text
        catalogue = published.snapshot.catalogue
        if site.kind == "skill":
            # SKL-22: every text file of a skill reads with LF line endings.
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            if not site.uri.endswith(_ENTRY):
                return text
            root = site.uri[: -len(_ENTRY)]
            if root not in site.skills.values():
                return text
            address = unquote(root[len(SCHEME) :])
            if address in published.hidden:
                # Fails the whole skill, in every build (PLUG-59): N13.
                raise ValueError(f"skill {address} holds a hidden file")
            if published.snapshot.index.get(address) is None:
                # One kb's harvest did not find, so never vetted for N13: fail
                # closed, as for a hidden one. The parity guard said why, once.
                raise ValueError(f"skill {address} is not one kb found")
            return catalogue.instructions(address, text, requested_scope())
        if site.kind == "agent":
            head, body = split_frontmatter(text)
            if not head:
                return text
            return head + catalogue.agent_instructions(
                row.library, row.plugin.id, body, requested_scope()
            )
        return text

    def read_command(self, text: str, path: str, name: str, plugin: Served) -> str:
        """Skip every command (PLUG-62): kb's prompts are kb's until K4."""
        return COMMANDS_ARE_KBS

    def agent_meta(self, name: str, plugin: Served) -> dict | None:
        """kb's ``io.kubed.mcp-kb/agent`` for an agent entering the set."""
        published = self._entering or self._published
        row = published.table.get((plugin.namespace, plugin.address))
        if row is None:
            return None
        path = next((f.path for f in plugin.agent_files if f.name == name), None)
        if path is None:
            return None
        catalogue = published.snapshot.catalogue
        read = None
        if is_live(row.plugin.fetch):
            key = (plugin.namespace, plugin.address)
            carried = self._carried.get(key)
            if carried is not None:
                # Kept unread: as its last add read it.
                read = carried.read.get(path)
            else:
                # Added: what the file says now, which a re-read is for (N6).
                read = _read_agent(
                    row.library, row.library_categories, row.plugin, plugin.root, path
                )
                if read is not None:
                    self._reads.setdefault(key, {})[path] = read
            if read is None:
                raise ValueError(f"kb cannot read agent file {path}")
        value = catalogue.agent_meta(row.library, row.plugin.id, path, read)
        if value is None:
            read = _read_agent(
                row.library, row.library_categories, row.plugin, plugin.root, path
            )
            if read is None:
                # kb cannot say what this agent is, so the set skips it (PLUG-73).
                raise ValueError(f"kb cannot read agent file {path}")
            value = catalogue.agent_meta(row.library, row.plugin.id, path, read)
        served = set(plugin.skills)
        value["skills"] = {k: v for k, v in value["skills"].items() if v in served}
        return {AGENT_META: value}


class _Abandoned(Exception):
    """A re-read that read a moved plugin from another export: not served."""


def _same_folder(recorded: Path | None, read: Path) -> bool:
    """Whether the folder a plugin was read from is the one recorded."""
    if recorded is None:
        return False
    try:
        return Path(read).resolve() == recorded.resolve()
    except OSError:
        return False


def _stamp(
    snapshot: Snapshot, skills: Sequence[Skill], agents: Sequence[Path]
) -> tuple:
    """What a live plugin's ``skills`` and ``agents`` files hold on disk now,
    each revalidated first (SKL-37)."""
    catalogue = snapshot.catalogue
    parts: list[tuple] = [catalogue.live_stamp(skill) for skill in skills]
    for path in agents:
        snapshot.revalidate(path)
        try:
            stat = path.stat()
        except OSError:
            parts.append((str(path),))
            continue
        parts.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(parts)


def _read_agent(
    library: str,
    library_categories: frozenset[str],
    plugin: Plugin,
    root: Path,
    path: str,
) -> Agent | None:
    """An agent file kb's harvest did not read, read as its roster reads one,
    with the file's stem as the name its frontmatter does not give (N10); None
    when kb cannot read it. Named by the plugin layer, whose name replaces it.

    Only a regular file inside ``root``, as kb's harvest reads one: a symlink
    out of the plugin is refused here whatever the plugin layer lists, so
    ``agent_meta`` raises and the set skips it (PLUG-73)."""
    if readable(root, path) is None:
        return None
    try:
        parsed = parse_agent(root / path, stem=Path(path).stem)
    except OSError:
        return None
    if isinstance(parsed, str):
        return None
    return Agent(
        name=parsed.name,
        library=library,
        plugin=plugin.id,
        root=root,
        path=root / path,
        parsed=parsed,
        servers=plugin.servers,
        category=plugin.category,
        tags=plugin.labels,
        library_categories=library_categories,
        live=is_live(plugin.fetch),
    )
