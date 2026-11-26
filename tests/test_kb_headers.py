"""The ``Kb-`` request headers and ``?`` parameters, and the old names as aliases.

Served by the ``test_library_categories`` catalogue: ``alpha`` and ``beta`` list
the category ``dev``, ``alpha``'s plugin carries the tag ``x``, ``gamma`` has
neither, and both ``alpha`` and ``gamma`` serve ``shared`` in a folder of its name.
"""

import pytest

from tests.test_library_categories import _client, _uris, server_url  # noqa: F401

pytestmark = pytest.mark.integration

GAMMA = [
    "skill://gamma/_files.md",
    "skill://gamma/shared/common/SKILL.md",
    "skill://gamma/three/SKILL.md",
]
DEV = [
    "skill://alpha/_files.md",
    "skill://alpha/one/SKILL.md",
    "skill://alpha/shared/common/SKILL.md",
    "skill://beta/two/SKILL.md",
]
ALPHA = ["skill://alpha/_files.md", "skill://alpha/one/SKILL.md"]

# (setting, new header, new param, old header, old param, value, uris it gives)
SETTINGS = [
    ("library", "Kb-Library", "library", "X-Skill-Library", None, "gamma", GAMMA),
    ("category", "Kb-Category", "category", "X-Skill-Categories", "categories", "dev", DEV),
    ("tag", "Kb-Tag", "tag", "X-Skill-Tags", "tags", "x", ALPHA),
]
IDS = [row[0] for row in SETTINGS]


@pytest.mark.parametrize("row", SETTINGS, ids=IDS)
async def test_new_headers_scope(server_url, row):  # noqa: F811
    _, header, param, _, _, value, expected = row
    assert await _uris(server_url, {header: value}) == expected
    assert await _uris(f"{server_url}?{param}={value}", {}) == expected


@pytest.mark.parametrize("row", SETTINGS, ids=IDS)
async def test_old_names_still_work(server_url, row):  # noqa: F811
    _, _, _, header, param, value, expected = row
    assert await _uris(server_url, {header: value}) == expected
    if param:
        assert await _uris(f"{server_url}?{param}={value}", {}) == expected


async def test_prefix_names(server_url):  # noqa: F811
    for header in ("Kb-Resource-Prefix", "X-MCP-Resource-Prefix"):
        async with _client(server_url, {header: "kb+"}) as client:
            assert "kb+skill://" in client.instructions
    async with _client(server_url + "?prefix=kb%2B", {}) as client:
        assert "kb+skill://" in client.instructions


@pytest.mark.parametrize("row", SETTINGS, ids=IDS)
async def test_new_header_beats_its_alias(server_url, row):  # noqa: F811
    _, header, _, old, _, value, expected = row
    other = {"library": "alpha", "category": "ops", "tag": "nope"}[row[0]]
    assert await _uris(server_url, {header: value, old: other}) == expected


async def test_new_header_beats_its_alias_for_the_prefix(server_url):  # noqa: F811
    new, old = "Kb-Resource-Prefix", "X-MCP-Resource-Prefix"
    async with _client(server_url, {new: "new+", old: "old+"}) as client:
        assert "new+skill://" in client.instructions
        assert "old+skill://" not in client.instructions


async def test_precedence_runs_header_then_param(server_url):  # noqa: F811
    # old header beats new param; new param beats old param
    assert await _uris(f"{server_url}?library=alpha", {"X-Skill-Library": "gamma"}) == GAMMA
    assert await _uris(f"{server_url}?category=dev&categories=ops", {}) == DEV


async def test_refusals_name_the_new_names(server_url):  # noqa: F811
    with pytest.raises(Exception) as caught:
        await _uris(server_url, {"Kb-Library": "alpha/x"})
    assert "?category= or ?tag=" in str(caught.value)
    assert "Kb-Category" in str(caught.value)
    with pytest.raises(Exception) as caught:
        await _uris(server_url, {"Kb-Category": "a,b"})
    assert "repeat ?category=" in str(caught.value)


async def test_an_empty_value_counts_as_not_sent(server_url):  # noqa: F811
    headers = {"Kb-Category": "", "X-Skill-Categories": "dev"}
    assert await _uris(server_url, headers) == DEV
