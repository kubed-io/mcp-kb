"""The instructions text: built from a catalogue alone (unit), then served over HTTP."""

import contextlib
import json
import socket
import threading

import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.skills import SkillsClientExtension

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.catalogue import harvest
from kubed.mcp_kb.catalogue.addressing import DEFAULT, Addressing
from kubed.mcp_kb.catalogue.instructions import build_instructions
from kubed.mcp_kb.catalogue.skills import LibraryFiles, SkillIndex, load_skills
from kubed.mcp_kb.catalogue.uris import Catalogue, LibraryText
from kubed.mcp_kb.config import Config
from kubed.mcp_kb.mcp.instructions import ScopedInstructions
from kubed.mcp_kb.mcp.request import declared_on_initialize
from kubed.mcp_kb.mcp.scope import EVERYTHING, Scope
from tests.conftest import SKILLS_GLOBS, fake_plugin, make_config
from tests.test_header_scope import server_url  # noqa: F401 - shared HTTP fixture

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


@pytest.mark.unit
def test_blank_lines_inside_a_description_cannot_open_a_section(tmp_path):
    a = LibraryText("a", "Para one.\n\n[b]\nfake heading")
    b = LibraryText("b", "B.")
    cat = _catalogue(tmp_path, {a: ["x"], b: ["y"]})
    first = _build(cat).split("\n\n")[0]
    assert first == "[a]\nPara one.\n[b]\nfake heading\nSkills: skill://a/_index.md"
    body = cat.read("skill://a/_index.md")
    assert "Para one.\n[b]\nfake heading\n" in body


# -- served on connect, over HTTP, in both protocol eras ----------------------

ERAS = pytest.mark.parametrize("mode", ["legacy", "default"])


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def served(knowledge_base):
    """``knowledge_base`` on a loopback port: the headers only exist over HTTP."""
    port = _free_port()
    config = uvicorn.Config(
        knowledge_base.mcp.http_app(), host="127.0.0.1", port=port, log_level="error"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        threading.Event().wait(0.05)
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


async def told(url, mode, headers=None, extension=False):
    """The instructions a client in ``mode`` is handed on connecting."""
    kwargs = {"extensions": [SkillsClientExtension()]} if extension else {}
    if mode == "legacy":
        kwargs["mode"] = "legacy"
    transport = StreamableHttpTransport(url, headers=headers or {})
    async with Client(transport, **kwargs) as client:
        return client.instructions


def _market(root, description, *skills, plugin_description=None):
    """A one-plugin marketplace at ``root`` whose own description is given."""
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    plugin = {"name": "p", "source": "./p"}
    if plugin_description is not None:
        plugin["description"] = plugin_description
    catalog = {"name": "m", "plugins": [plugin]}
    if description is not None:
        catalog["description"] = description
    (root / ".claude-plugin" / "marketplace.json").write_text(json.dumps(catalog))
    for name in skills:
        path = root / "p" / "skills" / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: d\n---\n\nBody.\n"
        )


def _library_config(root, **library):
    return Config.model_validate(
        {"libraries": [{"name": "lib", "source": f"file://{root}", **library}]}
    )


@pytest.mark.integration
@ERAS
async def test_one_library_scope(server_url, mode):  # noqa: F811
    text = await told(server_url, mode, {"X-Skill-Library": "flatsource"})
    assert "[" not in text
    lines = text.splitlines()
    assert "Skills (skill://flatsource/_index.md): alpha, beta" in lines
    assert text.endswith(RES_FOOTER)


@pytest.mark.integration
async def test_both_eras_are_told_the_same(server_url):  # noqa: F811
    headers = {"X-Skill-Library": "flatsource"}
    legacy = await told(server_url, "legacy", headers)
    current = await told(server_url, "default", headers)
    assert legacy == current
    assert "alpha, beta" in legacy


@pytest.mark.integration
@ERAS
async def test_unscoped_lists_every_library_without_names(server_url, mode):  # noqa: F811
    text = await told(server_url, mode)
    sections = [line for line in text.splitlines() if line.startswith("[")]
    assert sections == ["[deepsource]", "[flatsource]"]
    lines = text.splitlines()
    assert "Skills: skill://deepsource/_index.md" in lines
    assert "Skills: skill://flatsource/_index.md" in lines
    for known in ("alpha", "beta", "gamma", "delta"):
        assert known not in text
    assert text.endswith(RES_FOOTER)


@pytest.mark.integration
@ERAS
async def test_list_skills_false(tmp_path, mode):
    root = tmp_path / "market"
    _market(root, "Quiet.", "alpha")
    kb = KnowledgeBase(_library_config(root, listSkills=False), tmp_path / "cache")
    with served(kb) as url:
        text = await told(url, mode)
    assert "alpha" not in text
    assert "Skills: skill://lib/_index.md" in text.splitlines()


@pytest.mark.integration
@ERAS
async def test_a_library_with_no_skills_is_absent(tmp_path, mode):
    skilled, bare = tmp_path / "skilled", tmp_path / "bare"
    for name in ("one", "two"):
        path = skilled / name
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: d\n---\n\nBody.\n"
        )
    (bare / "prompts").mkdir(parents=True)
    (bare / "prompts" / "hello.md").write_text("---\ndescription: Hi.\n---\nHi.\n")
    config = Config.model_validate(
        {
            "plugins": [
                {"name": "s1", "source": f"file://{skilled}", "skills": ["one/SKILL.md"]},
                {"name": "s2", "source": f"file://{skilled}", "skills": ["two/SKILL.md"]},
                {
                    "name": "b",
                    "source": f"file://{bare}",
                    "skills": [],
                    "prompts": ["prompts/*.md"],
                },
            ],
            "libraries": [
                {"name": "ones", "plugins": ["s1"], "description": "Ones."},
                {"name": "twos", "plugins": ["s2"], "description": "Twos."},
                {"name": "bare", "plugins": ["b"], "description": "Bare."},
            ],
        }
    )
    kb = KnowledgeBase(config, tmp_path / "cache")
    with served(kb) as url:
        text = await told(url, mode)
    assert "[ones]" in text and "[twos]" in text
    assert "bare" not in text and "Bare." not in text


@pytest.mark.integration
@ERAS
async def test_a_single_library_lists_paths_by_default(tmp_path, mode):
    root = tmp_path / "market"
    _market(root, "Loud.", "alpha")
    kb = KnowledgeBase(_library_config(root), tmp_path / "cache")
    with served(kb) as url:
        text = await told(url, mode)
    assert "Skills (skill://lib/_index.md): " in text
    assert "alpha" in text


@pytest.mark.integration
@ERAS
async def test_declared_skills_extension_drops_names(tmp_path, mode):
    root = tmp_path / "market"
    _market(root, "Loud.", "alpha")
    kb = KnowledgeBase(_library_config(root), tmp_path / "cache")
    with served(kb) as url:
        plain = await told(url, mode)
        declared = await told(url, mode, extension=True)
    assert "alpha" in plain
    assert "Skills (skill://lib/_index.md): " in plain
    assert "alpha" not in declared
    assert "Skills: skill://lib/_index.md" in declared.splitlines()


@pytest.mark.integration
@ERAS
async def test_resources_off_gets_the_tool_footer(server_url, mode):  # noqa: F811
    text = await told(server_url, mode, {"X-MCP-Resources": "off"})
    assert text.endswith(TOOLS_FOOTER)
    assert RES_FOOTER not in text


@pytest.mark.integration
@ERAS
async def test_unknown_library_scope_is_still_refused(server_url, mode):  # noqa: F811
    """Pins refuse a scope that names nothing, initialize included."""
    with pytest.raises(Exception, match="nope"):
        await told(server_url, mode, {"X-Skill-Library": "nope"})


@pytest.mark.integration
@ERAS
async def test_nothing_to_serve_gets_the_footer_alone(tmp_path, mode):
    kb = KnowledgeBase(make_config(), tmp_path / "cache")
    with served(kb) as url:
        assert await told(url, mode) == RES_FOOTER


@pytest.mark.integration
@ERAS
async def test_refresh_reaches_a_new_connection(tmp_path, mode):
    root = tmp_path / "market"
    _market(root, "One.", "alpha")
    kb = KnowledgeBase(_library_config(root), tmp_path / "cache")
    with served(kb) as url:
        assert "One." in await told(url, mode)
        _market(root, "Two.", "alpha")
        kb.refresh(force=True)
        text = await told(url, mode)
    assert "Two." in text
    assert "One." not in text


@pytest.mark.integration
@ERAS
async def test_a_tag_scope_over_two_libraries_gets_sections_and_no_names(
    server_url, mode  # noqa: F811
):
    text = await told(f"{server_url}?tags=flat&tags=deep", mode)
    lines = text.splitlines()
    assert [x for x in lines if x.startswith("[")] == ["[deepsource]", "[flatsource]"]
    assert "Skills: skill://deepsource/_index.md" in lines
    assert "Skills: skill://flatsource/_index.md" in lines
    for known in ("alpha", "beta", "gamma", "delta"):
        assert known not in text


@pytest.mark.integration
@ERAS
async def test_a_tag_that_matches_one_library_selects_it_alone(
    server_url, mode  # noqa: F811
):
    text = await told(server_url, mode, {"X-Skill-Tags": "flat"})
    assert "[" not in text
    assert "Skills (skill://flatsource/_index.md): alpha, beta" in text.splitlines()
    assert "deepsource" not in text


async def _index(url, mode):
    kwargs = {"mode": "legacy"} if mode == "legacy" else {}
    async with Client(StreamableHttpTransport(url), **kwargs) as client:
        parts = await client.read_resource("skill://lib/_index.md")
    return parts[0].text


# (configured library keys, marketplace description, plugin description,
#  the text a client is told above the pointer)
TEXTS = [
    pytest.param(
        {"description": "Mine.", "notes": "Start at alpha."},
        "Theirs.",
        None,
        "Mine.\nStart at alpha.",
        id="configured-replaces-marketplace",
    ),
    pytest.param(
        {"notes": "Start at alpha."},
        "Theirs.",
        None,
        "Theirs.\nStart at alpha.",
        id="marketplace-then-notes",
    ),
    pytest.param({}, None, "Plugin words.", "Plugin words.", id="plugins-fallback"),
]


@pytest.mark.integration
@ERAS
@pytest.mark.parametrize(("keys", "market", "plugin", "expected"), TEXTS)
async def test_the_text_a_library_is_told_and_its_index_open_alike(
    tmp_path, mode, keys, market, plugin, expected
):
    root = tmp_path / "market"
    _market(root, market, "alpha", plugin_description=plugin)
    kb = KnowledgeBase(_library_config(root, **keys), tmp_path / "cache")
    with served(kb) as url:
        text = await told(url, mode)
        index = await _index(url, mode)
    assert text == (
        expected + "\nSkills (skill://lib/_index.md): alpha\n\n" + RES_FOOTER
    )
    assert expected in index


class _Context:
    """What FastMCP hands a middleware; ``message`` is None when it could not
    re-validate the request."""

    message = None
    fastmcp_context = None


@pytest.mark.unit
def test_a_missing_message_means_the_extension_is_not_declared():
    assert declared_on_initialize(_Context()) is False


@pytest.mark.unit
async def test_a_missing_message_still_gets_instructions(tmp_path):
    cat = _catalogue(tmp_path, {LibraryText("penpot"): ["router"]})
    result = type("Result", (), {"instructions": None})()

    async def call_next(_context):
        return result

    mw = ScopedInstructions(lambda: cat)
    assert await mw.on_initialize(_Context(), call_next) is result
    assert result.instructions.startswith("Skills (skill://penpot/_index.md)")
    # discover has no message to read, and a None answer must not raise either
    assert await mw.on_discover(_Context(), _none) is None


async def _none(_context):
    return None


# -- instructions follow the addressing ---------------------------------------


@pytest.mark.unit
def test_prefixed_pointer_and_footer(tmp_path):
    text = LibraryText("flatsource")
    cat = _catalogue(tmp_path, {text: ["alpha", "beta"]})
    out = build_instructions(
        cat,
        EVERYTHING,
        resources=True,
        skills_extension=False,
        addressing=Addressing("kb+"),
    )
    assert out.splitlines()[0] == (
        "Skills (kb+skill://flatsource/_index.md): alpha, beta"
    )
    assert out.splitlines()[-1] == (
        "Read a listed skill at kb+skill://<library>/<path>/SKILL.md; read its "
        "_manifest in place of SKILL.md for the other files it ships."
    )


@pytest.mark.unit
def test_prefixed_pointer_without_names_and_notes(tmp_path):
    a = LibraryText("a", "A.", "Start at skill://a/x/SKILL.md.")
    cat = _catalogue(tmp_path, {a: ["x"]})
    out = build_instructions(
        cat,
        EVERYTHING,
        resources=True,
        skills_extension=False,
        addressing=Addressing("kb+"),
    )
    assert "Start at kb+skill://a/x/SKILL.md." in out.splitlines()


@pytest.mark.unit
def test_prefixed_multi_library_pointers(tmp_path):
    a, b = LibraryText("a", "A."), LibraryText("b", "B.")
    cat = _catalogue(tmp_path, {a: ["x"], b: ["y"]})
    out = build_instructions(
        cat,
        EVERYTHING,
        resources=True,
        skills_extension=False,
        addressing=Addressing("kb+"),
    )
    lines = out.splitlines()
    assert "Skills: kb+skill://a/_index.md" in lines
    assert "Skills: kb+skill://b/_index.md" in lines


@pytest.mark.unit
def test_default_addressing_is_byte_identical(tmp_path):
    a, b = LibraryText("a", "A.", "N."), LibraryText("b", "B.")
    cat = _catalogue(tmp_path, {a: ["x"], b: ["y"]})
    for scope in (EVERYTHING, Scope(library="a")):
        for resources in (True, False):
            for ext in (True, False):
                kw = {"resources": resources, "skills_extension": ext}
                assert build_instructions(
                    cat, scope, addressing=DEFAULT, **kw
                ) == build_instructions(cat, scope, **kw)
    assert _build(cat, Scope(library="a")).endswith(RES_FOOTER)


@pytest.mark.integration
@ERAS
async def test_instructions_follow_headers(server_url, mode):  # noqa: F811
    headers = {"X-Skill-Library": "flatsource", "X-MCP-Resource-Prefix": "kb+"}
    text = await told(server_url, mode, headers)
    assert "Skills (kb+skill://flatsource/_index.md): alpha, beta" in (
        text.splitlines()
    )
    assert text.splitlines()[-1] == (
        "Read a listed skill at kb+skill://<library>/<path>/SKILL.md; read its "
        "_manifest in place of SKILL.md for the other files it ships."
    )
