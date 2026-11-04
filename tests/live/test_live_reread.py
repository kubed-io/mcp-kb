"""AGT-16: a live agent file is re-read on `agents/get`, over a real WebDAV share."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from kubed.mcp_kb.sources import live
from tests.live.kb import agent_names, definition, health
from tests.webdav_server import PASSWORD

pytestmark = pytest.mark.live


async def _edit(path: Path, text: str) -> None:
    """Write `text`, which must differ in length, and outwait the revalidation TTL.

    wsgidav's ETag is `inode-mtime-size`, so a same-length edit within the same
    second would be the same ETag and the re-read would pass for no reason.
    """
    assert len(text.encode()) != path.stat().st_size
    path.write_text(text)
    await asyncio.sleep(live.TTL_SECONDS + 0.5)


def _agent(frontmatter: str, body: str) -> str:
    return f"---\n{frontmatter}\n---\n{body}\n"


async def test_a_live_agent_is_reread(kb_url, dav_dir):
    """AGT-16: an edit shows on the next `agents/get`; a broken one falls back."""
    path = dav_dir / "agents/editable.md"
    original = path.read_text()
    try:
        first = await definition(kb_url, "dav_editable", "dav")
        assert first["instructions"] == "Original body.\n"

        await _edit(
            path,
            _agent(
                "name: editable\ndescription: Edited live.",
                "The edited body, which is longer.",
            ),
        )
        edited = await definition(kb_url, "dav_editable", "dav")
        assert edited["instructions"] == "The edited body, which is longer.\n"

        await _edit(path, "---\nname: [unclosed\n---\nHalf saved.\n")
        broken = await definition(kb_url, "dav_editable", "dav")
        assert broken["instructions"] == "Original body.\n"

        await _edit(
            path,
            _agent(
                "name: renamed-on-disk\ndescription: Edited live.",
                "Renamed on disk.",
            ),
        )
        renamed = await definition(kb_url, "dav_editable", "dav")
        assert renamed["agent"] == "dav_editable"
        assert renamed["instructions"] == "Renamed on disk.\n"
        assert await agent_names(kb_url, "dav") == ["dav_editable"]
    finally:
        # Not `_edit`: its length guard would hide a failure before any edit.
        if path.read_text() != original:
            path.write_text(original)
            await asyncio.sleep(live.TTL_SECONDS + 0.5)


def test_health_names_no_dav_url_or_credential(kb_url, dav_dir):
    """HTTP-11, SRC-25: a backend is config-only; /health shows no URL or credential."""
    report = health(kb_url)
    text = json.dumps(report)
    leaks = [n for n in (PASSWORD, "127.0.0.1:8090", "webdav+") if n in text]
    assert not leaks, f"/health carries {len(leaks)} backend detail(s)"
    assert any(f.get("live") is True for f in report["fetches"].values())
