"""A Claude Code subagent file, read for what the agents extension serves.

An agent is a markdown file: YAML frontmatter naming it and saying when to use
it, then the system prompt as the body. This module is the pure reading of one
-- no FastMCP, no catalogue -- so the harvest can record it and a later layer
can serve it. A file that is wrong in its *content* gives back the reason it is
skipped (AGT-6) rather than raising; only an unreadable file raises, which fails
the plugin as it does for a prompt.

``Agent`` and ``AgentRoster`` are what a snapshot serves of them: one agent
under the name its library gave it (AGT-8), and every one of them, admitted by
a ``Scope`` exactly as a skill or a prompt of the same plugin is (AGT-15).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import frontmatter
import yaml

from ..mcp.scope import EVERYTHING, Scope

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


def parse_agent(path: Path) -> ParsedAgent | str:
    """The agent in ``path``, or the reason its content cannot be served.

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
    if not isinstance(name, str) or not name.strip():
        return "agent frontmatter has no name"
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
    """One served agent: the name its library gave it, and what it was parsed as.

    ``plugin``, ``category``, ``tags`` and ``library_categories`` are its
    plugin's, in its library: what a scope admits it on. ``path`` is the file,
    under ``root``, its plugin root. ``parsed`` is the copy read when the
    snapshot was built; a ``live`` agent is read again on every definition and
    falls back to it (AGT-16).
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


class AgentRoster:
    """Every agent a snapshot serves, by name, and who may see each.

    Names are unique across the roster: one is unique within its library
    (AGT-8), and every name starts with its library's. Built once and never
    edited, as the snapshot holding it is not.
    """

    def __init__(self, agents: Sequence[Agent] = ()):
        self._agents = tuple(sorted(agents, key=lambda a: a.name))
        self._by_name: dict[str, Agent] = {}
        for agent in self._agents:
            self._by_name.setdefault(agent.name, agent)

    def __len__(self) -> int:
        return len(self._agents)

    def visible(self, scope: Scope = EVERYTHING) -> list[Agent]:
        """The agents ``scope`` admits, in name order (AGT-7)."""
        return [a for a in self._agents if a.admitted(scope)]

    def get(self, name: str, scope: Scope = EVERYTHING) -> Agent | None:
        """One agent by name, or None when it is absent or out of scope alike."""
        found = self._by_name.get(name)
        if found is None or not found.admitted(scope):
            return None
        return found
