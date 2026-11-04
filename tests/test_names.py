import pytest

from kubed.mcp_kb.catalogue.names import QualifiedNames, split_frontmatter

pytestmark = pytest.mark.unit

W = "skill://kit/writing/SKILL.md"
NAMES = QualifiedNames(
    plugins=(
        ("kit", {"writing": (W,), "twin": ("skill://kit/a/twin/SKILL.md",
                                           "skill://kit/b/twin/SKILL.md")}),
        ("kit-extra", {"ops": ("skill://kit/ops/SKILL.md",)}),
        ("kit", {"late": ("skill://kit/late/SKILL.md",)}),
    )
)


def test_a_qualified_name_reads_as_the_skill_address():
    assert NAMES.rewrite("Load kit:writing, then /kit:writing.") == (
        f"Load {W}, then {W}."
    )
    assert NAMES.rewrite("(`kit-extra:ops`)") == "(`skill://kit/ops/SKILL.md`)"


def test_the_first_plugin_of_that_name_that_serves_it_answers():
    assert NAMES.rewrite("kit:late") == "skill://kit/late/SKILL.md"


def test_a_name_inside_a_longer_token_is_left_alone():
    for text in ("https://kit:writing", "a/kit:writing", "kb+kit:writing",
                 "kit:writing.md", "kit:writing/x", "kit:writing:x", "xkit:writing",
                 "skill://kit:writing", "kit:writing-"):
        assert NAMES.rewrite(text) == text


def test_what_does_not_resolve_is_served_as_written():
    for text in ("kit:nope", "other:writing", "kit:twin", "/kit:db:migrate",
                 "kit:Writing", "Note: kit"):
        assert NAMES.rewrite(text) == text
    assert QualifiedNames().rewrite("kit:writing") == "kit:writing"


def test_preload_resolves_qualified_and_own_bare_names():
    assert NAMES.preload(["kit:writing", " writing ", "ops", "kit-extra:ops",
                          "twin", "nope", 3]) == {
        "kit:writing": W,
        "writing": W,
        "kit-extra:ops": "skill://kit/ops/SKILL.md",
    }
    assert NAMES.preload("kit:writing, writing") == {"kit:writing": W, "writing": W}
    assert NAMES.preload(None) == {} and NAMES.preload({"a": 1}) == {}


def test_split_frontmatter_keeps_the_block_whole():
    assert split_frontmatter("---\nname: a\n---\nbody kit:writing\n") == (
        "---\nname: a\n---\n", "body kit:writing\n"
    )
    assert split_frontmatter("no block\n") == ("", "no block\n")
    assert split_frontmatter("---\nunterminated\n") == ("", "---\nunterminated\n")
