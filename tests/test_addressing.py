from kubed.mcp_kb.catalogue.addressing import DEFAULT, Addressing

U = "skill://penpot/a/SKILL.md"


def test_default_changes_nothing():
    s = "see skill://penpot/a and skill://penpot."
    assert DEFAULT.text(s) == s
    assert DEFAULT.incoming(U) == [U]


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


def test_incoming_strips_only_this_prefix():
    a = Addressing.parse("kb+")
    assert a.incoming("kb+skill://penpot/_index.md") == ["skill://penpot/_index.md"]
    assert a.incoming(U) == [U]
    assert a.incoming("other+skill://x") == ["other+skill://x"]
    assert a.incoming("https://x/y") == ["https://x/y"]
    assert DEFAULT.incoming("kb+skill://x") == ["kb+skill://x"]


def test_first_returns_the_first_hit():
    a = Addressing.parse("kb+")
    store = {U: "body"}
    assert a.first("kb+" + U, store.get) == "body"
    assert a.first("skill://nope", store.get) is None


def test_text_leaves_already_prefixed_and_foreign_schemes_alone():
    a = Addressing.parse("kb+")
    assert a.text("kb+skill://penpot/x") == "kb+skill://penpot/x"
    assert a.text("myskill://penpot/x") == "myskill://penpot/x"
