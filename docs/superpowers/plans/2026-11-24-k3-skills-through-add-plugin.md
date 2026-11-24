# K3: Skills Through kubed-mcp's Plugin Layer Implementation Plan

> **History.** Proposed for #79 (PR #89, into `issue-80`). Not shipped.

> **For agentic workers:** REQUIRED SUB-SKILL: Use skill://superpowers/subagent-driven-development/SKILL.md (recommended) or skill://superpowers/executing-plans/SKILL.md to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** kubed-mcp 0.2.0rc1's plugin layer serves every skill kb collects, at the address it has
today. kb's scope becomes a view, and its placeholder and name rewriting becomes a rewriter.

**Architecture:** Each generation, kb stages one tree per (library, plugin, folder) and adds it to
a kubed-mcp plugin set under namespace `<library>[/<folder>]`. Each tree holds exactly that
group's skills, plus a `plugin.json` that lists them. kb then serves the set. A view keyed by the
admitted `(library, plugin)` pairs scopes the build. One kb rewriter applies SKL-55, SKL-25 and
SKL-52 to `SKILL.md`. K1's provider is deleted. Library indexes, `_files.md`, library files and
the fallbacks stay kb's.

**Tech Stack:** Python ≥3.11, `kubed-mcp==0.2.0rc1` (FastMCP 4 through it), pytest +
pytest-asyncio, uvicorn, wsgidav.

**Spec:** [the design](2026-11-24-k3-skills-through-add-plugin-design.md). It holds D1–D8, the
named changes N1–N4, and the five decisions it asks Dr K for. Also #79's notes in `.issue/`, and
the living spec in [skills.md](../specs/skills.md) and
[scoping-and-instructions.md](../specs/scoping-and-instructions.md).

## Global Constraints

- `pyproject.toml` pins `"kubed-mcp==0.2.0rc1"`, and nothing else in it changes.
- FastMCP is reached only through `kubed.mcp`, `kubed.mcp.plugins`, `kubed.mcp.skills` and
  `kubed.mcp.protocol`, never `fastmcp` or `mcp` directly.
- `catalogue/` and `plugins/` import no FastMCP, and `tests/test_boundaries.py` stays green.
  `catalogue/stage.py` is therefore handed its check; it does not import one.
- Every address stays as it is (SKL-9, SKL-10). Absent and out of scope stay indistinguishable
  (SCP-24).
- Rewrite at build, never on read. Read through a getter (`lambda: knowledge_base.snapshot`),
  never a captured `Catalogue`.
- No cache path, credential or backend name reaches a log line, `/health`, a URI or a body. A
  `PluginError` message is passed through `snapshot.unrooted` and `config.scrub` before it's
  published.
- Python 3.11 floor: no 3.12+ syntax, and a glob ending `**` is written `dir/**/*`. Lines are at
  most 88 columns.
- The checks every task runs: `ruff check .`, then the task's tests (`pytest tests/<file>.py
  -v`). The last task runs all of `pytest` and `python scripts/generate_wiki.py --check`.

## Review Focus

1. **A boot with no skills, then a refresh that adds one.** `_Skills` is registered after
   `CatalogueProvider`, and the new skill's files, `_manifest` and in-skill `_index.md` still
   read. *(Task 3: `test_a_skill_arriving_after_boot_reads`.)*
2. **A plugin with skills in several folders and at the top** (`skills/a/x`, `skills/b/y`,
   `skills/z`) keeps all three addresses. The stage for folder `a` doesn't also serve `z`
   through kubed-mcp's default `skills/` scan. *(Task 2 and Task 3:
   `test_a_plugin_spanning_folders_keeps_each_address`.)*
3. **Two scopes with one view key read the same bytes.** Take `?library=` and a `?tag=` that
   admit exactly one library's plugins: they read the same `SKILL.md` text and entry digests,
   with a qualified name resolved. *(Task 3: `test_two_scopes_with_one_key_read_the_same_bytes`.)*
4. **A refresh that removes a skill.** Once `refresh()` returns, the skill's read, its index line
   and its `skills/list` entry are all gone. A stage no longer served is deleted from disk.
   *(Task 3: `test_a_refresh_serves_the_new_set`.)*
5. **A CRLF or invalid-UTF-8 file in a skill** reads with LF and U+FFFD, as today (SKL-22).
   Through kubed-mcp, its digest matches the bytes read. *(Task 2:
   `test_staged_text_is_normalised`; Task 3: `test_digests_describe_the_bytes_read`.)*

---

### Task 1: Pin kubed-mcp 0.2.0rc1, and kb's `file` loader replaces `LocalLoader`

**Files:**
- Modify: `pyproject.toml:27-32` (the `kubed-mcp` line and its comment)
- Modify: `kubed/mcp_kb/app.py` (`create_app`)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `KnowledgeBase.loaders["file"]` (a `FileLoader`, `sources/__init__.py`) and
  `QuickMCP.add_loader(loader)`.
- Produces: an app whose `file://` addresses go through kb's `FileLoader`. Task 3 adds stages
  as `file://<abs path>`.

- [ ] **Step 1: Write the failing test** `test_kbs_file_loader_answers_file_addresses` in
  `tests/test_app.py`:
  - make a plugin dir, and a `link` symlink inside it pointing at a directory outside it;
  - `mcp = create_app(kb)`;
  - `with pytest.raises(PluginError, match="is not a directory in"):
    mcp.add_plugin(f"file://{root}//link")`.

  kubed-mcp's `LocalLoader` would follow the link. The second assertion is
  `mcp.add_plugin(f"file://{root}")` returning a `Plugin` whose `root == root`.
- [ ] **Step 2: Run it.** `pytest tests/test_app.py::test_kbs_file_loader_answers_file_addresses
  -v`. Expected: FAIL. The first call does not raise.
- [ ] **Step 3: Implement.**
  - Pin `"kubed-mcp==0.2.0rc1"`, with the comment saying milestones are release candidates and
    a later bump moves the pin.
  - In `create_app`, call `mcp.add_loader(knowledge_base.loaders["file"])` before any
    `register`.
  - Register no other loader: kb materialises its own fetches.
- [ ] **Step 4: Run** `pip install -e ".[test]"`, `ruff check .`, then all of `pytest`.
  Expected: PASS. If 0.2.0rc1's new middleware (`_PinScope`, `_TakeThePrefix`) breaks an
  existing test, fix it here and say how in the commit body.
- [ ] **Step 5: Commit** `build: pin kubed-mcp 0.2.0rc1, kb's file loader replaces LocalLoader`.

### Task 2: Stage a library's skills as kubed-mcp plugins

**Files:**
- Create: `kubed/mcp_kb/catalogue/stage.py`
- Modify: `kubed/mcp_kb/catalogue/uris.py`:
  - `skill_files` no longer rewrites;
  - new `live_stamp(skill)`, replacing `live_stamp(scope)`;
  - `_instructions` becomes `instructions`;
  - delete `_text`'s rewriting caller.
- Test: `tests/test_stage.py` (new), `tests/test_uris.py:150-185`

**Interfaces:**
- Consumes:
  - `Catalogue.visible_skills(EVERYTHING)`;
  - `Catalogue.selected(EVERYTHING)`, whose `LibraryText.plugins` is the `(id, name)` pairs in
    library order;
  - the `Skill` fields `library`, `plugin`, `folder`, `name`, `path`, `root`, `live`,
    `category`, `tags`, `library_categories`.
- Produces, in `catalogue/stage.py`:

```python
Check = Callable[[dict[str, bytes]], str | None]   # None: FastMCP accepts the skill

@dataclass(frozen=True)
class Stage:
    library: str
    plugin: str                  # kb plugin id
    name: str                    # plugin name, written into the staged plugin.json
    folder: str
    root: Path                   # <into>/<digest>
    skills: tuple[str, ...]      # the addresses staged, sorted
    category: str | None
    labels: frozenset[str]
    library_categories: frozenset[str]
    live: bool
    stamp: tuple = ()            # Catalogue.live_stamp over its skills when live

    @property
    def namespace(self) -> str: ...   # "<library>/<folder>", or "<library>"
    @property
    def address(self) -> str: ...     # f"file://{self.root.as_posix()}"

@dataclass(frozen=True)
class Staged:
    stages: tuple[Stage, ...]          # library order, plugin order, folder order
    refused: dict[str, str]            # address -> why it is not served

def stage_catalogue(catalogue: Catalogue, into: Path, check: Check | None = None) -> Staged
def restage(stage: Stage, catalogue: Catalogue, into: Path) -> Stage
def prune(into: Path, keep: Iterable[Path]) -> None
```

- Produces, in `catalogue/uris.py`:
  - `Catalogue.skill_files(skill, scope=EVERYTHING) -> dict[str, str]`: raw text per file, no
    rewriting;
  - `Catalogue.instructions(address: str, text: str, scope: Scope = EVERYTHING) -> str`;
  - `Catalogue.live_stamp(skill: Skill) -> tuple`: it revalidates and stats one live skill's
    files, and returns `()` when the skill isn't live. It decides no visibility: the skill
    passed is already chosen.

- [ ] **Step 1: Write the failing tests** in `tests/test_stage.py`. They use conftest's synthetic
  tree, plus `tmp_path` plugins built in the test.
  - `test_one_stage_per_library_plugin_and_folder`: the set of `(s.library, s.plugin, s.folder)`
    equals the set over `catalogue.visible_skills()`, and each stage's `skills` are exactly that
    group's addresses.
  - `test_a_plugin_spanning_folders_keeps_each_address`: one plugin with `skills/a/x`,
    `skills/b/y` and `skills/z` gives namespaces `{"lib/a", "lib/b", "lib"}`. The `lib/a` stage
    holds `skills/a/x/**` and no `skills/z`.
  - `test_a_stage_holds_only_its_skills`: the staged files are `.claude-plugin/plugin.json` and
    each skill's files at its plugin-relative path, and nothing else. A `commands/`, `agents/`
    or library file in the source plugin isn't staged. `json.loads(plugin.json) == {"name":
    <plugin name>, "skills": ["./skills/a/x"]}`.
  - `test_a_plugin_root_skill_is_staged_under_its_name`: a root that is itself skill `loki`
    stages at `loki/`, listed `"./loki"`, namespace `lib`.
  - `test_staged_text_is_normalised`: a `SKILL.md` written with `\r\n` and a `b"\xff"` byte
    stages as LF text with `"�"`, encoded UTF-8.
  - `test_hidden_and_reserved_files_are_not_staged`: `.secret`, `_index.md`, `_index.json` and a
    root `_manifest` inside a skill are absent from its stage.
  - `test_a_nested_skill_is_refused_and_ships_inside_its_outer`: `refused[inner] == "it sits
    inside the skill at <outer>"`. No stage lists `inner`, and the inner skill's `SKILL.md` is
    among the outer stage's files.
  - `test_a_skill_the_check_refuses_is_left_out`: `check` returns `"bad"` for one skill, so
    `refused[address] == "bad"`, and no stage holds it.
  - `test_an_unchanged_stage_is_reused`: staging twice gives the same `root`, and the
    `plugin.json` keeps its `st_mtime_ns`. Editing one skill file gives that stage a new
    `root`, and only that one.
  - `test_prune_keeps_what_is_served`: `prune(into, [a.root])` leaves `a.root` and removes every
    other entry of `into`, temporary siblings included.
  - In `tests/test_uris.py`, the three `skill_files` tests assert raw text. The rewrite they
    asserted moves to a new `test_instructions_resolves_names_and_placeholders`, with
    `catalogue.instructions(address, text, scope)` and the same expected strings.
- [ ] **Step 2: Run** `pytest tests/test_stage.py tests/test_uris.py -v`. Expected: FAIL, because
  `kubed.mcp_kb.catalogue.stage` doesn't exist.
- [ ] **Step 3: Implement `stage.py` and the `uris.py` changes.**
  - Group by `(library, plugin id, folder)`, ordered by `selected()`'s library and plugin order,
    then folder.
  - Nested-skill refusal is K1's `_check` rule, moved here.
  - Text comes from `skill_files`.
  - The digest is SHA-256 over `namespace`, `name`, and each sorted `(staged path, bytes)`.
  - Write into `into / f".tmp-{digest}-{os.getpid()}"`, then `os.replace` it onto `into /
    digest[:32]`. A target that already exists is reused, and the temporary one is removed.
  - `restage` stages one group again from disk, with a fresh `stamp`.
- [ ] **Step 4: Run** `ruff check .` and `pytest tests/test_stage.py tests/test_uris.py
  tests/test_boundaries.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: stage each library's skills as kubed-mcp plugins`.

### Task 3: Serve skills through the plugin set, the view and kb's rewriter

**Files:**
- Create: `kubed/mcp_kb/mcp/skills.py`
- Delete: `kubed/mcp_kb/mcp/skill_catalogue.py`
- Modify: `kubed/mcp_kb/app.py`
- Modify: `kubed/mcp_kb/server.py`: `serve_through`, then `refresh` and `__init__` call the
  publisher.
- Modify: `kubed/mcp_kb/catalogue/snapshot.py`: `Snapshot.stages: tuple[Stage, ...] = ()`.
- Modify: `kubed/mcp_kb/mcp/pins.py`, `kubed/mcp_kb/mcp/agents.py` and
  `kubed/mcp_kb/mcp/resources.py`, wherever they reached `SkillCatalogue`.
- Modify: `tests/conftest.py:52-67` (`served`)
- Test: `tests/test_plugin_serving.py` (new); `tests/test_skills_extension.py` is rewritten
  against a served app.

**Interfaces:**
- Consumes: `stage_catalogue`, `prune`, `Stage`, `Staged` and `Catalogue.instructions` (Task 2);
  `kubed.mcp.plugins` `View`, `Site`, `PluginError`; `kubed.mcp.skills.Skill.from_files`.
- Produces, in `mcp/skills.py`:

```python
EMPTY: frozenset[tuple[str, str]] = frozenset()

class SkillServing:
    def __init__(self, mcp: QuickMCP, knowledge_base: KnowledgeBase) -> None
    def attach(self) -> None            # plugin_view, add_rewriter, kb.serve_through(publish)
    def publish(self, snapshot: Snapshot) -> Snapshot
    def view(self) -> View
    def rewrite(self, site: Site, text: str) -> str
    @staticmethod
    def check(files: dict[str, bytes]) -> str | None
```

- Produces, in `server.py`: `KnowledgeBase.serve_through(publish: Callable[[Snapshot],
  Snapshot]) -> None`. It takes `self._lock`, and sets `self.snapshot = publish(self.snapshot)`,
  logging `log_changes(before, after)`. From then on, `refresh` runs `publish` on the built
  snapshot before `log_changes` and the swap.

- [ ] **Step 1: Write the failing tests** in `tests/test_plugin_serving.py`. They use a
  `fastmcp.Client(server_of(kb))`, and conftest's uvicorn fixture where a scope or a header is
  needed.
  - `test_every_skill_reads_at_its_address`:
    - the URIs `skills/list` returns equal `{f"skill://{s.address}/SKILL.md" for s in
      catalogue.visible_skills()}`;
    - each `SKILL.md` read equals `catalogue.instructions(address, raw)`;
    - `mcp.server`'s providers include no `SkillCatalogue`.
  - `test_a_plugin_spanning_folders_keeps_each_address`: Task 2's plugin, served. Its three
    `SKILL.md` read, and `skill://lib/_index.md` lists `skill://lib/a/_index.md`,
    `skill://lib/b/_index.md` and `skill://lib/z/SKILL.md`.
  - `test_kubed_mcp_serves_no_prompt_or_agent_of_its_own`: with a fixture plugin holding
    `commands/` and `agents/`, the `prompts/list` names equal `[p.name for p in
    snapshot.prompts]`, and `agents/list` equals `catalogue.agent_cards()`.
  - `test_skill_md_is_rewritten_by_kb_alone`. A fixture `SKILL.md` holds
    `${CLAUDE_PLUGIN_ROOT}/skills/kit/ref.md`, a bare `${CLAUDE_PLUGIN_ROOT}`,
    `${CLAUDE_SKILL_DIR}` and `kit:other`. It reads `skill://lib/kit/ref.md`, `skill://lib`,
    `skill://lib/kit` and `skill://lib/other/SKILL.md`. A `notes.md` beside it holding the same
    four strings reads as written.
  - `test_two_scopes_with_one_key_read_the_same_bytes`:
    - `?library=lib` and `?tag=<a tag only lib's plugins carry>` read the same text for one
      `SKILL.md` that cites `kit:other`;
    - their `skills/get` digests are equal;
    - `serving.view().key` is equal under both.
  - `test_an_out_of_scope_skill_reads_as_absent`: under `?library=other`, a read of `lib`'s
    `SKILL.md` fails with the same code and message shape as a read of
    `skill://lib/nope/SKILL.md`.
  - `test_the_prefix_is_written_after_kb`: with `X-MCP-Resource-Prefix: kb+`, the `SKILL.md`
    read holds `kb+skill://lib/other/SKILL.md` and no bare `skill://`. `skill://lib/_index.md`
    is prefixed too.
  - `test_a_refused_stage_is_a_conflict`. `monkeypatch` `PluginSet.add` to raise
    `PluginError("x is already served by plugin y")` for one stage. Then:
    - `/health` `libraries[lib]["conflicts"][pid] == "conflict: x is already served by plugin
      y"`;
    - every other stage's skills read;
    - an error is logged.
  - `test_a_skill_fastmcp_refuses_is_named_nowhere`: a skill with frontmatter `description: ""`
    doesn't read. It isn't in `_index.md`, `skills/list` or a hint, and a qualified name citing
    it is served as written.
  - `test_a_refresh_serves_the_new_set`:
    - on a `file://` source, edit one skill's text, delete another, then `kb.refresh(force=True)`;
    - the edit reads;
    - the deleted skill's read fails and its index line is gone;
    - the deleted skill's stage dir no longer exists.
  - `test_a_skill_arriving_after_boot_reads`: boot over a plugin with no skills, add one,
    refresh. Its `SKILL.md`, `_manifest` and `<skill>/_index.md` read.
  - `test_digests_describe_the_bytes_read`: for a CRLF skill, the `skills/get` digest is the
    SHA-256 of the UTF-8 bytes `resources/read` returns.
  - `test_manifest_names_the_skill_by_its_name` (N1): `json.loads(read("…/loki/_manifest"))["skill"]
    == "loki"`.
  - `test_a_json_file_in_a_skill_reads_as_a_blob` (N2): `data.json` comes back as a blob with
    `mimeType == "application/json"`.
  - In `tests/test_skills_extension.py`, keep every assertion on what a client sees. Drop the
    ones on `SkillCatalogue.refused()`, `skills()` and memo internals, and replace them with the
    `publish` result's `catalogue` (the refused skill is absent) and the log line.
- [ ] **Step 2: Run** `pytest tests/test_plugin_serving.py -v`. Expected: FAIL on the import of
  `kubed.mcp_kb.mcp.skills`.
- [ ] **Step 3: Implement.**
  - **`publish`:**
    - `stage_catalogue(snapshot.catalogue, kb.cache / "stage", self.check)`, then
      `mcp.plugin_set()`;
    - `add(stage.address, namespace=stage.namespace)` in order, catching `PluginError` and
      `ValueError` into conflicts;
    - `mcp.serve(set)`, then `prune` to the added stages' roots;
    - rebuild the stage table, `{added Plugin.address: Stage}`, and assert that kubed-mcp kept
      the address string it was given;
    - return `replace(snapshot, catalogue=snapshot.catalogue.without(sorted(refused)),
      status=<conflicts merged into status["libraries"]>, stages=<added>)`.
  - **`view`:** `requested_scope()`, then the frozenset of `(s.library, s.plugin)` over the
    table's stages where `scope.admits(s.library, s.category, s.labels,
    library_categories=s.library_categories)`. Return `View(EMPTY, _none)` when nothing is
    admitted, else `View(key, lambda p: _pair(p) in key)`.
  - **`rewrite`:** when `site.kind == "skill"` and `site.uri.endswith("/SKILL.md")`, with the
    address `site.uri[len("skill://"):-len("/SKILL.md")]` a key of the snapshot's index, return
    `knowledge_base.snapshot.catalogue.instructions(address, text, requested_scope())`.
    Otherwise return `text`.
  - **`check`:** `Skill.from_files(files)`, turning a `ValueError` into K1's `_reason` text.
  - **`create_app`:** call `SkillServing(mcp, kb).attach()` where `mcp.add_provider(skills)` was.
    `Catalogue`'s transient and every other getter becomes `lambda:
    knowledge_base.snapshot.catalogue`.
  - **`conftest.served`:** a skill's file is `catalogue.skill_files(skill)[file]`, `SKILL.md`
    through `catalogue.instructions`. Everything else is `catalogue.read`.
  - Delete `mcp/skill_catalogue.py`.
- [ ] **Step 4: Run** `ruff check .` and all of `pytest`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: serve skills through kubed-mcp's plugin set, view and rewriter`.

### Task 4: A refused or empty scope builds nothing (ruling 8)

**Files:**
- Modify: `kubed/mcp_kb/mcp/pins.py`: `what_is_wrong` and `_serving` lose the `catalogue`
  parameter.
- Modify: `kubed/mcp_kb/app.py` (the two `what_is_wrong` lambdas)
- Test: `tests/test_scope_builds.py` (new)

**Interfaces:**
- Consumes: `SkillServing.view` and `EMPTY` (Task 3).
- Produces: `what_is_wrong(scope: Scope, config: Config, snapshot: Snapshot) -> str | None`.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_refused_scope_builds_nothing`: wrap the view so each returned `View`'s `admits`
    counts its calls. Fifty requests with distinct unknown `Kb-Tag` values each fail with
    `-32602`, and the count stays 0.
  - `test_scopes_admitting_nothing_share_one_key`: two scopes naming a declared library whose
    only plugin is down both give `serving.view().key == EMPTY`. A `skills/list` under each
    calls `admits` at most once, across both.
  - `test_what_is_wrong_reads_the_snapshot`:
    `inspect.signature(what_is_wrong).parameters.keys() == {"scope", "config", "snapshot"}`.
- [ ] **Step 2: Run** `pytest tests/test_scope_builds.py -v`. Expected: FAIL on the signature.
- [ ] **Step 3: Implement.** `_serving` reads `snapshot.catalogue`, which `publish` has already
  narrowed. Drop the parameter and its callers.
- [ ] **Step 4: Run** `ruff check .` and `pytest tests/test_scope_builds.py
  tests/test_scope_and_prompt_tools.py tests/test_header_scope.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `fix: a refused or empty scope builds no skills`.

### Task 5: A live skill's edit is re-staged and served

**Files:**
- Modify: `kubed/mcp_kb/mcp/skills.py`: `view` runs the live check, plus a new `_restage_live`.
- Test: `tests/test_live.py` (the tests that built a `SkillCatalogue` move to a served app)

**Interfaces:**
- Consumes: `restage`, `Stage.stamp` and `Catalogue.live_stamp(skill)` (Task 2);
  `PluginSet.keep`; `Snapshot.stages` (Task 3).
- Produces: `SkillServing._restage_live(scope: Scope) -> None`. It is called first thing in
  `view()`, and runs under `self._lock` taken with `acquire(blocking=False)`.

- [ ] **Step 1: Write the failing tests.** They use the WebDAV fixture with `cache: live`.
  wsgidav's ETag is `inode-mtime-size`, so each edit changes the file's length.
  - `test_a_live_edit_reads_on_the_next_request_after_trust`: edit a live skill's `SKILL.md` on
    the share and wait past the 2 s trust. The next `resources/read` returns the new text, and
    `_manifest`'s hash and `skills/get`'s digest describe it.
  - `test_a_restage_keeps_every_other_plugin`: after that edit, every non-live `Plugin` in
    `mcp.plugins` is the same object as before (`is`), and `mcp.generation` moved by one.
  - `test_no_restage_while_a_refresh_publishes`: with `serving._lock` held, `view()` returns
    without serving. `mcp.generation` doesn't move.
  - `test_an_out_of_scope_live_skill_is_not_revalidated`: under `?library=other`, the share sees
    no request for the live skill's files. Count them through wsgidav's request log.
- [ ] **Step 2: Run** `pytest tests/test_live.py -v`. Expected: FAIL, because the edit isn't
  served.
- [ ] **Step 3: Implement.**
  - For each staged live stage the scope admits, compare `catalogue.live_stamp(skill)` over its
    skills with `stage.stamp`.
  - For those that moved, `restage`. Build a new set: `keep` each served `Plugin` whose stage
    didn't move, `add` the re-staged ones. Then `serve`, update the table and
    `knowledge_base.snapshot.stages` (a `replace` under kb's lock), and `prune`.
  - **Stop and report** if kubed-mcp pins its state before calling the view function. The test
    then shows the edit one request late. That is a quick-mcp ask, not something to work around
    here.
- [ ] **Step 4: Run** `ruff check .` and `pytest tests/test_live.py tests/test_webdav_source.py
  -v`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: a live skill's edit is re-staged and served`.

### Task 6: The spec, AGENTS.md, the wiki and the changelog

**Files:**
- Modify: `docs/superpowers/specs/skills.md`, `config-and-sources.md`,
  `plugins-and-libraries.md` and `scoping-and-instructions.md`
- Modify: `AGENTS.md` (Layout; "A skill's files are FastMCP's to serve"; the "Where code goes"
  bullets that cite `skill_catalogue`); `CONTRIBUTING.md` ("Where things live")
- Modify: `wiki/Skills.md` wherever it shows `_manifest`'s `skill` value or the prefix header
  (the wiki branch is named after this PR's branch, never `master`)
- Modify: `CHANGELOG.md` `[Unreleased]`
- Modify: `docs/superpowers/plans/2026-11-24-k3-skills-through-add-plugin-design.md` (its
  History line: shipped in #89)
- Test: `tests/test_wiki.py`, `tests/test_readme.py`

- [ ] **Step 1: Edit the spec.** Keep the IDs, add the new ones at the end of their sections,
  and reuse none.
  - **SKL-23:** the media-type rule for library files and fallbacks stays as it is. Add: "A
    skill's own file has the type FastMCP guesses from its name (`text/markdown` for `.md`,
    `application/octet-stream` when none), and reads as text when that type is `text/*`, as a
    blob otherwise."
  - **SKL-24:** `{"skill": "<the skill's name>", …}`, with the example `"skill": "loki"`.
  - **SKL-37:** a moved live file re-stages its skill's plugin and serves a new plugin set
    before the request reads it.
  - **SKL-40 and SKL-42:** the prefix on a skill's own files comes from `X-MCP-Resource-Prefix`
    or `?prefix=`. `Kb-Resource-Prefix` is still read for everything else.
  - **SKL-45:** replace the per-scope sentence with "A skill that fails only under one scope and
    prefix is left out of that build, and is still named by the indexes, listing and hints
    under it."
  - **SKL-58:** "A skill's files, `_manifest`, entry and inside-skill indexes are served by
    kubed-mcp's plugin layer. The library's own provider answers only what it misses."
  - **New SKL-59:** D1's staging rule, as statements: one plugin per library, plugin and folder;
    the namespace; what a tree holds.
  - **New SKL-60:** a staged tree is named by a digest of what it holds, reused while that is
    unchanged, and deleted once no served plugin reads it.
  - **New SKL-61:** kb's one rewriter applies SKL-55, then SKL-25 and SKL-52, to a skill's
    `SKILL.md` when a build is made. The prefix is written after it.
  - **SRC-53:** kb's `file` loader replaces kubed-mcp's `LocalLoader`, and no other loader is
    registered with kubed-mcp.
  - **LIB-29:** add "A staged plugin kubed-mcp refuses is reported the same way, with its
    reason."
  - **New SCP-36:** one build per set of `(library, plugin)` pairs a scope admits; every scope
    that admits nothing shares one; a refused scope builds nothing.
- [ ] **Step 2: Edit AGENTS.md and CONTRIBUTING.md.**
  - In the Layout, `mcp/skills.py` and `catalogue/stage.py` replace `skill_catalogue.py`.
  - The skills section describes stages, the view and the rewriter, and keeps the three rules
    (rewrite at build, the kb provider never answers a skill's file, a refused skill named
    nowhere).
  - Add one "cost an afternoon" bullet: kubed-mcp's default `skills/` scan can't be turned off,
    which is why kb stages trees rather than handing kubed-mcp a plugin root.
- [ ] **Step 3: Write the changelog.** Two lines under `Changed`:
  - "A skill's `_manifest` names the skill by its name."
  - "Skill files take their gateway prefix from `X-MCP-Resource-Prefix` or `?prefix=`."
- [ ] **Step 4: Run** `python scripts/generate_wiki.py --check`, `ruff check .`, then all of
  `pytest`. Expected: PASS.
- [ ] **Step 5: Commit** `docs: spec, AGENTS.md and the wiki for skills through kubed-mcp`.

After merge into `issue-80`, QA runs the ten-scope live dump with and without `kb+`, after the
gateway sends `X-MCP-Resource-Prefix`. It should differ from the before-dump only by N1–N3.
