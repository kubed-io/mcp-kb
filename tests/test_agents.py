"""Subagent files: read for the agents extension, and harvested into the record.

``agents_tree`` is the shared fixture of the agents tasks -- the shape of
kubed-io/skills in the parts that matter -- and is imported by the tests that
serve it.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.catalogue.agents import ParsedAgent, parse_agent, routing_hint
from kubed.mcp_kb.config import Config

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
        {"path": "agents/broken.md", "reason": "agent frontmatter has no description"}
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
