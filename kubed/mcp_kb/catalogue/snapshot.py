"""One immutable view of the whole catalogue, and how to build one.

Everything the request path touches -- the index, the library files, the
address space, each plugin's prompt files -- hangs off a single frozen
``Snapshot``. A rebuild
constructs a new one beside the old and the server swaps it in with one
assignment, so a listing in flight is served by a consistent catalogue and no
reader ever sees a half-rebuilt one. Nothing here mutates a snapshot; there is
no method that could.

Two units of work. ``build_fetch`` does the blocking part for a *tree*
(materialise, fingerprint) and hands back a ``FetchRecord``, which is what
``index.json`` holds. ``build_plugin`` does the harvest of one *plugin* out of
such a tree (find the skills, parse frontmatter, find the prompt, agent and
other files) and hands back a ``Harvest``. A harvest is in memory only, and is
redone for every plugin on every generation: it is a local walk, and a harvest
kept across generations is one the lists that chose it can move out from under
(SRC-48). ``build_snapshot`` then assigns every plugin to the libraries that
select it and gives each its copy of the plugin's skills. That split is what
lets a refresh rebuild one fetch and keep the rest, and what lets a cold start
fetch *nothing* and still serve.

A failed fetch or plugin is a record, not an exception. One unreachable
repository must not empty the catalogue of everything else, so the failure
rides in ``status`` and ``/health`` reports it.

And a fetch that failed *after* it once succeeded is not a failed fetch at all:
``stale`` keeps the last good record, root intact, and hangs the error off it.
Only a fetch that has never been materialised has nothing better to serve than
its error.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Literal

from ..config import Config, scrub
from ..mcp.scope import EVERYTHING, Scope
from ..plugins import Fetch, Globs, Plugin
from ..plugins.manifest import (
    Components,
    read_manifest,
)
from ..plugins.select import select
from ..sources import AccessRefused, SourceError, SourceLoader
from ..sources.live import Revalidator, is_live
from . import harvest
from .agents import ServedAgent
from .index import FetchRecord, now
from .prompts import FilePrompt
from .skills import LibraryFiles, Skill, SkillIndex, load_skills, naming_problem
from .uris import RESERVED_NAMES, SCHEME, Catalogue, LibraryText, _count, uri_for

log = logging.getLogger(__name__)

# The record states that still name a tree worth serving. A "stale" record is
# one of them: its tree is the last good one, which is the whole point.
SERVABLE = ("ok", "stale")


@dataclass(frozen=True)
class Library:
    """A resolved library: which plugins it serves, in config order.

    ``plugins`` is the union the config described -- the marketplace's
    entries, then the ``plugins:`` list, then the selector's matches --
    deduplicated in that order. ``error`` is why part of that could not be
    resolved (the marketplace could not be read, a named plugin does not
    exist); the library still serves the rest.

    ``main`` is the id of the plugin whose skills sit at ``<library>/<name>``,
    or None: every other plugin's sit at ``<library>/<plugin name>/<name>``
    (see ``main_plugin``). Decided here, from the config and what the
    marketplace publishes, so no request's scope and no serving outcome can
    move an address.
    """

    name: str
    description: str
    plugins: tuple[str, ...]
    error: str | None = None
    main: str | None = None
    skipped: tuple[dict[str, str], ...] = ()
    notes: str = ""
    list_skills: bool = True
    categories: tuple[str, ...] = ()


@dataclass(frozen=True)
class Harvest:
    """One plugin's harvest out of its fetch's tree, held in memory.

    ``root`` is the plugin root -- the fetch root joined with the plugin's
    subdirectory -- or ``None`` for a plugin that has none. A plugin fails on
    its own when its root is not a directory, its manifest does not parse, its
    fetch failed or its tree could not be read; the error says which.

    ``skills`` carry no library and no folder: those are the library's, and
    each library takes its copy of a skill with ``dataclasses.replace``, so a
    plugin in two libraries is one harvest served twice. Every path but
    ``skill_dirs`` is root-relative, in the order the harvest found it.
    """

    id: str
    root: Path | None
    status: Literal["ok", "failed"]
    error: str | None
    built: str
    skills: tuple[Skill, ...] = ()
    # The prompt files the harvest selected, in path order. Nothing is parsed
    # here: the plugin layer reads them, through kb's command reader, when the
    # plugin is added (PRM-18).
    prompts: tuple[str, ...] = ()
    # Those of ``prompts`` a ``commands`` declaration selects, which are read
    # in Claude's dialect wherever they sit (PRM-14).
    claude_prompts: tuple[str, ...] = ()
    # The declared command folders, which name what is below them (PLG-25).
    command_dirs: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    skill_dirs: tuple[Path, ...] = ()
    # The agent files the harvest found, read by nothing here; and the paths
    # a fallback must refuse (AGT-3).
    agents: tuple[str, ...] = ()
    agent_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginCommands:
    """One plugin's prompt files, as the plugin layer is handed them (D1).

    ``selected`` is what kb's harvest selected, root-relative and in path
    order, and ``claude`` those of them a ``commands`` declaration selects,
    which are Claude's wherever they sit (PRM-14, rule 5). ``command_dirs``
    are the declared command folders, which name what is below them (PLG-25),
    and ``entries`` the ``commands`` paths the layer reads ``selected`` through.
    """

    selected: tuple[str, ...]
    claude: frozenset[str]
    command_dirs: tuple[str, ...]
    entries: tuple[str, ...]


@dataclass(frozen=True)
class Snapshot:
    """The catalogue as of one generation, complete and never edited again.

    ``generation`` counts rebuilds from 0 (the cold start). It is what
    ``AnnounceChanges`` compares a session against, so it must move on every
    swap and only on a swap.

    ``status`` is the ``/health`` body less its counters: ``libraries``,
    ``plugins`` and ``fetches``, each keyed by name, id and key.

    ``prompts`` is what the plugin layer serves, as kb's command reader read
    it: empty as ``build_snapshot`` returns it, and filled in when the plugin
    set is published. ``commands`` is each plugin's prompt files by plugin id,
    which is what the set is handed.

    ``agents`` is what the plugin layer serves, likewise, in name order (AGT-7),
    and ``agent_files`` each harvested plugin's agent files by plugin id: what
    kb found, which a live plugin's watch stamps and the parity guard holds
    the layer to (D4). ``skill_dirs`` is each harvested plugin's skill
    folders by plugin id, root-relative.
    """

    generation: int
    built: str
    index: SkillIndex
    resources: LibraryFiles
    catalogue: Catalogue
    prompts: tuple[FilePrompt, ...]
    status: dict[str, dict] = field(default_factory=dict)
    # The live fetches of this generation, or None when none is live. Built
    # here and retired here: a refresh exports a fetch to a new directory, so
    # a revalidator that outlived its snapshot would go on writing into the
    # tree nothing is serving.
    live: Revalidator | None = None
    # What the generation was built from: the libraries in config order and
    # every resolved plugin. What a publisher walks to serve it.
    libraries: tuple[Library, ...] = ()
    plugins: tuple[Plugin, ...] = ()
    commands: Mapping[str, PluginCommands] = field(default_factory=dict)
    agent_files: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    agents: tuple[ServedAgent, ...] = ()
    skill_dirs: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def visible_agents(self, scope: Scope = EVERYTHING) -> list[ServedAgent]:
        """The agents served that ``scope`` admits, in name order (AGT-15)."""
        return [a for a in self.agents if a.admitted(scope)]

    def visible_prompts(self, scope: Scope = EVERYTHING) -> list[FilePrompt]:
        """The prompts served that ``scope`` admits, by their plugin's terms."""
        return [
            p
            for p in self.prompts
            if scope.admits(
                p.library, p.category, p.tags, library_categories=p.library_categories
            )
        ]

    def revalidate(self, path: Path) -> None:
        """Bring ``path`` level with its server, if a live fetch owns it."""
        if self.live is not None:
            self.live.revalidate(path)

    def stats(self, key: str) -> dict:
        """What live reads of the fetch ``key`` have done since this snapshot."""
        return {} if self.live is None else self.live.stats(key)


# -- the expensive half: one fetch, one plugin ----------------------------------


def build_fetch(
    fetch: Fetch, loader: SourceLoader, *, refusal_is_fatal: bool = False
) -> FetchRecord:
    """Materialise one fetch from scratch and fingerprint it: the blocking part.

    The fingerprint is taken here, *before* any plugin reads the tree, so a
    file written mid-harvest lands outside the recorded fingerprint and the
    next pass rebuilds. Taken after, that write would look already-accounted-for
    and the change would never be picked up.

    ``OSError`` is caught alongside ``SourceError``: a directory that vanishes
    between the materialise and the fingerprint is exactly as much "a failed
    fetch is a record, not an exception" as a bad URL is.

    With ``refusal_is_fatal``, a fetch whose server refuses its credentials is
    the one exception, and ``AccessRefused`` escapes. The cold start asks for
    that: see ``KnowledgeBase._cold_start``.
    """
    try:
        root = loader.materialise(fetch.key)
        stamp = loader.fingerprint(fetch, root)
    except AccessRefused as exc:
        if refusal_is_fatal:
            raise
        return failed_fetch(fetch.key, str(exc))
    except (SourceError, OSError) as exc:
        return failed_fetch(fetch.key, str(exc))
    return FetchRecord(
        key=fetch.key,
        status="ok",
        root=str(root),
        fingerprint=stamp,
        built=now(),
        error=None,
    )


def with_manifest(plugin: Plugin, root: Path) -> tuple[Plugin, Globs]:
    """The plugin completed by its own manifest, and the globs it serves.

    A ``plugin.json`` is the publisher's word on the plugin, read once here.
    Its ``keywords`` join the plugin's labels -- obra/superpowers is tagged
    nowhere but there -- and its ``description`` fills in only what the entry
    or the config left empty. Its ``version`` beats a marketplace entry's, as
    in Claude Code, while a declared plugin's own ``version:`` beats it (PLG-17).

    The components merge as Claude Code merges them, per kind:

    - ``skills/`` is always scanned, and the folders a manifest (PLG-20), an
      entry (LIB-30) and a declared plugin's own ``skills:`` list add to it, in
      that order -- the lists kubed-mcp is handed -- except a declared
      ``skills: []``, which serves none;
    - a declared plugin's own ``prompts:`` is exactly what it serves (LIB-33);
    - ``commands`` and ``agents`` replace their conventions (PLG-21, PLG-22),
      the entry's appended to the manifest's, and a default folder they leave
      unread is noted (PLG-23);
    - only a Claude-format plugin -- one with a manifest, or a marketplace
      entry -- has agents at all.

    ``None`` for a kind is ``harvest.DEFAULTS``, or for skills the scan alone.
    A manifest that does not parse raises, and so does a ``strict: false``
    entry that names components beside one (LIB-31): either is the plugin's
    failure, not a reason to guess.
    """
    manifest = read_manifest(root)
    entry = plugin.entry
    if manifest is not None and entry is not None and not plugin.strict and entry.named:
        raise ValueError("conflicting manifests")
    found = manifest.components if manifest is not None else Components()
    listed = entry if entry is not None else Components()
    claude_format = manifest is not None or entry is not None
    config = plugin.globs
    notes = [*found.notes, *listed.notes]

    # The declared skill folders, as kubed-mcp merges them; `skills: []` in
    # the config is the one way to serve none (`()`), and no folder at all
    # leaves the scan of `skills/` (`None`).
    if config.skills == ():
        skills: tuple[str, ...] | None = ()
    else:
        skills = _joined(found.skills, listed.skills, config.skills) or None

    prompts = config.prompts
    commands: tuple[str, ...] = ()
    command_files: tuple[str, ...] = ()
    command_dirs: tuple[str, ...] = ()
    if prompts is None and (found.commands is not None or listed.commands is not None):
        prompts = commands = _joined(found.commands, listed.commands)
        command_files = _joined(found.command_files, listed.command_files)
        command_dirs = _joined(found.command_dirs, listed.command_dirs)
        notes += _ignored(root, "commands", (*command_files, *command_dirs))
        notes += [
            f"commands entry '{rel}' is not in the plugin"
            for rel in command_files
            if harvest.readable(root, rel) is None
        ]

    if not claude_format:
        agents: tuple[str, ...] | None = ()
    elif found.agents is not None or listed.agents is not None:
        agents = _joined(found.agents, listed.agents)
        notes += _ignored(root, "agents", agents)
        notes += [
            f"agents entry '{rel}' is not in the plugin"
            for rel in agents
            if harvest.readable(root, rel) is None
        ]
    else:
        agents = None

    # Claude Code: beside a plugin.json, an entry's `mcpServers` don't apply.
    servers = _servers(root, (found,) if manifest is not None else (listed,), notes)
    completed = replace(
        plugin,
        claude_format=claude_format,
        servers=servers,
        # Fetched content, and /health publishes it: no cache path, no userinfo.
        notes=tuple(dict.fromkeys(scrub(unrooted(note, root)) for note in notes)),
    )
    if manifest is not None:
        completed = replace(
            completed,
            description=plugin.description or manifest.description or "",
            # Claude Code's calculatePluginVersion: plugin.json beats an entry;
            # a declared plugin's own `version:` is the operator's override.
            version=(manifest.version or plugin.version)
            if plugin.marketplace
            else (plugin.version or manifest.version),
            keywords=tuple(dict.fromkeys((*plugin.keywords, *manifest.keywords))),
        )
    globs = Globs(
        skills=skills,
        prompts=prompts,
        files=config.files,
        commands=commands,
        agents=agents,
        command_dirs=command_dirs,
        command_files=command_files,
    )
    return completed, globs


def _joined(*parts: tuple[str, ...] | None) -> tuple[str, ...]:
    """The patterns of every part that has any, in order, each once."""
    return tuple(dict.fromkeys(item for part in parts if part for item in part))


def _ignored(root: Path, key: str, paths: Iterable[str]) -> list[str]:
    """PLG-23's note, when ``key`` replaced a default folder that is there.

    ``paths`` are the paths as listed, never the patterns made of them: an
    escaped folder name is not the folder's name. As in Claude Code, a key
    that names the folder or a path inside it (``"./agents/reviewer.md"``,
    ``"./commands/"``) reads it, and earns none; so does ``"./"`` as a
    commands directory, which reads the whole plugin.
    """
    if not (root / key).is_dir():
        return []
    if any(path == "." or PurePosixPath(path).parts[:1] == (key,) for path in paths):
        return []
    return [f'Default {key}/ folder is ignored because the manifest sets "{key}"']


def _servers(
    root: Path, components: Iterable[Components], notes: list[str]
) -> tuple[str, ...]:
    """The MCP server names a plugin declares, sorted (PLG-27).

    Its root ``.mcp.json``, then its manifest's inline object and the files it
    names -- or, with no manifest, its entry's (LIB-30). Only names are read:
    nothing here is ever started, connected to or forwarded. A file that does
    not parse costs one note.
    """
    names = _server_file(root, ".mcp.json", notes, named=False)
    for part in components:
        names += part.mcp_servers
        for rel in part.mcp_files:
            names += _server_file(root, rel, notes, named=True)
    return tuple(sorted(set(names)))


def _server_file(root: Path, rel: str, notes: list[str], *, named: bool) -> list[str]:
    """The server names in one JSON file: its ``mcpServers`` keys, else its own.

    A root ``.mcp.json`` that is not there is ordinary; a file a manifest
    names and does not ship is noted, as one that does not parse is.
    """
    path = harvest.readable(root, rel)
    if path is None:
        if named:
            notes.append(f"mcpServers file {rel} is not in the plugin")
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        # ValueError covers a bad encoding, bad JSON and an integer too long
        # to convert; RecursionError a file nested past the parser's stack.
        data = None
    if not isinstance(data, dict):
        notes.append(f"{rel} is not a JSON object of MCP servers")
        return []
    servers = data.get("mcpServers")
    return [str(name) for name in (servers if isinstance(servers, dict) else data)]


def effective_globs(plugin: Plugin, root: Path) -> Globs:
    """What the plugin serves: its config, manifest and entry, merged."""
    return with_manifest(plugin, root)[1]


def build_plugin(plugin: Plugin, root: Path, *, globs: Globs) -> Harvest:
    """Harvest one plugin out of its tree: its skills and the files it serves.

    ``root`` is the plugin root -- the fetch root joined with the plugin's
    subdirectory -- and ``globs`` is already resolved (``effective_globs``).
    Prompt files are recorded by path and never parsed here: the plugin layer
    reads them through kb's command reader as the plugin is added (PRM-18).
    Agent files are recorded by path too, and the plugin layer is the one
    reader of them (AGT-6).

    Everything from ``skill_dirs`` through the agent files runs in one try: a
    file can vanish or turn unreadable between the fingerprint walk and the
    read that follows it (a plain TOCTOU, and the whole point of this module
    is serving trees that change underneath it), and that must fail *this
    plugin*, not the caller.
    """
    try:
        dirs = (
            [] if globs.skills == () else harvest.skill_dirs(root, globs.skills or ())
        )
        # No library and no folder: each library gives its copy its own.
        skills = load_skills(dirs, library="", plugin=plugin, root=root)
        files = harvest.library_files(root, globs, dirs)
        declared = harvest.command_files(root, globs)
        selected = harvest.prompt_files(root, globs)
        prompts = tuple(_relative(path, root) for path in selected)
        claude = tuple(_relative(path, root) for path in selected if path in declared)
        agents = tuple(
            _relative(path, root) for path, _ in harvest.agent_files(root, globs)
        )
        agent_paths = tuple(
            _relative(path, root) for path in harvest.agent_paths(root, globs)
        )
    except OSError as exc:
        return failed_plugin(plugin, unrooted(str(exc), root))

    return Harvest(
        id=plugin.id,
        root=root,
        status="ok",
        error=None,
        built=now(),
        skills=tuple(skills),
        prompts=prompts,
        claude_prompts=claude,
        command_dirs=globs.command_dirs,
        files=tuple(files),
        skill_dirs=tuple(dirs),
        agents=agents,
        agent_paths=agent_paths,
    )


# -- the cheap half: libraries, then the snapshot -------------------------------


def assemble_libraries(
    config: Config,
    plugins: list[Plugin],
    *,
    errors: dict[str, str] | None = None,
    skipped: dict[str, tuple[dict[str, str], ...]] | None = None,
    descriptions: dict[str, str] | None = None,
    entries: dict[str, int] | None = None,
) -> list[Library]:
    """Each library's plugins, in config order: marketplace, ``plugins:``, selector.

    ``errors`` and ``skipped`` are what reading each marketplace produced,
    keyed by library name: the caller materialised and read them, this only
    reports them beside what the library still serves. A ``plugins:`` entry
    with an ``@`` in it names a marketplace plugin that may not exist -- the
    config could not check that -- so a missing one becomes the library's
    error and the rest of the library serves.

    ``descriptions`` is each marketplace library's upstream description. A
    library's own is the first non-empty of: configured, upstream, its
    plugins' joined by newlines.

    ``entries`` is how many entries each marketplace library's catalog
    publishes, skipped ones included; a library whose marketplace could not
    be read has none, and so no main plugin by the lone-entry rule.
    """
    by_id = {plugin.id: plugin for plugin in plugins}
    libraries: list[Library] = []
    for lib in config.libraries:
        problems = [errors[lib.name]] if errors and lib.name in errors else []
        ids: list[str] = []
        if lib.source:
            ids += [p.id for p in plugins if p.marketplace == lib.name]
        missing = [name for name in lib.plugins if name not in by_id]
        ids += [name for name in lib.plugins if name in by_id]
        if lib.plugin_selector is not None:
            ids += [p.id for p in select(plugins, lib.plugin_selector)]
        upstream = (descriptions or {}).get(lib.name, "")
        resolved = tuple(dict.fromkeys(ids))
        own = [by_id[i].description for i in resolved]
        if missing:
            problems.append(_no_such_plugins(missing, plugins))
        libraries.append(
            Library(
                name=lib.name,
                description=_resolved(lib.description, upstream, own),
                notes=lib.notes,
                list_skills=lib.list_skills,
                categories=tuple(lib.categories),
                plugins=resolved,
                main=main_plugin(
                    lib.name,
                    [by_id[i] for i in resolved],
                    (entries or {}).get(lib.name) if lib.source else None,
                ),
                error=scrub("; ".join(problems)) or None,
                # Both of these quote fetched content -- a marketplace entry's
                # own fields -- and `/health` publishes them unauthenticated,
                # so they meet the same guard a log line does. The messages are
                # built from a host rather than a URL where they can be; this
                # is what stops the next one that is not from being a leak.
                skipped=tuple(
                    {key: scrub(value) for key, value in row.items()}
                    for row in (skipped or {}).get(lib.name, ())
                ),
            )
        )
    return libraries


def main_plugin(
    library: str, plugins: Sequence[Plugin], entries: int | None
) -> str | None:
    """The id of the library's main plugin, or None (design D1).

    The first of ``plugins`` named like the library; else, when the library's
    marketplace publishes exactly one entry (``entries``, skipped ones
    counted), that entry's plugin -- whatever its path -- unless that one
    entry was itself skipped; else none. ``plugins`` is the library's resolved
    list, in its order, and nothing about a request enters into it.
    """
    named = next((p.id for p in plugins if p.name == library), None)
    if named is not None or entries != 1:
        return named
    return next((p.id for p in plugins if p.marketplace == library), None)


def folder_for(library: Library, plugin: Plugin) -> str:
    """Where ``plugin``'s skills sit in ``library``: ``""`` for its main plugin."""
    return "" if plugin.id == library.main else plugin.name


def namespace_for(library: Library, plugin: Plugin) -> str:
    """The namespace ``plugin`` is served under in ``library``: its skills' base."""
    return "/".join(p for p in (library.name, folder_for(library, plugin)) if p)


def _resolved(configured: str, upstream: str, plugins: list[str]) -> str:
    """The first non-blank of the three tiers; blank text must not win."""
    joined = "\n".join(dict.fromkeys(d.strip() for d in plugins if d.strip()))
    if configured.strip():
        return configured.strip()
    return scrub(upstream.strip() or joined)


def _no_such_plugins(missing: list[str], plugins: list[Plugin]) -> str:
    """Which named plugins do not exist, and what their marketplaces publish."""
    parts = []
    for name in missing:
        _, _, market = name.partition("@")
        published = sorted(p.name for p in plugins if p.marketplace == market)
        there = f"; {market} publishes: {', '.join(published)}" if published else ""
        parts.append(f"no plugin named {name!r}{there}")
    return "; ".join(parts)


def build_snapshot(
    config: Config,
    plugins: list[Plugin],
    libraries: list[Library],
    fetches: dict[str, FetchRecord],
    harvests: dict[str, Harvest],
    generation: int,
) -> Snapshot:
    """The catalogue out of this generation's harvests, run on every rebuild.

    Each library takes its copy of each plugin's skills without touching
    disk. Prompts are not
    loaded here at all: each plugin's prompt files become its
    ``PluginCommands``, and the plugin layer reads them through kb's command
    reader when the set is published, which is what fills ``prompts``.

    Within a plugin, what the address space has no room for is left out and
    listed under the plugin's ``skipped`` in ``/health`` (see ``_admit``);
    everything else of that plugin is served. Libraries are walked in config
    order and a library's plugins in its order, and a plugin that would serve
    an address an earlier plugin *of that library* already serves fails in
    that library only (see ``_Claims``): the earlier one keeps
    serving, ``/health`` names the conflict under the library, and the same
    plugin serves normally in any other library.

    Agent files are not read here either: each plugin's are its
    ``agent_files``, and the plugin layer reads, names and serves them when the
    set is published, which is what fills ``agents`` (``SkillServing._narrowed``).
    """
    del config  # the libraries are already resolved; kept for the call shape
    by_id = {plugin.id: plugin for plugin in plugins}
    live_fetches = _live_fetches(plugins, fetches)
    revalidator = Revalidator(live_fetches) if live_fetches else None
    revalidate = None if revalidator is None else revalidator.revalidate

    skills: list[Skill] = []
    resources = LibraryFiles(revalidate)
    admitted = {
        pid: _admit(harvest)
        for pid, harvest in harvests.items()
        if harvest.status == "ok" and harvest.root is not None
    }
    # Filled by the first library that serves each plugin: its own counts.
    served: dict[str, dict[str, int]] = {}
    shadowed: dict[str, list[dict[str, str]]] = {}
    status_libraries: dict[str, dict] = {}

    for lib in libraries:
        entry, own = _serve_library(
            lib,
            by_id,
            harvests,
            admitted,
            resources,
            served,
            shadowed,
        )
        skills += own
        status_libraries[lib.name] = entry

    status_plugins = {
        plugin.id: _plugin_status(
            plugin,
            harvests.get(plugin.id),
            [lib.name for lib in libraries if plugin.id in lib.plugins],
            admitted.get(plugin.id),
            served.get(plugin.id),
            # What the libraries left out of it: files inside its own skills.
            shadowed.get(plugin.id, []),
        )
        for plugin in plugins
    }
    live_keys = {p.fetch.key for p in plugins if is_live(p.fetch)}
    status_fetches = {
        key: _fetch_status(record, key in live_keys) for key, record in fetches.items()
    }

    commands = {pid: _commands(harvests[pid]) for pid in admitted}
    index = SkillIndex(skills)
    return Snapshot(
        generation=generation,
        built=now(),
        index=index,
        resources=resources,
        catalogue=Catalogue(
            index,
            resources,
            revalidate,
            [
                LibraryText(
                    lib.name,
                    lib.description.strip(),
                    lib.notes.strip(),
                    lib.list_skills,
                    tuple(
                        (pid, by_id[pid].name) for pid in lib.plugins if pid in by_id
                    ),
                )
                for lib in libraries
            ],
        ),
        prompts=(),
        status={
            "libraries": status_libraries,
            "plugins": status_plugins,
            "fetches": status_fetches,
        },
        live=revalidator,
        libraries=tuple(libraries),
        plugins=tuple(plugins),
        commands=commands,
        agent_files={pid: harvests[pid].agents for pid in admitted},
        skill_dirs={pid: _skill_folders(harvests[pid]) for pid in admitted},
    )


def _skill_folders(harvested: Harvest) -> tuple[str, ...]:
    """A harvested plugin's skill folders, as the plugin names them."""
    root = harvested.root or Path()
    return tuple(_relative(path, root) for path in harvested.skill_dirs)


def _commands(harvested: Harvest) -> PluginCommands:
    """A harvested plugin's prompt files, and the entries that read them."""
    dirs = harvested.command_dirs
    return PluginCommands(
        selected=harvested.prompts,
        claude=frozenset(harvested.claude_prompts),
        command_dirs=dirs,
        entries=harvest.command_entries(harvested.prompts, dirs),
    )


def _serve_library(
    lib: Library,
    by_id: dict[str, Plugin],
    harvests: dict[str, Harvest],
    admitted: dict[str, _Admitted],
    resources: LibraryFiles,
    served: dict[str, dict[str, int]],
    shadowed: dict[str, list[dict[str, str]]],
) -> tuple[dict, list[Skill]]:
    """One library's plugins in order: its ``/health`` entry and its skills.

    Each plugin's skills take their addresses here, in the library's folder for
    the plugin (``folder_for``): each library's is its own copy of the skill.
    Registers the library's files on ``resources`` as it goes. ``served`` is
    written for a plugin the first time any library serves it, since it is the
    plugin's own and the same in every library. Its
    ``prompts`` and ``agents`` counts are the plugin's selected prompt files
    and the agent files it found, until the plugin layer says what it served
    (``SkillServing._narrowed``), and so are the library's. ``shadowed`` -- its
    library files that lie inside its own skills -- depends on the folder each
    library gives it, so every library adds what it finds.
    """
    claims = _Claims()
    lib_categories = frozenset(lib.categories)
    entry: dict = {
        "description": lib.description,
        "categories": list(lib.categories),
        "plugins": list(lib.plugins),
        "skills": 0,
        "prompts": 0,
        "files": 0,
        "agents": 0,
    }
    conflicts: dict[str, str] = {}
    skills: list[Skill] = []
    for pid in lib.plugins:
        plugin = by_id[pid]
        if pid not in admitted:
            continue
        harvested = harvests[pid]
        root = harvested.root or Path()
        own = [
            replace(
                skill,
                library=lib.name,
                folder=folder_for(lib, plugin),
                category=plugin.category,
                tags=plugin.labels,
                library_categories=lib_categories,
                live=is_live(plugin.fetch),
            )
            for skill in admitted[pid].skills
        ]
        files, inside = _outside_skills(lib.name, own, admitted[pid].files)
        rows = shadowed.setdefault(pid, [])
        rows += [row for row in inside if row not in rows]
        conflict = claims.conflict(lib.name, own, files)
        if conflict is not None:
            conflicts[pid] = conflict
            continue
        claims.claim(lib.name, pid, own, files)
        skills += own
        resources.add(
            lib.name,
            root,
            files,
            list(harvested.skill_dirs),
            plugin=plugin,
            library_categories=lib_categories,
            agent_paths=[root / a for a in harvested.agent_paths],
        )
        counts = {
            "skills": len(own),
            "prompts": len(harvested.prompts),
            "files": len(files),
            "agents": len(harvested.agents),
        }
        served.setdefault(pid, counts)
        for key, count in counts.items():
            entry[key] += count
    if lib.error:
        entry["error"] = lib.error
    if lib.skipped:
        entry["skipped"] = list(lib.skipped)
    if conflicts:
        entry["conflicts"] = conflicts
    return entry, skills


def _plugin_status(
    plugin: Plugin,
    harvested: Harvest | None,
    libraries: list[str],
    admitted: _Admitted | None,
    served: dict[str, int] | None,
    left_out: list[dict[str, str]],
) -> dict:
    """One plugin's entry in ``/health``: what it is, and what it yielded."""
    entry: dict = {
        "status": harvested.status if harvested is not None else "failed",
        "fetch": plugin.fetch.key,
        "root": plugin.subdir,
        "category": plugin.category,
        "tags": sorted(plugin.tags),
        "keywords": sorted(plugin.keywords),
        **({"version": plugin.version} if plugin.version else {}),
        "libraries": libraries,
        # Already scrubbed and unrooted by with_manifest, which had the root.
        **({"notes": list(plugin.notes)} if plugin.notes else {}),
    }
    if harvested is None or admitted is None:
        # A harvest that is not ok carries why; one that never got a root has
        # nothing to say, and the key is typed as a string.
        entry["error"] = (harvested.error if harvested is not None else None) or (
            "not harvested"
        )
        return entry
    # The plugin's own counts, library-independent: what a library gets from
    # it. Its prompts are the files its harvest selected, parsed or not, and
    # its agents the agent files it found, until the plugin layer says what it
    # served of them (P9, AGT-14).
    counts = served or {
        "skills": len(admitted.skills),
        "prompts": len(harvested.prompts),
        "files": len(admitted.files),
        "agents": len(harvested.agents),
    }
    entry.update(counts)
    entry["built"] = harvested.built
    skipped = [*admitted.skipped, *left_out]
    if skipped:
        entry["skipped"] = skipped
    return entry


def _fetch_status(record: FetchRecord, live: bool) -> dict:
    """One fetch's ``/health`` entry, which the published contract describes.

    ``built`` and ``fingerprint`` describe the tree being served, so only a
    record that has one carries them: a failed fetch published an empty
    fingerprint and a timestamp for a tree nobody can read, which an operator
    cannot tell from a real one.
    """
    return {
        "status": record.status,
        **(
            {"built": record.built, "fingerprint": record.fingerprint}
            if record.status in SERVABLE
            else {}
        ),
        # Config, so it is here rather than in the counters /health merges
        # in: an operator has to be able to see that a fetch is live even
        # before anything has read one of its files.
        **({"live": True} if live else {}),
        # A failed record carries why it failed; a stale one why what is being
        # served stopped moving.
        **({"error": record.error} if record.error else {}),
    }


def log_changes(before: dict[str, dict], after: dict[str, dict]) -> None:
    """One log line for each thing a new snapshot changed.

    ``/health`` is where the state of every fetch, plugin and library can be
    read, and nothing reads it unprompted; the log is where a change of that
    state is *noticed*. So a fetch that fails, goes stale or recovers says so
    once, with its reason, when it happens -- at boot, where ``before`` is
    empty, and on every rebuild after -- and says nothing while it stays as it
    was. A library says what it serves whenever that count or its error
    changes, and once each agent it renames or leaves unserved; a plugin says
    once what it skips and once why it failed.
    """
    for key, now_ in after.get("fetches", {}).items():
        was = before.get("fetches", {}).get(key, {})
        state, error = now_.get("status"), now_.get("error")
        if (state, error) == (was.get("status"), was.get("error")):
            continue
        if state == "failed":
            log.error("fetch %s failed: %s", key, error)
        elif state == "stale":
            log.warning(
                "fetch %s is stale, still serving its last tree: %s", key, error
            )
        else:
            log.info("fetch %s is ok", key)

    for pid, now_ in after.get("plugins", {}).items():
        was = before.get("plugins", {}).get(pid, {})
        if now_.get("status") == "failed" and (
            (now_.get("status"), now_.get("error"))
            != (was.get("status"), was.get("error"))
        ):
            log.error("plugin %s failed: %s", pid, now_.get("error"))
        known = {row["path"] for row in was.get("skipped", ())}
        for row in now_.get("skipped", ()):
            if row["path"] not in known:
                log.warning("plugin %s skips %r: %s", pid, row["path"], row["reason"])
        noted = set(was.get("notes", ()))
        for note in now_.get("notes", ()):
            if note not in noted:
                log.warning("plugin %s: %s", pid, note)

    for name, now_ in after.get("libraries", {}).items():
        was = before.get("libraries", {}).get(name, {})
        watched = (
            "skills", "prompts", "files", "agents", "error", "conflicts",
            "renamed", "unserved",
        )
        if all(now_.get(k) == was.get(k) for k in watched):
            continue
        kinds = [("skills", "skill"), ("prompts", "prompt"), ("files", "file")]
        if now_.get("agents"):
            kinds.append(("agents", "agent"))
        counts = [_count(now_.get(key, 0), noun) for key, noun in kinds]
        log.info(
            "library %s is serving %s and %s",
            name,
            ", ".join(counts[:-1]),
            counts[-1],
        )
        if now_.get("error") and now_.get("error") != was.get("error"):
            log.warning("library %s: %s", name, now_["error"])
        for pid, message in now_.get("conflicts", {}).items():
            if message != was.get("conflicts", {}).get(pid):
                log.error("library %s: plugin %s: %s", name, pid, message)
        for agent, message in now_.get("renamed", {}).items():
            if message != was.get("renamed", {}).get(agent):
                log.info("library %s serves agent %s: %s", name, agent, message)
        unserved = was.get("unserved", ())
        for row in now_.get("unserved", ()):
            if row not in unserved:
                log.warning(
                    "library %s: plugin %s: agent %s is not served: %s",
                    name,
                    row["plugin"],
                    row["path"],
                    row["reason"],
                )


@dataclass(frozen=True)
class _Admitted:
    """What of one plugin the address space has room for, library-independent."""

    skills: list[Skill]
    files: list[str]
    skipped: list[dict[str, str]]


def _admit(harvested: Harvest) -> _Admitted:
    """What of one plugin the address space has room for, and what it has not.

    Returns the skills and library files to serve, and a
    ``skipped`` row -- the plugin-relative path and the reason -- for
    everything left out. A skipped thing is a defect in the plugin, not a
    failure of it: the rest serves, and ``/health`` says what is missing and
    why. Decided per plugin, not per library: a plugin's skills share one
    folder in any library (``folder_for``), so two of them meet below it as
    their names meet. Where a library file lies against them is the library's
    question, answered by ``_outside_skills``.

    A skill is left out when its frontmatter ``name`` breaks the Agent Skills
    naming rule or differs from its directory's name (a skill that is the whole
    plugin excepted) -- SEP-2640 makes the name the last segment of the
    address, so anything else mints a URI that does not resolve, or invents a
    folder -- and when a skill before it already has its name, and so its
    address, as one tree reaching a skill through two skill folders does.

    A library file is left out when it is named like an index the server
    generates.

    A prompt's or an agent's name is the plugin layer's to check, and to claim
    (PLG-25, AGT-6, AGT-8).
    """
    skipped: list[dict[str, str]] = []

    def skip(path: str, reason: str) -> None:
        # Not logged here: a snapshot is rebuilt on every refresh, and this
        # would repeat the same line each time. ``log_changes`` says it once.
        skipped.append({"path": path, "reason": reason})

    root = harvested.root or Path()
    served: dict[str, Skill] = {}
    for skill in harvested.skills:
        path = skill.path
        where = _relative(path, root)
        problem = naming_problem(skill.name)
        # A plugin that is one skill has no directory of its own to match: its
        # root is wherever the cache put it, a commit hash for a git fetch.
        at_root = where == "."
        if problem is None and not at_root and skill.name != path.name:
            problem = f"name {skill.name!r} differs from its directory {path.name!r}"
        if problem is None and skill.name in served:
            first = _relative(served[skill.name].path, root)
            problem = f"{skill.name} is already served by {first}"
        if problem is not None:
            skip(where, problem)
            continue
        served[skill.name] = skill

    files: list[str] = []
    for rel in harvested.files:
        name = PurePosixPath(rel).name
        if name in RESERVED_NAMES:
            skip(rel, f"{name} is the name of an index the server generates")
            continue
        files.append(rel)
    return _Admitted(list(served.values()), files, skipped)


def _outside_skills(
    library: str, skills: Sequence[Skill], files: Sequence[str]
) -> tuple[list[str], list[dict[str, str]]]:
    """The plugin's library files that do not lie against its own skills here.

    A file whose address is one of the plugin's skills', or lies inside one,
    is left out -- the skill answers that URI, so the file could be listed and
    never read, or read only under a scope that hides the skill -- with a
    ``skipped`` row saying which skill. Asked per library, because a skill's
    address is: ``loki/notes.md`` lies inside the main plugin's ``loki`` and
    beside a nested plugin's. Another plugin's skills are ``_Claims``'.
    """
    roots = sorted(
        (s.address.removeprefix(f"{library}/") for s in skills), key=len, reverse=True
    )
    kept: list[str] = []
    skipped: list[dict[str, str]] = []
    for rel in files:
        inside = next((r for r in roots if _overlap(rel, r)), None)
        if inside is None:
            kept.append(rel)
        else:
            reason = f"its address lies inside the skill at {inside}"
            skipped.append({"path": rel, "reason": reason})
    return kept, skipped


def unrooted(text: str, root: Path) -> str:
    """``text`` with the plugin's root taken out of any path it quotes.

    A parse or read error names the file it failed on, absolutely; in ``/health``
    that would be the cache path ``_relative`` keeps out of every other row.
    Public because the server reads a marketplace off the same kind of root
    and publishes what went wrong the same way.
    """
    for base in (root.resolve(), root):
        text = text.replace(f"{base}/", "")
    return text


def _relative(path: Path, root: Path) -> str:
    """``path`` as the plugin names it: relative to its root, never absolute.

    ``/health`` is unauthenticated, so a cache path does not belong in it. A
    harvest resolves the root it walks, so either spelling may be the prefix.
    """
    for base in (root, root.resolve()):
        if path.is_relative_to(base):
            return path.relative_to(base).as_posix()
    return path.name


def _within(address: str, root: str) -> bool:
    """Whether ``address`` is ``root`` or lies under it, segment-wise."""
    return address == root or address.startswith(f"{root}/")


def _overlap(a: str, b: str) -> bool:
    """Whether either address is the other or lies under it.

    Both directions matter: a file inside a skill shadows the skill's file, and a
    skill under a file's address turns that address into a directory that must
    serve nothing.
    """
    return _within(a, b) or _within(b, a)


@dataclass
class _Claims:
    """What one library's plugins serve so far, so a later one cannot shadow it.

    Two plugins feeding one library can mint the same skill URI or the same
    library-level file URI, and a reader could reach
    only one of each. Serving half of the later plugin would be worse than
    serving none of it -- its skills cite its own files -- so a conflict fails
    that plugin in this library. Overlap counts, not only equality: a library
    file inside another plugin's skill, or a skill inside another plugin's
    skill, overlaps it, in either direction.

    Per library, because addresses are: the same two plugins in two libraries
    are two independent questions, and a plugin failed here serves normally
    there.
    """

    skills: dict[str, str] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)

    def conflict(
        self,
        library: str,
        skills: list[Skill],
        files: list[str],
    ) -> str | None:
        """Why these cannot be served beside the claims, or None."""
        for skill in skills:
            root = f"{SCHEME}{skill.address}"
            for claimed, owner in self.skills.items():
                if _overlap(root, claimed):
                    return _taken(uri_for(skill), owner)
            for uri, owner in self.files.items():
                if _overlap(uri, root):
                    return _taken(uri, owner)
        for rel in files:
            uri = f"{SCHEME}{library}/{rel}"
            claims = (*self.files.items(), *self.skills.items())
            owner = next((o for c, o in claims if _overlap(uri, c)), None)
            if owner is not None:
                return _taken(uri, owner)
        return None

    def claim(
        self,
        library: str,
        plugin: str,
        skills: list[Skill],
        files: list[str],
    ) -> None:
        for skill in skills:
            self.skills.setdefault(f"{SCHEME}{skill.address}", plugin)
        for rel in files:
            self.files.setdefault(f"{SCHEME}{library}/{rel}", plugin)


def _taken(what: str, owner: str) -> str:
    return f"conflict: {what} is already served by plugin '{owner}'"


def _live_fetches(
    plugins: Iterable[Plugin], fetches: dict[str, FetchRecord]
) -> list[tuple[Fetch, Path]]:
    """Every live fetch that has a tree, paired with the tree it is served from.

    Taken from the records rather than from the cache layout, for the same
    reason ``fingerprint`` is: an export is keyed by its version, and the one
    to revalidate into is the one *this* snapshot serves.
    """
    found: dict[str, tuple[Fetch, Path]] = {}
    for plugin in plugins:
        fetch = plugin.fetch
        record = fetches.get(fetch.key)
        if not is_live(fetch) or record is None or fetch.key in found:
            continue
        if record.status not in SERVABLE or record.root is None:
            continue
        found[fetch.key] = (fetch, Path(record.root))
    return list(found.values())


def stale(record: FetchRecord, error: str) -> FetchRecord:
    """``record`` still served, marked stale, carrying why the refresh failed.

    ``built`` is left alone on purpose: it dates the tree being served, and
    that tree is the one this record already held. A refresh that fails
    changes what is *known* about the fetch, never what is on disk for it.
    """
    return replace(record, status="stale", error=error)


def failed_fetch(key: str, error: str) -> FetchRecord:
    return FetchRecord(
        key=key, status="failed", root=None, fingerprint={}, built=now(), error=error
    )


def failed_plugin(plugin: Plugin, error: str) -> Harvest:
    return Harvest(
        id=plugin.id, root=None, status="failed", error=error, built=now()
    )
