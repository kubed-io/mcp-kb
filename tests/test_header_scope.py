"""The per-request knobs, exercised over real HTTP.

All three only exist inside an HTTP request, so an in-memory client cannot reach
this code at all: ``Kb-Library`` (which library), ``?resources=off`` (whether the
mirror is advertised) and ``?listed=`` (what the listing holds).
These tests run the ASGI app on a real port for that reason.
"""

import json
import socket
import threading
import urllib.request

import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from kubed.mcp_kb import KnowledgeBase
from tests.conftest import fetch_key, make_config, server_of


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server_url(skills_dir_module, prompts_dir_module):
    """Serve the skills app on a loopback port for the duration of the module."""
    port = _free_port()
    config = make_config(skills_dir_module, prompts_dir_module)
    app = server_of(KnowledgeBase(config, skills_dir_module / "_cache")).http_app()
    uvicorn_config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(uvicorn_config)
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


async def tool_names(url, headers=None):
    async with _client(url, headers) as client:
        return sorted(t.name for t in await client.list_tools())


async def resource_uris(url, headers=None):
    async with _client(url, headers) as client:
        return [str(r.uri) for r in await client.list_resources()]


async def call(url, tool, headers=None, **args):
    async with _client(url, headers) as client:
        result = await client.call_tool(tool, args, raise_on_error=False)
        return result.content[0].text


# -- the mirror toggle --------------------------------------------------------


@pytest.mark.integration
async def test_a_resource_client_is_shown_no_tools(server_url):
    """The mirror is noise to a client that can read the real thing."""
    assert await tool_names(server_url) == []


@pytest.mark.integration
async def test_resources_off_reveals_the_mirror(server_url):
    """n8n has no resources, so for n8n the mirror IS the server."""
    assert await tool_names(f"{server_url}?resources=off") == [
        "list_resources",
        "read_resource",
    ]


@pytest.mark.integration
@pytest.mark.parametrize("header", ["X-MCP-Resources", "Kb-Resources"])
async def test_the_header_declares_it_too(server_url, header):
    """A header can be set in a credential where a URL cannot."""
    names = await tool_names(server_url, headers={header: "off"})
    assert names == ["list_resources", "read_resource"]


@pytest.mark.integration
@pytest.mark.parametrize("header", ["X-MCP-Prompts", "Kb-Prompts"])
async def test_a_prompts_header_reveals_the_prompt_mirror(server_url, header):
    names = await tool_names(server_url, headers={header: "off"})
    assert names == ["get_prompt", "list_prompts"]


@pytest.mark.integration
async def test_kbs_prompts_header_wins_over_x_mcps(server_url):
    """DLV-16's order for kb's own input: ``Kb-`` first, as kubed-mcp reads."""
    headers = {"Kb-Prompts": "on", "X-MCP-Prompts": "off"}
    assert await tool_names(server_url, headers=headers) == []


@pytest.mark.integration
async def test_a_hidden_tool_is_still_callable(server_url):
    """Hiding from a listing is presentation; refusing to run would be a
    different and worse contract."""
    out = await call(
        server_url, "read_resource", uri="skill://flatsource/alpha/SKILL.md"
    )
    assert "First skill." in out


# -- the listing shape --------------------------------------------------------


FLAT = ["skill://flatsource/alpha/SKILL.md", "skill://flatsource/beta/SKILL.md"]
DEEP = [
    "skill://deepsource/plugin-a/gamma/SKILL.md",
    "skill://deepsource/plugin-b/delta/SKILL.md",
]


@pytest.mark.integration
async def test_the_listing_is_a_skill_md_row_per_skill_by_default(server_url):
    uris = await resource_uris(server_url)
    assert sorted(u for u in uris if u.endswith("SKILL.md")) == sorted(DEEP + FLAT)
    assert not any(u.endswith("_index.md") for u in uris)


@pytest.mark.integration
async def test_the_mirror_lists_the_same_rows(server_url):
    """A tools-only client is handed the rows ``resources/list`` returns."""
    rows = json.loads(await call(f"{server_url}?resources=off", "list_resources"))[
        "resources"
    ]
    assert [row["uri"] for row in rows] == await resource_uris(server_url)


# -- the library pin -----------------------------------------------------------


@pytest.mark.integration
async def test_no_header_sees_every_library(server_url):
    uris = await resource_uris(server_url)
    assert set(FLAT + DEEP) <= set(uris)


@pytest.mark.integration
async def test_the_pin_hides_the_other_library_from_the_listing(server_url):
    uris = await resource_uris(server_url, headers={"Kb-Library": "flatsource"})
    assert sorted(uris) == FLAT


@pytest.mark.integration
async def test_a_header_beats_the_same_setting_in_the_url(server_url):
    """The header is set in a credential, by an admin; the parameter rides on a
    URL somebody may paste. So a pasted ``?library=`` cannot reach past the pin
    an admin already set, and the two are read in that order everywhere.
    """
    uris = await resource_uris(
        f"{server_url}?library=deepsource", headers={"Kb-Library": "flatsource"}
    )
    assert sorted(uris) == FLAT


@pytest.mark.integration
async def test_the_pin_blocks_reading_a_resource_in_another_library(server_url):
    """The hole this closes: filtering a listing leaves guessable URIs readable,
    and every URI here is guessable by design."""
    async with _client(server_url, {"Kb-Library": "flatsource"}) as client:
        with pytest.raises(Exception, match=r"nknown|not found|deepsource"):
            await client.read_resource("skill://deepsource/plugin-a/gamma/SKILL.md")


@pytest.mark.integration
async def test_the_pin_blocks_the_mirror_too(server_url):
    """A scope enforced on only one half of the protocol is not a scope."""
    out = await call(
        f"{server_url}?resources=off",
        "read_resource",
        headers={"Kb-Library": "flatsource"},
        uri="skill://deepsource/plugin-a/gamma/SKILL.md",
    )
    # N4: kubed-mcp's read_resource words a miss as resources/read does.
    assert "Resource not found" in out


@pytest.mark.integration
async def test_the_pin_narrows_the_mirrors_listing(server_url):
    rows = json.loads(
        await call(
            f"{server_url}?resources=off",
            "list_resources",
            headers={"Kb-Library": "flatsource"},
        )
    )["resources"]
    assert sorted(row["uri"] for row in rows) == FLAT


@pytest.mark.integration
async def test_the_pin_still_allows_its_own_library(server_url):
    async with _client(server_url, {"Kb-Library": "flatsource"}) as client:
        body = (await client.read_resource("skill://flatsource/alpha/SKILL.md"))[
            0
        ].text
    assert "First skill." in body


@pytest.mark.integration
async def test_a_tag_header_narrows_by_the_plugins_labels(server_url):
    """`Kb-Tag` admits the plugins carrying the tag, and nothing else."""
    tagged = {"Kb-Tag": "deep"}
    uris = await resource_uris(server_url, headers=tagged)
    assert set(DEEP) <= set(uris)
    assert not any("flatsource" in u for u in uris)
    async with _client(server_url, tagged) as client:
        gamma = "skill://deepsource/plugin-a/gamma/SKILL.md"
        assert "Third skill." in (await client.read_resource(gamma))[0].text
        with pytest.raises(Exception, match=r"nknown|not found"):
            await client.read_resource("skill://flatsource/alpha/SKILL.md")


@pytest.mark.integration
async def test_the_listing_does_not_leak_other_library_names(server_url):
    """A pinned client must not learn the other libraries exist from a listing."""
    pinned = {"Kb-Library": "deepsource"}
    uris = await resource_uris(server_url, headers=pinned)
    assert uris
    assert not any("flatsource" in u for u in uris)


# -- prompts ------------------------------------------------------------------


async def prompt_names(url, headers=None):
    async with _client(url, headers) as client:
        return sorted(p.name for p in await client.list_prompts())


@pytest.mark.integration
async def test_the_pin_scopes_prompts_too(server_url):
    """Out of the pinned library, a prompt is neither listed nor renderable."""
    pinned = {"Kb-Library": "flatsource"}
    assert await prompt_names(server_url, pinned) == ["flatsource_hello"]
    async with _client(server_url, pinned) as client:
        with pytest.raises(Exception, match="deepsource_check"):
            await client.get_prompt("deepsource_check", {"service": "api"})


@pytest.mark.integration
async def test_a_tag_pin_sees_only_the_prompts_of_the_plugins_carrying_it(server_url):
    """A prompt carries its plugin's labels, and the prompts plugin carries none.

    `deepsource_check` comes from the `deepsource-prompts` plugin, which has no
    tags; the whole library still reaches it.
    """
    tagged = {"Kb-Tag": "deep"}
    assert await prompt_names(server_url, tagged) == []
    whole = {"Kb-Library": "deepsource"}
    assert await prompt_names(server_url, whole) == ["deepsource_check"]


# -- syncing skills to disk ---------------------------------------------------


@pytest.mark.integration
async def test_fastmcp_syncs_skills_from_the_listing(server_url, skills_dir_module):
    """The promise the listing keeps, checked with FastMCP's own client:
    it finds a skill by its /SKILL.md row, then reads every file its manifest
    names and checks each against the digest there."""
    alpha = "skill://flatsource/alpha/SKILL.md"
    async with _client(server_url) as client:
        found = {str(r.uri) for r in await client.list_skill_resources()}
        skill = await client.read_skill(alpha)
        [read] = await client.read_resource(alpha)
    assert found == {
        alpha,
        "skill://flatsource/beta/SKILL.md",
        "skill://deepsource/plugin-a/gamma/SKILL.md",
        "skill://deepsource/plugin-b/delta/SKILL.md",
    }
    source = skills_dir_module / "flatsource" / "alpha" / "SKILL.md"
    assert skill.name == "alpha"
    assert skill.files["SKILL.md"] == source.read_bytes()
    assert read.text == source.read_text()


# -- /health --------------------------------------------------------------------


@pytest.mark.integration
def test_health_reports_the_catalogue(server_url, skills_dir_module):
    """/health is plain HTTP outside the MCP protocol, so it is fetched directly."""
    url = server_url.removesuffix("/mcp") + "/health"
    with urllib.request.urlopen(url) as response:
        body = json.loads(response.read())
    assert body["status"] == "ok"
    assert sorted(body["libraries"]) == ["deepsource", "flatsource"]
    assert body["skills"] == 4
    assert body["prompts"] == 2
    assert body["generation"] == 0
    library = body["libraries"]["flatsource"]
    assert {k: library[k] for k in ("plugins", "skills", "prompts", "files")} == {
        "plugins": ["flatsource", "flatsource-prompts"],
        "skills": 2,
        "prompts": 1,
        "files": 0,
    }
    plugin = body["plugins"]["flatsource"]
    assert {k: plugin[k] for k in ("status", "libraries", "skills", "tags")} == {
        "status": "ok",
        "libraries": ["flatsource"],
        "skills": 2,
        "tags": ["flat"],
    }
    fetch = body["fetches"][fetch_key(skills_dir_module / "flatsource")]
    assert fetch["status"] == "ok"
    assert fetch["built"] and fetch["fingerprint"]["files"] == 3
    assert body["plugins"]["deepsource-prompts"]["status"] == "ok"
