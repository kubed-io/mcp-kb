"""HTTP-41, SKL-53: the server rows of a running kb."""

from __future__ import annotations

import httpx
import pytest
import yaml
from mcp_types import SERVER_INFO_META_KEY

from tests.live.kb import connect, health, rpc

pytestmark = pytest.mark.live


async def test_serverinfo_is_kbs_own_version(kb_url):
    """HTTP-41: serverInfo and every result's _meta name kb and its version."""
    info = yaml.safe_load(httpx.get(f"{kb_url}/openapi.yaml").text)["info"]
    expected = {"name": "mcp-kb", "version": info["version"]}
    async with connect(kb_url, mode="legacy") as client:
        server_info = client.initialize_result.serverInfo
        assert {"name": server_info.name, "version": server_info.version} == expected
    listing = await rpc(kb_url, "agents/list")
    assert listing["_meta"][SERVER_INFO_META_KEY] == expected
    assert expected["version"] != "0.0.0"


async def test_one_template_names_the_skill_space(kb_url):
    """SKL-53: one fixed template row names the skill:// address space."""
    async with connect(kb_url) as client:
        templates = await client.list_resource_templates()
    assert [(t.uriTemplate, t.name) for t in templates] == [
        ("skill://{library}/{+path}", "skill")
    ]


def test_every_fixture_plugin_is_ok(kb_url):
    """HTTP-41: every fixture plugin loaded, and no fixture library errs."""
    report = health(kb_url)
    for plugin_id, plugin in report["plugins"].items():
        if plugin_id.endswith(("@live", "@live-other")):
            assert plugin["status"] == "ok", (plugin_id, plugin)
            assert not plugin.get("error"), (plugin_id, plugin)
    for name in ("live", "live-other", "clash", "clash-appended", "dav"):
        library = report["libraries"].get(name)
        if library is not None:
            assert not library.get("error"), (name, library)
            assert not library.get("conflicts"), (name, library)
