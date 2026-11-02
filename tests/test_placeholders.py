"""The placeholders this server can answer, and the ones it must leave alone.

Two of Claude's placeholders name this server's own material -- the plugin's
files and a skill's own directory -- so they become addresses in the address
space. Every other `${…}` names something only the client has, and is served
as written.
"""

import pytest

from kubed.mcp_kb.catalogue import placeholders
from kubed.mcp_kb.catalogue.prompts import load_prompt

pytestmark = pytest.mark.unit

DIALECTS = ["mcp-kb", "claude", "copilot"]


def write(path, frontmatter, body):
    path.write_text(f"---\n{frontmatter}---\n{body}")
    return path


def test_both_placeholders_this_server_knows_are_replaced():
    text = "${CLAUDE_PLUGIN_ROOT}/shared/x.md and ${CLAUDE_SKILL_DIR}/SKILL.md"
    assert (
        placeholders.substitute(
            text, plugin_root="skill://lib", skill_dir="skill://lib/a/b"
        )
        == "skill://lib/shared/x.md and skill://lib/a/b/SKILL.md"
    )


def test_a_placeholder_only_the_client_can_fill_is_untouched():
    text = "${CLAUDE_PROJECT_DIR}/x ${CLAUDE_SESSION_ID} ${selection}"
    assert placeholders.substitute(text, plugin_root="skill://lib") == text


def test_without_a_skill_dir_the_skill_placeholder_stays_literal():
    """A prompt is not a skill, so nothing hands it a skill directory."""
    text = "${CLAUDE_SKILL_DIR}/SKILL.md"
    assert placeholders.substitute(text, plugin_root="skill://lib") == text


@pytest.mark.parametrize("dialect", DIALECTS)
def test_rendering_resolves_the_plugin_root_in_every_dialect(tmp_path, dialect):
    path = write(
        tmp_path / f"{dialect}.md",
        "description: d\n",
        "Read ${CLAUDE_PLUGIN_ROOT}/shared/x.md.",
    )
    prompt = load_prompt(path, "lib", dialect=dialect)
    assert prompt.render(plugin_root="skill://lib") == "Read skill://lib/shared/x.md."
    # No plugin root to substitute is the loader's own case: the text stands.
    assert prompt.render() == "Read ${CLAUDE_PLUGIN_ROOT}/shared/x.md."


@pytest.mark.parametrize("dialect", DIALECTS)
def test_rendering_resolves_a_skill_path_in_every_dialect(tmp_path, dialect):
    path = write(
        tmp_path / f"{dialect}.md",
        "description: d\n",
        "Read ${CLAUDE_PLUGIN_ROOT}/skills/w/a.md.",
    )
    prompt = load_prompt(path, "lib", dialect=dialect)
    skills = {"skills/w": "skill://lib/w"}
    assert (
        prompt.render(plugin_root="skill://lib", skills=skills)
        == "Read skill://lib/w/a.md."
    )
    # Without the map the path is the plugin root's, as before.
    assert prompt.render(plugin_root="skill://lib") == "Read skill://lib/skills/w/a.md."


SKILLS = {"skills/writing": "skill://kit/writing"}


@pytest.mark.parametrize(
    ("cited", "rendered"),
    [
        (
            "${CLAUDE_PLUGIN_ROOT}/skills/writing/notes.md",
            "skill://kit/writing/notes.md",
        ),
        (
            "${CLAUDE_PLUGIN_ROOT}/skills/writing/SKILL.md",
            "skill://kit/writing/SKILL.md",
        ),
        ("(${CLAUDE_PLUGIN_ROOT}/skills/writing)", "(skill://kit/writing)"),
        ("`${CLAUDE_PLUGIN_ROOT}/skills/writing`", "`skill://kit/writing`"),
        ("see ${CLAUDE_PLUGIN_ROOT}/skills/writing.", "see skill://kit/writing."),
        (
            "${CLAUDE_PLUGIN_ROOT}/skills/writing.md",
            "skill://kit/skills/writing.md",
        ),
        (
            "${CLAUDE_PLUGIN_ROOT}/skills/writing-x/y.md",
            "skill://kit/skills/writing-x/y.md",
        ),
        (
            "${CLAUDE_PLUGIN_ROOT}/skills/writings/y.md",
            "skill://kit/skills/writings/y.md",
        ),
        (
            "${CLAUDE_PLUGIN_ROOT}/./skills/writing/a.md",
            "skill://kit/./skills/writing/a.md",
        ),
        ("${CLAUDE_PLUGIN_ROOT}/shared/x.md", "skill://kit/shared/x.md"),
        ("${CLAUDE_PLUGIN_ROOT}", "skill://kit"),
    ],
)
def test_a_path_inside_a_skill_renders_its_address(cited, rendered):
    assert (
        placeholders.substitute(cited, plugin_root="skill://kit", skills=SKILLS)
        == rendered
    )


def test_the_deepest_skill_wins():
    nested = {
        "skills/writing": "skill://kit/writing",
        "skills/writing/drafts": "skill://kit/elsewhere",
    }
    for skills in (nested, dict(reversed(list(nested.items())))):
        deep = placeholders.substitute(
            "${CLAUDE_PLUGIN_ROOT}/skills/writing/drafts/d.md",
            plugin_root="skill://kit",
            skills=skills,
        )
        shallow = placeholders.substitute(
            "${CLAUDE_PLUGIN_ROOT}/skills/writing/a.md",
            plugin_root="skill://kit",
            skills=skills,
        )
        assert deep == "skill://kit/elsewhere/d.md"
        assert shallow == "skill://kit/writing/a.md"


def test_a_plugin_root_that_is_a_skill_renders_below_its_address():
    skills = {"": "skill://lib/solo", "skills/inner": "skill://lib/inner"}

    def render(text):
        return placeholders.substitute(text, plugin_root="skill://lib", skills=skills)

    assert (
        render("${CLAUDE_PLUGIN_ROOT}/scripts/run.py")
        == "skill://lib/solo/scripts/run.py"
    )
    assert (
        render("${CLAUDE_PLUGIN_ROOT}/skills/inner/a.md") == "skill://lib/inner/a.md"
    )
    assert render("${CLAUDE_PLUGIN_ROOT}") == "skill://lib"


def test_a_skill_directory_is_matched_literally():
    skills = {".claude/skills/x": "skill://kit/x"}

    def render(text):
        return placeholders.substitute(text, plugin_root="skill://kit", skills=skills)

    assert render("${CLAUDE_PLUGIN_ROOT}/.claude/skills/x/a.md") == (
        "skill://kit/x/a.md"
    )
    assert render("${CLAUDE_PLUGIN_ROOT}/Xclaude/skills/x/a.md") == (
        "skill://kit/Xclaude/skills/x/a.md"
    )


def test_every_citation_and_the_skill_dir_are_rendered():
    text = (
        "${CLAUDE_PLUGIN_ROOT}/skills/writing/a.md "
        "${CLAUDE_PLUGIN_ROOT}/skills/writing/b.md "
        "${CLAUDE_SKILL_DIR}/c.md"
    )
    assert placeholders.substitute(
        text, plugin_root="skill://kit", skill_dir="skill://kit/cite", skills=SKILLS
    ) == "skill://kit/writing/a.md skill://kit/writing/b.md skill://kit/cite/c.md"


def test_without_skills_the_plugin_root_renders_as_before():
    text = "${CLAUDE_PLUGIN_ROOT}/skills/writing/a.md"
    want = "skill://kit/skills/writing/a.md"
    assert placeholders.substitute(text, plugin_root="skill://kit") == want
    assert placeholders.substitute(text, plugin_root="skill://kit", skills=None) == want
    assert placeholders.substitute(text, plugin_root="skill://kit", skills={}) == want


def test_a_plugin_root_that_is_the_only_skill_renders_below_its_address():
    skills = {"": "skill://lib/solo"}

    def render(text):
        return placeholders.substitute(text, plugin_root="skill://lib", skills=skills)

    assert (
        render("${CLAUDE_PLUGIN_ROOT}/scripts/run.py")
        == "skill://lib/solo/scripts/run.py"
    )
    assert render("${CLAUDE_PLUGIN_ROOT}") == "skill://lib"
