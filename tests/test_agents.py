"""Subagent files: read for the agents extension, and harvested into the record.

``agents_tree`` is the shared fixture of the agents tasks -- the shape of
kubed-io/skills in the parts that matter -- and is imported by the tests that
serve it.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import pytest

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.catalogue.agents import (
    Agent,
    AgentRoster,
    ParsedAgent,
    parse_agent,
    routing_hint,
)
from kubed.mcp_kb.catalogue.skills import LibraryFiles, SkillIndex
from kubed.mcp_kb.catalogue.snapshot import build_snapshot
from kubed.mcp_kb.catalogue.uris import Catalogue
from kubed.mcp_kb.config import Config
from kubed.mcp_kb.mcp.scope import Scope

pytestmark = pytest.mark.unit

DIAGRAMMER = """\
---
name: diagrammer
description: Draws diagrams.
model: sonnet
color: cyan
---
Read ${CLAUDE_PLUGIN_ROOT}/skills/drawio/SKILL.md in ${CLAUDE_PROJECT_DIR}.
"""


def _agent(name: str | None, description: str | None = "Does a thing.", **more) -> str:
    fields = {"name": name, "description": description, **more}
    lines = [f"{k}: {v}" for k, v in fields.items() if v is not None]
    return "---\n" + "\n".join(lines) + "\n---\nBody.\n"


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@dataclass(frozen=True)
class AgentsTree:
    """The Part B tree: where it is, the config that serves it, a way to build it."""

    root: Path
    config: Config

    def knowledge_base(self, cache: Path) -> KnowledgeBase:
        return KnowledgeBase(self.config, cache)


def agents_tree(tmp_path: Path) -> AgentsTree:
    market = tmp_path / "market"
    _write(
        market,
        ".claude-plugin/marketplace.json",
        json.dumps(
            {
                "name": "kubed",
                "plugins": [
                    {
                        "name": "drawio",
                        "source": "./plugins/drawio",
                        "category": "diagrams",
                    },
                    {
                        "name": "extra",
                        "source": "./plugins/extra",
                        "category": "other",
                    },
                ],
            }
        ),
    )
    drawio = market / "plugins/drawio"
    _write(
        drawio,
        ".claude-plugin/plugin.json",
        json.dumps(
            {
                "name": "drawio",
                "keywords": ["drawio", "diagrams.net", "diagrams", "mxgraph", "mcp"],
            }
        ),
    )
    _write(drawio, "agents/diagrammer.md", DIAGRAMMER)
    _write(
        drawio,
        "skills/drawio/SKILL.md",
        "---\nname: drawio\ndescription: Draw.\n---\nDraw.\n",
    )
    _write(drawio, ".mcp.json", json.dumps({"mcpServers": {"drawio": {}}}))
    extra = market / "plugins/extra"
    _write(
        extra,
        ".claude-plugin/plugin.json",
        json.dumps({"name": "extra", "keywords": ["extra"]}),
    )
    _write(extra, "agents/diagrammer.md", _agent("diagrammer"))
    _write(extra, "agents/db/migrate.md", _agent("migrator"))
    _write(extra, "agents/broken.md", _agent("broken", None))
    _write(extra, "agents/twin-a.md", _agent("twin"))
    _write(extra, "agents/twin-b.md", _agent("twin"))
    lone = tmp_path / "lone"
    _write(
        lone,
        ".claude-plugin/plugin.json",
        json.dumps({"name": "lone", "keywords": ["lonely"]}),
    )
    _write(lone, "agents/solo.md", _agent("solo"))
    drive = tmp_path / "drive"
    _write(drive, "agents/x.md", _agent("x"))
    config = Config.model_validate(
        {
            "plugins": [
                {"name": "lone", "source": f"file://{lone}"},
                {"name": "drive", "source": f"file://{drive}"},
            ],
            "libraries": [
                {"name": "drawio", "source": f"file://{market}"},
                {"name": "lone", "plugins": ["lone"]},
                {"name": "drive", "plugins": ["drive"]},
            ],
        }
    )
    return AgentsTree(tmp_path, config)


def test_parse_agent_reads_the_diagrammer(tmp_path):
    _write(tmp_path, "d.md", DIAGRAMMER)

    parsed = parse_agent(tmp_path / "d.md")

    assert isinstance(parsed, ParsedAgent)
    assert parsed.name == "diagrammer"
    assert parsed.model == "sonnet"
    assert parsed.frontmatter["color"] == "cyan"
    assert parsed.body == (
        "Read ${CLAUDE_PLUGIN_ROOT}/skills/drawio/SKILL.md in ${CLAUDE_PROJECT_DIR}.\n"
    )


def test_a_description_has_its_whitespace_collapsed(tmp_path):
    _write(
        tmp_path, "d.md", "---\nname: a\ndescription: |\n  One\n  two   three\n---\n"
    )

    assert parse_agent(tmp_path / "d.md").description == "One two three"


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("---\nname: a\n---\nBody\n", "description"),
        ("---\ndescription: d\n---\nBody\n", "name"),
        ("---\nname: 3\ndescription: d\n---\nBody\n", "name"),
        ("---\nname: a\ndescription: ''\n---\nBody\n", "description"),
        ("---\nname: [unclosed\ndescription: d\n---\nBody\n", "parse"),
        ("---\n- a\n- b\n---\nBody\n", "mapping"),
        ("Just a body.\n", "mapping"),
        ("---\nname: a\ndescription: d\nscore: .nan\n---\nBody\n", "JSON"),
        ("---\nname: '  '\ndescription: d\n---\nBody\n", "name"),
        ("---\nname: a\ndescription: '  '\n---\nBody\n", "description"),
        ("---\n1: x\nname: a\ndescription: d\n---\nBody\n", "parse"),
    ],
)
def test_what_makes_an_agent_file_skipped(tmp_path, text, problem):
    _write(tmp_path, "a.md", text)

    reason = parse_agent(tmp_path / "a.md")

    assert isinstance(reason, str)
    assert problem in reason
    assert "unclosed" not in reason


@pytest.mark.parametrize(
    ("value", "kept"),
    [("[a, b]", ("a", "b")), ("a", ()), ("[1]", ())],
)
def test_capabilities_are_a_list_of_strings_or_nothing(tmp_path, value, kept):
    _write(tmp_path, "a.md", _agent("a", capabilities=value))

    assert parse_agent(tmp_path / "a.md").capabilities == kept


@pytest.mark.parametrize(
    ("model", "role"),
    [
        ("opus", "large"),
        ("sonnet", "medium"),
        ("haiku", "small"),
        ("claude-opus-5-5", "large"),
        ("claude-3-5-sonnet-20241022", "medium"),
        ("us.anthropic.claude-haiku-4-5-v1:0", "small"),
        ("Opus[1m]", "large"),
        ("sonnet-distilled-from-opus", "medium"),
        ("opus-then-sonnet", "large"),
    ],
)
def test_routing_hint_by_family(model, role):
    assert routing_hint(model) == {"role": role, "vision": False}


@pytest.mark.parametrize("model", [None, "inherit", "gpt-5", "opusx", ""])
def test_no_routing_hint(model):
    assert routing_hint(model) is None


def _record(tree: AgentsTree, tmp_path: Path, plugin: str):
    return tree.knowledge_base(tmp_path / "cache")._records[plugin]


def test_the_default_scan_adds_a_segment_per_folder(tmp_path):
    tree = agents_tree(tmp_path)
    knowledge_base = tree.knowledge_base(tmp_path / "cache")

    record = knowledge_base._records["extra@drawio"]

    assert [a.name for a in record.agents] == [
        "db_migrator",
        "diagrammer",
        "twin",
        "twin",
    ]
    assert [a.path for a in record.agents] == [
        "agents/db/migrate.md",
        "agents/diagrammer.md",
        "agents/twin-a.md",
        "agents/twin-b.md",
    ]
    assert record.agent_paths == ("agents",)
    skipped = knowledge_base.status["plugins"]["extra@drawio"]["skipped"]
    assert skipped == [
        {"path": "agents/broken.md", "reason": "agent frontmatter has no description"},
        {
            "path": "agents/twin-b.md",
            "reason": "agent twin is already served by agents/twin-a.md",
        },
    ]


def test_a_manifest_plugin_records_its_agent(tmp_path):
    record = _record(agents_tree(tmp_path), tmp_path, "lone")

    assert [a.name for a in record.agents] == ["solo"]


def test_a_listed_agent_has_no_folder_segment(tmp_path):
    root = tmp_path / "kit"
    _write(root, "agents/db/migrate.md", _agent("migrator"))
    _write(root, "agents/other.md", _agent("other"))
    _write(
        root,
        ".claude-plugin/plugin.json",
        json.dumps({"name": "kit", "agents": ["./agents/db/migrate.md"]}),
    )
    config = Config.model_validate(
        {
            "plugins": [{"name": "kit", "source": f"file://{root}"}],
            "libraries": [{"name": "kit", "plugins": ["kit"]}],
        }
    )

    record = KnowledgeBase(config, tmp_path / "cache")._records["kit"]

    assert [(a.path, a.name) for a in record.agents] == [
        ("agents/db/migrate.md", "migrator")
    ]
    assert record.agent_paths == ("agents", "agents/db/migrate.md")


def test_a_bare_plugin_has_no_agents(tmp_path):
    record = _record(agents_tree(tmp_path), tmp_path, "drive")

    assert record.agents == ()
    assert record.agent_paths == ()


def test_a_symlinked_agent_out_of_the_root_is_not_harvested(tmp_path):
    root = tmp_path / "kit"
    outside = tmp_path / "outside.md"
    outside.write_text(_agent("escaped"))
    _write(root, ".claude-plugin/plugin.json", json.dumps({"name": "kit"}))
    (root / "agents").mkdir()
    (root / "agents/link.md").symlink_to(outside)
    config = Config.model_validate(
        {
            "plugins": [{"name": "kit", "source": f"file://{root}"}],
            "libraries": [{"name": "kit", "plugins": ["kit"]}],
        }
    )

    record = KnowledgeBase(config, tmp_path / "cache")._records["kit"]

    assert record.agents == ()


def test_a_file_that_is_not_utf8_is_skipped_with_a_reason(tmp_path):
    (tmp_path / "a.md").write_bytes(b"---\nname: a\ndescription: \xff\xfe\n---\n")

    reason = parse_agent(tmp_path / "a.md")

    assert reason == "agent file is not UTF-8"


def test_the_body_is_exactly_the_text_after_the_frontmatter(tmp_path):
    _write(tmp_path, "a.md", "---\nname: a\ndescription: d\n---\n\n  indented\n")

    assert parse_agent(tmp_path / "a.md").body == "\n  indented\n"


def _kit(tmp_path: Path, manifest: dict | None = None) -> KnowledgeBase:
    root = tmp_path / "kit"
    _write(root, "agents/good.md", _agent("good"))
    _write(root, ".claude-plugin/plugin.json", json.dumps(manifest or {"name": "kit"}))
    config = Config.model_validate(
        {
            "plugins": [{"name": "kit", "source": f"file://{root}"}],
            "libraries": [{"name": "kit", "plugins": ["kit"]}],
        }
    )
    return KnowledgeBase(config, tmp_path / "cache")


def test_one_bad_agent_file_skips_itself_and_not_the_plugin(tmp_path):
    root = tmp_path / "kit"
    (root / "agents").mkdir(parents=True)
    (root / "agents/bytes.md").write_bytes(b"---\nname: \xff\n---\n")
    _write(root, "agents/keys.md", "---\n1: x\nname: k\ndescription: d\n---\n")

    knowledge_base = _kit(tmp_path)

    status = knowledge_base.status["plugins"]["kit"]
    assert status["status"] == "ok"
    assert {row["path"] for row in status["skipped"]} == {
        "agents/bytes.md",
        "agents/keys.md",
    }
    assert [a.name for a in knowledge_base._records["kit"].agents] == ["good"]


def test_an_unreadable_agent_file_is_skipped_without_its_error(tmp_path, monkeypatch):
    real = Path.read_text

    def read_text(self, *args, **kwargs):
        if self.name == "bad.md":
            raise OSError(13, "Permission denied", str(self))
        return real(self, *args, **kwargs)

    root = tmp_path / "kit"
    _write(root, "agents/bad.md", _agent("bad"))
    monkeypatch.setattr(Path, "read_text", read_text)

    knowledge_base = _kit(tmp_path)

    status = knowledge_base.status["plugins"]["kit"]
    assert status["status"] == "ok"
    assert status["skipped"] == [
        {"path": "agents/bad.md", "reason": "agent file is not readable"}
    ]
    assert [a.name for a in knowledge_base._records["kit"].agents] == ["good"]


def test_a_listed_agent_that_is_not_there_is_a_note(tmp_path):
    knowledge_base = _kit(
        tmp_path, {"name": "kit", "agents": ["./agents/good.md", "./agents/gone.md"]}
    )

    status = knowledge_base.status["plugins"]["kit"]
    assert status["status"] == "ok"
    assert "agents entry 'agents/gone.md' is not in the plugin" in status["notes"]
    assert [a.name for a in knowledge_base._records["kit"].agents] == ["good"]


# -- Task 7: names claimed per library, and the roster in the catalogue --------


def _entries(tree: AgentsTree, before=(), after=()) -> None:
    """``tree``'s marketplace with plugins put ahead of and after its own two.

    Each plugin is ``(name, {path: text})``, written below ``plugins/<name>``
    beside a manifest of its own, so every one of them is Claude-format.
    """
    market = tree.root / "market"
    catalog = json.loads((market / ".claude-plugin/marketplace.json").read_text())

    def entry(name: str, files: dict[str, str]) -> dict:
        root = market / "plugins" / name
        _write(root, ".claude-plugin/plugin.json", json.dumps({"name": name}))
        for rel, text in files.items():
            _write(root, rel, text)
        return {"name": name, "source": f"./plugins/{name}"}

    catalog["plugins"] = [
        *(entry(*p) for p in before),
        *catalog["plugins"],
        *(entry(*p) for p in after),
    ]
    _write(market, ".claude-plugin/marketplace.json", json.dumps(catalog))


def _names(knowledge_base: KnowledgeBase, library: str) -> list[str]:
    cards = knowledge_base.catalogue.agent_cards(Scope.parse(library=library))
    return [card["name"] for card in cards]


def _owners(knowledge_base: KnowledgeBase) -> dict[str, str]:
    """Each served agent's name in ``drawio``, mapped to its plugin."""
    catalogue = knowledge_base.catalogue
    return {
        name: catalogue.agent_definition(name)["_meta"]["io.kubed.mcp-kb/agent"][
            "plugin"
        ]
        for name in _names(knowledge_base, "drawio")
    }


def test_names_follow_claude_code(tmp_path):
    knowledge_base = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")

    assert _names(knowledge_base, "drawio") == [
        "drawio_db_migrator",
        "drawio_diagrammer",
        "drawio_diagrammer@extra",
        "drawio_twin",
    ]
    assert _names(knowledge_base, "lone") == ["lone_solo"]
    assert _names(knowledge_base, "drive") == []


def test_a_clash_is_renamed_and_reported(tmp_path):
    knowledge_base = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")

    status = knowledge_base.status["libraries"]
    assert status["drawio"]["renamed"] == {
        "drawio_diagrammer@extra": (
            "drawio_diagrammer is already served by plugin 'drawio@drawio'"
        )
    }
    assert "renamed" not in status["lone"]
    assert "unserved" not in status["drawio"]
    assert _owners(knowledge_base)["drawio_diagrammer@extra"] == "extra@drawio"


def _mix(tree: AgentsTree) -> Config:
    """Two plugins named ``extra``, from two marketplaces, in one library ``mix``.

    Both ship a ``diagrammer`` after drawio's, so the second one's rename is
    taken too: the only way to reach AGT-8's ``unserved``, since a frontmatter
    name cannot hold the ``@`` of a rename.
    """
    other = tree.root / "other"
    _write(
        other,
        ".claude-plugin/marketplace.json",
        json.dumps({"name": "other", "plugins": [{"name": "extra", "source": "./"}]}),
    )
    _write(other, ".claude-plugin/plugin.json", json.dumps({"name": "extra"}))
    _write(other, "agents/diagrammer.md", _agent("diagrammer"))
    return Config.model_validate(
        {
            "libraries": [
                {"name": "drawio", "source": f"file://{tree.root / 'market'}"},
                {"name": "other", "source": f"file://{other}"},
                {
                    "name": "mix",
                    "plugins": ["drawio@drawio", "extra@drawio", "extra@other"],
                },
            ]
        }
    )


def test_a_clash_on_the_renamed_name_is_unserved(tmp_path):
    knowledge_base = KnowledgeBase(_mix(agents_tree(tmp_path)), tmp_path / "cache")

    catalogue = knowledge_base.catalogue
    owners = {
        name: catalogue.agent_definition(name)["_meta"]["io.kubed.mcp-kb/agent"][
            "plugin"
        ]
        for name in _names(knowledge_base, "mix")
    }
    assert owners["mix_diagrammer"] == "drawio@drawio"
    assert owners["mix_diagrammer@extra"] == "extra@drawio"
    library = knowledge_base.status["libraries"]["mix"]
    assert library["unserved"] == [
        {
            "plugin": "extra@other",
            "path": "agents/diagrammer.md",
            "reason": "mix_diagrammer@extra is already served by plugin 'extra@drawio'",
        }
    ]
    assert library["agents"] == 4


def test_an_agent_named_like_a_rename_does_not_squat_it(tmp_path):
    tree = agents_tree(tmp_path)
    _entries(tree, before=[("sneak", {"agents/d.md": _agent("diagrammer@extra")})])
    # Ahead of extra, behind drawio: the marketplace keeps drawio first.
    market = tree.root / "market/.claude-plugin/marketplace.json"
    catalog = json.loads(market.read_text())
    catalog["plugins"] = [catalog["plugins"][i] for i in (1, 0, 2)]
    market.write_text(json.dumps(catalog))

    knowledge_base = tree.knowledge_base(tmp_path / "cache")

    owners = _owners(knowledge_base)
    assert owners["drawio_diagrammer"] == "drawio@drawio"
    assert owners["drawio_diagrammer@extra"] == "extra@drawio"
    assert "sneak@drawio" not in owners.values()
    assert "unserved" not in knowledge_base.status["libraries"]["drawio"]
    assert knowledge_base.status["plugins"]["sneak@drawio"]["skipped"] == [
        {"path": "agents/d.md", "reason": "agent frontmatter name is not a usable name"}
    ]


@pytest.mark.parametrize(
    "name", ["a\nb", "x/y", "sp ace", "tab\there", "a\x07b", "../../etc", "d@x"]
)
def test_an_agent_name_that_is_not_a_name_is_skipped(tmp_path, name):
    _write(tmp_path, "a.md", f"---\nname: {json.dumps(name)}\ndescription: d\n---\n")

    assert parse_agent(tmp_path / "a.md") == (
        "agent frontmatter name is not a usable name"
    )


def test_a_twin_in_one_plugin_is_skipped(tmp_path):
    knowledge_base = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")

    skipped = knowledge_base.status["plugins"]["extra@drawio"]["skipped"]
    assert {
        "path": "agents/twin-b.md",
        "reason": "agent twin is already served by agents/twin-a.md",
    } in skipped


def test_an_appended_plugin_renames_nothing(tmp_path):
    tree = agents_tree(tmp_path)
    before = _owners(tree.knowledge_base(tmp_path / "before"))
    _entries(tree, after=[("late", {"agents/d.md": _agent("diagrammer")})])

    after = _owners(tree.knowledge_base(tmp_path / "after"))

    assert after == {**before, "drawio_diagrammer@late": "late@drawio"}


def test_a_prepended_plugin_takes_the_short_name(tmp_path):
    tree = agents_tree(tmp_path)
    _entries(tree, before=[("first", {"agents/d.md": _agent("diagrammer")})])

    knowledge_base = tree.knowledge_base(tmp_path / "cache")

    owners = _owners(knowledge_base)
    assert owners["drawio_diagrammer"] == "first@drawio"
    assert owners["drawio_diagrammer@drawio"] == "drawio@drawio"
    assert owners["drawio_diagrammer@extra"] == "extra@drawio"
    assert knowledge_base.status["libraries"]["drawio"]["renamed"] == {
        "drawio_diagrammer@drawio": (
            "drawio_diagrammer is already served by plugin 'first@drawio'"
        ),
        "drawio_diagrammer@extra": (
            "drawio_diagrammer is already served by plugin 'first@drawio'"
        ),
    }


def test_a_conflicting_plugin_serves_no_agents(tmp_path):
    tree = agents_tree(tmp_path)
    skill = "---\nname: drawio\ndescription: Again.\n---\nAgain.\n"
    _entries(
        tree,
        after=[
            ("copy", {"skills/drawio/SKILL.md": skill, "agents/c.md": _agent("clone")})
        ],
    )

    knowledge_base = tree.knowledge_base(tmp_path / "cache")

    library = knowledge_base.status["libraries"]["drawio"]
    assert "copy@drawio" in library["conflicts"]
    assert "drawio_clone" not in _names(knowledge_base, "drawio")
    assert library["agents"] == 4
    assert knowledge_base.status["plugins"]["copy@drawio"]["agents"] == 1


def test_counts(tmp_path):
    knowledge_base = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")

    status = knowledge_base.status
    assert status["plugins"]["drawio@drawio"]["agents"] == 1
    assert status["plugins"]["extra@drawio"]["agents"] == 3
    assert status["plugins"]["lone"]["agents"] == 1
    assert status["plugins"]["drive"]["agents"] == 0
    assert status["libraries"]["drawio"]["agents"] == 4
    assert status["libraries"]["lone"]["agents"] == 1
    assert status["libraries"]["drive"]["agents"] == 0


def test_cards_and_definition_under_scope(tmp_path):
    catalogue = agents_tree(tmp_path).knowledge_base(tmp_path / "cache").catalogue

    assert catalogue.agent_cards(Scope.parse(tags="diagrams")) == [
        {
            "name": "drawio_diagrammer",
            "description": "Draws diagrams.",
            "capabilities": [],
        }
    ]
    other = catalogue.agent_cards(Scope.parse(categories="other"))
    assert [c["name"] for c in other] == [
        "drawio_db_migrator",
        "drawio_diagrammer@extra",
        "drawio_twin",
    ]
    extra = Scope.parse(tags="extra")
    assert catalogue.agent_definition("drawio_diagrammer", extra) is None
    assert catalogue.agent_definition("nobody") is None
    assert [c["name"] for c in catalogue.agent_cards()] == [
        "drawio_db_migrator",
        "drawio_diagrammer",
        "drawio_diagrammer@extra",
        "drawio_twin",
        "lone_solo",
    ]


def test_the_definition(tmp_path):
    catalogue = agents_tree(tmp_path).knowledge_base(tmp_path / "cache").catalogue

    definition = catalogue.agent_definition("drawio_diagrammer")

    assert definition == {
        "agent": "drawio_diagrammer",
        "instructions": (
            "Read skill://drawio/drawio/SKILL.md in ${CLAUDE_PROJECT_DIR}.\n"
        ),
        "modelRoutingHint": {"role": "medium", "vision": False},
        "tools": [],
        "_meta": {
            "io.kubed.mcp-kb/agent": {
                "plugin": "drawio@drawio",
                "library": "drawio",
                "path": "agents/diagrammer.md",
                "frontmatter": {
                    "name": "diagrammer",
                    "description": "Draws diagrams.",
                    "model": "sonnet",
                    "color": "cyan",
                },
                "servers": ["drawio"],
                "skills": {},
            }
        },
    }


def test_a_blank_body_and_no_model_leave_their_fields_out(tmp_path):
    root = tmp_path / "kit"
    _write(root, "agents/quiet.md", "---\nname: quiet\ndescription: d\n---\n\n  \n")
    _write(root, ".claude-plugin/plugin.json", json.dumps({"name": "kit"}))
    config = Config.model_validate(
        {
            "plugins": [{"name": "kit", "source": f"file://{root}"}],
            "libraries": [{"name": "kit", "plugins": ["kit"]}],
        }
    )

    catalogue = KnowledgeBase(config, tmp_path / "cache").catalogue

    definition = catalogue.agent_definition("kit_quiet")
    assert set(definition) == {"agent", "tools", "_meta"}
    assert definition["_meta"]["io.kubed.mcp-kb/agent"]["servers"] == []


def test_a_row_that_no_longer_parses_is_reported_and_keeps_its_claim(tmp_path):
    """A cold start serves the rows the index recorded; a file that broke since
    is reported under its plugin, and the names around it do not move."""
    knowledge_base = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")
    drawio = tmp_path / "market/plugins/drawio/agents/diagrammer.md"
    drawio.write_text("---\nname: diagrammer\n---\nNo description now.\n")

    snapshot = build_snapshot(
        knowledge_base.config,
        knowledge_base._plugins,
        knowledge_base._libraries,
        knowledge_base._fetches,
        knowledge_base._records,
        1,
    )

    plugin = snapshot.status["plugins"]["drawio@drawio"]
    assert plugin["agents"] == 0
    assert {
        "path": "agents/diagrammer.md",
        "reason": "agent frontmatter has no description",
    } in plugin["skipped"]
    names = [c["name"] for c in snapshot.catalogue.agent_cards()]
    assert "drawio_diagrammer" not in names
    assert "drawio_diagrammer@extra" in names
    assert snapshot.status["libraries"]["drawio"]["agents"] == 3
    assert str(tmp_path / "cache") not in json.dumps(snapshot.status)


def test_renames_and_unserved_agents_are_logged_once(tmp_path, caplog):
    config = _mix(agents_tree(tmp_path))

    with caplog.at_level(logging.INFO, logger="kubed.mcp_kb.catalogue.snapshot"):
        knowledge_base = KnowledgeBase(config, tmp_path / "cache")
        boot = caplog.text
        caplog.clear()
        knowledge_base.refresh(force=True)

    assert boot.count("mix_diagrammer@extra") == 2  # renamed once, unserved once
    assert "agents/diagrammer.md" in boot
    assert "mix_diagrammer@extra" not in caplog.text


def test_a_live_agent_is_reread(tmp_path, caplog):
    """An agent of a live fetch is revalidated, then parsed again (AGT-16).

    The stub stands in for the revalidator: what it writes is what a server
    that moved would have brought down.
    """
    root = tmp_path / "kit"
    _write(root, "agents/a.md", _agent("a"))
    path = root / "agents/a.md"
    upstream: list[str] = []
    asked: list[Path] = []

    def revalidate(target: Path) -> None:
        asked.append(target)
        if upstream:
            target.write_text(upstream.pop(0))

    def agent(name: str, live: bool) -> Agent:
        return Agent(
            name=name,
            library="kit",
            plugin="kit",
            root=root,
            path=path,
            parsed=parse_agent(path),
            servers=(),
            category=None,
            tags=frozenset(),
            live=live,
        )

    catalogue = Catalogue(
        SkillIndex([]),
        LibraryFiles(),
        revalidate,
        agents=AgentRoster([agent("kit_a", True), agent("kit_still", False)]),
    )

    upstream.append(_agent("a").replace("Body.", "The edited body."))
    assert catalogue.agent_definition("kit_a")["instructions"] == "The edited body.\n"
    assert asked == [path]

    upstream.append("---\nname: [unclosed\n---\nHalf saved.\n")
    with caplog.at_level(logging.WARNING, logger="kubed.mcp_kb.catalogue.uris"):
        definition = catalogue.agent_definition("kit_a")
    assert definition["instructions"] == "Body.\n"
    assert "kit_a" in caplog.text
    assert str(tmp_path) not in caplog.text

    asked.clear()
    catalogue.agent_cards()
    catalogue.agent_definition("kit_still")
    assert asked == []


def _read(tmp_path: Path, uri: str) -> str | None:
    tree = agents_tree(tmp_path)
    return tree.knowledge_base(tmp_path / "cache").catalogue.read(uri)


def test_the_library_fallback_refuses_an_agent_file(tmp_path):
    assert _read(tmp_path, "skill://drawio/agents/diagrammer.md") is None


def test_the_skill_fallback_refuses_an_agent_file(tmp_path):
    assert _read(tmp_path, "skill://drawio/drawio/agents/diagrammer.md") is None


def test_a_dotted_path_does_not_slip_past_the_refusal(tmp_path):
    assert _read(tmp_path, "skill://drawio/agents/../agents/diagrammer.md") is None
    assert _read(tmp_path, "skill://drawio/./agents/diagrammer.md") is None


def test_a_listed_agent_file_is_refused_wherever_it_sits(tmp_path):
    root = tmp_path / "kit"
    _write(root, "roles/reviewer.md", _agent("reviewer"))
    _write(root, "roles/notes.md", "notes\n")
    _write(
        root,
        ".claude-plugin/plugin.json",
        json.dumps({"name": "kit", "agents": ["./roles/reviewer.md"]}),
    )
    config = Config.model_validate(
        {
            "plugins": [{"name": "kit", "source": f"file://{root}"}],
            "libraries": [{"name": "kit", "plugins": ["kit"]}],
        }
    )
    catalogue = KnowledgeBase(config, tmp_path / "cache").catalogue

    assert catalogue.read("skill://kit/roles/reviewer.md") is None
    assert catalogue.read("skill://kit/roles/notes.md") == "notes\n"


def test_an_operator_files_glob_still_serves_agents(tmp_path):
    root = tmp_path / "kit"
    _write(root, "agents/a.md", _agent("a"))
    _write(root, ".claude-plugin/plugin.json", json.dumps({"name": "kit"}))
    config = Config.model_validate(
        {
            "plugins": [
                {
                    "name": "kit",
                    "source": f"file://{root}",
                    "files": ["agents/**/*.md"],
                }
            ],
            "libraries": [{"name": "kit", "plugins": ["kit"]}],
        }
    )
    catalogue = KnowledgeBase(config, tmp_path / "cache").catalogue

    listing = catalogue.read("skill://kit/_files.md")
    assert listing is not None and "agents/a.md" in listing
    assert catalogue.read("skill://kit/agents/a.md") == _agent("a")


def test_a_bare_plugins_agents_folder_is_not_guarded(tmp_path):
    assert _read(tmp_path, "skill://drive/agents/x.md") == _agent("x")
