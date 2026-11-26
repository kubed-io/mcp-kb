"""kubed-mcp 0.3.0's delivery layer, checked before kb builds on it (Task 0).

No kb code here: a ``QuickMCP`` and one plugin folder. These are the go/no-go
facts for what ``resources/list`` shows by ``Listed``, how the resource pair is
annotated, that ``list_resources`` is not paged, and what an ``instructions``
function is handed. The ``Client`` is FastMCP's, which tests may import.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastmcp import Client
from fastmcp.skills import SkillsClientExtension
from kubed.mcp import QuickMCP

from tests.test_server import VS_CODE

_SKILLS_ID = "io.modelcontextprotocol/skills"


def _delivery(listed):
    return SimpleNamespace(resources=None, listed=listed, via=None)


def _plugin(folder: Path, skills=("a", "b"), extras=True) -> Path:
    """A plugin folder with ``skills`` and, if ``extras``, a command and an agent."""
    for name in skills:
        path = folder / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nname: {name}\ndescription: Skill {name}.\n---\nBody.\n")
    if extras:
        (folder / "commands").mkdir(parents=True, exist_ok=True)
        (folder / "commands" / "top.md").write_text("---\ndescription: D.\n---\nB.\n")
        (folder / "agents").mkdir(parents=True, exist_ok=True)
        (folder / "agents" / "helper.md").write_text(
            "---\nname: helper\ndescription: H.\n---\nB.\n"
        )
    return folder


def _served(tmp_path: Path, delivery=None, config=True, **plugin) -> QuickMCP:
    """A ``QuickMCP("mcp-kb")`` serving one plugin at ``lib``, and a resource of its own.

    ``config=True`` passes ``SimpleNamespace(delivery=delivery)``; ``False`` passes
    no config at all, which reaches ``getattr(config, "delivery", None)`` as None.
    """
    kwargs = {"config": SimpleNamespace(delivery=delivery)} if config else {}
    mcp = QuickMCP("mcp-kb", **kwargs)
    staging = mcp.plugin_set()
    staging.add(
        _plugin(tmp_path / "lib", **plugin),
        namespace="lib",
        manifest={"name": "p", "commands": ["./commands"]},
    )
    mcp.serve(staging)
    mcp.server.resource("kb://own")(lambda: "x")
    return mcp


async def _uris(mcp: QuickMCP) -> list[str]:
    return [str(resource.uri) for resource in await mcp.server.list_resources()]


@pytest.mark.unit
async def test_the_default_lists_a_skill_md_row_per_skill(tmp_path):
    """No ``delivery`` on the config lists ``skills`` only: one row per skill.

    Observed for ``skill://lib/a/SKILL.md``: name ``lib/a/SKILL.md``, description
    ``Skill a.``, mimeType ``text/markdown``. No config is passed, so
    kubed-mcp's ``getattr(config, "delivery", None)`` is None.
    """
    mcp = _served(tmp_path, config=False)
    uris = await _uris(mcp)
    assert {"skill://lib/a/SKILL.md", "skill://lib/b/SKILL.md", "kb://own"} <= set(uris)
    assert not [
        u for u in uris if u.endswith(("_index.md", "_index.json", "_manifest"))
    ]
    assert not [u for u in uris if u.startswith(("prompts://", "agents://"))]
    row = next(
        r
        for r in await mcp.server.list_resources()
        if str(r.uri) == "skill://lib/a/SKILL.md"
    )
    assert (row.name, row.description, row.mime_type) == (
        "lib/a/SKILL.md",
        "Skill a.",
        "text/markdown",
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("listed", "scheme"),
    [
        (frozenset({"prompts"}), "prompts://"),
        (frozenset({"agents"}), "agents://"),
        (frozenset(), None),
    ],
)
async def test_listed_chooses_the_plugin_rows(tmp_path, listed, scheme):
    uris = await _uris(_served(tmp_path, _delivery(listed)))
    assert "kb://own" in uris  # server-own: always listed
    assert not [u for u in uris if u.startswith("skill://")]
    plugin = [u for u in uris if u != "kb://own"]
    assert bool(plugin) == bool(scheme)
    assert all(u.startswith(scheme) for u in plugin)


@pytest.mark.unit
async def test_the_resource_pair_is_annotated_as_tool_6_says(tmp_path):
    mcp = _served(tmp_path)
    for name, title in (
        ("list_resources", "List resources"),
        ("read_resource", "Read a resource"),
    ):
        hints = (await mcp.server.get_tool(name)).annotations
        assert (
            hints.title,
            hints.read_only_hint,
            hints.destructive_hint,
            hints.idempotent_hint,
            hints.open_world_hint,
        ) == (title, True, False, True, False)


@pytest.mark.unit
async def test_list_resources_is_not_paged(tmp_path):
    names = [f"s{i:03d}" for i in range(120)]
    mcp = _served(tmp_path, skills=names, extras=False)
    async with Client(mcp.server) as client:
        page = await client.session.list_resources()
        assert page.next_cursor is None
        result = await client.call_tool("list_resources", {})
    rows = json.loads(result.content[0].text)["resources"]
    skills = [row["uri"] for row in rows if row["uri"].startswith("skill://")]
    assert len(skills) == 120
    assert all(uri.endswith("/SKILL.md") for uri in skills)


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_fn_is_handed_the_resolution(tmp_path, mode):
    mcp = _served(tmp_path)
    seen = []
    mcp.instructions(lambda delivery: seen.append(delivery) or "T")

    async with Client(mcp.server, mode=mode) as client:
        assert client.instructions == "T"
    assert seen[-1].resources == "on"
    assert not (seen[-1].extensions or ())

    async with Client(mcp.server, mode=mode, client_info=VS_CODE) as client:
        assert client.instructions == "T"
    assert seen[-1].resources == "off"

    async with Client(
        mcp.server, mode=mode, extensions=[SkillsClientExtension()]
    ) as client:
        assert client.instructions == "T"
    assert _SKILLS_ID in seen[-1].extensions
