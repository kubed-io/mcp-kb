"""The server ``create_app`` builds: the knowledge base and the catalogue it injects."""

import json

import pytest
from fastmcp import Client
from kubed.mcp import Inject

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.app import create_app
from kubed.mcp_kb.catalogue.uris import Catalogue
from kubed.mcp_kb.mcp.scope import EVERYTHING
from tests.conftest import make_config

pytestmark = pytest.mark.unit


async def test_the_mirror_tools_take_the_catalogue_from_the_container(
    skills_dir, tmp_path
):
    """What the container resolves is what the tools read, and no client can
    pass it: the parameter is no part of either schema."""
    flat = make_config(skills_dir, libraries=["flatsource"])
    app = create_app(KnowledgeBase(flat, tmp_path / "flat"))
    deep = make_config(skills_dir, libraries=["deepsource"])
    other = KnowledgeBase(deep, tmp_path / "deep")
    app.override(Catalogue, other.catalogue)

    # Unfiltered: an in-memory client reads resources, so the mirror is hidden.
    tools = {t.name: t for t in await app.server.list_tools(run_middleware=False)}
    async with Client(app.server) as client:
        listed = await client.call_tool("list_resources", {})

    assert tools["list_resources"].parameters.get("properties", {}) == {}
    assert set(tools["read_resource"].parameters["properties"]) == {"uri"}
    rows = {row["uri"] for row in json.loads(listed.content[0].text)}
    assert rows == {entry.uri for entry in other.catalogue.entries(EVERYTHING)}
    assert "skill://deepsource/_index.md" in rows
    assert not any(uri.startswith("skill://flatsource/") for uri in rows)


async def test_a_call_reads_the_snapshot_serving_when_it_started(skills_dir, tmp_path):
    """``Catalogue`` is a transient over the ``KnowledgeBase`` singleton: one per
    call, the current snapshot's, so a refresh between calls is seen by the next."""
    knowledge_base = KnowledgeBase(make_config(skills_dir), tmp_path / "cache")
    app = create_app(knowledge_base)
    seen: list[tuple[bool, bool, bool, int]] = []

    @app.tool
    def probe(
        catalogue: Inject[Catalogue],
        again: Inject[Catalogue],
        kb: Inject[KnowledgeBase],
    ) -> str:
        current = catalogue is kb.snapshot.catalogue
        seen.append((kb is knowledge_base, current, catalogue is again, kb.generation))
        return "ok"

    async with Client(app.server) as client:
        await client.call_tool("probe", {})
        knowledge_base.refresh(force=True)
        await client.call_tool("probe", {})

    assert seen == [(True, True, True, 0), (True, True, True, 1)]

