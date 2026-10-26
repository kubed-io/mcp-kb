"""The server ``instructions`` for one request, as text.

Pure: a catalogue, a scope and two flags in, a string out. No FastMCP, so the
wording is tested without a server and the middleware only decides when to call it.
"""

from ..mcp.scope import Scope
from .uris import Catalogue, LibraryText, index_uri, tidy

RESOURCES_FOOTER = (
    "Read a listed skill at skill://<library>/<path>/SKILL.md; read its "
    "_manifest in place of SKILL.md for the other files it ships."
)
TOOLS_FOOTER = "Read these with read_resource."


def _section(
    catalogue: Catalogue, scope: Scope, text: LibraryText, names: bool
) -> list[str]:
    lines = [s for s in (tidy(text.description), tidy(text.notes)) if s]
    uri = index_uri(text.name)
    if names:
        paths = ", ".join(catalogue.skill_paths(text.name, scope))
        lines.append(f"Skills ({uri}): {paths}")
    else:
        lines.append(f"Skills: {uri}")
    return lines


def build_instructions(
    catalogue: Catalogue, scope: Scope, *, resources: bool, skills_extension: bool
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
        lines = _section(catalogue, scope, text, names)
        if not single:
            lines.insert(0, f"[{text.name}]")
        sections.append("\n".join(lines))
    sections.append(RESOURCES_FOOTER if resources else TOOLS_FOOTER)
    return "\n\n".join(sections)
