"""kb's prompts, served by kubed-mcp's plugin layer through kb's command reader (K4).

kb still decides which files are prompts, what each is called and what dialect
it is read in; the plugin layer reads the files, claims the names and serves
them, scoped by kb's view. These are the cases the switch could get wrong: a
selection narrower than the folder the layer reads, an entry the layer would
refuse, two files of one name, a refused plugin, and the render's order.
"""

from __future__ import annotations

import json
import logging

import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from kubed.mcp.protocol import MCPError

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.config import Config
from tests.conftest import http_client, serve_http, server_of
from tests.test_plugin_serving import _write, market

pytestmark = pytest.mark.unit

CMD = "---\ndescription: D.\n---\nBody.\n"
SKILL = "---\nname: s\ndescription: S.\n---\nS.\n"
PLUGINS = "kubed.mcp.plugins"


def _declared(tmp_path, plugins: dict[str, dict], libraries: dict[str, list[str]]):
    """A config of declared plugins over ``tmp_path/<name>``, and its libraries."""
    rows = []
    for name, spec in plugins.items():
        root = tmp_path / name
        _write(root, spec.pop("files"))
        rows.append({"name": name, "source": f"file://{root}", **spec})
    return Config.model_validate(
        {
            "plugins": rows,
            "libraries": [{"name": n, "plugins": p} for n, p in libraries.items()],
        }
    )


async def _names(kb: KnowledgeBase) -> list[str]:
    async with Client(server_of(kb)) as client:
        return sorted(p.name for p in await client.list_prompts())


async def test_every_name_is_plg25s(tmp_path):
    kb = KnowledgeBase(
        market(
            tmp_path,
            [{"name": "lib", "source": "./"}],
            {
                "skills/s/SKILL.md": SKILL,
                "commands/db/migrate.md": CMD,
                "commands/top.md": CMD,
                "prompts/sub/debug.md": CMD,
                ".github/prompts/x.prompt.md": CMD,
            },
        ),
        tmp_path / "cache",
    )
    async with Client(server_of(kb)) as client:
        names = sorted(p.name for p in await client.list_prompts())
    assert names == ["lib_db_migrate", "lib_debug", "lib_top", "lib_x"]
    assert names == sorted(p.name for p in kb.prompts)
    assert kb.status["libraries"]["lib"]["prompts"] == 4


async def test_a_partial_glob_in_commands_serves_only_what_it_selects(tmp_path):
    config = _declared(
        tmp_path,
        {
            "p": {
                "prompts": ["commands/*.md"],
                "files": {"commands/a.md": CMD, "commands/db/x.md": CMD},
            }
        },
        {"lib": ["p"]},
    )
    kb = KnowledgeBase(config, tmp_path / "cache")
    names = await _names(kb)
    assert names == ["lib_a"]
    assert not [
        r
        for r in kb.status["plugins"]["p"].get("skipped", ())
        if r["path"] == "commands/db/x.md"
    ]
    assert kb.status["plugins"]["p"]["prompts"] == 1


async def test_conventions_serve_beside_a_strict_false_entry(tmp_path):
    kb = KnowledgeBase(
        market(
            tmp_path,
            [{"name": "kit", "source": "./", "strict": False}],
            {
                ".claude-plugin/plugin.json": json.dumps({"name": "kit"}),
                "prompts/x.md": CMD,
                ".github/prompts/y.prompt.md": CMD,
            },
        ),
        tmp_path / "cache",
    )
    names = await _names(kb)
    assert names == ["lib_x", "lib_y"]
    assert "conflicts" not in kb.status["libraries"]["lib"]


async def test_a_declared_prompts_list_beats_the_manifests_commands(tmp_path):
    config = _declared(
        tmp_path,
        {
            "p": {
                "prompts": ["mine/*.md"],
                "files": {
                    ".claude-plugin/plugin.json": json.dumps(
                        {"name": "p", "commands": ["./commands/"]}
                    ),
                    "commands/two.md": CMD,
                    "mine/one.md": CMD,
                },
            }
        },
        {"lib": ["p"]},
    )
    kb = KnowledgeBase(config, tmp_path / "cache")
    names = await _names(kb)
    assert names == ["lib_one"]
    assert not [
        r
        for r in kb.status["plugins"]["p"].get("skipped", ())
        if r["path"] == "commands/two.md"
    ]


async def test_a_same_named_prompt_is_skipped_once(tmp_path):
    kb = KnowledgeBase(
        market(
            tmp_path,
            [{"name": "lib", "source": "./"}],
            {"commands/debug.md": CMD, "prompts/debug.md": CMD},
        ),
        tmp_path / "cache",
    )
    names = await _names(kb)
    assert names == ["lib_debug"]
    [pid] = kb.status["plugins"]
    rows = [
        r for r in kb.status["plugins"][pid]["skipped"] if r["path"] == "prompts/debug.md"
    ]
    assert rows == [
        {
            "path": "prompts/debug.md",
            "reason": "prompt lib_debug is already served by commands/debug.md",
        }
    ]
    assert [p.path.name for p in kb.prompts] == ["debug.md"]
    assert kb.prompts[0].path.parent.name == "commands"


async def test_a_broken_prompt_is_skipped_with_kbs_reason(tmp_path):
    kb = KnowledgeBase(
        market(
            tmp_path,
            [{"name": "lib", "source": "./"}],
            {"prompts/good.md": CMD, "prompts/bad.md": "Body only.\n"},
        ),
        tmp_path / "cache",
    )
    names = await _names(kb)
    assert names == ["lib_good"]
    [pid] = kb.status["plugins"]
    skipped = kb.status["plugins"][pid]["skipped"]
    assert {"path": "prompts/bad.md", "reason": "no YAML frontmatter"} in skipped
    assert str(tmp_path / "cache") not in json.dumps(kb.status)


async def test_a_later_plugin_with_a_claimed_name_conflicts(tmp_path):
    kb = KnowledgeBase(
        market(
            tmp_path,
            [{"name": "a", "source": "./a"}, {"name": "b", "source": "./b"}],
            {"a/prompts/x.md": CMD, "b/prompts/x.md": CMD},
        ),
        tmp_path / "cache",
    )
    names = await _names(kb)
    assert names == ["lib_x"]
    conflict = kb.status["libraries"]["lib"]["conflicts"]["b@lib"]
    assert conflict.startswith("conflict: prompt lib_x is already served by plugin")
    assert str(tmp_path / "cache") not in conflict
    assert [p.plugin for p in kb.prompts] == ["a@lib"]
    assert kb.status["libraries"]["lib"]["prompts"] == 1


async def test_out_of_scope_is_unknown(tmp_path):
    config = _declared(
        tmp_path,
        {
            "one": {"files": {"prompts/x.md": CMD}},
            "two": {"files": {"prompts/y.md": CMD}},
        },
        {"one": ["one"], "two": ["two"]},
    )
    kb = KnowledgeBase(config, tmp_path / "cache")

    async def miss(client, name):
        with pytest.raises(MCPError) as error:
            await client.get_prompt(name)
        return error.value.error.code, error.value.error.message.replace(name, "<n>")

    with serve_http(kb) as url:
        async with http_client(url, {"Kb-Library": "one"}) as client:
            listed = sorted(p.name for p in await client.list_prompts())
            rendered = await client.get_prompt("one_x")
            out_of_scope = await miss(client, "two_y")
            absent = await miss(client, "nobody_z")
        async with http_client(url) as client:
            everything = sorted(p.name for p in await client.list_prompts())
    assert listed == ["one_x"]
    assert rendered.messages[0].content.text == "Body.\n"
    assert everything == ["one_x", "two_y"]
    assert out_of_scope == absent
    assert "Unknown prompt" in absent[1]


async def test_names_and_plugin_root_render_at_build_and_arguments_as_typed(tmp_path):
    kb = KnowledgeBase(
        market(
            tmp_path,
            [{"name": "lib", "source": "./"}],
            {
                "skills/s/SKILL.md": SKILL,
                "shared/x.md": "x\n",
                "commands/cite.md": (
                    "---\ndescription: D.\n---\n"
                    "Read ${CLAUDE_PLUGIN_ROOT}/shared/x.md, use lib:s, say $ARGUMENTS\n"
                ),
            },
        ),
        tmp_path / "cache",
    )
    async with Client(server_of(kb)) as client:
        got = await client.get_prompt("lib_cite", {"arguments": "${CLAUDE_PLUGIN_ROOT}"})
    text = got.messages[0].content.text
    # P2: names and the plugin root at the build, the argument as typed.
    assert text == (
        "Read skill://lib/shared/x.md, use skill://lib/s/SKILL.md,"
        " say ${CLAUDE_PLUGIN_ROOT}\n"
    )


async def test_elicitation_survives_the_prefix(tmp_path):
    kb = KnowledgeBase(
        market(
            tmp_path,
            [{"name": "lib", "source": "./"}],
            {
                "skills/s/SKILL.md": SKILL,
                "prompts/ask.md": (
                    "---\n"
                    "description: Ask.\n"
                    "arguments:\n"
                    "- name: app\n"
                    "  description: The workload.\n"
                    "  required: true\n"
                    "---\n"
                    "Read ${CLAUDE_PLUGIN_ROOT}/shared/x.md for {{ app }}.\n"
                ),
            },
        ),
        tmp_path / "cache",
    )
    asked = []

    async def handler(message, response_type, params, context):
        asked.append(message)
        return {"app": "nextcloud"}

    with serve_http(kb) as url:
        transport = StreamableHttpTransport(url, headers={"Kb-Resource-Prefix": "kb+"})
        async with Client(transport, elicitation_handler=handler) as client:
            assert client.protocol_version == "2026-07-28"
            got = await client.get_prompt("lib_ask", {})
    text = got.messages[0].content.text
    assert asked == ["The lib_ask prompt needs app."]
    assert text == "Read kb+skill://lib/shared/x.md for nextcloud.\n"
    assert "kb+kb+" not in text


async def test_a_description_is_served_as_written(tmp_path):
    kb = KnowledgeBase(
        market(
            tmp_path,
            [{"name": "lib", "source": "./"}],
            {
                "skills/s/SKILL.md": SKILL,
                "prompts/see.md": "---\ndescription: See skill://lib/s/SKILL.md.\n---\nB\n",
            },
        ),
        tmp_path / "cache",
    )
    with serve_http(kb) as url:
        async with http_client(url, {"Kb-Resource-Prefix": "kb+"}) as client:
            [prompt] = await client.list_prompts()
    # D9: the gateway prefix is written into rendered text only.
    assert prompt.description == "See skill://lib/s/SKILL.md."


async def test_no_default_folder_note_for_the_conventions(tmp_path, caplog):
    kb = KnowledgeBase(
        market(
            tmp_path,
            [{"name": "lib", "source": "./"}],
            {"commands/a.md": CMD, "prompts/b.md": CMD},
        ),
        tmp_path / "cache",
    )
    with caplog.at_level(logging.WARNING, logger=PLUGINS):
        names = await _names(kb)
    assert names == ["lib_a", "lib_b"]
    assert "Default commands/ folder is ignored" not in caplog.text
    # Every entry kb writes starts with ./, so the layer notes none of them.
    assert "does not start with ./" not in caplog.text


async def test_a_file_kb_left_out_is_not_logged(tmp_path, caplog):
    config = _declared(
        tmp_path,
        {
            # commands/ is read for a.md, and b.md is kb's to leave out.
            "p": {
                "prompts": ["commands/a.md"],
                "files": {"commands/a.md": CMD, "commands/b.md": CMD},
            },
            # commands/ is not read at all: PLG-23's note still applies.
            "q": {
                "prompts": ["mine/*.md"],
                "files": {"commands/c.md": CMD, "mine/d.md": CMD},
            },
        },
        {"lib": ["p", "q"]},
    )
    kb = KnowledgeBase(config, tmp_path / "cache")
    with caplog.at_level(logging.WARNING, logger=PLUGINS):
        names = await _names(kb)
        # A second app in the process adds no second filter.
        server_of(KnowledgeBase(config, tmp_path / "cache2"))
    assert names == ["lib_a", "lib_d"]
    assert "is skipped" not in caplog.text
    assert "Default commands/ folder is ignored" in caplog.text
    from kubed.mcp_kb.mcp.skills import QuietSelection

    quiet = logging.getLogger(PLUGINS).filters
    assert sum(isinstance(f, QuietSelection) for f in quiet) == 1
    # Still in the layer's own record, and out of /health.
    assert not kb.status["plugins"]["p"].get("skipped")


def test_command_entries_follow_the_selection():
    from kubed.mcp_kb.catalogue.harvest import command_entries

    assert command_entries(
        [
            ".github/prompts/y.prompt.md",
            "commands/a.md",
            "commands/db/x.md",
            "prompts/b.md",
            "cmds/sub/c.md",
        ],
        ["cmds/sub"],
    ) == (".github/prompts/y.prompt.md", "commands", "prompts/b.md", "cmds/sub")
