"""``resources/list``: the plugin layer's ``SKILL.md`` rows, plus kb's ``_files.md``.

kubed-mcp lists what the request's ``Listed`` setting chooses, one ``SKILL.md``
row per served skill by default; kb adds one ``_files.md`` row per library with a
library file in scope, under every setting, because that resource is its own.
"""

import json

import pytest
from fastmcp import Client

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.app import create_app
from kubed.mcp_kb.catalogue.skills import SkillIndex
from kubed.mcp_kb.catalogue.uris import Catalogue, uri_for
from kubed.mcp_kb.config import Config, load
from kubed.mcp_kb.mcp.pins import what_is_wrong
from kubed.mcp_kb.mcp.scope import Scope
from tests.conftest import (
    build_library_files,
    http_client,
    load_all_skills,
    make_config,
    serve_http,
    server_of,
)
from tests.test_server import delivery
from tests.test_skills_extension import request

FILES_LIBRARIES = ["deepsource"]


@pytest.fixture(scope="module")
def served(skills_dir_module, prompts_dir_module, tmp_path_factory):
    kb = KnowledgeBase(
        make_config(skills_dir_module, prompts_dir_module),
        tmp_path_factory.mktemp("cache"),
    )
    with serve_http(kb) as url:
        yield kb, url


@pytest.fixture
def server_url(served):
    return served[1]


async def resource_uris(url, sent=None):
    """The URIs ``resources/list`` returns; ``sent`` is headers or a query string."""
    if isinstance(sent, str):
        url, sent = url + sent, None
    async with http_client(url, sent) as client:
        return [str(r.uri) for r in await client.list_resources()]


@pytest.mark.unit
def test_entries_are_files_md_alone(skills_dir):
    skills = load_all_skills(skills_dir)
    catalogue = Catalogue(SkillIndex(skills), build_library_files(skills_dir))
    assert [e.uri for e in catalogue.entries()] == ["skill://deepsource/_files.md"]
    row = catalogue.entries()[0]
    assert row.name == "deepsource/_files.md"
    assert row.mime_type == "text/markdown"
    assert row.tags == ("deepsource", "index")
    assert catalogue.entries(Scope.parse(library="nope")) == []


@pytest.mark.integration
async def test_the_default_listing_is_a_skill_md_row_per_skill(served):
    kb, url = served
    uris = await resource_uris(url)
    skills = {uri_for(s) for s in kb.snapshot.catalogue.visible_skills()}
    assert skills
    assert {u for u in uris if u.endswith("/SKILL.md")} == skills
    assert not [u for u in uris if u.endswith("_index.md")]
    assert len(uris) == len(set(uris))
    for lib in FILES_LIBRARIES:
        assert f"skill://{lib}/_files.md" in uris


@pytest.mark.integration
@pytest.mark.parametrize("prefix", [None, "kb+"])
async def test_a_tools_client_reads_every_listed_row(server_url, prefix):
    headers = {"Kb-Resources": "off"}
    if prefix:
        headers["Kb-Resource-Prefix"] = prefix
    async with http_client(server_url, headers) as client:
        listed = await client.call_tool("list_resources", {})
        rows = json.loads(listed.content[0].text)["resources"]
        assert rows
        for row in rows:
            assert row["uri"].startswith((prefix or "") + "skill://")
            result = await client.call_tool("read_resource", {"uri": row["uri"]})
            assert not result.is_error, row


@pytest.mark.integration
@pytest.mark.parametrize(
    "sent", [{"Kb-Listed": "none"}, {"X-MCP-Listed": "none"}, "?listed=none"]
)
async def test_listed_chooses_the_plugin_rows_and_keeps_files_md(server_url, sent):
    uris = await resource_uris(server_url, sent)
    assert uris == [f"skill://{lib}/_files.md" for lib in FILES_LIBRARIES]


@pytest.mark.integration
@pytest.mark.parametrize(
    "sent", [{"Kb-Listed": "prompts"}, {"X-MCP-Listed": "prompts"}, "?listed=prompts"]
)
async def test_listed_prompts_lists_prompt_files_and_files_md(server_url, sent):
    uris = await resource_uris(server_url, sent)
    assert uris
    assert all(u.endswith("/_files.md") or u.startswith("prompts://") for u in uris)
    assert any(u.startswith("prompts://") for u in uris)
    assert f"skill://{FILES_LIBRARIES[0]}/_files.md" in uris
    async with http_client(server_url, sent if isinstance(sent, dict) else None) as c:
        for uri in uris:
            if uri.startswith("prompts://"):
                assert (await c.read_resource(uri))[0].text is not None


@pytest.mark.integration
async def test_kb_listing_does_nothing(server_url):
    plain = await resource_uris(server_url)
    for sent in (
        {"Kb-Listing": "full"},
        {"X-Skill-Listing": "full"},
        "?listing=full",
        "?skills=full",
    ):
        assert await resource_uris(server_url, sent) == plain


@pytest.mark.integration
async def test_a_files_only_library_is_served_its_files_md(tmp_path):
    root = tmp_path / "docs"
    (root / "guides").mkdir(parents=True)
    (root / "guides" / "a.md").write_text("guide\n")
    config = Config.model_validate(
        {
            "plugins": [
                {
                    "name": "docs",
                    "source": f"file://{root}",
                    "skills": [],
                    "files": ["guides/*.md"],
                }
            ],
            "libraries": [{"name": "docs", "plugins": ["docs"]}],
        }
    )
    kb = KnowledgeBase(config, tmp_path / "cache")
    with serve_http(kb) as url:
        assert await resource_uris(url, "?library=docs") == ["skill://docs/_files.md"]


def _plugin(root, name, tag, link=None):
    skill = root / name / "only"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: only\ndescription: The only skill.\n---\n\n# only\n"
    )
    if link:
        # A symlink: the plugin layer refuses the skill holding it (N14).
        (skill / link).symlink_to(skill / "SKILL.md")
    return {
        "name": name,
        "source": f"file://{root / name}",
        "tags": [tag],
        "skills": ["."],
        "prompts": [],
        "files": [],
    }


@pytest.mark.unit
def test_the_pin_still_counts_served_skills(tmp_path):
    plugins = [
        _plugin(tmp_path, "good", "s"),
        _plugin(tmp_path, "bad", "t", "ref.md"),
    ]
    config = Config.model_validate(
        {
            "plugins": plugins,
            "libraries": [{"name": "lib", "plugins": ["good", "bad"]}],
        }
    )
    kb = KnowledgeBase(config, tmp_path / "cache")
    server_of(kb)  # the parity guard narrows the catalogue as the app stages it
    assert what_is_wrong(Scope.parse(tags="s"), config, kb.snapshot) is None
    problem = what_is_wrong(Scope.parse(tags="t"), config, kb.snapshot)
    assert problem == (
        "The scope names things that exist, but nothing in any library carries"
        " the combination: tags t."
    )


GAMMA = "skill://deepsource/plugin-a/gamma/SKILL.md"
DELTA = "skill://deepsource/plugin-b/delta/SKILL.md"
ALPHA = "skill://flatsource/alpha/SKILL.md"
BETA = "skill://flatsource/beta/SKILL.md"
# SKL-64: deepsource then flatsource, plugin order, then name.
ORDER = [GAMMA, DELTA, ALPHA, BETA]

# (headers, query, the skills listed)
MAX_INPUTS = [
    ({}, "", ORDER),
    ({"Kb-Max": "3"}, "", ORDER[:3]),  # within a plugin, by name: beta is cut
    ({"Kb-Max": "1"}, "", ORDER[:1]),  # by plugin order: delta is cut
    ({"X-MCP-Max": "2"}, "", ORDER[:2]),
    ({}, "?max=2", ORDER[:2]),
    ({"Kb-Max": "3"}, "?max=1", ORDER[:3]),  # a header beats the query (SCP-5)
    ({"Kb-Max": "2", "X-MCP-Max": "3"}, "", ORDER[:2]),  # Kb- first (DLV-16)
    ({"Kb-Max": "0"}, "?max=3", ORDER[:3]),  # an invalid value falls through
    ({"Kb-Max": "abc"}, "", ORDER),
    ({"Kb-Max": "4"}, "", ORDER),  # exactly the count: nothing is cut
    ({"Kb-Max": "ALL"}, "", ORDER),
    (
        {"Kb-Library": "flatsource", "Kb-Max": "1"},
        "",
        [ALPHA],
    ),  # a scope cuts what it admits
]


@pytest.mark.integration
@pytest.mark.parametrize(("headers", "query", "listed"), MAX_INPUTS)
async def test_the_max_cuts_both_listings_alike(server_url, headers, query, listed):
    async with http_client(server_url + query, headers) as client:
        rows = [str(r.uri) for r in await client.list_resources()]
        entries = (await request(client, "skills/list"))["skills"]
    assert {u for u in rows if u.endswith("/SKILL.md")} == set(listed)
    assert {e["uri"] for e in entries} == set(listed)
    # _files.md is kb's own row, which the max never cuts
    if headers.get("Kb-Library") != "flatsource":
        assert "skill://deepsource/_files.md" in rows


@pytest.mark.integration
async def test_a_cut_skill_still_gets_reads_and_is_indexed(server_url):
    folders = {
        DELTA: "skill://deepsource/plugin-b/_index.md",
        ALPHA: "skill://flatsource/_index.md",
        BETA: "skill://flatsource/_index.md",
    }
    async with http_client(server_url, {"Kb-Max": "1"}) as client:
        entries = (await request(client, "skills/list"))["skills"]
        assert {e["uri"] for e in entries} == {GAMMA}
        for uri, index in folders.items():
            got = await request(client, "skills/get", uri=uri)
            assert got["skill"]["uri"] == uri
            assert (await client.read_resource(uri))[0].text
            assert uri in (await client.read_resource(index))[0].text
            directory = uri.removesuffix("/SKILL.md")
            parent = directory.rsplit("/", 1)[0] + "/_index.json"
            assert directory in (await client.read_resource(parent))[0].text


@pytest.mark.integration
async def test_the_tool_mirror_is_capped_alike(server_url):
    async with http_client(
        server_url, {"Kb-Resources": "off", "Kb-Max": "3"}
    ) as client:
        result = await client.call_tool("list_resources", {})
    uris = [r["uri"] for r in json.loads(result.content[0].text)["resources"]]
    assert {u for u in uris if u.endswith("/SKILL.md")} == set(ORDER[:3])
    assert "skill://deepsource/_files.md" in uris


@pytest.mark.integration
async def test_local_lists_none_and_cuts_none(server_url):
    async with http_client(server_url, {"Kb-Via": "local", "Kb-Max": "1"}) as client:
        assert (await request(client, "skills/list"))["skills"] == []
        assert (await request(client, "skills/get", uri=BETA))["skill"]["uri"] == BETA


@pytest.mark.integration
@pytest.mark.parametrize(
    ("headers", "echoed"), [({}, 100), ({"Kb-Max": "3"}, 3), ({"Kb-Max": "all"}, "all")]
)
@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_the_echo_says_the_max(server_url, headers, echoed, mode):
    """HTTP-42."""
    from fastmcp import Client as MCPClient
    from fastmcp.client.transports import StreamableHttpTransport

    client = MCPClient(StreamableHttpTransport(server_url, headers=headers), mode=mode)
    async with client:
        assert (await delivery(client, mode))["max"] == echoed


def operator_app(skills_dir, tmp_path, how, max_, reverse=False):
    """An app over the synthetic tree, its max set as an operator does: env or flag."""
    declared = make_config(skills_dir).model_dump(mode="json", exclude_none=True)
    for library in declared["libraries"]:
        library.pop("list_skills", None)  # a computed field, not a config item
    if reverse:
        declared["libraries"].reverse()
    path = tmp_path / "config.yaml"
    path.write_text(json.dumps(declared))
    argv, environ = ["--config-file", str(path)], {}
    if how == "env":
        environ["DELIVERY_MAX"] = str(max_)
    else:
        argv += ["--delivery-max", str(max_)]
    loaded = load(argv, environ=environ)
    return create_app(KnowledgeBase(loaded.config, tmp_path / "cache"), loaded=loaded)


async def listed_by(app):
    async with Client(app.server) as client:
        return {e["uri"] for e in (await request(client, "skills/list"))["skills"]}


@pytest.mark.unit
@pytest.mark.parametrize("how", ["env", "flag"])
async def test_delivery_max_sets_the_servers_cap(skills_dir, tmp_path, how):
    app = operator_app(skills_dir, tmp_path, how, 2)
    assert await listed_by(app) == {GAMMA, DELTA}


@pytest.mark.unit
@pytest.mark.parametrize("how", ["env", "flag"])
async def test_the_config_order_of_libraries_decides_what_a_cap_keeps(
    skills_dir, tmp_path, how
):
    """SKL-64: flatsource declared first is the library whose skills are kept."""
    app = operator_app(skills_dir, tmp_path, how, 1, reverse=True)
    assert await listed_by(app) == {ALPHA}
