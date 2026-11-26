"""``resources/list``: the plugin layer's ``SKILL.md`` rows, plus kb's ``_files.md``.

kubed-mcp lists what the request's ``Listed`` setting chooses, one ``SKILL.md``
row per served skill by default; kb adds one ``_files.md`` row per library with a
library file in scope, under every setting, because that resource is its own.
"""

import json

import pytest

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.catalogue.skills import SkillIndex
from kubed.mcp_kb.catalogue.uris import Catalogue, uri_for
from kubed.mcp_kb.config import Config
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


def _plugin(root, name, tag, skill_extra=None):
    skill = root / name / "only"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: only\ndescription: The only skill.\n---\n\n# only\n"
    )
    if skill_extra:
        path = skill / skill_extra
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
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
        _plugin(tmp_path, "bad", "t", "assets/.gitkeep"),
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
