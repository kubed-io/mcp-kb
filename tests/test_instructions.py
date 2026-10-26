"""The instructions text, built from a catalogue with no server around it."""

import pytest

from kubed.mcp_kb.catalogue import harvest
from kubed.mcp_kb.catalogue.instructions import build_instructions
from kubed.mcp_kb.catalogue.skills import LibraryFiles, SkillIndex, load_skills
from kubed.mcp_kb.catalogue.uris import Catalogue, LibraryText
from kubed.mcp_kb.mcp.scope import EVERYTHING, Scope
from tests.conftest import SKILLS_GLOBS, fake_plugin

RES_FOOTER = (
    "Read a listed skill at skill://<library>/<path>/SKILL.md; read its "
    "_manifest in place of SKILL.md for the other files it ships."
)
TOOLS_FOOTER = "Read these with read_resource."


def _catalogue(tmp_path, libraries):
    """``libraries`` maps a LibraryText to the skill names it holds."""
    skills = []
    for text, names in libraries.items():
        root = tmp_path / text.name
        for name in names:
            path = root / name
            path.mkdir(parents=True)
            (path / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: d\n---\n\nBody.\n"
            )
        skills += load_skills(
            harvest.skill_dirs(root, SKILLS_GLOBS),
            library=text.name,
            plugin=fake_plugin(text.name, root),
            root=root,
        )
    return Catalogue(SkillIndex(skills), LibraryFiles(), libraries=list(libraries))


def _build(catalogue, scope=EVERYTHING, resources=True, skills_extension=False):
    return build_instructions(
        catalogue, scope, resources=resources, skills_extension=skills_extension
    )


@pytest.mark.unit
def test_one_library_has_no_heading_and_lists_paths(tmp_path):
    text = LibraryText("penpot", "P.", "Start at router.")
    cat = _catalogue(tmp_path, {text: ["router", "deck"]})
    assert _build(cat) == (
        "P.\nStart at router.\n"
        "Skills (skill://penpot/_index.md): deck, router\n\n" + RES_FOOTER
    )


@pytest.mark.unit
def test_several_libraries_get_headings_and_no_names(tmp_path):
    a, b = LibraryText("a", "A."), LibraryText("b", "B.", "Note.")
    cat = _catalogue(tmp_path, {a: ["x"], b: ["y"]})
    assert _build(cat) == (
        "[a]\nA.\nSkills: skill://a/_index.md\n\n"
        "[b]\nB.\nNote.\nSkills: skill://b/_index.md\n\n" + RES_FOOTER
    )


@pytest.mark.unit
def test_a_scope_that_selects_one_library_lists_its_names(tmp_path):
    a, b = LibraryText("a", "A."), LibraryText("b", "B.")
    cat = _catalogue(tmp_path, {a: ["x"], b: ["y"]})
    scope = Scope(library="a")
    assert _build(cat, scope).startswith("A.\nSkills (skill://a/_index.md): x\n")


@pytest.mark.unit
def test_list_skills_false_drops_the_names(tmp_path):
    text = LibraryText("penpot", list_skills=False)
    cat = _catalogue(tmp_path, {text: ["router"]})
    assert _build(cat) == "Skills: skill://penpot/_index.md\n\n" + RES_FOOTER


@pytest.mark.unit
def test_skills_extension_drops_the_names(tmp_path):
    text = LibraryText("penpot")
    cat = _catalogue(tmp_path, {text: ["router"]})
    out = _build(cat, skills_extension=True)
    assert out == "Skills: skill://penpot/_index.md\n\n" + RES_FOOTER


@pytest.mark.unit
def test_tools_mode_footer(tmp_path):
    cat = _catalogue(tmp_path, {LibraryText("penpot"): ["router"]})
    assert _build(cat, resources=False).splitlines()[-1] == TOOLS_FOOTER


@pytest.mark.unit
def test_nothing_selected_is_the_footer_alone(tmp_path):
    cat = _catalogue(tmp_path, {LibraryText("penpot"): ["router"]})
    nothing = Scope(library="absent")
    assert _build(cat, nothing) == RES_FOOTER
    assert _build(cat, nothing, resources=False) == TOOLS_FOOTER


@pytest.mark.unit
def test_empty_description_and_notes_start_at_the_pointer(tmp_path):
    text = LibraryText("penpot", "", "  ", list_skills=False)
    cat = _catalogue(tmp_path, {text: ["router"]})
    assert _build(cat).startswith("Skills: skill://penpot/_index.md\n")


@pytest.mark.unit
def test_block_scalars_leave_no_blank_runs(tmp_path):
    text = LibraryText("penpot", "d  ", "a\n")
    cat = _catalogue(tmp_path, {text: ["router"]})
    out = _build(cat)
    assert "\n\n\n" not in out
    assert not any(line.endswith(" ") for line in out.splitlines())
    assert out.startswith("d\na\nSkills")
