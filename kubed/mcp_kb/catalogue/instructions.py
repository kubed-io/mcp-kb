"""The server ``instructions`` for one request, as text.

Pure: a catalogue, a scope and two flags in, a string out. No FastMCP, so the
wording is tested without a server and the middleware only decides when to call it.
"""

from ..mcp.scope import Scope
from .addressing import DEFAULT, Addressing
from .uris import Catalogue, LibraryText, index_uri, tidy

_FOOTER = (
    "Read a listed skill at {prefix}skill://<library>/<path>/SKILL.md; read its "
    "_manifest in place of SKILL.md for the other files it ships."
)
TOOLS_FOOTER = "Read these with read_resource."


def _footer(a: Addressing) -> str:
    return _FOOTER.format(prefix=a.prefix)


def _section(
    catalogue: Catalogue, scope: Scope, text: LibraryText, names: bool, a: Addressing
) -> list[str]:
    lines = [
        a.text(s) for s in (tidy(text.description), tidy(text.notes)) if s
    ]
    uri = a.text(index_uri(text.name))
    if names:
        paths = ", ".join(catalogue.skill_paths(text.name, scope))
        lines.append(f"Skills ({uri}): {paths}")
    else:
        lines.append(f"Skills: {uri}")
    return lines


def build_instructions(
    catalogue: Catalogue,
    scope: Scope,
    *,
    resources: bool,
    skills_extension: bool,
    addressing: Addressing = DEFAULT,
) -> str:
    """One section per selected library, then the footer for the mode.

    Skill names are listed only when exactly one library is selected, it asks
    for them, and the client has no skills extension to discover them with.
    """
    selected = catalogue.selected(scope)
    single = len(selected) == 1
    sections = []
    for text in selected:
        names = single and text.list_skills and not skills_extension
        lines = _section(catalogue, scope, text, names, addressing)
        if not single:
            lines.insert(0, f"[{text.name}]")
        sections.append("\n".join(lines))
    sections.append(_footer(addressing) if resources else TOOLS_FOOTER)
    return "\n\n".join(sections)
