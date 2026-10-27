from kubed.mcp_kb.catalogue.addressing import DEFAULT, Addressing

U = "skill://penpot/a/SKILL.md"


def test_default_changes_nothing():
    s = "see skill://penpot/a and skill://penpot."
    assert DEFAULT.text(s) == s
    assert DEFAULT.structured(U) == U
    assert DEFAULT.incoming(U) == [U]


def test_empty_prefix_is_the_default():
    assert Addressing.parse("") == DEFAULT


def test_invalid_prefix_is_ignored():
    assert Addressing.parse("kb").prefix == ""
    assert Addressing.parse("1b+").prefix == ""
    assert Addressing.parse(" kb+ ").prefix == "kb+"


def test_pinned_structured_is_short():
    pinned = Addressing.parse(library="penpot")
    assert pinned.structured("skill://penpot/_index.md") == "skill://_index.md"
    assert (
        pinned.structured("skill://penpot/router/SKILL.md")
        == "skill://router/SKILL.md"
    )
    assert pinned.structured("skill://other/a") == "skill://other/a"
    both = Addressing.parse("kb+", "penpot")
    assert "kb+" not in both.structured("skill://penpot/router/SKILL.md")


def test_text_pinned_and_prefixed():
    a = Addressing.parse("kb+", "penpot")
    assert (
        a.text("see skill://penpot/router/SKILL.md and skill://penpot.")
        == "see kb+skill://router/SKILL.md and kb+skill://."
    )
    assert a.text("skill://penpot/_index.md") == "kb+skill://_index.md"


def test_text_prefix_only():
    assert Addressing.parse("kb+").text("skill://penpot/a") == "kb+skill://penpot/a"


def test_text_leaves_a_longer_library_name_alone():
    a = Addressing.parse(library="n8n")
    assert (
        a.text("skill://n8n-extra/a skill://n8n/b") == "skill://n8n-extra/a skill://b"
    )


def test_incoming_tries_short_then_long():
    a = Addressing.parse(library="penpot")
    assert a.incoming("skill://router/SKILL.md") == [
        "skill://penpot/router/SKILL.md"
    ]
    assert a.incoming("skill://penpot/router/SKILL.md") == [
        "skill://penpot/penpot/router/SKILL.md",
        "skill://penpot/router/SKILL.md",
    ]
    both = Addressing.parse("kb+", "penpot")
    assert both.incoming("kb+skill://_index.md") == ["skill://penpot/_index.md"]
    assert a.incoming("https://x/y") == ["https://x/y"]


def test_first_returns_the_first_hit():
    a = Addressing.parse(library="penpot")
    store = {"skill://penpot/router/SKILL.md": "body"}
    assert a.first("skill://penpot/router/SKILL.md", store.get) == "body"
    assert a.first("skill://nope", store.get) is None


def test_text_leaves_already_prefixed_and_foreign_schemes_alone():
    for a in (Addressing.parse("kb+", "penpot"), Addressing.parse("kb+")):
        assert a.text("kb+skill://penpot/x") == "kb+skill://penpot/x"
        assert a.text("myskill://penpot/x") == "myskill://penpot/x"
    pinned = Addressing.parse(library="penpot")
    assert pinned.text("myskill://penpot/x") == "myskill://penpot/x"
