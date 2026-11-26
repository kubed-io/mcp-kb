"""A library's ``categories`` select it, over real HTTP.

Three libraries: ``alpha`` and ``beta`` list ``dev`` and ``gamma`` does not.
Each has a main plugin of its own name. ``gamma``'s has the category ``ops`` of
its own, and ``shared`` is one plugin served by both ``alpha`` (which lists
``dev``) and ``gamma`` (which does not), in a folder of its name in each, so
the category is a question about the library the plugin is in.
"""

import json
import re
import socket
import threading
import urllib.request

import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.config import Config
from tests.conftest import server_of

pytestmark = pytest.mark.integration

DEV = {"Kb-Category": "dev"}


def _skill(root, name):
    path = root / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: The {name} skill.\n---\n\n# {name}\n"
    )


def _plugin(root, name, skills, **extra):
    for skill in skills:
        _skill(root / name, skill)
    return {
        "name": name,
        "source": f"file://{root / name}",
        "skills": ["."],
        "files": ["**/*"],
        **extra,
    }


def _prompts(root, name):
    path = root / f"{name}-prompts"
    path.mkdir(parents=True)
    (path / "hello.md").write_text("---\ndescription: Say hello.\n---\nHello.\n")
    return {
        "name": f"{name}-prompts",
        "source": f"file://{path}",
        "prompts": ["*.md"],
    }


@pytest.fixture(scope="module")
def server_url(tmp_path_factory):
    root = tmp_path_factory.mktemp("categories")
    plugins = [
        _plugin(root, "alpha", ["one"], tags=["x"]),
        _plugin(root, "beta", ["two"]),
        _plugin(root, "gamma", ["three"], category="ops"),
        _plugin(root, "shared", ["common"]),
        _prompts(root, "alpha"),
        _prompts(root, "gamma"),
    ]
    (root / "alpha" / "docs").mkdir()
    (root / "alpha" / "docs" / "guide.md").write_text("alpha guide\n")
    (root / "gamma" / "docs").mkdir()
    (root / "gamma" / "docs" / "guide.md").write_text("gamma guide\n")
    config = Config.model_validate(
        {
            "plugins": plugins,
            "libraries": [
                {
                    "name": "alpha",
                    "plugins": ["alpha", "shared", "alpha-prompts"],
                    "categories": ["dev"],
                },
                {"name": "beta", "plugins": ["beta"], "categories": ["dev"]},
                {
                    "name": "gamma",
                    "plugins": ["gamma", "shared", "gamma-prompts"],
                    "categories": [" sp ", ""],
                },
            ],
        }
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = server_of(KnowledgeBase(config, root / "_cache")).http_app()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        threading.Event().wait(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


def _client(url, headers):
    return Client(StreamableHttpTransport(url, headers=headers))


async def _uris(url, headers):
    async with _client(url, headers) as client:
        return sorted(str(r.uri) for r in await client.list_resources())


async def _read(url, headers, uri):
    async with _client(url, headers) as client:
        return (await client.read_resource(uri))[0].text


async def test_category_selects_libraries(server_url):
    """The two libraries listing `dev`, though no plugin has that category."""
    assert await _uris(server_url, DEV) == [
        "skill://alpha/_files.md",
        "skill://alpha/one/SKILL.md",
        "skill://alpha/shared/common/SKILL.md",
        "skill://beta/two/SKILL.md",
    ]
    assert "The one skill." in await _read(
        server_url, DEV, "skill://alpha/one/SKILL.md"
    )
    assert "The two skill." in await _read(server_url, DEV, "skill://beta/two/SKILL.md")
    async with _client(server_url, DEV) as client:
        headings = re.findall(r"^\[(\w+)\]$", client.instructions, re.M)
        with pytest.raises(Exception, match=r"nknown|not found"):
            await client.read_resource("skill://gamma/three/SKILL.md")
    assert headings == ["alpha", "beta"]


async def test_plugin_category_still_selects(server_url):
    uris = await _uris(server_url, {"Kb-Category": "ops"})
    assert "skill://gamma/three/SKILL.md" in uris
    assert not any(u.startswith(("skill://alpha", "skill://beta")) for u in uris)


async def test_pin_and_foreign_category(server_url):
    """gamma neither lists `dev` nor has a plugin of that category: refused, as a
    pin with a category from elsewhere is today."""
    headers = {"Kb-Library": "gamma", **DEV}
    with pytest.raises(Exception, match="category 'dev'"):
        await _uris(server_url, headers)


async def test_tag_narrows_within_categories(server_url):
    uris = await _uris(server_url, {**DEV, "Kb-Tag": "x"})
    assert "skill://alpha/one/SKILL.md" in uris
    assert not any(u.startswith("skill://beta") for u in uris)


async def test_unknown_category_lists_library_categories(server_url):
    with pytest.raises(Exception, match="nope") as caught:
        await _uris(server_url, {"Kb-Category": "nope"})
    assert "dev" in str(caught.value)


def test_health_shows_library_categories(server_url):
    url = server_url.removesuffix("/mcp") + "/health"
    with urllib.request.urlopen(url) as response:
        body = json.loads(response.read())
    libraries = body["libraries"]
    assert libraries["alpha"]["categories"] == ["dev"]
    assert libraries["beta"]["categories"] == ["dev"]
    assert libraries["gamma"]["categories"] == ["sp"]


async def test_category_is_per_library_for_a_shared_plugin(server_url):
    """`shared` is in alpha (dev) and gamma (not): only alpha's copy is in scope."""
    async with _client(server_url, DEV) as client:
        body = (await client.read_resource("skill://alpha/shared/common/SKILL.md"))[
            0
        ].text
        assert "The common skill." in body
        with pytest.raises(Exception, match=r"nknown|not found"):
            await client.read_resource("skill://gamma/shared/common/SKILL.md")


async def test_library_files_follow_library_categories(server_url):
    assert await _read(server_url, DEV, "skill://alpha/docs/guide.md") == (
        "alpha guide\n"
    )
    async with _client(server_url, DEV) as client:
        with pytest.raises(Exception, match=r"nknown|not found|No resource"):
            await client.read_resource("skill://gamma/docs/guide.md")


async def test_prompts_follow_library_categories(server_url):
    async with _client(server_url, DEV) as client:
        names = sorted(p.name for p in await client.list_prompts())
    assert names == ["alpha_hello"]


async def test_a_padded_library_category_still_selects(server_url):
    assert await _uris(server_url, {"Kb-Category": "sp"}) == [
        "skill://gamma/_files.md",
        "skill://gamma/shared/common/SKILL.md",
        "skill://gamma/three/SKILL.md",
    ]
