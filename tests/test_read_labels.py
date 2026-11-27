"""A read kb answers itself is labelled in the call metrics by its kind, never its address.

kubed-mcp's read observer labels a ``resources/read`` point with the ``uri_template`` of
the template the server matches for the URI, else the URI on a success (CFG-21). kb's
indexes, ``_files.md``, library files and plugin-root fallbacks are answered by
``CatalogueProvider``, which matches no template for a miss, so without a mark each
address read was a series of its own.

These drive kubed-mcp's own observer, with an in-memory metric reader, through the
server ``create_app`` builds with ``telemetry.otel`` on. The mark crosses FastMCP's
child tasks (its aggregate provider runs every provider in one), which a ``ContextVar``
set inside the provider would not, so a label here proves the holder survives them.
"""

from collections import Counter

import pytest
from fastmcp import Client
from kubed.mcp import load_config
from kubed.mcp.protocol import MCPError, VersionSpec
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.app import create_app
from kubed.mcp_kb.config import SECTIONS, SERVER_NAME, Telemetry
from kubed.mcp_kb.mcp.resources import (
    _SERVED,
    TEMPLATE_URI,
    CatalogueProvider,
    _Served,
    pattern_for,
)
from tests.conftest import _APPS, http_client, make_config, serve_http

pytestmark = pytest.mark.unit

DURATION = "mcp.server.operation.duration"
TEMPLATE = "mcp.resource.template"

LIBRARY_INDEX = "skill://{library}/_index.md"
FOLDER_INDEX = "skill://{library}/{folder}/_index.md"
LIBRARY_JSON = "skill://{library}/_index.json"
FOLDER_JSON = "skill://{library}/{folder}/_index.json"
FILES = "skill://{library}/_files.md"
PATH = "skill://{library}/{+path}"
LAYER_PATH = "skill://{library}/{path}"
PATTERNS = {LIBRARY_INDEX, FOLDER_INDEX, LIBRARY_JSON, FOLDER_JSON, FILES, PATH}

# Two addresses of each kind, in the synthetic tree: one series per kind, however
# many of its addresses are read.
KINDS = [
    (LIBRARY_INDEX, ["skill://flatsource/_index.md", "skill://deepsource/_index.md"]),
    (
        FOLDER_INDEX,
        ["skill://deepsource/plugin-a/_index.md", "skill://deepsource/plugin-b/_index.md"],
    ),
    (LIBRARY_JSON, ["skill://flatsource/_index.json", "skill://deepsource/_index.json"]),
    (
        FOLDER_JSON,
        [
            "skill://deepsource/plugin-a/_index.json",
            "skill://deepsource/plugin-b/_index.json",
        ],
    ),
    # Only deepsource lists files; the same address twice still adds one series.
    (FILES, ["skill://deepsource/_files.md", "skill://deepsource/_files.md"]),
    (PATH, ["skill://deepsource/README.md", "skill://deepsource/shared/guide.md"]),
    # The plugin-root fallback (SKL-30): a citation inside a skill that misses
    # there. kubed-mcp labels a read below a skill as its own, the fallback included.
    (
        LAYER_PATH,
        [
            "skill://deepsource/plugin-a/gamma/README.md",
            "skill://deepsource/plugin-b/delta/shared/guide.md",
        ],
    ),
]


@pytest.fixture(scope="session")
def reader():
    """The process's metric reader, and a tracer provider so kubed-mcp starts no SDK.

    A global ``TracerProvider`` is what kubed-mcp reads as an SDK already configured,
    so its own start exports nothing; the meter provider is set once per process, so
    every test reads the change its own reads made, never the totals.
    """
    if isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
        trace.set_tracer_provider(TracerProvider())
    found = InMemoryMetricReader()
    metrics.set_meter_provider(MeterProvider(metric_readers=[found]))
    return found


@pytest.fixture
def knowledge_base(skills_dir, tmp_path, reader):
    """A knowledge base whose app has ``telemetry.otel`` on, as ``server_of`` returns it."""
    loaded = load_config(
        sections=SECTIONS, config=[make_config(skills_dir), Telemetry(otel=True)]
    )
    kb = KnowledgeBase(loaded.config, tmp_path / "cache")
    _APPS[kb] = create_app(kb, loaded=loaded)
    yield kb
    _APPS.pop(kb, None)


def _points(reader) -> Counter:
    """Every ``resources/read`` duration point of this server, counted by attributes."""
    counts: Counter = Counter()
    data = reader.get_metrics_data()
    for resource in data.resource_metrics if data else ():
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name != DURATION:
                    continue
                for point in metric.data.data_points:
                    attributes = dict(point.attributes)
                    if (
                        attributes.get("mcp.method.name") == "resources/read"
                        and attributes.get("fastmcp.server.name") == SERVER_NAME
                    ):
                        counts[frozenset(attributes.items())] += point.count
    return counts


async def _labels(reader, reads) -> Counter:
    """The labels the reads ``reads()`` makes are recorded under, counted."""
    before = _points(reader)
    await reads()
    after = _points(reader)
    labels: Counter = Counter()
    for attributes, count in (after - before).items():
        labels[dict(attributes).get(TEMPLATE)] += count
    return labels


async def _error(client, uri) -> str:
    with pytest.raises(MCPError) as caught:
        await client.read_resource(uri)
    return str(caught.value)


# --- end to end, kubed-mcp's own observer ---------------------------------------


@pytest.mark.parametrize(("pattern", "uris"), KINDS)
async def test_a_kind_is_one_series_however_many_addresses_are_read(
    knowledge_base, reader, pattern, uris
):
    app = _APPS[knowledge_base]

    async def reads():
        async with Client(app.server) as client:
            for uri in uris:
                assert (await client.read_resource(uri))[0].text

    assert await _labels(reader, reads) == {pattern: 2}


async def test_no_concrete_address_is_ever_a_label(knowledge_base, reader):
    app = _APPS[knowledge_base]
    uris = {uri for _, pair in KINDS for uri in pair}

    async def reads():
        async with Client(app.server) as client:
            for uri in sorted(uris):
                await client.read_resource(uri)

    labels = await _labels(reader, reads)
    assert set(labels) <= PATTERNS | {LAYER_PATH}
    assert not any(label in uris for label in labels)


async def test_a_miss_carries_no_label_and_the_same_error(
    knowledge_base, reader, skills_dir, tmp_path
):
    """Absent, and a directory address with its hint: no label, and the error as
    the server without telemetry gives it."""
    misses = [
        "skill://flatsource/nope.md",
        "skill://nolib/_index.md",
        "skill://deepsource/plugin-a",
        "skill://flatsource/alpha",
    ]
    plain = create_app(KnowledgeBase(make_config(skills_dir), tmp_path / "plain"))
    async with Client(plain.server) as client:
        expected = [await _error(client, uri) for uri in misses]

    app = _APPS[knowledge_base]
    seen = []

    async def reads():
        async with Client(app.server) as client:
            seen.extend([await _error(client, uri) for uri in misses])

    assert await _labels(reader, reads) == {None: len(misses)}
    assert seen == expected
    assert any("_index.md" in error for error in seen)


async def test_a_read_after_a_miss_is_labelled_by_its_own_kind(knowledge_base, reader):
    """One mark per read: a hit does not leave a pattern for the next read."""
    app = _APPS[knowledge_base]

    async def reads():
        async with Client(app.server) as client:
            await client.read_resource("skill://flatsource/_index.md")
            with pytest.raises(MCPError):
                await client.read_resource("skill://flatsource/nope.md")

    assert await _labels(reader, reads) == {LIBRARY_INDEX: 1, None: 1}


async def test_a_skills_own_file_is_not_labelled_by_a_kb_pattern(knowledge_base, reader):
    app = _APPS[knowledge_base]

    async def reads():
        async with Client(app.server) as client:
            await client.read_resource("skill://flatsource/alpha/SKILL.md")

    labels = await _labels(reader, reads)
    assert sum(labels.values()) == 1
    assert not set(labels) & PATTERNS


async def test_a_read_through_the_tool_is_labelled_by_its_kind(knowledge_base, reader):
    """The DLV-6 mirror reads through ``resources/read``'s own chain, so its inner
    read is labelled as a direct one is."""
    app = _APPS[knowledge_base]

    async def reads():
        async with Client(app.server) as client:
            for uri in ("skill://flatsource/_index.md", "skill://deepsource/_index.md"):
                result = await client.call_tool("read_resource", {"uri": uri})
                assert not result.is_error

    assert await _labels(reader, reads) == {LIBRARY_INDEX: 2}


@pytest.mark.integration
def test_out_of_scope_is_labelled_as_absent_is(knowledge_base, reader):
    """Under a library pin, another library's index reads as a library that is not
    there: the same error, and no label."""
    import asyncio

    pin = {"Kb-Library": "flatsource"}
    with serve_http(knowledge_base) as url:

        async def errors(uris):
            async with http_client(url, headers=pin) as client:
                return [await _error(client, uri) for uri in uris]

        async def reads(uris, into):
            into.extend(await errors(uris))

        out, absent = [], []
        hidden = asyncio.run(
            _labels(reader, lambda: reads(["skill://deepsource/_index.md"], out))
        )
        missing = asyncio.run(
            _labels(reader, lambda: reads(["skill://nolib/_index.md"], absent))
        )

    assert hidden == missing == {None: 1}
    assert out[0].replace("deepsource", "nolib") == absent[0]


async def test_the_templates_list_keeps_its_one_row(knowledge_base):
    app = _APPS[knowledge_base]
    async with Client(app.server) as client:
        await client.read_resource("skill://flatsource/_index.md")
        templates = await client.list_resource_templates()
    assert [t.uri_template for t in templates] == [TEMPLATE_URI]


# --- the provider, below MCP --------------------------------------------------


@pytest.mark.parametrize(
    ("uri", "pattern"),
    [
        ("skill://flatsource/_index.md", LIBRARY_INDEX),
        ("skill://flatsource/_index.json", LIBRARY_JSON),
        ("skill://deepsource/_files.md", FILES),
        ("skill://deepsource/plugin-a/_index.md", FOLDER_INDEX),
        ("skill://deepsource/plugin-a/_index.json", FOLDER_JSON),
        ("skill://deepsource/README.md", PATH),
        ("skill://deepsource/shared/guide.md", PATH),
        ("skill://deepsource/shared/nested/schema.json", PATH),
        ("skill://deepsource/plugin-a/gamma/README.md", PATH),
        # A file named like an index, deeper than a folder's, is a path.
        ("skill://deepsource/shared/nested/_index.md", PATH),
        ("skill://deepsource/plugin-a/_files.md", PATH),
        # The shape is read from the address with its empty and dot segments resolved.
        ("skill://deepsource//_index.md", LIBRARY_INDEX),
        ("skill://deepsource/plugin-a/../_index.json", LIBRARY_JSON),
    ],
)
def test_a_pattern_is_the_uris_shape(uri, pattern):
    assert pattern_for(uri) == pattern


@pytest.mark.parametrize(
    "uri",
    [
        "skill://flatsource/_index.md",
        "skill://deepsource/plugin-a/_index.json",
        "skill://deepsource/shared/nested/schema.json",
        "skill://deepsource/plugin-b/delta/shared/guide.md",
    ],
)
def test_a_pattern_names_no_segment_of_the_uri(uri):
    pattern = pattern_for(uri)
    concrete = set(uri.removeprefix("skill://").split("/")) - {
        "_index.md",
        "_index.json",
        "_files.md",
    }
    assert not any(segment in pattern for segment in concrete)


@pytest.fixture
def provider(knowledge_base):
    return CatalogueProvider(lambda: knowledge_base.snapshot.catalogue)


@pytest.mark.parametrize(("pattern", "uris"), KINDS)
async def test_a_served_read_marks_its_pattern(provider, pattern, uris):
    for uri in uris:
        served = _Served()
        token = _SERVED.set(served)
        try:
            assert await provider._get_resource(uri) is not None
        finally:
            _SERVED.reset(token)
        # kb marks a fallback as PATH; the layer relabels it on the metric.
        assert served.pattern == (PATH if pattern == LAYER_PATH else pattern)


@pytest.mark.parametrize(
    "uri", ["skill://flatsource/nope.md", "skill://nolib/_index.md", "skill://flatsource"]
)
async def test_a_miss_marks_nothing(provider, uri):
    served = _Served()
    token = _SERVED.set(served)
    try:
        assert await provider._get_resource(uri) is None
    finally:
        _SERVED.reset(token)
    assert served.pattern is None


async def test_a_read_outside_a_marked_request_marks_nothing(provider):
    assert _SERVED.get() is None
    assert await provider._get_resource("skill://flatsource/_index.md") is not None


async def test_no_template_without_a_marked_read(provider):
    uri = "skill://flatsource/_index.md"
    assert await provider._get_resource_template(uri) is None
    token = _SERVED.set(_Served())
    try:
        assert await provider._get_resource_template(uri) is None
    finally:
        _SERVED.reset(token)


@pytest.mark.parametrize("version", [None, VersionSpec(eq="1.0")])
async def test_the_template_is_the_marked_pattern(provider, version):
    token = _SERVED.set(_Served(pattern=FOLDER_INDEX))
    try:
        template = await provider._get_resource_template(
            "skill://deepsource/plugin-a/_index.md", version
        )
    finally:
        _SERVED.reset(token)
    assert template is not None and template.uri_template == FOLDER_INDEX
