"""The MCP surface: what a client sees, as resources and as the tool mirror."""

import json
import logging
from importlib.metadata import version as dist_version

import fastmcp
import httpx
import pytest
from fastmcp import Client
from kubed.mcp.protocol import types

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.config import Config
from tests.conftest import key_of, make_config, server_of
from tests.test_skills_extension import request

KB_INFO = {"name": "mcp-kb", "version": dist_version("kubed-mcp-kb")}
# kubed-mcp's report of the delivery settings it resolved (HTTP-42).
DELIVERY_META = "io.kubed/delivery"
# A client kubed-mcp's table of known clients takes to declare resources off.
VS_CODE = types.Implementation(name="Visual Studio Code", version="1.99.0")


async def call(client, name, **args):
    """The tool's text, whether it is a result or an error result."""
    result = await client.call_tool(name, args, raise_on_error=False)
    return result.content[0].text


@pytest.mark.unit
# The handshake era does not stamp _meta on results; the initialize test covers it.
@pytest.mark.parametrize("mode", ["auto"])
async def test_every_result_names_kb_and_its_version(skills_dir, mode):
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    async with Client(server_of(server), mode=mode) as client:
        listing = await request(client, "skills/list")
    assert listing["_meta"][types.SERVER_INFO_META_KEY] == KB_INFO
    assert KB_INFO["version"] != fastmcp.__version__


@pytest.mark.unit
async def test_initialize_names_kb_and_its_version(skills_dir):
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    async with Client(server_of(server), mode="legacy") as client:
        info = client.initialize_result.server_info
    assert {"name": info.name, "version": info.version} == KB_INFO


async def delivery(client, mode):
    """The echo, from the answer the client's era negotiated with."""
    if mode == "legacy":
        return client.initialize_result.meta[DELIVERY_META]
    return (await request(client, "server/discover"))["_meta"][DELIVERY_META]


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_the_handshake_echo_matches_what_is_listed(skills_dir, mode):
    """HTTP-42: the echo says what kubed-mcp lists, VS Code (DLV-15) included."""
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "_cache")
    async with Client(server_of(server), mode=mode) as client:
        plain = await delivery(client, mode)
        assert await client.list_tools() == []
    assert plain["resources"] == "on"
    assert plain["prefix"] is None
    async with Client(server_of(server), mode=mode, client_info=VS_CODE) as client:
        vs_code = await delivery(client, mode)
        names = sorted(t.name for t in await client.list_tools())
    assert vs_code["resources"] == "off"
    assert names == ["list_resources", "read_resource"]


# -- resources ----------------------------------------------------------------


@pytest.mark.unit
async def test_resources_are_indexes_not_one_per_skill(skills_dir):
    """The listing is the cheap layer; it must not grow with the catalogue."""
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "_cache")
    async with Client(server_of(server)) as client:
        uris = [str(r.uri) for r in await client.list_resources()]
    assert "skill://flatsource/_index.md" in uris
    assert "skill://deepsource/plugin-a/_index.md" in uris
    assert not any("SKILL.md" in u for u in uris)


@pytest.mark.unit
async def test_reading_an_index_then_a_skill(skills_dir):
    """The whole interface: list addresses, read one, read the next."""
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "_cache")
    async with Client(server_of(server)) as client:
        index = (await client.read_resource("skill://deepsource/plugin-a/_index.md"))[
            0
        ].text
        assert "skill://deepsource/plugin-a/gamma/SKILL.md" in index
        body = (
            await client.read_resource("skill://deepsource/plugin-a/gamma/SKILL.md")
        )[0].text
    assert "Third skill." in body


@pytest.mark.unit
async def test_reading_a_manifest_then_one_of_its_files(skills_dir):
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "_cache")
    async with Client(server_of(server)) as client:
        manifest = (await client.read_resource("skill://flatsource/alpha/_manifest"))[
            0
        ].text
        paths = [f["path"] for f in json.loads(manifest)["files"]]
        assert "SKILL.md" in paths
        body = (await client.read_resource("skill://flatsource/alpha/SKILL.md"))[0].text
    assert "First skill." in body


@pytest.mark.unit
async def test_an_unknown_uri_is_an_error_not_an_empty_read(skills_dir):
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "_cache")
    async with Client(server_of(server)) as client:
        with pytest.raises(Exception, match=r"nope|[Uu]nknown|not found"):
            await client.read_resource("skill://flatsource/nope")


@pytest.mark.unit
async def test_server_scoped_to_libraries_hides_the_rest(skills_dir):
    """A config that lists less is the hard scope: the other library is unreachable."""
    server = KnowledgeBase(
        make_config(skills_dir, libraries=["flatsource"]), skills_dir / "_cache"
    )
    async with Client(server_of(server)) as client:
        uris = [str(r.uri) for r in await client.list_resources()]
        assert not any(u.startswith("skill://deepsource/") for u in uris)
        with pytest.raises(Exception, match=r"nknown|not found"):
            await client.read_resource("skill://deepsource/plugin-a/gamma/SKILL.md")


@pytest.mark.unit
async def test_empty_config_still_serves(tmp_path):
    """No plugins configured must not crash the server -- it just serves nothing."""
    server = KnowledgeBase(Config(), tmp_path / "cache")
    async with Client(server_of(server)) as client:
        assert await client.list_resources() == []


@pytest.mark.unit
async def test_a_failed_fetch_does_not_take_the_others_down(skills_dir):
    """One bad fetch must not stop the rest of the catalogue from loading, and
    every plugin reading it carries the fetch's error."""
    raw = make_config(skills_dir).model_dump(mode="json", by_alias=True, exclude_none=True)
    raw["plugins"].append({"name": "gone", "source": "file:///no/such/dir"})
    raw["libraries"].append({"name": "gone", "plugins": ["gone"]})
    config = Config.model_validate(raw)
    server = KnowledgeBase(config, skills_dir / "_cache")
    assert server.status["fetches"]["file:///no/such/dir"]["status"] == "failed"
    assert server.status["plugins"]["gone"]["status"] == "failed"
    assert "not a directory" in server.status["plugins"]["gone"]["error"]
    assert server.status["fetches"][key_of(config, "flatsource")]["status"] == "ok"
    assert server.status["plugins"]["flatsource"]["status"] == "ok"
    async with Client(server_of(server)) as client:
        uris = [str(r.uri) for r in await client.list_resources()]
    assert "skill://flatsource/_index.md" in uris


# -- the tool mirror ----------------------------------------------------------


@pytest.mark.unit
async def test_the_mirrors_are_four_tools_whatever_the_catalogue_holds(skills_dir):
    """Adding sources or prompts must never add tools; the mirrors absorb them."""
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "_cache")
    # Skip the middleware, which is the thing that hides these. What is
    # registered is what an ?resources=off client is shown; what a resource
    # client sees is covered over real HTTP in test_header_scope.
    # The resource pair is kubed-mcp's (N4), listed only to a client that
    # turned resources off, and always callable by name.
    mcp = server_of(server)
    registered = await mcp.list_tools(run_middleware=False)
    assert sorted(t.name for t in registered) == ["get_prompt", "list_prompts"]
    for name in ("list_resources", "read_resource"):
        assert await mcp.get_tool(name) is not None


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_vs_code_lists_the_resource_pair_without_a_header(skills_dir, mode):
    """TOOL-2: kubed-mcp takes VS Code to declare resources off (DLV-15)."""
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "_cache")
    async with Client(server_of(server), mode=mode, client_info=VS_CODE) as client:
        names = sorted(t.name for t in await client.list_tools())
        index = await call(client, "read_resource", uri="skill://flatsource/_index.md")
    assert names == ["list_resources", "read_resource"]
    assert "skill://flatsource/alpha/SKILL.md" in index
    async with Client(server_of(server), mode=mode) as client:
        assert await client.list_tools() == []


@pytest.mark.unit
async def test_the_mirror_tools_are_advertised_as_read_only(skills_dir):
    """Unannotated, MCP's defaults advertise a tool as destructive."""
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "_cache")
    mcp = server_of(server)
    registered = await mcp.list_tools(run_middleware=False)
    registered += [await mcp.get_tool(n) for n in ("list_resources", "read_resource")]
    assert len(registered) == 4
    for tool in registered:
        hints = tool.to_mcp_tool().annotations
        assert hints is not None, f"{tool.name} has no annotations"
        assert hints.read_only_hint is True
        assert hints.destructive_hint is False
        assert hints.idempotent_hint is True
        assert hints.open_world_hint is False
        assert hints.title or tool.title


@pytest.mark.unit
async def test_the_mirror_returns_the_same_rows_as_the_resource_listing(skills_dir):
    """If these drift, the tool is no longer the resource interface."""
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "_cache")
    async with Client(server_of(server)) as client:
        resources = {str(r.uri) for r in await client.list_resources()}
        # N4: kubed-mcp's list_resources answers {"resources": rows}.
        rows = json.loads(await call(client, "list_resources"))["resources"]
    assert {row["uri"] for row in rows} == resources
    assert {"uri", "name", "description", "mimeType"} <= set(rows[0])


@pytest.mark.unit
async def test_read_resource_returns_what_reading_the_uri_returns(skills_dir):
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "_cache")
    async with Client(server_of(server)) as client:
        gamma = "skill://deepsource/plugin-a/gamma/SKILL.md"
        through_tool = await call(client, "read_resource", uri=gamma)
        through_resource = (await client.read_resource(gamma))[0].text
    assert through_tool == through_resource


@pytest.mark.unit
async def test_read_resource_explains_an_unknown_uri(skills_dir, caplog):
    """An error result, so a caller branching on isError sees a miss -- with
    what to do next in its message, and no traceback in the server's log."""
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "_cache")
    server_of(server)  # publishing logs what the plugin layer notes; not a call
    caplog.clear()
    with caplog.at_level(logging.INFO):
        async with Client(server_of(server)) as client:
            result = await client.call_tool(
                "read_resource", {"uri": "skill://nope/nope"}, raise_on_error=False
            )
    assert result.is_error
    out = result.content[0].text
    # N4: kubed-mcp's tool words a miss as resources/read does.
    assert out == "Resource not found: 'skill://nope/nope'"
    # N4: kubed-mcp logs a caller's miss at INFO, where kb's tool used DEBUG;
    # never a warning, nor a traceback.
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not [r for r in caplog.records if r.exc_info]


@pytest.mark.unit
async def test_the_mirror_honours_the_hard_library_scope(skills_dir):
    """A tool call must not reach past a source that was never configured."""
    server = KnowledgeBase(
        make_config(skills_dir, libraries=["flatsource"]), skills_dir / "_cache"
    )
    async with Client(server_of(server)) as client:
        out = await call(
            client, "read_resource", uri="skill://deepsource/plugin-a/gamma/SKILL.md"
        )
    assert "Resource not found" in out


async def test_a_configmap_mount_is_served_under_the_names_it_was_mounted_as(tmp_path):
    """Every row names the path the config asked for, never the symlink target.

    A ConfigMap mounts `shared/foo.md -> ..data/shared/foo.md`, and `..data`
    points at a timestamp directory Kubernetes replaces on every update. A row
    recording the resolved path lists `..2026.../shared/foo.md` — not the URI a
    skill cites, and gone after the next update.
    """
    root = tmp_path / "library"
    stamp = root / "..2026_09_16_13_15_49"
    (stamp / "shared").mkdir(parents=True)
    (stamp / "shared" / "foo.md").write_text("shared body")
    (stamp / "skills" / "alpha").mkdir(parents=True)
    (stamp / "skills" / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: a\n---\nskill body"
    )
    (root / "..data").symlink_to(stamp)
    (root / "shared").symlink_to(root / "..data" / "shared")
    (root / "skills").symlink_to(root / "..data" / "skills")
    config = Config.model_validate(
        {
            "plugins": [
                {
                    "name": "library",
                    "source": f"file://{root}",
                    "prompts": [],
                    "files": ["shared/**/*"],
                }
            ],
            "libraries": [{"name": "library", "plugins": ["library"]}],
        }
    )
    knowledge_base = KnowledgeBase(config, tmp_path / "cache")

    assert knowledge_base.snapshot.resources.files("library") == ["shared/foo.md"]
    assert all(".." not in str(s.path) for s in knowledge_base.index.visible())
    async with Client(server_of(knowledge_base)) as client:
        shared = (await client.read_resource("skill://library/shared/foo.md"))[0].text
        skill = (await client.read_resource("skill://library/alpha/SKILL.md"))[0].text
    assert shared == "shared body"
    assert "skill body" in skill


@pytest.mark.unit
async def test_a_hidden_file_in_a_skill_is_not_readable_by_guessing(tmp_path):
    """A caller never gets a hidden file by typing its name, through the
    resource or the mirror.

    A `.env` beside a SKILL.md is exactly that file. kubed-mcp would serve it
    with the skill, so kb serves none of the skill holding it (N13); the skill
    beside it serves.
    """
    skill = tmp_path / "src" / "skills" / "x"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: x\ndescription: x\n---\nbody\n")
    (skill / ".env").write_text("SECRET=hunter2\n")
    (skill / "notes.md").write_text("visible\n")
    clean = tmp_path / "src" / "skills" / "y"
    clean.mkdir(parents=True)
    (clean / "SKILL.md").write_text("---\nname: y\ndescription: y\n---\nbody\n")
    (clean / "notes.md").write_text("visible\n")
    config = Config.model_validate(
        {
            "plugins": [{"name": "lib", "source": f"file://{tmp_path / 'src'}"}],
            "libraries": [{"name": "lib", "plugins": ["lib"]}],
        }
    )
    server = KnowledgeBase(config, tmp_path / "cache")

    async with Client(server_of(server)) as client:
        visible = (await client.read_resource("skill://lib/y/notes.md"))[0].text
        for uri in ("skill://lib/x/.env", "skill://lib/x/notes.md"):
            with pytest.raises(Exception, match=r"[Uu]nknown|not found"):
                await client.read_resource(uri)
        mirrored = await call(client, "read_resource", uri="skill://lib/x/.env")

    assert visible == "visible\n"
    assert "hunter2" not in mirrored


@pytest.mark.unit
async def test_health_shows_the_resolved_description(tmp_path):
    root = tmp_path / "market"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"name": "m", "description": "Upstream words.", "plugins": []})
    )
    config = Config.model_validate(
        {"libraries": [{"name": "up", "source": f"file://{root}"}]}
    )
    transport = httpx.ASGITransport(
        app=server_of(KnowledgeBase(config, tmp_path / "cache")).http_app()
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://kb") as http:
        health = (await http.get("/health")).json()
    assert health["libraries"]["up"]["description"] == "Upstream words."
