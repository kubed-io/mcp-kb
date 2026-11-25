"""kubed-mcp's own agent layer, checked before kb builds on it (K5, Task 0).

No kb code here: a ``QuickMCP`` and one plugin folder, served through the plugin
layer. These are the go/no-go for K5: that ``agent_meta`` runs as a plugin enters
a set and never in a build, what ``Plugin.agent_files`` and ``Plugin.skipped``
say, and what the layer exports for parsing an agent.
"""

from pathlib import Path

from fastmcp import Client
from kubed.mcp import QuickMCP
from kubed.mcp.agents import META_KEY, parse_agent
from kubed.mcp.plugins import AgentFile, Plugin, View
from kubed.mcp.protocol import RequestParams, types
from pydantic import ConfigDict, TypeAdapter

_NAMED = "---\nname: {name}\ndescription: D.\nmodel: {model}\n---\nBody.\n"


def _plugin(folder: Path) -> Path:
    """A plugin folder with one skill and six agent files, three of them served."""
    (folder / ".claude-plugin").mkdir(parents=True)
    (folder / ".claude-plugin" / "plugin.json").write_text('{"name": "p"}')
    skill = folder / "skills" / "s"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: s\ndescription: S.\n---\nS.\n")
    agents = folder / "agents"
    agents.mkdir()
    (agents / "a.md").write_text(_NAMED.format(name="a", model="claude-opus-5-5"))
    (agents / "b.md").write_text(_NAMED.format(name="b", model="opus4"))
    (agents / "twin-1.md").write_text(_NAMED.format(name="twin", model="x"))
    (agents / "twin-2.md").write_text(_NAMED.format(name="twin", model="x"))
    (agents / "latin.md").write_bytes(b"---\nname: l\xe9\n---\n")
    (agents / "colon.md").write_text(_NAMED.format(name='"a:b"', model="x"))
    return folder


class _Served:
    """A server serving ``_plugin`` at ``lib``, counting the hook's calls."""

    def __init__(self, tmp_path: Path) -> None:
        self.calls: list[str] = []
        self.view_key = "one"
        self.mcp = QuickMCP("mcp-kb")
        self.mcp.plugin_view(lambda: View(self.view_key, lambda plugin: True))

        @self.mcp.agent_meta
        def hook(name: str, plugin: Plugin) -> dict:
            self.calls.append(name)
            return {"io.example/seen": name}

        staging = self.mcp.plugin_set()
        staging.add(_plugin(tmp_path / "p"), namespace="lib")
        self.mcp.serve(staging)

    @property
    def plugin(self) -> Plugin:
        (plugin,) = self.mcp.plugins
        return plugin

    async def request(self, method: str, **params: object) -> dict:
        """``method`` sent as is, under the view ``view_key`` names."""

        class Params(RequestParams):
            model_config = ConfigDict(extra="allow")

        async with Client(self.mcp.server) as client:
            return await client.session.send_request(
                types.Request(method=method, params=Params(**params)),
                TypeAdapter(dict),
            )


async def test_agent_meta_runs_at_entry_and_never_in_a_build(tmp_path):
    served = _Served(tmp_path)
    entered = list(served.calls)
    assert sorted(entered) == sorted(served.plugin.agents)  # once per agent served
    assert len(entered) == len(set(entered)) == 3

    for key in ("one", "two"):  # two views, so two builds
        served.view_key = key
        await served.request("agents/list")
        await served.request("agents/get", name=entered[0])
    assert served.calls == entered  # no call in either build


async def test_agent_files_name_each_served_file(tmp_path):
    files = _Served(tmp_path).plugin.agent_files
    assert all(isinstance(f, AgentFile) for f in files)
    assert [(f.name, f.path, f.renamed) for f in files] == [
        ("lib_a", "agents/a.md", False),
        ("lib_b", "agents/b.md", False),
        ("lib_twin", "agents/twin-1.md", False),
    ]  # path order


async def test_the_routing_hint_is_agt9s(tmp_path):
    served = _Served(tmp_path)
    hints = {}
    for name in served.plugin.agents:
        got = await served.request("agents/get", name=name)
        hints[name] = got.get("modelRoutingHint")
    assert hints == {
        "lib_a": {"role": "large", "vision": False},
        "lib_b": None,
        "lib_twin": None,
    }


def test_parse_agent_reads_text_and_gives_the_frontmatter():
    parsed = parse_agent("---\nname: a\ndescription: d\nx: 1\n---\nBody.\n", stem="a")
    frontmatter = parsed.detail["_meta"][META_KEY]["frontmatter"]
    assert frontmatter == {"name": "a", "description": "d", "x": 1}
    assert (
        parse_agent("---\nname: a\n---\n", stem="a")
        == "its description must be a non-empty string"
    )


async def test_the_layers_skip_reasons(tmp_path):
    assert dict(_Served(tmp_path).plugin.skipped) == {
        "agents/twin-2.md": "agent lib_twin is already served by agents/twin-1.md",
        "agents/latin.md": (
            "'utf-8' codec can't decode byte 0xe9 in position 11: "
            "invalid continuation byte"
        ),
        "agents/colon.md": "agent name 'lib_a:b' is not a usable name",
    }
