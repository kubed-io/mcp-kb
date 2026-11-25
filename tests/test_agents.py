"""Subagent files: read for the agents extension, and harvested into the record.

``agents_tree`` is the shared fixture of the agents tasks -- the shape of
kubed-io/skills in the parts that matter -- and is imported by the tests that
serve it.
"""

import asyncio
import importlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import pytest
from kubed.mcp.protocol import MCPError

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.catalogue.agents import (
    ParsedAgent,
    parse_agent,
    routing_hint,
)
from kubed.mcp_kb.catalogue.snapshot import build_snapshot
from kubed.mcp_kb.catalogue.uris import AGENT_META
from kubed.mcp_kb.config import Config
from tests.conftest import (
    ext_request,
    http_client,
    read_served,
    run_client,
    serve_http,
    server_of,
)

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


def _served(knowledge_base: KnowledgeBase) -> dict[str, dict]:
    """Every agent the served app gives an unscoped caller: name -> agents/get."""

    async def read(client) -> dict[str, dict]:
        cards = (await ext_request(client, "agents/list"))["agents"]
        return {
            card["name"]: await ext_request(client, "agents/get", name=card["name"])
            for card in cards
        }

    return run_client(knowledge_base, read)


def _names(knowledge_base: KnowledgeBase, library: str) -> list[str]:
    """The served agents of ``library``: every one's name starts ``<library>_``."""
    return sorted(n for n in _served(knowledge_base) if n.startswith(f"{library}_"))


def _owners(knowledge_base: KnowledgeBase, library: str = "drawio") -> dict[str, str]:
    """Each served agent's name in ``library``, mapped to its plugin."""
    return {
        name: got["_meta"][AGENT_META]["plugin"]
        for name, got in _served(knowledge_base).items()
        if name.startswith(f"{library}_")
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

    owners = _owners(knowledge_base, "mix")
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
    # A skill of `copy` sits in its own folder (SKL-59), so what it collides on
    # is a prompt name an earlier plugin of the library already serves.
    command = "---\ndescription: Draw.\n---\nDraw.\n"
    _entries(
        tree,
        before=[("first", {"commands/draw.md": command})],
        after=[
            ("copy", {"commands/draw.md": command, "agents/c.md": _agent("clone")})
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
    """AGT-15: a scope admits an agent as it admits its plugin."""
    knowledge_base = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")

    async def read(url):
        async with http_client(url + "?tag=diagrams") as client:
            diagrams = (await ext_request(client, "agents/list"))["agents"]
        async with http_client(url + "?category=other") as client:
            other = (await ext_request(client, "agents/list"))["agents"]
        async with http_client(url + "?tag=extra") as client:
            with pytest.raises(MCPError) as hidden:
                await ext_request(client, "agents/get", name="drawio_diagrammer")
            with pytest.raises(MCPError) as absent:
                await ext_request(client, "agents/get", name="nobody")
        return diagrams, other, hidden.value, absent.value

    with serve_http(knowledge_base) as url:
        diagrams, other, hidden, absent = asyncio.run(read(url))

    assert diagrams == [
        {
            "name": "drawio_diagrammer",
            "description": "Draws diagrams.",
            "capabilities": [],
        }
    ]
    assert [c["name"] for c in other] == [
        "drawio_db_migrator",
        "drawio_diagrammer@extra",
        "drawio_twin",
    ]
    assert (hidden.code, hidden.message, hidden.data) == (
        absent.code,
        absent.message,
        absent.data,
    )
    assert sorted(_served(knowledge_base)) == [
        "drawio_db_migrator",
        "drawio_diagrammer",
        "drawio_diagrammer@extra",
        "drawio_twin",
        "lone_solo",
    ]


KB_META = {
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


def test_the_definition(tmp_path):
    """AGT-9 as kubed-mcp serves it: ``instructions`` is trimmed (N10), and
    ``_meta`` carries kubed-mcp's key beside kb's (N5)."""
    knowledge_base = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")

    definition = _served(knowledge_base)["drawio_diagrammer"]

    assert definition["agent"] == "drawio_diagrammer"
    assert definition["instructions"] == (
        "Read skill://drawio/drawio/SKILL.md in ${CLAUDE_PROJECT_DIR}."
    )
    assert definition["modelRoutingHint"] == {"role": "medium", "vision": False}
    assert definition["tools"] == []
    assert definition["_meta"][AGENT_META] == KB_META
    assert definition["_meta"]["io.kubed/agent"]["frontmatter"] == KB_META[
        "frontmatter"
    ]


def test_a_blank_body_and_no_model_leave_their_fields_out(tmp_path):
    root = tmp_path / "kit"
    # Agents alone, no skill: a plugin serving only agents is added too.
    _write(root, "agents/quiet.md", "---\nname: quiet\ndescription: d\n---\n\n  \n")
    _write(root, ".claude-plugin/plugin.json", json.dumps({"name": "kit"}))
    config = Config.model_validate(
        {
            "plugins": [{"name": "kit", "source": f"file://{root}"}],
            "libraries": [{"name": "kit", "plugins": ["kit"]}],
        }
    )

    definition = _served(KnowledgeBase(config, tmp_path / "cache"))["kit_quiet"]

    assert "instructions" not in definition
    assert "modelRoutingHint" not in definition
    assert definition["_meta"][AGENT_META]["servers"] == []


def test_a_row_that_no_longer_parses_is_reported_and_keeps_its_claim(tmp_path):
    """A cold start serves the rows the index recorded; a file that broke since
    is reported under its plugin, and kb's roster keeps its claim."""
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
    names = [a.name for a in snapshot.catalogue.agents.visible()]
    assert "drawio_diagrammer" not in names
    assert "drawio_diagrammer@extra" in names
    assert snapshot.status["libraries"]["drawio"]["agents"] == 3
    assert str(tmp_path / "cache") not in json.dumps(snapshot.status)


def test_a_broken_agent_frees_its_name_on_a_cold_start(tmp_path):
    """N11: kubed-mcp reads each file when its plugin is added, so an agent that
    no longer parses claims nothing, and the next one takes the short name."""
    tree = agents_tree(tmp_path)
    tree.knowledge_base(tmp_path / "cache")
    drawio = tmp_path / "market/plugins/drawio/agents/diagrammer.md"
    drawio.write_text("---\nname: diagrammer\n---\nNo description now.\n")

    knowledge_base = tree.knowledge_base(tmp_path / "cache")

    owners = _owners(knowledge_base)
    assert owners["drawio_diagrammer"] == "extra@drawio"
    assert "drawio_diagrammer@extra" not in owners
    assert "renamed" not in knowledge_base.status["libraries"]["drawio"]


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


# -- served by kubed-mcp (D11) -------------------------------------------------


def test_agent_names_are_kbs(tmp_path):
    """Review Focus 5: kubed-mcp's names across the set are kb's per library."""
    knowledge_base = KnowledgeBase(_mix(agents_tree(tmp_path)), tmp_path / "cache")
    roster = sorted(a.name for a in knowledge_base.catalogue.agents.visible())

    assert sorted(_served(knowledge_base)) == roster
    assert "mix_diagrammer@extra" in roster
    assert "drawio_diagrammer@extra" in roster
    libraries = knowledge_base.status["libraries"]
    assert libraries["drawio"]["renamed"] == {
        "drawio_diagrammer@extra": (
            "drawio_diagrammer is already served by plugin 'drawio@drawio'"
        )
    }
    assert libraries["mix"]["renamed"] == {
        "mix_diagrammer@extra": (
            "mix_diagrammer is already served by plugin 'drawio@drawio'"
        )
    }
    assert libraries["mix"]["unserved"] == [
        {
            "plugin": "extra@other",
            "path": "agents/diagrammer.md",
            "reason": "mix_diagrammer@extra is already served by plugin 'extra@drawio'",
        }
    ]


def _kit_agent(tmp_path: Path, agent: str, **files: str) -> KnowledgeBase:
    root = tmp_path / "kit"
    _write(root, ".claude-plugin/plugin.json", json.dumps({"name": "kit"}))
    _write(root, "skills/draw/SKILL.md", "---\nname: draw\ndescription: d\n---\nd\n")
    _write(root, "agents/a.md", agent)
    for rel, text in files.items():
        _write(root, rel, text)
    config = Config.model_validate(
        {
            "plugins": [{"name": "kit", "source": f"file://{root}", "tags": ["k"]}],
            "libraries": [{"name": "kit", "plugins": ["kit"]}],
        }
    )
    return KnowledgeBase(config, tmp_path / "cache")


def test_agent_instructions_are_rendered_by_kb(tmp_path):
    """AGT-17 then PRM-48 on the body; the frontmatter reads as written."""
    head = "---\nname: a\ndescription: See ${CLAUDE_PLUGIN_ROOT}.\n---\n"
    body = (
        "Use kit:draw, read ${CLAUDE_PLUGIN_ROOT}/skills/draw/x.md"
        " in ${CLAUDE_SKILL_DIR}.\n"
    )
    knowledge_base = _kit_agent(tmp_path, head + body)

    got = _served(knowledge_base)["kit_a"]

    assert got["instructions"] == (
        "Use skill://kit/draw/SKILL.md, read skill://kit/draw/x.md"
        " in ${CLAUDE_SKILL_DIR}."
    )
    assert got["_meta"][AGENT_META]["frontmatter"]["description"] == (
        "See ${CLAUDE_PLUGIN_ROOT}."
    )
    assert got["_meta"]["io.kubed/agent"]["frontmatter"]["description"] == (
        "See ${CLAUDE_PLUGIN_ROOT}."
    )


def test_agent_meta_keeps_kbs_key(tmp_path):
    """kb's ``io.kubed.mcp-kb/agent`` is today's value but for ``skills`` (N9),
    with kubed-mcp's ``io.kubed/agent`` beside it (N5)."""
    agent = "---\nname: a\ndescription: d\nskills: [draw, kit:draw]\n---\nBody.\n"
    knowledge_base = _kit_agent(tmp_path, agent)

    meta = _served(knowledge_base)["kit_a"]["_meta"]

    assert meta[AGENT_META] == {
        "plugin": "kit",
        "library": "kit",
        "path": "agents/a.md",
        "frontmatter": {
            "name": "a",
            "description": "d",
            "skills": ["draw", "kit:draw"],
        },
        "servers": [],
        "skills": {
            "draw": "skill://kit/draw/SKILL.md",
            "kit:draw": "skill://kit/draw/SKILL.md",
        },
    }
    assert "io.kubed/agent" in meta


def test_agent_meta_names_no_skill_of_another_plugin(tmp_path):
    """SCP-24, N9: ``skills`` resolves against the agent's own plugin, so no
    scope learns of another plugin's skill through it."""
    other = tmp_path / "other"
    _write(other, "skills/x/SKILL.md", "---\nname: x\ndescription: x\n---\nx\n")
    root = tmp_path / "kit"
    _write(root, ".claude-plugin/plugin.json", json.dumps({"name": "kit"}))
    _write(root, "skills/draw/SKILL.md", "---\nname: draw\ndescription: d\n---\nd\n")
    _write(
        root,
        "agents/a.md",
        "---\nname: a\ndescription: d\nskills: [other:x, draw]\n---\nUse other:x.\n",
    )
    config = Config.model_validate(
        {
            "plugins": [
                {"name": "kit", "source": f"file://{root}", "tags": ["k"]},
                {"name": "other", "source": f"file://{other}", "tags": ["o"]},
            ],
            "libraries": [{"name": "kit", "plugins": ["kit", "other"]}],
        }
    )
    knowledge_base = KnowledgeBase(config, tmp_path / "cache")

    async def read(url):
        got = {}
        for query in ("", "?tag=k", "?library=kit"):
            async with http_client(url + query) as client:
                got[query] = await ext_request(client, "agents/get", name="kit_a")
        return got

    with serve_http(knowledge_base) as url:
        got = asyncio.run(read(url))

    for query, definition in got.items():
        skills = definition["_meta"][AGENT_META]["skills"]
        assert "other:x" not in skills, query
        assert skills == {"draw": "skill://kit/draw/SKILL.md"}, query
    # The body's names stay the rewriter's, which runs per view.
    assert got[""]["instructions"] == "Use skill://kit/other/x/SKILL.md."
    assert got["?tag=k"]["instructions"] == "Use other:x."


def test_a_bare_plugin_serves_no_agent(tmp_path):
    """AGT-4: no plugin.json and no marketplace entry, so no agents."""
    root = tmp_path / "bare"
    _write(root, "skills/b/SKILL.md", "---\nname: b\ndescription: b\n---\nb\n")
    _write(root, "agents/x.md", _agent("x"))
    config = Config.model_validate(
        {
            "plugins": [{"name": "bare", "source": f"file://{root}"}],
            "libraries": [{"name": "bare", "plugins": ["bare"]}],
        }
    )
    knowledge_base = KnowledgeBase(config, tmp_path / "cache")

    assert _served(knowledge_base) == {}
    assert read_served(knowledge_base, "skill://bare/b/SKILL.md")


def test_an_out_of_scope_agent_is_absent(tmp_path):
    knowledge_base = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")

    async def read(url):
        failures = []
        async with http_client(url + "?library=lone") as client:
            for name in ("drawio_diagrammer", "nobody"):
                with pytest.raises(MCPError) as error:
                    await ext_request(client, "agents/get", name=name)
                failures.append((error.value.code, error.value.message, error.value.data))
        return failures

    with serve_http(knowledge_base) as url:
        hidden, absent = asyncio.run(read(url))

    assert hidden == absent
    assert absent[1] == "Agent not found"


def test_an_out_of_scope_agents_file_reads_as_absent(tmp_path):
    """N7: an agent's file reads at ``agents://``, under the connection's scope,
    and out of scope it fails as an absent one does."""
    knowledge_base = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")
    uri = "agents://drawio/diagrammer.md"
    nope = "agents://drawio/nope.md"

    async def read(url):
        async with http_client(url) as client:
            body = (await client.read_resource(uri))[0].text
        failures = []
        async with http_client(url + "?library=lone") as client:
            for each in (uri, nope):
                with pytest.raises(MCPError) as error:
                    await client.read_resource(each)
                failures.append(
                    (error.value.code, error.value.message.replace(each, "<uri>"))
                )
        return body, failures

    with serve_http(knowledge_base) as url:
        body, (hidden, absent) = asyncio.run(read(url))

    assert "Draws diagrams." in body
    assert hidden == absent


def test_kb_has_no_agents_extension(tmp_path):
    with pytest.raises(ImportError):
        importlib.import_module("kubed.mcp_kb.mcp.agents")
    knowledge_base = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")
    server = server_of(knowledge_base)
    answering = [
        extension
        for extension in server._extensions.values()
        if any(m.method == "agents/list" for m in extension.methods())
    ]
    assert len(answering) == 1
    assert type(answering[0]).__module__.startswith("kubed.mcp.")


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


@pytest.mark.parametrize(
    ("folder", "name"),
    [
        ("a b", "a b_r"),
        ("x@y", "x@y_r"),
        ("a\nb", "a\nb_r"),
        ("z\u200bw", "z\u200bw_r"),
    ],
)
def test_an_agent_whose_folder_is_not_a_usable_name_is_skipped(tmp_path, folder, name):
    tree = agents_tree(tmp_path)
    _entries(
        tree,
        after=[
            (
                "odd",
                {f"agents/{folder}/r.md": _agent("r"), "agents/ok/r.md": _agent("r")},
            )
        ],
    )

    knowledge_base = tree.knowledge_base(tmp_path / "cache")

    assert "drawio_ok_r" in _names(knowledge_base, "drawio")
    assert not [
        n
        for n in _names(knowledge_base, "drawio")
        if n.endswith("_r") and n != "drawio_ok_r"
    ]
    assert knowledge_base.status["plugins"]["odd@drawio"]["skipped"] == [
        {
            "path": f"agents/{folder}/r.md",
            "reason": f"agent name {name!r} is not a usable name",
        }
    ]
