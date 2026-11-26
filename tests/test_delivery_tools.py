"""The tools: kubed-mcp's resource pair and nothing else.

kb registers no tool (DLV-7). ``list_resources`` and ``read_resource`` are
kubed-mcp's (DLV-6), listed to a client that declared resources off; the prompt
mirror and ``Kb-Prompts`` are gone, and a tools-only client reads a prompt's
file at ``prompts://`` once ``Kb-Listed: prompts`` lists it.
"""

import json

import pytest
from fastmcp import Client
from kubed.mcp.protocol import INVALID_PARAMS, MCPError

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.config import Config
from tests.conftest import http_client, make_config, serve_http, server_of
from tests.test_instructions import _three
from tests.test_plugin_serving import market

PAIR = ["list_resources", "read_resource"]


@pytest.fixture(scope="module")
def server_url(tmp_path_factory):
    base = tmp_path_factory.mktemp("tools")
    kb = KnowledgeBase(_three(base), base / "cache")
    with serve_http(kb) as url:
        yield url


async def tool_names(url, sent=None):
    if isinstance(sent, str):
        url, sent = url + sent, None
    async with http_client(url, sent) as client:
        return sorted(t.name for t in await client.list_tools())


@pytest.mark.unit
async def test_kb_registers_no_tool(skills_dir):  # DLV-7
    mcp = server_of(KnowledgeBase(make_config(skills_dir), skills_dir / "_cache"))
    assert await mcp.list_tools(run_middleware=False) == []
    for name in PAIR:
        assert await mcp.get_tool(name) is not None


@pytest.mark.integration
@pytest.mark.parametrize(
    "sent", [{"Kb-Prompts": "off"}, {"X-MCP-Prompts": "off"}, "?prompts=off"]
)
async def test_the_prompt_inputs_do_nothing(server_url, sent):
    assert await tool_names(server_url, sent) == []

    async def seen(url, headers):
        async with http_client(url, headers) as client:
            listed = await client.list_prompts()
            got = await client.get_prompt("lib_top")
            return (
                sorted(p.name for p in listed),
                [m.content.text for m in got.messages],
            )

    plain = await seen(server_url, None)
    assert plain[0]
    if isinstance(sent, str):
        assert await seen(server_url + sent, None) == plain
    else:
        assert await seen(server_url, sent) == plain


@pytest.mark.integration
@pytest.mark.parametrize("off", ["off", "OFF", "false", "0", "no", "none"])
@pytest.mark.parametrize("header", ["Kb-Resources", "X-MCP-Resources"])
async def test_tool_3s_spellings_list_the_pair(server_url, header, off):
    assert await tool_names(server_url, {header: off}) == PAIR


@pytest.mark.integration
async def test_a_padded_value_is_read_trimmed(server_url):
    assert await tool_names(server_url, "?resources=%20OFF%20") == PAIR


@pytest.mark.integration
@pytest.mark.parametrize("on", ["on", "true", "1", "yes"])
@pytest.mark.parametrize("header", ["Kb-Resources", "X-MCP-Resources"])
async def test_the_on_spellings_list_no_tool(server_url, header, on):
    assert await tool_names(server_url, {header: on}) == []


@pytest.mark.integration
async def test_a_prompts_file_reads_through_the_tool_when_listed(server_url):
    headers = {"Kb-Resources": "off", "Kb-Listed": "prompts"}
    async with http_client(server_url, headers) as client:
        listed = await client.call_tool("list_resources", {})
        rows = json.loads(listed.content[0].text)["resources"]
        uris = [r["uri"] for r in rows if r["uri"].startswith("prompts://")]
        assert "prompts://lib/top.md" in uris
        read = await client.call_tool("read_resource", {"uri": "prompts://lib/top.md"})
    assert "Body." in read.content[0].text


@pytest.mark.integration
async def test_read_resource_follows_dlv6_for_a_skills_blobs(tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    files = {
        "p/skills/s/SKILL.md": "---\nname: s\ndescription: S.\n---\nBody.\n",
        "p/skills/s/assets/x.svg": "<svg/>\n",
    }
    config = market(tmp_path, [{"name": "lib", "source": "./p"}], files, name="lib")
    assets = tmp_path / "lib" / "p" / "skills" / "s" / "assets"
    assert assets.is_dir(), list(tmp_path.rglob("x.svg"))
    (assets / "x.png").write_bytes(png)
    (assets / "x.bin").write_bytes(b"\x00\xff")
    kb = KnowledgeBase(config, tmp_path / "cache")
    base = "skill://lib/s/assets/"
    with serve_http(kb) as url:
        async with http_client(url, {"Kb-Resources": "off"}) as client:
            image = await client.call_tool("read_resource", {"uri": base + "x.png"})
            blob = await client.call_tool("read_resource", {"uri": base + "x.bin"})
            svg = await client.call_tool("read_resource", {"uri": base + "x.svg"})
    assert image.content[0].type == "image"
    assert image.content[0].mime_type == "image/png"
    described = json.loads(blob.content[0].text)
    assert described["binary"] is True
    assert "Not returned: binary content is not text." in blob.content[0].text
    assert svg.content[0].text.startswith("<svg/>")


@pytest.fixture
def asking(tmp_path):
    root = tmp_path / "plugin"
    (root / "prompts").mkdir(parents=True)
    (root / "prompts" / "debug.md").write_text(
        "---\ndescription: Debug an app.\narguments:\n- name: app\n  required: true\n"
        "---\nLook at {{ app }}.\n"
    )
    config = Config.model_validate(
        {
            "plugins": [{"name": "kit", "source": f"file://{root}"}],
            "libraries": [{"name": "kit", "plugins": ["kit"]}],
        }
    )
    return KnowledgeBase(config, tmp_path / "cache")


@pytest.mark.unit
async def test_prompts_get_still_asks_at_2026_07_28(asking):
    asked = []

    async def handler(message, response_type, params, context):
        asked.append(params.requested_schema)
        return {"app": "loki"}

    async with Client(server_of(asking), elicitation_handler=handler) as client:
        got = await client.get_prompt("kit_debug", {})
    assert got.messages[0].content.text == "Look at loki.\n"
    assert asked and asked[0]["required"] == ["app"]
    assert list(asked[0]["properties"]) == ["app"]

    async with Client(
        server_of(asking), elicitation_handler=handler, mode="legacy"
    ) as client:
        with pytest.raises(MCPError) as caught:
            await client.get_prompt("kit_debug", {})
    assert caught.value.error.code == INVALID_PARAMS
    assert caught.value.error.message == "Prompt 'kit_debug' needs the argument app."


@pytest.mark.integration
async def test_kbs_resources_header_wins_over_x_mcps(server_url):
    headers = {"Kb-Resources": "on", "X-MCP-Resources": "off"}
    assert await tool_names(server_url, headers) == []
    headers = {"Kb-Resources": "off", "X-MCP-Resources": "on"}
    assert await tool_names(server_url, headers) == PAIR
