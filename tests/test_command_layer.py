"""kubed-mcp's own command layer, checked before kb builds on it (K4, Task 0).

No kb code here: a ``QuickMCP`` and one plugin folder, served through the plugin
layer's default command reader. These are the go/no-go for K4: that prompts are
named as PLG-25 names them, and that a served command adds no ``resources/list``
row. The server's own ``list_prompts`` and ``list_resources`` answer, so nothing
here imports FastMCP.
"""

from pathlib import Path

import pytest
from kubed.mcp import QuickMCP

_FILE = "---\ndescription: D.\n---\nBody.\n"
_COMMANDS = ["commands", "prompts/x.prompt.md", ".github/prompts/y.prompt.md"]


def _plugin(folder: Path) -> Path:
    """A plugin folder holding one command of each shape the layer reads."""
    for rel in (
        "commands/db/migrate.md",
        "commands/top.md",
        "prompts/x.prompt.md",
        ".github/prompts/y.prompt.md",
    ):
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_FILE)
    return folder


def _served(tmp_path: Path, namespace: str) -> QuickMCP:
    """A ``QuickMCP("mcp-kb")`` serving the plugin at ``namespace``."""
    folder = _plugin(tmp_path / namespace.replace("/", "-"))
    mcp = QuickMCP("mcp-kb")
    staging = mcp.plugin_set()
    staging.add(
        folder,
        namespace=namespace,
        manifest={"name": "p", "commands": _COMMANDS},
    )
    mcp.serve(staging)
    return mcp


async def _served_names(tmp_path: Path, namespace: str) -> list[str]:
    """The names ``prompts/list`` gives for the plugin at ``namespace``."""
    mcp = _served(tmp_path, namespace)
    return [prompt.name for prompt in await mcp.server.list_prompts()]


async def _listed_uris(tmp_path: Path, namespace: str) -> list[str]:
    """The URIs ``resources/list`` gives for the plugin at ``namespace``."""
    mcp = _served(tmp_path, namespace)
    return [str(resource.uri) for resource in await mcp.server.list_resources()]


async def test_the_layer_names_commands_as_plg25_does(tmp_path):
    for namespace in ("lib", "lib/sub"):
        names = await _served_names(tmp_path, namespace)
        assert sorted(names) == ["lib_db_migrate", "lib_top", "lib_x", "lib_y"]


async def test_a_namespace_named_like_the_server_has_no_prefix(tmp_path):
    assert "top" in await _served_names(tmp_path, "mcp-kb")  # why D8 refuses it


async def test_a_served_command_adds_no_listing_row(tmp_path):
    rows = await _listed_uris(tmp_path, "lib")
    assert not [uri for uri in rows if uri.startswith("prompts://")]


async def test_a_served_commands_prompts_address(tmp_path):
    """P6: what ``prompts://`` reads as under the pinned rc (observed, rc2).

    ``prompts://lib/commands/top.md`` is a miss: the layer's ``place`` is the file's
    path below its commands folder, so ``commands/`` is not in the address. The
    spelling ``_file_uri("prompts", "lib", ("top.md",))`` builds,
    ``prompts://lib/top.md``, reads, and gives the file's raw text, frontmatter
    included. It is never listed (see the listing test above).
    """
    mcp = _served(tmp_path, "lib")

    with pytest.raises(Exception) as miss:
        await mcp.server.read_resource("prompts://lib/commands/top.md")
    assert type(miss.value).__name__ == "NotFoundError"

    result = await mcp.server.read_resource("prompts://lib/top.md")
    assert [item.content for item in result.contents] == [_FILE]


def _write(folder: Path, *rels: str) -> Path:
    for rel in rels:
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_FILE)
    return folder


async def _text(mcp: QuickMCP, uri: str) -> str:
    """The first content's text at ``uri``."""
    return (await mcp.server.read_resource(uri)).contents[0].content


def _nested(tmp_path: Path, *, main: bool) -> QuickMCP:
    """``lib/sub`` serving ``commands/x.md``, and ``lib`` ``commands/top.md`` if ``main``."""
    mcp = QuickMCP("mcp-kb")
    staging = mcp.plugin_set()
    if main:
        staging.add(
            _write(tmp_path / "main", "commands/top.md"),
            namespace="lib",
            manifest={"name": "m", "commands": ["./commands"]},
        )
    staging.add(
        _write(tmp_path / "sub", "commands/x.md"),
        namespace="lib/sub",
        manifest={"name": "sub", "commands": ["./commands"]},
    )
    mcp.serve(staging)
    return mcp


async def test_the_namespace_folder_needs_a_prompt_of_its_own(tmp_path):
    """PLUG-68 under 0.3.0 (observed, #85 Task 0).

    ``prompts://lib`` is a folder only when the namespace ``lib`` itself serves a
    prompt; then each served ``lib/<plugin>`` is a row in it, as
    ``prompts://lib/sub: A folder of prompts in lib/sub``. With only ``lib/sub``
    serving, ``prompts://lib/_index.md`` is a miss like any absent address, and
    ``prompts://lib/sub/_index.md`` reads. So INS-19 falls back to each plugin
    folder (D2).
    """
    both = _nested(tmp_path / "a", main=True)
    index = await _text(both, "prompts://lib/_index.md")
    assert "prompts://lib/top.md: D." in index.splitlines()
    assert "prompts://lib/sub: A folder of prompts in lib/sub" in index.splitlines()
    assert (
        await _text(both, "prompts://lib/sub/_index.md")
        == "prompts://lib/sub/x.md: D.\n"
    )

    only = _nested(tmp_path / "b", main=False)
    with pytest.raises(Exception) as miss:
        await only.server.read_resource("prompts://lib/_index.md")
    assert type(miss.value).__name__ == "NotFoundError"
    assert (
        await _text(only, "prompts://lib/sub/_index.md")
        == "prompts://lib/sub/x.md: D.\n"
    )


@pytest.mark.parametrize(
    ("commands", "kept", "skipped", "first"),
    [
        (
            ["./commands", "./prompts/x.md"],
            "lib_prompts_x",
            "prompts/x.md",
            "commands/prompts/x.md",
        ),
        (
            ["./prompts/x.md", "./commands"],
            "lib_x",
            "commands/prompts/x.md",
            "prompts/x.md",
        ),
    ],
)
async def test_two_commands_at_one_place(tmp_path, commands, kept, skipped, first):
    """The ``prompts://`` place collision under 0.3.0 (observed, #85 Task 0; D4).

    ``commands/prompts/x.md`` (by the ``./commands`` entry) and ``prompts/x.md`` (by
    its own) are both ``prompts://lib/prompts/x.md``. The file the manifest lists
    first keeps the address and its prompt; the other is skipped whole, its prompt
    included, and the plugin's ``skipped`` says why. kb hands the layer its entries
    at their first file in path order (``harvest.command_entries``), so under kb the
    earlier path wins: ``commands/prompts/x.md``, ``lib_prompts_x``.
    """
    mcp = QuickMCP("mcp-kb")
    staging = mcp.plugin_set()
    staging.add(
        _write(tmp_path / "p", "commands/prompts/x.md", "prompts/x.md"),
        namespace="lib",
        manifest={"name": "p", "commands": commands},
    )
    mcp.serve(staging)

    assert [prompt.name for prompt in await mcp.server.list_prompts()] == [kept]
    index = await _text(mcp, "prompts://lib/prompts/_index.md")
    assert index == "prompts://lib/prompts/x.md: D.\n"
    (plugin,) = mcp.plugins
    assert dict(plugin.skipped) == {
        skipped: f"prompts://lib/prompts/x.md is already served by {first}"
    }
