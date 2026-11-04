"""Plugin-qualified skill names, read back through a running server.

A ``SKILL.md`` body and an agent's instructions cite ``<plugin>:<skill>``; the
server serves each as the ``skill://`` address that resolves (SKL-54, SKL-55),
within the caller's scope, and an agent's ``skills:`` entries come back as a
map to addresses (AGT-17). Scope exists only inside an HTTP request, so this
runs against a real server on a loopback port.
"""

import hashlib
import json
import threading

import httpx
import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.config import Config
from tests.test_header_scope import _free_port

pytestmark = pytest.mark.integration

NAMES = (
    "A kit:writing\n"
    "B /kit:writing\n"
    "C kit-extra:ops\n"
    "D kit:nope\n"
    "E https://kit:writing\n"
    "F /kit:db:migrate\n"
    "G /kit:cite\n"  # a skill and a command share the name: the skill wins
)
RESOLVED = (
    "A skill://kit/writing/SKILL.md\n"
    "B skill://kit/writing/SKILL.md\n"
    "C skill://kit/ops/SKILL.md\n"
    "D kit:nope\n"
    "E https://kit:writing\n"
    "F /kit:db:migrate\n"
    "G skill://kit/cite/SKILL.md\n"
)
HEAD = "---\nname: cite\ndescription: See kit:writing.\n---\n\n"
SKILL_ON_DISK = HEAD + NAMES  # what _build writes to kit's skills/cite/SKILL.md

AGENT = (
    "---\n"
    "name: helper\n"
    "description: Helps.\n"
    "skills:\n"
    "  - kit:writing\n"
    "  - writing\n"
    "  - kit-extra:ops\n"
    "  - nope\n"
    "---\n" + NAMES
)


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _build(base):
    kit = base / "kit"
    _write(
        kit,
        "skills/writing/SKILL.md",
        "---\nname: writing\ndescription: Write things.\n---\n\nWrite.\n",
    )
    _write(kit, "skills/cite/SKILL.md", SKILL_ON_DISK)
    _write(kit, ".claude-plugin/plugin.json", json.dumps({"name": "kit"}))
    _write(kit, "agents/helper.md", AGENT)
    _write(
        kit,
        "commands/cite.md",
        "---\ndescription: Cite.\n---\n" + NAMES + "H $ARGUMENTS\n",
    )

    extra = base / "extra"
    _write(
        extra,
        "skills/ops/SKILL.md",
        "---\nname: ops\ndescription: Run things.\n---\n\nBody.\n",
    )

    return Config.model_validate(
        {
            "plugins": [
                {"name": "kit", "source": f"file://{kit}", "tags": ["core"]},
                {"name": "kit-extra", "source": f"file://{extra}", "tags": ["extra"]},
            ],
            "libraries": [{"name": "kit", "plugins": ["kit", "kit-extra"]}],
        }
    )


@pytest.fixture(scope="module")
def url(tmp_path_factory):
    base = tmp_path_factory.mktemp("qualified-names")
    app = KnowledgeBase(_build(base), base / "_cache").mcp.http_app()
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
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


def _headers(tags=None, prefix=None):
    headers = {"Kb-Tag": tags} if tags else {}
    if prefix:
        headers["Kb-Resource-Prefix"] = prefix
    return headers


async def _read(url, uri, tags=None, prefix=None):
    client = Client(StreamableHttpTransport(url, headers=_headers(tags, prefix)))
    async with client:
        return (await client.read_resource(uri))[0].text


async def _raw(url, method, headers, **params) -> dict:
    """One sessionless 2026-07-28 request."""
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
    return response.json()["result"]


async def _skills_get(url, uri, tags=None):
    return (await _raw(url, "skills/get", _headers(tags), uri=uri))["skill"]


async def _agent(url, name, tags=None, prefix=None):
    return await _raw(url, "agents/get", _headers(tags, prefix), name=name)


async def _prompt(url, name, arguments=None):
    client = Client(StreamableHttpTransport(url))
    async with client:
        got = await client.get_prompt(name, arguments)
    return got.messages[0].content.text


async def _prompt_tool(url, name, arguments=None):
    client = Client(
        StreamableHttpTransport(url, headers={"X-MCP-Prompts": "off"})
    )
    async with client:
        result = await client.call_tool(
            "get_prompt", {"name": name, "arguments": arguments or {}}
        )
    return json.loads(result.content[0].text)["messages"][0]["content"]


async def test_a_skill_body_reads_qualified_names_as_addresses(url):
    body = await _read(url, "skill://kit/cite/SKILL.md")
    assert body == HEAD + RESOLVED


async def test_an_out_of_scope_skill_is_left_as_written(url):
    body = await _read(url, "skill://kit/cite/SKILL.md", tags="core")
    assert "C kit-extra:ops\n" in body and "A skill://kit/writing/SKILL.md\n" in body


async def test_a_rewritten_name_takes_the_prefix_once(url):
    body = await _read(url, "skill://kit/cite/SKILL.md", prefix="kb+")
    assert "A kb+skill://kit/writing/SKILL.md\n" in body and "kb+kb+" not in body


async def test_the_extension_digest_follows_the_rewrite(url):
    entry = await _skills_get(url, "skill://kit/cite/SKILL.md")
    body = await _read(url, "skill://kit/cite/SKILL.md")
    (main,) = [r for r in entry["resources"] if r["uri"].endswith("/cite/SKILL.md")]
    assert main["digest"] == "sha256:" + hashlib.sha256(body.encode()).hexdigest()
    assert entry["frontmatter"]["description"] == "See kit:writing."


async def test_the_manifest_still_describes_disk_bytes(url):
    manifest = json.loads(await _read(url, "skill://kit/cite/_manifest"))
    (main,) = [f for f in manifest["files"] if f["path"] == "SKILL.md"]
    assert main["size"] == len(SKILL_ON_DISK.encode())


async def test_an_agent_reads_names_as_addresses_and_preloads_its_skills(url):
    definition = await _agent(url, "kit_helper")
    assert definition["instructions"] == RESOLVED
    meta = definition["_meta"]["io.kubed.mcp-kb/agent"]
    assert meta["skills"] == {
        "kit:writing": "skill://kit/writing/SKILL.md",
        "writing": "skill://kit/writing/SKILL.md",
        "kit-extra:ops": "skill://kit/ops/SKILL.md",
    }
    assert meta["frontmatter"]["skills"] == [
        "kit:writing", "writing", "kit-extra:ops", "nope"
    ]


async def test_a_scoped_agent_preloads_only_what_it_can_see(url):
    meta = (await _agent(url, "kit_helper", tags="core"))["_meta"][
        "io.kubed.mcp-kb/agent"
    ]
    assert "kit-extra:ops" not in meta["skills"]


async def test_the_preload_map_is_never_prefixed(url):
    meta = (await _agent(url, "kit_helper", prefix="kb+"))["_meta"][
        "io.kubed.mcp-kb/agent"
    ]
    assert meta["skills"]["writing"] == "skill://kit/writing/SKILL.md"


async def test_a_prompt_body_reads_qualified_names_as_addresses(url):
    assert await _prompt(url, "kit_cite") == RESOLVED + "H \n"


async def test_an_argument_value_is_never_rewritten(url):
    text = await _prompt(url, "kit_cite", {"arguments": "kit:writing"})
    assert text == RESOLVED + "H kit:writing\n"


async def test_the_prompt_mirror_rewrites_alike(url):
    assert await _prompt_tool(url, "kit_cite") == RESOLVED + "H \n"
