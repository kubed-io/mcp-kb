"""AGT-5..9, AGT-17: agent names, definitions and qualified names, live."""

from __future__ import annotations

import pytest

from tests.live.kb import (
    META,
    agent_names,
    definition,
    health,
    owners,
    prompt_text,
    prompts,
    read,
)

pytestmark = pytest.mark.live

HOOKED = {
    "name": "hooked",
    "description": "Has deep frontmatter.",
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": "echo never-run"}],
            }
        ]
    },
    "metadata": {
        "owners": ["a", "b"],
        "limits": {"depth": 3, "nested": {"ok": True}},
    },
}


async def test_names_follow_library_order_and_folders(kb_url):
    """AGT-7, AGT-8, AGT-5: names are library-prefixed, in library order."""
    assert await agent_names(kb_url, "live") == [
        "live_filed",
        "live_finder",
        "live_hooked",
        "live_ops_oncall",
        "live_picked",
        "live_reviewer",
        "live_reviewer@late",
        "live_reviewer@second",
        "live_wired",
    ]


async def test_a_clash_is_renamed_and_its_rename_clash_unserved(kb_url):
    """AGT-8: a clash takes `@plugin`; a clash of that is unserved, with why."""
    clash = health(kb_url)["libraries"]["clash"]
    assert clash["renamed"] == {
        "clash_reviewer@second": (
            "clash_reviewer is already served by plugin 'first@live'"
        )
    }
    assert clash["unserved"] == [
        {
            "plugin": "second@live-other",
            "path": "agents/reviewer.md",
            "reason": "clash_reviewer@second is already served by plugin "
            "'second@live'",
        }
    ]
    assert clash["agents"] == 2
    assert await owners(kb_url, "clash") == {
        "reviewer": "first@live",
        "reviewer@second": "second@live",
    }


async def test_an_appended_plugin_renames_nothing(kb_url):
    """AGT-8: appending a plugin to a library renames no earlier agent.

    This compares two libraries, `clash` and `clash-appended`, which differ only
    by the appended `late@live`, and does not reindex. Against a deployment the
    fixtures are a git ref pinned to a commit, which cannot change in the middle
    of a run, so a reindex would show nothing new. A name comes from library order
    alone, so two libraries show it at once.
    """
    assert await owners(kb_url, "clash-appended") == {
        **await owners(kb_url, "clash"),
        "reviewer@late": "late@live",
    }


def test_a_listed_agent_list_replaces_the_scan(kb_url):
    """PLG-22, AGT-5, PLG-23, PLG-26: `agents:` replaces the scan; bad rows note."""
    report = health(kb_url)
    assert set(report["plugins"]["listed-agents@live"]["notes"]) == {
        "agents entry 'agents/notes.txt' is not a .md file",
        "agents entry 'agents/gone.md' is not in the plugin",
    }


async def test_deep_frontmatter_is_served_verbatim(kb_url):
    """AGT-6, AGT-9: nested frontmatter reaches the definition untouched."""
    got = await definition(kb_url, "live_hooked", "live")
    assert got["_meta"][META]["frontmatter"] == HOOKED


async def test_declared_servers_are_names(kb_url):
    """PLG-27, AGT-9: servers are names from plugin.json and .mcp.json."""
    wired = await definition(kb_url, "live_wired", "live")
    assert wired["_meta"][META]["servers"] == ["alpha", "beta"]
    filed = await definition(kb_url, "live_filed", "live")
    assert filed["_meta"][META]["servers"] == ["gamma"]


async def test_folders_name_prompts(kb_url):
    """PLG-25, PRM-42: folders below commands/ or prompts/ join a prompt's name."""
    assert {"live_db_migrate", "live_check"} <= set(await prompts(kb_url, "live"))


async def test_qualified_names_become_addresses(kb_url):
    """AGT-17, SKL-55, PRM-62: `<plugin>:<skill>` in served text is an address."""
    finder = await definition(kb_url, "live_finder", "live")
    assert finder["instructions"] == (
        "Load skill://live/lookup/SKILL.md first, then run /names:lookup-cmd.\n"
    )
    assert finder["_meta"][META]["skills"] == {
        "lookup": "skill://live/lookup/SKILL.md",
        "names:lookup": "skill://live/lookup/SKILL.md",
    }
    assert finder["_meta"][META]["frontmatter"]["skills"] == [
        "lookup",
        "names:lookup",
        "nowhere",
    ]
    skill = await read(kb_url, "skill://live/lookup/SKILL.md", "live")
    assert "Pairs with skill://live/helper/SKILL.md." in skill
    assert "Use skill://live/helper/SKILL.md." in await prompt_text(
        kb_url, "live_use", "live"
    )
