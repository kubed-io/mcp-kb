"""The `${…}` placeholders this server is the authority on.

Claude's placeholders are client-side machinery -- ``${selection}``,
``${CLAUDE_PROJECT_DIR}``, ``${CLAUDE_SESSION_ID}`` name things only the
client has, and Claude Code itself leaves them literal in a skill it did not
fetch locally (§C1.35 point 7). Two are different: ``${CLAUDE_PLUGIN_ROOT}``
and ``${CLAUDE_SKILL_DIR}`` name *this server's* material, so they become
addresses in the ``skill://`` address space and are always resolved (§C1.37).

A regex over every `${…}` would have to decide what to do with each spelling,
and the answer is always "nothing", so a plain ``str.replace`` handles them. The
only regex is anchored to the skill directories the caller names. A skill's
files have one address (SKL-31), so a citation
``${CLAUDE_PLUGIN_ROOT}/<skill dir>/…`` renders as that skill's address instead
of the plugin root's, and the plain replace then handles whatever is left.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

PLUGIN_ROOT = "${CLAUDE_PLUGIN_ROOT}"
SKILL_DIR = "${CLAUDE_SKILL_DIR}"


# A directory name ends here: not before more of a name, and not before a
# dot that starts an extension (`writing.md` is a file, not the skill `writing`).
_BOUNDARY = r"(?![\w~%+@-])(?!\.[\w.~%+@-])"


def _skill_citations(skills: Mapping[str, str]) -> re.Pattern[str] | None:
    """One pattern for every citation of a named skill directory, deepest first."""
    dirs = sorted((d for d in skills if d), key=len, reverse=True)
    root = re.escape(PLUGIN_ROOT)
    alternatives = []
    if dirs:
        names = "|".join(re.escape(d) for d in dirs)
        alternatives.append(rf"{root}/(?P<dir>{names}){_BOUNDARY}")
    if "" in skills:
        alternatives.append(rf"{root}(?P<root>(?=/))")
    return re.compile("|".join(alternatives)) if alternatives else None


def substitute(
    text: str,
    *,
    plugin_root: str,
    skill_dir: str | None = None,
    skills: Mapping[str, str] | None = None,
) -> str:
    """Replace the placeholders this server can answer; leave every other `${…}` alone.

    ``skill_dir`` is absent for a prompt -- a command is not a skill and has no
    directory of its own -- and ``${CLAUDE_SKILL_DIR}`` then stays as written,
    which is what every other unanswerable placeholder does too.

    ``skills`` maps a skill's directory below the plugin root (posix, no
    leading or trailing slash, ``""`` for the root itself) to its unprefixed
    ``skill://`` address. A citation inside one of them renders as that
    skill's address, the deepest directory winning.
    """
    pattern = _skill_citations(skills) if skills else None
    if pattern is not None:

        def address(match: re.Match[str]) -> str:
            return skills[match.groupdict().get("dir") or ""]

        text = pattern.sub(address, text)
    text = text.replace(PLUGIN_ROOT, plugin_root)
    if skill_dir is not None:
        text = text.replace(SKILL_DIR, skill_dir)
    return text
