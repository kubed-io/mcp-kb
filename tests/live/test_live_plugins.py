"""PLG-16..26, LIB-13: plugin.json parity, live."""

from __future__ import annotations

import pytest

from tests.live.kb import health, prompts, read

pytestmark = pytest.mark.live

COMMANDS_NOTE = (
    'Default commands/ folder is ignored because the manifest sets "commands"'
)


async def test_a_manifest_skills_list_adds(kb_url):
    """PLG-20: a manifest `skills` list adds to the default skills folder."""
    assert health(kb_url)["plugins"]["skills-add@live"]["skills"] == 2
    base = await read(kb_url, "skill://live/added-base/SKILL.md", "live")
    extra = await read(kb_url, "skill://live/extra/added-extra/SKILL.md", "live")
    assert "name: added-base" in base
    assert "name: added-extra" in extra


async def test_a_path_without_dot_slash_is_served_and_noted(kb_url):
    """PLG-24, PLG-16, PLG-26: a bare path is served; a bad one is noted."""
    text = await read(kb_url, "skill://live/more/undotted-skill/SKILL.md", "live")
    assert "name: undotted-skill" in text
    notes = health(kb_url)["plugins"]["undotted@live"]["notes"]
    assert set(notes) == {
        "skills path 'more' does not start with ./",
        "skills path '../outside' leaves the plugin root",
    }


async def test_the_prompts_are_exactly_these(kb_url):
    """PLG-21, PLG-23, PLG-25: only declared commands and conventions are served."""
    assert set(await prompts(kb_url, "live")) == {
        "live_check",
        "live_db_migrate",
        "live_deploy",
        "live_greet",
        "live_kept",
        "live_listed",
        "live_ops_restart",
        "live_use",
    }


async def test_a_commands_map_names_and_describes(kb_url):
    """PLG-21: a commands map names the prompt and its description wins."""
    served = await prompts(kb_url, "live")
    assert served["live_deploy"] == "Deploy the service."
    assert served["live_greet"] == "Greet someone."
    notes = health(kb_url)["plugins"]["commands-map@live"]["notes"]
    assert set(notes) == {
        COMMANDS_NOTE,
        "commands entry 'both' needs exactly one of source and content",
    }


async def test_a_key_naming_its_folder_earns_no_note(kb_url):
    """PLG-23: listing `./commands/` is no override; a path form is one."""
    plugins = health(kb_url)["plugins"]
    assert "notes" not in plugins["commands-list@live"]
    assert plugins["commands-path@live"]["notes"] == [COMMANDS_NOTE]


async def test_version_precedence_as_kb_specifies(kb_url):
    """PLG-17, LIB-13: the entry's version wins; else the manifest's.

    This is kb's rule. Whether Claude Code agrees is one of #35's follow-ups.
    """
    plugins = health(kb_url)["plugins"]
    assert plugins["versioned@live"]["version"] == "2.0.0"
    assert plugins["manifest-versioned@live"]["version"] == "1.5.0"
