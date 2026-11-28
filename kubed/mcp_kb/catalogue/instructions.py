"""The server ``instructions`` for one request, as text.

Pure: a catalogue, a scope, two inputs (whether the client reads resources,
and its Via), kubed-mcp's count of
skills listed and cut as two plain ints, and where the prompts and
agents are served in, a string out. No FastMCP, so the wording is tested
without a server and the middleware only decides when to call it.
The text is unprefixed; ``mcp/instructions.py`` writes the gateway prefix over it.
"""

from collections.abc import Mapping, Sequence
from typing import Literal

from ..mcp.scope import Scope
from .snapshot import Folders
from .uris import Catalogue, LibraryText, index_uri, tidy

Via = Literal["mcp", "extension", "local"]

RESOURCES_FOOTER = (
    "Read a listed skill at skill://<library>/<path>/SKILL.md; read its "
    "_manifest in place of SKILL.md for the other files it ships."
)
TOOLS_FOOTER = "Read these with read_resource."
EXTENSION_FOOTER = (
    "Skills arrive through the Skills extension; each reads at "
    "skill://<library>/<path>/SKILL.md, and its entry lists the files it ships."
)
CUT_LINE = (
    "{listed} of {total} skills are listed; every skill reads through its "
    "library's _index.md."
)


def footer(*, resources: bool, via: Via = "mcp") -> str:
    """The closing line for a mode: INS-15 under ``mcp``, INS-21, or none (INS-20)."""
    if via == "local":
        return ""
    if via == "extension":
        return EXTENSION_FOOTER
    return RESOURCES_FOOTER if resources else TOOLS_FOOTER


def kind_pointer(
    label: str, scheme: str, library: str, namespaces: Sequence[str]
) -> str | None:
    """The ``<label>:`` line for the ``namespaces`` serving one kind, or None.

    The library's own index when its main plugin is among them, since only then
    is that folder there; else each namespace's index, in order (INS-19).
    """
    if not namespaces:
        return None
    if library in namespaces:
        namespaces = (library,)
    return f"{label}: " + ", ".join(f"{scheme}://{n}/_index.md" for n in namespaces)


def _section(
    catalogue: Catalogue,
    scope: Scope,
    text: LibraryText,
    names: bool,
    folders: Folders,
    via: Via = "mcp",
) -> list[str]:
    lines = [s for s in (tidy(text.description), tidy(text.notes)) if s]
    if via == "local":
        return lines
    uri = index_uri(text.name)
    if names:
        paths = ", ".join(catalogue.skill_paths(text.name, scope))
        lines.append(f"Skills ({uri}): {paths}")
    else:
        lines.append(f"Skills: {uri}")
    for label, scheme, namespaces in (
        ("Prompts", "prompts", folders.prompts),
        ("Agents", "agents", folders.agents),
    ):
        line = kind_pointer(label, scheme, text.name, namespaces)
        if line is not None:
            lines.append(line)
    return lines


def build_instructions(
    catalogue: Catalogue,
    scope: Scope,
    *,
    resources: bool,
    folders: Mapping[str, Folders] | None = None,
    via: Via = "mcp",
    skills: tuple[int, int] | None = None,
) -> str:
    """One section per selected library, the cut line if any, then the footer.

    Skill names are listed under ``mcp``, when exactly one library is
    selected and it asks for them. Under ``local`` a section is the description
    and notes alone, and one with neither is left out, heading too (INS-20, INS-22).
    ``folders`` is ``Snapshot.folders`` for the scope: where each library's
    prompts and agents are served, pointed at after its skills (INS-19).
    ``skills`` is ``(listed, cut)``, kubed-mcp's count for the request: when
    ``cut`` is above 0, ``mcp`` and ``extension`` say how many of how many are
    listed, between the sections and the footer (INS-24).
    """
    selected = catalogue.selected(scope)
    single = len(selected) == 1
    sections = []
    for text in selected:
        names = via == "mcp" and single and text.list_skills
        found = (folders or {}).get(text.name, Folders())
        lines = _section(catalogue, scope, text, names, found, via)
        if not lines:
            continue
        if not single:
            lines.insert(0, f"[{text.name}]")
        sections.append("\n".join(lines))
    if via != "local" and skills is not None and skills[1] > 0:
        listed, cut = skills
        sections.append(CUT_LINE.format(listed=listed, total=listed + cut))
    closing = footer(resources=resources, via=via)
    return "\n\n".join([*sections, closing] if closing else sections)
