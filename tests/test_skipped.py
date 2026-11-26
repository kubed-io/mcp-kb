"""What one plugin ships but cannot serve: skipped, and named in ``/health``.

A plugin whose tree holds something the address space has no room for keeps
serving everything else. The one thing is left out and listed under
``skipped`` in that plugin's ``/health`` entry, with the reason, so it is
visible rather than silently shadowed:

- a library file whose address lies inside one of the plugin's own skills,
  or that is named like the server's own indexes;
- a skill whose frontmatter ``name`` is not one valid segment matching its
  directory, or whose address a skill before it already has;
- a prompt whose name a prompt before it already has.

Across two plugins of one library the rule is the one in ``test_conflicts.py``:
the later plugin fails in that library.
"""

import json
import logging

import httpx
import pytest
from fastmcp import Client

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.catalogue import skills
from kubed.mcp_kb.config import Config
from kubed.mcp_kb.mcp.scope import Scope
from tests.conftest import server_of, serving_of

pytestmark = pytest.mark.unit


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _skill(root, rel, name, description):
    _write(
        root, f"{rel}/SKILL.md", f"---\nname: {name}\ndescription: {description}\n---\n"
    )


def _kb(tmp_path, build, globs, name="src"):
    """One plugin ``name`` in library `lib`: its skills sit at `lib/<name>/…`."""
    root = tmp_path / "src"
    root.mkdir()
    build(root)
    config = Config.model_validate(
        {
            "plugins": [{"name": name, "source": f"file://{root}", **globs}],
            "libraries": [{"name": "lib", "plugins": [name]}],
        }
    )
    return KnowledgeBase(config, tmp_path / "c")


async def _health(knowledge_base):
    transport = httpx.ASGITransport(app=server_of(knowledge_base).http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://kb") as http:
        return (await http.get("/health")).json()


async def _read(knowledge_base, uri):
    """The body at ``uri``, or None when the server says it is not there."""
    async with Client(server_of(knowledge_base)) as client:
        try:
            return (await client.read_resource(uri))[0].text
        except Exception as exc:  # noqa: BLE001 - "not found" is the answer
            assert "not found" in str(exc)
            return None


def _skipped(health, plugin="src"):
    return {row["path"]: row["reason"] for row in health["plugins"][plugin]["skipped"]}


# -- library files --------------------------------------------------------------


def _overlapping(root):
    _skill(root, "skills/grafana-lgtm/loki", "loki", "Query logs.")
    _skill(root, "skills/grafana-lgtm/tempo", "tempo", "Query traces.")
    _skill(root, "skills/grafana-k6/k6", "k6", "Load test.")
    _write(root, "grafana-lgtm/loki/notes.md", "LIBRARY NOTES\n")
    _write(root, "grafana-lgtm/tempo/SKILL.md", "LIBRARY FILE SHADOWED\n")
    _write(root, "_index.md", "LIBRARY INDEX\n")
    _write(root, "docs/_files.md", "LIBRARY FILES LIST\n")
    _write(root, "shared/ok.md", "fine\n")


OVERLAP_GLOBS = {
    "skills": ["./skills/grafana-lgtm", "./skills/grafana-k6"],
    "files": ["shared/**", "grafana-lgtm/**", "docs/**", "_index.md"],
}
# The plugin the overlapping tree is: its skills sit at lib/grafana-lgtm/<name>,
# which is where the tree's grafana-lgtm/ files would be served.
OVERLAP = "grafana-lgtm"


async def test_a_library_file_inside_one_of_its_own_plugins_skills_is_skipped(tmp_path):
    kb = _kb(tmp_path, _overlapping, OVERLAP_GLOBS, OVERLAP)
    health = await _health(kb)

    entry = health["plugins"][OVERLAP]
    assert entry["status"] == "ok"
    assert entry["files"] == 1
    assert health["libraries"]["lib"]["files"] == 1
    skipped = _skipped(health, OVERLAP)
    assert "grafana-lgtm/loki" in skipped["grafana-lgtm/loki/notes.md"]
    assert "grafana-lgtm/tempo" in skipped["grafana-lgtm/tempo/SKILL.md"]

    files = await _read(kb, "skill://lib/_files.md")
    assert "skill://lib/shared/ok.md" in files
    assert "grafana-lgtm" not in files
    assert await _read(kb, "skill://lib/grafana-lgtm/loki/notes.md") is None
    assert "Query traces." in await _read(kb, "skill://lib/grafana-lgtm/tempo/SKILL.md")
    # One URI, one answer: a scope that hides the skill does not uncover the file.
    pinned = Scope.parse("lib", categories=["nope"])
    assert kb.catalogue.read("skill://lib/grafana-lgtm/tempo/SKILL.md", pinned) is None


async def test_a_library_file_named_like_an_index_is_skipped(tmp_path):
    kb = _kb(tmp_path, _overlapping, OVERLAP_GLOBS, OVERLAP)
    health = await _health(kb)

    skipped = _skipped(health, OVERLAP)
    assert "_index.md" in skipped["_index.md"]
    assert "_files.md" in skipped["docs/_files.md"]
    assert "LIBRARY INDEX" not in await _read(kb, "skill://lib/_index.md")
    assert await _read(kb, "skill://lib/docs/_files.md") is None
    assert "_index.md" not in await _read(kb, "skill://lib/_files.md")


async def test_a_plugin_with_nothing_skipped_reports_no_skipped_list(tmp_path):
    kb = _kb(
        tmp_path,
        lambda r: (_skill(r, "skills/a", "a", "A."), _write(r, "shared/x.md", "x\n")),
        {"files": ["shared/**"]},
    )
    assert "skipped" not in (await _health(kb))["plugins"]["src"]


# -- skills -----------------------------------------------------------------------


def _misnamed(root):
    _skill(root, "skills/f/good", "good", "Good.")
    _skill(root, "skills/f/dotdot", "..", "Dots.")
    _skill(root, "skills/f/slash", "grafana-lgtm/loki", "Slash.")
    _skill(root, "skills/f/Upper", "Upper", "Upper.")
    _skill(root, "skills/f/mismatch", "other", "Mismatch.")
    _skill(root, "skills/f/idx", "_index.md", "Index.")
    # One address reached from two skill folders: the first claimed serves, and
    # skills/ is claimed before any declared folder.
    _skill(root, "skills/dup", "dup", "First dup.")
    _skill(root, ".claude/skills/dup", "dup", "Second dup.")


MISNAMED_GLOBS = {"skills": ["./skills/f", "./.claude/skills"]}


async def test_a_skill_that_cannot_be_one_address_segment_is_skipped(tmp_path):
    kb = _kb(tmp_path, _misnamed, MISNAMED_GLOBS, "f")
    health = await _health(kb)

    entry = health["plugins"]["f"]
    assert entry["status"] == "ok"
    assert entry["skills"] == 2
    skipped = _skipped(health, "f")
    for path in ("skills/f/dotdot", "skills/f/slash", "skills/f/Upper", "skills/f/idx"):
        assert "naming rule" in skipped[path], path
    assert "directory" in skipped["skills/f/mismatch"]
    assert skipped[".claude/skills/dup"] == "dup is already served by skills/dup"
    assert set(skipped) == {
        "skills/f/dotdot",
        "skills/f/slash",
        "skills/f/Upper",
        "skills/f/mismatch",
        "skills/f/idx",
        ".claude/skills/dup",
    }

    # Every skill of the plugin `f` sits in its folder, the one directly in
    # skills/ included.
    folder = await _read(kb, "skill://lib/f/_index.md")
    assert folder.startswith("# lib/f — 2 skills\n")
    assert "skill://lib/f/good/SKILL.md" in folder
    assert ".." not in folder and "grafana-lgtm" not in folder
    assert folder.count("skill://lib/f/dup/SKILL.md") == 1
    library = await _read(kb, "skill://lib/_index.md")
    assert library.startswith("# lib — 2 skills\n")
    assert "First dup." in await _read(kb, "skill://lib/f/dup/SKILL.md")
    for uri in (
        "skill://lib/f/other/SKILL.md",
        "skill://lib/f/mismatch/SKILL.md",
        "skill://lib/f/Upper/SKILL.md",
        "skill://lib/f/grafana-lgtm/loki/SKILL.md",
        "skill://lib/f/_index.md/SKILL.md",
    ):
        assert await _read(kb, uri) is None, uri


async def test_a_plugin_that_is_one_skill_is_not_served(tmp_path, caplog):
    """A git fetch's root is a directory named for a commit, not for the skill.

    kb harvests it, but kubed-mcp names a declared ``.`` skill after its root
    folder, which FastMCP refuses for not matching its ``name``: the parity
    guard takes it out of every index, the plugin lists its root as skipped
    with the layer's reason, says so once, and counts no skill (I3, I5).
    """
    kb = _kb(
        tmp_path,
        lambda r: _skill(r, ".", "whole", "The whole plugin."),
        {"skills": ["."]},
    )
    with caplog.at_level(logging.WARNING, logger="kubed.mcp_kb"):
        health = await _health(kb)

    reason = "Skill folder 'src' must match its SKILL.md name 'whole'"
    assert health["plugins"]["src"]["skills"] == 0
    assert health["plugins"]["src"]["skipped"] == [{"path": ".", "reason": reason}]
    assert health["libraries"]["lib"]["skills"] == 0
    assert await _read(kb, "skill://lib/src/whole/SKILL.md") is None
    assert _ours(caplog, "whole") == [f"plugin src skips '.': {reason}"]
    assert _theirs(caplog, "whole") == []


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("a", True),
        ("pdf-processing", True),
        ("k6", True),
        ("x" * 64, True),
        ("x" * 65, False),
        ("-a", False),
        ("a-", False),
        ("a--b", False),
        ("a_b", False),
        ("a.b", False),
        ("A", False),
        ("..", False),
        ("a/b", False),
        ("", False),
    ],
)
def test_the_agent_skills_naming_rule(name, valid):
    assert (skills.naming_problem(name) is None) is valid


# -- prompts ----------------------------------------------------------------------


async def test_a_second_prompt_with_one_name_in_a_plugin_is_skipped(tmp_path):
    def build(root):
        _write(root, "prompts/debug.md", "---\ndescription: 1\n---\nfirst\n")
        _write(root, "prompts/sub/debug.md", "---\ndescription: 2\n---\nsecond\n")

    kb = _kb(tmp_path, build, {})
    health = await _health(kb)

    assert health["plugins"]["src"]["prompts"] == 1
    assert _skipped(health)["prompts/sub/debug.md"] == (
        "prompt lib_debug is already served by prompts/debug.md"
    )
    async with Client(server_of(kb)) as client:
        prompts = await client.list_prompts()
        rendered = await client.get_prompt("lib_debug")
        mirrored = await client.call_tool("list_prompts", {})
    assert [p.name for p in prompts] == ["lib_debug"]
    assert "first" in rendered.messages[0].content.text
    assert mirrored.content[0].text.count("lib_debug") == 1


async def test_a_skipped_skills_own_files_neither_serve_nor_fail_the_plugin(tmp_path):
    """A `files:` glob that reaches into a skill the plugin then skips.

    Skill directories and library files come from one harvest, and library files
    never include anything inside a harvested skill — valid or not — so the
    skipped skill's files are simply not served. The plugin stays `ok`, lists the
    skill under `skipped`, and serves its valid skill.
    """
    root = tmp_path / "src"
    (root / "skills" / "good").mkdir(parents=True)
    (root / "skills" / "good" / "SKILL.md").write_text(
        "---\nname: good\ndescription: g\n---\nbody\n"
    )
    (root / "skills" / "bad").mkdir(parents=True)
    (root / "skills" / "bad" / "SKILL.md").write_text(
        "---\nname: Not_Valid\ndescription: b\n---\nbody\n"
    )
    (root / "skills" / "bad" / "notes.md").write_text("never served\n")
    config = Config.model_validate(
        {
            "plugins": [
                {"name": "lib", "source": f"file://{root}", "files": ["skills/bad/**/*"]}
            ],
            "libraries": [{"name": "lib", "plugins": ["lib"]}],
        }
    )
    kb = KnowledgeBase(config, tmp_path / "cache")
    status = kb.snapshot.status["plugins"]["lib"]

    assert status["status"] == "ok"
    assert [entry["path"] for entry in status["skipped"]] == ["skills/bad"]
    async with Client(server_of(kb)) as client:
        assert "body" in (await client.read_resource("skill://lib/good/SKILL.md"))[0].text
        with pytest.raises(Exception, match="not found"):
            await client.read_resource("skill://lib/skills/bad/notes.md")


# -- what the plugin layer does not serve (K6) ------------------------------------

# FastMCP's Agent Skills limit: SKILL.md and 512 more files is 513 (Task 0 (b)).
BIG_REASON = "A skill may contain at most 512 files"
NESTED = "a skill is one folder below its skills folder"
HELLO = "---\ndescription: Hi.\n---\nHello.\n"


def _big(root):
    _skill(root, "skills/big", "big", "Too many files.")
    for i in range(512):
        _write(root, f"skills/big/refs/{i}.md", "x\n")
    _skill(root, "skills/ok", "ok", "Fine.")


def _ours(caplog, word):
    """kb's log lines that mention ``word``."""
    return [
        r.getMessage()
        for r in caplog.records
        if r.name.startswith("kubed.mcp_kb") and word in r.getMessage()
    ]


def _theirs(caplog, word):
    """The plugin layer's log lines that mention ``word``, past kb's filter."""
    return [
        r.getMessage()
        for r in caplog.records
        if (r.name == "kubed.mcp" or r.name.startswith("kubed.mcp."))
        and word in r.getMessage()
    ]


def _plugins(tmp_path, trees, libraries):
    """One declared plugin per ``trees`` entry, each over ``tmp_path/<name>``."""
    rows = []
    for name, build in trees.items():
        root = tmp_path / name
        root.mkdir()
        build(root)
        rows.append({"name": name, "source": f"file://{root}"})
    config = Config.model_validate(
        {
            "plugins": rows,
            "libraries": [{"name": n, "plugins": p} for n, p in libraries.items()],
        }
    )
    return KnowledgeBase(config, tmp_path / "c")


def _greeter(skill):
    """A plugin of one skill, ``skill``, and the prompt file ``commands/hello.md``."""

    def build(root):
        _skill(root, f"skills/{skill}", skill, "S.")
        _write(root, "commands/hello.md", HELLO)

    return build


def _counts(entry):
    return {kind: entry[kind] for kind in ("skills", "prompts", "agents")}


async def test_a_skill_folder_the_layer_skips_is_a_row(tmp_path, caplog):
    """I3: a skill folder the plugin layer does not load is a ``skipped`` row,
    its path relative to the plugin root, and is not counted. It is logged
    once, by kb, and neither the layer's line nor the parity note says it."""
    with caplog.at_level(logging.WARNING, logger="kubed.mcp_kb"):
        kb = _kb(tmp_path, _big, {})
        health = await _health(kb)
        kb.refresh(force=True)
    plugin = health["plugins"]["src"]
    assert plugin["skipped"] == [{"path": "skills/big", "reason": BIG_REASON}]
    assert plugin["skills"] == 1
    assert health["libraries"]["lib"]["skills"] == 1
    assert _ours(caplog, "big") == [f"plugin src skips 'skills/big': {BIG_REASON}"]
    assert _theirs(caplog, "big") == []
    assert await _read(kb, "skill://lib/src/big/SKILL.md") is None
    assert "Fine." in await _read(kb, "skill://lib/src/ok/SKILL.md")


async def test_a_skill_folder_kb_did_not_find_is_said_once(tmp_path, caplog, monkeypatch):
    """A skill folder the layer skips that kb's harvest never found is not the
    plugin's row, as an agent file's is not (D4); kb says it once, in the
    layer's place."""
    from kubed.mcp_kb.catalogue import harvest

    real = harvest.skill_dirs
    monkeypatch.setattr(
        harvest,
        "skill_dirs",
        lambda root, globs: [d for d in real(root, globs) if d.name != "big"],
    )
    with caplog.at_level(logging.WARNING, logger="kubed.mcp_kb"):
        kb = _kb(tmp_path, _big, {})
        health = await _health(kb)
        kb.refresh(force=True)
    assert "skipped" not in health["plugins"]["src"]
    assert _ours(caplog, "big") == [
        f"'skills/big' of plugin src is not served: {BIG_REASON}"
    ]
    assert _theirs(caplog, "big") == []


async def test_a_nested_skill_is_no_row_and_no_note(tmp_path, caplog):
    """kubed-mcp's line for a ``SKILL.md`` deeper than a skill folder is one of
    its plugin's ``components.notes``, never ``skipped``: kb neither lists it
    nor reads it into its own ``notes``, and the layer's line is kept."""

    def build(root):
        _skill(root, "skills/ok", "ok", "Fine.")
        _skill(root, "skills/g/y", "y", "Nested.")

    with caplog.at_level(logging.WARNING):
        kb = _kb(tmp_path, build, {})
        health = await _health(kb)
    plugin = health["plugins"]["src"]
    assert "skipped" not in plugin and "notes" not in plugin
    assert NESTED not in json.dumps(health)
    assert any(NESTED in line for line in _theirs(caplog, "skills/g/y"))


async def test_a_refused_plugin_counts_no_skills_prompts_or_agents(tmp_path):
    """I4: a plugin the layer refuses (LIB-29) serves nothing, so counts none."""
    kb = _plugins(
        tmp_path,
        {"first": _greeter("a"), "second": _greeter("b")},
        {"lib": ["first", "second"]},
    )
    health = await _health(kb)
    conflict = health["libraries"]["lib"]["conflicts"]["second"]
    assert conflict.startswith("conflict: prompt lib_hello")
    assert _counts(health["plugins"]["second"]) == {
        "skills": 0,
        "prompts": 0,
        "agents": 0,
    }
    assert _counts(health["plugins"]["first"]) == {
        "skills": 1,
        "prompts": 1,
        "agents": 0,
    }


async def test_a_skills_empty_plugin_counts_no_prompts_or_agents(tmp_path):
    """I4: a plugin declared ``skills: []`` is never added (LIB-33), so its
    prompt file is not counted."""

    def build(root):
        _skill(root, "skills/a", "a", "A.")
        _write(root, "commands/hello.md", HELLO)

    kb = _kb(tmp_path, build, {"skills": []})
    health = await _health(kb)
    assert _counts(health["plugins"]["src"]) == {
        "skills": 0,
        "prompts": 0,
        "agents": 0,
    }


async def test_a_plugin_refused_in_one_library_counts_what_another_serves(tmp_path):
    """Review Focus 3: ``second`` is refused in ``lib`` and alone in ``solo``,
    so its counts are what ``solo`` serves of it."""
    kb = _plugins(
        tmp_path,
        {"first": _greeter("a"), "second": _greeter("b")},
        {"lib": ["first", "second"], "solo": ["second"]},
    )
    health = await _health(kb)
    assert "second" in health["libraries"]["lib"]["conflicts"]
    assert _counts(health["plugins"]["second"]) == {
        "skills": 1,
        "prompts": 1,
        "agents": 0,
    }


async def test_a_skill_kb_and_the_layer_both_skip_is_one_row(tmp_path):
    """Review Focus 4: one row per path, and kb's reason is the one kept."""

    def build(root):
        _skill(root, "skills/a", "b", "Misnamed.")
        _skill(root, "skills/ok", "ok", "Fine.")

    kb = _kb(tmp_path, build, {})
    health = await _health(kb)
    assert health["plugins"]["src"]["skipped"] == [
        {"path": "skills/a", "reason": "name 'b' differs from its directory 'a'"}
    ]
    served = [p for p in serving_of(kb)._mcp.plugins if p.name == "src"]
    assert any(path == "skills/a" for p in served for path, _ in p.skipped)


async def test_a_layer_row_names_no_cache_path(tmp_path, monkeypatch):
    """Review Focus 5: the ``_big`` plugin read through a ``git+file://``
    source, so its tree sits under the cache: the row names the plugin's
    path, never the cache's, even when the layer's reason quotes it."""
    import pygit2
    from kubed.mcp import skills as layer

    real = layer._load_skill

    def quoting(path):
        # As an unreadable file's errno text does: the absolute path, in the cache.
        loaded = real(path)
        return f"{loaded}: {path}/refs/0.md" if isinstance(loaded, str) else loaded

    monkeypatch.setattr(layer, "_load_skill", quoting)
    repo_root = tmp_path / "hub" / "kit"
    _big(repo_root)
    repo = pygit2.init_repository(str(repo_root), initial_head="main")
    repo.index.add_all()
    repo.index.write()
    signature = pygit2.Signature("Test", "test@example.com", 1700000000, 0)
    tree = repo.index.write_tree()
    repo.create_commit("refs/heads/main", signature, signature, "one", tree, [])
    config = Config.model_validate(
        {
            "sources": [{"name": "lab", "url": f"git+file://{tmp_path / 'hub'}"}],
            "plugins": [{"name": "src", "source": "lab://kit?ref=main"}],
            "libraries": [{"name": "lib", "plugins": ["src"]}],
        }
    )
    kb = KnowledgeBase(config, tmp_path / "c")
    health = await _health(kb)
    assert health["plugins"]["src"]["skipped"] == [
        {"path": "skills/big", "reason": f"{BIG_REASON}: skills/big/refs/0.md"}
    ]
    assert str(tmp_path / "c") not in json.dumps(health)


async def test_a_duplicate_skill_folder_logs_kbs_line_alone(tmp_path, caplog):
    """D6: kubed-mcp claims ``x`` for ``skills/x``, which kb skips, so it skips
    the declared ``extra/x`` as served already. Both are rows, each logged
    once by kb, and the layer's lines for them are kept out of the log."""

    def build(root):
        _skill(root, "skills/x", "y", "Misnamed.")
        _skill(root, "extra/x", "x", "The real x.")
        _skill(root, "skills/ok", "ok", "Fine.")

    with caplog.at_level(logging.WARNING):
        kb = _kb(tmp_path, build, {"skills": ["./extra"]})
        health = await _health(kb)
    skipped = _skipped(health)
    assert skipped["skills/x"] == "name 'y' differs from its directory 'x'"
    assert skipped["extra/x"].endswith(" is already served by skills/x")
    assert _ours(caplog, "'extra/x'") == [
        f"plugin src skips 'extra/x': {skipped['extra/x']}"
    ]
    assert _ours(caplog, "'skills/x'") == [
        f"plugin src skips 'skills/x': {skipped['skills/x']}"
    ]
    assert _ours(caplog, "the plugin layer refused it") == []
    assert _theirs(caplog, "served already") == []
    assert _theirs(caplog, "not a valid Agent Skill") == []


async def test_a_skipped_agent_file_logs_kbs_line_alone(tmp_path, caplog):
    """D6: an agent file the layer skips, for its frontmatter or for a name
    another file of its plugin serves, is logged once, by kb."""
    from tests.test_agents import agents_tree

    with caplog.at_level(logging.WARNING):
        kb = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")
        health = await _health(kb)
    (pid,) = [pid for pid in health["plugins"] if pid.startswith("extra")]
    skipped = _skipped(health, pid)
    for path in ("agents/broken.md", "agents/twin-b.md"):
        assert _ours(caplog, repr(path)) == [
            f"plugin {pid} skips {path!r}: {skipped[path]}"
        ]
        assert _theirs(caplog, path.removeprefix("agents/")) == []


async def test_a_skipped_command_file_logs_kbs_line_alone(tmp_path, caplog):
    """D6: a prompt file the layer skips, for a name an earlier file has or
    for kb's reader refusing it, is logged once, by kb."""

    def build(root):
        _skill(root, "skills/ok", "ok", "Fine.")
        _write(root, "prompts/debug.md", "---\ndescription: 1\n---\nfirst\n")
        _write(root, "prompts/sub/debug.md", "---\ndescription: 2\n---\nsecond\n")
        _write(root, "commands/broken.md", "---\ndescription: [\n---\nx\n")

    with caplog.at_level(logging.WARNING):
        kb = _kb(tmp_path, build, {})
        health = await _health(kb)
    skipped = _skipped(health)
    for path in ("prompts/sub/debug.md", "commands/broken.md"):
        assert _ours(caplog, repr(path)) == [
            f"plugin src skips {path!r}: {skipped[path]}"
        ]
        assert _theirs(caplog, path.rpartition("/")[2]) == []
    assert _theirs(caplog, "is skipped") == []


async def test_an_unselected_command_beside_a_root_skills_entry_is_quiet(
    tmp_path, caplog
):
    """P8: a one-skill plugin (``skills: ["."]``) whose command folder holds a
    file kb did not select. The layer skips it as ``NOT_SELECTED``, and
    nobody logs it, however wide the plugin's skills entry is."""
    root = tmp_path / "whole"
    _skill(root, ".", "whole", "The whole plugin.")
    _write(root, "commands/a.md", HELLO)
    _write(root, "commands/b.md", HELLO)
    config = Config.model_validate(
        {
            "plugins": [
                {
                    "name": "src",
                    "source": f"file://{root}",
                    "skills": ["."],
                    "prompts": ["commands/a.md"],
                }
            ],
            "libraries": [{"name": "lib", "plugins": ["src"]}],
        }
    )
    with caplog.at_level(logging.WARNING):
        kb = KnowledgeBase(config, tmp_path / "c")
        health = await _health(kb)
    assert health["plugins"]["src"]["prompts"] == 1
    assert [r.getMessage() for r in caplog.records if "b.md" in r.getMessage()] == []
