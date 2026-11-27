"""SKL-64, INS-24: the unscoped cut of a running kb, derived from its own route."""

from __future__ import annotations

import pytest
from kubed.mcp.protocol import MCPError

from tests.live.kb import connect, health, read, rpc
from tests.test_skills_extension import request

pytestmark = pytest.mark.live

CAP = 100  # kubed-mcp's default; kb sets no delivery.max (D7)
LINE = "{listed} of {total} skills are listed; every skill reads through its library's _index.md."


async def indexed(kb_url) -> dict[str, str]:
    """Every SKILL.md the libraries' indexes reach, each with the _index.md that lists it."""
    todo = [f"skill://{lib}/_index.md" for lib in health(kb_url)["libraries"]]
    found: dict[str, str] = {}
    seen: set[str] = set()
    while todo:
        index = todo.pop()
        if index in seen:
            continue
        seen.add(index)
        try:
            text = await read(kb_url, index)
        except MCPError:
            continue  # an index with no skill (SKL-19) is not served
        for line in text.splitlines():
            uri, sep, _ = line.partition(": ")
            if not sep:
                continue
            if uri.endswith("/_index.md"):
                todo.append(uri)
            elif uri.endswith("/SKILL.md"):
                found[uri] = index
    return found


async def test_the_unscoped_cut_is_named_by_the_route(kb_url):
    found = await indexed(kb_url)
    assert found, "the index walk reached no skill"
    async with connect(kb_url) as client:  # unscoped, no Kb-Max
        listed = {e["uri"] for e in (await request(client, "skills/list"))["skills"]}
        told = client.instructions or ""
    total = len(found)
    cut = sorted(set(found) - listed)
    print("cut:", cut)  # the pull request's report names these
    assert listed <= set(found)
    assert len(listed) == min(CAP, total)
    count = LINE.format(listed=len(listed), total=total)
    assert (count in told) == bool(cut)  # the handshake's count: listed, total - listed
    if not cut:
        assert "skills are listed" not in told
    for uri in cut:
        assert (await rpc(kb_url, "skills/get", uri=uri))["skill"]["uri"] == uri
        assert await read(kb_url, uri)
        assert f"{uri}: " in await read(kb_url, found[uri])
