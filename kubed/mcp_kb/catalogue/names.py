"""Plugin-qualified skill names, and the address each one stands for.

In Claude Code a plugin's skill is ``<plugin>:<skill>``, and a slash invokes
it: ``/<plugin>:<skill>``. Over MCP that name points at nothing -- a client
cannot register this server's skills with its Skill tool -- so text that cites
one sends a reader to a call that fails. This module finds such names and
rewrites each to the ``skill://`` address that does resolve.

What a name is (SKL-54). ``<plugin>`` matches PLG-1's name pattern and
``<skill>`` is a lowercase letter or digit followed by lowercase letters,
digits and ``-``. A name stands alone or it is not one: before it (before its
``/`` when it has one) there is no letter, digit or any of ``_ . / : @ + ~ % -``,
and after it there is no letter, digit or any of ``_ : / ~ % + @ -``, nor a
``.`` followed by one of those. ``https://kit:writing``, ``a/kit:writing``,
``kit:writing.md``, ``kit:writing/x`` and ``kit:writing:x`` are not names; a
sentence ending ``kit:writing.`` holds one.

How it resolves (SKL-55). The candidates are the plugins of the text's own
library whose name equals ``<plugin>``: the text's own plugin first, then the
rest in library order. The first candidate that serves an in-scope skill of
that name answers, with that skill's ``SKILL.md`` address and without the
``/``. A candidate that serves two such skills, in different folders, is
ambiguous and the name stays as written; kb never guesses. The table is built
from what the caller's scope admits and from nothing else, so an out-of-scope
target stays as written exactly as an absent one does.

Why an address and never another name: a client's own MCP-skills support would
choose its own per-server names, and any name kb picked could be wrong for it.
An address is the one thing every client can read.

Why the rest is left alone. A command has no address, and a gateway renames
prompts, so ``/<plugin>:<command>`` and ``/<plugin>:a:b`` stay as written. A
bare word such as ``penpot-build-screen`` is too ambiguous in prose to touch;
the only place a bare name resolves is :meth:`QualifiedNames.preload`, for an
agent's ``skills:`` entries, where it means the agent's own plugin's skill.

The pattern runs over the whole body, fenced code included, as the placeholder
rewrite does. A match that resolves to nothing is put back exactly as matched,
so a false match costs nothing.

Pure and stdlib-only: this package imports no FastMCP.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

QUALIFIED = re.compile(
    r"(?<![\w./:@+~%-])"
    r"(?P<slash>/)?"
    r"(?P<plugin>[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?)"
    r":"
    r"(?P<skill>[a-z0-9][a-z0-9-]*)"
    r"(?![\w~%+@:/-])(?!\.[\w~%+@-])"
)


@dataclass(frozen=True)
class QualifiedNames:
    """Plugin name -> skill name -> that skill's unprefixed ``SKILL.md`` URIs.

    ``plugins[0]`` is the text's own plugin, then the rest in library order.
    The default, empty table rewrites nothing.
    """

    plugins: tuple[tuple[str, Mapping[str, tuple[str, ...]]], ...] = ()

    def address(self, plugin: str, skill: str) -> str | None:
        """SKL-55: the first plugin of that name serving the skill answers."""
        for name, skills in self.plugins:
            if name != plugin or skill not in skills:
                continue
            uris = skills[skill]
            return uris[0] if len(uris) == 1 else None
        return None

    def rewrite(self, text: str) -> str:
        """Replace each name that resolves; leave every other match as it was."""

        def replace(match: re.Match[str]) -> str:
            found = self.address(match["plugin"], match["skill"])
            return match[0] if found is None else found

        return QUALIFIED.sub(replace, text)

    def preload(self, skills: object) -> dict[str, str]:
        """AGT-17: each entry of an agent's ``skills`` as written -> its address."""
        if isinstance(skills, str):
            entries = skills.split(",")
        elif isinstance(skills, list):
            entries = [e for e in skills if isinstance(e, str)]
        else:
            return {}
        resolved: dict[str, str] = {}
        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue
            found: str | None = None
            match = QUALIFIED.fullmatch(entry)
            if match:
                found = self.address(match["plugin"], match["skill"])
            elif self.plugins:
                uris = self.plugins[0][1].get(entry, ())
                found = uris[0] if len(uris) == 1 else None
            if found is not None:
                resolved[entry] = found
        return resolved


def split_frontmatter(text: str) -> tuple[str, str]:
    """``(head, body)``: the block through its closing ``---`` line, then the rest."""
    if not text.startswith("---\n"):
        return "", text
    pos = 4
    while pos <= len(text):
        end = text.find("\n", pos)
        line = text[pos:] if end < 0 else text[pos:end]
        if line == "---":
            cut = len(text) if end < 0 else end + 1
            return text[:cut], text[cut:]
        if end < 0:
            break
        pos = end + 1
    return "", text
