"""Skills served through kubed-mcp's plugin set, kb's view and kb's rewriter (K3).

kb publishes a plugin set each generation: every plugin of every library, added
as itself under its library's namespace. kubed-mcp serves the skills, their
files, ``_manifest`` and folders, and the prompts, through kb's command reader;
kb serves its indexes, ``_files.md``, library files and fallbacks. kb's scope is
the view, and kb's placeholder and name rewriting the one rewriter.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import re
from pathlib import Path

import pytest
from fastmcp import Client
from kubed.mcp.plugins import PluginError, PluginSet
from kubed.mcp.protocol import MCPError

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.config import Config
from kubed.mcp_kb.mcp import tools as tools_module
from kubed.mcp_kb.mcp.scope import Scope
from kubed.mcp_kb.mcp.skills import EMPTY
from tests.conftest import (
    ext_request,
    http_client,
    make_config,
    serve_http,
    server_of,
    serving_of,
)
from tests.test_git_source import _config as _git_config
from tests.test_git_source import origin  # noqa: F401 - a fixture

pytestmark = pytest.mark.unit

MAIN = (
    "---\nname: kit\ndescription: The kit.\n---\n\n"
    "Read ${CLAUDE_PLUGIN_ROOT}/skills/kit/ref.md, start at ${CLAUDE_PLUGIN_ROOT},"
    " look in ${CLAUDE_SKILL_DIR}, then use kit:other.\n"
)
OTHER = "---\nname: other\ndescription: The other one.\n---\n\nOther.\n"
NOTES = (
    "${CLAUDE_PLUGIN_ROOT}/skills/kit/ref.md ${CLAUDE_PLUGIN_ROOT}"
    " ${CLAUDE_SKILL_DIR} kit:other\n"
)
AGENT = (
    "---\nname: helper\ndescription: Helps.\n---\n"
    "Use kit:other from ${CLAUDE_PLUGIN_ROOT}.\n"
)


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def market(
    tmp_path: Path,
    entries: list[dict],
    files: dict[str, str],
    *,
    name: str = "lib",
    extra: list[dict] | None = None,
) -> Config:
    """A marketplace library ``name`` publishing ``entries``, over ``files``."""
    root = tmp_path / name
    _write(root, files)
    _write(
        root,
        {".claude-plugin/marketplace.json": json.dumps({"name": name, "plugins": entries})},
    )
    return Config.model_validate(
        {"libraries": [{"name": name, "source": f"file://{root}"}, *(extra or [])]}
    )


def kit(tmp_path: Path, **more: str) -> KnowledgeBase:
    """Library ``lib`` whose one entry ``kit`` is its main plugin (SKL-59)."""
    config = market(
        tmp_path,
        [{"name": "kit", "source": "./", "tags": ["t"]}],
        {
            "skills/kit/SKILL.md": MAIN,
            "skills/kit/ref.md": "ref\n",
            "skills/kit/notes.md": NOTES,
            "skills/kit/data.json": '{"a": 1}\n',
            "skills/other/SKILL.md": OTHER,
            "agents/helper.md": AGENT,
            **more,
        },
    )
    return KnowledgeBase(config, tmp_path / "cache")


async def _text(client, uri: str) -> str:
    return (await client.read_resource(uri))[0].text


async def _miss(client, uri: str) -> tuple:
    with pytest.raises(MCPError) as error:
        await client.read_resource(uri)
    return error.value.code, error.value.message.replace(uri, "<uri>")


# -- skills ------------------------------------------------------------------


async def test_every_skill_reads_at_its_address(skills_dir):
    knowledge_base = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    catalogue = knowledge_base.catalogue
    async with Client(server_of(knowledge_base)) as client:
        listing = await ext_request(client, "skills/list")
        uris = {entry["uri"] for entry in listing["skills"]}
        assert uris == {
            f"skill://{s.address}/SKILL.md" for s in catalogue.visible_skills()
        }
        for skill in catalogue.visible_skills():
            raw = (skill.path / "SKILL.md").read_text()
            got = await _text(client, f"skill://{skill.address}/SKILL.md")
            assert got == catalogue.instructions(skill.address, raw)


async def test_the_listing_is_index_rows_only(skills_dir):
    knowledge_base = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    catalogue = knowledge_base.catalogue
    async with Client(server_of(knowledge_base)) as client:
        rows = [str(r.uri) for r in await client.list_resources()]
    assert rows == [entry.uri for entry in catalogue.entries()]
    assert not [uri for uri in rows if uri.endswith("/SKILL.md")]

    with serve_http(knowledge_base) as url:
        async with http_client(url, {"Kb-Listing": "full"}) as client:
            full = [str(r.uri) for r in await client.list_resources()]
    assert full == [entry.uri for entry in catalogue.entries(full=True)]
    assert len([uri for uri in full if uri.endswith("/SKILL.md")]) == len(
        catalogue.visible_skills()
    )


async def test_kubed_mcp_serves_the_prompts(tmp_path):
    """The prompts are the plugin layer's, under kb's names (PLG-25); a command
    lists no resource row, and reads unlisted at ``prompts://<namespace>/<place>``,
    its raw text, where ``<place>`` is its path below the entry that read it (P6)."""
    command = "---\ndescription: Say it.\n---\nSay it.\n"
    skill = "---\nname: {0}\ndescription: Skill {0}.\n---\n{0}\n"
    config = market(
        tmp_path,
        [{"name": "a", "source": "./a"}, {"name": "b", "source": "./b"}],
        {
            "a/commands/hello.md": command,
            "a/skills/sa/SKILL.md": skill.format("sa"),
            "b/.claude-plugin/plugin.json": json.dumps(
                {"name": "b", "commands": ["./prompts/x.md"]}
            ),
            "b/prompts/x.md": command,
            "b/skills/sb/SKILL.md": skill.format("sb"),
        },
    )
    knowledge_base = KnowledgeBase(config, tmp_path / "cache")
    async with Client(server_of(knowledge_base)) as client:
        names = [p.name for p in await client.list_prompts()]
        rows = [str(r.uri) for r in await client.list_resources()]
        read = {
            uri: await _text(client, uri)
            for uri in ("prompts://lib/a/hello.md", "prompts://lib/b/prompts/x.md")
        }
        with pytest.raises(MCPError):
            await client.read_resource("prompts://lib/a/commands/hello.md")
        assert await _text(client, "skill://lib/a/sa/SKILL.md")
    assert names == [p.name for p in knowledge_base.snapshot.prompts]
    assert sorted(names) == ["lib_hello", "lib_x"]
    assert not [uri for uri in rows if uri.startswith("prompts://")]
    assert set(read.values()) == {command}


async def test_a_strict_false_entry_without_components_serves(tmp_path):
    config = market(
        tmp_path,
        [{"name": "kit", "source": "./", "strict": False}],
        {
            ".claude-plugin/plugin.json": json.dumps({"name": "kit"}),
            "skills/kit/SKILL.md": MAIN,
        },
    )
    knowledge_base = KnowledgeBase(config, tmp_path / "cache")
    async with Client(server_of(knowledge_base)) as client:
        assert "The kit" in await _text(client, "skill://lib/kit/SKILL.md")
    assert "conflicts" not in knowledge_base.status["libraries"]["lib"]


async def test_skill_md_is_rewritten_by_kb_alone(tmp_path):
    knowledge_base = kit(tmp_path)
    async with Client(server_of(knowledge_base)) as client:
        body = await _text(client, "skill://lib/kit/SKILL.md")
        notes = await _text(client, "skill://lib/kit/notes.md")
    assert "Read skill://lib/kit/ref.md," in body
    assert "start at skill://lib," in body
    assert "look in skill://lib/kit," in body
    assert "use skill://lib/other/SKILL.md." in body
    assert "${CLAUDE" not in body and "kit:other" not in body
    assert notes == NOTES


async def test_two_scopes_with_one_key_read_the_same_bytes(tmp_path, monkeypatch):
    config = market(
        tmp_path,
        [{"name": "kit", "source": "./", "tags": ["t"]}],
        {"skills/kit/SKILL.md": MAIN, "skills/other/SKILL.md": OTHER},
        extra=[{"name": "else", "source": f"file://{_else(tmp_path)}"}],
    )
    knowledge_base = KnowledgeBase(config, tmp_path / "cache")
    uri = "skill://lib/kit/SKILL.md"
    got = []
    with serve_http(knowledge_base) as url:
        for query in ("?library=lib", "?tag=t"):
            async with http_client(url + query) as client:
                text = await _text(client, uri)
                entry = await ext_request(client, "skills/get", uri=uri)
            got.append((text, _digest(entry, uri)))
    assert got[0] == got[1]
    assert "skill://lib/other/SKILL.md" in got[0][0]

    serving = serving_of(knowledge_base)
    keys = []
    for scope in (Scope.parse(library="lib"), Scope.parse(tags="t")):
        monkeypatch.setattr("kubed.mcp_kb.mcp.skills.requested_scope", lambda s=scope: s)
        keys.append(serving.view().key)
    assert keys[0] == keys[1] != EMPTY


def _else(tmp_path: Path) -> Path:
    """A second marketplace library, ``else``, carrying no tag ``t``."""
    root = tmp_path / "else"
    _write(
        root,
        {
            ".claude-plugin/marketplace.json": json.dumps(
                {"name": "else", "plugins": [{"name": "e", "source": "./"}]}
            ),
            "skills/e/SKILL.md": "---\nname: e\ndescription: E.\n---\nE\n",
        },
    )
    return root


async def test_an_out_of_scope_skill_reads_as_absent(tmp_path):
    config = market(
        tmp_path,
        [{"name": "kit", "source": "./"}],
        {"skills/kit/SKILL.md": MAIN},
        extra=[{"name": "else", "source": f"file://{_else(tmp_path)}"}],
    )
    knowledge_base = KnowledgeBase(config, tmp_path / "cache")
    with serve_http(knowledge_base) as url:
        async with http_client(url + "?library=else") as client:
            hidden = await _miss(client, "skill://lib/kit/SKILL.md")
            absent = await _miss(client, "skill://lib/nope/SKILL.md")
        async with http_client(url) as client:
            assert await _text(client, "skill://lib/kit/SKILL.md")
    assert hidden == absent


async def test_one_prefix_wins_everywhere(tmp_path):
    knowledge_base = kit(tmp_path)
    headers = {"Kb-Resource-Prefix": "kb+", "X-MCP-Resource-Prefix": "other+"}
    with serve_http(knowledge_base) as url:
        async with http_client(url, headers) as client:
            body = await _text(client, "kb+skill://lib/kit/SKILL.md")
            index = await _text(client, "kb+skill://lib/_index.md")
            agent = await ext_request(client, "agents/get", name="lib_helper")
    for text in (body, index, agent["instructions"]):
        assert "kb+skill://" in text
        assert "other+" not in text


async def test_a_refused_add_is_a_conflict(tmp_path, monkeypatch):
    skill = "---\nname: {0}\ndescription: Skill {0}.\n---\n{0}\n"
    config = market(
        tmp_path,
        [{"name": "a", "source": "./a"}, {"name": "b", "source": "./b"}],
        {
            "a/.claude-plugin/plugin.json": json.dumps({"name": "a"}),
            "a/skills/sa/SKILL.md": skill.format("sa"),
            "a/agents/ga.md": "---\nname: ga\ndescription: A.\n---\nA\n",
            "b/.claude-plugin/plugin.json": json.dumps({"name": "b"}),
            "b/skills/sb/SKILL.md": skill.format("sb"),
            "b/agents/gb.md": "---\nname: gb\ndescription: B.\n---\nB\n",
        },
    )
    reason = "x is inside skill skill://lib/x/SKILL.md of plugin y"
    real = PluginSet.add

    def add(self, address, *, namespace=None, manifest=None):
        if namespace == "lib/b":
            raise PluginError(reason)
        return real(self, address, namespace=namespace, manifest=manifest)

    monkeypatch.setattr(PluginSet, "add", add)
    knowledge_base = KnowledgeBase(config, tmp_path / "cache")
    async with Client(server_of(knowledge_base)) as client:
        assert await _text(client, "skill://lib/a/sa/SKILL.md")
        with pytest.raises(MCPError):
            await client.read_resource("skill://lib/b/sb/SKILL.md")
        index = await _text(client, "skill://lib/_index.md")
        names = [a["name"] for a in (await ext_request(client, "agents/list"))["agents"]]
        listing = await ext_request(client, "skills/list")
        refused = await _agent_miss(client, "lib_gb")
        absent = await _agent_miss(client, "lib_nobody")
    assert refused == absent
    conflict = knowledge_base.status["libraries"]["lib"]["conflicts"]["b@lib"]
    assert conflict.startswith("conflict: ") and reason in conflict
    assert "lib/b" not in index
    assert names == ["lib_ga"]
    assert [e["uri"] for e in listing["skills"]] == ["skill://lib/a/sa/SKILL.md"]
    assert str(tmp_path / "cache") not in json.dumps(knowledge_base.status)


async def test_kb_names_only_what_kubed_mcp_serves(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="kubed.mcp_kb.mcp.skills"):
        knowledge_base = kit(
            tmp_path,
            **{
                "skills/empty/SKILL.md": "---\nname: empty\ndescription: ''\n---\nE\n",
                "skills/other/SKILL.md": OTHER.replace("Other.", "See kit:empty."),
            },
        )
    async with Client(server_of(knowledge_base)) as client:
        with pytest.raises(MCPError):
            await client.read_resource("skill://lib/empty/SKILL.md")
        other = await _text(client, "skill://lib/other/SKILL.md")
        index = await _text(client, "skill://lib/_index.md")
        listing = await ext_request(client, "skills/list")
        with pytest.raises(MCPError) as hint:
            await client.read_resource("skill://lib/empty")
    assert "See kit:empty." in other
    assert "empty" not in index
    assert "skill://lib/empty/SKILL.md" not in [e["uri"] for e in listing["skills"]]
    assert "SKILL.md" not in hint.value.message
    lines = [r for r in caplog.records if "lib/empty" in r.getMessage()]
    assert len(lines) == 1


async def test_the_resource_tools_are_kubed_mcps(tmp_path):
    knowledge_base = kit(tmp_path)
    with serve_http(knowledge_base) as url:
        async with http_client(url + "?resources=off") as client:
            off = {t.name for t in await client.list_tools()}
            index = await client.call_tool(
                "read_resource", {"uri": "skill://lib/_index.md"}
            )
            body = await client.call_tool(
                "read_resource", {"uri": "skill://lib/kit/SKILL.md"}
            )
        async with http_client(url, {"Kb-Resources": "off"}) as client:
            kb_off = {t.name for t in await client.list_tools()}
        async with http_client(url) as client:
            on = {t.name for t in await client.list_tools()}
    assert {"list_resources", "read_resource"} <= off
    assert {"list_resources", "read_resource"} <= kb_off
    assert not {"list_resources", "read_resource"} & on
    assert "skill://lib/kit/SKILL.md" in index.content[0].text
    assert "skill://lib/other/SKILL.md" in body.content[0].text
    source = inspect.getsource(tools_module)
    assert "def list_resources" not in source
    assert "def read_resource" not in source


async def test_a_refresh_serves_the_new_set(tmp_path, caplog):
    knowledge_base = kit(tmp_path)
    root = tmp_path / "lib"
    (root / "skills/kit/SKILL.md").write_text(MAIN + "\nEdited.\n")
    (root / "skills/other/SKILL.md").unlink()
    (root / "agents/helper.md").unlink()
    # Harvested, then gone before the set is published: the layer never reads it.
    note = (
        "agent file agents/helper.md of plugin kit@lib is not served:"
        " the plugin layer did not read it"
    )

    def notes() -> int:
        return [
            r.getMessage()
            for r in caplog.records
            if r.name == "kubed.mcp_kb.mcp.skills"
        ].count(note)

    with caplog.at_level(logging.WARNING):
        server_of(knowledge_base)
    assert notes() == 1
    async with Client(server_of(knowledge_base)) as client:
        knowledge_base.refresh(force=True)
        knowledge_base.refresh(force=True)
        assert notes() == 1
        assert "Edited." in await _text(client, "skill://lib/kit/SKILL.md")
        with pytest.raises(MCPError):
            await client.read_resource("skill://lib/other/SKILL.md")
        assert "other" not in await _text(client, "skill://lib/_index.md")
        agents = await ext_request(client, "agents/list")
    assert agents["agents"] == []


async def test_a_skill_arriving_after_boot_reads(tmp_path):
    root = tmp_path / "lib"
    config = market(
        tmp_path, [{"name": "kit", "source": "./"}], {"README.md": "nothing yet\n"}
    )
    knowledge_base = KnowledgeBase(config, tmp_path / "cache")
    server_of(knowledge_base)
    _write(root, {"skills/kit/SKILL.md": MAIN, "skills/kit/ref.md": "ref\n"})
    knowledge_base.refresh(force=True)
    async with Client(server_of(knowledge_base)) as client:
        assert "The kit" in await _text(client, "skill://lib/kit/SKILL.md")
        manifest = json.loads(await _text(client, "skill://lib/kit/_manifest"))
        index = await _text(client, "skill://lib/kit/_index.md")
    assert {f["path"] for f in manifest["files"]} == {"SKILL.md", "ref.md"}
    assert "skill://lib/kit/ref.md" in index


async def test_manifest_names_the_skill_by_its_name(tmp_path):
    """N1: FastMCP's ``_manifest``, naming the skill by its name."""
    knowledge_base = kit(tmp_path)
    async with Client(server_of(knowledge_base)) as client:
        manifest = json.loads(await _text(client, "skill://lib/kit/_manifest"))
    assert manifest["skill"] == "kit"


async def test_a_json_file_reads_as_text(tmp_path):
    knowledge_base = kit(tmp_path)
    async with Client(server_of(knowledge_base)) as client:
        result = await client.read_resource("skill://lib/kit/data.json")
    assert result[0].text == '{"a": 1}\n'


async def test_a_skill_digest_is_of_the_bytes_served(tmp_path):
    knowledge_base = kit(tmp_path)
    uri = "skill://lib/kit/SKILL.md"
    async with Client(server_of(knowledge_base)) as client:
        text = await _text(client, uri)
        entry = await ext_request(client, "skills/get", uri=uri)
    digest = f"sha256:{hashlib.sha256(text.encode()).hexdigest()}"
    assert _digest(entry, uri) == digest


def _digest(entry: dict, uri: str) -> str:
    """The digest ``skills/get`` gives for the file at ``uri``."""
    return next(r["digest"] for r in entry["skill"]["resources"] if r["uri"] == uri)


async def _agent_miss(client, name: str) -> tuple:
    with pytest.raises(MCPError) as error:
        await ext_request(client, "agents/get", name=name)
    return error.value.code, error.value.message, error.value.data


# -- what FastMCP reads whole (N13, N14) --------------------------------------

HIDDEN = "skill {} holds a hidden file, which kubed-mcp would serve; not served"


@pytest.mark.parametrize("hidden", [".env", "refs/.cache/x.md", ".git/config"])
async def test_a_skill_holding_a_hidden_path_is_not_served(tmp_path, caplog, hidden):
    """N13: FastMCP reads a skill folder whole, dot files included, so a skill
    holding one is not served at all; the others serve."""
    with caplog.at_level(logging.WARNING, logger="kubed.mcp_kb.mcp.skills"):
        knowledge_base = kit(
            tmp_path,
            **{
                "skills/vault/SKILL.md": "---\nname: vault\ndescription: V.\n---\nV\n",
                f"skills/vault/{hidden}": "SECRET=1\n",
            },
        )
        server_of(knowledge_base)
    async with Client(server_of(knowledge_base)) as client:
        for uri in (
            f"skill://lib/vault/{hidden}",
            "skill://lib/vault/SKILL.md",
            "skill://lib/vault/_manifest",
        ):
            with pytest.raises(MCPError):
                await client.read_resource(uri)
        listing = await ext_request(client, "skills/list")
        index = await _text(client, "skill://lib/_index.md")
        assert "The kit" in await _text(client, "skill://lib/kit/SKILL.md")
        manifest = json.loads(await _text(client, "skill://lib/kit/_manifest"))
    uris = {entry["uri"] for entry in listing["skills"]}
    assert uris == {"skill://lib/kit/SKILL.md", "skill://lib/other/SKILL.md"}
    assert "vault" not in index
    assert not [f for f in manifest["files"] if "/." in "/" + f["path"]]
    assert "lib/vault" not in [s.address for s in knowledge_base.catalogue.visible_skills()]
    lines = [r.getMessage() for r in caplog.records if r.name == "kubed.mcp_kb.mcp.skills"]
    assert lines == [HIDDEN.format("lib/vault")]
    assert "SECRET" not in json.dumps(knowledge_base.status)


async def test_a_skill_holding_a_symlink_is_not_served(tmp_path, caplog):
    """N14: FastMCP refuses a skill holding a symlink whole; the parity guard
    takes it out of kb's catalogue, and says so once."""
    root = tmp_path / "lib"
    _write(root, {"elsewhere.md": "linked\n"})
    with caplog.at_level(logging.WARNING, logger="kubed.mcp_kb.mcp.skills"):
        config = market(
            tmp_path,
            [{"name": "kit", "source": "./"}],
            {
                "skills/kit/SKILL.md": MAIN,
                "skills/other/SKILL.md": OTHER,
            },
        )
        (root / "skills/other/ref.md").symlink_to(root / "elsewhere.md")
        knowledge_base = KnowledgeBase(config, tmp_path / "cache")
        server_of(knowledge_base)
    async with Client(server_of(knowledge_base)) as client:
        with pytest.raises(MCPError):
            await client.read_resource("skill://lib/other/SKILL.md")
        index = await _text(client, "skill://lib/_index.md")
        assert "The kit" in await _text(client, "skill://lib/kit/SKILL.md")
    assert "skill://lib/other/" not in index
    lines = [r.getMessage() for r in caplog.records if r.name == "kubed.mcp_kb.mcp.skills"]
    assert lines == ["skill lib/other is not served: the plugin layer refused it"]


async def test_a_skill_kb_did_not_find_is_not_served(tmp_path, caplog, monkeypatch):
    """M3: N13 fails closed. A skill the plugin layer finds and kb's harvest did
    not is one kb never vetted, so its ``SKILL.md`` fails in kb's rewriter and
    it is not served at all; the server says so once."""
    from kubed.mcp_kb.catalogue import harvest

    real = harvest.skill_dirs

    def missing_other(root, globs):
        return [d for d in real(root, globs) if Path(d).name != "other"]

    monkeypatch.setattr(harvest, "skill_dirs", missing_other)
    with caplog.at_level(logging.WARNING, logger="kubed.mcp_kb.mcp.skills"):
        knowledge_base = kit(tmp_path)
        server_of(knowledge_base)
        async with Client(server_of(knowledge_base)) as client:
            for uri in ("skill://lib/other/SKILL.md", "skill://lib/other/_manifest"):
                with pytest.raises(MCPError):
                    await client.read_resource(uri)
            listing = await ext_request(client, "skills/list")
            assert "The kit" in await _text(client, "skill://lib/kit/SKILL.md")
            # A second session: still not served, and not said again.
            async with Client(server_of(knowledge_base)) as again:
                await ext_request(again, "skills/list")
    assert {entry["uri"] for entry in listing["skills"]} == {"skill://lib/kit/SKILL.md"}
    lines = [r.getMessage() for r in caplog.records if r.name == "kubed.mcp_kb.mcp.skills"]
    assert lines == ["skill lib/other is not served: kb did not find it"]


async def test_a_misnamed_folder_claimed_first_takes_the_address(tmp_path, caplog):
    """Brief fact 2: ``skills/x`` names itself ``y``, so kb skips it and serves
    the declared ``extra/x``; kubed-mcp's first claim of ``x`` wins and is
    refused, so neither serves, and kb names neither."""
    root = tmp_path / "kit"
    _write(
        root,
        {
            "skills/x/SKILL.md": "---\nname: y\ndescription: Misnamed.\n---\nY\n",
            "extra/x/SKILL.md": "---\nname: x\ndescription: The real x.\n---\nX\n",
            "skills/ok/SKILL.md": "---\nname: ok\ndescription: Fine.\n---\nOK\n",
        },
    )
    config = Config.model_validate(
        {
            "plugins": [{"name": "lib", "source": f"file://{root}", "skills": ["./extra"]}],
            "libraries": [{"name": "lib", "plugins": ["lib"]}],
        }
    )
    with caplog.at_level(logging.WARNING, logger="kubed.mcp_kb.mcp.skills"):
        knowledge_base = KnowledgeBase(config, tmp_path / "cache")
        assert "lib/x" in [s.address for s in knowledge_base.catalogue.visible_skills()]
        server_of(knowledge_base)
    async with Client(server_of(knowledge_base)) as client:
        with pytest.raises(MCPError):
            await client.read_resource("skill://lib/x/SKILL.md")
        index = await _text(client, "skill://lib/_index.md")
        assert "Fine" in await _text(client, "skill://lib/ok/SKILL.md")
    assert "skill://lib/x/" not in index
    lines = [r.getMessage() for r in caplog.records if r.name == "kubed.mcp_kb.mcp.skills"]
    assert lines == ["skill lib/x is not served: the plugin layer refused it"]


# -- publishing ----------------------------------------------------------------


async def test_a_serve_that_raises_keeps_the_published_set(tmp_path, monkeypatch):
    knowledge_base = kit(tmp_path)
    serving = serving_of(knowledge_base)
    before = serving._published
    (tmp_path / "lib/skills/kit/SKILL.md").write_text(MAIN + "\nEdited.\n")

    def refuse(staged):
        raise RuntimeError("serve failed")

    monkeypatch.setattr(serving._mcp, "serve", refuse)
    with pytest.raises(RuntimeError, match="serve failed"):
        knowledge_base.refresh(force=True)

    assert serving._published is before
    async with Client(server_of(knowledge_base)) as client:
        body = await _text(client, "skill://lib/kit/SKILL.md")
    assert "skill://lib/other/SKILL.md" in body
    assert "Edited." not in body


async def test_a_refusal_quoting_the_tree_names_kbs_address(
    origin, tmp_path, monkeypatch  # noqa: F811 - a fixture
):
    """A ``PluginError`` that names the served tree, a cache path, is published
    with kb's own address in its place."""
    config = _git_config(origin, ref="main")
    knowledge_base = KnowledgeBase(config, tmp_path / "cache")
    key = f"lab://{origin.path.name}?ref=main"
    tree = knowledge_base.served_tree(key)
    assert tree is not None and str(tmp_path / "cache") in str(tree)
    real = PluginSet.add

    def add(self, address, *, namespace=None, manifest=None):
        raise PluginError(f"{tree}/skills/x is not a folder; nor is {tree}")

    monkeypatch.setattr(PluginSet, "add", add)
    server_of(knowledge_base)
    monkeypatch.setattr(PluginSet, "add", real)

    conflict = knowledge_base.status["libraries"]["library"]["conflicts"]["library"]
    assert str(tmp_path / "cache") not in conflict
    assert conflict == (
        f"conflict: skills/x is not a folder; nor is lab://{origin.path.name}?ref=main"
    )


async def test_an_agent_kb_did_not_read_is_kbs_too(tmp_path):
    """N10: kubed-mcp serves a nameless agent under its stem: kb found its
    file, so it is counted and carries kb's key."""
    knowledge_base = kit(
        tmp_path, **{"agents/nameless.md": "---\ndescription: No name.\n---\nHi\n"}
    )
    server_of(knowledge_base)
    async with Client(server_of(knowledge_base)) as client:
        got = await ext_request(client, "agents/get", name="lib_nameless")
    assert got["_meta"]["io.kubed.mcp-kb/agent"]["path"] == "agents/nameless.md"
    assert got["_meta"]["io.kubed.mcp-kb/agent"]["plugin"] == "kit@lib"
    assert "lib_nameless" in [a.name for a in knowledge_base.snapshot.agents]
    assert knowledge_base.status["libraries"]["lib"]["agents"] == 2


async def test_kbs_index_json_carries_the_prefix_as_its_index_md_does(tmp_path):
    """One writer: kb's own ``_index.json`` is text, prefixed as kb's
    ``_index.md`` and kubed-mcp's skill-folder ``_index.json`` are."""
    knowledge_base = kit(tmp_path)
    with serve_http(knowledge_base) as url:
        async with http_client(url, {"Kb-Resource-Prefix": "kb+"}) as client:
            ours = await _text(client, "skill://lib/_index.json")
            theirs = await _text(client, "skill://lib/kit/_index.json")
            md = await _text(client, "skill://lib/_index.md")
    for text in (ours, theirs, md):
        assert "kb+skill://" in text
        assert re.search(r"(?<![+\w])skill://", text) is None, text
