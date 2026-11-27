"""kb's skills, agents and prompts, served by kubed-mcp's plugin layer (K3, K4).

Each generation kb publishes a plugin set: every plugin of every library, in
config order and each library's plugin order, added as itself under its
library's namespace (``snapshot.namespace_for``) from kb's own address, through
the served-tree loader. kubed-mcp then serves each skill's files, its
``_manifest``, the Skills extension's entries and the folders inside a skill,
the plugins' agents through its agents extension, and their commands as MCP
prompts. kb keeps its indexes, ``_files.md``, library files and fallbacks.

Four hooks make what kubed-mcp serves kb's:

- **The view** is kb's scope: the set of plugins a request's scope admits, as
  ``(namespace, address)`` pairs, which is also the build key. Every scope that
  admits nothing shares ``EMPTY``.
- **The rewriter** is kb's text rewriting, applied when a build is made, never
  on a read: a root ``SKILL.md`` through ``Catalogue.instructions``, and an
  agent's or a command's body through ``Catalogue.agent_instructions``. Every
  other file is served as written. The gateway prefix is kubed-mcp's writer,
  after it.
- **``read_command``** is kb's dialect reader. Each entry kb hands the layer
  names its ``commands`` as exactly kb's selection of prompt files
  (``harvest.command_entries``), and the reader holds the layer to it: a file
  kb did not select is skipped, and so is one the layer names otherwise than
  kb does (D2). Every other file is parsed in the dialect ``dialect_of``
  decides at the read, and a build re-reads its rewritten text in that same
  dialect (D3).
- **``agent_meta``** adds kb's ``io.kubed.mcp-kb/agent`` key to an agent's
  ``_meta``, its ``frontmatter`` read through kubed-mcp's own ``parse_agent``
  (``_frontmatter``), so kb parses no agent itself. It is kb's veto too: it
  raises for a file that is not a regular file inside the plugin root, at the
  path ``readable`` resolves, or that kb's harvest did not find (D4), and the
  set skips that agent. It never sees a scope, so its ``skills`` names the
  agent's own plugin's skills alone (N9).

**The parity guard.** After the set is staged, kb's catalogue is narrowed to
what kubed-mcp reports serving -- each added plugin's ``skills`` URIs -- so no
index, hint, listing or rewritten name points at a skill that does not read.
Anything either side has alone is logged once, and a skill only kubed-mcp found
is failed in the rewriter, so it is not served either: kb never vetted it; an
agent file only kubed-mcp found is refused in ``agent_meta`` alike (D4). The
agents served are each added plugin's ``agent_files``. A plugin kubed-mcp
refuses is a conflict in its library, as LIB-28's are. kb's prompts are what
the reader read as the set was staged, kept to the names kubed-mcp serves (D5).

``/health`` reads what the layer serves (K6). Each ``ok`` plugin's skills,
prompts and agents are counted from the first library that adds it, and are 0
when none does: refused, failed in every library, or ``skills: []``. Its
``skipped`` is kb's own rows, then the layer's for each skill folder, selected
prompt file and agent file kb found and the layer did not serve, one row per
path with the first reason. ``log_changes`` logs each row once, so the parity
guard does not say a skill whose folder has one, and ``QuietSelection`` keeps
the layer's own line for it out of the log; a skill folder or agent file the
layer skips that kb never found is said once in its place (``_unlisted``).

The rewriter and the reader read the published state its request's view
pinned, so a build of one set never reads the next one's, whether a re-read, a
refresh or a ``serve()`` that raises swaps it meanwhile; a build no view pinned
reads the state published now. While a set is staged, ``agent_meta``, the
reader and the rewriter read the generation entering it (``_reading``, D6). The
published state is set before ``serve()``: a build made between ``serve()`` and
the swap in ``KnowledgeBase`` must already see the generation it is a build of.
One window is left. kb swaps its state before ``serve()`` and kubed-mcp swaps
its own inside it, so a request that reads kubed-mcp's state before kubed-mcp
swaps it and kb's after kb swaps it pins N and N+1, and builds N against N+1.
The other way round is a publish on a worker thread that makes both swaps
between the view reading kb's state and kubed-mcp taking its own, which it does
after the view (0.4.2), and builds N+1 against N. If that
``serve()`` then raises, kubed-mcp keeps the build until the next publish that
serves. Either order of the swaps leaves such a window. Closing it needs
kubed-mcp to hand the pinned generation to the view and on ``Site``.

**A live plugin is re-read on view (D9).** What a live plugin's skill, agent and
prompt files held on disk is stamped as it enters the set. The view revalidates the
live plugins its request's scope admits and stamps them again; a plugin whose
stamp moved is added again, every other one is kept as served, and the set is
served and kb's catalogue narrowed afresh, under the generation it already had.
The view re-reads before it pins kb's state, and kubed-mcp takes its own state
after the view (0.4.2), so the request whose view re-reads a moved plugin reads
the re-read, its pin for the rewriter included (SKL-37, N6).
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import unquote

from kubed.mcp import Prompt, QuickMCP
from kubed.mcp.agents import META_KEY, parse_agent
from kubed.mcp.plugins import Plugin as Served
from kubed.mcp.plugins import PluginError, PluginSet, Site, View

from ..catalogue.agents import ServedAgent
from ..catalogue.harvest import readable
from ..catalogue.names import split_frontmatter
from ..catalogue.prompts import (
    READ_ERRORS,
    FilePrompt,
    dialect_of,
    parse_prompt,
    prompt_name,
)
from ..catalogue.skills import Skill
from ..catalogue.snapshot import (
    Library,
    PluginCommands,
    Snapshot,
    log_changes,
    namespace_for,
    unrooted,
)
from ..catalogue.uris import AGENT_META, MAIN_FILE, SCHEME
from ..config import scrub
from ..plugins import Plugin
from ..sources import plugin_root
from ..sources.live import is_live
from .prompts import adapt
from .request import requested_scope
from .scope import Scope

if TYPE_CHECKING:
    from ..server import KnowledgeBase

log = logging.getLogger(__name__)

# The key of every view that admits nothing, shared so no bogus scope makes one.
EMPTY: frozenset[tuple[str, str]] = frozenset()
# Why the reader skips a command file (D2): one kb's harvest did not select, and
# one the plugin layer names otherwise than kb does.
NOT_SELECTED = "not one of the plugin's prompt files"
RENAMED = "named {name} by the plugin layer and {expected} by kb"
# The plugin layer's line for a skipped command file, which ``QuietSelection``
# keeps out of the log: for ``NOT_SELECTED`` a file kb left out (P8), and for any
# other reason one kb lists in the plugin's ``skipped`` and logs itself (D6).
_SKIP_LINE = "prompt %s is skipped: %s"
# The plugin layer's lines for every other skip kb lists and logs itself, or
# says once (D6), by logger: each a template with the number of args it takes,
# matched as written, never by the formatted text, which quotes a cache path. A
# skills folder's nested ``SKILL.md`` (a note kb does not read) is not here.
_QUIET: Mapping[str, Mapping[str, int]] = {
    "kubed.mcp.plugins": {
        _SKIP_LINE: 2,
        "agent file %s is skipped: %s": 2,
        "plugin %s: agent file %s is skipped: %s": 3,
        "%s is already served by %s; %s is skipped": 3,
        "plugin %s: %s is skipped, served already": 2,
        # An agent kb's ``agent_meta`` refused: a row of its plugin's for a file
        # kb found, else ``_agents_of``'s note (D4).
        "plugin %s: agent_meta failed on agent %s, so it is not served: %s": 3,
    },
    "kubed.mcp.skills": {
        "skill at %s is not a valid Agent Skill, so it is not served: %s": 2,
    },
}

_ENTRY = f"/{MAIN_FILE}"
# kubed-mcp's reason for an agent whose rename is taken (PLUG-64).
_RENAME_TAKEN = re.compile(r"^agent (?P<name>\S+) is already served by plugin .+$")
# kubed-mcp's prefix for an agent ``agent_meta`` refused (PLUG-73): the only way a
# file it read is skipped for kb's sake, and how kb tells an agent's skip from a
# prompt's or a skill's for a path kb never found.
_AGENT_META_FAILED = "agent_meta failed: "


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
    """A live plugin's skills, agent files and prompt files, and what they held
    on disk when it entered the set (D9)."""

    skills: tuple[Skill, ...]
    agents: tuple[Path, ...]
    stamp: tuple
    # The folder the plugin was added from: a refresh points its fetch at a
    # new export before it publishes, and a re-read must not add from that.
    root: Path | None = None
    # Its selected prompt files, as paths under ``root`` (D7).
    commands: tuple[Path, ...] = ()


@dataclass(frozen=True)
class _Published:
    """What one generation is served from: its snapshot, narrowed, and its table.

    ``source`` is the snapshot as it was handed to ``publish``, which a re-read
    narrows again, and ``live`` each live plugin's watch, by key.
    """

    snapshot: Snapshot
    table: Table
    source: Snapshot | None = None
    live: Mapping[Key, _Watch] = field(default_factory=dict)
    # What the reader made of each added plugin's prompt files as it entered
    # the set, by key and then root-relative path, in read order (D5).
    prompts: Mapping[Key, Mapping[str, FilePrompt]] = field(default_factory=dict)
    # The frontmatter ``agent_meta`` read for each added plugin's agents as it
    # entered the set, by key and then root-relative path: what a plugin kept
    # unread answers from, live or not (D9, AGT-16).
    agent_reads: Mapping[Key, Mapping[str, Mapping[str, object]]] = field(
        default_factory=dict
    )


# The published state of the set the current request's build belongs to, and
# the ``SkillServing`` whose ``view()`` set it. It rests on one invariant: every
# rewrite kubed-mcp makes follows a view in the same context, in ``_pin``, so a
# pin left set after a build is never read by another build. kubed-mcp running a
# build in a task copied before the view, or a rewriter on read, would break it.
_PINNED: ContextVar[tuple[SkillServing, _Published] | None] = ContextVar(
    "kb_pinned_published", default=None
)
# The generation a ``SkillServing`` is staging, while its plugins enter the set
# (D6). A context, not a field: a publish on a worker thread must not make a
# build on the loop read the generation being staged, and a live re-read stages
# inside a request whose view has set ``_PINNED``.
_ENTERING: ContextVar[tuple[SkillServing, _Published] | None] = ContextVar(
    "kb_entering_published", default=None
)


def entry_for(
    plugin: Plugin, commands: PluginCommands | None = None
) -> dict[str, object]:
    """The marketplace entry kubed-mcp reads ``plugin`` with (``manifest=``).

    A marketplace entry as published, less ``source``, its ``strict`` kept. A
    declared plugin's is its name and the ``skills:`` folders it declares. No
    empty component list is added, so ``strict: false`` beside a ``plugin.json``
    is never refused for one -- except ``"agents": []`` for a bare plugin, which
    has no ``plugin.json`` and no entry, so there is nothing for it to conflict
    with, and which serves no agents (AGT-4).

    Given its ``commands``, they are the entry's ``commands``, replacing its
    own: the paths that read exactly kb's selection of prompt files, each
    written ``./``-relative as Claude requires (D1). ``strict: false`` then has
    nothing left to decide -- kb never adds a plugin whose entry names
    components beside a ``plugin.json`` (LIB-31) -- so it is dropped, and the
    conventions reach the layer beside a ``plugin.json`` too.
    """
    if plugin.manifest_entry is not None:
        entry = dict(plugin.manifest_entry)
    else:
        entry = {"name": plugin.name}
        if plugin.globs.skills:
            entry["skills"] = list(plugin.globs.skills)
    if not plugin.claude_format:
        entry["agents"] = []
    if commands is not None:
        entry["commands"] = [
            "./" if path == "." else f"./{path}" for path in commands.entries
        ]
        if entry.get("strict") is False:
            del entry["strict"]
    return entry


class QuietSelection(logging.Filter):
    """Keeps the plugin layer's line for a skip kb reports out of the log (P8, D6).

    A command folder kb hands the layer can hold files kb's selection leaves out
    on purpose, and the layer logs each one it skips at WARNING on every read,
    which buries the warnings worth reading (P8). Every other skill folder,
    command file and agent file the layer skips is a row of its plugin's
    ``skipped``, which ``log_changes`` logs once, its path written with ``%r``
    and no cache path in it, or else a line kb says once (``_unlisted``). So
    this drops the layer's own line for each of those skips (``_QUIET``),
    matched on its template and the number of its args, and each such skip
    logs one line, kb's. The skip is still in the layer's own record.

    Two kinds of skip are now said by nobody. A file kb did not select that the
    layer skips before kb's reader sees it -- at an index's name, with an
    unusable name, or unreadable -- is left out on purpose, as ``NOT_SELECTED``
    is (P8). And a plugin the layer refuses in every library (LIB-29) has no
    served plugin to take rows from, so the skips it met before the refusal
    are not said; its library's conflict line says it serves nothing.
    """

    LOGGERS = tuple(_QUIET)

    def filter(self, record: logging.LogRecord) -> bool:
        msg, args = record.msg, record.args
        if not isinstance(msg, str):
            return True
        arity = _QUIET.get(record.name, {}).get(msg)
        return not (
            arity is not None and isinstance(args, tuple) and len(args) == arity
        )

    @classmethod
    def install(cls) -> None:
        """Add the filter to each of the plugin layer's loggers, once per process."""
        for name in cls.LOGGERS:
            logger = logging.getLogger(name)
            if not any(isinstance(f, cls) for f in logger.filters):
                logger.addFilter(cls())


def _address_of(uri: str) -> str:
    """A ``SKILL.md`` URI's skill address."""
    return unquote(uri[len(SCHEME) : -len(_ENTRY)])


class SkillServing:
    """Publishes kb's plugin set each generation, and is its view and rewriter."""

    def __init__(self, mcp: QuickMCP, knowledge_base: KnowledgeBase) -> None:
        self._mcp = mcp
        self._knowledge_base = knowledge_base
        self._published = _Published(knowledge_base.snapshot, {})
        # One publisher at a time; a live re-read takes it too, never blocking.
        # Always taken after ``KnowledgeBase._lock``, never before it.
        self._lock = threading.Lock()
        # What the parity guard has said, so a refresh does not say it again.
        self._noted: set[str] = set()
        # While a set is staged: the agent frontmatter each plugin kept unread
        # was published with, and what ``agent_meta`` read for those added, by
        # key and path, and the prompts ``read_command`` read for them alike.
        self._carried: dict[Key, Mapping[str, Mapping[str, object]]] = {}
        self._reads: dict[Key, dict[str, Mapping[str, object]]] = {}
        self._prompt_reads: dict[Key, dict[str, FilePrompt]] = {}

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

        noted: set[str] = set()
        table: dict[tuple[str, str], _Row] = {}
        live: dict[Key, _Watch] = {}
        # What each plugin in the set was read as: this publish's reads for one
        # added, and what it was published with for one kept (D5).
        prompts: dict[Key, Mapping[str, FilePrompt]] = {}
        agent_reads: dict[Key, Mapping[str, Mapping[str, object]]] = {}
        entering = _ENTERING.set((self, _Published(snapshot, table)))
        self._carried, self._reads, self._prompt_reads = {}, {}, {}
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
                    # Any agent file kb found counts: the plugin layer is the
                    # one to read it, and to say whether it serves.
                    own = (lib.name, pid)
                    commands = snapshot.commands.get(pid)
                    has_agents = bool(snapshot.agent_files.get(pid))
                    has_prompts = commands is not None and bool(commands.selected)
                    if own not in skills and not has_agents and not has_prompts:
                        continue
                    if plugin.globs.skills == ():
                        # kubed-mcp reads skills/ whatever an entry says, so a
                        # plugin serving none is not added, and nor are its
                        # agents and prompts (LIB-33).
                        lost = " and ".join(
                            kind
                            for kind, has in (
                                ("agents", has_agents),
                                ("prompts", has_prompts),
                            )
                            if has
                        )
                        self._note(
                            noted,
                            f"plugin {pid} in library {lib.name} serves no skills"
                            f" (skills: []), so its {lost} are not served either",
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
                    # What its agents were published with, if it is served now.
                    read = self._published.agent_reads.get(key, {})
                    watch: _Watch | None = None
                    # Kept as served: what it was published with stands.
                    kept = True
                    try:
                        if served_now is not None and key not in (moved or {}):
                            # Not moved: carried as served, unread (D9), its
                            # agents as its last add read them.
                            watch = last
                            served = self._keep(staged, key, served_now, read)
                        else:
                            if moved is not None and key in moved:
                                watch = moved[key]
                            elif is_live(plugin.fetch):
                                # Stamped first, so what is added is what it says.
                                watch = self._watch(
                                    snapshot,
                                    plugin,
                                    found.get(own, ()),
                                    commands,
                                )
                            self._prompt_reads.pop(key, None)
                            served, kept = self._add(
                                staged,
                                key,
                                plugin,
                                served_now,
                                read,
                                lib,
                                noted,
                                commands,
                            )
                            if moved is not None and key in moved and not kept:
                                readded.append((moved[key].root, served))
                    except (PluginError, ValueError) as exc:
                        # A refused add leaves the set as it was, and the table.
                        if before is None:
                            del table[key]
                        else:
                            table[key] = before
                        reason = (
                            f"conflict: {self._refusal(exc, plugin, _root(served_now))}"
                        )
                        refused.setdefault(lib.name, {})[pid] = reason
                        continue
                    if watch is not None:
                        live[key] = watch
                    # Added: this add's reads alone, none when no file read,
                    # never a generation's before it (PRM-60).
                    prompts[key] = (
                        self._published.prompts.get(key, {})
                        if kept
                        else self._prompt_reads.get(key, {})
                    )
                    agent_reads[key] = read if kept else self._reads.get(key, {})
                    added.append((lib, plugin, served))
        finally:
            _ENTERING.reset(entering)
            self._carried, self._reads, self._prompt_reads = {}, {}, {}

        for root, served in readded:
            if not _same_folder(root, served.root):
                # Read from another export than the one it was added from: a
                # refresh moved the fetch under this re-read, and publishes it.
                raise _Abandoned
        published = self._narrowed(
            snapshot, added, refused, skills, noted, prompts, found
        )
        # Before serve(): a build of the new set must find its own generation.
        # A serve that raises serves nothing new, so what was published stays.
        previous = self._published
        self._published = _Published(
            published, table, snapshot, live, prompts, agent_reads
        )
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
        read: Mapping[str, Mapping[str, object]],
        lib: Library,
        noted: set[str],
        commands: PluginCommands | None = None,
    ) -> tuple[Served, bool]:
        """``plugin`` read and added to ``staged``, and False. On a re-read, a
        refused one is kept as served instead, its agents as ``read`` gives
        them, said once, and True (D9)."""
        try:
            if served_now is not None:
                # A re-read: a file the plugin served that no longer reads would
                # leave it serving less, so the plugin keeps its build (D7).
                self._vet(
                    served_now,
                    _Row(lib.name, plugin, frozenset(lib.categories)),
                    self._root_of(plugin),
                    commands,
                )
            served = staged.add(
                plugin.address,
                namespace=key[0],
                manifest=entry_for(plugin, commands),
            )
            return served, False
        except (PluginError, ValueError) as exc:
            self._prompt_reads.pop(key, None)
            if served_now is None:
                raise
            self._reads.pop(key, None)
            reason = self._clean(str(exc), plugin, served_now.root)
            self._note(
                noted,
                f"plugin {plugin.id} in library {lib.name} was not read again, so"
                f" it serves what it served: {reason}",
            )
            return self._keep(staged, key, served_now, read), True

    def _vet(
        self,
        served_now: Served,
        row: _Row,
        root: Path | None,
        commands: PluginCommands | None = None,
    ) -> None:
        """Raise ``ValueError`` when a prompt file ``served_now`` serves does not
        read now, in the dialect its text says (PRM-59, PRM-60), or an agent file
        it serves does not read as an agent (AGT-16).

        Only the first read of each name it serves, as ``_prompts_of`` keeps
        them: a file that lost its name to another served nothing to keep."""
        # Not _reading(): on a re-read that is the entering state, whose prompts
        # are still empty; ``_published`` is what is being replaced (D6).
        key = (served_now.namespace, served_now.address)
        names = set(served_now.prompts)
        for path, last in self._published.prompts.get(key, {}).items():
            if last.name not in names:
                continue
            names.discard(last.name)
            try:
                if root is None:
                    raise OSError("the plugin's tree is not served")
                text = (root / path).read_text(encoding="utf-8")
                parse_prompt(
                    text,
                    root / path,
                    name=last.name,
                    library=row.library,
                    plugin=row.plugin.id,
                    dialect=dialect_of(
                        path,
                        configured=row.plugin.dialect,
                        claude=() if commands is None else commands.claude,
                    ),
                )
            except (OSError, UnicodeDecodeError, *READ_ERRORS) as exc:
                reason = self._clean(str(exc) or type(exc).__name__, row.plugin, root)
                raise ValueError(f"prompt {path}: {reason}") from exc
        # Every agent it serves, read as ``agent_meta`` reads it: one that no
        # longer reads would be skipped by the add, or lose its name (AGT-16).
        for file in served_now.agent_files:
            if root is None:
                raise ValueError(f"agent {file.path}: the plugin's tree is not served")
            try:
                _frontmatter(root, file.path)
            except ValueError as exc:
                message = str(exc)
                reason = (
                    message.removeprefix(f"agent file {file.path}: ")
                    if message.startswith("agent file ")
                    else "kb cannot read it"
                )
                reason = self._clean(reason, row.plugin, root)
                raise ValueError(f"agent {file.path}: {reason}") from exc

    def _keep(
        self,
        staged: PluginSet,
        key: Key,
        served_now: Served,
        read: Mapping[str, Mapping[str, object]],
    ) -> Served:
        """``served_now`` carried into ``staged`` unread: ``agent_meta`` answers
        its agents from ``read``, what its last add read, never from disk -- a
        ``file://`` tree is served in place, and an edit to it is a refresh's."""
        self._carried[key] = read
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
        commands: PluginCommands | None = None,
    ) -> _Watch:
        """A live ``plugin``'s root, skills, agent files and prompt files, stamped now.

        The agent files are the ones ``snapshot`` harvested for it
        (``agent_files``): what its ``plugin.json`` or entry lists decides them,
        and a fresh glob of the config's ``agents:`` would miss a listed file and
        watch an ignored one."""
        root = self._root_of(plugin)
        agents = (
            tuple(root / rel for rel in snapshot.agent_files.get(plugin.id, ()))
            if root is not None and plugin.claude_format
            else ()
        )
        prompts = (
            ()
            if root is None or commands is None
            else tuple(root / path for path in commands.selected)
        )
        stamp = _stamp(snapshot, tuple(skills), (*agents, *prompts))
        return _Watch(tuple(skills), agents, stamp, root, commands=prompts)

    def _clean(self, text: str, plugin: Plugin, read_from: Path | None = None) -> str:
        """A kubed-mcp message with no cache path and no credential in it.

        ``read_from`` is the root the layer read ``plugin`` at, its ``Served.root``.
        A refresh assigns a fetch's new export before it publishes, and a live
        re-read in that window reads one tree while ``served_tree`` answers the
        next, so the layer's reasons quote a root kb no longer serves (HTTP-11)."""
        for root, _tree in self._roots(plugin, read_from):
            text = unrooted(text, root)
            for base in (root.resolve(), root):
                text = text.replace(str(base), plugin.address)
        return scrub(text)

    def _roots(
        self, plugin: Plugin, read_from: Path | None = None
    ) -> list[tuple[Path, bool]]:
        """Each root a message about ``plugin`` may quote, and whether it is a
        fetch's tree rather than the plugin's own root: the one the layer read it
        at and the one served now, the longest first: a plugin's root is below
        its tree, and one export's name can begin another's (``<version>.1``)."""
        roots: list[tuple[Path, bool]] = []
        if read_from is not None:
            tree = Path(read_from)
            for _ in PurePosixPath(plugin.subdir).parts:
                tree = tree.parent
            roots += [(Path(read_from), False), (tree, True)]
        served = self._knowledge_base.served_tree(plugin.fetch.key)
        if served is not None:
            root = plugin_root(served, plugin.subdir)
            roots += [] if root is None else [(root, False)]
            roots.append((served, True))
        return sorted(roots, key=lambda pair: len(str(pair[0])), reverse=True)

    def _refusal(
        self, exc: Exception, plugin: Plugin, read_from: Path | None = None
    ) -> str:
        """Why kubed-mcp refused to add ``plugin``, as LIB-29 reports it: the
        layer's reason less its ``plugin <address> is not served:`` wrapper,
        which the conflict's key already says, with no cache path in it."""
        text = str(exc).removeprefix(f"plugin {plugin.address} is not served: ")
        return self._clean(text, plugin, read_from)

    def _cleaned(
        self,
        text: str,
        plugins: Sequence[Plugin],
        read_from: Sequence[tuple[Plugin, Path]] = (),
    ) -> str:
        """``text`` with every served tree of ``plugins`` named by kb's address:
        each plugin's own root by its address, a fetch's tree by its key, the
        deepest first, so a path is named by the plugin it is under. The roots
        ``read_from`` pairs with a plugin, the ones the layer read it at, are
        named too, as ``_clean`` names them."""
        names: dict[str, str] = {}
        pairs = [(plugin, None) for plugin in plugins] + list(read_from)
        for plugin, root in pairs:
            for base, is_tree in self._roots(plugin, root):
                name = plugin.fetch.key if is_tree else plugin.address
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
        noted: set[str],
        reads: Mapping[Key, Mapping[str, FilePrompt]],
        found: Mapping[tuple[str, str], Sequence[Skill]],
    ) -> Snapshot:
        """``snapshot`` less what kubed-mcp does not serve, with its ``/health``
        reading what it does: the parity guard (D3, D11).

        Every ``ok`` plugin's ``skills``, ``prompts`` and ``agents`` are what
        the first library that adds it serves, and 0 when none does (K6 D3):
        the skills both kb and the layer have, the prompts kb's reader read
        as it entered the set, the first read of each name kubed-mcp serves
        (D5), and its ``agent_files`` (AGT-14). Its ``skipped`` is kb's own
        rows, then that add's rows for each skill folder kb found
        (``_skills_of``), selected prompt file and agent file kb found that the
        layer did not serve, with the layer's reason: one row per path, the
        first reason kept (K6 D4). ``found`` is kb's skills by library and
        plugin, which place a skill's folder for the parity guard's note."""
        catalogue = snapshot.catalogue
        kept = {(lib.name, plugin.id) for lib, plugin, _ in added}
        gone: list[str] = []
        for (library, pid), addresses in skills.items():
            if (library, pid) not in kept:
                gone += addresses

        served_agents: list[ServedAgent] = []
        # Every served agent name across the set, to its kb plugin id.
        owners: dict[str, str] = {}
        renamed: dict[str, dict[str, str]] = {}
        unserved: dict[str, list[dict[str, str]]] = {}
        prompts: list[FilePrompt] = []
        library_prompts: dict[str, int] = {}
        # Each plugin's skill, prompt and agent counts and skipped rows, from
        # the first library that adds it: all are the plugin's own.
        plugin_skills: dict[str, tuple[int, list[dict[str, str]]]] = {}
        plugin_prompts: dict[str, tuple[int, list[dict[str, str]]]] = {}
        plugin_agents: dict[str, tuple[int, list[dict[str, str]]]] = {}
        for lib, plugin, served in added:
            served_prompts, skipped = self._prompts_of(
                plugin, served, reads, snapshot.commands.get(plugin.id), noted
            )
            prompts += served_prompts
            library_prompts[lib.name] = library_prompts.get(lib.name, 0) + len(
                served_prompts
            )
            plugin_prompts.setdefault(plugin.id, (len(served_prompts), skipped))
            mine = set(skills.get((lib.name, plugin.id), ()))
            theirs = {_address_of(uri) for uri in served.skills}
            skill_rows = self._skills_of(plugin, served, snapshot)
            plugin_skills.setdefault(plugin.id, (len(mine & theirs), skill_rows))
            # A folder with a row is said by ``log_changes``, with its reason.
            listed = {row["path"] for row in skill_rows}
            folders = self._folders(plugin, found.get((lib.name, plugin.id)))
            for address in sorted(mine - theirs):
                gone.append(address)
                if folders.get(address) in listed:
                    continue
                self._note(
                    noted,
                    f"skill {address} is not served: the plugin layer refused it",
                )
            self._unlisted(plugin, served, snapshot, noted)
            for address in sorted(theirs - mine):
                # Its SKILL.md fails in the rewriter, which finds no such skill.
                self._note(noted, f"skill {address} is not served: kb did not find it")
            for file in served.agent_files:
                if file.renamed:
                    base = file.name.rpartition("@")[0]
                    renamed.setdefault(lib.name, {})[file.name] = (
                        f"{base} is already served by plugin '{owners.get(base, '?')}'"
                    )
                owners[file.name] = plugin.id
                served_agents.append(
                    ServedAgent(
                        name=file.name,
                        library=lib.name,
                        plugin=plugin.id,
                        path=file.path,
                        category=plugin.category,
                        tags=plugin.labels,
                        library_categories=frozenset(lib.categories),
                    )
                )
            # Per library, for its ``unserved``; the counts are the first's.
            counted = self._agents_of(
                lib, plugin, served, snapshot, unserved, owners, noted
            )
            plugin_agents.setdefault(plugin.id, counted)

        narrowed = catalogue.without(sorted(set(gone)))
        status_libraries = {}
        for name, entry in snapshot.status.get("libraries", {}).items():
            entry = dict(entry)
            if name in refused:
                entry["conflicts"] = {**entry.get("conflicts", {}), **refused[name]}
            entry["skills"] = sum(
                1 for s in narrowed.visible_skills() if s.library == name
            )
            entry["agents"] = sum(1 for a in served_agents if a.library == name)
            entry["prompts"] = library_prompts.get(name, 0)
            for key, by_library in (("renamed", renamed), ("unserved", unserved)):
                if by_library.get(name):
                    entry[key] = by_library[name]
                else:
                    entry.pop(key, None)
            status_libraries[name] = entry
        status_plugins = {}
        for pid, entry in snapshot.status.get("plugins", {}).items():
            entry = dict(entry)
            if entry.get("status") != "ok":
                status_plugins[pid] = entry
                continue
            # kb's own rows first, then the layer's, one row per path (D4).
            skipped = list(entry.get("skipped", ()))
            paths = {row["path"] for row in skipped}
            for kind, by_plugin in (
                ("skills", plugin_skills),
                ("prompts", plugin_prompts),
                ("agents", plugin_agents),
            ):
                # A plugin no library adds serves none of either (D3, LIB-33).
                count, rows = by_plugin.get(pid, (0, []))
                entry[kind] = count
                for row in rows:
                    if row["path"] not in paths:
                        paths.add(row["path"])
                        skipped.append(row)
            if skipped:
                entry["skipped"] = skipped
            else:
                entry.pop("skipped", None)
            status_plugins[pid] = entry
        return replace(
            snapshot,
            index=snapshot.index.without(gone),
            catalogue=narrowed,
            prompts=tuple(prompts),
            agents=tuple(sorted(served_agents, key=lambda a: a.name)),
            status={
                **snapshot.status,
                "libraries": status_libraries,
                "plugins": status_plugins,
            },
        )

    def _skills_of(
        self, plugin: Plugin, served: Served, snapshot: Snapshot
    ) -> list[dict[str, str]]:
        """A ``skipped`` row for each skill folder kb's harvest found that the
        plugin layer skipped, in the layer's order, with its first reason and
        no cache path (K6 D4). A folder is one of ``snapshot.skill_dirs``,
        relative to the plugin root as the layer's paths are."""
        dirs = set(snapshot.skill_dirs.get(plugin.id, ()))
        rows: dict[str, str] = {}
        for path, why in served.skipped:
            if path in dirs:
                rows.setdefault(path, why)
        return [
            {
                "path": self._clean(path, plugin, served.root),
                "reason": self._clean(why, plugin, served.root),
            }
            for path, why in rows.items()
        ]

    def _folders(
        self, plugin: Plugin, skills: Sequence[Skill] | None
    ) -> dict[str, str]:
        """Each of ``skills``' folders, relative to ``plugin``'s root, by address."""
        root = self._root_of(plugin)
        if root is None or not skills:
            return {}
        folders: dict[str, str] = {}
        spellings = ((root, False), (root.resolve(), True))
        for skill in skills:
            for base, resolved in spellings:
                path = skill.path.resolve() if resolved else skill.path
                if path.is_relative_to(base):
                    folders[skill.address] = path.relative_to(base).as_posix()
                    break
        return folders

    def _unlisted(
        self, plugin: Plugin, served: Served, snapshot: Snapshot, noted: set[str]
    ) -> None:
        """Say once each skill folder or agent file the layer skipped that kb's
        harvest never found, so no row of the plugin's lists it (D6).

        ``QuietSelection`` keeps the layer's own line for it out of the log, so
        this is the one line said. A file in the plugin's command entries is a
        prompt file, which kb selected and lists, or left out on purpose and
        nobody says (P8), and so is any ``NOT_SELECTED`` skip, whatever entry a
        ``.`` skills or agents component makes it look like it is in. A rename
        that is taken is the library's ``unserved``, and an agent ``agent_meta``
        refused is said by ``_agents_of``."""
        commands = snapshot.commands.get(plugin.id)
        known = {
            *snapshot.skill_dirs.get(plugin.id, ()),
            *snapshot.agent_files.get(plugin.id, ()),
            *(() if commands is None else commands.selected),
        }
        parts = served.components
        entries = [PurePosixPath(e).as_posix() for e in (*parts.skills, *parts.agents)]
        prompts = [PurePosixPath(e).as_posix() for e in parts.commands]
        said: set[str] = set()
        for path, why in served.skipped:
            if path in known or path in said or why == NOT_SELECTED:
                continue
            if _RENAME_TAKEN.match(why) or why.startswith(_AGENT_META_FAILED):
                continue
            if any(_under(path, entry) for entry in prompts):
                continue
            if not any(_under(path, entry) for entry in entries):
                continue
            said.add(path)
            self._note(
                noted,
                f"{self._clean(path, plugin, served.root)!r} of plugin {plugin.id}"
                f" is not served: {self._clean(why, plugin, served.root)}",
            )

    def _agents_of(
        self,
        lib: Library,
        plugin: Plugin,
        served: Served,
        snapshot: Snapshot,
        unserved: dict[str, list[dict[str, str]]],
        owners: Mapping[str, str],
        noted: set[str],
    ) -> tuple[int, list[dict[str, str]]]:
        """What one added plugin serves of its agent files: the count, and a
        ``skipped`` row for each agent file kb found that the layer skipped,
        with the layer's reason and no cache path (AGT-6, AGT-14).

        A rename that is taken too is the library's ``unserved`` instead
        (AGT-8). A file kb never found, which ``agent_meta`` refused (D4), is
        not the plugin's to report: it is said once, and so is a file kb found
        that the layer neither served nor skipped, as the parity guard says a
        skill's."""
        found = snapshot.agent_files.get(plugin.id, ())
        accounted = {file.path for file in served.agent_files}
        rows: dict[str, str] = {}
        for path, why in served.skipped:
            taken = _RENAME_TAKEN.match(why)
            if taken is not None:
                accounted.add(path)
                unserved.setdefault(lib.name, []).append(
                    {
                        "plugin": plugin.id,
                        "path": path,
                        "reason": f"{taken['name']} is already served by plugin"
                        f" '{owners.get(taken['name'], '?')}'",
                    }
                )
            elif path in found:
                accounted.add(path)
                rows.setdefault(path, self._clean(why, plugin, served.root))
            elif why.startswith(_AGENT_META_FAILED):
                # kb says it once; the layer's line is filtered (HTTP-45).
                self._note(
                    noted,
                    f"agent file {self._clean(path, plugin, served.root)} of plugin"
                    f" {plugin.id} is not served: kb's harvest did not find it",
                )
        for path in found:
            if path not in accounted:
                self._note(
                    noted,
                    f"agent file {path} of plugin {plugin.id} is not served:"
                    " the plugin layer did not read it",
                )
        return (
            len(served.agent_files),
            [{"path": path, "reason": why} for path, why in rows.items()],
        )

    def _prompts_of(
        self,
        plugin: Plugin,
        served: Served,
        reads: Mapping[Key, Mapping[str, FilePrompt]],
        commands: PluginCommands | None,
        noted: set[str],
    ) -> tuple[list[FilePrompt], list[dict[str, str]]]:
        """What one added plugin serves of its prompt files, as kb read them,
        and a ``skipped`` row for each selected file that did not serve (D5).

        A served name's prompt is the first read of it: the one the plugin
        layer claimed. A row is the layer's first reason for a selected path,
        never ``NOT_SELECTED`` and never one for a path that served under
        another read; a selected path the layer neither served nor skipped is
        said once, as the parity guard says a skill's."""
        names = set(served.prompts)
        mine: list[FilePrompt] = []
        paths: set[str] = set()
        for path, file in reads.get((served.namespace, served.address), {}).items():
            if file.name in names:
                names.discard(file.name)
                mine.append(file)
                paths.add(path)
        if commands is None:
            return mine, []
        selected = set(commands.selected)
        rows: dict[str, str] = {}
        for path, reason in served.skipped:
            if path in selected and path not in paths and reason != NOT_SELECTED:
                rows.setdefault(path, self._clean(reason, plugin, served.root))
        for path in commands.selected:
            if path not in paths and not any(
                where == path for where, _ in served.skipped
            ):
                self._note(
                    noted,
                    f"prompt file {path} of plugin {plugin.id} is not served:"
                    " the plugin layer did not read it",
                )
        return mine, [{"path": path, "reason": why} for path, why in rows.items()]

    # -- the hooks -----------------------------------------------------------

    def view(self) -> View:
        """The plugins the request's scope admits, which is also the build key.

        The live ones among them are revalidated first, and re-read when they
        moved (D9). The published state is read after that re-read and pinned
        for the rewriter, and kubed-mcp takes its own state after the view
        (0.4.2), so the request that re-reads builds the re-read and serves the
        edit (SKL-37, N6).
        """
        scope = requested_scope()
        self._reread_live(scope)
        published = self._published
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
        for this one. It runs before the view pins kb's state and before
        kubed-mcp takes its own (0.4.2), so the request that re-reads serves the
        edit (SKL-37, N6).
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
                stamp = _stamp(source, watch.skills, (*watch.agents, *watch.commands))
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
                read_from = [
                    (published.table[key].plugin, served.root)
                    for key, served in current.items()
                    if key in published.table
                ]
                message = self._cleaned(str(exc), plugins, read_from)
                log.warning("re-reading live plugins failed: %s", message)
                # Not tried again until a file moves again.
                self._published = replace(published, live={**published.live, **moved})
                return
            self._knowledge_base.renarrowed(published.snapshot, narrowed)
            if self._knowledge_base.snapshot is narrowed:
                # What the re-read changed, said once as a refresh says it: a
                # skill it newly skips is a row, which no parity note says. kb's
                # lock is not held here, nor taken.
                log_changes(published.snapshot.status, narrowed.status)
        finally:
            self._lock.release()

    def _reading(self) -> tuple[_Published, bool]:
        """The published state a hook reads, and whether it is add time (D6).

        The generation entering the set while this serving stages one, then the
        state its request's view pinned for a build, then what is published.
        """
        entering = _ENTERING.get()
        if entering is not None and entering[0] is self:
            return entering[1], True
        pinned = _PINNED.get()
        if pinned is not None and pinned[0] is self:
            return pinned[1], False
        return self._published, False

    def served_snapshot(self) -> Snapshot:
        """The narrowed snapshot of the state a hook reads (``_reading``).

        The one the request's view pinned when it has pinned, otherwise the one
        published with the set kubed-mcp serves now. ``_published`` is set
        just before ``serve()`` and ``KnowledgeBase`` swaps after, so it leads
        kb's snapshot and never lags what the layer serves. While this serving
        stages a generation, and in the publishing context only, it is the
        staged one, which the instructions never reach.
        """
        return self._reading()[0].snapshot

    def rewrite(self, site: Site, text: str) -> str:
        """kb's rewriting: a root ``SKILL.md`` and an agent's or a command's body
        rendered, and every text file of a skill with LF line endings (SKL-22);
        anything else as written. Against the state ``_reading`` gives."""
        published, _ = self._reading()
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
            if published.snapshot.index.get(address) is None:
                # One kb's harvest did not find, so one kb never vetted: fail
                # closed, the whole skill (PLUG-59). The parity guard said why,
                # once.
                raise ValueError(f"skill {address} is not one kb found")
            return catalogue.instructions(address, text, requested_scope())
        if site.kind in ("agent", "command"):
            # The frontmatter as written, so a description is served as it is
            # (D9); the body's names and plugin root rendered (D4). A command
            # with no frontmatter block is skipped by the reader anyway.
            head, body = split_frontmatter(text)
            if not head:
                return text
            return head + catalogue.agent_instructions(
                row.library, row.plugin.id, body, requested_scope()
            )
        return text

    def read_command(
        self, text: str, path: str, name: str, plugin: Served
    ) -> Prompt | str:
        """kb's dialect reader for one command file (PLUG-62, D2, D3).

        Skips a file kb's harvest did not select, and one the plugin layer names
        otherwise than kb does. Else parses ``text`` as kb's prompt: at add time
        in the dialect ``dialect_of`` decides, recorded with the read; at a
        build in the dialect it was read in, so a rewritten body never changes
        a file's dialect. A malformed file's reason is kb's, with no cache path.
        """
        published, adding = self._reading()
        key = (plugin.namespace, plugin.address)
        row = published.table.get(key)
        commands = (
            None if row is None else published.snapshot.commands.get(row.plugin.id)
        )
        if row is None or commands is None or path not in commands.selected:
            return NOT_SELECTED
        root = Path(plugin.root)
        below = prompt_name(root / path, root, commands.command_dirs)
        expected = f"{row.library}_{below}"
        if name != expected:
            return RENAMED.format(name=name, expected=expected)
        last = published.prompts.get(key, {}).get(path)
        dialect = (
            dialect_of(path, configured=row.plugin.dialect, claude=commands.claude)
            if adding or last is None
            else last.dialect
        )
        try:
            file = parse_prompt(
                text,
                root / path,
                name=name,
                library=row.library,
                plugin=row.plugin.id,
                tags=sorted(row.plugin.labels),
                category=row.plugin.category,
                library_categories=row.library_categories,
                dialect=dialect,
            )
        except READ_ERRORS as exc:
            return self._clean(str(exc), row.plugin, root)
        if adding:
            self._prompt_reads.setdefault(key, {}).setdefault(path, file)
        elif last is not None:
            # A build re-reads the text its rewriters wrote, and the gateway
            # prefix's writer rewrites the frontmatter too. kb's rewriter keeps
            # it as written, so the read's own frontmatter is what serves --
            # the description and the arguments as written (D9) -- and only
            # the body is the build's.
            file = replace(last, template=file.template)
        return adapt(file)

    def agent_meta(self, name: str, plugin: Served) -> dict | None:
        """kb's ``io.kubed.mcp-kb/agent`` for an agent entering the set.

        Raises, so the set skips the agent (PLUG-73), for a file kb's harvest
        did not find (D4) -- every agent served is then one AGT-3's fallback
        refuses -- and for one kb cannot read (``_frontmatter``). ``frontmatter``
        is what kubed-mcp's own parser makes of the file, so the two keys agree:
        read from the file when its plugin is added, and as that add read it
        when the plugin is kept unread, live or not. ``skills`` is narrowed to
        the skills the layer serves of its plugin that kb found."""
        published, _ = self._reading()
        key = (plugin.namespace, plugin.address)
        row = published.table.get(key)
        if row is None:
            return None
        path = next((f.path for f in plugin.agent_files if f.name == name), None)
        if path is None:
            return None
        if path not in published.snapshot.agent_files.get(row.plugin.id, ()):
            # One kb never vetted: fail closed, as the rewriter fails a skill
            # kb never found.
            raise ValueError(f"agent file {path} is not one kb found")
        catalogue = published.snapshot.catalogue
        carried = self._carried.get(key)
        if carried is not None:
            # Kept unread: as its last add read it, whatever its file says now.
            read = carried.get(path)
            if read is None:
                # kb cannot say what this agent is, so the set skips it (PLUG-73).
                raise ValueError(f"kb cannot read agent file {path}")
        else:
            # Added: what the file says now, which a live re-read is for (SKL-37).
            # A file kb cannot read raises, so the set skips it (PLUG-73).
            read = _frontmatter(Path(plugin.root), path)
            self._reads.setdefault(key, {})[path] = read
        value = catalogue.agent_meta(
            row.library, row.plugin.id, path, read, row.plugin.servers
        )
        served = set(plugin.skills)
        index = published.snapshot.index

        def serves(uri: str) -> bool:
            # The parity guard runs after the set is staged, so a skill kb did
            # not find is still the layer's here: leave it out.
            return uri in served and index.get(_address_of(uri)) is not None

        value["skills"] = {k: v for k, v in value["skills"].items() if serves(v)}
        return {AGENT_META: value}


class _Abandoned(Exception):
    """A re-read that read a moved plugin from another export: not served."""


def _under(path: str, entry: str) -> bool:
    """Whether the root-relative ``path`` is the component ``entry`` or in it."""
    return entry == "." or path == entry or path.startswith(f"{entry}/")


def _root(served: Served | None) -> Path | None:
    """The root ``served`` was read at, or None for a plugin not served yet."""
    return None if served is None else Path(served.root)


def _same_folder(recorded: Path | None, read: Path) -> bool:
    """Whether the folder a plugin was read from is the one recorded."""
    if recorded is None:
        return False
    try:
        return Path(read).resolve() == recorded.resolve()
    except OSError:
        return False


def _stamp(snapshot: Snapshot, skills: Sequence[Skill], files: Sequence[Path]) -> tuple:
    """What a live plugin's ``skills``, agent and prompt ``files`` hold on disk now,
    each revalidated first (SKL-37)."""
    catalogue = snapshot.catalogue
    parts: list[tuple] = [catalogue.live_stamp(skill) for skill in skills]
    for path in files:
        snapshot.revalidate(path)
        try:
            stat = path.stat()
        except OSError:
            parts.append((str(path),))
            continue
        parts.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(parts)


def _frontmatter(root: Path, path: str) -> dict[str, object]:
    """The frontmatter of the agent file at ``path`` under ``root``, as kubed-mcp's
    own parser reads it (``parse_agent``, with no prefix: GW-8), for kb's
    ``_meta`` key.

    Only a regular file inside ``root``, read at the path ``readable`` resolves:
    a symlink out of the plugin, a directory or a ``..`` is refused here whatever
    the plugin layer lists. Raises ``ValueError``, so ``agent_meta`` skips the
    agent (PLUG-73), naming ``path`` and never the cache path under it."""
    target = readable(root, path)
    try:
        if target is None:
            raise FileNotFoundError
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # No errno or decode text in the reason: either can carry a path.
        raise ValueError(f"kb cannot read agent file {path}") from None
    parsed = parse_agent(text, stem=PurePosixPath(path).stem)
    if isinstance(parsed, str):
        raise ValueError(f"agent file {path}: {parsed}")
    return dict(parsed.detail["_meta"][META_KEY]["frontmatter"])
