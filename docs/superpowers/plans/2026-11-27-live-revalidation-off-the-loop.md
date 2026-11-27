# Live Revalidation Off the Event Loop Implementation Plan

> **History.** Proposed for #116 (PR #118, into `issue-112`, after #115 merged there as PR #117).
> The spec is #116's notes in `.issue/issues.md`, built to the parent's rulings of 2026-11-27 08:04
> and approved by the parent. The design is below, checked against the code on `issue-112`, and
> there is no separate design file. The branch had no draft spec. This plan finishes the spec. It
> settles the points the spec left to the plan and departs from it in four places, each marked
> **(changed)** below with its reason.

> **For agentic workers:** REQUIRED SUB-SKILL: Use skill://superpowers/subagent-driven-development/SKILL.md (recommended) or skill://superpowers/executing-plans/SKILL.md to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No request ever waits for a WebDAV server. A `cache: live` fetch is revalidated by one
background pass per generation, and the next request serves what that pass brought down.

**Architecture:** `Revalidator.revalidate(path)` keeps its signature. It stops doing network work
and only starts a single-flight daemon thread when the path's fetch is due. The thread lists each
due live fetch once and downloads the files whose ETag moved. Every caller (`_stamp`,
`Catalogue.live_stamp`, `LibraryFiles._serve`, `Snapshot.revalidate`) becomes disk-only without a
code change. The view's existing re-read (`_reread_live` → `renarrowed`) picks the new bytes up on
the next request. `KnowledgeBase.refresh` retires the revalidator of the snapshot it swaps out.

**Tech Stack:** Python ≥3.11, `threading`, webdav4 (`WebdavFileSystem`), kubed-mcp (pin
unchanged), pytest + pytest-asyncio, wsgidav/cheroot (`tests/webdav_server.py`), uvicorn
(`tests.conftest.serve_http`).

**Spec:** this plan's Design section and #116's notes in `.issue/issues.md`. The living spec rows
it changes are [skills.md](../specs/skills.md) SKL-37 and SKL-38,
[config-and-sources.md](../specs/config-and-sources.md) SRC-21, its bounds table, SRC-23 and
SRC-25, plus a new SRC-54, [agents.md](../specs/agents.md) AGT-16 and
[prompts.md](../specs/prompts.md) PRM-58. HTTP-10 and SRC-24 are checked and left as they are.

## Design

### What is on the branch now, read in the code

- `sources/live.py::Revalidator.revalidate(path)` runs on its caller's thread. It looks up a
  per-file TTL in `_checked[(fetch key, rel)]` and calls `webdav.fetch_file`, which sends one
  `fs.info(rel)` PROPFIND and, if the ETag moved, one GET. It also stamps `_checked`, `cooling_until`
  and the counters.
- Callers, all on the event loop during a request:
  - `mcp/skills.py::_stamp`, from `SkillServing._reread_live`, from `view()`. kubed-mcp calls
    `view()` synchronously for each pin (quick-mcp#86).
  - `catalogue/uris.py::Catalogue.live_stamp`, from `_stamp`.
  - `catalogue/skills.py::LibraryFiles._serve`, for library files and fallbacks.
  - `catalogue/snapshot.py::Snapshot.revalidate`, from `_stamp`.
- Two other callers are not on the loop: `_stamp` from `SkillServing._watch`, at publish time.
  That is the boot publish in `serve_through` and a refresh's publish on its worker thread.
- `webdav.fetch_file` has no caller outside `live.py` except `tests/test_webdav_source.py`.
  `webdav._etags(fetch, fs)` is the recursive listing (`fs.info("")`, then `fs.find("",
  detail=True)`), already used by `materialise_webdav` and `fingerprint_webdav`.
- `KnowledgeBase.refresh` swaps `self.snapshot` under `_lock`, and nothing retires the old
  snapshot's revalidator. `renarrowed` swaps in a `replace()` of the same generation, which shares
  `live`.
- **There is no 2.5-minute interval** (the issue's ask 2). `TTL_SECONDS = 2.0` is per file,
  `REVALIDATE_TIMEOUT = 1.0` and `COOLDOWN_SECONDS = 30.0`. The stall cadence comes from traffic:
  it is the first pinned request after 2 s of quiet whose scope admits a live plugin. The new TTL
  is per fetch, with the same 2 s.

### Decisions

- **D1. One seam.** `revalidate(path)`:
  1. Find the owning live fetch (`_owner`, as today). Return if there is none or the revalidator
     is retired.
  2. Return if the fetch is not due. It is due when `now >= live.cooling_until` and
     `now - live.passed_at >= ttl`.
  3. Take `_running.acquire(blocking=False)`. Return if a pass holds it.
  4. Start `threading.Thread(target=self._pass, name="kb-revalidate", daemon=True)` and keep it as
     `self._thread`. If `start()` raises, release `_running` and re-raise.
  No network call ever happens on the caller's thread: `client`, `remote_etags` and `download` are
  called only from `_pass`.
- **D2. The pass.** `_pass()` runs in the thread and releases `_running` in a `finally`. For each
  `_Live` that is due when the pass reaches it (the kicked fetch and any other due one), in
  construction order, it stops at once if retired. Otherwise it calls `_price(live)`:
  1. `listed = remote_etags(live.fetch, self._client(live))`.
  2. For each `rel` in `sorted(live.etags)`, stop if retired. A `rel` missing from `listed` is gone
     upstream: keep the local copy (SRC-24) and count nothing. Otherwise do `revalidated += 1`. If
     `listed[rel] != live.etags[rel]` or `(live.root / rel)` is not a file, call
     `download(live.fetch, live.root, rel, fs)`, then set `live.etags[rel] = listed[rel]` and do
     `fetched += 1`.
  3. A file listed upstream that the export lacks is ignored. New and renamed files stay the
     refresh's job (SRC-24).
  4. On success set `cooling_until = 0.0`. On any `Exception`, in the listing or in a GET, set
     `cooling_until = now + cooldown`, skip the rest of this fetch, and log one warning, unless
     retired (a retired pass logs nothing). Then go on with the next fetch.
  5. Either way, `passed_at = time.monotonic()` after the answer, so the TTL runs from the answer
     (SKL-38).
- **D3. Who touches `_Live`.** Only `_pass` writes `etags`, `fs`, the counters, `cooling_until`
  and `passed_at`. The kicker and `stats()` read only floats and ints, and `_owner` reads
  `live.root` and the list `self._fetches`, which is never changed after `__init__`. The per-file
  `_checked` dict goes. `_running` is the one primitive both sides touch. It is never taken
  blocking, so nobody waits on it. The pass never takes `KnowledgeBase._lock` or
  `SkillServing._lock`.
- **D4. One listing per fetch.** `webdav._etags` becomes public as `remote_etags` (same body),
  because `live.py` now imports it. `Depth: infinity` is not used: Nextcloud refuses it by default,
  and it would mean a hand-written PROPFIND outside webdav4. One `Depth: 1` per directory costs
  nothing off the loop. Say so in its docstring. The fingerprint stays as it is, with no ETag map
  in `/health` or `index.json`.
- **D5. The GET half.** `download(fetch, root, rel, fs) -> None` is `fetch_file`'s download half:
  the `_inside` guard, the parents made, a temp file in `workspace(root.parent)` with
  `WORK_PREFIX`, `fs.get_file` under `_reporting(fetch, f"fetch of {rel}")`, and an atomic
  `replace`. **(changed)** `fetch_file` is deleted: only its tests called it. Its tests move to
  `download` or to the pass (Task 1, Task 2).
- **D6. Log copy**, with the fetch key said once (the existing test's rule):
  - listing: `"%s: revalidating the listing failed: %s"`, with the reason taken from the
    `SourceError` with its `"<key>: listing failed: "` prefix removed;
  - GET: `"%s: revalidating %s failed: %s"` with `rel`, and the reason with
    `"<key>: fetch of <rel> failed: "` removed;
  - any other exception: its `str()`.
  No URL or credential appears: `_failure` already guarantees that.
- **D7. Lifetime.** The revalidator is still built in `build_snapshot`. It gets `retire()`, which
  sets `_retired`, and `retired`, a read-only property. A kick then does nothing, and a running pass
  stops before its next fetch or file. A download already under way finishes its one atomic
  replace into the old export, which is harmless: the old export is collected after its grace
  period.
  `KnowledgeBase.refresh` reads `old = self.snapshot` just before `self.snapshot = snapshot`.
  After the swap it calls `old.live.retire()` when `old.live is not None and old.live is not
  snapshot.live`.
  - **(changed)** If the build or the publish raises, `refresh` retires the built snapshot's
    revalidator, when one was built and it is not the served one. Its publish-time `_watch` may
    already have kicked a pass, and nothing would ever retire it.
  - **(changed)** No retire in the lifespan's shutdown. An in-memory `fastmcp.Client` connection
    runs the lifespan (see `tests/test_live.py::no_refresh_loop`), so every `read_served` would
    retire the served revalidator after its first read. The thread is a daemon and does not hold
    the process open, and a download killed at exit leaves only a temp file in `.work/`, which
    SRC-22 and `tests/test_webdav_source.py` already cover.
- **D8. Publishing is unchanged.** The worker publishes nothing. The next request's `view()` runs
  `_reread_live`, whose disk-only `_stamp` sees the moved files, re-adds the plugin on the loop and
  swaps through `renarrowed` only while that snapshot is served. `served_tree` stays lock-free.
- **D9. Staleness (SKL-37).** An edit is served by the first request after the pass that saw it:
  about 2 s plus one pass behind under steady traffic, and one request behind when the server is
  quiet. The request that kicks a pass serves whatever is on disk when it stamps. That is usually
  the old bytes, but not always: a fast pass can land first. No test may assert that the kicking
  request serves the old bytes unless the listing is held.
- **D10. Scope no longer limits what is listed.** A pass lists the whole fetch. A request whose
  scope admits one plugin of a fetch starts a listing of every folder of that fetch, but only
  plugins its scope admits are stamped and re-read (`_reread_live`, unchanged).
  `test_an_out_of_scope_live_skill_is_not_revalidated` is rewritten to that rule (Task 2).
- **D11. No extra bound on a pass's wall time.** It runs off the loop, so it can only delay
  staleness. `REVALIDATE_TIMEOUT` bounds each HTTP operation, as now.
- **D12. Tests wait on a pass.** `wait(timeout=None) -> bool` joins `self._thread` and returns
  whether no pass is running. **(changed)** The spec's `settled_read` (read, wait, read) is replaced
  by `landed(kb)` (wait, kick, wait). A pass already in flight when a test edits upstream may have
  listed before the edit. Waiting on it alone would then make the next read serve the old bytes,
  sometimes.

### Named changes, for QA

- **L1.** A pinned request never sends a PROPFIND or a GET on the event loop. `/health` and a
  concurrent `resources/list` answer while a live server is slow.
- **L2.** A live edit is served by the request after the background pass, not by the request
  that triggers it.
- **L3.** `/health`'s `revalidated` counts files compared against a listing, so it now climbs by
  the export's file count per pass, not by one per file read.
- **L4.** A failed listing logs `<fetch>: revalidating the listing failed: <reason>`.

## Global Constraints

- No network on the request path. `Revalidator.revalidate` never calls `client`, `remote_etags` or
  `download` on its caller's thread.
- The pass thread is named `kb-revalidate` and is a daemon. It never takes `KnowledgeBase._lock`
  or `SkillServing._lock`. `served_tree` and `renarrowed` take no lock.
- `TTL_SECONDS = 2.0`, `REVALIDATE_TIMEOUT = 1.0` and `COOLDOWN_SECONDS = 30.0` are unchanged and
  still read from the module at construction. The TTL and the cooldown are per fetch.
- No URL, cache path or credential in a log, an error or `/health` (SRC-23, HTTP-11). The
  fingerprint carries no ETag map.
- `catalogue/` and `plugins/` import no FastMCP (`tests/test_boundaries.py`). kb imports
  `kubed.mcp*` only.
- Spec IDs are stable and never reused. Spec files hold statements only: no dates, issue numbers
  or "used to".
- Changelog: one line under `[Unreleased]` → `### Fixed`, exactly: `- A slow Nextcloud no longer
  stalls other requests or fails health probes: live sources revalidate in the background.`
- An edit in a wsgidav test changes the file's length (ETag `inode-mtime-size`).
- The wiki change goes on the wiki's `issue-116` branch, never `master`. Generated pages come only
  from `python scripts/generate_wiki.py`. Commits are signed (`git commit -S`).
- Markers: in-process tests are `@pytest.mark.unit`, and uvicorn ones `@pytest.mark.integration`.
- Every task passes, from the repository root with `wiki/` checked out:
  `ruff check . && pytest && python scripts/generate_wiki.py --check`. That is `test.yml`'s lint and
  suite, on 3.11 and 3.14 in CI, plus the wiki drift check.
- Do not weaken an assertion to make it pass. A failure the Design does not explain is a finding:
  stop and report it with the output.

## Review Focus

1. **An edit made while a pass is running.** The pass listed before the edit, so it brings
   nothing down. The next due pass must see the edit; it is never lost. Task 2,
   `test_an_edit_during_a_pass_is_seen_by_the_next`.
2. **A pass that dies of something unexpected**, such as `download` raising `OSError` (a full
   disk). It must release the single-flight flag, or live revalidation stops for good without a
   word. Task 2, `test_a_pass_that_raises_releases_the_flag`.
3. **A local copy that lost a file whose ETag did not move.** The pass downloads it again. Task 2,
   `test_a_missing_local_copy_is_downloaded_again`.
4. **A refresh whose publish raises.** The discarded build's revalidator is retired, the served
   one is not, and live re-reads go on against the served tree. Task 3, in
   `test_a_publisher_that_raises_leaves_the_records_as_they_were`.
5. **A file deleted upstream.** The pass keeps the local copy, downloads nothing and counts
   nothing for it. Task 2, `test_a_file_gone_upstream_keeps_its_local_copy`.

---

### Task 1: `webdav.py`: the listing made public, the download split out

A refactor with the suite green. `fetch_file` keeps its signature and behaviour, its GET half now
a call to `download`, and `live.py` is untouched until Task 2 deletes `fetch_file`.

**Files:**
- Modify: `kubed/mcp_kb/sources/webdav.py` (rename `_etags` → `remote_etags` in its two callers;
  add `download`; `fetch_file` calls it; the module docstring's third bullet names `download`)
- Test: `tests/test_webdav_source.py`

**Interfaces:**
- Produces:
  - `remote_etags(fetch: Fetch, fs: WebdavFileSystem) -> dict[str, str]`
  - `download(fetch: Fetch, root: Path, rel: str, fs: WebdavFileSystem) -> None`, which raises
    `SourceError` (`AccessRefused` on 401/403) and refuses a `rel` outside `root`

- [ ] **Step 1: Move the `fetch_file` tests onto `download`** (all `@pytest.mark.unit`)

```python
def test_download_replaces_the_local_copy(webdav, tmp_path):
    # edit SKILL longer; download(source, root, SKILL, client(source))
    # "edited in nextcloud" in _body(root)

# test_a_live_fetch_replaces_the_local_copy_rather_than_rewriting_it -> download, same asserts
# test_a_live_fetch_stages_its_download_outside_the_export -> download with _Watched (get_file only)
# test_a_name_that_needs_encoding_is_revalidated_like_any_other -> download(..., rel, client(source)),
#     the edited text read back
def test_download_refuses_a_path_that_leaves_the_export(webdav, tmp_path):
    with pytest.raises(SourceError, match="outside"):
        download(source, root, "../escaped.md", client(source))

def test_remote_etags_lists_every_file_with_its_etag(webdav, tmp_path):
    etags = remote_etags(source, client(source))
    assert set(etags) >= {SKILL, "docs/guide.md"}
    assert etags == json.loads((materialise_webdav(source, tmp_path) / ETAGS_FILE).read_text())
```

The three `fetch_file` decision tests
(`test_fetch_file_returns_the_etag_unchanged_when_the_file_has_not_moved`,
`test_fetch_file_replaces_the_local_copy_when_the_etag_moved`,
`test_a_missing_upstream_file_leaves_the_local_copy`) stay until Task 2 deletes them with
`fetch_file`. Their rules become the pass's there.

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_webdav_source.py -v`
Expected: FAIL with `ImportError: cannot import name 'download'`.

- [ ] **Step 3: Implement** D4 and D5's `download` in `webdav.py`. `fetch_file` keeps its PROPFIND
  and its early return, and calls `download(fetch, root, rel, fs)` for the GET.

- [ ] **Step 4: Run every check**

Run: `ruff check . && pytest && python scripts/generate_wiki.py --check`
Expected: all pass, `tests/test_live.py` unchanged.

- [ ] **Step 5: Commit**

```bash
git add kubed/mcp_kb/sources/webdav.py tests/test_webdav_source.py
git commit -S -m "refactor: split webdav's download from fetch_file and publish its listing (#116)"
```

### Task 2: The revalidator starts a background pass and never waits

**Files:**
- Modify: `kubed/mcp_kb/sources/live.py` (`_Live.passed_at`; `Revalidator.revalidate`, `wait`,
  `retire`, `retired`, `_due`, `_pass`, `_price`; `_checked` goes; the module docstring; the
  comments on the three constants)
- Modify: `kubed/mcp_kb/sources/webdav.py` (delete `fetch_file`, D5; `client`'s docstring names
  the pass), and `tests/test_webdav_source.py` (delete the three `fetch_file` decision tests and
  the import)
- Modify (docstrings only): `kubed/mcp_kb/catalogue/snapshot.py` (`Snapshot.revalidate`, the
  `live` field comment), `catalogue/uris.py` (`live_stamp`, `_text`), `catalogue/skills.py`
  (`LibraryFiles.__init__`'s comment, `_serve`'s), `mcp/skills.py` (module docstring's "A live
  plugin is re-read on view (D9)", `view`, `_reread_live`, `_stamp`)
- Modify: `kubed/mcp_kb/spec/builder.py` (`revalidated` and `cooling` descriptions), then
  regenerate `wiki/Endpoints.md`
- Modify: specs `skills.md` (SKL-37, SKL-38), `config-and-sources.md` (SRC-21, the table, SRC-23,
  SRC-25), `agents.md` (AGT-16), `prompts.md` (PRM-58)
- Modify: `tests/webdav_server.py` (`Webdav.stall`)
- Modify: `tests/conftest.py` (an autouse fixture that joins stray passes)
- Test: `tests/test_live.py`

**Interfaces:**
- Consumes: Task 1's `remote_etags` and `download`, imported into `live.py`'s namespace so a test
  patches `live.remote_etags` and `live.download`.
- Produces:
  - `Revalidator.revalidate(path: Path) -> None` (D1)
  - `Revalidator.wait(timeout: float | None = None) -> bool`
  - `Revalidator.retire() -> None` and `Revalidator.retired -> bool` (a property)
  - `Revalidator.stats(key: str) -> dict`, unchanged in shape
  - `Webdav.stall(verb: str, seconds: float) -> threading.Event`. From the call on, each request
    with that method waits up to `seconds` before it is served, and the returned Event is set when
    the first one arrives. `stop()` releases every stall before it stops the server.
  - `tests/test_live.py::landed(kb) -> None` (D12): `assert kb.snapshot.live.wait(5)`, then
    `kb.snapshot.live.revalidate(<a path under the export>)`, then `assert kb.snapshot.live.wait(5)`.
    The path is any path inside the fetch's export, e.g. `kb.index.get("notes/x").path.parent`.

- [ ] **Step 1: Write the failing tests** in `tests/test_live.py`

```python
@pytest.mark.integration
async def test_a_blocked_listing_delays_no_request(webdav, tmp_path, monkeypatch):
    """L1, the issue's test: the server holds every PROPFIND for 2 s."""
    monkeypatch.setattr(live, "REVALIDATE_TIMEOUT", 5.0)   # the old path would wait the 2 s out
    kb = _knowledge_base(webdav, tmp_path)
    serving_of(kb)
    assert kb.snapshot.live.wait(5)                         # the boot publish's pass is done
    arrived = webdav.stall("PROPFIND", 2.0)
    with serve_http(kb) as url:
        async with http_client(url) as kicker, http_client(url) as other:
            start = time.monotonic()
            await kicker.list_resources()                   # kicks the pass
            kicked = time.monotonic() - start
            assert await asyncio.to_thread(arrived.wait, 5), "the pass never reached the server"
            start = time.monotonic()
            await other.list_resources()
            listed = time.monotonic() - start
            async with httpx.AsyncClient() as http:
                start = time.monotonic()
                assert (await http.get(url.removesuffix("/mcp") + "/health")).status_code == 200
                health = time.monotonic() - start
    assert kicked < 1.0 and listed < 1.0 and health < 1.0, (kicked, listed, health)

def test_kicks_while_a_pass_runs_start_no_second(webdav, tmp_path, monkeypatch):
    # live.remote_etags patched: counts calls by fetch key, sets `entered`, waits on `release` (5 s)
    # landed() is not used: kick with kb.snapshot.live.revalidate(path) 10 times while held
    # assert calls == [KEY]
    # assert [t.name for t in threading.enumerate()].count("kb-revalidate") == 1
    # release.set(); assert kb.snapshot.live.wait(5)

def test_one_pass_prices_every_due_live_fetch(webdav, tmp_path, monkeypatch):
    # two live fetches of one source: plugins at notes://kb and notes://kb/other, two libraries
    # wait(5), clear the counter, one kick on the first fetch's file, wait(5):
    # listing calls == {KEY, f"{KEY}/other"}, one each

def test_a_retired_revalidator_stops_between_files_and_ignores_kicks(webdav, tmp_path, monkeypatch):
    # edit skills/x/SKILL.md and docs/guide.md upstream, both longer
    # live.download wrapped: on its first call, revalidator.retire(), then the real download
    # landed(kb): downloads == 1, and the second file's local copy is unchanged
    # revalidator.retired is True; revalidate(path) starts nothing: wait(0) is True, listing count same

def test_an_edit_during_a_pass_is_seen_by_the_next(webdav, tmp_path, monkeypatch):   # Review Focus 1
    # remote_etags wrapped: the real listing first, then wait on `release`
    # kick; edit x upstream while held; release; wait -> x not fetched by that pass
    # landed(kb); "edited" in read_served(kb, URI)

def test_a_pass_that_raises_releases_the_flag(webdav, tmp_path, monkeypatch):        # Review Focus 2
    # COOLDOWN_SECONDS 0.05; edit x; live.download raises OSError("No space left on device") once
    # landed(kb); n = listing calls; time.sleep(0.1); landed(kb): listing calls == n + 1,
    # and "edited" in read_served(kb, URI)

def test_a_missing_local_copy_is_downloaded_again(webdav, tmp_path):                 # Review Focus 3
    # unlink the export's skills/x/SKILL.md (kb.index.get("notes/x").path / "SKILL.md")
    # landed(kb): the file is back; stats(KEY)["fetched"] == 1

def test_a_file_gone_upstream_keeps_its_local_copy(webdav, tmp_path):                # Review Focus 5
    # landed(kb); unlink upstream docs/guide.md
    # landed(kb): read_served(kb, GUIDE) == "library-level guidance\n"; stats(KEY)["fetched"] == 0

def test_a_failed_download_names_its_file_once(webdav, tmp_path, monkeypatch, caplog):
    # edit x; live.download raises SourceError(f"{KEY}: fetch of skills/x/SKILL.md failed: HTTP 500")
    # landed(kb) under caplog: one line, == f"{KEY}: revalidating skills/x/SKILL.md failed: HTTP 500"
```

`time`, `threading` and `httpx` are already imported. Add `import asyncio`.

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_live.py -v -k "blocked_listing or kicks_while or every_due or retired or during_a_pass or releases_the_flag or missing_local or gone_upstream or failed_download"`
Expected: FAIL. `Revalidator` has no `wait` or `retire`, and `Webdav` has no `stall`. With
`wait` removed from the first test, `listed` and `health` come out at about 2 s.

- [ ] **Step 3: Implement** D1 to D3, D6 and D7's `retire`/`retired` in `live.py`, `Webdav.stall`
  in `tests/webdav_server.py`, and in `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _passes_end_with_their_test(monkeypatch):
    """No revalidation pass outlives its test, or runs after its patches are undone."""
    yield
    for thread in [t for t in threading.enumerate() if t.name == "kb-revalidate"]:
        thread.join(timeout=5)
        if thread.is_alive():
            pytest.fail("a revalidation pass outlived its test")
```

It requests `monkeypatch` so its teardown runs before the patches are undone. It is autouse in
`conftest.py`, so the `webdav` fixture is torn down (stalls released) before it joins.

- [ ] **Step 4: Run the new tests to see them pass**

Run: the Step 2 command.
Expected: PASS.

- [ ] **Step 5: Bring `tests/test_live.py` to the new rule**

Run: `pytest tests/test_live.py -x -q`. Rewrite each failure by these rules, and nothing else:
- **An edit, then a request that must serve it:** insert `landed(kb)` after the edit (and after
  `clock(2.5)` where there is one) and before that request. That covers
  `test_an_edit_upstream_is_visible_on_the_next_read_without_a_refresh`,
  `test_the_rereading_read_builds_the_set_it_reread`, `test_a_skill_a_live_edit_breaks_is_logged_once`,
  `test_a_library_level_file_is_revalidated_too`, the three live prompt tests and
  `_keeps_the_last_good_build` (before each render that expects a change),
  `test_a_prompt_broken_by_a_refresh_does_not_block_a_live_skill_edit`,
  `test_a_broken_edit_to_a_file_that_lost_its_name_does_not_block_a_reread`,
  `test_a_manifest_is_priced_against_the_server_before_it_is_served`,
  `test_the_revalidator_follows_the_export_a_refresh_created`,
  `test_a_live_edit_reads_after_trust`, `test_a_reread_keeps_every_other_plugin`,
  `test_no_reread_while_a_refresh_publishes` (after the lock is released),
  `test_a_live_agent_edit_reads_after_trust`, and every other test the run shows, the agent and
  re-read tests from line 980 on included. The `"N6: the re-adding read"` messages and docstrings
  become "the first request after the pass" (SKL-37).
- **Assertions within the 2 s trust** ("trusted for 2 s") keep their place, before the
  `clock(2.5)`.
- **A test that patches `live.fetch_file`** patches `live.remote_etags` (a listing that fails or
  hangs) or `live.download` (a GET), and calls `landed(kb)` where it read to trigger the call:
  `test_a_snapshot_source_never_revalidates` (both patched to `boom`, `reached == []`), the two
  cooling tests, `test_the_ttl_runs_from_the_answer_and_not_from_the_question` (a slow listing of
  0.4 s against a TTL of 0.3, then one more kick and `wait`, and `webdav.requests == []`).
- **`test_reads_within_the_ttl_do_not_hit_the_server`:** the TTL is per fetch. After the first
  read, `wait(5)`, clear the requests, read twice, `wait(5)`, and `requests == []`.
- **`test_a_server_that_hangs_is_asked_once_and_then_left_alone`:** `REVALIDATE_TIMEOUT` 2.0.
  Count `live.remote_etags` calls. `first < 1.0`, and `not kb.snapshot.live.wait(0)` right after
  the first read (the read did not wait for the pass). Then `wait(5)`, five reads and a `GUIDE`
  read with `wait(5)`, the call count still 1, `"first"` served, and
  `caplog.text.count("revalidating") == 1`.
- **`test_a_failed_revalidation_names_the_source_once`:** after `webdav.stop()`, `landed(kb)`.
  `caplog.text.count(f"{KEY}:") == 1` and `"revalidating the listing failed"` in it.
  `test_a_failed_revalidation_says_nothing_about_the_credentials` also gets `landed(kb)`.
- **`test_health_reports_what_a_live_source_revalidated`:** `fetched == 1`, and `revalidated` at
  least twice the export's file count (L3).
- **`test_one_client_serves_every_live_read`:** `wait(5)` before `built == [KEY]`.
- **`test_an_out_of_scope_live_skill_is_not_revalidated`** becomes
  `test_an_out_of_scope_live_plugin_is_not_reread` (D10). Over `_two_libraries`, edit x and z
  upstream, then `landed(kb)`, then read `OTHER` at `?library=other`. It serves z's edit,
  `notes`'s served plugin object is the one from before, and `other`'s is new.
- The module docstring: "a read starts a background revalidation, and the first request after it
  lands serves the edit".

A failure no rule covers is a finding.

- [ ] **Step 6: Spec rows**

- **SKL-37:** "When a file read, or a request that reads skills, agents or prompts, touches a
  `cache: live` source ([config-and-sources.md](config-and-sources.md)), it starts that fetch's
  revalidation in the background if one is due (SKL-38), and serves what is on disk now. That
  covers library files and both fallbacks, and every file of each live skill, and each agent and
  prompt file, of the plugins its scope admits. A read never waits for the server. A revalidation
  lists the fetch once and downloads each of its files whose ETag moved. The first request after a
  revalidation that moved a file re-reads that plugin and serves it again, every other plugin kept
  as it is served. From that request on, a skill's files, its `_manifest`, its extension entry and
  the plugin's agents and prompts describe the new bytes. So an edit is served once a revalidation
  has seen it: about 2 seconds and one revalidation behind under steady traffic, and one request
  behind on a quiet server. A request that arrives while a refresh is publishing re-reads nothing."
- **SKL-38:** "A fetch revalidated within the last 2 seconds, counted from when that revalidation
  ended, is not revalidated again. One revalidation request times out after 1 second. A
  revalidation that fails serves the copy on disk, and that fetch is not revalidated for 30
  seconds. One revalidation at a time runs for the generation being served, and it covers every
  live fetch that is due."
- **AGT-16**, the first two sentences: "An agent of a live fetch is revalidated in the background
  with its plugin's files (SKL-37), started by each request that reads skills or agents under a
  scope admitting its plugin. A file that moved re-reads its plugin, and from the first request
  after the revalidation that found the edit, `agents/list` and `agents/get` both serve the new
  read." The rest is unchanged.
- **PRM-58:** "A prompt file of a `cache: live` source (see
  [config-and-sources.md](config-and-sources.md)) is revalidated in the background with its
  plugin's skill and agent files (SKL-37), started by each request whose scope admits the plugin.
  One that moved re-reads its plugin, and the prompt as edited serves from the first request after
  the revalidation that found it."
- **SRC-21:** "On a live fetch, each read of one of its library files, and each request that reads
  skills, agents or prompts under a scope admitting one of its plugins, starts the fetch's
  revalidation in the background if one is due (SKL-37). It is served from the local copy as it
  is. A revalidation lists the fetch's folder once, one PROPFIND per directory, and downloads each
  file the local copy holds whose ETag differs from the local copy's. An edit is served from the
  first request after the revalidation that found it."
- **The table:** `a fetch revalidated this recently is not revalidated again | 2 s`, the two other
  rows as they are, and a new row: `revalidations running at once for the generation served | 1`.
- **SRC-23:** "A failed revalidation logs one warning, `<fetch>: revalidating the listing failed:
  <reason>` or `<fetch>: revalidating <path> failed: <reason>`, with no URL or credential. The local
  copy goes on serving, and no read fails or waits for it. While the fetch is cooling, `/health`
  shows `cooling: true`."
- **SRC-25:** "A live fetch's `/health` entry carries `live: true` and two counts: `revalidated`,
  the files a revalidation compared against the server's listing, and `fetched`, the ones
  downloaded again."
- **Check, unchanged:** HTTP-10 and SRC-24. SKL-39 still reads true. Reword only a row that
  names a per-file TTL.
- **`spec/builder.py`:** `revalidated` becomes "Live fetches only: files compared against the
  server's listing since this snapshot was built." `cooling` becomes "Live fetches only: present
  and true while a failed revalidation has this fetch's background revalidation suspended." Then
  run `python scripts/generate_wiki.py`. Only `wiki/Endpoints.md` changes, and only those two
  rows; any other change is a finding.

- [ ] **Step 7: Run every check**

Run: `ruff check . && pytest && python scripts/generate_wiki.py --check`
Expected: all pass. `tests/test_exports.py` passes unchanged, and `tests/test_webdav_source.py`
with only the three `fetch_file` tests gone.

- [ ] **Step 8: Commit**

```bash
git add kubed tests docs/superpowers/specs wiki
git commit -S -m "fix: revalidate live sources in a background pass, never on the event loop (#116)"
```

### Task 3: A revalidator is retired with its snapshot

**Files:**
- Modify: `kubed/mcp_kb/server.py` (`KnowledgeBase.refresh`, D7)
- Modify: spec `config-and-sources.md` (SRC-54, after SRC-25)
- Test: `tests/test_live.py`

**Interfaces:**
- Consumes: Task 2's `Revalidator.retire()`, `retired`, `wait()`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_refresh_retires_the_revalidator_it_swaps_out(webdav, tmp_path):
    kb = _knowledge_base(webdav, tmp_path)
    serving_of(kb)
    was = kb.snapshot.live
    webdav.skill("y", "a second skill, which moves the whole folder's digest")
    assert kb.refresh() == [KEY]
    assert was.retired and kb.snapshot.live is not was and not kb.snapshot.live.retired

def test_a_live_reread_does_not_retire_the_revalidator(webdav, tmp_path):
    # edit x; landed(kb); read_served -> edited (renarrowed swapped a replace())
    # kb.snapshot.live is the revalidator from before, and it is not retired
```

And in `test_a_publisher_that_raises_leaves_the_records_as_they_were` (Review Focus 4), `flaky`
records `published.live`. After the failed refresh, that revalidator is `retired`, and
`kb.snapshot.live` is the served one and is not.

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_live.py -v -k "retires_the_revalidator or does_not_retire or publisher_that_raises"`
Expected: FAIL on `was.retired` and on the discarded build's `retired`.

- [ ] **Step 3: Implement** D7 in `refresh`. Keep the restore of the four records in the `except`
  as it is. The built snapshot is retired inside it before the `raise`.

- [ ] **Step 4: SRC-54**, after SRC-25: "A live fetch's revalidation belongs to the generation it
  serves. Once a refresh swaps in a new generation, the previous one's revalidation starts
  nothing, and one it is running stops before its next file and logs nothing more."

- [ ] **Step 5: Run every check**

Run: `ruff check . && pytest && python scripts/generate_wiki.py --check`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add kubed/mcp_kb/server.py tests/test_live.py docs/superpowers/specs/config-and-sources.md
git commit -S -m "fix: retire a snapshot's revalidator when a refresh swaps it out (#116)"
```

### Task 4: The record: AGENTS.md, the wiki, the changelog and the live check

**Files:**
- Modify: `AGENTS.md`, `README.md`, `CHANGELOG.md`
- Modify: wiki `Sources.md` (lines 172-180), `Operations.md` (111-114), `Plugins.md` (310-312),
  `Prompts.md` (276-279), on the wiki's `issue-116` branch
- Modify: `tests/live/test_live_reread.py` (`_edit`)

- [ ] **Step 1: AGENTS.md**

- Replace the paragraph "**A live read blocks the whole event loop.**" with "**No network on the
  request path.**" Say that kubed-mcp calls `view()` synchronously on the loop, so a blocking call
  under it holds every request, `/health` included. A `cache: live` fetch is priced only by its
  `Revalidator`'s one background pass (`kb-revalidate`, a daemon thread, one at a time per
  snapshot). `revalidate(path)`, called from `_stamp`, `Catalogue.live_stamp`, `LibraryFiles` and
  `Snapshot.revalidate`, only starts that pass when the fetch is due. The pass lists each due fetch
  once with `webdav.remote_etags` (one `Depth: 1` PROPFIND per directory, because Nextcloud refuses
  `Depth: infinity` by default) and downloads what moved. The next request's view stamps from disk
  and re-reads. Only the pass writes `_Live`, and no lock is shared beyond the single-flight flag,
  which is taken without blocking. Anything that talks to a server goes in that pass, never under a
  handler.
- In "**A provider that stores a `Catalogue`…**", "It is built in `build_snapshot` and retired
  with the snapshot" becomes "It is built in `build_snapshot`, and `KnowledgeBase.refresh` retires
  it once its snapshot is swapped out".

- [ ] **Step 2: README.md line 116:** "so **a file edited in Nextcloud is served on the next
  read**" becomes "so **a file edited in Nextcloud is served within seconds, with no refresh**".

- [ ] **Step 3: The wiki** (hand-written pages, on its `issue-116` branch):
- `Sources.md`: `cache: live` keeps the copy and revalidates it **in the background**, started by
  a read. That is one listing of the folder and a download of each file whose ETag moved. A read
  never waits for the server. A file edited in Nextcloud is served from the first request after
  that revalidation, a library file and a skill's, an agent's or a prompt's file alike, with the
  `_manifest`, `skills/get` and the plugin's agents and prompts included. Keep the mid-edit
  sentence and the "does not do" list.
- `Operations.md`: if the server stops answering, a background revalidation waits a short
  timeout. No read waits for it. The source is then served from its local copy for the next 30
  seconds and shows `cooling: true`.
- `Plugins.md` and `Prompts.md`: "from the request that finds it" and "that same request" become
  "from the first request after the background revalidation that finds it".

- [ ] **Step 4: CHANGELOG.md**, under `[Unreleased]` → `### Fixed`, the Global Constraints line.

- [ ] **Step 5: The live check.** `_edit(path, text)` becomes `_edit(path, text, kb_url)`. After
  the write and the `TTL_SECONDS + 0.5` sleep, it calls `await agent_names(kb_url, "dav")` to start
  the pass, then `await asyncio.sleep(1.0)` for it to land. The `finally` restore does the same.
  It is not run in CI. Run it locally by CONTRIBUTING.md's "Live checks" block if a kb can be
  started.

- [ ] **Step 6: Run every check**

Run: `ruff check . && pytest && python scripts/generate_wiki.py --check && python scripts/generate_openapi.py`
Expected: all pass (`tests/test_wiki.py` not skipped). Lint the written `openapi.yaml` with
`npx --yes @redocly/cli@2 lint openapi.yaml` where `npx` is available, and delete the file after.

- [ ] **Step 7: Commit**

```bash
git add AGENTS.md README.md CHANGELOG.md tests/live/test_live_reread.py wiki
git commit -S -m "docs: live sources revalidate in the background (#116)"
```

## Done when

- Tasks 1 to 4 are merged into `issue-112`.
- The issue's own check, after deployment (carried by #111's live check): in a 1-hour window of
  natural load, no list call takes over 1 s outside startup, no probe fails, and Pyroscope shows no
  `propfind` under the event-loop root. Take `/health`'s `fetches.<nextcloud>.revalidated` delta
  across one pass to record N, the live file count, which the spec left unmeasured.
