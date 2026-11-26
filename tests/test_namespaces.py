"""A library is a namespace, with its main plugin on top (design D1).

A library's *main plugin* is decided once per generation from its resolved
plugin list: the first plugin named like the library, else the only entry of a
marketplace that publishes exactly one -- skipped entries count -- else none.
A skill of the main plugin is ``<library>/<name>``; a skill of any other plugin
is ``<library>/<plugin name>/<name>``. Nothing about a request moves either.
"""

import inspect
import json

import httpx
import pytest
from fastmcp import Client

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.catalogue.index import Index
from kubed.mcp_kb.catalogue.snapshot import assemble_libraries, namespace_for
from kubed.mcp_kb.config import Config
from kubed.mcp_kb.mcp.scope import Scope
from tests.conftest import server_of

pytestmark = pytest.mark.unit


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _skill(root, rel, name):
    _write(root, f"{rel}/SKILL.md", f"---\nname: {name}\ndescription: {name}.\n---\n")


def _catalog(root, *entries):
    _write(
        root,
        ".claude-plugin/marketplace.json",
        json.dumps({"name": "market", "plugins": list(entries)}),
    )


def _kb(tmp_path, **config):
    return KnowledgeBase(Config.model_validate(config), tmp_path / "cache")


def _library(kb, name):
    return next(lib for lib in kb._libraries if lib.name == name)


def _addresses(kb, scope=None):
    skills = kb.index.visible() if scope is None else kb.index.visible(scope)
    return sorted(s.address for s in skills)


async def _health(kb):
    transport = httpx.ASGITransport(app=server_of(kb).http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://kb") as http:
        return (await http.get("/health")).json()


async def _read(kb, uri):
    async with Client(server_of(kb)) as client:
        return (await client.read_resource(uri))[0].text


async def _miss(kb, uri):
    """What the server answers for ``uri``, with the URI itself taken out."""
    async with Client(server_of(kb)) as client:
        with pytest.raises(Exception) as caught:
            await client.read_resource(uri)
    return str(caught.value).replace(uri, "<uri>")


@pytest.fixture
def superpowers(tmp_path):
    """A library `superpowers` with a plugin of its own name and a `tidy`."""
    _skill(tmp_path / "sp", "skills/writing-plans", "writing-plans")
    _skill(tmp_path / "tidy", "skills/natural-writing", "natural-writing")
    return {
        "plugins": [
            {"name": "superpowers", "source": f"file://{tmp_path / 'sp'}"},
            {
                "name": "tidy",
                "source": f"file://{tmp_path / 'tidy'}",
                "tags": ["prose"],
            },
        ],
        "libraries": [{"name": "superpowers", "plugins": ["superpowers", "tidy"]}],
    }


async def test_a_plugin_named_like_its_library_is_main(superpowers, tmp_path):
    kb = _kb(tmp_path, **superpowers)

    assert _library(kb, "superpowers").main == "superpowers"
    assert _addresses(kb) == [
        "superpowers/tidy/natural-writing",
        "superpowers/writing-plans",
    ]
    nested = "skill://superpowers/tidy/natural-writing/SKILL.md"
    assert "natural-writing." in await _read(kb, nested)
    assert "writing-plans." in await _read(
        kb, "skill://superpowers/writing-plans/SKILL.md"
    )
    library = _library(kb, "superpowers")
    by_name = {p.name: p for p in kb._plugins}
    assert namespace_for(library, by_name["superpowers"]) == "superpowers"
    assert namespace_for(library, by_name["tidy"]) == "superpowers/tidy"


async def test_a_plugin_is_main_in_one_library_and_nested_in_another(
    superpowers, tmp_path
):
    """The folder is the library's decision, not the harvest's."""
    superpowers["libraries"].append({"name": "all", "plugins": ["superpowers"]})
    kb = _kb(tmp_path, **superpowers)

    assert _library(kb, "all").main is None
    assert "superpowers/writing-plans" in _addresses(kb)
    assert "all/superpowers/writing-plans" in _addresses(kb)


@pytest.mark.parametrize("where", ["./", "./plugins/claude/x"])
async def test_a_lone_entry_is_main_whatever_its_path(tmp_path, where):
    market = tmp_path / "market"
    _skill(market / where, "skills/build", "build")
    _catalog(market, {"name": "x", "source": where})
    _skill(tmp_path / "house", "skills/n8n-mcp-instructions", "n8n-mcp-instructions")
    kb = _kb(
        tmp_path,
        plugins=[{"name": "n8n-house", "source": f"file://{tmp_path / 'house'}"}],
        libraries=[
            {"name": "n8n", "source": f"file://{market}", "plugins": ["n8n-house"]}
        ],
    )

    assert _library(kb, "n8n").main == "x@n8n"
    assert _addresses(kb) == ["n8n/build", "n8n/n8n-house/n8n-mcp-instructions"]


GRAFANA = {
    "grafana-lgtm": ("loki", "tempo"),
    "grafana-k6": ("k6",),
    "grafana-oncall": ("oncall",),
    "grafana-irm": ("irm",),
    "grafana-faro": ("faro",),
    "grafana-alloy": ("alloy",),
    "grafana-dash": ("dash",),
}


async def test_several_entries_have_no_main(tmp_path):
    """Grafana's shape: seven entries on one tree, each naming its own folder."""
    market = tmp_path / "grafana"
    entries = []
    for entry, skills in GRAFANA.items():
        for skill in skills:
            _skill(market, f"skills/{entry}/{skill}", skill)
        entries.append({"name": entry, "source": "./", "skills": [f"./skills/{entry}"]})
    _catalog(market, *entries)
    kb = _kb(tmp_path, libraries=[{"name": "grafana", "source": f"file://{market}"}])

    assert _library(kb, "grafana").main is None
    addresses = _addresses(kb)
    assert "grafana/grafana-lgtm/loki" in addresses
    assert "grafana/grafana-lgtm/tempo" in addresses
    assert "grafana/grafana-k6/k6" in addresses
    assert len(addresses) == 8


async def test_a_skipped_entry_still_counts(tmp_path):
    """The count is of entries published, so a skip never moves an address."""
    market = tmp_path / "market"
    _skill(market, "skills/build", "build")
    _catalog(
        market,
        {"name": "x", "source": "./"},
        {"name": "run", "source": {"source": "command", "command": "make"}},
    )
    kb = _kb(tmp_path, libraries=[{"name": "lib", "source": f"file://{market}"}])

    assert kb.status["libraries"]["lib"]["skipped"][0]["plugin"] == "run"
    assert _library(kb, "lib").main is None
    assert _addresses(kb) == ["lib/x/build"]


async def test_the_main_plugin_follows_the_config_not_the_scope(superpowers, tmp_path):
    params = inspect.signature(assemble_libraries).parameters.values()
    assert not any(
        "scope" in p.name.lower() or "Scope" in str(p.annotation) for p in params
    )

    kb = _kb(tmp_path, **superpowers)
    pinned = Scope.parse(tags="prose")
    assert _addresses(kb, pinned) == ["superpowers/tidy/natural-writing"]
    assert _library(kb, "superpowers").main == "superpowers"


async def test_a_marketplace_gaining_an_entry_moves_nothing_unexpected(tmp_path):
    market = tmp_path / "market"
    _skill(market, "plugins/x/skills/build", "build")
    x = {"name": "x", "source": "./plugins/x"}
    _catalog(market, x)
    kb = _kb(tmp_path, libraries=[{"name": "n8n", "source": f"file://{market}"}])
    assert _addresses(kb) == ["n8n/build"]

    _skill(market, "plugins/y/skills/deploy", "deploy")
    _catalog(market, x, {"name": "y", "source": "./plugins/y"})
    kb.refresh()

    assert _library(kb, "n8n").main is None
    assert _addresses(kb) == ["n8n/x/build", "n8n/y/deploy"]
    assert "build." in await _read(kb, "skill://n8n/x/build/SKILL.md")
    assert await _miss(kb, "skill://n8n/build/SKILL.md") == await _miss(
        kb, "skill://n8n/never/SKILL.md"
    )
    assert "conflicts" not in (await _health(kb))["libraries"]["n8n"]


async def test_a_plugin_named_like_a_main_skill_conflicts(tmp_path):
    _skill(tmp_path / "main", "skills/tidy", "tidy")
    _skill(tmp_path / "tidy", "skills/natural-writing", "natural-writing")
    kb = _kb(
        tmp_path,
        plugins=[
            {"name": "lib", "source": f"file://{tmp_path / 'main'}"},
            {"name": "tidy", "source": f"file://{tmp_path / 'tidy'}"},
        ],
        libraries=[{"name": "lib", "plugins": ["lib", "tidy"]}],
    )

    conflicts = (await _health(kb))["libraries"]["lib"]["conflicts"]
    assert conflicts["tidy"].startswith("conflict: skill://lib/tidy")
    assert _addresses(kb) == ["lib/tidy"]
    assert "tidy." in await _read(kb, "skill://lib/tidy/SKILL.md")


def test_a_v11_skill_row_carrying_a_folder_is_never_read(superpowers, tmp_path):
    """A skill's folder is the library's to decide, and the index holds no skill
    rows to carry one (D1): a v11 file whose rows do is read for its fetches
    alone, and every address is the library's again."""
    kb = _kb(tmp_path, **superpowers)
    path = next((tmp_path / "cache").rglob("index.json"))
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "plugins" not in raw

    row = {"name": "x", "description": "d", "path": "/x", "folder": "elsewhere"}
    raw |= {"version": 11, "plugins": {"p": {"skills": [row]}}}
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert Index.read(path).fetches.keys() == raw["fetches"].keys()
    assert _addresses(_kb(tmp_path, **superpowers)) == _addresses(kb)
