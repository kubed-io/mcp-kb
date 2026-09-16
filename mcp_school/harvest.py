"""Turn a source directory into the things the catalogue serves.

A source is a directory (``sources/`` produced it); what to serve out of it is
a set of globs per kind, and the conventions below are the defaults. Setting a
kind *replaces* its default rather than appending to it -- an append would
leave no way to stop serving a convention -- and an empty list turns a kind
off.

Everything found is resolved and checked to lie inside the root, the same
guard ``uris.py`` applies on read, so a glob like ``../**`` finds nothing.
Dot directories are skipped, except the three that agent tooling conventionally
lives in.

``dir/**`` and ``dir/**/*`` mean the same thing here: ``patterns`` normalises
the first into the second, because a trailing ``**`` matches directories only
before Python 3.13 and a config should not depend on which interpreter is
running it.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

from .config import Include

MAIN_FILE = "SKILL.md"

DEFAULTS: dict[str, tuple[str, ...]] = {
    "skills": (
        "skills/**/SKILL.md",
        ".github/skills/*/SKILL.md",
        ".claude/skills/*/SKILL.md",
        ".agents/skills/*/SKILL.md",
    ),
    "prompts": ("prompts/**/*.md", ".github/prompts/*.prompt.md", "commands/*.md"),
    "instructions": (
        ".github/copilot-instructions.md",
        ".github/instructions/*.instructions.md",
        "AGENTS.md",
        "CLAUDE.md",
    ),
    "agents": (".github/agents/*.agent.md", "agents/*.md"),
    "files": (),
}

# The directories that hold skills by convention. A skill directly under one of
# these has no group of its own; anything deeper is grouped by its parent.
SKILL_ROOTS: tuple[str, ...] = (
    "",
    "skills",
    ".github/skills",
    ".claude/skills",
    ".agents/skills",
)

CONVENTIONAL_DOTDIRS: frozenset[str] = frozenset({".github", ".claude", ".agents"})


def patterns(kind: str, include: Include) -> tuple[str, ...]:
    explicit = getattr(include, kind)
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
    """Whether a path relative to a source root is one this project ignores."""
    return any(
        part.startswith(".") and part not in CONVENTIONAL_DOTDIRS for part in rel.parts
    )


def _matches(base: Path, pattern: str) -> Iterator[Path]:
    """Every glob hit that is safely inside ``base``, resolved.

    Shared by ``files`` and ``skill_dirs`` so the guards are written once: a
    hit that escapes the root is rejected whether it turns out to be a file or
    a directory.
    """
    for hit in base.glob(pattern):
        # A pattern like "../**" can walk out of base and straight back in
        # -- resolve() then quietly collapses the ".." and the hit looks
        # like a plain interior file. Reject the escape before resolving.
        # config.py's Include validator refuses such a pattern before it
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
        target = hit.resolve()
        if target.is_relative_to(base):
            yield target


def files(root: Path, kind: str, include: Include) -> list[Path]:
    """Every regular file matching the kind's globs, resolved, inside root, sorted."""
    base = root.resolve()
    found = {
        target
        for pattern in patterns(kind, include)
        for target in _matches(base, pattern)
        if target.is_file()
    }
    return sorted(found)


def skill_dirs(root: Path, include: Include) -> list[Path]:
    """The skill directories a source's ``include.skills`` globs select.

    A glob may name either the ``SKILL.md`` or the *directory*, because both
    spellings mean the same thing to whoever writes the config:

        skills: ["skills/*/SKILL.md"]   # the file that makes it a skill
        skills: ["skills/*"]            # each of those folders IS a skill
        skills: ["skills"]              # everything under here is

    A matched directory contributes every skill beneath it, so pointing at a
    leaf registers one and pointing at a composite registers the set -- which
    is what a folder of folders already means to a reader. Without this, the
    directory spelling matched nothing and said nothing, the same silent empty
    a trailing ``**`` used to give.
    """
    base = root.resolve()
    found: set[Path] = set()
    for pattern in patterns("skills", include):
        for target in _matches(base, pattern):
            if target.is_file():
                if target.name == MAIN_FILE:
                    found.add(target.parent)
            elif target.is_dir():
                found.update(
                    main.parent
                    for main in target.rglob(MAIN_FILE)
                    if main.is_file() and not hidden(main.relative_to(base))
                )
    return sorted(found)


def prompt_files(root: Path, include: Include) -> list[Path]:
    return files(root, "prompts", include)


def pack_files(root: Path, include: Include, skill_dirs: Sequence[Path]) -> list[str]:
    """Pack-level files as root-relative posix paths, never one inside a skill."""
    base = root.resolve()
    inside = tuple(d.resolve() for d in skill_dirs)
    return [
        f.relative_to(base).as_posix()
        for f in files(root, "files", include)
        if not any(f == d or d in f.parents for d in inside)
    ]


def group_of(skill_dir: Path, root: Path) -> str | None:
    """The directory containing a skill, unless that is one of the skill roots."""
    parent = skill_dir.resolve().parent
    rel = parent.relative_to(root.resolve()).as_posix()
    return None if rel in SKILL_ROOTS or rel == "." else parent.name
