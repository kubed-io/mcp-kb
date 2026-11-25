"""Skills discovery and integrity through real MCP requests, in both eras.

The Skills extension is FastMCP's (through kubed-mcp), over the catalogue
``SkillCatalogue`` builds from kb's ``Catalogue``: these check what kb puts in
it and that every surface agrees about it.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from fastmcp import Client
from fastmcp.skills import SkillsClientExtension
from kubed.mcp.protocol import MCPError, RequestParams, types
from pydantic import ConfigDict, TypeAdapter

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.catalogue.addressing import Addressing
from kubed.mcp_kb.mcp.request import EXTENSION_ID
from kubed.mcp_kb.mcp.scope import EVERYTHING, Scope
from kubed.mcp_kb.mcp.skill_catalogue import SkillCatalogue
from tests.conftest import DEEP_YAML, make_config, server_of
from tests.test_header_scope import server_url  # noqa: F401 - shared HTTP fixture

ALPHA = "skill://flatsource/alpha/SKILL.md"


class ExtensionParams(RequestParams):
    model_config = ConfigDict(extra="allow")


async def request(client, method, **params):
    return await client.session.send_request(
        types.Request(method=method, params=ExtensionParams(**params)), TypeAdapter(dict)
    )


def _sha(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_discovery_get_and_verified_reads(skills_dir, mode):
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    async with Client(server_of(server), mode=mode) as client:
        caps = client.session.server_capabilities
        assert caps.resources is not None
        assert caps.extensions[EXTENSION_ID] == {"directoryRead": True}
        listing = await request(client, "skills/list")
        assert listing["resultType"] == "complete"
        assert listing["ttlMs"] == 0
        assert listing["cacheScope"] == "private"
        assert len(listing["skills"]) == 4
        assert len(await client.list_resources()) < len(listing["skills"]) + 4
        assert await client.list_tools() == []
        for entry in listing["skills"]:
            got = await request(client, "skills/get", uri=entry["uri"])
            assert got["skill"] == entry
            assert entry["resources"]
            for resource in entry["resources"]:
                result = await client.read_resource(resource["uri"])
                data = result[0].text.encode("utf-8")
                assert resource["size"] == len(data)
                assert resource["digest"] == f"sha256:{hashlib.sha256(data).hexdigest()}"


async def test_fastmcps_client_reads_every_skill_and_verifies_it(skills_dir):
    """``read_skill`` checks every file against the entry's digest (MD-59)."""
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    async with Client(server_of(server), extensions=[SkillsClientExtension()]) as client:
        for entry in await client.list_skills():
            skill = await client.read_skill(entry.uri)
            assert "SKILL.md" in skill.files


async def test_the_manifest_the_entry_and_the_read_are_one_set_of_bytes(skills_dir):
    """SKL-24 and SKL-47: the ``_manifest`` describes the bytes served."""
    path = skills_dir / "flatsource" / "alpha"
    (path / "SKILL.md").write_bytes(
        b"---\r\nname: alpha\r\ndescription: |\r\n  First line.\r\n"
        b"  Second line.\r\nmetadata:\r\n  audience: [one, two]\r\n---\r\n"
        b"Read ${CLAUDE_SKILL_DIR}/guide.md from ${CLAUDE_PLUGIN_ROOT}.\r\n"
    )
    (path / "guide.md").write_bytes("Café\r\n".encode())
    (path / ".env").write_text("secret", encoding="utf-8")
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    async with Client(server_of(server)) as client:
        entry = (await request(client, "skills/get", uri=ALPHA))["skill"]
        assert entry["frontmatter"]["description"] == "First line.\nSecond line.\n"
        assert entry["frontmatter"]["metadata"] == {"audience": ["one", "two"]}
        assert not any(r["uri"].endswith("/.env") for r in entry["resources"])
        manifest = json.loads(
            (await client.read_resource("skill://flatsource/alpha/_manifest"))[0].text
        )
        assert manifest["skill"] == "flatsource/alpha"
        assert all(set(f) == {"path", "size", "hash"} for f in manifest["files"])
        hashes = {f"skill://flatsource/alpha/{f['path']}": f for f in manifest["files"]}
        assert set(hashes) == {r["uri"] for r in entry["resources"]}
        for resource in entry["resources"]:
            text = (await client.read_resource(resource["uri"]))[0].text
            assert "${CLAUDE_" not in text
            assert "\r" not in text
            assert resource["digest"] == _sha(text) == hashes[resource["uri"]]["hash"]
            assert resource["size"] == len(text.encode()) == hashes[resource["uri"]]["size"]


async def test_direct_get_needs_no_listing_and_follows_refresh(skills_dir):
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    async with Client(server_of(server)) as client:
        before = (await request(client, "skills/get", uri=ALPHA))["skill"]
        path = skills_dir / "flatsource" / "alpha" / "SKILL.md"
        path.write_text(path.read_text() + "\nUpdated instructions.\n", encoding="utf-8")
        server.refresh(force=True)
        after = (await request(client, "skills/get", uri=ALPHA))["skill"]
        assert before["resources"] != after["resources"]


async def test_an_unknown_skill_is_fastmcps_error(skills_dir):
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    async with Client(server_of(server)) as client:
        for uri in ("skill://flatsource/nope/SKILL.md", "skill://flatsource/_index.md"):
            with pytest.raises(MCPError) as error:
                await request(client, "skills/get", uri=uri)
            assert error.value.code == -32602
            assert str(error.value) == f"Unknown skill URI: {uri}"


async def test_a_skill_folder_is_a_directory_with_its_indexes(skills_dir):
    """SEP-2640 directory resources inside a skill, and the two index files."""
    (skills_dir / "flatsource" / "alpha" / "references").mkdir()
    (skills_dir / "flatsource" / "alpha" / "references" / "a.md").write_text("# A\n")
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    root = "skill://flatsource/alpha"
    async with Client(server_of(server)) as client:
        listed = await request(client, "resources/directory/read", uri=root)
        uris = [r["uri"] for r in listed["resources"]]
        assert uris == [f"{root}/SKILL.md", f"{root}/references"]
        inner = await request(client, "resources/directory/read", uri=f"{root}/references")
        assert [r["uri"] for r in inner["resources"]] == [f"{root}/references/a.md"]
        index = json.loads((await client.read_resource(f"{root}/_index.json"))[0].text)
        assert index == listed["resources"]
        assert f"{root}/references/a.md: A" in (
            await client.read_resource(f"{root}/references/_index.md")
        )[0].text
        with pytest.raises(MCPError, match=r"references/_index\.md to list it"):
            await client.read_resource(f"{root}/references")
        with pytest.raises(MCPError, match="Directory not found"):
            await request(client, "resources/directory/read", uri=f"{root}/SKILL.md")


async def test_an_invalid_skill_is_not_served_at_all(skills_dir):
    """MD-56: refused by FastMCP, so neither read, listed nor offered."""
    path = skills_dir / "flatsource" / "alpha" / "SKILL.md"
    path.write_text("---\nname: alpha\n---\nMissing description.\n", encoding="utf-8")
    (path.parent / "notes.md").write_text("notes\n")
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    async with Client(server_of(server)) as client:
        listing = await request(client, "skills/list")
        assert len(listing["skills"]) == 3
        for uri in (ALPHA, "skill://flatsource/alpha/notes.md"):
            with pytest.raises(MCPError, match="Resource not found"):
                await client.read_resource(uri)
        with pytest.raises(MCPError):
            await request(client, "skills/get", uri=ALPHA)
        index = (await client.read_resource("skill://flatsource/_index.md"))[0].text
        assert "alpha" not in index
        full = await client.list_resources()
        assert all("alpha" not in str(r.uri) for r in full)


async def test_frontmatter_too_deep_for_the_parser_is_not_served(skills_dir):
    path = skills_dir / "flatsource" / "alpha" / "SKILL.md"
    path.write_text(
        f"---\nname: alpha\ndescription: d\nx: {DEEP_YAML}\n---\nBody.\n",
        encoding="utf-8",
    )
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    async with Client(server_of(server)) as client:
        listing = await request(client, "skills/list")
        assert ALPHA not in {s["uri"] for s in listing["skills"]}
        with pytest.raises(MCPError, match="Resource not found"):
            await client.read_resource(ALPHA)


def test_a_skill_inside_a_skill_is_refused_and_its_files_are_the_outers(tmp_path):
    from kubed.mcp_kb.catalogue import harvest
    from kubed.mcp_kb.catalogue.skills import LibraryFiles, SkillIndex, load_skills
    from kubed.mcp_kb.catalogue.uris import Catalogue
    from tests.conftest import fake_plugin

    root = tmp_path / "flatsource"
    outer = root / "skills" / "outer"
    for path, name in ((outer, "outer"), (outer / "inner", "inner")):
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n")
    # Nothing below a skill is searched, so only a folder declared in its own
    # right puts one skill inside another.
    dirs = harvest.skill_dirs(root, ("./skills/outer/inner",))
    plugin = fake_plugin("flatsource", root)
    files = LibraryFiles()
    files.add("flatsource", root, [], dirs, plugin=plugin)
    catalogue = Catalogue(
        SkillIndex(load_skills(dirs, library="flatsource", plugin=plugin, root=root)),
        files,
    )
    skills = SkillCatalogue(lambda: catalogue)

    built = skills.skills()

    assert list(built) == ["flatsource/outer"]
    assert set(built["flatsource/outer"].files) == {"SKILL.md", "inner/SKILL.md"}
    assert skills.refused() == {
        "flatsource/outer/inner": "it sits inside the skill at flatsource/outer"
    }
    assert "inner" not in skills.catalogue().read("skill://flatsource/_index.md")


def test_a_catalogue_is_built_once_per_scope_and_prefix(skills_dir):
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    skills = SkillCatalogue(lambda: server.snapshot.catalogue)
    flat = Scope("flatsource")
    prefixed = Addressing.parse("kb+")

    first = skills.skills(flat)

    assert skills.skills(flat) is first
    assert list(first) == ["flatsource/alpha", "flatsource/beta"]
    assert skills.skills(EVERYTHING, prefixed) is not skills.skills(EVERYTHING)
    # A file a key does not rewrite is the same bytes object in every key.
    alpha = skills.skills(EVERYTHING)["flatsource/alpha"]
    assert first["flatsource/alpha"] is alpha
    server.refresh(force=True)
    assert skills.skills(flat) is not first


def test_a_prefix_that_breaks_a_skill_drops_it_under_that_prefix_only(skills_dir):
    """A rewrite can take a description past 1024 characters."""
    words = "skill://flatsource " + "x" * (1022 - len("skill://flatsource "))
    (skills_dir / "flatsource" / "alpha" / "SKILL.md").write_text(
        f"---\nname: alpha\ndescription: {words}\n---\nBody.\n"
    )
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    skills = SkillCatalogue(lambda: server.snapshot.catalogue)

    assert "flatsource/alpha" in skills.skills()
    assert "flatsource/alpha" not in skills.skills(EVERYTHING, Addressing.parse("kb+"))


@pytest.mark.integration
async def test_http_scope_and_header_precedence(server_url):  # noqa: F811
    from fastmcp.client.transports import StreamableHttpTransport

    transport = StreamableHttpTransport(
        f"{server_url}?library=deepsource",
        headers={"Kb-Library": "flatsource"},
    )
    async with Client(transport) as client:
        listing = await request(client, "skills/list")
        assert len(listing["skills"]) == 2
        assert all(s["uri"].startswith("skill://flatsource/") for s in listing["skills"])
        for uri in ("skill://deepsource/plugin-a/gamma/SKILL.md", "skill://missing/nope/SKILL.md"):
            with pytest.raises(MCPError) as error:
                await request(client, "skills/get", uri=uri)
            # Out of scope and absent fail identically (SCP-24).
            assert (error.value.code, str(error.value)) == (
                -32602,
                f"Unknown skill URI: {uri}",
            )
    with pytest.raises(MCPError, match="no such library"):
        async with Client(f"{server_url}?library=missing") as client:
            await request(client, "skills/list")


@pytest.mark.integration
async def test_a_prefixed_address_resolves_in_skills_get_and_reads(server_url):  # noqa: F811
    """SKL-42: the request's own prefix is taken off before any provider looks."""
    from fastmcp.client.transports import StreamableHttpTransport

    headers = {"Kb-Resource-Prefix": "kb+"}
    async with Client(StreamableHttpTransport(server_url, headers=headers)) as client:
        plain = (await request(client, "skills/get", uri=ALPHA))["skill"]
        prefixed = (await request(client, "skills/get", uri=f"kb+{ALPHA}"))["skill"]
        assert prefixed == plain
        assert plain["uri"] == ALPHA
        for resource in plain["resources"]:
            read = await client.read_resource(f"kb+{resource['uri']}")
            assert _sha(read[0].text) == resource["digest"]
        listed = await request(
            client, "resources/directory/read", uri="kb+skill://flatsource/alpha"
        )
        assert listed["resources"][0]["uri"] == ALPHA
    async with Client(StreamableHttpTransport(server_url)) as client:
        with pytest.raises(MCPError, match="Unknown skill URI"):
            await request(client, "skills/get", uri=f"kb+{ALPHA}")


SCOPES = (
    {},
    {"Kb-Library": "flatsource"},
    {"Kb-Library": "deepsource"},
    {"Kb-Tag": "deep"},
    {"Kb-Resource-Prefix": "kb+"},
)


@pytest.mark.integration
@pytest.mark.parametrize("headers", SCOPES)
async def test_every_child_a_directory_names_is_readable(server_url, headers):  # noqa: F811
    """MD-57: listed is a subset of readable, under every scope."""
    from fastmcp.client.transports import StreamableHttpTransport

    async with Client(StreamableHttpTransport(server_url, headers=headers)) as client:
        todo = sorted(
            {"/".join(str(r.uri).split("/")[:3]) for r in await client.list_resources()}
        )
        seen = 0
        while todo:
            folder = todo.pop()
            listed = await request(client, "resources/directory/read", uri=folder)
            index = json.loads((await client.read_resource(f"{folder}/_index.json"))[0].text)
            assert index == listed["resources"]
            for child in listed["resources"]:
                seen += 1
                if child["mimeType"] == "inode/directory":
                    todo.append(child["uri"])
                else:
                    assert (await client.read_resource(child["uri"]))[0].text is not None
        assert seen
        for absent in ("skill://nope", "skill://flatsource/nope"):
            with pytest.raises(MCPError, match="Directory not found"):
                await request(client, "resources/directory/read", uri=absent)


@pytest.mark.integration
async def test_out_of_scope_folders_fail_as_absent_ones_do(server_url):  # noqa: F811
    """SCP-24, for the directory surfaces too."""
    from fastmcp.client.transports import StreamableHttpTransport

    headers = {"Kb-Library": "flatsource"}
    async with Client(StreamableHttpTransport(server_url, headers=headers)) as client:
        for uri in ("skill://deepsource", "skill://deepsource/plugin-a/gamma"):
            with pytest.raises(MCPError) as hidden:
                await request(client, "resources/directory/read", uri=uri)
            assert str(hidden.value) == "Directory not found"
            with pytest.raises(MCPError) as hidden:
                await client.read_resource(f"{uri}/_index.json")
            assert str(hidden.value) == f"Resource not found: '{uri}/_index.json'"


@pytest.mark.integration
async def test_the_mirror_reads_what_resources_read_does(server_url):  # noqa: F811
    from fastmcp.client.transports import StreamableHttpTransport

    headers = {"Kb-Resource-Prefix": "kb+"}
    url = f"{server_url}?resources=off"
    async with Client(StreamableHttpTransport(url, headers=headers)) as client:
        for uri in (
            "skill://flatsource/alpha/_manifest",
            "kb+skill://flatsource/alpha/SKILL.md",
            "skill://flatsource/alpha/_index.md",
            "skill://deepsource/_index.json",
            "skill://deepsource/shared/guide.md",
        ):
            tool = await client.call_tool("read_resource", {"uri": uri})
            read = await client.read_resource(uri)
            assert tool.content[0].text == read[0].text
        index = (await client.read_resource("skill://flatsource/alpha/_index.md"))[0].text
        assert index.startswith("kb+skill://flatsource/alpha/SKILL.md: ")


def _serve(knowledge_base):
    """``knowledge_base`` on a loopback port, for headers: a context manager."""
    import contextlib
    import threading

    import uvicorn

    from tests.test_header_scope import _free_port

    @contextlib.contextmanager
    def serving():
        port = _free_port()
        app = server_of(knowledge_base).http_app()
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            threading.Event().wait(0.05)
        try:
            yield f"http://127.0.0.1:{port}/mcp"
        finally:
            server.should_exit = True
            thread.join(timeout=5)

    return serving()


async def _named(client) -> set[str]:
    """Every skill:// URI a listing, an entry, an index or a directory names."""
    import re

    named = {str(row.uri) for row in await client.list_resources()}
    for row in (await request(client, "skills/list"))["skills"]:
        named.update(r["uri"] for r in row["resources"])
    indexes = [u for u in named if u.endswith(("/_index.md", "/_files.md"))]
    folders = sorted({"/".join(u.split("/")[:3]) for u in named})
    while indexes:
        text = (await client.read_resource(indexes.pop()))[0].text
        for found in re.findall(r"(?:kb\+)?skill://[^\s`)]+?(?=[:\s`)]|$)", text):
            if found not in named:
                named.add(found)
                if found.endswith(("/_index.md", "/_files.md")):
                    indexes.append(found)
    while folders:
        listed = await request(client, "resources/directory/read", uri=folders.pop())
        for child in listed["resources"]:
            named.add(child["uri"])
            if child["mimeType"] == "inode/directory":
                folders.append(child["uri"])
    return {u for u in named if "/" in u.split("://", 1)[1] and not _is_dir(u, named)}


def _is_dir(uri: str, named: set[str]) -> bool:
    """A directory, which serves nothing: some other named URI sits under it."""
    return any(other.startswith(f"{uri}/") for other in named)


async def test_a_skill_one_prefix_cannot_build_is_named_nowhere_under_it(skills_dir):
    """MD-57 per key: listed is a subset of readable under the prefix too."""
    from fastmcp.client.transports import StreamableHttpTransport

    words = "skill://flatsource " + "x" * (1022 - len("skill://flatsource "))
    (skills_dir / "flatsource" / "alpha" / "SKILL.md").write_text(
        f"---\nname: alpha\ndescription: {words}\n---\nBody.\n"
    )
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    with _serve(server) as url:
        for headers in (
            {"Kb-Resource-Prefix": "kb+", "Kb-Listing": "full"},
            {"Kb-Resource-Prefix": "kb+"},
            {"Kb-Listing": "full"},
        ):
            transport = StreamableHttpTransport(url, headers=headers)
            async with Client(transport) as client:
                named = await _named(client)
                prefixed = "Kb-Resource-Prefix" in headers
                assert any("flatsource/alpha" in u for u in named) is not prefixed
                for uri in named:
                    if (await client.read_resource(uri))[0].text is None:
                        pytest.fail(f"{uri} is named but does not read")


async def test_a_prompt_names_no_skill_that_is_not_served(tmp_path):
    """SKL-45 for prompt bodies: a name that resolves to a refused skill is
    left as written, as one to an absent skill is (SKL-55)."""
    from kubed.mcp_kb.config import Config

    root = tmp_path / "kit"
    for name, head in (("good", "description: Fine."), ("bad", "")):
        (root / "skills" / name).mkdir(parents=True)
        (root / "skills" / name / "SKILL.md").write_text(
            f"---\nname: {name}\n{head}\n---\nBody.\n"
        )
    (root / "commands").mkdir()
    (root / "commands" / "use.md").write_text(
        "---\ndescription: Use them.\n---\nUse kit:good, then kit:bad.\n"
    )
    config = Config.model_validate(
        {
            "plugins": [{"name": "kit", "source": f"file://{root}"}],
            "libraries": [{"name": "lib", "plugins": ["kit"]}],
        }
    )
    server = KnowledgeBase(config, tmp_path / "cache")
    async with Client(server_of(server)) as client:
        text = (await client.get_prompt("lib_use")).messages[0].content.text
        assert "skill://lib/good/SKILL.md" in text
        assert "kit:bad" in text
        assert "skill://lib/bad" not in text


def test_a_scope_whose_only_skills_are_refused_names_nothing(tmp_path):
    """RefuseEmptyScope counts what is served, not what was harvested."""
    from kubed.mcp_kb.config import Config
    from kubed.mcp_kb.mcp.pins import what_is_wrong

    for plugin, head in (("kit", "description: Fine."), ("odd", "")):
        path = tmp_path / plugin / "skills" / plugin
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(f"---\nname: {plugin}\n{head}\n---\nBody.\n")
    config = Config.model_validate(
        {
            "plugins": [
                {"name": p, "source": f"file://{tmp_path / p}", "tags": [p]}
                for p in ("kit", "odd")
            ],
            "libraries": [{"name": "lib", "plugins": ["kit", "odd"]}],
        }
    )
    server = KnowledgeBase(config, tmp_path / "cache")
    skills = SkillCatalogue(lambda: server.snapshot.catalogue)
    odd = Scope.parse(tags=["odd"])

    assert what_is_wrong(odd, config, server.snapshot) is None
    assert "nothing in any library carries" in what_is_wrong(
        odd, config, server.snapshot, skills.catalogue
    )
    kit = Scope.parse(tags=["kit"])
    assert what_is_wrong(kit, config, server.snapshot, skills.catalogue) is None


async def test_dot_segments_and_escaped_slashes_read_alike_everywhere(skills_dir):
    """SKL-13: ``..`` resolves for every read, an escaped ``/`` for none."""
    (skills_dir / "flatsource" / "alpha" / "references").mkdir()
    (skills_dir / "flatsource" / "alpha" / "references" / "a.md").write_text("# A\n")
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    root = "skill://flatsource/alpha"
    async with Client(server_of(server)) as client:
        up = await request(client, "resources/directory/read", uri=f"{root}/references/..")
        plain = await request(client, "resources/directory/read", uri=root)
        assert up["resources"] == plain["resources"]
        sibling = f"{root}/references/../../beta/SKILL.md"
        assert (await client.read_resource(sibling))[0].text
        for escaped in ("skill://flatsource%2Falpha/SKILL.md", f"{root}%2fSKILL.md"):
            with pytest.raises(MCPError, match="Resource not found"):
                await client.read_resource(escaped)
        miss = await client.call_tool(
            "read_resource", {"uri": f"{root}/references"}, raise_on_error=False
        )
        assert miss.is_error
        assert f"read {root}/references/_index.md to list it" in miss.content[0].text
