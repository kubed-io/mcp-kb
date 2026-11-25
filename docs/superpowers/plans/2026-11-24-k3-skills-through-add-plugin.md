# K3: Skills Through kubed-mcp's Plugin Layer Implementation Plan

> **History.** Proposed for #79 (PR #89, into `issue-80`). Not shipped. Revised to Dr K's rulings
> of 2026-11-24 (23:01): one library per namespace, with its main plugin on top; each plugin
> added as itself; no staged trees.

> **For agentic workers:** REQUIRED SUB-SKILL: Use skill://superpowers/subagent-driven-development/SKILL.md (recommended) or skill://superpowers/executing-plans/SKILL.md to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** kubed-mcp 0.2.0rc2's plugin layer serves every skill kb collects, each plugin read as
itself under its library's namespace. kb's scope becomes a view, and its placeholder and name
rewriting becomes its one rewriter.

**Architecture:** kb finds skills the way kubed-mcp does: `skills/<name>/`, plus declared
folders. Each library is a namespace: its main plugin sits at `<library>`, and every other
plugin at `<library>/<plugin name>`. Each generation, kb adds every plugin to a kubed-mcp plugin
set through a served-tree loader, with `commands` and `agents` emptied, and serves it. A view
keyed by the admitted `(library, address)` pairs scopes each build. K1's provider and kb's
resource mirror tools go. Library indexes, `_files.md`, library files and the fallbacks stay
kb's.

**Tech Stack:** Python ≥3.11, `kubed-mcp==0.2.0rc2` (FastMCP 4 through it), pytest +
pytest-asyncio, uvicorn, wsgidav.

**Spec:** [the design](2026-11-24-k3-skills-through-add-plugin-design.md): D1–D10, the named
changes N1–N4, and Dr K's answers of 2026-11-25 (main-plugin rule 2, `listed` none until #86,
kubed-mcp's resource tools in K3). Also #79's notes in `.issue/`, Dr K's rulings on
PR #89, quick-mcp#37 and #21, and the living spec in [skills.md](../specs/skills.md) and
[plugins-and-libraries.md](../specs/plugins-and-libraries.md).

## Global Constraints

- `pyproject.toml` pins `"kubed-mcp==0.2.0rc2"`. **The code turn waits for that release.** Task 1
  reads rc2's source for the names this plan takes from #21 and #37's text: `header_prefix`,
  `config.delivery`, DLV-6's tool names, the nesting-guard reason, and what `Plugin.skills`
  holds. It corrects the plan's names in its commit body when they differ.
- FastMCP is reached only through `kubed.mcp`, `kubed.mcp.plugins`, `kubed.mcp.skills` and
  `kubed.mcp.protocol`. `catalogue/` and `plugins/` import no FastMCP, and
  `tests/test_boundaries.py` stays green.
- Addresses are SKL-59's. The only live addresses that move are tidy's two skills and n8n-house's
  `n8n-mcp-instructions`. Absent and out of scope stay indistinguishable (SCP-24).
- Rewrite at build, never on read. Read through a getter (`lambda: knowledge_base.snapshot`),
  never a captured `Catalogue`.
- No cache path or credential reaches a log line, `/health`, a URI or a body. kubed-mcp is handed
  kb's own plugin address, never a cache path. A `PluginError` message goes through
  `snapshot.unrooted` and `config.scrub` before it's published.
- Python 3.11 floor; 88 columns; a glob ending `**` is written `dir/**/*`.
- The checks every task runs: `ruff check .`, then its tests (`pytest tests/<file>.py -v`). The
  last task runs all of `pytest`, `python scripts/generate_wiki.py --check`, and the schema check
  in `tests/test_schema.py`.

## Review Focus

1. **A marketplace that gains a second entry, or an entry renamed like its library.** The main
   plugin can then change across a refresh. Its skills' addresses move in that one generation,
   the old ones read as absent, and nothing serves twice. *(Task 3:
   `test_the_main_plugin_follows_the_config_not_the_scope` and
   `test_a_marketplace_gaining_an_entry_moves_nothing_unexpected`.)*
2. **A plugin named like one of the main plugin's skills** (`superpowers/tidy` beside a skill
   `tidy`). LIB-28 refuses the later one in that library and reports it, as #37's guard would,
   and the earlier one keeps serving. *(Task 3: `test_a_plugin_named_like_a_main_skill_conflicts`.)*
3. **A plugin whose `plugin.json` declares `commands` or `agents`.** The entry's `[]` doesn't
   empty a list `plugin.json` declares (the union), so kubed-mcp would serve those beside kb's.
   *(Task 4: `test_kubed_mcp_serves_no_prompt_or_agent`. If it fails on such a fixture, stop and
   report: that needs a quick-mcp answer.)*
4. **A `strict: false` entry beside a `plugin.json`.** kb's `"commands": []` must not make an
   entry with no components look like one with them: kubed-mcp would refuse it as conflicting
   manifests. *(Task 4: `test_a_strict_false_entry_without_components_serves`.)*
5. **A request carrying `Kb-Resource-Prefix: kb+` and `X-MCP-Resource-Prefix: other+`.**
   `kb+` is the prefix in both kb's index and kubed-mcp's `SKILL.md`, as one writer.
   *(Task 4: `test_one_prefix_wins_everywhere`.)*

---

### Task 1: Pin kubed-mcp 0.2.0rc2, `header_prefix="Kb"`, and the served-tree loader

**Files:**
- Modify: `pyproject.toml:27-32`
- Modify: `kubed/mcp_kb/sources/__init__.py`: a new `ServedTrees` class
- Modify: `kubed/mcp_kb/server.py`: `KnowledgeBase.served_tree`
- Modify: `kubed/mcp_kb/app.py`
- Test: `tests/test_served_trees.py` (new)

**Interfaces:**
- Consumes: `KnowledgeBase._fetches` (`FetchRecord.root`, `status`), `plugin_root`,
  `parse_address`, `source_fetch`.
- Produces:

```python
# sources/__init__.py
class ServedTrees:                                  # a kubed-mcp PluginLoader
    def __init__(self, schemes: tuple[str, ...], served: Callable[[str], Path | None]) -> None
    schemes: tuple[str, ...]                        # "file" and every declared source name
    def materialise(self, address: str) -> Path     # served(fetch key) + subdir, guarded

# server.py
def served_tree(self, key: str) -> Path | None      # the serving record's root, else None
```

- [ ] **Step 1: Write the failing tests** in `tests/test_served_trees.py`.
  - `test_it_answers_the_tree_kb_serves`: for a `file://` and a `git+file://` plugin,
    `loader.materialise(address) == plugin_root(Path(record.root), subdir)`, and the git
    `SourceLoader.build` is called 0 times (monkeypatched counter).
  - `test_it_serves_the_last_good_tree`: break the remote and `refresh(force=True)`. The record
    goes `stale`, and `materialise` still returns its old root.
  - `test_an_unknown_fetch_is_not_materialised`: `pytest.raises(SourceError, match="is not
    materialised")`. The message names the key and no path.
  - `test_a_subdir_link_out_of_the_tree_is_refused`: match `"is not a directory in"`.
  - `test_it_replaces_local_loader`: `create_app(kb)`, then `mcp.add_plugin(plugin.address)`
    returns a `Plugin` with `root == <the record's tree>`.
- [ ] **Step 2: Run** `pytest tests/test_served_trees.py -v`. Expected: FAIL on the import.
- [ ] **Step 3: Implement.**
  - Pin `"kubed-mcp==0.2.0rc2"`. Comment: milestones are release candidates, and a bump moves
    the pin.
  - Pass `QuickMCP(..., header_prefix="Kb")`.
  - Call `mcp.add_loader(ServedTrees((…schemes…), knowledge_base.served_tree))` before any
    `register`. `served_tree` reads `self._fetches`, which is set under the lock by
    `_cold_start`, `_fetch_record` and `refresh`, after `keep_last_good`.
  - In the commit body, record what rc2's source says for each name the Global Constraints
    list.
- [ ] **Step 4: Run** `pip install -e ".[test]"`, `ruff check .`, then all of `pytest`.
  Expected: PASS. Fix here any existing test that rc2's middleware (`_PinScope`,
  `_TakeThePrefix`, the delivery pin) breaks.
- [ ] **Step 5: Commit** `build: pin kubed-mcp 0.2.0rc2, serve kb's trees as its loader`.

### Task 2: kb finds skills the way kubed-mcp serves them

**Files:**
- Modify: `kubed/mcp_kb/catalogue/harvest.py`:
  - `skill_dirs(root, declared)` takes the native rule;
  - delete `SKILL_ROOTS`, `folder_of` and `DEFAULTS["skills"]`.
- Modify: `kubed/mcp_kb/catalogue/snapshot.py`: `with_manifest` gives `Globs.skills` as the
  declared folders, and LIB-32's branch goes.
- Modify: `kubed/mcp_kb/config.py`: `PluginConfig.skills` is folders, and a glob character
  (`*`, `?`, `[`) is refused.
- Modify: `kubed/mcp_kb/catalogue/index.py`: bump `INDEX_VERSION`.
- Modify: `config.schema.json`, regenerated.
- Modify: `tests/conftest.py`: the synthetic trees use `skills/<name>/`, and its addresses stay
  as they are (Task 3 gives `deepsource`'s folders from plugin names).
- Test: `tests/test_harvest.py`, `tests/test_config.py`, `tests/test_marketplace.py`,
  `tests/test_plugins.py`, `tests/test_skills.py`

**Interfaces:**
- Produces: `harvest.skill_dirs(root: Path, declared: Sequence[str] = ()) -> list[Path]`, in
  claim order. `Globs.skills: tuple[str, ...] | None`, where None means no declared folders and
  `()` means serve no skills.

- [ ] **Step 1: Write the failing tests** (new or rewritten) in `tests/test_harvest.py`:
  - `test_a_skill_is_a_direct_child_of_skills`: `skills/a/SKILL.md` is found;
    `skills/g/b/SKILL.md` is not; `.claude/skills/c/SKILL.md` is not; a root `SKILL.md` is not.
  - `test_a_declared_folder_is_a_skill_or_holds_skills`:
    - `declared=["./skills/g/b"]` finds `skills/g/b`;
    - `["./skills/g"]` finds `skills/g/b` and `skills/g/c`, and not `skills/g/b/deep`;
    - `["./missing"]` finds nothing.
  - `test_the_first_claim_wins`: a folder reached by the scan and by a declaration is found once.
  - `test_dot_folders_are_skipped`: `skills/.hidden/SKILL.md` is not found.
  - `test_grafana_entries_serve_their_declared_skills`: a root entry declaring
    `./skills/grafana-lgtm/loki` serves exactly that one, as LIB-32 did.
  - In `tests/test_config.py`, `test_a_glob_in_skills_is_refused` raises a `ValueError` naming the
    item, and `test_skills_empty_serves_none` holds.
  - Delete every test of a removed behaviour: skill globs, SKL-2's directory spelling, the
    `.claude/.github/.agents` skill roots, deeper folders, a plugin-root skill, LIB-32. Name each
    deleted one, and the requirement it pinned, in the commit body.
- [ ] **Step 2: Run** `pytest tests/test_harvest.py tests/test_config.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the rule as the design's D3 writes it, mirroring kubed-mcp's
  `_skill_folders`.
  - The declared order is the manifest's `skills`, then the entry's, then a declared plugin's
    `skills:`.
  - `files:` and `prompts:` keep their globs.
  - Regenerate the schema with `python -m kubed.mcp_kb schema > config.schema.json`.
- [ ] **Step 4: Run** `ruff check .` and all of `pytest`. Expected: PASS, except the address
  tests Task 3 owns, which assert the `deepsource` folders. If any fail here, Task 2 and Task 3
  merge into one commit.
- [ ] **Step 5: Commit** `feat!: find skills as Claude Code and kubed-mcp do`.

### Task 3: A library is a namespace, with its main plugin on top

**Files:**
- Modify: `kubed/mcp_kb/catalogue/snapshot.py`:
  - `Library.main: str | None`, set in `assemble_libraries`;
  - `_serve_library` gives each skill its folder;
  - `_Claims` runs on those addresses.
- Modify: `kubed/mcp_kb/catalogue/index.py`: `SkillRow.to_skill(..., folder: str)`
- Modify: `kubed/mcp_kb/plugins/marketplace.py`: the published entry count is kept on the result
  (`Marketplace.entries: int`).
- Test: `tests/test_namespaces.py` (new); `tests/test_conflicts.py`

**Interfaces:**
- Produces:
  - `Library.main` (a plugin id, or None);
  - `snapshot.folder_for(lib: Library, plugin: Plugin) -> str`, which is `""` for `lib.main` and
    `plugin.name` otherwise;
  - `snapshot.namespace_for(lib, plugin) -> str`, which is `lib.name`, or
    `f"{lib.name}/{plugin.name}"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_namespaces.py`.
  - `test_a_plugin_named_like_its_library_is_main`: library `superpowers` with plugins
    `superpowers` and `tidy` has `main == "superpowers"`. Skill addresses are
    `superpowers/writing-plans` and `superpowers/tidy/natural-writing`.
  - `test_a_lone_entry_is_main_whatever_its_path`: in library `n8n`, a marketplace whose only
    entry is named `x` makes `x` main, whether its `source` is `./` or `./plugins/claude/x`. A
    listed plugin `n8n-house` is `n8n/n8n-house/<skill>`.
  - `test_several_entries_have_no_main`: grafana's seven entries give `main is None`, with
    addresses `grafana/grafana-lgtm/loki` as today.
  - `test_a_skipped_entry_still_counts`: a marketplace with one root entry and one `source:
    command` entry has no main.
  - `test_the_main_plugin_follows_the_config_not_the_scope`: `Library.main` is computed without
    a `Scope` (`inspect.signature`). Under `?tag=` admitting only the nested plugin, its
    addresses are unchanged.
  - `test_a_marketplace_gaining_an_entry_moves_nothing_unexpected`: add a second entry and
    refresh. The former main's skills move to `<library>/<name>/…`; their old addresses read as
    absent; `/health` shows no conflict.
  - `test_a_plugin_named_like_a_main_skill_conflicts`: main skill `tidy` plus a plugin `tidy`
    gives `/health` `libraries[lib]["conflicts"]["tidy"]` starting `conflict: skill://lib/tidy`,
    and the main plugin serves.
- [ ] **Step 2: Run** `pytest tests/test_namespaces.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** D1's three rules in `assemble_libraries`, in library order. Bump
  `INDEX_VERSION` once for Tasks 2 and 3 together.
- [ ] **Step 4: Run** `ruff check .` and all of `pytest`. Expected: PASS.
- [ ] **Step 5: Commit** `feat!: a library is a namespace, with its main plugin on top`.

### Task 4: Serve skills through the plugin set, the view and kb's rewriter

**Files:**
- Create: `kubed/mcp_kb/mcp/skills.py`
- Delete: `kubed/mcp_kb/mcp/skill_catalogue.py`
- Modify: `kubed/mcp_kb/server.py`: `serve_through`; `refresh` runs the publisher before
  `log_changes` and the swap.
- Modify: `kubed/mcp_kb/config.py`: `Config.delivery`
- Modify: `kubed/mcp_kb/catalogue/uris.py`:
  - `_instructions` becomes `instructions(address, text, scope)`;
  - `skill_files` stops rewriting;
  - `live_stamp(skill)`;
  - delete `_text`'s rewriting caller.
- Modify: `kubed/mcp_kb/plugins/__init__.py`: `Plugin.address` and `Plugin.manifest_entry`;
  `plugins/marketplace.py` keeps the entry as published.
- Modify: `kubed/mcp_kb/mcp/tools.py`: delete `list_resources` and `read_resource`.
  `kubed/mcp_kb/mcp/resources.py`'s `HideMirrorTools` keeps only the prompt tools.
- Modify: `kubed/mcp_kb/app.py`, `mcp/pins.py`, `mcp/agents.py`, `tests/conftest.py:52-67`
- Test: `tests/test_plugin_serving.py` (new); `tests/test_skills_extension.py`,
  `tests/test_uris.py` and `tests/test_scope_and_prompt_tools.py` are rewritten where they
  reached K1 or kb's resource tools.

**Interfaces:**
- Consumes: `ServedTrees` (Task 1), `harvest.skill_dirs` (Task 2), `Library.main` and
  `namespace_for` (Task 3), `kubed.mcp.plugins` `View`, `Site`, `PluginError`.
- Produces:

```python
# plugins/__init__.py
Plugin.address -> str                          # "<scheme>://<path>[//<subdir>][?ref=<ref>]"
Plugin.manifest_entry: Mapping[str, object] | None   # the entry as published, less "source"

# mcp/skills.py
EMPTY: frozenset[tuple[str, str]] = frozenset()
class SkillServing:
    def __init__(self, mcp: QuickMCP, knowledge_base: KnowledgeBase) -> None
    def attach(self) -> None          # plugin_view, add_rewriter, kb.serve_through(publish)
    def publish(self, snapshot: Snapshot) -> Snapshot
    def view(self) -> View
    def rewrite(self, site: Site, text: str) -> str
def entry_for(plugin: Plugin) -> dict[str, object]   # manifest= with commands/agents []

# server.py
def serve_through(self, publish: Callable[[Snapshot], Snapshot]) -> None

# catalogue/uris.py
def instructions(self, address: str, text: str, scope: Scope = EVERYTHING) -> str
def live_stamp(self, skill: Skill) -> tuple
```

- [ ] **Step 1: Write the failing tests** in `tests/test_plugin_serving.py`. They use a
  `fastmcp.Client(server_of(kb))`, or conftest's uvicorn fixture for headers.
  - `test_every_skill_reads_at_its_address`: `skills/list` URIs `== {f"skill://{s.address}/SKILL.md"
    for s in catalogue.visible_skills()}`, and each read equals `catalogue.instructions(address,
    raw)`.
  - `test_the_listing_is_index_rows_only`: `resources/list` equals the K2 baseline for the
    fixture, with no `SKILL.md` row; under `Kb-Listing: full`, kb's full rows (SKL-16).
  - `test_kubed_mcp_serves_no_prompt_or_agent` (Review Focus 3): a fixture plugin with
    `commands/` and `agents/`, and another whose `plugin.json` declares both. `prompts/list`
    names equal `[p.name for p in snapshot.prompts]`, and `agents/list` equals
    `catalogue.agent_cards()`.
  - `test_a_strict_false_entry_without_components_serves` (Review Focus 4): its skills read and
    `/health` shows no conflict.
  - `test_skill_md_is_rewritten_by_kb_alone`: `${CLAUDE_PLUGIN_ROOT}/skills/kit/ref.md`, bare
    `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_SKILL_DIR}` and `kit:other` read as
    `skill://lib/kit/ref.md`, `skill://lib`, `skill://lib/kit` and `skill://lib/other/SKILL.md`.
    A `notes.md` holding the same strings reads as written.
  - `test_two_scopes_with_one_key_read_the_same_bytes`: `?library=lib`, and a `?tag=` admitting
    exactly `lib`'s plugins, read the same text and digest for a `SKILL.md` citing `kit:other`,
    and `serving.view().key` is equal under both.
  - `test_an_out_of_scope_skill_reads_as_absent`: the same error as `skill://lib/nope/SKILL.md`.
  - `test_one_prefix_wins_everywhere` (Review Focus 5): with `Kb-Resource-Prefix: kb+` and
    `X-MCP-Resource-Prefix: other+`, the `SKILL.md` read and `skill://lib/_index.md` both hold
    `kb+skill://` and no `other+`.
  - `test_a_refused_add_is_a_conflict`: monkeypatch `PluginSet.add` to raise
    `PluginError("x is inside skill skill://lib/x/SKILL.md of plugin y")` for one plugin.
    - `/health` `conflicts[pid]` holds `conflict: ` and that text;
    - that plugin's skills read as absent and are in no index;
    - the rest serve.
  - `test_kb_names_only_what_kubed_mcp_serves`: a skill with `description: ""` doesn't read. It
    is in no index, hint or `skills/list`, and a name citing it is served as written. One log
    line says so.
  - `test_the_resource_tools_are_kubed_mcps`: `tools/list` under `?resources=off` holds DLV-6's
    two tools, and under neither header no resource tool. A call reads `skill://lib/_index.md`
    and a `SKILL.md`. kb's `tools.py` defines no tool of either name.
  - `test_a_refresh_serves_the_new_set`: an edit reads; a deleted skill reads as absent and
    leaves its index.
  - `test_a_skill_arriving_after_boot_reads`: boot with no skills, add one and refresh. Its
    `SKILL.md`, `_manifest` and `<skill>/_index.md` read.
  - `test_manifest_names_the_skill_by_its_name` (N1); `test_a_json_file_reads_as_text` (#37).
- [ ] **Step 2: Run** `pytest tests/test_plugin_serving.py -v`. Expected: FAIL on the import.
- [ ] **Step 3: Implement.**
  - **`publish`:**
    - for each library, each plugin in its order that is admitted by LIB-28, `ok`, and has
      skills: `set.add(plugin.address, namespace=namespace_for(lib, plugin),
      manifest=entry_for(plugin))`;
    - a `PluginError` or `ValueError` is a conflict (scrubbed, unrooted, logged);
    - then `mcp.serve(set)`;
    - narrow the catalogue with `without(...)` to the URIs each added `Plugin.skills` serves;
    - log each skill either side has alone, dropping the two "Default … folder is ignored" notes;
    - rebuild the table keyed by `(library, address)`;
    - return `replace(snapshot, catalogue=…, status=…)`.
  - **`entry_for`:** `{**(plugin.manifest_entry or {"name": plugin.name}), "commands": [],
    "agents": []}`, plus the declared `skills:` for a declared plugin. A `strict: false` entry
    keeps its `strict` as published.
  - **`view`:** the frozenset of admitted `(library, address)` pairs by `Scope.admits`, else
    `EMPTY`.
  - **`rewrite`:** on `site.kind == "skill"` and a root `SKILL.md`, return
    `knowledge_base.snapshot.catalogue.instructions(address, text, requested_scope())`; otherwise
    return `text`.
  - **`Config.delivery`:** `listed` is empty, and `resources` and `via` are unset, in the shape
    rc2's `Delivery` protocol takes. If rc2 can't express an empty `listed` in config, stop and
    report.
  - **`create_app`:** call `SkillServing(mcp, kb).attach()` before `resources.register`. The
    `Catalogue` transient and the other getters become `lambda:
    knowledge_base.snapshot.catalogue`.
  - **`conftest.served`:** a skill's file is the raw text, `SKILL.md` through `instructions`.
  - Delete `mcp/skill_catalogue.py`, and kb's two resource tools.
- [ ] **Step 4: Run** `ruff check .` and all of `pytest`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: serve skills through kubed-mcp's plugin set, view and rewriter`.

### Task 5: A refused or empty scope builds nothing (ruling 8)

**Files:**
- Modify: `kubed/mcp_kb/mcp/pins.py`: `what_is_wrong` and `_serving` lose `catalogue`
- Modify: `kubed/mcp_kb/app.py`
- Test: `tests/test_scope_builds.py` (new)

**Interfaces:**
- Produces: `what_is_wrong(scope: Scope, config: Config, snapshot: Snapshot) -> str | None`.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_refused_scope_builds_nothing`: count `admits` calls. Fifty distinct unknown `Kb-Tag`
    values each fail with `-32602`, and the count stays 0.
  - `test_scopes_admitting_nothing_share_one_key`: two scopes on a declared library whose only
    plugin is down both give `EMPTY`, with at most one build between them.
  - `test_what_is_wrong_reads_the_snapshot`: its parameters are `{"scope", "config",
    "snapshot"}`.
- [ ] **Step 2: Run** `pytest tests/test_scope_builds.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** `_serving` reads `snapshot.catalogue`.
- [ ] **Step 4: Run** `ruff check .` and `pytest tests/test_scope_builds.py
  tests/test_header_scope.py tests/test_scope_and_prompt_tools.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `fix: a refused or empty scope builds no skills`.

### Task 6: A live skill's edit is re-read and served (ruling 7)

**Files:**
- Modify: `kubed/mcp_kb/mcp/skills.py`: `view` calls `_reread_live(scope)`
- Test: `tests/test_live.py` (its `SkillCatalogue` tests move to a served app)

**Interfaces:**
- Consumes: `Catalogue.live_stamp(skill)`, `PluginSet.keep`, the table (Task 4).
- Produces: `SkillServing._reread_live(scope: Scope) -> None`, run under `self._lock` acquired
  with `blocking=False`.

- [ ] **Step 1: Write the failing tests.** They use the WebDAV fixture with `cache: live`, and
  each edit changes the file's length (wsgidav's ETag).
  - `test_a_live_edit_reads_after_trust`: past the 2 s trust, the next read returns the new text,
    and `_manifest` and `skills/get` describe it.
  - `test_a_reread_keeps_every_other_plugin`: every other `Plugin` in `mcp.plugins` is the same
    object, and `mcp.generation` moved by one.
  - `test_no_reread_while_a_refresh_publishes`: with the lock held, `mcp.generation` doesn't move.
  - `test_an_out_of_scope_live_skill_is_not_revalidated`: wsgidav logs no request for its files.
- [ ] **Step 2: Run** `pytest tests/test_live.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** D9.
  - For each admitted live plugin, compare the stamps over its skills with the ones recorded at
    publish. For those that moved, build a new set: `keep` the rest and `add` the moved address
    again. Then `serve`.
  - **Stop and report** if kubed-mcp pins its state before calling the view function, so the
    edit shows a request late.
- [ ] **Step 4: Run** `ruff check .` and `pytest tests/test_live.py tests/test_webdav_source.py
  -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: a live skill's edit is re-read and served`.

### Task 7: The spec, AGENTS.md, the wiki and the changelog

**Files:**
- Modify: `docs/superpowers/specs/skills.md`, `plugins-and-libraries.md`,
  `config-and-sources.md`, `scoping-and-instructions.md` and `http-and-tools.md`
- Modify: `AGENTS.md` (Layout; the skills section; "Where code goes"; the mirror-tools text);
  `CONTRIBUTING.md` ("Where things live")
- Modify: `examples/config.yaml` only if a comment names a removed layout. Modify the hand-written
  wiki pages (Skills, Plugins, Tools notes) on the wiki branch named after this PR's branch.
  Regenerate the generated pages with `python scripts/generate_wiki.py`.
- Modify: `CHANGELOG.md` `[Unreleased]`
- Modify: the design's History line

- [ ] **Step 1: Edit the spec** as the design's "The spec, as the PR leaves it" lists, keeping
  the IDs; removed ones leave gaps.
  - **New SKL-59:** a library's main plugin (D1's three rules), its namespace `<library>`, every
    other plugin's `<library>/<plugin name>`, and that a scope never moves an address.
  - **New SKL-60:** kb's one rewriter, with SKL-55 then SKL-25 and SKL-52, on a root `SKILL.md`,
    before the prefix.
  - **New SCP-36:** one build per admitted `(library, plugin)` set; `EMPTY` is shared; a refused
    scope builds nothing.
- [ ] **Step 2: Edit AGENTS.md and CONTRIBUTING.md.** `mcp/skills.py` replaces
  `skill_catalogue.py`, and the served-tree loader is described. The tools paragraph says the
  resource mirror is kubed-mcp's and the prompt mirror kb's. Add one "cost an afternoon" bullet:
  kubed-mcp serves a library's main plugin at `<library>`, so a plugin named like one of its
  skills is a conflict.
- [ ] **Step 3: Write the changelog.** Under `Changed`:
  - "**BREAKING:** skills are found as Claude Code finds them: `skills/<name>/` and declared
    folders. A declared plugin's `skills:` lists folders."
  - "A library's plugins other than its main one serve under `skill://<library>/<plugin>/`."
  - "A skill's `_manifest` names the skill by its name."
- [ ] **Step 4: Run** `python scripts/generate_wiki.py --check`, `ruff check .`, then all of
  `pytest`. Expected: PASS.
- [ ] **Step 5: Commit** `docs: spec, AGENTS.md and the wiki for skills through kubed-mcp`.

After merge into `issue-80`, QA updates the n8n library's note in the cluster's
`mcp/mcp-kb/config.yaml` and runs the ten-scope dump with and without `kb+`. It should differ
from the before-dump only by N1–N4.
