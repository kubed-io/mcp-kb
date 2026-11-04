"""A plugin read the way Claude Code reads it: config, manifest and entry merged.

One ``plugin.json`` has to mean the same here as in Claude Code for the kinds
this server serves (PLG-20 to PLG-27, LIB-30 to LIB-33). Each test builds a
small tree on disk, serves it through a real ``KnowledgeBase`` and reads the
answer back out of what it serves and its ``status``, which is ``/health``.
"""

import json
import logging
from pathlib import Path

import pytest

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.catalogue.snapshot import effective_globs
from kubed.mcp_kb.config import Config
from tests.conftest import DEEP_YAML

pytestmark = pytest.mark.unit

IGNORED = 'Default {0}/ folder is ignored because the manifest sets "{0}"'
COMMANDS_NOTE = IGNORED.format("commands")
AGENTS_NOTE = IGNORED.format("agents")

# grafana/skills' shape: seven entries on the repository root, each naming its
# own skills, and `skills/template` named by none of them.
GRAFANA_SKILLS = {
    "grafana-lgtm": [
        "./skills/grafana-lgtm/loki",
        "./skills/grafana-lgtm/tempo",
        "./skills/grafana-lgtm/mimir",
    ],
    "grafana-dashboards": ["./skills/grafana-dashboards/panels"],
    "grafana-alerting": ["./skills/grafana-alerting/rules"],
    "grafana-k6": ["./skills/grafana-k6/load"],
    "grafana-oncall": ["./skills/grafana-oncall/schedules"],
    "grafana-faro": ["./skills/grafana-faro/sessions"],
    "grafana-plugins": ["./skills/grafana-plugins/scaffold"],
}

PENPOT_COMMANDS = (
    "brief",
    "audit",
    "tokens",
    "handoff",
    "components",
    "layout",
    "export",
    "review",
)


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _skill(root: Path, rel: str) -> None:
    name = rel.rstrip("/").rsplit("/", 1)[-1]
    _write(root, f"{rel}/SKILL.md", f"---\nname: {name}\ndescription: {name}.\n---\n")


def _command(root: Path, rel: str) -> None:
    _write(root, rel, "---\ndescription: A command.\n---\nDo $ARGUMENTS.\n")


def _manifest(root: Path, **fields) -> None:
    _write(root, ".claude-plugin/plugin.json", json.dumps(fields))


def _catalog(root: Path, *entries: dict) -> None:
    _write(
        root,
        ".claude-plugin/marketplace.json",
        json.dumps({"name": "market", "plugins": list(entries)}),
    )


def grafana_root(tmp_path: Path) -> Path:
    root = tmp_path / "grafana"
    for skills in GRAFANA_SKILLS.values():
        for rel in skills:
            _skill(root, rel.removeprefix("./"))
    _skill(root, "skills/template")
    _catalog(
        root,
        *(
            {"name": name, "source": "./", "category": "grafana", "skills": skills}
            for name, skills in GRAFANA_SKILLS.items()
        ),
    )
    return root


def penpot_root(tmp_path: Path) -> Path:
    root = tmp_path / "penpot"
    for name in PENPOT_COMMANDS:
        _command(root, f"prompts/{name}.md")
    _write(root, "prompts/README.md", "# The prompts\n\nRead me.\n")
    _manifest(
        root,
        name="penpot",
        commands=[f"./prompts/{name}.md" for name in PENPOT_COMMANDS],
    )
    _catalog(root, {"name": "penpot", "source": "./", "category": "design"})
    return root


def object_map_root(tmp_path: Path) -> Path:
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _command(root, "cmds/brief.md")
    _command(root, "commands/two.md")
    _command(root, "prompts/three.md")
    _manifest(
        root,
        name="kit",
        commands={
            "brief": {
                "source": "./cmds/brief.md",
                "description": "Write a brief.",
                "argumentHint": "<topic>",
            },
            "about": {"content": "Say what this plugin does."},
            "bad": {"source": "./x.md", "content": "y"},
        },
    )
    return root


def _marketplace(tmp_path: Path, root: Path, name: str = "lib") -> KnowledgeBase:
    config = Config.model_validate(
        {"libraries": [{"name": name, "source": f"file://{root}"}]}
    )
    return KnowledgeBase(config, tmp_path / "cache")


def _config(root: Path, library: str, **fields) -> Config:
    return Config.model_validate(
        {
            "plugins": [{"name": "kit", "source": f"file://{root}", **fields}],
            "libraries": [{"name": library, "plugins": ["kit"]}],
        }
    )


def _declared(
    tmp_path: Path, root: Path, *, library: str = "kit", **fields
) -> KnowledgeBase:
    return KnowledgeBase(_config(root, library, **fields), tmp_path / "cache")


def _names(knowledge_base: KnowledgeBase) -> list[str]:
    return [prompt.name for prompt in knowledge_base.prompts]


def _prompt(knowledge_base: KnowledgeBase, name: str):
    return next(p for p in knowledge_base.prompts if p.name == name)


def _served(knowledge_base: KnowledgeBase) -> set[str]:
    return {skill.name for skill in knowledge_base.index.visible()}


def test_a_manifest_skills_list_adds_to_the_conventions(tmp_path):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _skill(root, "extra/b")
    _manifest(root, name="kit", skills=["./extra"])

    assert _served(_declared(tmp_path, root)) == {"a", "b"}


@pytest.mark.parametrize("where", ["./", "."])
def test_a_root_skills_path_in_a_manifest_is_the_plugin_root(tmp_path, where):
    root = tmp_path / "kit"
    _skill(root, "a")
    _manifest(root, name="kit", skills=[where])

    knowledge_base = _declared(tmp_path, root)

    assert knowledge_base.status["plugins"]["kit"]["status"] == "ok"
    assert _served(knowledge_base) == {"a"}


def test_a_root_skills_path_in_a_root_entry_is_the_plugin_root(tmp_path):
    root = tmp_path / "market"
    _skill(root, "a")
    _catalog(root, {"name": "kit", "source": "./", "skills": ["./"]})

    knowledge_base = _marketplace(tmp_path, root)

    assert knowledge_base.status["plugins"]["kit@lib"]["status"] == "ok"
    assert _served(knowledge_base) == {"a"}


def test_seven_root_entries_each_serve_their_own_skills(tmp_path):
    knowledge_base = _marketplace(tmp_path, grafana_root(tmp_path), "grafana")

    plugins = knowledge_base.status["plugins"]
    assert {pid: p["status"] for pid, p in plugins.items()} == {
        f"{name}@grafana": "ok" for name in GRAFANA_SKILLS
    }
    assert "conflicts" not in knowledge_base.status["libraries"]["grafana"]
    for name, skills in GRAFANA_SKILLS.items():
        assert plugins[f"{name}@grafana"]["skills"] == len(skills), name
    assert "template" not in _served(knowledge_base)


def test_commands_replace_the_conventions_and_note_the_folder(tmp_path):
    root = tmp_path / "kit"
    _command(root, "cmds/one.md")
    _command(root, "commands/two.md")
    _command(root, "prompts/three.md")
    _manifest(root, name="kit", commands=["./cmds/one.md"])

    knowledge_base = _declared(tmp_path, root)

    assert [p.name for p in knowledge_base.prompts] == ["kit_one"]
    assert knowledge_base.status["plugins"]["kit"]["notes"] == [COMMANDS_NOTE]


def test_no_note_when_the_replaced_folder_is_not_there(tmp_path):
    root = tmp_path / "kit"
    _command(root, "cmds/one.md")
    _manifest(root, name="kit", commands=["./cmds/one.md"])

    knowledge_base = _declared(tmp_path, root)

    assert "notes" not in knowledge_base.status["plugins"]["kit"]


def test_commands_in_subfolders_carry_their_folders(tmp_path):
    root = tmp_path / "kit"
    _command(root, "commands/db/migrate.md")
    _command(root, "commands/top.md")

    knowledge_base = _declared(tmp_path, root, library="lib")

    assert sorted(_names(knowledge_base)) == ["lib_db_migrate", "lib_top"]
    assert {p.dialect for p in knowledge_base.prompts} == {"claude"}


def test_a_declared_commands_directory_reads_its_subfolders(tmp_path):
    root = tmp_path / "kit"
    _command(root, "cmds/a/b.md")
    _manifest(root, name="kit", commands="./cmds")

    knowledge_base = _declared(tmp_path, root, library="lib")

    assert _names(knowledge_base) == ["lib_a_b"]


def test_the_prompts_convention_still_names_by_stem(tmp_path):
    root = tmp_path / "kit"
    _command(root, "prompts/sub/debug.md")
    _command(root, "prompts/debug.md")

    knowledge_base = _declared(tmp_path, root, library="lib")

    assert _names(knowledge_base) == ["lib_debug"]
    assert _prompt(knowledge_base, "lib_debug").path.name == "debug.md"
    assert knowledge_base.status["plugins"]["kit"]["skipped"] == [
        {
            "path": "prompts/sub/debug.md",
            "reason": "prompt debug is already served by prompts/debug.md",
        }
    ]


def test_a_name_clash_is_on_the_name_not_the_stem(tmp_path):
    root = tmp_path / "kit"
    _command(root, "commands/a/x.md")
    _command(root, "commands/b/x.md")

    knowledge_base = _declared(tmp_path, root, library="lib")

    assert sorted(_names(knowledge_base)) == ["lib_a_x", "lib_b_x"]
    assert "skipped" not in knowledge_base.status["plugins"]["kit"]


def test_penpot_still_serves_its_eight_commands(tmp_path):
    knowledge_base = _marketplace(tmp_path, penpot_root(tmp_path), "penpot")

    assert knowledge_base.status["libraries"]["penpot"]["prompts"] == 8
    assert not any(p.path.name == "README.md" for p in knowledge_base.prompts)
    assert {p.dialect for p in knowledge_base.prompts} == {"claude"}


def test_an_entry_appends_to_its_manifest(tmp_path):
    root = tmp_path / "market"
    _skill(root, "plug/a")
    _skill(root, "plug/b")
    _skill(root, "plug/skills/c")
    _manifest(root / "plug", name="plug", skills=["./a"])
    _catalog(root, {"name": "plug", "source": "./plug", "skills": ["./b"]})

    assert _served(_marketplace(tmp_path, root)) == {"a", "b", "c"}


@pytest.mark.parametrize("key", ["hooks", "outputStyles"])
def test_strict_false_beside_a_manifest_that_names_components_fails(tmp_path, key):
    root = tmp_path / "market"
    _skill(root, "plug/skills/c")
    _manifest(root / "plug", name="plug")
    _catalog(
        root, {"name": "plug", "source": "./plug", "strict": False, key: "./x.json"}
    )

    status = _marketplace(tmp_path, root).status["plugins"]["plug@lib"]

    assert status["status"] == "failed"
    assert status["error"] == "conflicting manifests"


def test_strict_false_naming_no_component_is_ordinary(tmp_path):
    root = tmp_path / "market"
    _skill(root, "plug/skills/c")
    _manifest(root / "plug", name="plug")
    _catalog(root, {"name": "plug", "source": "./plug", "strict": False})

    knowledge_base = _marketplace(tmp_path, root)

    assert knowledge_base.status["plugins"]["plug@lib"]["status"] == "ok"
    assert _served(knowledge_base) == {"c"}


def test_strict_false_without_a_manifest_is_the_manifest(tmp_path):
    root = tmp_path / "market"
    _skill(root, "plug/b")
    _skill(root, "plug/skills/c")
    _catalog(
        root, {"name": "plug", "source": "./plug", "strict": False, "skills": ["./b"]}
    )

    knowledge_base = _marketplace(tmp_path, root)

    assert knowledge_base.status["plugins"]["plug@lib"]["status"] == "ok"
    assert _served(knowledge_base) == {"b", "c"}


def test_a_declared_plugins_config_globs_still_win(tmp_path):
    root = tmp_path / "kit"
    _skill(root, "x/one")
    _skill(root, "y/two")
    _skill(root, "skills/three")
    _manifest(root, name="kit", skills=["./y"])

    assert _served(_declared(tmp_path, root, skills=["x/**/SKILL.md"])) == {"one"}


def test_claude_format(tmp_path):
    bare = tmp_path / "bare"
    _skill(bare, "skills/a")
    assert not _declared(tmp_path / "1", bare)._plugins[0].claude_format

    manifested = tmp_path / "manifested"
    _skill(manifested, "skills/a")
    _manifest(manifested, name="kit")
    assert _declared(tmp_path / "2", manifested)._plugins[0].claude_format

    market = tmp_path / "market"
    _skill(market, "plug/skills/a")
    _catalog(market, {"name": "plug", "source": "./plug"})
    assert _marketplace(tmp_path / "3", market)._plugins[0].claude_format


def test_servers_are_names_from_every_place(tmp_path):
    inline = tmp_path / "inline"
    _skill(inline, "skills/a")
    _write(inline, ".mcp.json", json.dumps({"mcpServers": {"b": {}, "a": {}}}))
    _manifest(inline, name="kit", mcpServers={"c": {}, "a": {}})
    assert _declared(tmp_path / "1", inline)._plugins[0].servers == ("a", "b", "c")

    filed = tmp_path / "filed"
    _skill(filed, "skills/a")
    _write(filed, ".mcp.json", json.dumps({"z": {"command": "x"}}))
    _write(filed, "servers.json", json.dumps({"mcpServers": {"y": {}}}))
    _manifest(filed, name="kit", mcpServers="./servers.json")
    assert _declared(tmp_path / "2", filed)._plugins[0].servers == ("y", "z")


def test_an_entrys_servers_do_not_apply_beside_a_manifest(tmp_path):
    """Claude Code: with a plugin.json, an entry's ``mcpServers`` don't apply."""
    root = tmp_path / "market"
    _skill(root, "plug/skills/a")
    _manifest(root / "plug", name="plug", mcpServers={"b": {}})
    _catalog(root, {"name": "plug", "source": "./plug", "mcpServers": {"a": {}}})

    assert _marketplace(tmp_path, root)._plugins[0].servers == ("b",)


def test_an_entrys_servers_count_without_a_manifest(tmp_path):
    root = tmp_path / "market"
    _skill(root, "plug/skills/a")
    _write(root, "plug/.mcp.json", json.dumps({"mcpServers": {"c": {}}}))
    _catalog(root, {"name": "plug", "source": "./plug", "mcpServers": {"a": {}}})

    assert _marketplace(tmp_path, root)._plugins[0].servers == ("a", "c")


def test_an_unparsable_mcp_json_is_a_note_and_nothing_else(tmp_path):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _write(root, ".mcp.json", "{not json")
    _manifest(root, name="kit", mcpServers={"c": {}})

    knowledge_base = _declared(tmp_path, root)
    status = knowledge_base.status["plugins"]["kit"]

    assert status["status"] == "ok"
    assert _served(knowledge_base) == {"a"}
    assert knowledge_base._plugins[0].servers == ("c",)
    assert len(status["notes"]) == 1
    assert ".mcp.json" in status["notes"][0]
    assert str(tmp_path) not in status["notes"][0]


def test_a_manifest_note_reaches_health_without_a_cache_path(tmp_path):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _manifest(root, name="kit", skills=["extra", "../away"])

    notes = _declared(tmp_path, root).status["plugins"]["kit"]["notes"]

    assert notes == [
        "skills path 'extra' does not start with ./",
        "skills path '../away' leaves the plugin root",
    ]


def test_a_note_is_logged_once(tmp_path, caplog):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _manifest(root, name="kit", skills=["extra"])

    with caplog.at_level(logging.WARNING, logger="kubed.mcp_kb.catalogue.snapshot"):
        knowledge_base = _declared(tmp_path, root)
        knowledge_base.refresh(force=True)

    messages = [record.getMessage() for record in caplog.records]
    said = [message for message in messages if "does not start" in message]
    assert said == ["plugin kit: skills path 'extra' does not start with ./"]


@pytest.mark.parametrize(
    "text", ["[" * 200000, '{"a": ' + "1" * 5000 + "}"], ids=["deep", "long-int"]
)
def test_an_mcp_json_too_deep_or_too_long_to_parse_is_a_note(tmp_path, text):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _write(root, ".mcp.json", text)

    knowledge_base = _declared(tmp_path, root)
    status = knowledge_base.status["plugins"]["kit"]

    assert status["status"] == "ok"
    assert _served(knowledge_base) == {"a"}
    assert status["notes"] == [".mcp.json is not a JSON object of MCP servers"]


def test_a_manifest_too_deep_to_parse_fails_the_plugin_and_quotes_nothing(
    tmp_path, monkeypatch
):
    _parser_out_of_stack(monkeypatch)
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _write(root, ".claude-plugin/plugin.json", "[" * 200000)

    knowledge_base = _declared(tmp_path, root)
    status = knowledge_base.status["plugins"]["kit"]

    assert status["status"] == "failed"
    assert status["error"] == ".claude-plugin/plugin.json is nested too deeply to read"
    assert _served(knowledge_base) == set()


def test_a_map_only_commands_replaces_the_conventions(tmp_path):
    """The map is all it serves: the conventions it replaces serve nothing."""
    root = object_map_root(tmp_path)

    knowledge_base = _declared(tmp_path, root)
    globs = effective_globs(knowledge_base._plugins[0], root)

    assert _names(knowledge_base) == ["kit_brief", "kit_about"]
    assert globs.prompts == ()
    assert [entry.name for entry in globs.command_map] == ["brief", "about"]
    brief = globs.command_map[0]
    assert (brief.source, brief.description, brief.argument_hint) == (
        "cmds/brief.md", "Write a brief.", "<topic>",
    )
    assert knowledge_base.status["plugins"]["kit"]["notes"] == [
        "commands entry 'bad' needs exactly one of source and content",
        COMMANDS_NOTE,
    ]


def test_an_object_map_plugin_loads(tmp_path):
    knowledge_base = _declared(tmp_path, object_map_root(tmp_path), library="lib")

    brief = _prompt(knowledge_base, "lib_brief")
    assert brief.description == "Write a brief."
    assert [(a.name, a.description) for a in brief.arguments] == [
        ("arguments", "<topic>")
    ]
    about = _prompt(knowledge_base, "lib_about")
    assert about.render() == "Say what this plugin does."
    assert {brief.dialect, about.dialect} == {"claude"}
    assert not about.live
    notes = knowledge_base.status["plugins"]["kit"]["notes"]
    assert any("'bad'" in note for note in notes)


def test_an_inline_prompt_clashing_with_a_file_is_skipped_at_its_manifest(tmp_path):
    root = tmp_path / "kit"
    _command(root, "cmds/about.md")
    _manifest(
        root,
        name="kit",
        commands={
            "about": {"content": "Inline."},
            "again": {"source": "./cmds/about.md"},
            "first": {"source": "./cmds/about.md"},
        },
    )
    _catalog(root, {"name": "kit", "source": "./", "commands": "./cmds"})

    knowledge_base = _marketplace(tmp_path, root)
    status = knowledge_base.status["plugins"]["kit@lib"]

    assert _names(knowledge_base) == ["lib_about", "lib_again", "lib_first"]
    assert _prompt(knowledge_base, "lib_about").path.name == "about.md"
    assert status["skipped"] == [
        {
            "path": ".claude-plugin/plugin.json",
            "reason": "prompt about is already served by cmds/about.md",
        }
    ]


def test_a_map_source_outside_the_plugin_is_skipped(tmp_path):
    root = tmp_path / "kit"
    _command(tmp_path / "away", "x.md")
    (root / "cmds").mkdir(parents=True)
    (root / "cmds" / "x.md").symlink_to(tmp_path / "away" / "x.md")
    _manifest(root, name="kit", commands={"x": {"source": "./cmds/x.md"}})

    knowledge_base = _declared(tmp_path, root)

    assert knowledge_base.prompts == ()
    assert knowledge_base.status["plugins"]["kit"]["skipped"] == [
        {"path": "cmds/x.md", "reason": "not a file in the plugin"}
    ]


def test_an_inline_prompt_survives_a_cold_start(tmp_path, monkeypatch):
    from kubed.mcp_kb import server

    root = object_map_root(tmp_path)
    config = _config(root, "lib")
    first = KnowledgeBase(config, tmp_path / "cache")
    body = _prompt(first, "lib_about").render()

    def must_not_run(*args, **kwargs):
        raise AssertionError("a cold start over a good index harvests nothing")

    monkeypatch.setattr(server, "build_plugin", must_not_run)
    del first
    second = KnowledgeBase(config, tmp_path / "cache")

    about = _prompt(second, "lib_about")
    assert about.render() == body == "Say what this plugin does."
    assert _prompt(second, "lib_brief").arguments[0].description == "<topic>"


def test_a_bare_declared_plugin_has_no_agents(tmp_path):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _write(root, "agents/helper.md", "---\nname: helper\n---\nHelp.\n")

    knowledge_base = _declared(tmp_path, root)

    assert effective_globs(knowledge_base._plugins[0], root).agents == ()


def test_a_manifest_agents_list_notes_the_folder(tmp_path):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _write(root, "agents/helper.md", "---\nname: helper\n---\nHelp.\n")
    _write(root, "more/other.md", "---\nname: other\n---\nOther.\n")
    _manifest(root, name="kit", agents=["./more/other.md"])

    knowledge_base = _declared(tmp_path, root)

    assert effective_globs(knowledge_base._plugins[0], root).agents == (
        "more/other.md",
    )
    assert knowledge_base.status["plugins"]["kit"]["notes"] == [AGENTS_NOTE]


def test_a_listed_agent_is_a_path_not_a_glob(tmp_path):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _write(root, "agents/[draft].md", "---\nname: draft\ndescription: D.\n---\nGo.\n")
    _write(root, "agents/d.md", "---\nname: d\ndescription: D.\n---\nGo.\n")
    _write(root, "agents/x.md", "---\nname: x\ndescription: X.\n---\nGo.\n")
    _manifest(root, name="kit", agents=["./agents/[draft].md", "./agents/*.md"])

    knowledge_base = _declared(tmp_path, root)

    cards = knowledge_base.catalogue.agent_cards()
    assert [card["name"] for card in cards] == ["kit_draft"]
    assert knowledge_base.status["plugins"]["kit"]["notes"] == [
        "agents entry 'agents/*.md' is not in the plugin"
    ]


def test_a_listed_agent_in_a_dot_folder_is_served_and_one_outside_is_not(tmp_path):
    outside = tmp_path / "elsewhere.md"
    outside.write_text("---\nname: out\ndescription: O.\n---\nGo.\n")
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _write(root, ".private/wip.md", "---\nname: wip\ndescription: W.\n---\nGo.\n")
    (root / "agents").mkdir()
    (root / "agents/out.md").symlink_to(outside)
    _manifest(root, name="kit", agents=["./.private/wip.md", "./agents/out.md"])

    knowledge_base = _declared(tmp_path, root)

    cards = knowledge_base.catalogue.agent_cards()
    assert [card["name"] for card in cards] == ["kit_wip"]
    assert knowledge_base.status["plugins"]["kit"]["notes"] == [
        "agents entry 'agents/out.md' is not in the plugin"
    ]


LISTED_COMMANDS = [
    "./cmds/[draft].md",
    "./stars/*.md",
    "./.private/secret.md",
    "./more",
    "./v[1]",
]


def listed_commands_root(root: Path) -> Path:
    """The tree Dr K checked Claude Code 2.1.317 against, for #56."""
    for rel in (
        "cmds/[draft].md",
        "cmds/d.md",
        "stars/a.md",
        ".private/secret.md",
        "more/m.md",
        "more/.h/hid.md",
        "v[1]/go.md",
        "v1/no.md",
    ):
        _command(root, rel)
    _skill(root, "skills/s")
    return root


def test_a_listed_command_is_a_path_not_a_glob(tmp_path):
    root = listed_commands_root(tmp_path / "kit")
    _manifest(root, name="kit", commands=LISTED_COMMANDS)

    knowledge_base = _declared(tmp_path, root)

    assert sorted(_names(knowledge_base)) == [
        "kit_[draft]",
        "kit_go",
        "kit_m",
        "kit_secret",
    ]
    assert {p.dialect for p in knowledge_base.prompts} == {"claude"}
    assert knowledge_base.status["plugins"]["kit"]["notes"] == [
        "commands entry 'stars/*.md' is not in the plugin"
    ]


def test_an_entrys_listed_command_is_a_path_not_a_glob(tmp_path):
    root = listed_commands_root(tmp_path / "market")
    _catalog(root, {"name": "kit", "source": "./", "commands": LISTED_COMMANDS})

    knowledge_base = _marketplace(tmp_path, root)

    assert sorted(_names(knowledge_base)) == [
        "lib_[draft]",
        "lib_go",
        "lib_m",
        "lib_secret",
    ]
    assert {p.dialect for p in knowledge_base.prompts} == {"claude"}
    assert knowledge_base.status["plugins"]["kit@lib"]["notes"] == [
        "commands entry 'stars/*.md' is not in the plugin"
    ]


def test_a_config_prompts_glob_is_still_a_glob(tmp_path):
    root = listed_commands_root(tmp_path / "kit")
    _manifest(root, name="kit", commands=LISTED_COMMANDS)

    knowledge_base = _declared(tmp_path, root, prompts=["cmds/*.md"])

    assert sorted(_names(knowledge_base)) == ["kit_[draft]", "kit_d"]


def test_a_listed_command_python_refuses_as_a_glob_is_served(tmp_path, monkeypatch):
    _glob_as_on_3_11(monkeypatch)
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _command(root, "cmds/a**b.md")
    _manifest(root, name="kit", commands=["./cmds/a**b.md"])

    knowledge_base = _declared(tmp_path, root)

    assert _names(knowledge_base) == ["kit_a**b"]
    assert "notes" not in knowledge_base.status["plugins"]["kit"]


def test_a_listed_command_outside_the_plugin_or_a_folder_is_noted(tmp_path):
    outside = tmp_path / "elsewhere.md"
    outside.write_text("---\ndescription: Out.\n---\nGo.\n")
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    (root / "out.md").symlink_to(outside)
    (root / "dir.md").mkdir()
    _manifest(root, name="kit", commands=["./out.md", "./dir.md"])

    knowledge_base = _declared(tmp_path, root)

    assert _names(knowledge_base) == []
    assert knowledge_base.status["plugins"]["kit"]["notes"] == [
        "commands entry 'out.md' is not in the plugin",
        "commands entry 'dir.md' is not in the plugin",
    ]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("agents", ["./agents/helper.md"]),
        ("agents", ["./more/other.md", "./agents/helper.md"]),
        ("commands", ["./commands/deploy.md"]),
        ("commands", "./commands/"),
        ("commands", "./"),
        ("commands", {"ship": {"source": "./commands/deploy.md"}}),
    ],
)
def test_a_key_naming_its_default_folder_earns_no_note(tmp_path, key, value):
    # Claude Code: a path inside the folder "names a file in the default
    # folder and produces no warning", and "./commands/" keeps the folder.
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _command(root, "commands/deploy.md")
    _write(root, "agents/helper.md", "---\nname: helper\n---\nHelp.\n")
    _write(root, "more/other.md", "---\nname: other\n---\nOther.\n")
    _manifest(root, name="kit", **{key: value})

    knowledge_base = _declared(tmp_path, root)

    assert "notes" not in knowledge_base.status["plugins"]["kit"]


# -- fetched content that must not take the server down -------------------------


def _glob_as_on_3_11(monkeypatch) -> None:
    """``Path.glob`` as Python 3.11 and 3.12 have it: a partial ``**`` raises."""
    real = Path.glob

    def glob(self, pattern, *args, **kwargs):
        if any("**" in part and part != "**" for part in str(pattern).split("/")):
            raise ValueError("Invalid pattern: '**' can only be an entire component")
        return real(self, pattern, *args, **kwargs)

    monkeypatch.setattr(Path, "glob", glob)


def _parser_out_of_stack(monkeypatch) -> None:
    """``json.loads`` as a runner with a small stack has it: deep nesting raises.

    Since 3.14 how deep the parser goes depends on the thread's stack size, not
    on the recursion limit, so the same input raises on one runner and parses
    to the end on another. Every other text still goes to the real parser.
    """
    real = json.loads

    def loads(text, *args, **kwargs):
        if isinstance(text, str) and text.startswith("[" * 1000):
            raise RecursionError("maximum recursion depth exceeded")
        return real(text, *args, **kwargs)

    monkeypatch.setattr(json, "loads", loads)


@pytest.mark.parametrize(
    ("key", "paths"),
    [
        ("agents", ["./x**.md", "./agents/good.md"]),
        ("commands", ["./x**.md", "./cmds/ok.md"]),
        ("skills", ["./x**", "./extra"]),
    ],
)
def test_a_component_glob_python_refuses_matches_nothing(
    tmp_path, monkeypatch, key, paths
):
    _glob_as_on_3_11(monkeypatch)
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _skill(root, "extra/b")
    _command(root, "cmds/ok.md")
    _write(root, "agents/good.md", "---\nname: good\ndescription: Good.\n---\nGo.\n")
    _manifest(root, name="kit", **{key: paths})

    knowledge_base = _declared(tmp_path, root)

    assert knowledge_base.status["plugins"]["kit"]["status"] == "ok"
    assert "a" in _served(knowledge_base)
    if key == "agents":
        cards = knowledge_base.catalogue.agent_cards()
        assert [card["name"] for card in cards] == ["kit_good"]
    if key == "commands":
        assert _names(knowledge_base) == ["kit_ok"]
    if key == "skills":
        assert _served(knowledge_base) == {"a", "b"}


def test_a_marketplace_too_deep_to_parse_fails_the_library_and_quotes_nothing(
    tmp_path, monkeypatch
):
    _parser_out_of_stack(monkeypatch)
    root = tmp_path / "market"
    _write(root, ".claude-plugin/marketplace.json", "[" * 100000)

    knowledge_base = _marketplace(tmp_path, root)

    library = knowledge_base.status["libraries"]["lib"]
    assert library["error"] == "marketplace.json is nested too deeply to read"
    assert knowledge_base._plugins == []


NOT_TEXT_KEY = "---\n1: x\ntrue: y\ndescription: d\n---\nBody $ARGUMENTS\n"
KEY_REASON = "frontmatter has a key that is not a string"


def test_a_prompt_file_with_a_key_that_is_not_text_is_skipped(tmp_path):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _write(root, "prompts/bad.md", NOT_TEXT_KEY)
    _command(root, "prompts/ok.md")

    knowledge_base = _declared(tmp_path, root)
    status = knowledge_base.status["plugins"]["kit"]

    assert status["status"] == "ok"
    assert _names(knowledge_base) == ["kit_ok"]
    assert status["skipped"] == [{"path": "prompts/bad.md", "reason": KEY_REASON}]


def test_a_command_file_with_a_key_that_is_not_text_is_skipped(tmp_path):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _write(root, "cmds/bad.md", NOT_TEXT_KEY)
    _command(root, "cmds/ok.md")
    _manifest(root, name="kit", commands=["./cmds/bad.md", "./cmds/ok.md"])

    knowledge_base = _declared(tmp_path, root)
    status = knowledge_base.status["plugins"]["kit"]

    assert status["status"] == "ok"
    assert _names(knowledge_base) == ["kit_ok"]
    assert status["skipped"] == [{"path": "cmds/bad.md", "reason": KEY_REASON}]


def test_inline_content_with_a_key_that_is_not_text_is_skipped(tmp_path):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _manifest(
        root,
        name="kit",
        commands={"bad": {"content": NOT_TEXT_KEY}, "ok": {"content": "Ok."}},
    )

    knowledge_base = _declared(tmp_path, root)
    status = knowledge_base.status["plugins"]["kit"]

    assert status["status"] == "ok"
    assert _names(knowledge_base) == ["kit_ok"]
    assert status["skipped"] == [
        {"path": ".claude-plugin/plugin.json", "reason": KEY_REASON}
    ]


def test_a_skill_with_a_key_that_is_not_text_is_read_as_no_frontmatter(tmp_path):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _write(root, "skills/odd/SKILL.md", "---\n1: x\nname: named\n---\nBody.\n")

    knowledge_base = _declared(tmp_path, root)

    assert knowledge_base.status["plugins"]["kit"]["status"] == "ok"
    # As a frontmatter block that does not parse: named by its folder.
    assert _served(knowledge_base) == {"a", "odd"}


DEEP = f"---\nname: named\ndescription: d\nx: {DEEP_YAML}\n---\nBody $ARGUMENTS\n"
DEEP_REASON = "frontmatter is nested too deeply to read"


def test_a_prompt_file_too_deep_to_parse_is_skipped_and_quotes_nothing(
    tmp_path, frontmatter_out_of_stack
):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _write(root, "prompts/bad.md", DEEP)
    _command(root, "prompts/ok.md")

    knowledge_base = _declared(tmp_path, root)
    status = knowledge_base.status["plugins"]["kit"]

    assert status["status"] == "ok"
    assert _names(knowledge_base) == ["kit_ok"]
    assert status["skipped"] == [{"path": "prompts/bad.md", "reason": DEEP_REASON}]


def test_inline_content_too_deep_to_parse_is_skipped(
    tmp_path, frontmatter_out_of_stack
):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _manifest(
        root,
        name="kit",
        commands={"bad": {"content": DEEP}, "ok": {"content": "Ok."}},
    )

    knowledge_base = _declared(tmp_path, root)
    status = knowledge_base.status["plugins"]["kit"]

    assert status["status"] == "ok"
    assert _names(knowledge_base) == ["kit_ok"]
    assert status["skipped"] == [
        {"path": ".claude-plugin/plugin.json", "reason": DEEP_REASON}
    ]


def test_a_prompt_gone_too_deep_under_a_good_index_does_not_stop_a_cold_start(
    tmp_path, frontmatter_out_of_stack
):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _command(root, "prompts/bad.md")
    _command(root, "prompts/ok.md")
    config = _config(root, "kit")
    first = KnowledgeBase(config, tmp_path / "cache")
    assert _names(first) == ["kit_bad", "kit_ok"]
    del first
    # The index still lists it; the cold start parses every prompt again.
    _write(root, "prompts/bad.md", DEEP)

    second = KnowledgeBase(config, tmp_path / "cache")

    assert _names(second) == ["kit_ok"]


def test_a_skill_too_deep_to_parse_is_read_as_no_frontmatter(
    tmp_path, frontmatter_out_of_stack
):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _write(root, "skills/odd/SKILL.md", DEEP)

    knowledge_base = _declared(tmp_path, root)

    assert knowledge_base.status["plugins"]["kit"]["status"] == "ok"
    # As a frontmatter block that does not parse: named by its folder.
    assert _served(knowledge_base) == {"a", "odd"}


@pytest.mark.parametrize(
    "key", ["", "a\nb", "x/y", "sp ace", "tab\there", "a\x07b", "../../etc", "d@x"]
)
def test_a_commands_map_key_that_is_not_a_name_is_dropped(tmp_path, key):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _manifest(
        root,
        name="kit",
        commands={key: {"content": "Bad."}, "ok": {"content": "Ok."}},
    )

    knowledge_base = _declared(tmp_path, root)
    status = knowledge_base.status["plugins"]["kit"]

    assert status["status"] == "ok"
    assert _names(knowledge_base) == ["kit_ok"]
    assert status["notes"] == [f"commands entry {key!r} is not a usable name"]
    assert "skipped" not in status
