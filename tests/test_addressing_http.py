"""Addresses in text follow the request's gateway prefix, over real HTTP."""

import contextlib
import hashlib
import json
import re
import socket
import threading

import frontmatter
import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from kubed.mcp_kb import KnowledgeBase
from tests.conftest import make_config

PIN = {"Kb-Library": "flatsource"}
PREFIX = {"Kb-Resource-Prefix": "kb+"}
FULL = {"Kb-Listing": "full"}
ALPHA_DESCRIPTION = "First skill, see kb+skill://flatsource/beta/SKILL.md now"
BOTH = {**PIN, **PREFIX}


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
        "---\nname: alpha\n"
        "description: First skill, see skill://flatsource/beta/SKILL.md now\n---\n\n"
        "See skill://flatsource/beta/SKILL.md.\n"
    )
    (alpha / "notes.md").write_text("Also skill://flatsource/alpha/SKILL.md.\n")
    (skills_dir_module / "flatsource" / "beta" / "already.md").write_text(
        "kb+skill://flatsource/beta/SKILL.md and myskill://flatsource/beta.\n"
    )
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
async def test_a_library_pin_changes_no_address(server_url):
    rows = await listing(server_url, PIN)
    assert rows == [("skill://flatsource/_index.md", "flatsource/_index.md")]
    pinned = await read(server_url, "skill://flatsource/_index.md", PIN)
    assert pinned == await read(server_url, "skill://flatsource/_index.md")
    assert "skill://flatsource/alpha/SKILL.md" in pinned


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
    body = await read(server_url, "skill://flatsource/_index.md", headers)
    links = re.findall(r"kb\+skill://\S+?(?=[:\s]|$)", body)
    assert links
    for link in links:
        assert await read(server_url, link.removeprefix("kb+"), headers)
    assert await read(server_url, "skill://flatsource/alpha/_manifest", headers)


@pytest.mark.integration
async def test_no_double_prefix(server_url):
    uri = "skill://flatsource/beta/already.md"
    body = await read(server_url, uri, PREFIX)
    assert body == await read(server_url, uri)
    assert "kb+kb+" not in body


@pytest.mark.integration
async def test_invalid_prefix_is_ignored(server_url):
    bad = await read(
        server_url, "skill://flatsource/_index.md", {"Kb-Resource-Prefix": "kb"}
    )
    assert bad == await read(server_url, "skill://flatsource/_index.md")


@pytest.mark.integration
async def test_directory_hint_is_translated(server_url):
    with pytest.raises(Exception, match=re.escape("kb+skill://flatsource/alpha/SKILL.md")):
        await read(server_url, "skill://flatsource/alpha", BOTH)


@pytest.mark.integration
async def test_prefixed_directory_hint_names_the_prefixed_file(server_url):
    want = "kb+skill://flatsource/alpha/SKILL.md"
    with pytest.raises(Exception, match=re.escape(want)):
        await read(server_url, "kb+skill://flatsource/alpha", BOTH)
    with pytest.raises(Exception, match=re.escape(want)):
        await tool(
            server_url,
            "read_resource",
            {"uri": "kb+skill://flatsource/alpha"},
            {**BOTH, "X-MCP-Resources": "off"},
        )


@pytest.mark.integration
async def test_read_returns_the_uri_the_client_sent(server_url):
    async with _client(server_url, BOTH) as client:
        for sent in (
            "skill://flatsource/alpha/SKILL.md",
            "kb+skill://flatsource/alpha/SKILL.md",
        ):
            assert str((await client.read_resource(sent))[0].uri) == sent


@pytest.mark.integration
async def test_listing_descriptions_are_addressed(server_url):
    headers = {**BOTH, **FULL}
    async with _client(server_url, headers) as client:
        rows = {str(r.uri): r.description for r in await client.list_resources()}
    assert rows["skill://flatsource/alpha/SKILL.md"] == ALPHA_DESCRIPTION
    plain = {**FULL, **PIN}
    async with _client(server_url, plain) as client:
        rows = {str(r.uri): r.description for r in await client.list_resources()}
    assert "kb+" not in rows["skill://flatsource/alpha/SKILL.md"]
    tools = json.loads(
        await tool(server_url, "list_resources", headers={**headers, "X-MCP-Resources": "off"})
    )
    by_uri = {r["uri"]: r["description"] for r in tools}
    assert by_uri["kb+skill://flatsource/alpha/SKILL.md"] == ALPHA_DESCRIPTION


async def tool(url, name, args=None, headers=None):
    async with _client(url, headers) as client:
        result = await client.call_tool(name, args or {})
        return result.content[0].text


@pytest.mark.integration
async def test_tools_mode_with_the_prefix(server_url):
    headers = {**BOTH, "X-MCP-Resources": "off"}
    rows = json.loads(await tool(server_url, "list_resources", headers=headers))
    assert [r["uri"] for r in rows] == ["kb+skill://flatsource/_index.md"]
    bodies = {
        await tool(server_url, "read_resource", {"uri": uri}, headers)
        for uri in (
            "skill://flatsource/alpha/SKILL.md",
            "kb+skill://flatsource/alpha/SKILL.md",
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
async def test_skills_extension_with_the_prefix(server_url):
    listed = (await skills_request(server_url, "skills/list", BOTH))["skills"]
    assert listed
    for entry in listed:
        assert entry["uri"].startswith("skill://flatsource/")
        # Frontmatter is text and may cite addresses; structured fields never do.
        assert "kb+" not in json.dumps({**entry, "frontmatter": None})
        for file in entry["resources"]:
            served = (await read(server_url, file["uri"], BOTH)).encode("utf-8")
            assert file["digest"] == f"sha256:{hashlib.sha256(served).hexdigest()}"
            assert file["size"] == len(served)
    got = await skills_request(
        server_url, "skills/get", BOTH, uri="skill://flatsource/alpha/SKILL.md"
    )
    entry = got["skill"]
    sent = await skills_request(
        server_url, "skills/get", BOTH, uri="kb+skill://flatsource/alpha/SKILL.md"
    )
    assert sent["skill"] == entry
    served_main = await read(server_url, "skill://flatsource/alpha/SKILL.md", BOTH)
    assert entry["frontmatter"] == frontmatter.loads(served_main).metadata
    assert entry["frontmatter"]["description"] == ALPHA_DESCRIPTION
    assert len(entry["resources"]) >= 2
    for file in entry["resources"]:
        served = (await read(server_url, file["uri"], BOTH)).encode("utf-8")
        assert file["digest"] == f"sha256:{hashlib.sha256(served).hexdigest()}"
        assert file["size"] == len(served)
        assert file["uri"].startswith("skill://flatsource/")
        plain = await read(server_url, file["uri"])
        assert plain.encode("utf-8") != served


@pytest.mark.integration
async def test_prompt_renders_the_prefixed_root(server_url):
    async def render(headers):
        async with _client(server_url, headers) as client:
            got = await client.get_prompt("flatsource_cite")
            return got.messages[0].content.text

    assert await render(BOTH) == "Read kb+skill://flatsource/shared/x.md.\n"
    assert await render({}) == "Read skill://flatsource/shared/x.md.\n"


@pytest.mark.integration
async def test_a_plus_in_the_url_parameter_is_a_plus(server_url):
    # In a query string a bare "+" decodes to a space.
    async with _client(f"{server_url}?prefix=kb+") as client:
        body = (await client.read_resource("skill://flatsource/_index.md"))[0].text
    assert "kb+skill://flatsource/alpha/SKILL.md" in body


@contextlib.contextmanager
def _served(knowledge_base):
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            knowledge_base.mcp.http_app(), host="127.0.0.1", port=port, log_level="error"
        )
    )
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


@pytest.mark.integration
async def test_library_notes_are_addressed_in_the_instructions(tmp_path):
    from kubed.mcp_kb.config import Config

    skill = tmp_path / "m" / "p" / "skills" / "s"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: s\ndescription: d\n---\n\nBody.\n")
    (tmp_path / "m" / ".claude-plugin").mkdir()
    (tmp_path / "m" / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"name": "m", "plugins": [{"name": "p", "source": "./p"}]})
    )
    config = Config.model_validate(
        {
            "libraries": [
                {
                    "name": "lib",
                    "source": f"file://{tmp_path / 'm'}",
                    "notes": "Start at skill://lib/s/SKILL.md.",
                }
            ]
        }
    )
    with _served(KnowledgeBase(config, tmp_path / "cache")) as url:
        async def told(headers):
            async with _client(url, headers) as client:
                return client.instructions

        plain = await told({})
        both = await told({"Kb-Library": "lib", **PREFIX})
    assert "Start at skill://lib/s/SKILL.md." in plain
    assert "Start at kb+skill://lib/s/SKILL.md." in both
