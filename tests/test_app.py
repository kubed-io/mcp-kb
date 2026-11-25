"""The server ``create_app`` builds: the knowledge base and the catalogue it injects."""

import json
import logging
import sys

import pytest
from fastmcp import Client
from kubed.mcp import Inject

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.app import create_app
from kubed.mcp_kb.catalogue.uris import Catalogue
from kubed.mcp_kb.config import Config
from tests.conftest import make_config

pytestmark = pytest.mark.unit


async def test_the_resource_mirror_is_kubed_mcps_over_kbs_rows(skills_dir, tmp_path):
    """N4: the resource tools are the plugin layer's (DLV-6), with no
    parameter but ``uri``, and list what ``resources/list`` lists."""
    app = create_app(KnowledgeBase(make_config(skills_dir), tmp_path / "cache"))
    listing = await app.get_tool("list_resources")
    reading = await app.get_tool("read_resource")

    async with Client(app.server) as client:
        listed = await client.call_tool("list_resources", {})
        resources = {str(r.uri) for r in await client.list_resources()}

    assert listing.parameters.get("properties", {}) == {}
    assert set(reading.parameters["properties"]) == {"uri"}
    rows = {row["uri"] for row in json.loads(listed.content[0].text)["resources"]}
    assert rows == resources
    assert "skill://deepsource/_index.md" in rows


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


async def test_the_telemetry_section_reaches_the_server(
    skills_dir, tmp_path, monkeypatch, caplog
):
    """The config is validated so that the section is the field's, not an
    attribute set on the side."""
    monkeypatch.setitem(sys.modules, "pyroscope", None)
    base = make_config(skills_dir).model_dump(mode="json", by_alias=True)
    config = Config.model_validate(
        {**base, "telemetry": {"profiles": "http://pyroscope.example.com:4040"}}
    )
    app = create_app(KnowledgeBase(config, tmp_path / "cache"))
    with caplog.at_level(logging.WARNING):
        async with Client(app.server) as client:
            assert await client.list_resources()
    warned = [r for r in caplog.records if "kubed-mcp[telemetry]" in r.getMessage()]
    assert len(warned) == 1


async def test_no_telemetry_section_starts_no_signal(skills_dir, tmp_path, caplog):
    app = create_app(KnowledgeBase(make_config(skills_dir), tmp_path / "cache"))
    with caplog.at_level(logging.WARNING):
        async with Client(app.server) as client:
            assert await client.list_resources()
    assert not [r for r in caplog.records if "kubed-mcp[telemetry]" in r.getMessage()]
