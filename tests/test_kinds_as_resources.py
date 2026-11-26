"""``prompts://`` and ``agents://`` through kb: its scope, the prefix, a collision.

The resources are kubed-mcp's (PRM-63, AGT-19); these pin them to kb's view.
"""

import pytest

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.config import Config
from tests.conftest import http_client, serve_http, server_of
from tests.test_instructions import CMD, _skill, _three
from tests.test_plugin_serving import market

URIS = [
    "prompts://lib/_index.md",
    "prompts://lib/top.md",
    "prompts://lib/a/_index.md",
    "prompts://lib/a/hello.md",
    "agents://lib/b/_index.md",
    "agents://lib/b/helper.md",
    "prompts://else/_index.md",
    "prompts://else/other.md",
]
PREFIX = {"Kb-Resource-Prefix": "kb+"}


def _two_libraries(tmp_path) -> KnowledgeBase:
    """``lib`` (``_three``) beside ``else``, one skill and one command."""
    config = _three(tmp_path)
    other = market(
        tmp_path,
        [{"name": "else", "source": "./p"}],
        {"p/skills/e/SKILL.md": _skill("e"), "p/commands/other.md": CMD},
        name="else",
    )
    both = Config.model_validate(
        {
            "libraries": [
                *(
                    lib.model_dump(mode="json", exclude_defaults=True)
                    for lib in config.libraries
                ),
                *(
                    lib.model_dump(mode="json", exclude_defaults=True)
                    for lib in other.libraries
                ),
            ]
        }
    )
    return KnowledgeBase(both, tmp_path / "cache")


def _absent_twin(uri: str) -> str:
    if uri.endswith("/_index.md"):
        return "prompts://nope/_index.md"
    return uri.rsplit("/", 1)[0] + "/nope.md"


async def _outcome(client, uri, prefix=""):
    """The text ``uri`` reads, or ``(type, message with the address as <uri>)``."""
    sent = prefix + uri
    try:
        return (await client.read_resource(sent))[0].text
    except Exception as error:  # noqa: BLE001 - the failure is the datum
        return (type(error).__name__, str(error).replace(sent, "<uri>"))


@pytest.mark.integration
async def test_every_scope_reads_an_addition_or_an_absence(tmp_path):
    kb = _two_libraries(tmp_path)
    with serve_http(kb) as url:
        reads = {
            "?library=lib": URIS[:6],
            "?library=else": URIS[6:],
            "?tag=t": URIS[2:4],
        }
        for headers in ({}, PREFIX):
            prefix = headers.get("Kb-Resource-Prefix", "")
            async with http_client(url, headers) as client:
                baseline = {uri: await _outcome(client, uri, prefix) for uri in URIS}
            assert all(isinstance(t, str) for t in baseline.values()), baseline
            for query, readable in reads.items():
                async with http_client(url + query, headers) as client:
                    for uri in URIS:
                        got = await _outcome(client, uri, prefix)
                        if uri in readable:
                            assert got == baseline[uri], (query, headers, uri)
                            continue
                        twin = _absent_twin(uri)
                        if uri.startswith("agents://"):
                            twin = twin.replace("prompts://", "agents://")
                        assert isinstance(got, tuple), (query, headers, uri, got)
                        assert got == await _outcome(client, twin, prefix), (
                            query,
                            headers,
                            uri,
                        )


@pytest.mark.integration
async def test_the_prefixed_address_reads_through_both_paths(tmp_path):
    kb = KnowledgeBase(_three(tmp_path), tmp_path / "cache")
    with serve_http(kb) as url:
        async with http_client(url, PREFIX) as client:
            plain = (await client.read_resource("prompts://lib/top.md"))[0].text
            sent = (await client.read_resource("kb+prompts://lib/top.md"))[0].text
            assert sent == plain
            index = (await client.read_resource("kb+prompts://lib/_index.md"))[0].text
            assert "kb+prompts://lib/top.md" in index
            agent = (await client.read_resource("kb+agents://lib/b/helper.md"))[0].text
            assert "helper" in agent
        async with http_client(url, {**PREFIX, "X-MCP-Resources": "off"}) as client:
            result = await client.call_tool(
                "read_resource", {"uri": "kb+prompts://lib/top.md"}
            )
            assert result.content[0].text == plain


@pytest.mark.integration
async def test_two_files_at_one_prompts_place_serve_one(tmp_path):
    config = market(
        tmp_path,
        [{"name": "lib", "source": "./p"}],
        {
            "p/skills/s/SKILL.md": _skill("s"),
            "p/commands/prompts/x.md": CMD,
            "p/prompts/x.md": CMD,
        },
    )
    kb = KnowledgeBase(config, tmp_path / "cache")
    server_of(kb)
    assert [p.name for p in kb.snapshot.prompts] == ["lib_prompts_x"]
    status = kb.status["plugins"]["lib@lib"]
    assert status["prompts"] == 1
    assert status["skipped"] == [
        {
            "path": "prompts/x.md",
            "reason": "prompts://lib/prompts/x.md is already served by commands/prompts/x.md",
        }
    ]
    with serve_http(kb) as url:
        async with http_client(url) as client:
            names = [p.name for p in await client.list_prompts()]
            assert [n for n in names if n in ("lib_prompts_x", "lib_x")] == [
                "lib_prompts_x"
            ]
            index = (await client.read_resource("prompts://lib/prompts/_index.md"))[
                0
            ].text
            assert index.count("prompts://lib/prompts/x.md") == 1
