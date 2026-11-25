"""Prompt files: parsed, with no FastMCP anywhere in the chain.

A prompt file is YAML frontmatter plus a body::

    ---
    description: One line for the prompt picker.
    arguments:
    - name: app
      description: Shown to whoever fills it in.
      required: true
    - name: since
      default: 1h
    ---
    Investigate {{ app }} over the last {{ since }}.

That is this server's own dialect, and it is one of three. Point the server at
a Claude Code command or a VS Code Copilot ``.prompt.md`` and the same MCP
prompt comes out: ``detect.py`` decides which dialect a file is written in and
``mcpkb.py``, ``claude.py`` and ``copilot.py`` each read one of them into the
same ``Parsed`` and render it back. None of them invents a schema -- the
target is the MCP prompt itself (§C1.34).

The exposed name is ``<library>_<name>``, and the name below the library is
decided where the prompt was found (PLG-25, ``prompt_name``): the folders below
a commands directory and the file stem, or the stem
alone. Prompt names are one flat namespace per server, and two libraries
shipping a ``debug.md`` must not collide the way two skills named ``testing``
otherwise would.

Nothing here reads a file. The plugin layer reads each prompt file kb's
harvest selected and hands its text to kb's command reader, which parses it
with ``parse_prompt`` in the dialect ``dialect_of`` decides (PRM-18). Qualified
names and ``${CLAUDE_PLUGIN_ROOT}`` are rendered into the body when a build is
made; ``FilePrompt.render`` fills in the dialect's own placeholders and nothing
else (PRM-47).

``FilePrompt`` here is a plain dataclass -- the catalogue's own parsed form,
with no pydantic and no FastMCP base class -- so ``catalogue/snapshot.py`` can
hold it without importing FastMCP at all. ``kubed/mcp_kb/mcp/prompts.py`` is
where a ``FilePrompt`` becomes something FastMCP can serve.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import frontmatter
import yaml

from ..harvest import COMMAND_DIRS
from . import claude, copilot, detect, mcpkb
from .mcpkb import PLACEHOLDER
from .shape import Argument, Parsed

log = logging.getLogger(__name__)

# What a malformed prompt's text raises; a file's read adds OSError to it.
READ_ERRORS = (ValueError, TypeError, yaml.YAMLError)

DIALECTS = {module.NAME: module for module in (mcpkb, claude, copilot)}

__all__ = [
    "DIALECTS",
    "PLACEHOLDER",
    "READ_ERRORS",
    "Argument",
    "FilePrompt",
    "MissingArguments",
    "Parsed",
    "dialect_of",
    "parse_prompt",
    "prompt_name",
    "stem",
]


@dataclass
class FilePrompt:
    """One prompt file, rendered by substituting its placeholders.

    ``path`` is where its text was read from, which ``detect`` reads the suffix
    of; the text itself is ``template``, the body as the build rendered it.

    ``plugin``, ``category`` and ``tags`` are the plugin's: what a scope matches
    a prompt on, since a prompt has no library of its own beyond the one that
    named it.

    ``dialect`` is which module renders it, decided when the plugin is read:
    the body's placeholders mean different things in each, so it travels with
    the prompt rather than being sniffed again per render, and a build's
    re-read reads in it too.
    """

    path: Path
    name: str
    library: str
    plugin: str = ""
    template: str = ""
    description: str | None = None
    title: str | None = None
    arguments: list[Argument] = field(default_factory=list)
    tags: set[str] = field(default_factory=set)
    category: str | None = None
    library_categories: frozenset[str] = frozenset()
    defaults: dict[str, str] = field(default_factory=dict)
    dialect: str = mcpkb.NAME

    def render(self, arguments: dict[str, object] | None = None) -> str:
        """Fill in the placeholders, raising ``MissingArguments`` on a missing one.

        ``values`` is built from ``self.arguments`` rather than from what was
        passed, so it holds every declared argument, in the order the file
        declared them: Claude's `$1` is the first declared name, and that order
        is knowable nowhere else.

        The dialect's placeholders are all that is filled in here. Qualified
        names and ``${CLAUDE_PLUGIN_ROOT}`` were rendered into ``template``
        when the build was made, so an argument's value is never rewritten,
        whatever it holds (PRM-47).

        Plain and synchronous: the FastMCP-facing wrapper is what turns this
        into the async ``render`` a ``Prompt`` subclass must provide, and what
        turns a raised ``ValueError`` into whatever error shape FastMCP wants.
        """
        # A field left blank arrives as "" from most prompt pickers, so it
        # counts as not given: a default applies, and a required argument
        # fails.
        given = {
            key: str(value)
            for key, value in (arguments or {}).items()
            if value not in (None, "")
        }
        missing = [
            arg.name for arg in self.arguments if arg.required and arg.name not in given
        ]
        if missing:
            raise MissingArguments(self.name, missing)
        values = {
            arg.name: given.get(arg.name, self.defaults.get(arg.name, ""))
            for arg in self.arguments
        }
        return DIALECTS[self.dialect].substitute(self.template, values)


class MissingArguments(ValueError):
    """A render was asked for without a required argument: the caller's mistake."""

    def __init__(self, prompt: str, names: list[str]):
        self.prompt = prompt
        self.names = names
        super().__init__(
            f"Prompt {prompt!r} needs the argument"
            f"{'s' if len(names) > 1 else ''} {', '.join(names)}."
        )


NOT_TEXT_KEY = "frontmatter has a key that is not a string"
TOO_DEEP = "frontmatter is nested too deeply to read"


class _NoFrontmatter(ValueError):
    """No frontmatter block at all: a file's failure."""


def _split(text: str) -> tuple[dict, str]:
    """Frontmatter and body, raising ValueError when there is no frontmatter block.

    ``frontmatter.loads`` returns empty metadata both for "no block" and for an
    "empty block" (``---\\n---\\nbody``) -- the latter is valid, so absence is
    told apart by comparing the stripped content back against the stripped
    whole text: only "no block at all" (including an unterminated one, which
    the library also parses as empty metadata over the whole text) leaves them
    equal. ``.content`` is ``rstrip``-ped by the library, which would silently
    drop a template's trailing newline; the body is re-sliced from the original
    text by length instead of by ``str.index``, which would find the first
    occurrence of the content anywhere -- including inside the frontmatter
    block itself, when the body text happens to recur there -- so a LogQL line
    like ``|= "error"\\n`` renders exactly as written.
    """
    try:
        post = frontmatter.loads(text)
    except TypeError:
        # A key like `1:` or `true:` -- python-frontmatter passes the mapping
        # as keyword arguments. Fetched content, so the reason quotes none.
        raise ValueError(NOT_TEXT_KEY) from None
    except RecursionError:
        # Nested past the parser's stack: a file's failure, not the build's.
        raise ValueError(TOO_DEEP) from None
    if post.metadata == {} and post.content.strip() == text.strip():
        raise _NoFrontmatter("no YAML frontmatter")
    meta = post.metadata if isinstance(post.metadata, dict) else {}
    if not post.content:
        return meta, ""
    start = len(text.rstrip()) - len(post.content)
    return meta, text[start:]


def stem(path: Path) -> str:
    """The file's name without its extension, ``.prompt.md`` counting as one.

    ``investigate.prompt.md`` is Copilot's spelling of ``investigate``: the
    ``.prompt`` is the convention that marks the file, not part of what the
    prompt is called.
    """
    if path.name.endswith(detect.COPILOT_SUFFIX):
        return path.name[: -len(detect.COPILOT_SUFFIX)]
    return path.stem


def prompt_name(path: Path, root: Path, command_dirs: Sequence[str]) -> str:
    """The name below its library of a prompt file found at ``path`` (PLG-25).

    Under a commands directory -- a convention's or one a ``commands``
    declaration named, the deepest that contains the file -- the folders
    between it and the file come first, then the stem, joined with ``_``:
    ``commands/db/migrate.md`` is ``db_migrate``. Anywhere else it is the stem,
    so ``prompts/sub/debug.md`` is ``debug`` as it has always been. A harvest
    resolves the root it walks, so either spelling of ``root`` may be the
    prefix.
    """
    rel = next(
        (
            PurePosixPath(path.relative_to(base).as_posix())
            for base in (root, root.resolve())
            if path.is_relative_to(base)
        ),
        None,
    )
    if rel is None:
        return stem(path)
    parts = rel.parts
    depth = max(
        (
            len(prefix)
            for prefix in (
                PurePosixPath(d).parts for d in (*COMMAND_DIRS, *command_dirs)
            )
            if len(prefix) < len(parts) and parts[: len(prefix)] == prefix
        ),
        default=None,
    )
    if depth is None:
        return stem(path)
    return "_".join((*parts[depth:-1], stem(path)))


def parse_prompt(
    text: str,
    path: Path,
    *,
    name: str,
    library: str,
    plugin: str = "",
    tags: Sequence[str] = (),
    category: str | None = None,
    library_categories: frozenset[str] = frozenset(),
    dialect: str = detect.AUTO,
) -> FilePrompt:
    """Parse one prompt from its ``text``, which is never read from ``path``.

    ``name`` is the full served name, ``<library>_<name below it>``. ``path``
    only says where the text came from, and ``detect`` reads its suffix.
    Raises one of ``READ_ERRORS`` for a malformed one.
    """
    meta, body = _split(text)
    return _build(
        meta,
        body,
        path,
        name=name,
        library=library,
        plugin=plugin,
        tags=tags,
        category=category,
        library_categories=library_categories,
        dialect=dialect,
    )


def dialect_of(rel: str, *, configured: str, claude: Collection[str]) -> str:
    """The dialect a harvested file is read in: the plugin's, else how it was found.

    ``rel`` is the file's path below its plugin root, in posix form (PRM-14,
    rules 2 to 5). ``configured`` is the plugin's ``dialect``; ``claude`` holds
    the paths a ``commands`` declaration matched. ``"auto"`` leaves the rest to
    ``detect``.

    A file a publisher called a command is Claude's wherever it put it:
    penpot declares seven under ``prompts/``, and left to the body a
    description-only one would read as this server's own dialect. A config's
    own ``prompts:`` glob is not a command declaration and puts nothing in
    ``claude``.

    A ``.prompt.md`` is the exception to the last two: a filename that names its
    own dialect beats the directory it sits in, so ``detect`` reads it as
    Copilot's.
    """
    if configured != detect.AUTO:
        return configured
    if rel.endswith(detect.COPILOT_SUFFIX):
        return detect.AUTO
    if any(rel.startswith(f"{d}/") for d in COMMAND_DIRS):
        return "claude"
    if rel in claude:
        return "claude"
    return detect.AUTO


def _build(
    meta: dict,
    body: str,
    path: Path,
    *,
    name: str,
    library: str,
    plugin: str,
    tags: Sequence[str],
    category: str | None,
    library_categories: frozenset[str],
    dialect: str,
) -> FilePrompt:
    """A ``FilePrompt`` from split text: the dialect decided, then read."""
    chosen = detect.dialect_for(path, meta, body, dialect)
    if chosen is None:
        raise ValueError(f"not a prompt: has `{detect.not_a_prompt(meta)}`")
    if chosen not in DIALECTS:
        raise ValueError(f"unknown dialect '{chosen}'")

    parsed = DIALECTS[chosen].parse(meta, body)
    if parsed.dropped:
        log.debug(
            "prompt %s: ignoring %s (no meaning over MCP)",
            path,
            ", ".join(parsed.dropped),
        )

    return FilePrompt(
        path=path,
        name=name,
        description=parsed.description,
        title=parsed.title,
        arguments=parsed.arguments,
        tags=set(tags),
        library=library,
        plugin=plugin,
        category=category,
        library_categories=library_categories,
        template=body,
        defaults=parsed.defaults,
        dialect=chosen,
    )

