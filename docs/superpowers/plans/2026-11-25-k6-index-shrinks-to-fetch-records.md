# K6: index.json Shrinks to Fetch Records Implementation Plan

> **History.** Proposed for #84 (PR #102, into `issue-80`), after K3 (#79, PR #89), the gateway
> prefix (#81, PR #93), the `_publish` race fix (#94, PR #96), K4 (#82, PR #97), K5 (#83, PR #100)
> and the kubed-mcp 0.3.0 pin (#92, PR #99). The spec is #84's notes in `.issue/issues.md`, with Dr
> K's rulings of 2026-11-24 and the parent's messages of 2026-11-25: scope (a), the version
> transition applied to the version now on disk (accept v11's `fetches`, write v12),
> `PluginRecord.skipped` deleted with the plugin rows, and `/health` counts taken from what the
> layer serves. The design is below. There is no separate design file. Two points in the notes
> could not be built as written against kubed-mcp `v0.3.0`'s source. D4 and D6 say what replaces
> each.
>
> **Approved 2026-11-25.** Task 0 corrected two facts under 0.3.0. The layer does log a skill
> folder it rejects, at `ERROR` on `kubed.mcp.skills`, which the plan said it did not. And its
> reason for a folder of 513 files is `BIG_REASON = "A skill may contain at most 512 files"`.
>
> **Shipped 2026-11-25**, Tasks 0 to 3. D6 is built as Dr K ruled, not as written below: one log
> line per skip, kb's. `QuietSelection` drops the layer's own line for each skip kb reports,
> matched on its template and its number of args, the rejected-skill `ERROR` and the
> `agent_meta` refusal included, and keeps the layer's nested-`SKILL.md` line. A skill folder or
> agent file the layer skips that kb's harvest never found is said once by kb, with no row. An
> unselected command file the layer skips before kb's reader, and the skips of a plugin refused
> in every library, are now said by nobody. Task 2's review added two fixes: a live re-read logs
> what it changed through `log_changes`, and a `skills: ["."]` plugin's unselected command files
> stay quiet (P8). The spec is HTTP-9 and HTTP-44 to HTTP-47, with SRC-30, SRC-36, SRC-37,
> SRC-48, PRM-18, AGT-6, AGT-14, PLG-18 and LIB-33 reworded.

> **For agentic workers:** REQUIRED SUB-SKILL: Use skill://superpowers/subagent-driven-development/SKILL.md (recommended) or skill://superpowers/executing-plans/SKILL.md to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `index.json` keeps only fetch records, and every boot and every refresh re-harvests
every plugin from the trees on disk, with no network. `/health`'s plugin counts and `skipped` rows
come from what kubed-mcp's plugin layer serves for each plugin.

**Architecture:** kb's harvest stays, in memory, as the vetting table (the parity guard and N13,
the fail-closed `rewrite` against `snapshot.index`, and the publish skip rules). Three things go:
- what `index.py` persists of it (`SkillRow`, `PluginRecord`);
- the reuse of a harvest across boots and refreshes (`_plugin_record`'s keep branch, SRC-48's
  matching);
- `PluginRecord.skipped`, which nothing writes.

`SkillServing._narrowed` already overlays the plugin layer's prompt and agent counts. It now
owns all three counts and the layer's skill-folder rows too, for every plugin.

**Tech Stack:** Python ≥3.11, `kubed-mcp>=0.3.0,<0.4` (FastMCP through it), pytest +
pytest-asyncio, uvicorn, jsonschema.

**Spec:** this plan's design section; #84's notes in `.issue/issues.md`; the living spec in
[config-and-sources.md](../specs/config-and-sources.md) (SRC-30, SRC-36, SRC-37, SRC-48),
[prompts.md](../specs/prompts.md) (PRM-18), [http-and-tools.md](../specs/http-and-tools.md)
(HTTP-9), [agents.md](../specs/agents.md) (AGT-14) and
[plugins-and-libraries.md](../specs/plugins-and-libraries.md) (PLG-18, LIB-33).

## Design

### What is on the branch now, read in the code

- `catalogue/index.py`: `INDEX_VERSION = 11`. `Index` has `fetches` and `plugins`. `PluginRecord`
  holds `SkillRow`s, prompt paths, `claude_prompts`, files, skill dirs, `skipped` (never written,
  K5), agents, agent paths and the `Globs` it was harvested with. A file of any other version
  reads as `None`.
- `server.py`: `_cold_start` keeps the stored fetches that are servable, and the stored plugin
  records whose fetch survived. `_plugin_record` reuses a record while its fetch key, root and
  globs match, and otherwise calls `build_plugin`. `refresh` passes the records of the fetches it
  did not rebuild as `reusable`. `served_tree` reads `_fetches` alone.
- `catalogue/snapshot.py`: `build_plugin` returns a `PluginRecord`. `build_snapshot` turns
  `SkillRow`s back into `Skill`s per library (`to_skill`). It writes each plugin's counts as
  kb's harvest found them: the first library's served skills, every selected prompt file, every
  agent file. A plugin no library serves falls back to the harvest's lengths.
- `mcp/skills.py`: `_narrowed` overwrites `prompts` and `agents` for each plugin it **added**, and
  appends the layer's prompt and agent rows to `skipped`. A plugin it did not add keeps
  `build_snapshot`'s counts. That is K4's miscount: a plugin the layer refuses, or one declared
  `skills: []`, reports its prompt files (and its agent files, by AGT-14's fallback). A plugin's
  `skills` count is never narrowed, so a hidden-file skill (N13) is still counted.
- kubed-mcp `v0.3.0`, read at its source:
  - `Plugin.skipped` is `(path, reason)` for each skill folder, command file and agent file not
    served.
  - A `SKILL.md` deeper than a skill folder is **not** in `skipped`. It is a line in
    `Plugin.components.notes`: `<path> is not served: a skill is one folder below its skills
    folder`.
  - The layer logs a skipped command file, a skipped agent file and a duplicate skill folder at
    WARNING when the plugin is read. A skill folder that `_load_skill` rejects is recorded in
    `skipped` without a log line.

### Decisions

- **D1. Index v12 holds `version`, `built`, `config_hash` and `fetches`.** This is ruling 1,
  applied to the version now on disk. `Index.read` accepts `INDEX_VERSION = 12` and
  `PREVIOUS_VERSION = 11`, and for both reads only `fetches`. A v11 file's `plugins` is never
  looked at, whatever it holds, so its shape cannot fail a boot. SRC-36's config-hash check
  applies to both. `FetchRecord` is unchanged, and a test pins its field list against the v11
  literal, so a later change to it fails. A boot writes v12. Dropping `PREVIOUS_VERSION` is a
  follow-up, once every deployment has written v12.
- **D2. A harvest is an in-memory `Harvest`, and it is never reused.** `PluginRecord` and
  `SkillRow` leave `index.py`. `snapshot.py` gains `Harvest`, the same harvest less what only
  reuse or the file needed (`fetch`, `globs`, `skipped`). It holds `Skill`s (library and folder
  empty), and each library takes its copy with `dataclasses.replace`. Every `_assemble` (boot and
  refresh) calls `build_plugin` for every plugin whose fetch serves. That is the issue's "SRC-48:
  the reuse is gone". It deletes the root/globs matching that a cross-repository marketplace entry
  needed, and what SRC-48 guaranteed stays true: an entry whose lists or `path` moved on another
  repository is re-harvested. The cost is one tree walk per plugin per generation, all local. QA
  measures it at boot.
- **D3. `/health` counts are what the layer serves, for every `ok` plugin.** In `_narrowed`, a
  plugin's `skills`, `prompts` and `agents` come from the first library that **adds** it:
  - `skills` counts its `SKILL.md` URIs that kb also found and does not hide (N13);
  - `prompts` is the prompts as now;
  - `agents` is its `agent_files`, as now.

  A plugin no library adds counts `0` for all three: one the layer refused (LIB-29), one LIB-28
  failed in every library, and one declared `skills: []` (LIB-33). This is K4's miscount, fixed,
  and AGT-14's fallback, removed. `files` stays kb's (library files are kb's surface, and LIB-29
  keeps serving them). Library totals already read the narrowed catalogue and the served agents
  and prompts, and they do not change.
- **D4. A plugin's `skipped` is kb's harvest rows, then the layer's rows.** The layer's rows are
  `Plugin.skipped` for the plugin's skill folders, its selected prompt files and its found agent
  files. kb's rows come first (PLG-18: naming, twin addresses, reserved file names, files inside a
  skill). Each layer row's path and reason go through `_clean` (`unrooted`, the root named by the
  plugin's address, `scrub`). There is one row per path, and the first reason wins, so a skill kb's
  `_admit` already skipped keeps kb's reason. A skill-folder row is a `served.skipped` path that is
  one of the harvest's skill folders (`Snapshot.skill_dirs`, root-relative). The prompt and agent
  rows keep K4's and K5's rules (no `NOT_SELECTED`, rename-taken to `unserved`, an `agent_meta`
  refusal of a file kb never found logged and not listed).

  **Correction to the notes:** the nested-skill line is not in `skipped` in 0.3.0 (see above), so
  there is no row to filter. kb never reads `components.notes`, because kb builds `notes` itself
  (ruling 2), and a test pins that the line, which kubed-mcp logs, reaches neither the plugin's
  `skipped` nor its `notes`.
- **D5. Every new row is logged once, by `log_changes`, as now.** kb logs at publish and never at
  read. The parity guard's `skill <address> is not served: the plugin layer refused it` is not
  said for a skill whose folder has a layer row, because `log_changes` says it with the reason.
- **D6. The layer's own skip lines are left alone (open, for Dr K).** The layer also logs a
  skipped command file, agent file or duplicate skill folder when it reads the plugin, so those
  have two lines: the layer's, and kb's. Note 4 asked for no double line. kb's line is the one
  that writes the path with `%r` (one line even when the path holds a newline, as
  `test_parity.py::test_a_skip_whose_path_holds_a_newline_is_one_log_line` pins) and carries no
  cache path, and the layer's line does neither (K5's note). Dropping kb's line would lose both
  guarantees, so the plan keeps it. If Dr K wants one line, the fix is a quick-mcp row that makes
  the layer log at DEBUG, not a kb change.

### Named changes for QA's dump diff

| | Change | Where |
|---|---|---|
| I1 | `index.json` holds fetch records only, at version 12; a v11 file boots from disk and is rewritten as v12 | SRC-30, SRC-36, SRC-37 |
| I2 | nothing about a prompt is recorded on disk; its dialect is detected at every read (no client-visible change) | PRM-18 |
| I3 | a plugin's `skipped` gains the plugin layer's rows for its skill folders | HTTP-9, PLG-18 |
| I4 | a plugin the layer does not add (refused, or `skills: []`) reports `skills`, `prompts` and `agents` as `0` (K4's miscount) | HTTP-9, AGT-14, LIB-33 |
| I5 | a plugin's `skills` counts what is served, so a hidden-file skill (N13, `grafana-k6/k6-perf-test-website`) is no longer counted under its plugin | HTTP-9 |
| I6 | a plugin's `built` is when this generation harvested it, so it moves at every boot and every refresh | HTTP-9 |
| I7 | a refresh re-harvests every plugin, not only those of rebuilt fetches (no client-visible change) | SRC-48 |

## Global Constraints

- The pin stays `kubed-mcp>=0.3.0,<0.4`. kb imports FastMCP only through `kubed.mcp*`.
- `INDEX_VERSION = 12` and `PREVIOUS_VERSION = 11`, both in `catalogue/index.py`.
- `FetchRecord`'s fields stay `key, status, root, fingerprint, built, error`, in that order.
- `catalogue/` and `plugins/` import no FastMCP (`tests/test_boundaries.py`).
- Every build-time hook reads through `_reading()`. `served_tree` and `renarrowed` take no lock.
- Nothing in `/health` names a cache path or carries a credential (HTTP-11).
- Python 3.11 floor; 88-column lines; `ruff check .` clean.
- The wiki commit goes on the wiki's `issue-84` branch, never on its `master`.

## Review Focus

1. **A v11 file whose fetch tree was deleted since.** Expected: that fetch is built again, and
   every other fetch is kept (SRC-37). *(Task 1: `test_a_v11_fetch_whose_tree_is_gone_is_built`.)*
2. **A v11 file written from another config.** Expected: discarded whole, everything fetched
   (SRC-36 holds for v11). *(Task 1: `test_a_previous_version_index_meets_the_hash_check`.)*
3. **One plugin in two libraries, refused in the first and added in the second.** Expected: its
   counts are the second library's, not `0`. *(Task 2:
   `test_a_plugin_refused_in_one_library_counts_what_another_serves`.)*
4. **kb's harvest and the layer both skip one skill folder.** Expected: one row, kb's reason.
   *(Task 2: `test_a_skill_kb_and_the_layer_both_skip_is_one_row`.)*
5. **A layer reason that quotes the cache path.** Expected: the row names the plugin's address,
   never the cache. *(Task 2: `test_a_layer_row_names_no_cache_path`.)*

---

### Task 0: Check the layer under the pin before building on it

**Files:** none changed.

- [ ] **Step 1: Bring the branch level and confirm the baseline**

Run: `git fetch origin && git merge origin/issue-80`, then `pip install -e '.[test]'`, then
`ruff check .` and `pytest -q`.
Expected: green, with one xfail (N15). K5 shipped 1338 passed. `pyproject.toml` pins
`kubed-mcp>=0.3.0,<0.4`.

- [ ] **Step 2: Read three facts off the installed kubed-mcp and record them in the PR body**

Read `kubed/mcp/plugins.py` in the installed package:
- (a) the nested `SKILL.md` line goes to `components.notes`, not `skipped` (D4);
- (b) the reason `Plugin.skipped` gives for a skill folder of 513 files, which kb's harvest still
  finds (the Agent Skills limit is 512), quoted exactly;
- (c) which skips the layer logs at read (D6).

**If (a) is false, so the nested line is a `skipped` row,** add a filter on that exact reason in
Task 2's `_skills_of` and pin it there. **If no 513-file folder is skipped,** pick another input
that the layer's `_load_skill` rejects and kb's `load_skills` keeps, and use it in Task 2's tests.

---

### Task 1: Index v12 holds fetch records, and every generation harvests from disk

One task in two parts: `tests/conftest.py` imports `server.py`, so `index.py` cannot lose
`PluginRecord` while `server.py` and `snapshot.py` still import it. Part A's tests are written
first and run with Part B's.

#### Part A: the index

**Files:**
- Modify: `kubed/mcp_kb/catalogue/index.py` (delete `SkillRow`, `PluginRecord`,
  `_plugin_record_from_dict`, `_globs_from_dict`, `_paths`, `_skipped_row`, and the `Globs` and
  `Skill` imports; `Index` loses `plugins`; the module docstring says what the file is now)
- Modify: `tests/conftest.py` (add `V11_PLUGIN_ROW`)
- Test: `tests/test_index.py` (rewrite)

**Interfaces:**
- Produces: `INDEX_VERSION = 12`, `PREVIOUS_VERSION = 11`;
  `Index(version: int, built: str, config_hash: str, fetches: dict[str, FetchRecord])`;
  `Index.read(path) -> Index | None`, where `version` is the file's own (11 or 12);
  `Index.write(path)` unchanged. `FetchRecord`, `config_hash` and `now` are unchanged.
- Produces for Part B: `tests.conftest.V11_PLUGIN_ROW: dict`, one plugin row exactly as v11 wrote
  it. Its keys are `id, fetch, root, status, error, built, skills, prompts, files, skill_dirs,
  skipped, agents, agent_paths, globs, claude_prompts`, with `skills` a list of `{name,
  description, path}` and `globs` a dict of the seven `Globs` keys.

- [ ] **Step 1: Write the failing tests**

In `tests/test_index.py`, drop every `PluginRecord`, `SkillRow`, globs, prompt-row and
skipped-row test, and keep the round-trip, corruption, atomic-write, `mkstemp` and `config_hash`
tests on a fetch-only `_index()`. Add:

```python
FIELDS = ["key", "status", "root", "fingerprint", "built", "error"]

def _v11(tmp_path, **raw):
    """The file as v11 wrote it: these fetches, and one plugin row of its shape."""
    body = {"version": 11, "built": now(), "config_hash": "deadbeef",
            "fetches": {FETCH: asdict(_fetch_record())},
            "plugins": {"flatsource": V11_PLUGIN_ROW}, **raw}
    path = tmp_path / "index.json"
    path.write_text(json.dumps(body))
    return path

def test_a_v12_index_holds_no_plugin_rows(tmp_path):
    path = tmp_path / "index.json"
    _index().write(path)
    assert set(json.loads(path.read_text())) == {"version", "built", "config_hash", "fetches"}
    assert json.loads(path.read_text())["version"] == INDEX_VERSION == 12

def test_a_v11_index_keeps_its_fetches_and_ignores_its_plugins(tmp_path):
    read = Index.read(_v11(tmp_path))
    assert read.version == PREVIOUS_VERSION == 11
    assert read.fetches == {FETCH: _fetch_record(built=read.fetches[FETCH].built)}
    assert not hasattr(read, "plugins")

@pytest.mark.parametrize("plugins", [[], "x", {"p": {"id": "p"}}, None])
def test_a_v11_plugins_value_of_any_shape_is_ignored(tmp_path, plugins):
    assert Index.read(_v11(tmp_path, plugins=plugins)).fetches.keys() == {FETCH}

def test_the_fetch_record_shape_is_the_one_v11_wrote(tmp_path):
    assert [f.name for f in fields(FetchRecord)] == FIELDS
    raw = json.loads(_v11(tmp_path).read_text())
    assert list(raw["fetches"][FETCH]) == FIELDS

@pytest.mark.parametrize("version", [13, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1])
def test_a_different_version_reads_as_none(tmp_path, version): ...   # as today, v10 now refused

@pytest.mark.parametrize("version", [11, 12])
def test_a_wrong_shaped_fetches_mapping_reads_as_none(tmp_path, version): ...  # fetches=[]

def test_a_previous_version_index_meets_the_hash_check(skills_dir, tmp_path, monkeypatch):
    """Review Focus 2: a v11 file from another config is discarded whole (SRC-36)."""
    # boot once on config A, rewrite the file as v11 with V11_PLUGIN_ROW, then boot on
    # config B with `_counting_materialise`-style spy: every fetch of B is materialised.
```

Keep `test_a_v4_index_on_disk_is_discarded_whole`. Rewrite its docstring list of version
literals to add "11 while the index held plugin rows (read for its `fetches` alone, D1)".

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_index.py -v`
Expected: FAIL. `PREVIOUS_VERSION` cannot be imported, and `Index` still requires `plugins`.

- [ ] **Step 3: Implement `index.py` as the Interfaces say**

`read` refuses any version outside `(PREVIOUS_VERSION, INDEX_VERSION)`, requires `fetches` to be
a dict, and never reads the key `plugins`. Put a comment on `PREVIOUS_VERSION`: it goes once every
deployment has written 12 (#84's follow-up). The suite does not import again until Part B is
done.

#### Part B: harvests in memory, never reused

**Files:**
- Modify: `kubed/mcp_kb/catalogue/snapshot.py` (`Harvest`; `build_plugin`, `failed_plugin`,
  `build_snapshot`, `_commands`, `_serve_library`, `_plugin_status`, `_admit`, `_Admitted`;
  `Snapshot.skill_dirs`; the module docstring's "rows, not objects, because both records are also
  what gets written" paragraph says a harvest is in memory and redone every generation)
- Modify: `kubed/mcp_kb/server.py` (`_harvests`; `_cold_start`; `_assemble`; `_harvest` replaces
  `_plugin_record`; `refresh`; `_write_index`; `_serving`; the docstring's first rule)
- Test: `tests/test_refresh.py`, `tests/test_assembly.py`, `tests/test_agents.py`,
  `tests/test_live.py`, `tests/test_harvest.py`, `tests/test_config.py`, `tests/test_plugins.py`

**Interfaces:**
- Consumes: Part A's `Index`, `INDEX_VERSION`, `V11_PLUGIN_ROW`.
- Produces:
  - `snapshot.Harvest`, frozen: `id: str`, `root: Path | None`,
    `status: Literal["ok", "failed"]`, `error: str | None`, `built: str`, then, defaulting to
    `()`:
    - `skills: tuple[Skill, ...]`, with library and folder `""`;
    - `prompts: tuple[str, ...]`;
    - `claude_prompts: tuple[str, ...]`;
    - `command_dirs: tuple[str, ...]`;
    - `files: tuple[str, ...]`;
    - `skill_dirs: tuple[Path, ...]`;
    - `agents: tuple[str, ...]`;
    - `agent_paths: tuple[str, ...]`.
  - `build_plugin(plugin: Plugin, root: Path, *, globs: Globs) -> Harvest`.
  - `failed_plugin(plugin: Plugin, error: str) -> Harvest`.
  - `build_snapshot(config, plugins, libraries, fetches, harvests: dict[str, Harvest],
    generation) -> Snapshot`.
  - `Snapshot.skill_dirs: Mapping[str, tuple[str, ...]]`: each admitted plugin's skill folders,
    root-relative (`_relative`), by plugin id. Task 2 reads it.
  - `KnowledgeBase._harvests: dict[str, Harvest]`; `KnowledgeBase._assemble(fetches, *,
    refusal_is_fatal=False) -> tuple[list[Plugin], list[Library], dict[str, Harvest]]`;
    `KnowledgeBase._harvest(plugin, fetch: FetchRecord) -> tuple[Plugin, Harvest]`.
  - `server.build_plugin` stays imported by name, so the tests' spy keeps working.

- [ ] **Step 4: Write the failing tests**

In `tests/test_refresh.py`:

```python
def test_a_v11_index_boots_from_disk_with_no_network(skills_dir, cache, monkeypatch):
    first = KnowledgeBase(make_config(skills_dir), cache)
    raw = json.loads((cache / "index.json").read_text())
    raw |= {"version": 11, "plugins": {"flatsource": V11_PLUGIN_ROW}}
    (cache / "index.json").write_text(json.dumps(raw))

    def refuse(*args, **kwargs):
        raise AssertionError("no network, no fetch")
    monkeypatch.setattr(SourceLoader, "materialise", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    second = KnowledgeBase(make_config(skills_dir), cache)

    assert second.status["fetches"] == first.status["fetches"]   # every fetch kept, built unmoved
    assert [s.address for s in second.index.visible()] == [s.address for s in first.index.visible()]
    written = json.loads((cache / "index.json").read_text())
    assert written["version"] == 12 and "plugins" not in written

def test_a_v11_fetch_whose_tree_is_gone_is_built(skills_dir, cache, monkeypatch):
    # as above, then delete skills_dir / "flatsource" before the second boot, with
    # `_counting_materialise`: seen == _keys(config, "flatsource"), flatsource `failed`,
    # deepsource `ok` with its first-boot `built`.

def test_every_boot_harvests_every_plugin_from_disk(skills_dir, cache, monkeypatch):
    config = make_config(skills_dir)
    first = KnowledgeBase(config, cache)
    harvested = _harvests(monkeypatch)
    seen = _counting_materialise(monkeypatch)
    KnowledgeBase(config, cache)
    assert sorted(harvested) == sorted(p.id for p in first._plugins)
    assert seen == []
```

It replaces `test_a_cold_start_reuses_a_plugin_record_only_with_its_fetch`, which is deleted.

Change the existing tests that pin reuse:
- `test_a_cold_start_reuses_a_marketplace_entrys_records` becomes
  `test_a_cold_start_re_harvests_a_marketplace_entry_from_disk`: `"tools@up" in harvested`, no
  materialise, `_served(again, "tools@up") == ["alpha"]`.
- `test_a_cross_repository_entry_whose_lists_changed_is_harvested_again`: the
  "untouched plugin is not harvested again" assertion becomes
  `sorted(harvested) == ["own", "tools@up"]` (I7).
- `test_refresh_rebuilds_only_the_fetch_whose_fingerprint_changed`: drop the
  `_records["deepsource"] is deepsource` assertion; the fetch `built` assertion stays.
- `test_persistence_failure_does_not_leave_records_ahead_of_the_snapshot`: read
  `_harvests["deepsource"].built`.

In `tests/test_assembly.py`:
- `test_a_cold_start_reuses_the_index_and_re_reads_the_marketplace` keeps only the
  `SourceLoader.materialise` guard.
- `test_a_plugin_status_never_carries_a_null_error` and
  `test_a_snapshot_strips_library_text_before_the_index_uses_it` build `Harvest`s. The second
  one's skills are `Skill(name=n, library="", folder="", description=f"{n}.", path=tmp_path / n,
  plugin="p", root=tmp_path)`.

Rename `_records` to `_harvests` in `tests/test_agents.py` and `tests/test_live.py`. In
`tests/test_harvest.py`, `tests/test_config.py` and `tests/test_plugins.py`, a `build_plugin`
result's `.skills` are `Skill`s: compare `.name` and `.path` as `Path`.

- [ ] **Step 5: Run them to see them fail**

Run: `pytest tests/test_refresh.py tests/test_assembly.py -v`
Expected: FAIL at import (`PluginRecord`), then, once it imports, on the new tests.

- [ ] **Step 6: Implement the Interfaces**

- `_cold_start`: from a trusted index, keep the servable fetches. There are no records, and
  `_assemble(fetches, refusal_is_fatal=True)` runs.
- `_harvest`: `with_manifest` as now, then `build_plugin`, always.
- `refresh`: there is no `reusable`; `was` and the rollback hold `_harvests`.
- `_write_index`: `Index(version=INDEX_VERSION, built=now(), config_hash=..., fetches=self._fetches)`.
- `_serving(record: FetchRecord)`.
- `_serve_library`: each library's skill is `replace(skill, library=lib.name,
  folder=folder_for(lib, plugin), category=plugin.category, tags=plugin.labels,
  library_categories=lib_categories, live=is_live(plugin.fetch))`.
- `_admit` reads `Skill.path`.
- `_commands` reads `harvest.command_dirs`.
- `_plugin_status` drops `record.skipped`.
- `build_snapshot` fills `skill_dirs`.

Rewrite the first rule of `server.py`'s docstring: "Start from the fetches on disk, not from the
sources. `<cache>/index.json` holds each fetch's tree and fingerprint. A boot over the same config
keeps every tree still on disk and harvests every plugin from it, which touches no network."

- [ ] **Step 7: Run them to see them pass**

Run: `ruff check .` then
`pytest tests/test_index.py tests/test_refresh.py tests/test_assembly.py tests/test_agents.py tests/test_live.py tests/test_harvest.py tests/test_config.py tests/test_plugins.py -v`
Expected: all pass, `test_agents.py::test_a_broken_agent_frees_its_name_on_a_cold_start` (N11)
included, unchanged.

- [ ] **Step 8: Run the whole suite, then commit**

Run: `pytest -q`. Expected: green, one xfail (N15).

```bash
git add kubed/mcp_kb/catalogue/index.py kubed/mcp_kb/catalogue/snapshot.py kubed/mcp_kb/server.py tests/
git commit -S -m "feat(index): index.json holds fetch records only; every generation harvests from disk (#84)"
```

---

### Task 2: `/health` counts and `skipped` from what the layer serves

**Files:**
- Modify: `kubed/mcp_kb/mcp/skills.py` (`_narrowed`; new `_skills_of`; the parity note in the
  `mine - theirs` loop; the module docstring's parity-guard paragraph)
- Modify: `kubed/mcp_kb/spec/builder.py` (`PLUGIN_STATUS` and `SKIPPED` descriptions)
- Test: `tests/test_skipped.py`, `tests/test_openapi.py`, and the tests that pin the old counts
  (run the suite to find them)

**Interfaces:**
- Consumes: `Snapshot.skill_dirs` (Task 1); `Served.skipped`, `Served.skills`,
  `Served.agent_files` (kubed-mcp).
- Produces: `SkillServing._skills_of(plugin: Plugin, served: Served, snapshot: Snapshot) ->
  list[dict[str, str]]`. It returns the `served.skipped` rows whose path is in
  `snapshot.skill_dirs[plugin.id]`, each as `{"path": self._clean(path, plugin), "reason":
  self._clean(reason, plugin)}`, with the first reason per path, in the layer's order.

- [ ] **Step 1: Write the failing tests** (in `tests/test_skipped.py` unless named)

```python
def _big(root):                       # Task 0 (b)'s input
    _skill(root, "skills/big", "big", "Too many files.")
    for i in range(512):
        _write(root, f"skills/big/refs/{i}.md", "x\n")
    _skill(root, "skills/ok", "ok", "Fine.")

async def test_a_skill_folder_the_layer_skips_is_a_row(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="kubed.mcp_kb"):
        kb = _kb(tmp_path, _big, {})
        health = await _health(kb)
    plugin = health["plugins"]["src"]
    assert plugin["skipped"] == [{"path": "skills/big", "reason": BIG_REASON}]  # Task 0 (b)
    assert plugin["skills"] == 1
    kb_lines = [r.getMessage() for r in caplog.records
                if r.name.startswith("kubed.mcp_kb") and "big" in r.getMessage()]
    assert kb_lines == [f"plugin src skips 'skills/big': {BIG_REASON}"]      # D5: once

async def test_a_nested_skill_is_no_row_and_no_note(tmp_path, caplog):
    # skills/x/SKILL.md and skills/x/y/SKILL.md (grafana's shape)
    ...
    assert "skipped" not in plugin and "notes" not in plugin
    assert "a skill is one folder below its skills folder" not in json.dumps(health)
    assert any("a skill is one folder below its skills folder" in r.getMessage()
               for r in caplog.records if r.name == "kubed.mcp.plugins")

async def test_a_refused_plugin_counts_no_skills_prompts_or_agents(tmp_path):
    # two plugins in `lib`, each shipping commands/hello.md: the second is refused (LIB-29)
    assert health["libraries"]["lib"]["conflicts"]["second"].startswith("conflict: prompt lib_hello")
    assert {k: health["plugins"]["second"][k] for k in ("skills", "prompts", "agents")} == \
        {"skills": 0, "prompts": 0, "agents": 0}

async def test_a_skills_empty_plugin_counts_no_prompts_or_agents(tmp_path):
    # a declared plugin, `skills: []`, with skills/a/SKILL.md and commands/hello.md
    assert {k: plugin[k] for k in ("skills", "prompts", "agents")} == \
        {"skills": 0, "prompts": 0, "agents": 0}

async def test_a_plugin_refused_in_one_library_counts_what_another_serves(tmp_path):
    # Review Focus 3: `second` refused in `lib`, alone in `solo`: its counts are solo's
    assert health["plugins"]["second"]["prompts"] == 1

async def test_a_skill_kb_and_the_layer_both_skip_is_one_row(tmp_path):
    # Review Focus 4: skills/a/SKILL.md names itself `b`
    assert plugin["skipped"] == [{"path": "skills/a",
                                  "reason": "name 'b' differs from its directory 'a'"}]

async def test_a_layer_row_names_no_cache_path(tmp_path):
    # Review Focus 5: the `_big` plugin read through a `git+file://` source, so its tree sits
    # under the cache
    assert str(tmp_path / "c") not in json.dumps(health)
```

In `tests/test_openapi.py`, add `test_a_health_response_with_layer_rows_validates`: the `_big`
tree as one plugin, `validate("Health", body)`. Extend
`test_a_real_health_response_matches_the_documented_fields` to assert
`body["plugins"]["clash"]["prompts"] == 0` (I4: `clash` is declared `skills: []`).

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_skipped.py tests/test_openapi.py -v`
Expected: FAIL. No `skills/big` row is listed, a refused or `skills: []` plugin reports its
prompt files, and the parity note is logged beside `log_changes`' line.

- [ ] **Step 3: Implement D3 to D5 in `_narrowed`**

- Collect `plugin_skills[pid]` from the first `(lib, plugin, served)` for that pid: the addresses
  in `mine & theirs` not in `hidden`.
- Collect `_skills_of` rows beside the prompt and agent rows, from the same first add.
- For every `status_plugins` entry whose `status` is `"ok"`, set `skills`, `prompts` and `agents`
  from those maps, `0` where the pid is absent.
- Build `skipped` as kb's rows (`entry.get("skipped", ())`), then the skill, prompt and agent rows
  whose path no earlier row has. Drop the key when the list is empty.
- In the `mine - theirs` loop, skip the "the plugin layer refused it" note when that skill's
  folder (root-relative) has a `_skills_of` row. Pass the found `Skill`s, which `_publish`
  already has as `found`.

Change `spec/builder.py`:
- `skills`: "Skills the plugin layer serves for this plugin, from the first library that adds it;
  0 when no library adds it."
- `prompts`, `agents`: the same, with "Prompts" and "Agents".
- `built`: "When this generation harvested the plugin."
- `SKIPPED` gains, after the skill clause: "a skill folder the plugin layer does not load, with its
  reason (such as the Agent Skills limits)". It also says "one row per path; the server's own
  reason first".

- [ ] **Step 4: Run them to see them pass**

Run: `ruff check .` then
`pytest tests/test_skipped.py tests/test_openapi.py tests/test_parity.py tests/test_agents.py tests/test_prompt_serving.py tests/test_live.py tests/test_conflicts.py -v`
Expected: all pass. A test that pinned the old fallback counts, a refused or `skills: []` plugin's
prompt or agent count, or an unnarrowed skill count, is changed to the new value. Its docstring
names I4 or I5.

- [ ] **Step 5: Commit**

```bash
git add kubed/mcp_kb/mcp/skills.py kubed/mcp_kb/spec/builder.py tests/
git commit -S -m "feat(health): plugin counts and skipped rows from what the plugin layer serves (#84)"
```

---

### Task 3: The spec, AGENTS.md, the wiki, the changelog and the whole suite

**Files:**
- Modify: `docs/superpowers/specs/config-and-sources.md`, `prompts.md`, `http-and-tools.md`,
  `agents.md`, `plugins-and-libraries.md`
- Modify: `AGENTS.md` (Layout rows for `index.py` and `snapshot.py`)
- Modify: `CHANGELOG.md` (`[Unreleased]` → `### Fixed`)
- Modify: `wiki/Operations.md`, `wiki/Deployment.md`, and the generated `wiki/Endpoints.md`
  (on the wiki's `issue-84` branch)

- [ ] **Step 1: Reword the requirements, keeping their IDs**

- **SRC-30.** "`<cache>/index.json` holds the fetch records of the served snapshot: each fetch's
  key, status, root, fingerprint, `built` and error. It holds no plugin: a plugin is harvested
  from its tree on disk (SRC-37). It is written atomically at boot and after every rebuild. When
  it cannot be written, the server logs a warning and serves on."
- **SRC-36.** Add: "The server writes version 12. It also reads version 11, for its `fetches`
  alone, ignoring its `plugins` (2026-11-25, #84), until every deployment has written 12."
- **SRC-37.** "From a reused index, boot keeps each `ok` or `stale` fetch record whose tree is on
  disk, and builds the rest. Every plugin is harvested again from its fetch's tree, which touches
  no network."
- **SRC-48.** Drop the last-but-one and the record sentences. It reads: "On a change, every
  plugin is harvested again from its tree on disk, every marketplace is re-read from disk, any
  fetch a marketplace starts needing is built, and a snapshot with the next generation replaces
  the served one in one assignment. So a marketplace entry on another repository serves its edited
  `skills`, `commands`, `agents` or `git-subdir` `path` though its own fetch did not move. A request
  in flight finishes on the snapshot it started with."
- **PRM-18.** "The dialect is decided by PRM-14 each time the plugin is read. Nothing about a
  prompt is kept on disk, so a boot decides it afresh. A build of that read …" (the rest as now).
- **HTTP-9.** Add: "A plugin's `skills`, `prompts` and `agents` are what the plugin layer serves
  for it, from the first library that adds it, and `0` for an `ok` plugin that no library adds.
  Its `files` are kb's. Its `skipped` holds kb's rows (PLG-18), then the plugin layer's rows for
  its skill folders, prompt files and agent files, one row per path, each path plugin-relative and
  no reason naming a cache path. A `SKILL.md` deeper than a skill folder is no row. Its `built` is
  when this generation harvested it."
- **AGT-14.** "a plugin no library serves counts the agent files found (AGT-5)" becomes "a plugin
  no library adds counts `0`".
- **PLG-18.** Add a table row: `| a skill | the plugin layer does not load its folder; the plugin
  layer's row, with its reason |`.
- **LIB-33.** Add: "`/health` counts it `0` skills, prompts and agents."

- [ ] **Step 2: AGENTS.md, the changelog and the wiki**

- AGENTS.md Layout: `index.py` is "`Index`, `FetchRecord`: the on-disk `index.json`, the fetch
  records a cold start keeps". `snapshot.py` is "`Snapshot`, `Harvest`, `build_snapshot`: the
  immutable view every request reads, and the in-memory harvest it is built from".
- CHANGELOG `### Fixed`: "`/health` lists the skill folders a plugin cannot serve, and counts no
  skills, prompts or agents for a plugin that is not served."
- `wiki/Operations.md`:
  - "A plugin has `skipped` entries" adds "or a skill folder too big or malformed to serve".
  - "Restarts are slow" says `index.json` records the trees already downloaded. A restart with
    it downloads nothing and re-reads each plugin from disk.
- `wiki/Deployment.md`: line 71 reads "re-downloads everything on every restart", and line 121
  reads "re-clones everything instead of reading last boot's trees back".
- Run `python scripts/generate_wiki.py` and commit the wiki on its `issue-84` branch. The
  submodule pointer follows.

- [ ] **Step 3: The whole suite and the generated documents**

Run: `ruff check .`, then `pytest`, then `python scripts/generate_wiki.py --check`, then
`python scripts/generate_openapi.py` and `npx --yes @redocly/cli@2 lint openapi.yaml`.
Expected: ruff is clean, pytest is green with one xfail (N15), and the wiki check and the lint
are clean.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs AGENTS.md CHANGELOG.md wiki
git commit -S -m "docs: index.json is fetch records; /health reads the plugin layer (#84)"
```

---

### QA (not CI): boot time and the dump

- **Boot time:** in the pod, warm cache, from process start to the first `/health` 200,
  measured on the image before this change and after it. The PR body records both numbers.
  Before: the current `issue-80` image. After: this branch's image, booting from the v11 file the
  before-image wrote.
- **The dump:** ten scopes, with and without `kb+`, before and after. It differs only by I1 to I7.
