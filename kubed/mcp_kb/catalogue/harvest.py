"""Turn a plugin's directory into the things the catalogue serves.

A plugin root is a directory (``sources/`` materialised the tree it sits in).
Its skills are found the way Claude Code and kubed-mcp find them
(``skill_dirs``): each folder directly in ``skills/`` that holds a ``SKILL.md``,
then the folders a manifest, an entry or the config declares. Its prompts and
library files are a set of globs per kind, and the conventions below are the
defaults. Setting a prompt or file kind *replaces* its default rather than
appending to it -- an append would leave no way to stop serving a convention --
and an empty list turns a kind off.

Everything found is resolved and checked to lie inside the root, the same
guard ``uris.py`` applies on read, so a glob like ``../**`` finds nothing.
Dot directories are skipped, except the three that agent tooling conventionally
lives in. A backend's *fingerprint* walk sees one more of them --
``FINGERPRINTED_DOTDIRS`` below says which, and why the two sets differ.

``dir/**`` and ``dir/**/*`` mean the same thing here: ``patterns`` normalises
the first into the second, because a trailing ``**`` matches directories only
before Python 3.13 and a config should not depend on which interpreter is
running it.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..plugins import Globs

MAIN_FILE = "SKILL.md"

AGENTS_DIR = "agents"

PLUGIN_ROOT = PurePosixPath(".")

# The folder whose direct children are a plugin's skills by convention.
SKILLS_DIR = "skills"

DEFAULTS: dict[str, tuple[str, ...]] = {
    "prompts": ("prompts/**/*.md", ".github/prompts/*.prompt.md", "commands/**/*.md"),
    "files": (),
}

# The directories whose markdown files are Claude Code commands by convention.
# A file there is read in Claude's dialect unless the plugin says otherwise, and
# named by the folders below the directory as well as its stem (PLG-25);
# detect.py cannot see paths, so the caller says it (§C1.34).
COMMAND_DIRS: tuple[str, ...] = ("commands", ".claude/commands")

# The dot directories agent tooling keeps its files in. Never hidden, so a
# prompt convention (``.github/prompts``, ``.claude/commands``), a ``files:``
# glob or a declared skill folder can reach into one.
CONVENTIONAL_DOTDIRS: frozenset[str] = frozenset({".github", ".claude", ".agents"})

# Where this server's own metadata files live: a `marketplace.json` and a
# `plugin.json` (`plugins/marketplace.py`, `plugins/manifest.py`). Deliberately
# *not* in CONVENTIONAL_DOTDIRS, and the two sets differ for one reason --
# `hidden` keeps these out of every listing, because a catalogue and a manifest
# are what say *what* to serve and are not themselves a skill, a prompt or a
# library file, while a backend's fingerprint walk has to see them or editing a
# local marketplace never looks like a change and a configured `refresh:` never
# re-reads it.
METADATA_DOTDIRS: frozenset[str] = frozenset({".claude-plugin"})

# What a fingerprint descends into: everything a harvest reads, plus the
# directories holding the files that decide what a harvest reads.
FINGERPRINTED_DOTDIRS: frozenset[str] = CONVENTIONAL_DOTDIRS | METADATA_DOTDIRS


def patterns(kind: str, globs: Globs) -> tuple[str, ...]:
    """The globs for one kind: what ``globs`` says, else the conventions."""
    explicit = getattr(globs, kind)
    chosen = tuple(explicit) if explicit is not None else DEFAULTS[kind]
    return tuple(_globstar(p) for p in chosen)


def _globstar(pattern: str) -> str:
    """Normalise a pattern whose last *component* is ``**`` to ``**/*``.

    Before Python 3.13 a trailing ``**`` matches directories *only*, so
    ``shared/**`` finds the folders under ``shared`` and none of the files in
    them; from 3.13 it matches both. A config is not a place to encode an
    interpreter version, and the failure is silent -- ``files: ["shared/**"]``
    served penpot's 29 shared files on one runtime and nothing at all on
    another, with no error either way. Whoever writes it means "everything
    underneath", so that is what it becomes, identically on every version.

    Only a whole component counts. ``logs**`` is not a globstar at all -- it
    matches names beginning with "logs", so rewriting it to ``logs**/*`` would
    quietly change it to mean the descendants of those names instead.
    """
    return f"{pattern}/*" if pattern == "**" or pattern.endswith("/**") else pattern


def hidden(rel: Path) -> bool:
    """Whether a path relative to a plugin root is one this project ignores."""
    return any(
        part.startswith(".") and part not in CONVENTIONAL_DOTDIRS for part in rel.parts
    )


def _matches(base: Path, pattern: str) -> Iterator[Path]:
    """Every glob hit that is safely inside ``base``, as the path that matched.

    Shared by every glob kind so the guards are written once: a hit that
    escapes the root is rejected whether it turns out to be a file or a
    directory.

    The *resolved* path decides containment and nothing else. What is yielded,
    and so what becomes a catalogue row, an index entry or a ``skill://`` path,
    is the path the config asked for: a ConfigMap key ``shared/foo.md`` resolves
    to ``..<timestamp>/shared/foo.md``, a name no client asked for and a
    directory Kubernetes deletes on the next update.

    ``"."`` is the plugin root itself, a directory hit: ``Path.glob(".")``
    raises rather than answer it.

    A pattern ``Path.glob`` refuses matches nothing: before Python 3.13 a
    ``**`` inside a component (``"x**.md"``) raises ``ValueError``, and the
    pattern can be a fetched manifest's, which must not fail a build.
    """
    if PurePosixPath(pattern) == PLUGIN_ROOT:
        hits: Iterable[Path] = [base]
    else:
        try:
            hits = list(base.glob(pattern))
        except ValueError:
            return
    for hit in hits:
        # A pattern like "../**" can walk out of base and straight back in
        # -- resolve() then quietly collapses the ".." and the hit looks
        # like a plain interior file. Reject the escape before resolving.
        # PluginConfig's glob validator refuses such a pattern before it
        # ever reaches here; this is defence in depth, not the first line.
        if ".." in hit.relative_to(base).parts:
            continue
        # Hidden-ness is a property of the path that was asked for, not of
        # wherever a symlink lands. A Kubernetes ConfigMap mounts every key
        # as `key -> ..data/key -> ..<timestamp>/key`, so judging the
        # resolved path discards the whole mount as hidden -- which is the
        # one thing a `file://` source is for here. Containment below is
        # the security property; the target's NAME is the filesystem's
        # business.
        if hidden(hit.relative_to(base)):
            continue
        if inside(hit, base) is not None:
            yield hit


def inside(path: Path, base: Path) -> Path | None:
    """``path`` resolved, or None when it escapes ``base`` or cannot resolve.

    Before Python 3.13 a symlink loop makes ``resolve()`` raise ``RuntimeError``
    rather than ``OSError``; one malformed link must fail that link, not the
    whole harvest.
    """
    try:
        target = path.resolve()
    except (OSError, RuntimeError):
        return None
    return target if target.is_relative_to(base) else None


def readable(base: Path, rel: str | Path) -> Path | None:
    """``base / rel`` resolved, when it is a regular file inside ``base``.

    The guard every read shares -- a skill's own file, its plugin root's, and a
    library file (``uris.py``, ``skills.py``). Resolving before comparing is
    what refuses a ``..`` that climbs out and a symlink pointing out of the
    tree; a directory and a missing path are refused because neither is a body.
    """
    root = base.resolve()
    target = inside(root / rel, root)
    return target if target is not None and target.is_file() else None


def listed(root: Path, rels: Iterable[str]) -> list[Path]:
    """Each of ``rels`` that is a regular file inside ``root``, sorted.

    A path, not a glob, as Claude Code reads a manifest's ``agents``:
    ``agents/[draft].md`` is that file, not a character class. What is
    returned is the spelling asked for, as ``_matches`` keeps it, so a
    ConfigMap key is not swapped for the ``..<timestamp>`` it resolves to.
    """
    base = root.resolve()
    return sorted({base / rel for rel in rels if readable(base, rel) is not None})


def matching(root: Path, globs: Iterable[str]) -> set[Path]:
    """Every regular file inside ``root`` that one of ``globs`` selects.

    Separate from ``files`` because a pattern set is not always a kind: the
    command patterns a manifest declared are matched against the prompts
    already harvested, to tell which of them the plugin called a command.
    """
    base = root.resolve()
    return {
        hit
        for pattern in globs
        for hit in _matches(base, _globstar(pattern))
        if hit.is_file()
    }


def files(root: Path, kind: str, globs: Globs) -> list[Path]:
    """Every regular file matching the kind's globs, inside root, sorted."""
    return sorted(matching(root, patterns(kind, globs)))


def agent_files(root: Path, globs: Globs) -> list[tuple[Path, tuple[str, ...]]]:
    """Each agent file, sorted, with the folders that name it.

    The default scan (``agents/**/*.md``) names an agent by the folders between
    ``agents/`` and the file; a file the plugin listed has none (AGT-5).
    """
    if globs.agents == ():
        return []
    base = root.resolve()
    if globs.agents is not None:
        return [(f, ()) for f in listed(root, globs.agents)]
    return [
        (f, f.relative_to(base / AGENTS_DIR).parts[:-1])
        for f in sorted(matching(root, (f"{AGENTS_DIR}/**/*.md",)))
    ]


def agent_paths(root: Path, globs: Globs) -> tuple[Path, ...]:
    """The ``agents/`` directory and every listed file: what a fallback refuses."""
    if globs.agents == ():
        return ()
    base = root.resolve()
    found: list[Path] = []
    folder = inside(base / AGENTS_DIR, base)
    if folder is not None and folder.is_dir():
        found.append(base / AGENTS_DIR)
    if globs.agents is not None:
        found += listed(root, globs.agents)
    return tuple(found)


def skill_dirs(root: Path, declared: Sequence[str] = ()) -> list[Path]:
    """A plugin's skill folders, in the order they are claimed.

    The rule Claude Code and kubed-mcp read a plugin by, and nothing deeper.
    ``skills/`` is read first and then each of ``declared``, in order, and each
    is read the same way: the folder itself when it holds a ``SKILL.md``, else
    each folder directly in it that does, by name. A folder reached twice is
    found once, where it was first reached.

    A folder named ``.…`` directly in one is never a skill, and neither is one
    that is itself a symlink: ``os.walk``, which kubed-mcp reads a folder with,
    does not descend into either. The folder read may be a symlink, as
    ``os.walk``'s top may be -- a ConfigMap mounts ``skills -> ..data/skills``.
    A path that is not a folder inside the root finds nothing, and neither
    does a ``SKILL.md`` symlinked out of it. ``skills/g/b/SKILL.md`` is not a
    skill unless ``skills/g`` or ``skills/g/b`` is declared.

    What is returned is the path as it was reached, not its symlink target, so
    a ConfigMap key is not swapped for the ``..<timestamp>`` it resolves to.
    """
    base = root.resolve()
    found: dict[Path, None] = {}
    for folder in (SKILLS_DIR, *declared):
        for skill in _skills_in(base, folder):
            found.setdefault(skill)
    return list(found)


def _skills_in(base: Path, folder: str) -> list[Path]:
    """The skill ``folder`` is, or the skills directly in it, sorted."""
    start = base / folder
    if inside(start, base) is None or not start.is_dir():
        return []
    if _is_skill(start, base):
        return [start]
    try:
        children = sorted(start.iterdir())
    except OSError:
        return []
    return [
        child
        for child in children
        if not child.name.startswith(".")
        and not child.is_symlink()
        and child.is_dir()
        and _is_skill(child, base)
    ]


def _is_skill(folder: Path, base: Path) -> bool:
    """Whether ``folder`` holds a ``SKILL.md`` that is a regular file in ``base``."""
    main = inside(folder / MAIN_FILE, base)
    return main is not None and main.is_file()


def command_files(root: Path, globs: Globs) -> set[Path]:
    """Every file a ``commands`` declaration selects, which makes it ``claude``.

    A listed folder's escaped pattern, and each listed file read as the path it
    spells (PLG-21), as ``listed`` reads a manifest's agents: in a dot folder
    too, and never one that resolves outside the plugin.
    """
    return matching(root, globs.commands) | set(listed(root, globs.command_files))


def prompt_files(root: Path, globs: Globs) -> list[Path]:
    """The prompt globs' matches, and the command files a declaration lists."""
    return sorted(
        matching(root, patterns("prompts", globs))
        | set(listed(root, globs.command_files))
    )


def command_entries(
    selected: Sequence[str], command_dirs: Sequence[str]
) -> tuple[str, ...]:
    """The ``commands`` paths the plugin layer reads ``selected`` through (D1).

    ``selected`` is a plugin's prompt files, root-relative and in path order.
    A file under a command folder -- a convention's or one of ``command_dirs``,
    the deepest that contains it, as ``prompts.prompt_name`` decides, and
    ``"."`` containing every path -- brings that folder in, so the layer names
    it by the folders below it (PLG-25); any other file is an entry of its own,
    named by its stem. Each entry comes once, at its first file, so the layer
    reads in kb's order and the first of two same-named files is the one served.
    """
    folders = [PurePosixPath(d).parts for d in (*COMMAND_DIRS, *command_dirs)]
    entries: dict[str, None] = {}
    for rel in selected:
        parts = PurePosixPath(rel).parts
        depth = max(
            (
                len(prefix)
                for prefix in folders
                if len(prefix) < len(parts) and parts[: len(prefix)] == prefix
            ),
            default=None,
        )
        entry = rel if depth is None else PurePosixPath(*parts[:depth]).as_posix()
        entries.setdefault(entry, None)
    return tuple(entries)


def library_files(root: Path, globs: Globs, skill_dirs: Sequence[Path]) -> list[str]:
    """Library-level files as root-relative posix paths, never one inside a skill."""
    base = root.resolve()
    skills = tuple(skill_dirs)
    return [
        f.relative_to(base).as_posix()
        for f in files(root, "files", globs)
        if not any(f == d or d in f.parents for d in skills)
    ]

