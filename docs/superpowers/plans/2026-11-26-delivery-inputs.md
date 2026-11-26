# Delivery Inputs Implementation Plan

> **History.** Proposed for #86 (PR #105, into `issue-80`). It follows K3 (#79, PR #89), the
> gateway prefix (#81, PR #93), the `_publish` race fix (#94, PR #96), K4 (#82, PR #97), K5 (#83,
> PR #100), the kubed-mcp 0.3.0 pin (#92, PR #99), K6 (#84, PR #102) and #85 (PR #104). The spec is
> #86's notes in `.issue/issues.md`, with Dr K's rulings of 2026-11-24 05:58 (rulings 1 to 5) and
> the parent's messages up to 2026-11-26 02:25, which approved it. The design is below, and there is
> no separate design file. The branch had no draft spec.
>
> **Two points are settled here differently from the notes, because kubed-mcp 0.3.0 does it
> differently** (read in its source at `v0.3.0`):
> - **D5, the footer.** 0.3.0 has no public reader of a request's resolution. `delivery._resolved()`
>   is private, and the handshake echo is written by `_Describe`, which sits outside every
>   middleware kb adds. The one public way in is `QuickMCP.instructions(fn)` (DLV-11): `fn` is
>   called with the `Resolved` itself. So ruling 3 is built by moving `ScopedInstructions` onto that
>   hook. That is the hook half of #87; #87 keeps Via, the `local` mode and N17.
> - **D6, the pin.** Ruling 1's "asks the view" is built as "does the view admit any plugin". That
>   differs from today in one corner, named as L6.

> **For agentic workers:** REQUIRED SUB-SKILL: Use skill://superpowers/subagent-driven-development/SKILL.md (recommended) or skill://superpowers/executing-plans/SKILL.md to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** kb's delivery inputs become kubed-mcp's. `resources/list` is one `SKILL.md` row per skill
in scope (DLV-8), chosen by `X-MCP-Listed`/`Kb-Listed`. `Kb-Listing` and the prompt mirror tools
go. The tools-mode footer follows kubed-mcp's resolved `resources`.

**Architecture:** Mostly deletion. kb's `CatalogueProvider` stops listing index rows and lists only
`_files.md`. kubed-mcp's plugin layer lists the `SKILL.md` rows once kb stops forcing `listed`
to none. `mcp/prompts.py` loses the mirror, and `HideMirrorTools` goes. `RefuseEmptyScope`'s
`_serving` asks `SkillServing` whether its view admits any plugin. `ScopedInstructions` becomes the
`fn` that `mcp.instructions` calls with the request's `Resolved`.

**Tech Stack:** Python ≥3.11, `kubed-mcp>=0.3.0,<0.4` (FastMCP through it), pytest +
pytest-asyncio, uvicorn.

**Spec:** this plan's design section and #86's notes in `.issue/issues.md`. The living spec rows
are [skills.md](../specs/skills.md) (SKL-14 to SKL-16),
[scoping-and-instructions.md](../specs/scoping-and-instructions.md) (SCP-2, SCP-3, SCP-21,
SCP-24, SCP-31, INS-2, INS-3, INS-15, INS-16), [http-and-tools.md](../specs/http-and-tools.md)
(TOOL-1 to TOOL-20) and [prompts.md](../specs/prompts.md) (PRM-3, PRM-57). kubed-mcp's rows are
cited from its wiki at `v0.3.0`: DLV-2, DLV-6 to DLV-9, DLV-11, DLV-15 and DLV-16.

## Design

### What is on the branch now, read in the code

- `config.py::Config.delivery` returns `Delivery(listed=())`. That forces kubed-mcp's `Listed` to
  none at the config level, so the plugin layer lists no `SKILL.md` row. Its docstring says it is
  there "until #86 replaces `Kb-Listing`".
- `catalogue/uris.py::Catalogue.entries(scope, full=False)` lists, per library, the library index,
  one index per top-level folder and `_files.md`, and every skill when `full`. It is memoised per
  `(scope, full)`, except an empty scoped result. `mcp/resources.py::CatalogueProvider` lists it
  with `full=full_listing()`.
- `mcp/request.py` reads kb's own `Kb-Listing` (`full_listing`), `Kb-Prompts`/`X-MCP-Prompts`
  (`client_uses_prompts`) and a duplicate of kubed-mcp's `Kb-Resources` (`client_reads_resources`,
  through `_declared_on`). `ScopedInstructions` uses the last one for the footer, and
  `declared_on_initialize`/`declared_on_discover` for the Skills extension.
- `mcp/prompts.py` holds `ReadOnlyPromptsAsTools`, `_annotate`, `PROMPT_TOOLS`, `register()` and
  `_mirrored`. `mcp/tools.py` holds `READ_ONLY`, used only by `_annotate`, and `RESOURCE_TOOLS`, for
  the wiki. `app.py` adds `HideMirrorTools` for the prompt pair.
- `mcp/pins.py::_serving` is true when `catalogue.entries(scope)` has a row, or a prompt or an
  agent is visible. Once the index rows go, `entries` holds only `_files.md`, so this has to change
  in the same commit as the listing.
- `scripts/generate_wiki.py` reads `request.RESOURCES_*`, `request.PROMPTS_*` and `PROMPT_TOOLS`.
  `tests/test_wiki.py::test_installing_documents_every_url_parameter_and_header` reads
  `request.PROMPTS_*`, `RESOURCES_*` and `LISTING_*`.

### Checked against kubed-mcp 0.3.0 (its source at `v0.3.0`)

- **Listed** (`delivery.py`). It is parsed from `Kb-Listed`, `X-MCP-Listed` and `?listed=`
  (`header_prefix` first, DLV-16). The kinds are `skills`, `prompts` and `agents`. `none` or a
  blank value gives the empty set, and unknown names are dropped. When a config gives no `listed`
  (no `delivery`, or `listed` None), the level is passed over and Via's preset answers: `mcp` gives
  `{"skills"}`, and `extension` and `local` give the empty set (DLV-9).
- **The tools** (`_tools.py`). Both carry `title` ("List resources", "Read a resource"),
  `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true` and `openWorldHint: false`.
  So TOOL-6 needs no named change. `list_resources` makes one `list_resources()` call through the
  server's middleware, unpaged, with no templates, each `uri` prefixed. The pair is listed only when
  the resolved `resources` is `off`, and callable always. A read miss is a `ToolError` with
  `Resource not found: '<uri>'`, an `MCPError` keeps its message, and a blob follows DLV-6.
- **The handshake** (`_handshake.py`, `app.py`). `_Describe` is added in `QuickMCP.__init__`,
  before any middleware kb adds, so it is outside them. It calls `fn(resolved)` on `initialize` and
  `server/discover`. A raise, None or a non-string keeps the built instructions, and anything else
  is written as `prefixed(text, resolved.prefix)`. `Resolved` carries `resources`, `listed`, `via`,
  `prefix` and `extensions` (the client's declared ids, or None).
- **No public reader of the resolution.** `kubed.mcp.request` exports `request_values`,
  `get_context` and `get_http_request` only. `delivery.__all__` is `BinaryPointer`, `Delivery`,
  `DeliveryDefault`, `Instructions` and `Resolved`.

What was not read: how the plugin layer filters its own rows by `listed`, and the fields of a
`SKILL.md` row. Task 0 pins both.

### Decisions

- **D1. The listing is kubed-mcp's, plus `_files.md`.** Delete `Config.delivery`, `Delivery` and
  `DELIVERY`. kubed-mcp reads `getattr(config, "delivery", None)`, so Via's preset answers and the
  default lists `SKILL.md` rows. Leaving `listed` unset is what lets #87's Via presets work. A
  config-level `listed` would beat them. `Catalogue.entries(scope)` lists one `_files.md` row per
  library with a library file in scope. It takes no `full`, is memoised per scope, and an empty
  scoped result is still not memoised. kb lists no `SKILL.md` row of its own, so none is listed
  twice. `_files.md` is kb's own resource, so kubed-mcp's `listed` filter never removes it (ruling
  2): it is listed under `Listed: none` too, and under #87's `local`.
- **D2. Nothing kb reads replaces `Kb-Listing`.** `full_listing`, `LISTING_*` and `_FULL` go, with
  no alias (the epic's no-shims rule). A request that still sends `Kb-Listing: full` gets the
  default listing, which now holds every skill anyway.
- **D3. The prompt mirror goes whole.** Delete `ReadOnlyPromptsAsTools`, `_annotate`,
  `PROMPT_TOOLS`, `register()`, `_mirrored`, `READ_ONLY`, `HideMirrorTools`, `PROMPTS_*` and
  `client_uses_prompts`. `MCPFilePrompt._ask` opens with `if not _can_ask(): return None`. A
  tools-only client reaches a prompt's file with `Kb-Listed: prompts` and `read_resource` on
  `prompts://` (#85).
- **D4. The wiki keeps its own list of delivery names.** `mcp/tools.py` keeps `RESOURCE_TOOLS` and
  gains the names kubed-mcp's inputs are read under with kb's `Kb` prefix, for the generator and
  `tests/test_wiki.py` only, never to read a request: `RESOURCES_PARAM = "resources"`,
  `RESOURCES_HEADER = "kb-resources"`, `LISTED_PARAM = "listed"` and `LISTED_HEADER = "kb-listed"`.
- **D5. The instructions are kubed-mcp's `fn`.** `ScopedInstructions(snapshot)` stops being a
  middleware and becomes a callable, `__call__(self, delivery: Resolved) -> str`. It reads
  `snapshot = self._snapshot()` and `scope = requested_scope()` once each, and builds with
  `resources=delivery.resources == "on"` and
  `skills_extension=EXTENSION_ID in (delivery.extensions or ())`. It returns the text unprefixed,
  because `_Describe` writes `resolved.prefix` over it. `create_app` calls
  `mcp.instructions(ScopedInstructions(serving.served_snapshot))`. `client_reads_resources`,
  `_declared_on`, `RESOURCES_*`, `_OFF`, `declared_on_initialize` and `declared_on_discover` go.
  `RefuseEmptyScope` raises inside `_Describe`'s `call_next`, so a refused scope never reaches `fn`
  (INS-5). `Resolved` is imported from `kubed.mcp.delivery` under `TYPE_CHECKING`, and AGENTS.md's
  facade list names that module.
- **D6. The pin asks the view.** `SkillServing.admits(scope: Scope) -> bool` is true when any row
  of `self._reading()[0].table` is `admitted(scope)`. It does not re-read live plugins, pin or build.
  `what_is_wrong(scope, config, snapshot, admits)` takes it as `admits: Callable[[Scope], bool]`.
  `_serving(snapshot, scope, admits)` is `admits(scope) or bool(snapshot.catalogue.entries(scope))`.
  The second term covers a library of files alone. Every prompt and agent comes from an added
  plugin, so `visible_prompts` and `visible_agents` leave `_serving`. The messages are unchanged.
- **D7. Spec rows keep their IDs.** Removed rows leave gaps (specs/README). TOOL-9, TOOL-14 to
  TOOL-20 and PRM-3 are deleted. SKL-16 is deleted and SKL-14 rewritten. TOOL-1 to TOOL-13 are
  reworded to the resource pair alone, and each says which DLV row it restates.

### Named changes, for QA's dump

- **L1. The listing.** With no `Listed` setting, `resources/list` and `list_resources` give one
  `SKILL.md` row per skill in scope, in the plugin layer's shape, then each library's `_files.md`.
  No `_index.md` row is listed, and every index still reads. `Kb-Listed`/`X-MCP-Listed`/`?listed=`
  `prompts` or `agents` lists those files instead, and `none` lists `_files.md` alone. The listing
  grows from about a dozen rows (1.9 KB) to one row per skill.
- **L2. No longer read:** `Kb-Listing`, `X-Skill-Listing`, `?listing=` and `?skills=`.
- **L3. The prompt mirror is gone:** `list_prompts`, `get_prompt`, `Kb-Prompts`, `X-MCP-Prompts`
  and `?prompts=`. A client sending `?prompts=off` lists no tool.
- **L4. TOOL-14 goes.** What a missed `read_resource` logs is kubed-mcp's.
- **L5. The tools footer follows kubed-mcp.** Any client kubed-mcp resolves `resources: off` for
  gets `Read these with read_resource.`, VS Code with no header included (DLV-15). It matches the
  tools it is listed (#99).
- **L6. A scope whose view admits a plugin is not refused under SCP-31 row 9,** even when that
  plugin serves the scope nothing (every skill dropped by the parity guard, no prompt, no agent).
  Before, that scope was refused.

Not named: `Kb-Resources` keeps working, because kubed-mcp reads it. kb's duplicate read goes
unseen. The resource tools' text is kubed-mcp's (K3 N4). VS Code's default listing of the pair is
#99's. TOOL-6 holds on 0.3.0.

## Global Constraints

- Pin `kubed-mcp>=0.3.0,<0.4`, as `issue-80` has. kb imports `kubed.mcp*` only, never `fastmcp`,
  `mcp` or `mcp_types`, outside tests. `catalogue/` and `plugins/` import no FastMCP
  (`tests/test_boundaries.py`).
- No compatibility shims: a removed header, parameter or tool has no alias.
- kb never imports a private kubed-mcp name (`_resolved`, `_RESOLVED`). A missing public name is a
  quick-mcp row, raised with Dr K.
- Spec IDs are stable. A removed row leaves a gap, and no number is reused. The spec files hold
  statements only: no dates, issue numbers or "used to".
- Footer copy is exact. Resources: `Read a listed skill at skill://<library>/<path>/SKILL.md; read
  its _manifest in place of SKILL.md for the other files it ships.` Tools: `Read these with
  read_resource.`
- Changelog: one short line per entry, under `[Unreleased]` only, in Added / Changed / Fixed /
  Removed order. Add a `### Removed` section after `### Fixed`. **BREAKING:** marks the removals.
- The wiki change goes on the wiki's `issue-86` branch, never `master`. Generated pages come from
  `python scripts/generate_wiki.py` only. Commits are signed (`git commit -S`).
- Markers: in-process tests are `@pytest.mark.unit`, uvicorn ones `@pytest.mark.integration`.
- Every task passes, from the repository root and with the `wiki/` submodule checked out:
  `ruff check . && pytest && python scripts/generate_wiki.py --check`. Task 3 also runs
  `python -m build && twine check --strict dist/*`.
- Do not weaken an assertion to make it pass. A failing test the Design does not explain is a
  finding: stop and report it with the output.

## Review Focus

1. **A tools-only client (n8n: `?resources=off`, no `Listed`).** `list_resources` returns every
   in-scope `SKILL.md` row plus `_files.md`, each row reads through `read_resource`, and both hold
   with and without `Kb-Resource-Prefix: kb+`. Task 1, `test_a_tools_client_reads_every_listed_row`.
2. **`Kb-Listed: none` and `Kb-Listed: prompts`.** `none` lists `_files.md` alone. `prompts`
   lists prompt files that read, and still lists `_files.md`. Task 1,
   `test_listed_chooses_the_plugin_rows_and_never_files_md`.
3. **A client still sending the old inputs** (`kb-agents` sends `?prompts=off` until QA). It lists
   no tool, its prompts still work over `prompts/get`, and `Kb-Listing: full` lists what the
   default does. Tasks 1 and 2, `test_kb_listing_does_nothing` and
   `test_the_prompt_inputs_do_nothing`.
4. **VS Code with no header.** The footer is the tools footer, and the pair is listed, in both
   eras. Task 3, `test_the_footer_follows_what_kubed_mcp_resolved`.
5. **A scope pinned to a library that serves only library files** (a plugin with `skills: []` and
   `files:`). It is not refused, lists `_files.md`, and lists no `SKILL.md`. Task 1,
   `test_a_files_only_library_is_served_its_files_md`.

---

### Task 0: What kubed-mcp 0.3.0 lists, and what `fn` is handed

These are the go/no-go facts, against kubed-mcp alone with no kb code, like
`tests/test_command_layer.py`. They describe 0.3.0 and are expected to pass at once. A failure is a
finding, not a bug to fix:
- **No `SKILL.md` row when no config is given:** Task 1 keeps `Config.delivery` with
  `listed=("skills",)` instead of deleting it. Record that in this plan's History and tell Dr K in
  the PR that #87's Via presets are then overridden.
- **`extensions` missing the declared id in one era:** stop before Task 3 and report to Dr K.
  kb does not read `_resolved`.

**Files:**
- Create: `tests/test_delivery_layer.py`

**Interfaces:**
- Consumes: `QuickMCP(name, config=)`, `plugin_set()`, `PluginSet.add(folder, namespace=,
  manifest=)`, `serve`, `mcp.instructions(fn)`, `mcp.get_tool`, `mcp.server.list_resources`,
  `fastmcp.Client(mcp.server, mode=, client_info=, extensions=)`, and `VS_CODE`
  (`tests.test_server`).
- Produces: the observed row shape, written in the docstring of
  `test_the_default_lists_a_skill_md_row_per_skill`. Task 1's SKL-14 is written from it.

- [ ] **Step 1: Write the tests** (all `@pytest.mark.unit`)

```python
# _served(tmp_path, delivery=None): QuickMCP("mcp-kb", config=SimpleNamespace(delivery=delivery))
# over one plugin at "lib" with skills/a, skills/b, commands/top.md and agents/helper.md;
# plus a server-own resource: mcp.server.resource("kb://own")(lambda: "x")
def _delivery(listed): return SimpleNamespace(resources=None, listed=listed, via=None)

async def test_the_default_lists_a_skill_md_row_per_skill(tmp_path):
    uris = await _uris(_served(tmp_path))          # config without `delivery`
    assert {"skill://lib/a/SKILL.md", "skill://lib/b/SKILL.md", "kb://own"} <= set(uris)
    assert not [u for u in uris if u.endswith(("_index.md", "_index.json", "_manifest"))]
    assert not [u for u in uris if u.startswith(("prompts://", "agents://"))]
    # docstring: the observed name, description, mimeType of one SKILL.md row

@pytest.mark.parametrize(("listed", "scheme"), [
    (frozenset({"prompts"}), "prompts://"), (frozenset({"agents"}), "agents://"),
    (frozenset(), None)])
async def test_listed_chooses_the_plugin_rows(tmp_path, listed, scheme):
    uris = await _uris(_served(tmp_path, _delivery(listed)))
    assert "kb://own" in uris                       # server-own: always listed
    assert not [u for u in uris if u.startswith("skill://")]
    plugin = [u for u in uris if u != "kb://own"]
    assert all(u.startswith(scheme) for u in plugin) and bool(plugin) == bool(scheme)

async def test_the_resource_pair_is_annotated_as_tool_6_says(tmp_path):
    for name, title in (("list_resources", "List resources"), ("read_resource", "Read a resource")):
        hints = (await _served(tmp_path).get_tool(name)).annotations
        assert (hints.title, hints.readOnlyHint, hints.destructiveHint,
                hints.idempotentHint, hints.openWorldHint) == (title, True, False, True, False)

async def test_list_resources_is_not_paged(tmp_path):
    # 120 skills at "lib": resources/list (client.session.list_resources()) has nextCursor None,
    # and call_tool("list_resources") returns 120 SKILL.md rows

@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_fn_is_handed_the_resolution(tmp_path, mode):
    # mcp.instructions(lambda delivery: seen.append(delivery) or "T")
    # plain client:   seen[-1].resources == "on", not (seen[-1].extensions or ())
    # VS_CODE:        seen[-1].resources == "off"
    # extensions=[SkillsClientExtension()]: "io.modelcontextprotocol/skills" in seen[-1].extensions
    # each: the handshake's instructions == "T"
```

- [ ] **Step 2: Run them**

Run: `pytest tests/test_delivery_layer.py -v`
Expected: PASS. On a failure, stop and act as this task's opening says.

- [ ] **Step 3: Commit**

```bash
git add tests/test_delivery_layer.py
git commit -S -m "test: what kubed-mcp 0.3.0 lists by Listed, and what instructions fn is handed (#86)"
```

### Task 1: One `SKILL.md` row per skill (L1, L2, L6)

**Files:**
- Modify: `kubed/mcp_kb/config.py` (delete `Config.delivery`, `Delivery`, `DELIVERY`)
- Modify: `kubed/mcp_kb/catalogue/uris.py` (`Catalogue.entries`, `_entries`, `_memo`, `Entry`'s
  docstring)
- Modify: `kubed/mcp_kb/mcp/resources.py` (`CatalogueProvider._list_resources`, module docstring)
- Modify: `kubed/mcp_kb/mcp/request.py` (delete `LISTING_*`, `_FULL`, `full_listing`)
- Modify: `kubed/mcp_kb/mcp/skills.py` (`SkillServing.admits`)
- Modify: `kubed/mcp_kb/mcp/pins.py` (`what_is_wrong`, `_serving`), `kubed/mcp_kb/app.py`
  (`RefuseEmptyScope`'s lambda)
- Modify: `kubed/mcp_kb/mcp/tools.py` (`LISTED_PARAM`, `LISTED_HEADER`, D4), `tests/test_wiki.py`
- Modify: specs `skills.md` (SKL-14, SKL-15, SKL-16), `scoping-and-instructions.md` (SCP-2's
  Listing row, SCP-3, SCP-31 rows 8 and 9 and the note under the table),
  `http-and-tools.md` (TOOL-9); `AGENTS.md`; `README.md`; `CHANGELOG.md`; wiki `Skills.md`,
  `Installing.md`, `Scoping.md`, `Home.md`
- Test: `tests/test_listing.py` (create); then every test that asserts the old listing:
  `test_uris.py`, `test_server.py`, `test_address_space.py`, `test_header_scope.py`,
  `test_kb_headers.py`, `test_plugin_serving.py`, `test_skills_extension.py`,
  `test_addressing_http.py`, `test_assembly.py`, `test_scope.py`, and any other the run shows

**Interfaces:**
- Consumes: Task 0's row shape. `tests.conftest`: `serve_http`, `http_client`, `make_config`,
  `server_of`, `serving_of`.
- Produces:
  - `Catalogue.entries(self, scope: Scope = EVERYTHING) -> list[Entry]`: only `_files.md` rows.
  - `SkillServing.admits(self, scope: Scope) -> bool`.
  - `what_is_wrong(scope: Scope, config: Config, snapshot: Snapshot, admits: Callable[[Scope], bool]) -> str | None`.
  - `tools.LISTED_PARAM = "listed"` and `tools.LISTED_HEADER = "kb-listed"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_listing.py`, over `serve_http` with the
  `skills_dir` tree (`make_config`) unless a test says otherwise

```python
@pytest.mark.unit
def test_entries_are_files_md_alone(catalogue):        # test_uris's fixture shape
    assert [e.uri for e in catalogue.entries()] == ["skill://<lib>/_files.md", ...]
    assert catalogue.entries(Scope.parse(library="nope")) == []

@pytest.mark.integration
async def test_the_default_listing_is_a_skill_md_row_per_skill(server_url):
    uris = await resource_uris(server_url)
    skills = {uri_for(s) for s in kb.snapshot.catalogue.visible_skills()}
    assert {u for u in uris if u.endswith("/SKILL.md")} == skills
    assert not [u for u in uris if u.endswith("_index.md")]
    assert len(uris) == len(set(uris))                 # no row twice
    for lib in libraries_with_files: assert f"skill://{lib}/_files.md" in uris

@pytest.mark.integration
@pytest.mark.parametrize("prefix", [None, "kb+"])
async def test_a_tools_client_reads_every_listed_row(server_url, prefix):
    # ?resources=off (+ Kb-Resource-Prefix): every row of call_tool("list_resources")
    # reads through call_tool("read_resource", {"uri": row["uri"]}) without isError,
    # and every uri starts with (prefix or "") + "skill://"

@pytest.mark.integration
@pytest.mark.parametrize("sent", [{"Kb-Listed": "none"}, {"X-MCP-Listed": "none"}, "?listed=none"])
async def test_listed_chooses_the_plugin_rows_and_never_files_md(server_url, sent):
    # none: uris == the _files.md rows alone
    # and with "prompts" in place of "none": every row is _files.md or prompts://…, and each
    # prompts:// row reads

@pytest.mark.integration
async def test_kb_listing_does_nothing(server_url):
    for sent in ({"Kb-Listing": "full"}, {"X-Skill-Listing": "full"}, "?listing=full", "?skills=full"):
        assert await resource_uris(server_url, sent) == await resource_uris(server_url)

@pytest.mark.integration
async def test_a_files_only_library_is_served_its_files_md(tmp_path):
    # library "docs": one plugin, skills: [], files: ["guides/*.md"]; ?library=docs
    # not refused; uris == ["skill://docs/_files.md"]

@pytest.mark.unit
def test_the_pin_asks_the_view(tmp_path):
    # a plugin tagged "t" whose only skill holds assets/.gitkeep (dropped, N13), no prompt or agent
    # what_is_wrong(Scope.parse(tags="t"), config, kb.snapshot, serving.admits) is None    (L6)
    # what_is_wrong(Scope.parse(tags="t,u"), ...) is the row-9 message, unchanged
```

`resource_uris(url, sent=None)` is a helper in the file: a headers dict or a query string.

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_listing.py -v`
Expected: FAIL. The listing still has index rows and no `SKILL.md` row, `entries` still lists index
rows, and `what_is_wrong` takes three arguments.

- [ ] **Step 3: Implement**

- `config.py`: delete `Config.delivery`, `Delivery` and `DELIVERY`. If Task 0 recorded the
  fallback, keep it, set `listed=("skills",)`, and reword its docstring.
- `uris.py`: `entries(scope)` and `_entries(scope)` build only the `_files.md` row per library, as
  today (its name, description, `text/markdown`, tags `(library, "index")`). `_memo` becomes
  `dict[Scope, list[Entry]]`. Keep the empty-scoped and `MEMO_LIMIT` rules. Drop `_count`,
  `_children` and `_under` if nothing else uses them (check `directory` and `index` first).
- `resources.py`: `self._catalogue().entries(requested_scope())`. In the module docstring, the
  listing is the plugin layer's `SKILL.md` rows plus kb's `_files.md`.
- `request.py`: delete `LISTING_*`, `_FULL` and `full_listing`.
- `skills.py`: `admits` as D6. Its docstring says it reads `_reading()`, takes no lock and builds
  nothing.
- `pins.py`: `what_is_wrong` gains `admits`. `_serving` follows D6, and its docstring says why
  prompts and agents need no term of their own.
- `app.py`: `what_is_wrong(scope, config, knowledge_base.snapshot, serving.admits)`.
- `tools.py`: D4's two `LISTED_*` names. `tests/test_wiki.py` lists `tools.LISTED_PARAM` and
  `tools.LISTED_HEADER` in place of `request.LISTING_*`.

- [ ] **Step 4: Run the new tests to see them pass**

Run: `pytest tests/test_listing.py tests/test_boundaries.py -v`
Expected: PASS.

- [ ] **Step 5: Bring the rest of the suite to the new listing**

Run: `pytest -x -q`. Each failure that asserts the old listing is rewritten to the new one:
- an index row becomes the `SKILL.md` rows it summarised;
- `?listing=full`, `Kb-Listing: full`, `FULL` and `entries(full=True)` are dropped, because the
  default now lists the same rows (in `test_assembly.py`, use `catalogue.visible_skills()`);
- `test_server.py::test_resources_are_indexes_not_one_per_skill` becomes
  `test_resources_are_a_skill_md_row_per_skill`;
- `test_header_scope.py::test_fastmcp_syncs_skills_from_the_full_listing` becomes
  `…_from_the_listing`, with no query;
- `test_kb_headers.py`'s listing cases move to `test_kb_listing_does_nothing`;
- `test_scope.py` drops its `full_listing` assertions.

Any other failure is a finding (Global Constraints).

- [ ] **Step 6: Spec, docs, changelog**

- **SKL-14:** `resources/list` holds what the plugin layer lists for the request's `Listed`
  setting (`Kb-Listed`, `X-MCP-Listed` or `?listed=`, DLV-8): by default, one `SKILL.md` row per
  served skill in scope, in its shape (Task 0's fields). `prompts` lists prompt files and `agents`
  agent files instead, and `none` lists none. Then, under every setting, one row per library with a
  library file in scope: `skill://<library>/_files.md`, with the description `Files the <library>
  library ships outside any skill, which its skills reference.` No `_index.md` is listed. Each one
  still reads (SKL-17).
- **SKL-15:** the `_files.md` row's `name` is its URI without `skill://`, its `mimeType` is
  `text/markdown`, and its tags are the library's name and `index`.
- **SKL-16:** delete it (a gap).
- **SCP-2:** delete the Listing row. **SCP-3:** delete "The listing,". It adds `Listed` to
  kubed-mcp's inputs, read with the header prefix `Kb` (DLV-16).
- **SCP-31:** row 8 becomes "no library is set and the plugin layer's view admits no plugin, and
  no library file is served". Row 9 becomes "categories or tags are set, and the view admits no
  plugin for the scope and no library file is in it". The note "Rows 8 and 9 count only skills that
  are served (SKL-45)" becomes "Rows 8 and 9 ask the plugin layer's view (SCP-36), so a plugin it
  adds counts whatever it serves, plus kb's library files".
- **TOOL-9:** delete it.
- **AGENTS.md:** in the progressive-disclosure table, the list row becomes "one `SKILL.md` per
  skill in scope, plus `_files.md` | grows with the catalogue". The sentence above it, "adding a
  library adds neither tools nor listing rows", becomes "adding a library adds no tools". In "Do not
  reach for `ResourcesAsTools`…", "`resources/list` is 1.9 KB…" becomes "the listing is the plugin
  layer's, and `SkillsDirectoryProvider` would list a second copy".
- **README.md:** line 41's "a listing is a dozen index rows…" becomes "the listing names each
  skill's `SKILL.md`; indexes read, unlisted". Line 43 drops "no `?listing=full` is needed…". The
  `?listing=full` row at line 187 becomes `?listed=` / `Kb-Listed` (`skills`, `prompts`, `agents`
  or `none`).
- **Wiki** (on the wiki's `issue-86` branch): `Installing.md`'s `?listing=full` row and its
  paragraph at lines 46-47 become `?listed=` / `Kb-Listed`. `Skills.md` lines 70 and 93,
  `Scoping.md`'s Listing row and `Home.md` line 47 are reworded to L1.
- **CHANGELOG.md**, `[Unreleased]`:
  - Added: `` - Choose what `resources/list` lists with `Kb-Listed` (`?listed=`): `skills`, `prompts`, `agents` or `none`. ``
  - Changed: `` - `resources/list` lists each skill's `SKILL.md` and each library's `_files.md`; the `_index.md` files still read, unlisted. ``
  - Removed: `` - **BREAKING:** `Kb-Listing` (`?listing=`, `?skills=`, `X-Skill-Listing`) is no longer read. ``
  - Line 44: drop `` `Kb-Listing`, ``.

- [ ] **Step 7: Run every check**

Run: `ruff check . && pytest && python scripts/generate_wiki.py --check`
Expected: all pass, `tests/test_wiki.py` not skipped.

- [ ] **Step 8: Commit**

```bash
git add kubed tests docs/superpowers/specs AGENTS.md README.md CHANGELOG.md wiki
git commit -S -m "feat: list a SKILL.md row per skill through kubed-mcp's Listed; drop Kb-Listing (#86)"
```

### Task 2: The prompt mirror goes (L3, L4)

**Files:**
- Modify: `kubed/mcp_kb/mcp/prompts.py` (delete `ReadOnlyPromptsAsTools`, `_annotate`,
  `PROMPT_TOOLS`, `register`, `_mirrored`, the `functools`, `ContextVar`, `NotFoundError`,
  `ToolError`, `QuickMCP`, `PromptsAsTools`, `Tool`, `ToolAnnotations` and `READ_ONLY` imports;
  `_ask`; the module docstring)
- Modify: `kubed/mcp_kb/mcp/tools.py` (delete `READ_ONLY`; add `RESOURCES_PARAM`,
  `RESOURCES_HEADER`; docstring: the resource pair and nothing else)
- Modify: `kubed/mcp_kb/mcp/resources.py` (delete `HideMirrorTools`)
- Modify: `kubed/mcp_kb/mcp/request.py` (delete `PROMPTS_*`, `client_uses_prompts`)
- Modify: `kubed/mcp_kb/app.py` (delete `prompts.register`, `HideMirrorTools` and their imports;
  the module docstring)
- Modify: `scripts/generate_wiki.py` (`_reveals`, `_live_tools`, the page prose), `wiki/Tools.md`
  (regenerated), `tests/test_wiki.py`
- Modify: specs `http-and-tools.md` (TOOL-1 to TOOL-20), `prompts.md` (PRM-3, PRM-57),
  `scoping-and-instructions.md` (SCP-2's Prompts row, SCP-21, SCP-24, the opening);
  `AGENTS.md`; `.github/copilot-instructions.md`; `CONTRIBUTING.md` (the `mcp/` row); `README.md`;
  `CHANGELOG.md`; wiki `Prompts.md`, `Installing.md`
- Test: `tests/test_delivery_tools.py` (create); then `test_scope_and_prompt_tools.py`,
  `test_input_required.py`, `test_qualified_names.py`, `test_address_space.py`,
  `test_plugin_root.py`, `test_skipped.py`, `test_header_scope.py`, `test_server.py`,
  `test_scope.py`

**Interfaces:**
- Consumes: Task 1's `tools.LISTED_*`.
- Produces: `tools.RESOURCES_PARAM = "resources"` and `tools.RESOURCES_HEADER = "kb-resources"`,
  read by `generate_wiki.py` and `tests/test_wiki.py` only.

- [ ] **Step 1: Write the failing tests** in `tests/test_delivery_tools.py`

```python
@pytest.mark.unit
async def test_kb_registers_no_tool(skills_dir):              # DLV-7, check 2
    mcp = server_of(KnowledgeBase(make_config(skills_dir), skills_dir / "_cache"))
    assert await mcp.list_tools(run_middleware=False) == []
    for name in ("list_resources", "read_resource"):
        assert await mcp.get_tool(name) is not None

@pytest.mark.integration
@pytest.mark.parametrize("sent", [{"Kb-Prompts": "off"}, {"X-MCP-Prompts": "off"}, "?prompts=off"])
async def test_the_prompt_inputs_do_nothing(server_url, sent):
    # tool names == []; prompts/list == the prompts with no input; prompts/get renders as without

@pytest.mark.integration
@pytest.mark.parametrize("off", ["off", "OFF", " false ", "0", "no", "none"])
@pytest.mark.parametrize("header", ["Kb-Resources", "X-MCP-Resources"])
async def test_tool_3s_spellings_list_the_pair(server_url, header, off):   # check 1
    # names == ["list_resources", "read_resource"]; and for "on", "true", "1", "yes": names == []

@pytest.mark.integration
async def test_a_prompts_file_reads_through_the_tool_when_listed(server_url):
    # headers {"Kb-Resources": "off", "Kb-Listed": "prompts"}: a prompts:// row of list_resources
    # reads through read_resource, and its text holds the prompt's body

@pytest.mark.integration
async def test_read_resource_follows_dlv6_for_a_skills_blobs(tmp_path):    # check 3
    # a skill with assets/x.png (PNG bytes), assets/x.bin (b"\x00\xff"), assets/x.svg:
    # read_resource x.png -> ImageContent, mimeType image/png
    # x.bin -> JSON text with "binary": true and "Not returned: binary content is not text."
    # x.svg -> its text

@pytest.mark.unit
async def test_prompts_get_still_asks_at_2026_07_28(...):                 # check 6
    # as test_input_required's native ask, with the mirror gone: an InputRequiredResult keyed
    # "arguments"; then an older protocol gets PRM-52's error
```

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_delivery_tools.py -v`
Expected: FAIL. `get_prompt` and `list_prompts` are registered, and `?prompts=off` lists them.

- [ ] **Step 3: Implement** the deletions in the Files list. `MCPFilePrompt._ask` opens with
  `if not _can_ask(): return None`. In `generate_wiki.py`, `_reveals()` returns only the resource
  pair, from `tools_module.RESOURCES_PARAM` and `RESOURCES_HEADER`. `_live_tools()` returns the
  pair alone, because `app.server.list_tools(run_middleware=False)` is now empty. `tools_page()`'s
  prose names two tools. `tests/test_wiki.py` drops `request.PROMPTS_*` and reads
  `tools.RESOURCES_*` in place of `request.RESOURCES_*`.

- [ ] **Step 4: Bring the suite along**

Run: `pytest -x -q`.
- **Delete** the tests of the mirror itself: `test_scope_and_prompt_tools.py`'s `list_prompts` and
  `get_prompt` tests, `test_input_required.py`'s two mirror cases, `test_header_scope.py`'s
  `X-MCP-Prompts`/`Kb-Prompts` tests, and `test_scope.py`'s `client_uses_prompts` assertions.
- **Convert** a test that used the mirror only to render a prompt to `client.get_prompt(...)`:
  `test_qualified_names.py:180`, `test_address_space.py:361`, `test_plugin_root.py:270`. In
  `test_skipped.py:272`, drop the mirrored half and keep the native one.
- `test_server.py::test_the_mirrors_are_four_tools_whatever_the_catalogue_holds` is replaced by
  `test_kb_registers_no_tool`.
- `test_server.py::test_read_resource_explains_an_unknown_uri` keeps its message assertions and
  drops the two log assertions (L4).

- [ ] **Step 5: Regenerate the wiki.** Run `python scripts/generate_wiki.py`. `wiki/Tools.md` loses
  the `list_prompts` and `get_prompt` sections and rows, and `&prompts=off` goes from its example
  URL. Any other change to a generated page is a finding.

- [ ] **Step 6: Spec, docs, changelog**

- **TOOL-1:** "The server has two tools, kubed-mcp's resource pair (DLV-6). It is registered once
  kb adds its first plugin to the plugin set and listed by the request's resources setting
  (DLV-2)." The table keeps the two resource rows.
- **TOOL-2:** "A request that declares nothing sees no tools…", keeping the VS Code clause. Drop
  "Each pair is listed independently of the other."
- **TOOL-3:** "`off`, `false`, `0`, `no` and `none` declare resources off, and `on`, `true`, `1`
  and `yes` on, ignoring case and surrounding space. Any other value is passed over for the next
  source with a warning, and none means on unless TOOL-2's known clients say otherwise (DLV-2)."
- **TOOL-4 to TOOL-7:** "mirror tool" becomes "either tool". TOOL-6 keeps the first two titles only
  and cites the tools' DLV-6.
- **TOOL-8, TOOL-10 to TOOL-13:** unchanged except "the plugin layer's" becomes "kubed-mcp's
  (DLV-6)". **TOOL-12:** the error message is the one `resources/read` fails with, hint included,
  as kubed-mcp hands it on.
- Delete **TOOL-14** to **TOOL-20**, and the `## list_prompts and get_prompt` heading. Rename
  `## The mirror tools` to `## The resource tools`.
- **PRM-3:** delete it. **PRM-57:** "An older protocol and a client that declared no form
  elicitation are never asked. They get the failure in PRM-52."
- **SCP-2:** delete the Prompts row. **SCP-21** and **SCP-24:** "the mirror tools" becomes "the
  resource tools", and "or `get_prompt`" goes. The file's opening names `Kb-Resources` alone.
- **AGENTS.md:** "The surface, and why the tools are a mirror": the tools are kubed-mcp's resource
  pair, and a tools-only client reads prompt files at `prompts://` with `Kb-Listed: prompts`.
  "Adding a tool" no longer cites `mcp/prompts.py` or `READ_ONLY`. The `?prompts=off` sentence
  goes. The `PromptsAsTools` afternoon goes. The layout rows for `resources.py` (no
  `HideMirrorTools`) and `tools.py`/`prompts.py` change.
- **`.github/copilot-instructions.md`** lines 66-67 and 78, and **CONTRIBUTING.md**'s `mcp/` row:
  the same.
- **README.md** lines 55-62 and 183: two tools, revealed with `?resources=off`. A tools-only
  client reads prompt files with `?listed=prompts`.
- **Wiki:** `Prompts.md` lines 267-268 and `Installing.md` lines 25, 81-82, 90 and 120.
- **CHANGELOG.md:** Removed: `` - **BREAKING:** The `list_prompts` and `get_prompt` tools and `Kb-Prompts` (`?prompts=`, `X-MCP-Prompts`) are gone; a tools-only client lists prompt files with `Kb-Listed: prompts` and reads them with `read_resource`. ``
  Line 44: drop `` and `Kb-Prompts` ``.

- [ ] **Step 7: Run every check**

Run: `ruff check . && pytest && python scripts/generate_wiki.py --check`
Expected: all pass. `tests/test_kinds_as_resources.py` passes unchanged.

- [ ] **Step 8: Commit**

```bash
git add kubed scripts tests docs/superpowers/specs AGENTS.md README.md CONTRIBUTING.md \
  .github/copilot-instructions.md CHANGELOG.md wiki
git commit -S -m "feat: drop the prompt mirror tools; kubed-mcp's resource pair is the only tools (#86)"
```

### Task 3: The footer reads kubed-mcp's resolution (L5)

**Files:**
- Modify: `kubed/mcp_kb/mcp/instructions.py` (`ScopedInstructions` becomes the `fn`; the module
  docstring)
- Modify: `kubed/mcp_kb/mcp/request.py` (delete `RESOURCES_*`, `_OFF`, `_declared_on`,
  `client_reads_resources`, `declared_on_initialize`, `declared_on_discover` and the
  `client_supports_extension` import; the module docstring is about the scope alone)
- Modify: `kubed/mcp_kb/app.py` (`mcp.instructions(...)` in place of `add_middleware`)
- Modify: spec `scoping-and-instructions.md` (INS-2, INS-3, INS-15, INS-16); `AGENTS.md`
- Test: `tests/test_instructions.py`

**Interfaces:**
- Consumes: Task 0's fact that `Resolved.extensions` carries the declared id in both eras.
- Produces: `ScopedInstructions(snapshot: Callable[[], Snapshot])` with
  `__call__(self, delivery: Resolved) -> str`.

- [ ] **Step 1: Write the failing tests** in `tests/test_instructions.py`

```python
@pytest.mark.unit
def test_the_fn_builds_from_the_resolution(tmp_path):
    cat = _catalogue(tmp_path, {LibraryText("penpot"): ["router"]})
    fn = ScopedInstructions(lambda: SimpleNamespace(catalogue=cat, folders=lambda scope: {}))
    on = SimpleNamespace(resources="on", extensions=None, prefix="kb+")
    assert fn(on).startswith("Skills (skill://penpot/_index.md)")   # unprefixed: kubed-mcp writes it
    assert fn(on).endswith(RES_FOOTER)
    assert fn(SimpleNamespace(resources="off", extensions=frozenset(), prefix=None)).endswith(TOOLS_FOOTER)
    assert fn(SimpleNamespace(resources="on", extensions=frozenset({EXTENSION_ID}), prefix=None)
              ).startswith("Skills: skill://penpot/_index.md")

@pytest.mark.integration
@ERAS
async def test_the_footer_follows_what_kubed_mcp_resolved(server_url, mode):
    # told(server_url, mode) with client_info=VS_CODE (told gains client_info=None):
    #   endswith(TOOLS_FOOTER), and the same client lists ["list_resources", "read_resource"]
    # {"Kb-Resources": "on"} with VS_CODE: endswith(RES_FOOTER), no tools
    # {"Kb-Resources": "nonsense"}: endswith(RES_FOOTER)   (passed over, DLV-2)
```

`test_a_missing_message_means_the_extension_is_not_declared` and
`test_a_missing_message_still_gets_instructions` are deleted: there is no context to read now. The
second is replaced by the first test above.

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_instructions.py -v`
Expected: FAIL. `ScopedInstructions` is not callable, and VS Code gets the resources footer.

- [ ] **Step 3: Implement** D5. `instructions.py` imports neither `prefix` nor `prefixed`, and
  imports `Resolved` from `kubed.mcp.delivery` under `TYPE_CHECKING`. `EXTENSION_ID` stays in
  `request.py`. `app.py`:
  `mcp.instructions(ScopedInstructions(serving.served_snapshot))`, at the line where the middleware
  was added, with its comment kept.

- [ ] **Step 4: Run the instructions, prefix and refusal tests**

Run: `pytest tests/test_instructions.py tests/test_addressing_http.py tests/test_header_scope.py tests/test_server.py -v`
Expected: PASS, the existing INS tests unchanged. That includes `kb+` written once,
`test_unknown_library_scope_is_still_refused` (INS-5),
`test_a_refresh_between_the_pin_and_the_instructions` and both eras of
`test_declared_skills_extension_drops_names`. A `kb+kb+` or a missing extension is a finding.

- [ ] **Step 5: Spec and AGENTS.md**

- **INS-2:** "…whether the client reads resources, which is kubed-mcp's resolved `resources`
  setting for the request (DLV-2, DLV-15)…".
- **INS-3:** "The client declared the Skills extension when `io.modelcontextprotocol/skills` is
  among the extensions kubed-mcp resolved for the request (DLV-11)."
- **INS-15:** the Mode column reads "Resources (`resources` resolved `on`)" and "Tools (`resources`
  resolved `off`, a VS Code client with no setting included)". The copy is unchanged.
- **INS-16:** "kubed-mcp writes the prefix over the whole text kb's instructions hook returns
  (DLV-11), by SKL-40 and SKL-41."
- **AGENTS.md:** the layout row for `mcp/instructions.py` becomes "`ScopedInstructions`: the
  `instructions` hook kubed-mcp calls with each `initialize` and `server/discover` request's
  resolution". The facade list adds `kubed.mcp.delivery` (its `Resolved`, for that hook).

- [ ] **Step 6: Run every check**

Run: `ruff check . && pytest && python scripts/generate_wiki.py --check && python -m build && twine check --strict dist/*`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add kubed tests docs/superpowers/specs AGENTS.md
git commit -S -m "feat: the instructions footer follows kubed-mcp's resolved resources (#86)"
```
