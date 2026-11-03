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


def _declared(tmp_path: Path, root: Path, **fields) -> KnowledgeBase:
    config = Config.model_validate(
        {
            "plugins": [{"name": "kit", "source": f"file://{root}", **fields}],
            "libraries": [{"name": "kit", "plugins": ["kit"]}],
        }
    )
    return KnowledgeBase(config, tmp_path / "cache")


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


def test_a_subfolder_command_is_served_by_the_convention(tmp_path):
    root = tmp_path / "kit"
    _command(root, "commands/db/migrate.md")

    knowledge_base = _declared(tmp_path, root)

    assert [p.name for p in knowledge_base.prompts] == ["kit_migrate"]


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


def test_an_entrys_servers_join_the_manifests(tmp_path):
    root = tmp_path / "market"
    _skill(root, "plug/skills/a")
    _manifest(root / "plug", name="plug", mcpServers={"b": {}})
    _catalog(root, {"name": "plug", "source": "./plug", "mcpServers": {"a": {}}})

    assert _marketplace(tmp_path, root)._plugins[0].servers == ("a", "b")


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


def test_a_manifest_too_deep_to_parse_fails_the_plugin_and_quotes_nothing(tmp_path):
    root = tmp_path / "kit"
    _skill(root, "skills/a")
    _write(root, ".claude-plugin/plugin.json", "[" * 200000)

    knowledge_base = _declared(tmp_path, root)
    status = knowledge_base.status["plugins"]["kit"]

    assert status["status"] == "failed"
    assert status["error"] == ".claude-plugin/plugin.json is nested too deeply to read"
    assert _served(knowledge_base) == set()


def test_a_map_only_commands_replaces_the_conventions(tmp_path):
    """The map is carried for Task 4 to serve; until then it serves nothing,
    and the conventions it replaces serve nothing either."""
    root = object_map_root(tmp_path)

    knowledge_base = _declared(tmp_path, root)
    globs = effective_globs(knowledge_base._plugins[0], root)

    assert knowledge_base.prompts == ()
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
