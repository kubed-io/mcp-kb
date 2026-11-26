"""A refused or empty scope builds nothing (ruling 8, design D10).

kubed-mcp makes a build, and so calls the view's ``admits`` once per plugin, for
every distinct view key. A key minted from a scope that names nothing is a build
for nothing, so a client sending a new bogus value each request could fill the
build cache. These tests count ``admits`` calls over real HTTP.
"""

import inspect

import pytest

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.config import Config
from kubed.mcp_kb.mcp import skills
from kubed.mcp_kb.mcp.pins import what_is_wrong
from kubed.mcp_kb.mcp.scope import Scope
from kubed.mcp_kb.mcp.skills import EMPTY, SkillServing
from tests.conftest import (
    http_client,
    make_config,
    serve_http,
    serving_of,
)


@pytest.fixture
def builds(monkeypatch):
    """Every view's ``admits`` calls, counted: a build makes one per plugin."""
    seen = {"calls": 0, "keys": []}
    view = SkillServing.view

    def counting(self):
        got = view(self)
        seen["keys"].append(got.key)
        admits = got.admits

        def counted(plugin):
            seen["calls"] += 1
            return admits(plugin)

        return type(got)(got.key, counted)

    monkeypatch.setattr(SkillServing, "view", counting)
    return seen


async def _list(url, headers):
    async with http_client(url, headers) as client:
        return await client.list_resources()


@pytest.mark.integration
async def test_a_refused_scope_builds_nothing(skills_dir, prompts_dir, builds):
    kb = KnowledgeBase(make_config(skills_dir, prompts_dir), skills_dir / "_cache")
    with serve_http(kb) as url:
        # One accepted request, to know what a build costs here: one admits
        # call per plugin of the set, for the one unscoped key.
        await _list(url, {})
        baseline = builds["calls"]
        assert baseline > 0
        keys = len(builds["keys"])
        for n in range(50):
            with pytest.raises(Exception, match="which nothing carries"):
                await _list(url, {"Kb-Tag": f"nope-{n}"})
    # Nothing beyond the unscoped build above: a refused request admits nothing.
    assert builds["calls"] == baseline
    # Nor is the view asked for at all: kubed-mcp reads it lazily, and kb's
    # RefuseEmptyScope, inside it, raises first.
    assert len(builds["keys"]) == keys


def _down_config(skills_dir, prompts_dir, tmp_path):
    config = make_config(skills_dir, prompts_dir)
    data = config.model_dump(by_alias=True, exclude_none=True)
    data["plugins"] = [
        *data.get("plugins", []),
        {"name": "ghost", "source": f"file://{tmp_path / 'missing'}"},
    ]
    data["libraries"] = [
        *data.get("libraries", []),
        {"name": "ghostlib", "plugins": ["ghost"], "categories": ["spooky"]},
    ]
    return Config.model_validate(data)


async def test_scopes_admitting_nothing_share_one_key(
    skills_dir, prompts_dir, tmp_path, monkeypatch
):
    config = _down_config(skills_dir, prompts_dir, tmp_path)
    kb = KnowledgeBase(config, skills_dir / "_cache")
    assert kb.status["libraries"]["ghostlib"]["plugins"]
    assert what_is_wrong(Scope.parse(library="ghostlib"), config, kb.snapshot) is None
    serving = serving_of(kb)
    for scope in (
        Scope.parse(library="ghostlib"),
        Scope.parse(library="ghostlib", categories=["whatever"]),
        Scope.parse(library="ghostlib", tags=["whatever"]),
    ):
        monkeypatch.setattr(skills, "requested_scope", lambda scope=scope: scope)
        assert serving.view().key == EMPTY


def test_what_is_wrong_reads_the_snapshot():
    assert set(inspect.signature(what_is_wrong).parameters) == {
        "scope",
        "config",
        "snapshot",
    }
