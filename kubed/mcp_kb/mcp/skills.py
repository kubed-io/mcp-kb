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
once. A plugin kubed-mcp refuses is a conflict in its library, as LIB-28's are.

The rewriter and ``agent_meta`` read the snapshot being published, held here
and set before ``serve()``: a build made between ``serve()`` and the swap in
``KnowledgeBase`` must already see the generation it is a build of.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote

from kubed.mcp import QuickMCP
from kubed.mcp.plugins import Plugin as Served
from kubed.mcp.plugins import PluginError, Site, View

from ..catalogue.agents import Agent, AgentRoster, parse_agent
from ..catalogue.names import split_frontmatter
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


# Each added plugin by ``(namespace, address)``: what kubed-mcp's ``Plugin``
# carries. ``(library, address)`` alone is not unique: grafana's root entries
# share one address, each with its own category, and so do declared plugins
# reading different folders of one tree.
Table = Mapping[tuple[str, str], _Row]


@dataclass(frozen=True)
class _Published:
    """What one generation is served from: its snapshot, narrowed, and its table.

    ``hidden`` is the addresses of the skills holding a hidden path, which the
    rewriter fails in every build (N13).
    """

    snapshot: Snapshot
    table: Table
    hidden: frozenset[str] = frozenset()


def holds_hidden(folder: Path) -> bool:
    """Whether ``folder`` holds a hidden path at any depth: a file or a folder
    whose name starts with ``.``. FastMCP reads a skill folder whole, so a skill
    holding one would serve it (N13)."""
    for _, dirnames, filenames in os.walk(folder):
        if any(name.startswith(".") for name in (*dirnames, *filenames)):
            return True
    return False


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
        # One publisher at a time; a live re-read (Task 6) takes it too.
        self._lock = threading.Lock()
        # What the parity guard has said, so a refresh does not say it again.
        self._noted: set[str] = set()

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

    def _publish(self, snapshot: Snapshot) -> Snapshot:
        catalogue = snapshot.catalogue
        by_id = {plugin.id: plugin for plugin in snapshot.plugins}
        libraries = snapshot.status.get("libraries", {})
        plugins = snapshot.status.get("plugins", {})
        skills: dict[tuple[str, str], list[str]] = {}
        for skill in catalogue.visible_skills():
            skills.setdefault((skill.library, skill.plugin), []).append(skill.address)
        agents: dict[tuple[str, str], list[Agent]] = {}
        for agent in catalogue.agents.visible():
            agents.setdefault((agent.library, agent.plugin), []).append(agent)

        noted: set[str] = set()
        table: dict[tuple[str, str], _Row] = {}
        self._entering = _Published(snapshot, table)
        staged = self._mcp.plugin_set()
        added: list[tuple[Library, Plugin, Served]] = []
        refused: dict[str, dict[str, str]] = {}
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
                    before = table.get(key)
                    table[key] = _Row(lib.name, plugin, frozenset(lib.categories))
                    try:
                        served = staged.add(
                            plugin.address,
                            namespace=namespace,
                            manifest=entry_for(plugin),
                        )
                    except (PluginError, ValueError) as exc:
                        # A refused add leaves the set as it was, and the table.
                        if before is None:
                            del table[key]
                        else:
                            table[key] = before
                        reason = f"conflict: {self._clean(str(exc), plugin)}"
                        refused.setdefault(lib.name, {})[pid] = reason
                        continue
                    added.append((lib, plugin, served))
        finally:
            self._entering = None

        published, hidden = self._narrowed(
            snapshot, added, refused, skills, agents, noted
        )
        # Before serve(): a build of the new set must find its own generation.
        # A serve that raises serves nothing new, so what was published stays.
        previous = self._published
        self._published = _Published(published, table, hidden)
        try:
            self._mcp.serve(staged)
        except BaseException:
            self._published = previous
            raise
        self._noted = noted
        return published

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
                self._note(
                    noted,
                    f"skill {address} is served by the plugin layer, but kb did"
                    " not find it",
                )
            matched: set[str] = set()
            for file in served.agent_files:
                if file.renamed:
                    base = file.name.rpartition("@")[0]
                    renamed.setdefault(lib.name, {})[file.name] = (
                        f"{base} is already served by plugin '{owners.get(base, '?')}'"
                    )
                owners[file.name] = plugin.id
                agent = catalogue.agent(lib.name, plugin.id, file.path)
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
        """The plugins the request's scope admits, which is also the build key."""
        scope = requested_scope()
        table = self._published.table
        admitted = frozenset(key for key, row in table.items() if row.admitted(scope))
        key = admitted or EMPTY

        def admits(plugin: Served) -> bool:
            return (plugin.namespace, plugin.address) in key

        return View(key, admits)

    def rewrite(self, site: Site, text: str) -> str:
        """kb's rewriting: a root ``SKILL.md`` and an agent's body rendered, and
        every text file of a skill with LF line endings (SKL-22); anything else
        as written."""
        published = self._published
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
        value = catalogue.agent_meta(row.library, row.plugin.id, path)
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


def _read_agent(
    library: str,
    library_categories: frozenset[str],
    plugin: Plugin,
    root: Path,
    path: str,
) -> Agent | None:
    """An agent file kb's harvest did not read, read as its roster reads one,
    with the file's stem as the name its frontmatter does not give (N10); None
    when kb cannot read it. Named by the plugin layer, whose name replaces it."""
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
