"""``cache: live``: a read revalidates the file it is about to serve.

Every test drives a real ``KnowledgeBase`` over the real WebDAV server
(``tests/webdav_server.py``), which refuses an unauthenticated request. What is
being proved is one sentence: *a file edited upstream is served on the next
read, and everything else about the server stays where it was.*

Two quirks of the server under test:

- Its ETag is ``inode-mtime-size``, so a test that edits a file makes it a
  different length. Nextcloud's ETags are content-derived and have no such
  requirement.
- The revalidation TTL is off by default here (``TTL_SECONDS`` monkeypatched to
  zero), because a test that edits a file and reads it again does so in
  microseconds. The one test about the TTL turns it back on.
"""

import hashlib
import json
import logging
import socket
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastmcp import Client
from kubed.mcp.protocol import MCPError

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.catalogue.uris import AGENT_META
from kubed.mcp_kb.config import BasicAuth, Config, EnvRef
from kubed.mcp_kb.plugins import Fetch
from kubed.mcp_kb.sources import live
from tests.conftest import (
    DEEP_YAML,
    ext_request,
    http_client,
    read_served,
    run_client,
    serve_http,
    server_of,
    serving_of,
)
from tests.webdav_server import FOLDER, PASSWORD, USERNAME

pytestmark = pytest.mark.unit

ENV = "WEBDAV_PASSWORD"
KEY = f"notes://{FOLDER}"
SKILL = "skill://notes/x"
URI = f"{SKILL}/SKILL.md"
GUIDE = "skill://notes/docs/guide.md"
PROMPT = "---\ndescription: A prompt.\n---\n\n{body}\n"
ARGUED = (
    "---\ndescription: A prompt.\narguments:\n- name: who\n  description: Whom.\n"
    "  required: true\n---\n\n{body}\n"
)
EDITED = "---\nname: x\ndescription: Edited upstream.\n---\n\nedited in nextcloud, and longer\n"
OTHER = "skill://other/z/SKILL.md"
AGENT = "---\nname: helper\ndescription: {description}\n---\n\n{body}\n"


@pytest.fixture(autouse=True)
def credential(monkeypatch):
    """The password the config only ever names."""
    monkeypatch.setenv(ENV, PASSWORD)


@pytest.fixture(autouse=True)
def no_refresh_loop(monkeypatch):
    """Reads go through an MCP client, whose connection starts the server's
    lifespan; its refresh loop would list the source on its own schedule, and
    what is under test here is what a read alone asks of the server."""
    import asyncio

    from kubed.mcp_kb import server

    async def idle(knowledge_base):
        await asyncio.Event().wait()

    monkeypatch.setattr(server, "loop", idle)


@pytest.fixture(autouse=True)
def no_ttl(monkeypatch):
    """Ask the server on every read, because a test edits faster than 2 seconds."""
    monkeypatch.setattr(live, "TTL_SECONDS", 0.0)


def _knowledge_base(webdav, tmp_path, cache="live"):
    config = Config.model_validate(
        {
            "sources": [
                {
                    "name": "notes",
                    "url": webdav.url,
                    "auth": {"username": USERNAME, "password": {"env": ENV}},
                    "cache": cache,
                }
            ],
            "plugins": [
                {
                    "name": "notes",
                    "source": KEY,
                    "prompts": ["prompts/*.md"],
                    "files": ["docs/**/*"],
                }
            ],
            "libraries": [{"name": "notes", "plugins": ["notes"]}],
        }
    )
    return KnowledgeBase(config, tmp_path / "cache")


# -- what live mode buys -------------------------------------------------------


def test_an_edit_upstream_is_visible_on_the_next_read_without_a_refresh(
    webdav, tmp_path
):
    """One request late (N6): the read that revalidates re-adds the plugin and
    still serves the copy it pinned; the read after it serves the edit."""
    knowledge_base = _knowledge_base(webdav, tmp_path)
    assert "first" in read_served(knowledge_base, URI)

    webdav.skill("x", "edited in nextcloud, and rather longer than before")

    assert "first" in read_served(knowledge_base, URI), "N6: the re-adding read"
    assert "edited in nextcloud" in read_served(knowledge_base, URI)
    assert knowledge_base.generation == 0, "no refresh happened; the read did the work"


def test_the_rereading_read_builds_the_set_it_pinned(webdav, tmp_path):
    """N6 and MD-57: the read whose view re-reads a live skill FastMCP now
    refuses still builds the set it pinned, against that set's state, so it
    serves the old copy; the read after it serves nothing at the skill."""
    knowledge_base = _knowledge_base(webdav, tmp_path)
    # Served, and never read: a read now would keep a build of the set, which
    # the re-reading read would then share instead of making its own.
    plugin = next(p for p in serving_of(knowledge_base)._mcp.plugins)
    assert URI in plugin.skills

    webdav.write("skills/x/SKILL.md", "---\nname: x\ndescription: ''\n---\nBody.\n")

    assert "first" in (read_served(knowledge_base, URI) or ""), "N6: the re-adding read"
    assert read_served(knowledge_base, URI) is None, "MD-57: x no longer builds"


def _skill_site(serving, view_key=None):
    """The ``Site`` kubed-mcp's build hands the rewriter for x's ``SKILL.md``."""
    from kubed.mcp.plugins import Site

    plugin = next(p for p in serving._mcp.plugins if p.namespace == "notes")
    assert URI in plugin.skills
    return Site(
        plugin=plugin,
        namespace=plugin.namespace,
        kind="skill",
        path="skills/x/SKILL.md",
        uri=URI,
        view=view_key,
        admitted=(plugin,),
        skills={"skills/x": SKILL},
    )


def test_a_build_pinned_before_a_refresh_publishes_reads_its_own_state(
    webdav, tmp_path, monkeypatch
):
    """A refresh publishing from another thread while a build is in flight: the
    build's rewriter reads the state its request's view pinned, not the new one;
    a build no view pinned reads what is published now (N13).

    The refresh lands inside an ``agents/get``, after its view pinned: that
    request answers from its own generation, kb's ``_meta`` key included, and
    the next one from the new generation (AGT-17)."""
    import contextvars
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace

    command = "---\ndescription: Cite.\n---\nUse notes:x.\n"
    webdav.write("prompts/cite.md", command)
    webdav.write(".claude-plugin/plugin.json", json.dumps({"name": "notes"}))
    webdav.write(
        "agents/a.md",
        "---\nname: a\ndescription: Cites.\nskills: [x, y]\n---\n"
        "Use notes:x and notes:y.\n",
    )
    knowledge_base = _knowledge_base(webdav, tmp_path)
    serving = serving_of(knowledge_base)
    text = (webdav.root / "skills/x/SKILL.md").read_text()
    pinned = contextvars.copy_context()
    view = pinned.run(serving.view)
    site = _skill_site(serving, view.key)
    # The same build's command: its body cites x by its qualified name (D6).
    cite = replace(
        site, kind="command", path="prompts/cite.md", uri="prompts://notes/cite.md"
    )
    plugin = site.plugin

    # x renamed y: x's folder now holds a hidden file, so x no longer serves.
    webdav.write("skills/x/.draft.md", "draft\n")
    webdav.skill("y", "renamed")
    reread = serving._reread_live
    refreshed: list[list[str]] = []

    def refresh_inside_the_view(scope):
        # The plugin layer has taken its state, and kb's view its published
        # one: a refresh publishing from another thread now lands after the pin.
        reread(scope)
        if not refreshed:
            with ThreadPoolExecutor(1) as pool:
                done = pool.submit(knowledge_base.refresh, force=True)
                refreshed.append(done.result())

    monkeypatch.setattr(serving, "_reread_live", refresh_inside_the_view)

    async def get_twice(client):
        first = await ext_request(client, "agents/get", name="notes_a")
        return first, await ext_request(client, "agents/get", name="notes_a")

    first, then = run_client(knowledge_base, get_twice)
    assert refreshed == [[KEY]]
    assert first["instructions"] == "Use skill://notes/x/SKILL.md and notes:y."
    assert first["_meta"][AGENT_META]["skills"] == {"x": "skill://notes/x/SKILL.md"}
    assert then["instructions"] == "Use notes:x and skill://notes/y/SKILL.md."
    assert then["_meta"][AGENT_META]["skills"] == {"y": "skill://notes/y/SKILL.md"}
    assert SKILL.removeprefix("skill://") in serving._published.hidden

    assert "first" in pinned.run(serving.rewrite, site, text)
    with pytest.raises(ValueError, match="hidden file"):
        contextvars.Context().run(serving.rewrite, site, text)

    # The pinned build renders the command against its own generation's names,
    # where x serves; the generation published since serves no x to name.
    rendered = pinned.run(serving.rewrite, cite, command)
    assert rendered.endswith("Use skill://notes/x/SKILL.md.\n")
    assert contextvars.Context().run(serving.rewrite, cite, command) == command
    prompt = pinned.run(
        serving.read_command, rendered, "prompts/cite.md", "notes_cite", plugin
    )
    assert prompt.file.template == "Use skill://notes/x/SKILL.md.\n"


def test_a_build_pinned_before_a_serve_that_raises_reads_its_own_generation(
    webdav, tmp_path, monkeypatch
):
    """A refresh whose ``serve()`` raises serves nothing new: a build pinned
    before it reads its own generation, inside the window too, and after it
    both a pinned and an unpinned build read the generation still served."""
    import contextvars

    knowledge_base = _knowledge_base(webdav, tmp_path)
    serving = serving_of(knowledge_base)
    mcp = serving._mcp
    previous = serving._published
    text = (webdav.root / "skills/x/SKILL.md").read_text()
    pinned = contextvars.copy_context()
    view = pinned.run(serving.view)
    site = _skill_site(serving, view.key)
    during = {}

    def refused(staging):
        # A build of the set served, made while the new state is swapped in.
        try:
            during["pinned"] = pinned.run(serving.rewrite, site, text)
        except ValueError as exc:
            during["pinned"] = f"raised: {exc}"
        raise RuntimeError("the plugin layer fell over")

    monkeypatch.setattr(mcp, "serve", refused)
    webdav.write("skills/x/.draft.md", "draft\n")
    with pytest.raises(RuntimeError, match="fell over"):
        knowledge_base.refresh(force=True)

    assert "first" in during["pinned"]
    assert serving._published is previous
    assert "first" in pinned.run(serving.rewrite, site, text)
    assert "first" in contextvars.Context().run(serving.rewrite, site, text)


def test_an_edit_upstream_fastmcp_refuses_unlists_the_skill(webdav, tmp_path):
    """MD-57 for a live skill: once it no longer builds, nothing names it --
    from the read after the one that re-adds its plugin (N6)."""
    knowledge_base = _knowledge_base(webdav, tmp_path)
    assert "skill://notes/x/SKILL.md" in read_served(knowledge_base, "skill://notes/_index.md")

    webdav.write("skills/x/SKILL.md", "---\nname: x\ndescription: ''\n---\nBody.\n")

    assert "first" in read_served(knowledge_base, URI), "N6: the re-adding read"
    assert read_served(knowledge_base, URI) is None
    index = read_served(knowledge_base, "skill://notes/_index.md")
    assert index is None or "skill://notes/x" not in index
    assert knowledge_base.generation == 0, "the read did it, not a refresh"


def test_a_library_level_file_is_revalidated_too(webdav, tmp_path):
    """A skill's instructions are not the only thing a live source serves."""
    knowledge_base = _knowledge_base(webdav, tmp_path)
    assert read_served(knowledge_base, GUIDE) == "library-level guidance\n"

    webdav.write("docs/guide.md", "guidance, revised and lengthened upstream\n")

    assert "revised and lengthened" in read_served(knowledge_base, GUIDE)


async def _rendered(client, name, **arguments) -> str:
    got = await client.get_prompt(name, arguments)
    return "".join(m.content.text for m in got.messages)


async def test_a_live_prompt_edit_serves_from_the_next_request(webdav, tmp_path):
    """PRM-58, PRM-59: the request that notices an edit still reads the old
    build; the next one reads the edit, with its arguments."""
    webdav.write("prompts/p.md", PROMPT.format(body="the first body"))
    kb = _knowledge_base(webdav, tmp_path)
    async with Client(server_of(kb)) as client:
        assert "the first body" in await _rendered(client, "notes_p")
        webdav.write(
            "prompts/p.md", ARGUED.format(body="the second, longer body {{ who }}")
        )
        assert "the first body" in await _rendered(client, "notes_p")  # noticed here
        assert "the second, longer body you" in await _rendered(
            client, "notes_p", who="you"
        )
        (listed,) = [p for p in await client.list_prompts() if p.name == "notes_p"]
        assert [a.name for a in listed.arguments] == ["who"]


async def _keeps_the_last_good_build(webdav, tmp_path, caplog, broken, reason):
    webdav.write("prompts/p.md", PROMPT.format(body="the first body"))
    kb = _knowledge_base(webdav, tmp_path)
    async with Client(server_of(kb)) as client:
        assert "the first body" in await _rendered(client, "notes_p")
        webdav.write("prompts/p.md", broken)
        with caplog.at_level(logging.WARNING, logger="kubed.mcp_kb"):
            assert "the first body" in await _rendered(client, "notes_p")
            assert "the first body" in await _rendered(client, "notes_p")
        warned = [
            r.getMessage() for r in caplog.records if "not read again" in r.getMessage()
        ]
        assert len(warned) == 1 and "prompts/p.md" in warned[0], warned
        assert reason in warned[0], warned
        assert str(tmp_path) not in warned[0], warned
        webdav.write(
            "prompts/p.md", PROMPT.format(body="the third body, longest of all")
        )
        assert "the first body" in await _rendered(client, "notes_p")  # noticed here
        assert "the third body" in await _rendered(client, "notes_p")


async def test_a_live_prompt_saved_mid_edit_keeps_the_last_good_build(
    webdav, tmp_path, caplog
):
    """PRM-60: an unquoted `[a] [b]` is no YAML at all."""
    await _keeps_the_last_good_build(
        webdav,
        tmp_path,
        caplog,
        "---\ndescription: A prompt.\nargument-hint: [a] [b]\n---\n\nthe edited body\n",
        "did not find expected key",
    )


async def test_a_live_prompt_saved_too_deep_keeps_the_last_good_build(
    webdav, tmp_path, caplog, frontmatter_out_of_stack
):
    await _keeps_the_last_good_build(
        webdav,
        tmp_path,
        caplog,
        f"---\ndescription: A prompt.\nx: {DEEP_YAML}\n---\n\nthe edited body\n",
        "nested too deeply",
    )


def test_a_prompt_broken_by_a_refresh_does_not_block_a_live_skill_edit(
    webdav, tmp_path, caplog
):
    """PRM-60: a refresh that finds the plugin's only prompt broken adds the
    plugin with no prompt read, so a later re-read has no prompt to vet, and a
    skill's edit serves from the next request."""
    webdav.write("prompts/p.md", PROMPT.format(body="the first body"))
    kb = _knowledge_base(webdav, tmp_path)
    assert "first" in read_served(kb, URI)
    webdav.write("prompts/p.md", "no frontmatter here at all, and longer than before\n")
    kb.refresh(force=True)
    assert [p.name for p in kb.prompts] == []
    webdav.skill("x", "edited in nextcloud, and rather longer than before")
    with caplog.at_level(logging.WARNING, logger="kubed.mcp_kb"):
        assert "first" in read_served(kb, URI), "N6: the re-adding read"
        assert "edited in nextcloud" in read_served(kb, URI)
    assert not [r for r in caplog.records if "not read again" in r.getMessage()]


def test_a_broken_edit_to_a_file_that_lost_its_name_does_not_block_a_reread(
    webdav, tmp_path, caplog
):
    """PRM-60 vets what the plugin served: a file the layer refused for a name
    another file took serves nothing, so breaking it blocks no re-read."""
    config = Config.model_validate(
        {
            "sources": [
                {
                    "name": "notes",
                    "url": webdav.url,
                    "auth": {"username": USERNAME, "password": {"env": ENV}},
                    "cache": "live",
                }
            ],
            "plugins": [
                {
                    "name": "notes",
                    "source": KEY,
                    # Both are notes_p: a/p.md is read first and claims it.
                    "prompts": ["prompts/a/*.md", "prompts/b/*.md"],
                }
            ],
            "libraries": [{"name": "notes", "plugins": ["notes"]}],
        }
    )
    webdav.write("prompts/a/p.md", PROMPT.format(body="the served body"))
    webdav.write("prompts/b/p.md", PROMPT.format(body="the losing body"))
    kb = KnowledgeBase(config, tmp_path / "cache")
    assert "first" in read_served(kb, URI)
    assert [p.template for p in kb.prompts] == ["the served body\n"]
    webdav.write("prompts/b/p.md", "no frontmatter here, and longer than before\n")
    webdav.skill("x", "edited in nextcloud, and rather longer than before")
    with caplog.at_level(logging.WARNING, logger="kubed.mcp_kb"):
        assert "first" in read_served(kb, URI), "N6: the re-adding read"
        assert "edited in nextcloud" in read_served(kb, URI)
    assert not [r for r in caplog.records if "not read again" in r.getMessage()]


# -- and what it does not ------------------------------------------------------


def test_a_manifest_is_priced_against_the_server_before_it_is_served(
    webdav, tmp_path
):
    """A size and a hash are claims about bytes. Served without revalidating,
    they describe the copy on disk and the very next read serves something
    else."""
    knowledge_base = _knowledge_base(webdav, tmp_path)
    manifest = "skill://notes/x/_manifest"

    def size() -> int:
        files = json.loads(read_served(knowledge_base, manifest))["files"]
        return next(f["size"] for f in files if f["path"] == "SKILL.md")

    before = size()
    webdav.skill("x", "edited in nextcloud, and rather longer than before")

    assert size() == before, "N6: the read that re-adds still prices its pin"
    assert size() > before


def test_a_new_upstream_file_needs_a_refresh(webdav, tmp_path):
    """Revalidation prices a file that has a URI. A new one has none yet."""
    knowledge_base = _knowledge_base(webdav, tmp_path)
    webdav.skill("y", "a skill added after the folder was indexed")

    assert read_served(knowledge_base, "skill://notes/y/SKILL.md") is None
    assert [s.name for s in knowledge_base.index.visible()] == ["x"]

    assert knowledge_base.refresh() == [KEY]
    assert "a skill added after" in read_served(knowledge_base, "skill://notes/y/SKILL.md")


def test_reads_within_the_ttl_do_not_hit_the_server(webdav, tmp_path, monkeypatch):
    """One read of a skill is several reads of its files; one PROPFIND is enough."""
    monkeypatch.setattr(live, "TTL_SECONDS", 60.0)
    knowledge_base = _knowledge_base(webdav, tmp_path)
    read_served(knowledge_base, URI)
    webdav.requests.clear()

    read_served(knowledge_base, URI)
    read_served(knowledge_base, URI)

    assert webdav.requests == []


def test_a_snapshot_source_never_revalidates(webdav, tmp_path, monkeypatch):
    """The default dial is disk and nothing else: not one request on a read."""
    knowledge_base = _knowledge_base(webdav, tmp_path, cache="snapshot")
    reached = []

    def boom(*args, **kwargs):
        # Recorded as well as raised: a revalidator swallows what a read
        # raises, so a raise alone would leave this test green either way.
        reached.append(args)
        raise AssertionError("a snapshot source must not touch the network")

    monkeypatch.setattr(live, "fetch_file", boom)
    webdav.requests.clear()

    assert "first" in read_served(knowledge_base, URI)
    assert read_served(knowledge_base, GUIDE) == "library-level guidance\n"
    assert reached == [], "the read path never reached the network"
    assert webdav.requests == []


# -- degrading --------------------------------------------------------------


def test_a_flaky_server_degrades_to_the_cached_copy(webdav, tmp_path):
    """A read is answered from disk whatever the network is doing.

    The copy is on disk and complete; a server that has stopped answering is a
    reason to serve it unrevalidated, never a reason to fail the read.
    """
    knowledge_base = _knowledge_base(webdav, tmp_path)
    assert "first" in read_served(knowledge_base, URI)

    webdav.stop()

    assert "first" in read_served(knowledge_base, URI)
    assert read_served(knowledge_base, GUIDE) == "library-level guidance\n"


def test_a_failed_revalidation_says_nothing_about_the_credentials(
    webdav, tmp_path, caplog
):
    knowledge_base = _knowledge_base(webdav, tmp_path)
    read_served(knowledge_base, URI)
    webdav.stop()

    with caplog.at_level("WARNING"):
        read_served(knowledge_base, URI)

    assert caplog.text, "a revalidation that failed is worth a line in the log"
    assert PASSWORD not in caplog.text
    assert USERNAME not in caplog.text


def test_a_failed_revalidation_names_the_source_once(webdav, tmp_path, caplog):
    """fetch_file's error already carries the fetch, and the log line adds it:
    `notes://kb: revalidating … failed: notes://kb: …` reads as two fetches."""
    knowledge_base = _knowledge_base(webdav, tmp_path)
    read_served(knowledge_base, URI)
    webdav.stop()

    with caplog.at_level("WARNING"):
        read_served(knowledge_base, URI)

    assert caplog.text.count(f"{KEY}:") == 1
    assert caplog.text.count("skills/x/SKILL.md") == 1


def test_a_server_that_hangs_is_asked_once_and_then_left_alone(
    tmp_path, black_hole, monkeypatch, caplog
):
    """The measured collapse: every read paid httpx's 5s default against a 2s
    TTL, and repeats of the *same* file paid it too.

    Two things stop it. The revalidation client has a timeout well under the
    TTL, so one read costs a bounded moment; and a failure puts the source in a
    cooldown, so nothing after the first pays anything at all.

    "Nothing" is counted, not timed: a read that never asks the hung server
    cannot wait on it, and a wall-clock bound on the repeats only measures the
    runner (one of them took 122 ms on a loaded 3.11 job, against 50 ms).
    """
    monkeypatch.setattr(live, "REVALIDATE_TIMEOUT", 0.2)
    monkeypatch.setattr(live, "COOLDOWN_SECONDS", 60.0)
    knowledge_base = black_hole(tmp_path)
    asked: list[str] = []
    asking = live.fetch_file

    def counted(fetch, root, rel, *args, **kwargs):
        asked.append(rel)
        return asking(fetch, root, rel, *args, **kwargs)

    monkeypatch.setattr(live, "fetch_file", counted)

    with caplog.at_level("WARNING"):
        first = _elapsed(knowledge_base, URI)
        once = len(asked)
        for _ in range(5):
            read_served(knowledge_base, URI)
        repeats = len(asked) - once
        read_served(knowledge_base, GUIDE)
        other = len(asked) - once - repeats

    assert once >= 1, "the first read asks the server"
    assert "first" in read_served(knowledge_base, URI), "the cached copy is still served"
    assert first < 1.0, f"one read must not cost the httpx default: {first:.2f}s"
    assert repeats == 0, f"a wedged server must not be asked twice: {asked}"
    assert other == 0, f"the cooldown covers the source, not the one file: {asked}"
    assert caplog.text.count("revalidating") == 1


async def test_health_says_a_live_source_is_cooling_after_a_failure(
    webdav, tmp_path, monkeypatch
):
    """An operator reading /health has to be able to tell "nothing changed"
    from "we stopped asking"."""
    knowledge_base = _knowledge_base(webdav, tmp_path)
    read_served(knowledge_base, URI)
    monkeypatch.setattr(live, "fetch_file", _wedged)
    read_served(knowledge_base, URI)

    transport = httpx.ASGITransport(app=server_of(knowledge_base).http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://knowledge_base") as http:
        body = (await http.get("/health")).json()

    assert body["fetches"][KEY]["cooling"] is True


def test_a_source_that_answers_again_stops_cooling(webdav, tmp_path, monkeypatch):
    """The cooldown is a pause, not a verdict: a folder comes back by itself."""
    monkeypatch.setattr(live, "COOLDOWN_SECONDS", 0.05)
    knowledge_base = _knowledge_base(webdav, tmp_path)
    answering = live.fetch_file
    monkeypatch.setattr(live, "fetch_file", _wedged)
    read_served(knowledge_base, URI)
    assert knowledge_base.snapshot.stats(KEY)["cooling"] is True

    monkeypatch.setattr(live, "fetch_file", answering)
    time.sleep(0.1)
    read_served(knowledge_base, URI)

    assert "cooling" not in knowledge_base.snapshot.stats(KEY)


def test_the_ttl_runs_from_the_answer_and_not_from_the_question(
    webdav, tmp_path, monkeypatch
):
    """Stamped before the request but measured against elapsed time, a request
    slower than the TTL leaves the same file due for another the instant it
    comes back -- so a slow server is asked once per read, not once per TTL."""
    monkeypatch.setattr(live, "TTL_SECONDS", 0.3)
    knowledge_base = _knowledge_base(webdav, tmp_path)
    read_served(knowledge_base, URI)
    answering = live.fetch_file

    def slow(*args, **kwargs):
        time.sleep(0.4)
        return answering(*args, **kwargs)

    time.sleep(0.35)
    monkeypatch.setattr(live, "fetch_file", slow)
    read_served(knowledge_base, URI)

    monkeypatch.setattr(live, "fetch_file", answering)
    webdav.requests.clear()
    read_served(knowledge_base, URI)

    assert webdav.requests == [], "the TTL must bound a slow server too"


# -- the machinery ------------------------------------------------------------


def test_the_revalidator_follows_the_export_a_refresh_created(webdav, tmp_path):
    """A refresh moves the source to a new directory; live reads must follow it.

    A revalidator that outlived its snapshot would go on writing into the
    export nothing is serving any more, and the edit would never appear.
    """
    knowledge_base = _knowledge_base(webdav, tmp_path)
    retired = knowledge_base.index.get("notes/x").path
    webdav.skill("y", "a second skill, which moves the whole folder's digest")
    assert knowledge_base.refresh() == [KEY]
    current = knowledge_base.index.get("notes/x").path
    assert current != retired

    webdav.skill("x", "edited after the refresh, and longer than it was")

    read_served(knowledge_base, URI)  # N6: this one re-adds the plugin
    assert "edited after the refresh" in read_served(knowledge_base, URI)
    assert "first" in (retired / "SKILL.md").read_text(), "the retired export stands"


def test_one_client_serves_every_live_read(webdav, tmp_path, monkeypatch):
    """A client per read is a TCP connection and a TLS handshake per read."""
    knowledge_base = _knowledge_base(webdav, tmp_path)
    built = []
    original = live.client

    def counted(fetch, **kwargs):
        built.append(fetch.key)
        return original(fetch, **kwargs)

    monkeypatch.setattr(live, "client", counted)

    read_served(knowledge_base, URI)
    read_served(knowledge_base, URI)
    read_served(knowledge_base, GUIDE)

    assert built == [KEY]


async def test_health_reports_what_a_live_source_revalidated(webdav, tmp_path):
    knowledge_base = _knowledge_base(webdav, tmp_path)
    read_served(knowledge_base, URI)
    webdav.skill("x", "edited in nextcloud, and rather longer than before")
    read_served(knowledge_base, URI)

    transport = httpx.ASGITransport(app=server_of(knowledge_base).http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://knowledge_base") as http:
        body = (await http.get("/health")).json()

    fetch = body["fetches"][KEY]
    assert fetch["live"] is True
    # Once per request that reads skills, and once for the first build.
    assert fetch["revalidated"] == 3
    assert fetch["fetched"] == 1


async def test_health_says_nothing_about_the_backend_or_the_credentials(
    webdav, tmp_path
):
    """A backend is config-only, and /health is not where it stops being one."""
    knowledge_base = _knowledge_base(webdav, tmp_path)
    read_served(knowledge_base, URI)

    transport = httpx.ASGITransport(app=server_of(knowledge_base).http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://knowledge_base") as http:
        body = (await http.get("/health")).text

    assert PASSWORD not in body
    assert "127.0.0.1" not in body
    assert "SKILL.md" not in body, "the fingerprint is a digest, not a file listing"


def test_a_snapshot_source_reports_no_live_fields(webdav, tmp_path):
    knowledge_base = _knowledge_base(webdav, tmp_path, cache="snapshot")

    assert "live" not in knowledge_base.status["fetches"][KEY]


# -- re-reading on view (D9) ----------------------------------------------------


@pytest.fixture
def clock(monkeypatch):
    """The revalidator's clock, moved on by hand: past the 2 s trust without
    sleeping through it. Only ``sources/live.py`` reads it."""
    offset = [0.0]
    monkeypatch.setattr(
        live, "time", SimpleNamespace(monotonic=lambda: time.monotonic() + offset[0])
    )
    monkeypatch.setattr(live, "TTL_SECONDS", 2.0)

    def advance(seconds: float) -> None:
        offset[0] += seconds

    return advance


def _live_config(webdav, tmp_path, plugins, libraries):
    """A knowledge base over the live source ``notes`` with these plugins."""
    config = Config.model_validate(
        {
            "sources": [
                {
                    "name": "notes",
                    "url": webdav.url,
                    "auth": {"username": USERNAME, "password": {"env": ENV}},
                    "cache": "live",
                }
            ],
            "plugins": plugins,
            "libraries": libraries,
        }
    )
    return KnowledgeBase(config, tmp_path / "cache")


def _two_libraries(webdav, tmp_path):
    """``notes`` as ``_knowledge_base`` has it, and ``other``, a plugin in a
    folder of the same live source, in a library of its own."""
    webdav.write(
        "other/skills/z/SKILL.md", "---\nname: z\ndescription: Z.\n---\n\nz\n"
    )
    return _live_config(
        webdav,
        tmp_path,
        [
            {"name": "notes", "source": KEY},
            {"name": "other", "source": f"{KEY}//other"},
        ],
        [
            {"name": "notes", "plugins": ["notes"]},
            {"name": "other", "plugins": ["other"]},
        ],
    )


def _skill_view(knowledge_base) -> tuple[str, dict, dict]:
    """One client, three requests: ``URI``, its ``_manifest`` and ``skills/get``."""

    async def read(client):
        text = (await client.read_resource(URI))[0].text
        manifest = json.loads(
            (await client.read_resource(f"{SKILL}/_manifest"))[0].text
        )
        entry = await ext_request(client, "skills/get", uri=URI)
        return text, manifest, entry

    return run_client(knowledge_base, read)


def test_a_live_edit_reads_after_trust(webdav, tmp_path, clock):
    """D9: within the 2 s trust an edit is not looked for; past it, the read
    that revalidates re-adds the plugin and still serves its pin, and the read
    after it serves the edit, its ``_manifest`` and its entry agreeing (N6)."""
    knowledge_base = _knowledge_base(webdav, tmp_path)
    assert "first" in read_served(knowledge_base, URI)

    webdav.write("skills/x/SKILL.md", EDITED)
    assert "first" in read_served(knowledge_base, URI), "trusted for 2 s"

    clock(2.5)
    assert "first" in read_served(knowledge_base, URI), "N6: the re-adding read"
    text, manifest, entry = _skill_view(knowledge_base)

    assert "edited in nextcloud" in text
    size = len(EDITED.encode())
    digest = hashlib.sha256(EDITED.encode()).hexdigest()
    listed = next(f for f in manifest["files"] if f["path"] == "SKILL.md")
    assert listed["size"] == size
    assert digest in listed["hash"]
    assert entry["skill"]["frontmatter"]["description"] == "Edited upstream."
    resource = next(r for r in entry["skill"]["resources"] if r["uri"] == URI)
    assert resource["digest"] == f"sha256:{digest}"
    assert resource["size"] == size
    assert knowledge_base.generation == 0, "the read did it, not a refresh"


def test_a_reread_keeps_every_other_plugin(webdav, tmp_path):
    """Only the plugin whose file moved is read again; the rest are kept as served."""
    knowledge_base = _two_libraries(webdav, tmp_path)
    mcp = serving_of(knowledge_base)._mcp
    before = {p.namespace: p for p in mcp.plugins}
    generation = mcp.generation
    assert set(before) == {"notes", "other"}

    webdav.skill("x", "edited in nextcloud, and rather longer than before")
    read_served(knowledge_base, URI)
    assert "edited in nextcloud" in read_served(knowledge_base, URI)

    after = {p.namespace: p for p in mcp.plugins}
    assert after["other"] is before["other"]
    assert after["notes"] is not before["notes"]
    assert mcp.generation == generation + 1


def test_no_reread_while_a_refresh_publishes(webdav, tmp_path):
    """The serving lock is taken without blocking: a publish holding it is
    about to serve a new set anyway, so the request reads what is served."""
    knowledge_base = _knowledge_base(webdav, tmp_path)
    serving = serving_of(knowledge_base)
    mcp = serving._mcp
    generation = mcp.generation
    webdav.skill("x", "edited in nextcloud, and rather longer than before")

    with serving._lock:
        assert "first" in read_served(knowledge_base, URI)
        assert "first" in read_served(knowledge_base, URI)
        assert mcp.generation == generation

    read_served(knowledge_base, URI)
    assert "edited in nextcloud" in read_served(knowledge_base, URI)
    assert mcp.generation == generation + 1


async def test_an_out_of_scope_live_skill_is_not_revalidated(webdav, tmp_path):
    """Only the plugins a request's scope admits are revalidated."""
    knowledge_base = _two_libraries(webdav, tmp_path)
    serving_of(knowledge_base)
    webdav.requests.clear()

    with serve_http(knowledge_base) as url:
        async with http_client(url + "?library=other") as client:
            assert "z" in (await client.read_resource(OTHER))[0].text

    paths = [path for _, path in webdav.requests]
    assert f"/{FOLDER}/other/skills/z/SKILL.md" in paths, "the admitted one is"
    assert not [p for p in paths if p.startswith(f"/{FOLDER}/skills/")]


def test_a_live_agent_edit_reads_after_trust(webdav, tmp_path, clock, caplog):
    """N6 for an agent: the request after the re-adding one serves the edit, on
    ``agents/get`` and ``agents/list`` both; an edit that no longer parses
    keeps the plugin's last good build, said once (AGT-16), and the next good
    one is served."""
    webdav.write(".claude-plugin/plugin.json", json.dumps({"name": "notes"}))
    webdav.write(
        "agents/helper.md", AGENT.format(description="Helps.", body="Help first.")
    )
    knowledge_base = _knowledge_base(webdav, tmp_path)
    name = "notes_helper"

    async def served(client):
        return await ext_request(client, "agents/get", name=name)

    assert run_client(knowledge_base, served)["instructions"] == "Help first."

    def edit(text: str):
        webdav.write("agents/helper.md", text)
        clock(2.5)

        async def go(client):
            try:
                first = await ext_request(client, "agents/get", name=name)
            except MCPError:
                first = None
            try:
                got = await ext_request(client, "agents/get", name=name)
            except MCPError:
                got = None
            listed = (await ext_request(client, "agents/list"))["agents"]
            return first, got, {card["name"]: card for card in listed}

        return run_client(knowledge_base, go)

    first, got, listed = edit(
        AGENT.format(description="Helps, edited upstream.", body="Help, edited.")
    )
    assert first["instructions"] == "Help first.", "N6: the re-adding request"
    assert got["instructions"] == "Help, edited."
    for key in ("io.kubed/agent", "io.kubed.mcp-kb/agent"):
        assert got["_meta"][key]["frontmatter"]["description"] == (
            "Helps, edited upstream."
        ), key
    assert listed[name]["description"] == "Helps, edited upstream."

    first, got, listed = edit(  # an unquoted `[a] [b]` is no YAML at all
        "---\nname: helper\ndescription: [a] [b]\n---\n\nHalfway through a save.\n"
    )
    assert first["instructions"] == "Help, edited."
    assert got["instructions"] == "Help, edited.", "AGT-16: the last good build"
    assert listed[name]["description"] == "Helps, edited upstream."
    assert "was not read again" in caplog.text and "agents/helper.md" in caplog.text

    first, got, listed = edit(
        AGENT.format(description="Helps again.", body="Help, saved properly.")
    )
    assert first["instructions"] == "Help, edited.", "N6: the re-adding request"
    assert got["instructions"] == "Help, saved properly."
    assert listed[name]["description"] == "Helps again."


def test_a_live_agent_saved_with_an_unusable_name_keeps_its_name(
    webdav, tmp_path, clock, caplog
):
    """AGT-16: an edit to a name the plugin layer refuses keeps the plugin's last
    good build, the agent under its name and with its body, said once and with
    no cache path in it."""
    webdav.write(".claude-plugin/plugin.json", json.dumps({"name": "notes"}))
    webdav.write(
        "agents/helper.md", AGENT.format(description="Helps.", body="Help first.")
    )
    knowledge_base = _knowledge_base(webdav, tmp_path)

    async def names(client):
        listed = (await ext_request(client, "agents/list"))["agents"]
        return {card["name"] for card in listed}

    assert run_client(knowledge_base, names) == {"notes_helper"}

    webdav.write(
        "agents/helper.md",
        '---\nname: "a b"\ndescription: Helps, renamed.\n---\n\nRenamed.\n',
    )
    clock(2.5)

    async def go(client):
        first = await names(client)
        then = await names(client)
        got = await ext_request(client, "agents/get", name="notes_helper")
        return first, then, got

    first, then, got = run_client(knowledge_base, go)
    assert first == {"notes_helper"}, "N6: the re-adding request"
    assert then == {"notes_helper"}, "AGT-16: the agent keeps its name"
    assert got["instructions"] == "Help first."
    assert got["_meta"]["io.kubed.mcp-kb/agent"]["frontmatter"]["name"] == "helper"
    kbs = [r.getMessage() for r in caplog.records if r.name.startswith("kubed.mcp_kb")]
    warned = [message for message in kbs if "agents/helper.md" in message]
    assert len(warned) == 1, warned
    assert "was not read again" in warned[0]
    assert "is not a usable name" in warned[0]
    assert not [message for message in kbs if str(tmp_path) in message]


def test_a_live_edit_taking_a_twins_name_serves_the_first_in_path_order(
    webdav, tmp_path, clock
):
    """AGT-16's carve-out: an edit that gives an agent the name another file of
    its plugin serves still reads, so no build is kept. From the next request
    the first file in path order is served under that name and the other is
    skipped (AGT-6), as a refresh of the same tree serves them."""
    webdav.write(".claude-plugin/plugin.json", json.dumps({"name": "notes"}))
    webdav.write(
        "agents/alpha.md", "---\nname: alpha\ndescription: A.\n---\n\nAlpha's.\n"
    )
    webdav.write(
        "agents/helper.md", AGENT.format(description="Helps.", body="Helper's.")
    )
    knowledge_base = _knowledge_base(webdav, tmp_path)

    async def names(client):
        listed = (await ext_request(client, "agents/list"))["agents"]
        return {card["name"] for card in listed}

    assert run_client(knowledge_base, names) == {"notes_alpha", "notes_helper"}

    webdav.write(
        "agents/alpha.md",
        "---\nname: helper\ndescription: A, renamed.\n---\n\nAlpha's, renamed.\n",
    )
    clock(2.5)

    async def go(client):
        first = await names(client)
        then = await names(client)
        got = await ext_request(client, "agents/get", name="notes_helper")
        return first, then, got

    first, then, got = run_client(knowledge_base, go)
    assert first == {"notes_alpha", "notes_helper"}, "N6: the re-adding request"
    assert then == {"notes_helper"}, "AGT-6: one name, the first file in path order"
    assert got["instructions"] == "Alpha's, renamed."
    assert knowledge_base.generation == 0, "no refresh did it"


def test_a_live_watch_stamps_the_agents_the_manifest_lists(webdav, tmp_path, clock):
    """I2: the watch stamps the agent files kb harvested, which a ``plugin.json``
    listing ``agents`` decides, not the config's globs: an edit to the listed
    ``roles/r.md`` re-reads, one to the unlisted ``agents/old.md`` does not."""
    webdav.write(
        ".claude-plugin/plugin.json",
        json.dumps({"name": "notes", "agents": ["./roles/r.md"]}),
    )
    webdav.write("roles/r.md", AGENT.format(description="Roles.", body="Role first."))
    webdav.write(
        "agents/old.md",
        "---\nname: old\ndescription: Old.\n---\n\nNot listed.\n",
    )
    knowledge_base = _knowledge_base(webdav, tmp_path)
    mcp = serving_of(knowledge_base)._mcp
    name = "notes_helper"

    async def twice(client):
        first = await ext_request(client, "agents/get", name=name)
        got = await ext_request(client, "agents/get", name=name)
        return first, got

    assert run_client(knowledge_base, twice)[1]["instructions"] == "Role first."
    generation = mcp.generation

    webdav.write(
        "agents/old.md",
        "---\nname: old\ndescription: Old, edited.\n---\n\nNot listed, and longer.\n",
    )
    clock(2.5)
    run_client(knowledge_base, twice)
    assert mcp.generation == generation, "an unlisted file is not watched"

    webdav.write(
        "roles/r.md", AGENT.format(description="Roles, edited.", body="Role, edited.")
    )
    clock(2.5)
    first, got = run_client(knowledge_base, twice)
    assert first["instructions"] == "Role first.", "N6: the re-adding request"
    assert got["instructions"] == "Role, edited."
    assert mcp.generation == generation + 1


def test_no_reread_while_a_refresh_builds(webdav, tmp_path, monkeypatch):
    """A refresh points the fetch at its new export before it builds and
    publishes. A re-read in that window would add the plugin from the new tree
    while N13's check still walks the old one, so it waits for the publish."""
    knowledge_base = _knowledge_base(webdav, tmp_path)
    mcp = serving_of(knowledge_base)._mcp
    seen = {}
    build = knowledge_base._build

    def building(*args, **kwargs):
        generation = mcp.generation
        read_served(knowledge_base, URI)
        seen["hidden"] = read_served(knowledge_base, f"{SKILL}/.secret.md")
        read_served(knowledge_base, URI)
        seen["moved"] = mcp.generation - generation
        return build(*args, **kwargs)

    webdav.skill("x", "edited in nextcloud, and rather longer than before")
    webdav.write("skills/x/.secret.md", "SECRET=1\n")
    webdav.skill("y", "a second skill, which moves the whole folder's digest")
    monkeypatch.setattr(knowledge_base, "_build", building)

    assert knowledge_base.refresh() == [KEY]

    assert seen == {"hidden": None, "moved": 0}
    assert read_served(knowledge_base, f"{SKILL}/.secret.md") is None
    assert read_served(knowledge_base, URI) is None, "N13: x holds a hidden file"


def test_a_publisher_that_raises_leaves_the_records_as_they_were(
    webdav, tmp_path, monkeypatch
):
    """I3: a refresh whose publish raises keeps the fetches, plugins, libraries
    and records it had, so live re-reads go on against the tree being served,
    and the next refresh publishes the new content."""
    knowledge_base = _knowledge_base(webdav, tmp_path)
    mcp = serving_of(knowledge_base)._mcp
    snapshot = knowledge_base.snapshot
    before = (
        knowledge_base._fetches,
        knowledge_base._plugins,
        knowledge_base._libraries,
        knowledge_base._records,
    )
    publish = knowledge_base._publish
    raised = []

    def flaky(published):
        if not raised:
            raised.append(published.generation)
            raise RuntimeError("the plugin layer fell over")
        return publish(published)

    monkeypatch.setattr(knowledge_base, "_publish", flaky)
    webdav.skill("x", "edited for the refresh that fails to publish")
    with pytest.raises(RuntimeError, match="fell over"):
        knowledge_base.refresh(force=True)
    assert raised
    assert knowledge_base.snapshot is snapshot
    assert (
        knowledge_base._fetches,
        knowledge_base._plugins,
        knowledge_base._libraries,
        knowledge_base._records,
    ) == before

    # Live re-reads resume against the tree being served (N6: one request late).
    webdav.skill("x", "edited live after the failed refresh, and longer again")
    read_served(knowledge_base, URI)
    assert "edited live after the failed refresh" in read_served(knowledge_base, URI)

    webdav.skill("x", "edited for the refresh that publishes, much longer than that")
    generation = mcp.generation
    assert knowledge_base.refresh(force=True) == [KEY]
    assert knowledge_base.snapshot.generation == snapshot.generation + 1
    assert mcp.generation > generation
    assert "edited for the refresh that publishes" in read_served(knowledge_base, URI)

    webdav.skill("x", "and live again after it, the longest edit of all of them")
    read_served(knowledge_base, URI)
    assert "and live again after it" in read_served(knowledge_base, URI)


def test_a_reread_that_reads_a_new_export_is_abandoned(
    webdav, tmp_path, monkeypatch
):
    """The root a moved plugin is added from is checked after it is read, not
    only before: a refresh that points the fetch at a new export in between
    leaves the re-read unserved, for the refresh to publish."""
    import dataclasses
    import shutil

    from kubed.mcp_kb.sources import ServedTrees

    knowledge_base = _knowledge_base(webdav, tmp_path)
    mcp = serving_of(knowledge_base)._mcp
    generation = mcp.generation
    snapshot = knowledge_base.snapshot
    old = knowledge_base.served_tree(KEY)
    new = tmp_path / "next-export"
    shutil.copytree(old, new)
    (new / "skills/x/.secret.md").write_text("SECRET=1\n")
    real = ServedTrees.materialise
    switched = []

    def materialise(self, address):
        if not switched:
            # A refresh's assignment, landing as the moved plugin is read.
            record = knowledge_base._fetches[KEY]
            knowledge_base._fetches = {
                **knowledge_base._fetches,
                KEY: dataclasses.replace(record, root=str(new)),
            }
            switched.append(address)
        return real(self, address)

    monkeypatch.setattr(ServedTrees, "materialise", materialise)
    webdav.skill("x", "edited in nextcloud, and rather longer than before")

    read_served(knowledge_base, URI)
    assert switched, "the moved plugin was read"
    assert read_served(knowledge_base, f"{SKILL}/.secret.md") is None
    assert "first" in read_served(knowledge_base, URI)
    assert mcp.generation == generation
    assert knowledge_base.snapshot is snapshot


def test_no_reread_between_a_publish_and_its_swap(webdav, tmp_path, monkeypatch):
    """A set served but not yet swapped in: the request reads what is served
    and leaves the swap to land."""
    knowledge_base = _knowledge_base(webdav, tmp_path)
    mcp = serving_of(knowledge_base)._mcp
    seen = {}
    publish = knowledge_base._publish

    def published(snapshot):
        narrowed = publish(snapshot)
        webdav.skill("x", "edited again while the swap is pending, and longer")
        generation = mcp.generation
        read_served(knowledge_base, URI)
        read_served(knowledge_base, URI)
        seen["moved"] = mcp.generation - generation
        return narrowed

    webdav.skill("y", "a second skill, which moves the whole folder's digest")
    monkeypatch.setattr(knowledge_base, "_publish", published)
    assert knowledge_base.refresh() == [KEY]

    assert seen == {"moved": 0}
    read_served(knowledge_base, URI)  # N6: this one re-adds the plugin
    assert "edited again" in read_served(knowledge_base, URI)


def test_a_reread_that_cannot_serve_says_so_once(webdav, tmp_path, monkeypatch, caplog):
    """A re-read whose set will not serve leaves what is served, logs once
    with no cache path, and is not tried again until a file moves again."""
    knowledge_base = _knowledge_base(webdav, tmp_path)
    mcp = serving_of(knowledge_base)._mcp
    generation = mcp.generation
    tree = knowledge_base.served_tree(KEY)
    calls = []

    def refused(staging):
        calls.append(staging)
        raise RuntimeError(f"the set at {tree.resolve()} and {tree} is not served")

    monkeypatch.setattr(mcp, "serve", refused)
    webdav.skill("x", "edited in nextcloud, and rather longer than before")

    with caplog.at_level("WARNING"):
        for _ in range(4):
            assert "first" in read_served(knowledge_base, URI)

    assert len(calls) == 1, "no retry until a file moves again"
    assert mcp.generation == generation
    failures = [r for r in caplog.records if "re-reading" in r.getMessage()]
    assert len(failures) == 1
    assert str(tmp_path) not in caplog.text
    assert KEY in failures[0].getMessage()


def test_a_plugin_refused_at_publish_is_not_reread(webdav, tmp_path, monkeypatch):
    """A plugin kubed-mcp refused is not served, so a re-read neither
    revalidates nor adds it, whatever the scope: its conflict carries over."""
    from kubed.mcp.plugins import PluginError, PluginSet

    real = PluginSet.add
    asked = []

    def add(self, address, *, namespace=None, manifest=None):
        asked.append(namespace)
        if namespace == "other":
            raise PluginError("other is refused here")
        return real(self, address, namespace=namespace, manifest=manifest)

    monkeypatch.setattr(PluginSet, "add", add)
    knowledge_base = _two_libraries(webdav, tmp_path)
    serving_of(knowledge_base)
    conflicts = knowledge_base.status["libraries"]["other"]["conflicts"]
    assert conflicts == {"other": "conflict: other is refused here"}
    assert asked == ["notes", "other"]
    webdav.requests.clear()

    webdav.skill("x", "edited in nextcloud, and rather longer than before")
    read_served(knowledge_base, URI)
    assert "edited in nextcloud" in read_served(knowledge_base, URI)

    assert asked == ["notes", "other", "notes"]
    assert not [p for _, p in webdav.requests if p.startswith(f"/{FOLDER}/other/")]
    assert knowledge_base.status["libraries"]["other"]["conflicts"] == conflicts


def test_a_kept_plugins_agents_are_not_read_again(webdav, tmp_path, monkeypatch):
    """A re-read reads the moved plugin; a kept one's agents are what its last
    add read, not whatever its folder holds now."""
    from kubed.mcp_kb.mcp import skills as serving_module

    webdav.write(".claude-plugin/plugin.json", json.dumps({"name": "notes"}))
    webdav.write("other/.claude-plugin/plugin.json", json.dumps({"name": "other"}))
    webdav.write("other/agents/z.md", AGENT.format(description="Z.", body="Zed."))
    knowledge_base = _two_libraries(webdav, tmp_path)
    serving_of(knowledge_base)
    read = []
    original = serving_module._frontmatter

    def counted(root, path):
        read.append(path)
        return original(root, path)

    monkeypatch.setattr(serving_module, "_frontmatter", counted)
    webdav.skill("x", "edited in nextcloud, and rather longer than before")
    read_served(knowledge_base, URI)
    assert "edited in nextcloud" in read_served(knowledge_base, URI)

    assert "agents/z.md" not in read

    async def get(client):
        return await ext_request(client, "agents/get", name="other_helper")

    got = run_client(knowledge_base, get)
    assert got["instructions"] == "Zed."
    assert got["_meta"]["io.kubed.mcp-kb/agent"]["frontmatter"]["description"] == "Z."


def test_a_kept_local_plugins_agents_are_not_read_again(webdav, tmp_path, caplog):
    """A re-read keeps every plugin that is not live as its last add read it,
    agents included: a ``file://`` agent edited in place serves what the layer
    read, kb's ``frontmatter`` agreeing with the layer's, and one saved halfway
    through stays listed, with no ``agent_meta`` failure (AGT-16)."""
    webdav.write(".claude-plugin/plugin.json", json.dumps({"name": "notes"}))
    local = tmp_path / "kit"
    (local / ".claude-plugin").mkdir(parents=True)
    (local / ".claude-plugin/plugin.json").write_text(json.dumps({"name": "kit"}))
    (local / "agents").mkdir()
    agent = local / "agents/aide.md"
    agent.write_text("---\nname: aide\ndescription: Aids.\n---\n\nKit's.\n")
    knowledge_base = _live_config(
        webdav,
        tmp_path,
        [
            {"name": "notes", "source": KEY},
            {"name": "kit", "source": f"file://{local}"},
        ],
        [
            {"name": "notes", "plugins": ["notes"]},
            {"name": "kit", "plugins": ["kit"]},
        ],
    )
    name = "kit_aide"

    async def go(client):
        got = await ext_request(client, "agents/get", name=name)
        listed = (await ext_request(client, "agents/list"))["agents"]
        return got, {card["name"]: card for card in listed}

    assert run_client(knowledge_base, go)[0]["instructions"] == "Kit's."

    def reread(text: str, edit: str):
        agent.write_text(text)
        webdav.skill("x", edit)
        read_served(knowledge_base, URI)
        assert edit in read_served(knowledge_base, URI), "the live plugin re-read"
        return run_client(knowledge_base, go)

    with caplog.at_level("WARNING"):
        got, listed = reread(
            "---\nname: aide\ndescription: Aids, edited in place.\n---\n\nKit's, longer.\n",
            "edited in nextcloud, and rather longer than before",
        )
        layer = got["_meta"]["io.kubed/agent"]["frontmatter"]
        assert got["_meta"]["io.kubed.mcp-kb/agent"]["frontmatter"] == layer
        assert layer["description"] == "Aids."
        assert listed[name]["description"] == "Aids."

        got, listed = reread(
            "---\nname: aide\n---\n\nSaved halfway through.\n",
            "edited in nextcloud a second time, and longer again than that",
        )
    assert name in listed, "AGT-16: a kept plugin's agent stays served"
    assert got["_meta"]["io.kubed.mcp-kb/agent"]["frontmatter"]["description"] == (
        "Aids."
    )
    assert "agent_meta failed" not in caplog.text


def test_a_live_rename_renames_a_later_clashing_agent(webdav, tmp_path):
    """N6: a live edit of an agent's frontmatter ``name`` is served under the
    new name from the next request, without a refresh, and a later plugin's
    agent it now clashes with is renamed ``<name>@<plugin>`` (PLUG-64)."""
    webdav.write(".claude-plugin/plugin.json", json.dumps({"name": "notes"}))
    webdav.write("agents/helper.md", AGENT.format(description="Helps.", body="Mine."))
    webdav.write("kit/.claude-plugin/plugin.json", json.dumps({"name": "kit"}))
    webdav.write(
        "kit/agents/aide.md",
        "---\nname: aide\ndescription: Aids.\n---\n\nKit's.\n",
    )
    knowledge_base = _live_config(
        webdav,
        tmp_path,
        [
            {"name": "notes", "source": KEY},
            {"name": "kit", "source": f"{KEY}//kit"},
        ],
        [{"name": "notes", "plugins": ["notes", "kit"]}],
    )

    async def names(client):
        return {
            card["name"]
            for card in (await ext_request(client, "agents/list"))["agents"]
        }

    assert run_client(knowledge_base, names) == {"notes_helper", "notes_aide"}

    webdav.write(
        "agents/helper.md",
        "---\nname: aide\ndescription: Helps, renamed.\n---\n\nMine, renamed.\n",
    )

    async def go(client):
        first = await names(client)
        then = await names(client)
        mine = await ext_request(client, "agents/get", name="notes_aide")
        kits = await ext_request(client, "agents/get", name="notes_aide@kit")
        return first, then, mine, kits

    first, then, mine, kits = run_client(knowledge_base, go)
    assert first == {"notes_helper", "notes_aide"}, "N6: the re-adding request"
    assert then == {"notes_aide", "notes_aide@kit"}
    assert mine["instructions"] == "Mine, renamed."
    assert kits["instructions"] == "Kit's."
    assert knowledge_base.generation == 0, "no refresh did it"


# -- helpers -------------------------------------------------------------------


def _wedged(*args, **kwargs):
    """A revalidation against a server that never answers."""
    raise TimeoutError("timed out")


def _elapsed(knowledge_base, uri: str) -> float:
    start = time.monotonic()
    read_served(knowledge_base, uri)
    return time.monotonic() - start


@pytest.fixture
def black_hole(webdav, monkeypatch):
    """A knowledge base whose revalidations go to a socket that accepts and never answers.

    Not "refused", which is instant and is what the flaky-server test already
    covers. This is the Nextcloud failure mode that costs a timeout. The folder
    is indexed against the real server, so the copy on disk is whole and only
    the revalidation is wedged -- which is exactly the shape of the failure:
    every byte is already on disk and the server is what has gone quiet.
    """

    def build(tmp_path):
        knowledge_base = _knowledge_base(webdav, tmp_path)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(16)
        accepted: list[socket.socket] = []

        def accept():
            while True:
                try:
                    accepted.append(listener.accept()[0])
                except OSError:
                    return

        threading.Thread(target=accept, daemon=True).start()
        void = Fetch(
            key=KEY,
            backend="webdav",
            url=f"http://127.0.0.1:{listener.getsockname()[1]}/{FOLDER}",
            auth=BasicAuth(username=USERNAME, password=EnvRef(env=ENV)),
            cache="live",
        )
        answering = live.client
        monkeypatch.setattr(live, "client", lambda _, **kwargs: answering(void, **kwargs))
        monkeypatch.setattr(live, "TTL_SECONDS", 0.0)
        return knowledge_base

    return build
