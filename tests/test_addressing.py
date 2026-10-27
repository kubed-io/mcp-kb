from kubed.mcp_kb.catalogue.addressing import DEFAULT, Addressing

U = "skill://penpot/a/SKILL.md"


def test_default_changes_nothing():
    s = "see skill://penpot/a and skill://penpot."
    assert DEFAULT.text(s) == s
    assert DEFAULT.canonical(U) == U


def test_empty_prefix_is_the_default():
    assert Addressing.parse("") == DEFAULT


def test_invalid_prefix_is_ignored():
    assert Addressing.parse("kb").prefix == ""
    assert Addressing.parse("1b+").prefix == ""
    assert Addressing.parse(" kb+ ").prefix == "kb+"


def test_text_prefixes_every_address_and_keeps_the_library():
    a = Addressing.parse("kb+")
    assert (
        a.text("see skill://penpot/router/SKILL.md and skill://penpot/_index.md")
        == "see kb+skill://penpot/router/SKILL.md and kb+skill://penpot/_index.md"
    )


def test_canonical_strips_only_this_prefix():
    a = Addressing.parse("kb+")
    assert a.canonical("kb+skill://penpot/_index.md") == "skill://penpot/_index.md"
    assert a.canonical(U) == U
    assert a.canonical("other+skill://x") == "other+skill://x"
    assert a.canonical("https://x/y") == "https://x/y"
    assert DEFAULT.canonical("kb+skill://x") == "kb+skill://x"


def test_text_leaves_already_prefixed_and_foreign_schemes_alone():
    a = Addressing.parse("kb+")
    assert a.text("kb+skill://penpot/x") == "kb+skill://penpot/x"
    assert a.text("myskill://penpot/x") == "myskill://penpot/x"
