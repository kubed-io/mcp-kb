"""A Claude Code subagent file: kb's reading of one, and what is served of it.

An agent is a markdown file: YAML frontmatter naming it and saying when to use
it, then the system prompt as the body. kubed-mcp's plugin layer is the one
reader that decides whether an agent serves and under which name (AGT-6,
AGT-8): kb's harvest records each agent file's path and nothing else.
``parse_agent`` is kb's own reading of one file, for the ``_meta`` key kb adds
to an agent the layer serves (AGT-9). A file that is wrong in its *content*
gives back a reason rather than raising; only an unreadable file raises
``OSError``.

``ServedAgent`` is what the plugin layer serves of one agent file, as kb
records it: its name and file as the layer reports them, admitted by a
``Scope`` exactly as a skill or a prompt of the same plugin is (AGT-15). No
FastMCP here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import frontmatter
import yaml

from ..mcp.scope import Scope
from .harvest import usable_name

# Model families (AGT-9): the first one named in a value, by position, wins.
ROLES: dict[str, str] = {"opus": "large", "sonnet": "medium", "haiku": "small"}


@dataclass(frozen=True)
class ParsedAgent:
    name: str
    description: str  # whitespace collapsed
    capabilities: tuple[str, ...]
    model: str | None
    frontmatter: dict  # verbatim, JSON-safe
    body: str


def parse_agent(path: Path, stem: str | None = None) -> ParsedAgent | str:
    """The agent in ``path``, or the reason its content cannot be served.

    ``stem`` is the name of an agent whose frontmatter names none, as
    kubed-mcp names one (N10); without it a frontmatter ``name`` is required
    (AGT-6).

    An unreadable file (``OSError``) is the caller's: it names no errno here,
    because that text can carry a path.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "agent file is not UTF-8"
    try:
        post = frontmatter.loads(text)
    except (yaml.YAMLError, TypeError, ValueError, RecursionError):
        # TypeError: a mapping key that is not a string.
        return "agent frontmatter does not parse"
    meta = post.metadata
    if not isinstance(meta, dict) or not meta:
        return "agent has no frontmatter mapping"
    try:
        # Frontmatter travels as JSON, so a YAML-only value (a date, .nan) has
        # no form to send: refuse it, as skill_entry does.
        json.dumps(meta, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return "agent frontmatter has no JSON form"
    name = meta.get("name")
    if name is None and stem is not None:
        name = stem
    if not isinstance(name, str) or not name.strip():
        return "agent frontmatter has no name"
    if not usable_name(name):
        return "agent frontmatter name is not a usable name"
    description = meta.get("description")
    if not isinstance(description, str) or not description.strip():
        return "agent frontmatter has no description"
    capabilities = meta.get("capabilities")
    model = meta.get("model")
    return ParsedAgent(
        name=name,
        description=" ".join(description.split()),
        capabilities=(
            tuple(capabilities)
            if isinstance(capabilities, list)
            and all(isinstance(c, str) for c in capabilities)
            else ()
        ),
        model=model if isinstance(model, str) else None,
        frontmatter=meta,
        body=_body(text),
    )


def _body(text: str) -> str:
    """Everything after the frontmatter's closing ``---`` line, as written."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "".join(lines[i + 1 :])
    return ""


def routing_hint(model: str | None) -> dict | None:
    """``modelRoutingHint`` by model family, or None when no family is named."""
    if not model:
        return None
    for word in re.findall(r"[a-z]+", model.lower()):
        if word in ROLES:
            return {"role": ROLES[word], "vision": False}
    return None


@dataclass(frozen=True)
class Agent:
    """One agent file as kb read it, for the ``_meta`` key kb adds to it (AGT-9).

    ``plugin``, ``category``, ``tags`` and ``library_categories`` are its
    plugin's, in its library. ``path`` is the file, under ``root``, its plugin
    root, and ``parsed`` what it read as when its plugin entered the set; a
    ``live`` plugin kept unread answers with that read.
    """

    name: str
    library: str
    plugin: str
    root: Path
    path: Path
    parsed: ParsedAgent
    servers: tuple[str, ...]
    category: str | None
    tags: frozenset[str]
    library_categories: frozenset[str] = frozenset()
    live: bool = False

    def admitted(self, scope: Scope) -> bool:
        return scope.admits(
            self.library,
            self.category,
            self.tags,
            library_categories=self.library_categories,
        )


@dataclass(frozen=True)
class ServedAgent:
    """One agent the plugin layer serves: the name and the file it reports.

    ``name`` is the layer's (``AgentFile.name``), a rename included, and
    ``path`` its file, relative to the plugin root (``AgentFile.path``).
    ``plugin`` is kb's plugin id, and ``category``, ``tags`` and
    ``library_categories`` are that plugin's, in ``library``: what a scope
    admits it on.
    """

    name: str
    library: str
    plugin: str
    path: str
    category: str | None
    tags: frozenset[str]
    library_categories: frozenset[str] = frozenset()

    def admitted(self, scope: Scope) -> bool:
        return scope.admits(
            self.library,
            self.category,
            self.tags,
            library_categories=self.library_categories,
        )
