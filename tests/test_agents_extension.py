"""The Agents extension through real MCP requests, in both eras and over HTTP.

Every assertion here is about what a client sees on the wire: the declaration,
the envelope, the cards, the definition and the errors. Scope only exists inside
an HTTP request, so the scoping tests serve ``agents_tree`` over real uvicorn.
"""

from __future__ import annotations

import json
import shutil
import socket
import threading

import httpx
import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp.shared.exceptions import MCPError
from mcp_types import SERVER_INFO_META_KEY

from kubed.mcp_kb.mcp.request import AGENTS_EXTENSION_ID, EXTENSION_ID
from tests.test_agents import DIAGRAMMER, agents_tree
from tests.test_skills_extension import request

ERAS = pytest.mark.parametrize("mode", ["auto", "legacy"])
ENVELOPE = {"resultType": "complete", "ttlMs": 0, "cacheScope": "private"}
NOT_FOUND = (-32602, "Agent not found", {"reason": "agent_not_found"})
ROW_7 = (
    "The scope names tag 'nonesuch', which nothing carries. The tags are:"
    " diagrams, diagrams.net, drawio, extra, lonely, mcp, mxgraph."
)
SEE = "see: skill://drawio/drawio/SKILL.md\n"
COMMAND = "---\ndescription: Draw one.\n---\nDraw a diagram.\n"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ours(result: dict) -> dict:
    """``result`` without the stamp a 2026-era runner puts on every result."""
    meta = dict(result.get("_meta", {}))
    meta.pop(SERVER_INFO_META_KEY, None)
    rest = {k: v for k, v in result.items() if k != "_meta"}
    return {**rest, "_meta": meta} if meta else rest


def _failure(error: pytest.ExceptionInfo[MCPError]) -> tuple:
    return error.value.code, error.value.message, error.value.data


# -- in process, both eras ----------------------------------------------------


@pytest.mark.unit
@ERAS
async def test_both_extensions_are_declared(tmp_path, mode):
    server = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")
    async with Client(server.mcp, mode=mode) as client:
        caps = client.session.server_capabilities
        assert caps.extensions[AGENTS_EXTENSION_ID] == {"listChanged": False}
        assert caps.extensions[EXTENSION_ID] == {}


@pytest.mark.unit
@ERAS
async def test_list_returns_cards(tmp_path, mode):
    server = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")
    async with Client(server.mcp, mode=mode) as client:
        listing = _ours(await request(client, "agents/list"))
    assert {k: listing[k] for k in ENVELOPE} == ENVELOPE
    assert set(listing) == {*ENVELOPE, "agents"}
    assert [card["name"] for card in listing["agents"]] == [
        "drawio_db_migrator",
        "drawio_diagrammer",
        "drawio_diagrammer@extra",
        "drawio_twin",
        "lone_solo",
    ]
    for card in listing["agents"]:
        assert set(card) == {"name", "description", "capabilities"}
    assert listing["agents"][1] == {
        "name": "drawio_diagrammer",
        "description": "Draws diagrams.",
        "capabilities": [],
    }


@pytest.mark.unit
@ERAS
async def test_get_returns_the_definition(tmp_path, mode):
    server = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")
    async with Client(server.mcp, mode=mode) as client:
        got = _ours(await request(client, "agents/get", name="drawio_diagrammer"))
        again = _ours(await request(client, "agents/get", name="drawio_diagrammer"))
    assert got == again
    assert got == {
        **ENVELOPE,
        "agent": "drawio_diagrammer",
        "instructions": (
            "Read skill://drawio/drawio/SKILL.md in ${CLAUDE_PROJECT_DIR}.\n"
        ),
        "modelRoutingHint": {"role": "medium", "vision": False},
        "tools": [],
        "_meta": {
            "io.kubed.mcp-kb/agent": {
                "plugin": "drawio@drawio",
                "library": "drawio",
                "path": "agents/diagrammer.md",
                "frontmatter": {
                    "name": "diagrammer",
                    "description": "Draws diagrams.",
                    "model": "sonnet",
                    "color": "cyan",
                },
                "servers": ["drawio"],
            }
        },
    }


@pytest.mark.unit
@ERAS
async def test_unknown_is_agent_not_found(tmp_path, mode):
    server = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")
    async with Client(server.mcp, mode=mode) as client:
        for name in ("nobody", "drawio_x", "solo", "drive_x"):
            with pytest.raises(MCPError) as error:
                await request(client, "agents/get", name=name)
            assert _failure(error) == NOT_FOUND


@pytest.mark.unit
@ERAS
async def test_a_cursor_is_refused(tmp_path, mode):
    server = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")
    async with Client(server.mcp, mode=mode) as client:
        with pytest.raises(MCPError) as error:
            await request(client, "agents/list", cursor="not-issued")
    assert (error.value.code, error.value.message) == (-32602, "Invalid agents cursor")


async def _surface(server, mode) -> dict:
    async with Client(server.mcp, mode=mode) as client:
        return {
            "tools": await client.list_tools(),
            "resources": await client.list_resources(),
            "prompts": await client.list_prompts(),
            "instructions": client.instructions,
        }


@pytest.mark.unit
@ERAS
async def test_nothing_else_changes(tmp_path, mode):
    """AGT-2: the same tree with every ``agents/`` gone serves the same rest."""
    with_agents = agents_tree(tmp_path / "with")
    without = agents_tree(tmp_path / "without")
    for tree in (with_agents, without):
        # A prompt, so the prompts listing has a row to compare.
        command = tree.root / "market/plugins/drawio/commands/draw.md"
        command.parent.mkdir(parents=True)
        command.write_text(COMMAND)
    removed = sorted(without.root.rglob("agents"))
    assert removed
    for folder in removed:
        shutil.rmtree(folder)

    served = await _surface(with_agents.knowledge_base(tmp_path / "c1"), mode)
    bare = await _surface(without.knowledge_base(tmp_path / "c2"), mode)

    assert served["prompts"]
    assert served["resources"]
    assert served == bare


# -- over HTTP ----------------------------------------------------------------


@pytest.fixture(scope="module")
def url(tmp_path_factory):
    base = tmp_path_factory.mktemp("agents-extension")
    tree = agents_tree(base)
    # An address in the frontmatter, which a prefix must leave as written.
    diagrammer = base / "market/plugins/drawio/agents/diagrammer.md"
    diagrammer.write_text(DIAGRAMMER.replace("color: cyan\n", SEE + "color: cyan\n"))
    app = tree.knowledge_base(base / "_cache").mcp.http_app()
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
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


def _client(url, headers=None):
    return Client(StreamableHttpTransport(url, headers=headers or {}))


async def _names(url, headers=None) -> list[str]:
    async with _client(url, headers) as client:
        listing = await request(client, "agents/list")
    return [card["name"] for card in listing["agents"]]


async def _get_failure(url, name, headers=None) -> tuple:
    async with _client(url, headers) as client:
        with pytest.raises(MCPError) as error:
            await request(client, "agents/get", name=name)
    return _failure(error)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("where", "headers"),
    [
        ("?tag=diagrams", {}),
        ("", {"Kb-Tag": "diagrams"}),
        ("?category=diagrams", {}),
    ],
)
async def test_tag_and_category_scope_list_the_diagrammer(url, where, headers):
    assert await _names(url + where, headers) == ["drawio_diagrammer"]


@pytest.mark.integration
async def test_out_of_scope_is_agent_not_found(url):
    extra = {"Kb-Tag": "extra"}
    hidden = await _get_failure(url, "drawio_diagrammer", extra)
    unknown = await _get_failure(url, "nobody", extra)
    unscoped = await _get_failure(url, "nobody")

    assert hidden == unknown == unscoped == NOT_FOUND
    # In scope for anyone else, so the failure above is the scope's doing.
    async with _client(url, {"Kb-Tag": "diagrams"}) as client:
        got = await request(client, "agents/get", name="drawio_diagrammer")
    assert got["agent"] == "drawio_diagrammer"


@pytest.mark.integration
async def test_a_scoped_caller_sees_the_library_name(url):
    names = await _names(url, {"Kb-Category": "other"})

    assert "drawio_diagrammer@extra" in names
    assert "drawio_diagrammer" not in names
    async with _client(url, {"Kb-Category": "other"}) as client:
        got = await request(client, "agents/get", name="drawio_diagrammer@extra")
    assert got["agent"] == "drawio_diagrammer@extra"


@pytest.mark.integration
async def test_a_scope_of_only_agents_is_served(url):
    """SCP-31 row 9: a plugin of nothing but agents is something to serve."""
    assert await _names(url, {"Kb-Tag": "lonely"}) == ["lone_solo"]


async def _raw(url, method, headers, **params) -> dict:
    """One sessionless 2026-07-28 request, so a refused scope reaches the method."""
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {
            **params,
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientInfo": {"name": "t", "version": "0"},
                "io.modelcontextprotocol/clientCapabilities": {},
            },
        },
    }
    async with httpx.AsyncClient() as http:
        response = await http.post(
            url,
            content=json.dumps(message),
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
                "mcp-protocol-version": "2026-07-28",
                "mcp-method": method,
                **headers,
            },
        )
    return response.json()


@pytest.mark.integration
async def test_a_refused_scope_fails_both_methods(url):
    refused = {"Kb-Tag": "nonesuch"}
    for method, params in (
        ("agents/list", {}),
        ("agents/get", {"name": "drawio_diagrammer"}),
    ):
        answer = await _raw(url, method, refused, **params)
        assert answer["error"] == {"code": -32602, "message": ROW_7}, method
    # The same request, unrefused, is answered: the refusal is the scope's.
    answer = await _raw(url, "agents/get", {}, name="drawio_diagrammer")
    assert answer["result"]["agent"] == "drawio_diagrammer"


@pytest.mark.integration
async def test_a_library_scope(url):
    assert await _names(url, {"Kb-Library": "lone"}) == ["lone_solo"]
    assert await _get_failure(url, "drawio_diagrammer", {"Kb-Library": "lone"}) == (
        NOT_FOUND
    )


@pytest.mark.integration
async def test_a_prefix_reaches_instructions_only(url):
    async with _client(url, {"Kb-Resource-Prefix": "kb+"}) as client:
        got = await request(client, "agents/get", name="drawio_diagrammer")
        listing = await request(client, "agents/list")

    assert got["instructions"] == (
        "Read kb+skill://drawio/drawio/SKILL.md in ${CLAUDE_PROJECT_DIR}.\n"
    )
    meta = got["_meta"]["io.kubed.mcp-kb/agent"]
    assert meta["frontmatter"] == {
        "name": "diagrammer",
        "description": "Draws diagrams.",
        "model": "sonnet",
        "see": "skill://drawio/drawio/SKILL.md",
        "color": "cyan",
    }
    assert "drawio_diagrammer" in [card["name"] for card in listing["agents"]]
