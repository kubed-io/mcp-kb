"""The generated OpenAPI document.

Built from nothing but literal response schemas -- there is no tool schema to
derive a request body from, unlike the sibling `selenium-flow` -- so what
these tests hold the document against is `routes.py` itself: the paths it
actually registers, and the shape of what a real request to each of them
returns.
"""

import httpx
import pytest
import yaml

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.spec import build_spec
from tests.conftest import make_config

pytestmark = pytest.mark.unit


@pytest.fixture
def cache(tmp_path_factory):
    return tmp_path_factory.mktemp("cache")


@pytest.fixture
def knowledge_base(skills_dir, cache):
    return KnowledgeBase(make_config(skills_dir), cache)


def test_it_is_openapi_31():
    assert build_spec()["openapi"] == "3.1.0"


def test_the_document_validates():
    """Validated with a real validator, not just eyeballed."""
    validator = pytest.importorskip("openapi_spec_validator")
    validator.validate(build_spec())


def test_every_registered_route_except_openapi_yaml_is_documented(knowledge_base):
    """The path list comes from the LIVE app, not a second hand-kept list.

    `mcp._additional_http_routes` is exactly what `@mcp.custom_route`
    populates in `routes.py`, so a third endpoint added there with no
    matching entry in `build_spec()` fails this test -- proved by adding one
    temporarily (`@mcp.custom_route("/throwaway", methods=["GET"])`) and
    watching it fail before removing it again.
    """
    registered = {route.path for route in knowledge_base.mcp._additional_http_routes}
    assert registered - {"/openapi.yaml"} == set(build_spec()["paths"])


async def test_the_served_document_equals_the_built_one(knowledge_base):
    transport = httpx.ASGITransport(app=knowledge_base.mcp.http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://kb") as http:
        response = await http.get("/openapi.yaml")
    assert response.status_code == 200
    assert "yaml" in response.headers["content-type"]
    assert yaml.safe_load(response.text) == build_spec()


def test_source_status_documents_every_field_report_can_produce():
    """Every key `snapshot.status[name]` or `snapshot.stats(name)` can add."""
    props = set(build_spec()["components"]["schemas"]["SourceStatus"]["properties"])
    assert props == {
        "status", "library", "skills", "prompts", "files", "built",
        "fingerprint", "live", "error", "revalidated", "fetched", "cooling",
    }


def test_health_documents_every_top_level_field():
    props = set(build_spec()["components"]["schemas"]["Health"]["properties"])
    assert props == {
        "status", "generation", "built", "libraries", "skills", "prompts", "sources",
    }


def test_reindex_extends_health_with_rebuilt():
    """`/reindex` answers with `/health`'s own body plus one field."""
    reindex = build_spec()["components"]["schemas"]["Reindex"]
    ref, extra = reindex["allOf"]
    assert ref == {"$ref": "#/components/schemas/Health"}
    assert set(extra["properties"]) == {"rebuilt"}


def test_reindex_500_uses_the_error_schema():
    op = build_spec()["paths"]["/reindex"]["post"]
    schema = op["responses"]["500"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/ReindexError"}


def test_info_is_drawn_from_pyproject():
    from importlib.metadata import metadata

    spec = build_spec()
    dist = metadata("kubed-mcp-kb")
    assert spec["info"]["description"] == dist["Summary"]
    assert spec["info"]["version"] == dist["Version"]
    assert spec["info"]["title"] == "mcp-kb"


def test_servers_are_the_in_cluster_service_and_localhost():
    urls = {s["url"] for s in build_spec()["servers"]}
    assert urls == {"http://mcp-kb.flow.svc.cluster.local:8000", "http://localhost:8000"}


def test_operations_are_tagged_and_carry_a_summary():
    for path, ops in build_spec()["paths"].items():
        for method, op in ops.items():
            assert op["tags"] == ["ops"], f"{method} {path}"
            assert op["summary"], f"{method} {path} has no summary"
            assert op["operationId"], f"{method} {path} has no operationId"


async def test_a_real_health_response_matches_the_documented_fields(knowledge_base):
    """The anti-drift guarantee: what `report()` actually returns is exactly
    what `Health` and `SourceStatus` say it may."""
    transport = httpx.ASGITransport(app=knowledge_base.mcp.http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://kb") as http:
        body = (await http.get("/health")).json()

    schemas = build_spec()["components"]["schemas"]
    assert set(body) == set(schemas["Health"]["properties"])
    for info in body["sources"].values():
        assert set(info) <= set(schemas["SourceStatus"]["properties"])


async def test_a_real_reindex_response_matches_the_documented_fields(knowledge_base):
    transport = httpx.ASGITransport(app=knowledge_base.mcp.http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://kb") as http:
        body = (await http.post("/reindex")).json()

    schemas = build_spec()["components"]["schemas"]
    documented = set(schemas["Health"]["properties"]) | set(
        schemas["Reindex"]["allOf"][1]["properties"]
    )
    assert set(body) == documented
