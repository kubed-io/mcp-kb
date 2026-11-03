"""A plugin's own ``plugin.json``: what it says it ships.

Claude's plugin manifest is the publisher's description of the plugin, so it
is read before the conventions are: a plugin that lists its ``skills`` and
``commands`` is telling us exactly which directories are which, and guessing
from the tree instead is how a repository's ``template/`` skill ends up served.

What it says is *not* trusted as a path. A published manifest is fetched
content, and a component path that escapes the plugin root is dropped rather
than raised: one bad entry must not cost the whole plugin, and nothing outside
the root may be served whatever a manifest asks for.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..catalogue.harvest import readable

MANIFEST_FILES = (".claude-plugin/plugin.json", "plugin.json")


COMPONENT_KEYS = ("skills", "commands", "agents", "hooks", "outputStyles", "themes")


@dataclass(frozen=True)
class CommandEntry:
    """One item of an object-map ``commands``: a name, and a file or a body."""

    name: str
    source: str | None
    content: str | None
    description: str | None
    argument_hint: str | None


@dataclass(frozen=True)
class Components:
    """What a manifest, or a marketplace entry, says the plugin ships."""

    skills: tuple[str, ...] | None = None  # "." is the plugin root
    commands: tuple[str, ...] | None = None  # patterns; () when only a map is set
    command_dirs: tuple[str, ...] = ()  # the directories among them
    command_map: tuple[CommandEntry, ...] = ()
    agents: tuple[str, ...] | None = None  # .md files only
    mcp_servers: tuple[str, ...] = ()  # names from an inline object
    mcp_files: tuple[str, ...] = ()  # paths a string mcpServers names
    named: frozenset[str] = frozenset()  # which of COMPONENT_KEYS are present
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Manifest:
    name: str | None
    description: str | None
    version: str | None
    keywords: tuple[str, ...]
    components: Components


def manifest_file(root: Path) -> str | None:
    """Which of ``MANIFEST_FILES`` the plugin ships, root-relative: the one read.

    Also what an inline object-map command is named by in ``/health``, since
    the manifest is the only file it has.
    """
    return next((name for name in MANIFEST_FILES if readable(root, name)), None)


def read_manifest(root: Path) -> Manifest | None:
    """The plugin's manifest, or None when it ships none.

    Found through ``readable``, the guard every read shares: a ``plugin.json``
    that is a symlink out of the root is not this plugin's manifest, and
    ``is_file()`` alone would follow it and let a foreign file's description
    and keywords into the catalogue. A link inside the root still resolves,
    which is the ConfigMap case.
    """
    name = manifest_file(root)
    if name is None:
        return None
    path = readable(root, name)
    if path is None:
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} is not readable JSON: {exc}") from exc
    except RecursionError:
        # Fetched content nested past the parser's stack: the plugin's failure,
        # not the server's, and nothing of the file is quoted back.
        raise ValueError(f"{name} is nested too deeply to read") from None
    if not isinstance(data, dict):
        raise ValueError(f"{name} must be a JSON object")

    return Manifest(
        name=_text(data.get("name")),
        description=_text(data.get("description")),
        version=_text(data.get("version")),
        keywords=_strings(data.get("keywords"), "keywords") or (),
        components=read_components(data),
    )


def read_components(data: dict) -> Components:
    """Every component key of a manifest or a marketplace entry, read.

    A wrong-typed field raises ``ValueError`` naming it; any other defect in
    what a publisher wrote is a note, so one bad item costs only itself.
    """
    notes: list[str] = []
    skills = _paths(data.get("skills"), "skills", notes)
    commands, command_dirs, command_map = _commands(data.get("commands"), notes)
    agents = _agents(data.get("agents"), notes)
    servers, files = _mcp(data.get("mcpServers"), notes)
    return Components(
        skills=skills,
        commands=commands,
        command_dirs=command_dirs,
        command_map=command_map,
        agents=agents,
        mcp_servers=servers,
        mcp_files=files,
        named=frozenset(key for key in COMPONENT_KEYS if key in data),
        notes=tuple(notes),
    )


def _paths(value: object, field: str, notes: list[str]) -> tuple[str, ...] | None:
    found = _strings(value, field)
    if found is None:
        return None
    kept = (_inside(item, field, notes) for item in found)
    return tuple(dict.fromkeys(cleaned for cleaned in kept if cleaned))


def _commands(
    value: object, notes: list[str]
) -> tuple[tuple[str, ...] | None, tuple[str, ...], tuple[CommandEntry, ...]]:
    if isinstance(value, dict):
        return (), (), _command_map(value, notes)
    found = _paths(value, "commands", notes)
    if found is None:
        return None, (), ()
    patterns: list[str] = []
    dirs: list[str] = []
    for path in found:
        if path.endswith(".md"):
            patterns.append(path)
            continue
        dirs.append(path)
        patterns.append("**/*.md" if path == "." else f"{path}/**/*.md")
    return tuple(patterns), tuple(dirs), ()


def _command_map(value: dict, notes: list[str]) -> tuple[CommandEntry, ...]:
    entries = []
    for name, item in value.items():
        if not isinstance(item, dict):
            notes.append(f"commands entry '{name}' is not an object")
            continue
        source, content = item.get("source"), item.get("content")
        if (source is None) == (content is None):
            notes.append(
                f"commands entry '{name}' needs exactly one of source and content"
            )
            continue
        if source is not None:
            if isinstance(source, str):
                source = _inside(source, "commands", notes)
            else:
                source = ""
            if not source:
                notes.append(f"commands entry '{name}' has no usable source")
                continue
        elif not isinstance(content, str):
            notes.append(f"commands entry '{name}' content is not text")
            continue
        entries.append(
            CommandEntry(
                name=str(name),
                source=source,
                content=content,
                description=_text(item.get("description")),
                argument_hint=_text(item.get("argumentHint")),
            )
        )
    return tuple(entries)


def _agents(value: object, notes: list[str]) -> tuple[str, ...] | None:
    found = _paths(value, "agents", notes)
    if found is None:
        return None
    kept = []
    for path in found:
        if path.endswith(".md"):
            kept.append(path)
        else:
            notes.append(f"agents entry '{path}' is not a .md file")
    return tuple(kept)


def _mcp(value: object, notes: list[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if value is None:
        return (), ()
    if isinstance(value, dict):
        return tuple(str(name) for name in value), ()
    if isinstance(value, str):
        path = _inside(value, "mcpServers", notes)
        return (), ((path,) if path else ())
    notes.append("mcpServers must be an object or a path")
    return (), ()


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _strings(value: object, field: str) -> tuple[str, ...] | None:
    """A field that may be written as one string or as a list of them."""
    if value is None:
        return None
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise ValueError(f"{field} must be a string or a list of strings")


def _inside(text: str, field: str, notes: list[str]) -> str:
    """``text`` as a root-relative path, or ``""`` when it leaves the root.

    ``"."`` names the plugin root itself. A path that does not start ``./`` is
    kept, and noted: Claude requires the prefix, and a publisher who left it
    off should hear that.
    """
    path = text.strip()
    if path in (".", "./"):
        return "."
    relative = path.removeprefix("./")
    if not relative or path.startswith("/") or ".." in PurePosixPath(relative).parts:
        notes.append(f"{field} path '{path}' leaves the plugin root")
        return ""
    if relative == path:
        notes.append(f"{field} path '{path}' does not start with ./")
    return relative
