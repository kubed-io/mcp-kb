"""Resource addresses follow the request's pin and gateway prefix, over real HTTP."""

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
    plain = await read(server_url, "skill://flatsource/alpha/SKILL.md")
    got = await read(server_url, "kb+skill://flatsource/alpha/SKILL.md", PREFIX)
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
