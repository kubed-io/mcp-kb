"""Resource addresses follow the request's pin and gateway prefix, over real HTTP."""

import hashlib
import json
import re
import socket
import threading

import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from kubed.mcp_kb import KnowledgeBase
from tests.conftest import make_config

PIN = {"X-Skill-Library": "flatsource"}
PREFIX = {"X-MCP-Resource-Prefix": "kb+"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server_url(skills_dir_module, prompts_dir_module):
    port = _free_port()
    # Addresses in prose, so a translated body differs from the canonical one.
    alpha = skills_dir_module / "flatsource" / "alpha"
    (alpha / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: First skill.\n---\n\n"
        "See skill://flatsource/beta/SKILL.md.\n"
    )
    (alpha / "notes.md").write_text("Also skill://flatsource/alpha/SKILL.md.\n")
    # Only this module's server sees it; the shared tree's counts stay put.
    (prompts_dir_module / "flatsource" / "cite.md").write_text(
        "---\ndescription: Cite a shared file.\n---\n"
        "Read ${CLAUDE_PLUGIN_ROOT}/shared/x.md.\n"
    )
    config = make_config(skills_dir_module, prompts_dir_module)
    app = KnowledgeBase(config, skills_dir_module / "_cache").mcp.http_app()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        threading.Event().wait(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


def _client(url, headers=None):
    return Client(StreamableHttpTransport(url, headers=headers or {}))


async def listing(url, headers=None):
    async with _client(url, headers) as client:
        return [(str(r.uri), r.name) for r in await client.list_resources()]


async def read(url, uri, headers=None):
    async with _client(url, headers) as client:
        return (await client.read_resource(uri))[0].text


@pytest.mark.integration
async def test_defaults_are_unchanged(server_url):
    assert ("skill://flatsource/_index.md", "flatsource/_index.md") in await listing(
        server_url
    )
    body = await read(server_url, "skill://flatsource/_index.md")
    assert "skill://flatsource/alpha/SKILL.md" in body


@pytest.mark.integration
async def test_pinned_listing_and_links_are_short(server_url):
    assert ("skill://_index.md", "_index.md") in await listing(server_url, PIN)
    body = await read(server_url, "skill://_index.md", PIN)
    assert "skill://alpha/SKILL.md" in body
    short = await read(server_url, "skill://alpha/SKILL.md", PIN)
    assert short
    assert await read(server_url, "skill://flatsource/alpha/SKILL.md", PIN) == short


@pytest.mark.integration
async def test_prefix_only_bodies_and_prefixed_reads(server_url):
    uris = [u for u, _ in await listing(server_url, PREFIX)]
    assert "skill://flatsource/_index.md" in uris
    body = await read(server_url, "skill://flatsource/_index.md", PREFIX)
    assert "kb+skill://flatsource/alpha/SKILL.md" in body
    plain = await read(server_url, "skill://flatsource/beta/SKILL.md")
    got = await read(server_url, "kb+skill://flatsource/beta/SKILL.md", PREFIX)
    assert got == plain


@pytest.mark.integration
async def test_behind_a_simulated_gateway(server_url):
    headers = {**PIN, **PREFIX}
    body = await read(server_url, "skill://_index.md", headers)
    links = re.findall(r"kb\+skill://\S+?(?=[:\s]|$)", body)
    assert links
    for link in links:
        assert await read(server_url, link.removeprefix("kb+"), headers)
    assert await read(server_url, "skill://alpha/_manifest", headers)


@pytest.mark.integration
async def test_a_tag_scope_keeps_long_addresses(server_url):
    uris = [u for u, _ in await listing(server_url, {"X-Skill-Tags": "flat"})]
    assert "skill://flatsource/_index.md" in uris


@pytest.mark.integration
async def test_invalid_prefix_is_ignored(server_url):
    bad = await read(
        server_url, "skill://flatsource/_index.md", {"X-MCP-Resource-Prefix": "kb"}
    )
    assert bad == await read(server_url, "skill://flatsource/_index.md")


@pytest.mark.integration
async def test_directory_hint_is_translated(server_url):
    with pytest.raises(Exception, match=re.escape("kb+skill://alpha/SKILL.md")):
        await read(server_url, "skill://alpha", {**PIN, **PREFIX})


BOTH = {**PIN, **PREFIX}


async def tool(url, name, args=None, headers=None):
    async with _client(url, headers) as client:
        result = await client.call_tool(name, args or {})
        return result.content[0].text


@pytest.mark.integration
async def test_tools_mode_with_both(server_url):
    headers = {**BOTH, "X-MCP-Resources": "off"}
    rows = json.loads(await tool(server_url, "list_resources", headers=headers))
    assert "kb+skill://_index.md" in [r["uri"] for r in rows]
    bodies = {
        await tool(server_url, "read_resource", {"uri": uri}, headers)
        for uri in (
            "skill://alpha/SKILL.md",
            "skill://flatsource/alpha/SKILL.md",
            "kb+skill://alpha/SKILL.md",
        )
    }
    assert len(bodies) == 1


async def skills_request(url, method, headers, **params):
    from mcp_types import Request, RequestParams
    from pydantic import ConfigDict, TypeAdapter

    class Params(RequestParams):
        model_config = ConfigDict(extra="allow")

    async with _client(url, headers) as client:
        return await client.session.send_request(
            Request(method=method, params=Params(**params)), TypeAdapter(dict)
        )


@pytest.mark.integration
async def test_skills_extension_with_a_pin(server_url):
    listed = (await skills_request(server_url, "skills/list", BOTH))["skills"]
    assert listed
    for entry in listed:
        assert entry["uri"].startswith("skill://")
        assert not entry["uri"].startswith("skill://flatsource/")
        assert "kb+" not in json.dumps(entry)
    got = await skills_request(
        server_url, "skills/get", BOTH, uri="skill://alpha/SKILL.md"
    )
    entry = got["skill"]
    assert len(entry["resources"]) >= 2
    for file in entry["resources"]:
        served = (await read(server_url, file["uri"], BOTH)).encode("utf-8")
        assert file["digest"] == f"sha256:{hashlib.sha256(served).hexdigest()}"
        assert file["size"] == len(served)
        plain = await read(server_url, f"skill://flatsource/{file['uri'][8:]}")
        assert plain.encode("utf-8") != served


@pytest.mark.integration
async def test_prompt_renders_pinned_prefixed_root(server_url):
    async def render(headers):
        async with _client(server_url, headers) as client:
            got = await client.get_prompt("flatsource_cite")
            return got.messages[0].content.text

    assert await render(BOTH) == "Read kb+skill://shared/x.md.\n"
    assert await render({}) == "Read skill://flatsource/shared/x.md.\n"
