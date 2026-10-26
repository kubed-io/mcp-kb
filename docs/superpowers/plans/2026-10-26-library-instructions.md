# Library Instructions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The MCP `instructions` kb returns on `initialize` and `server/discover` are built from
the libraries the request's scope selects. Each library contributes its own text, with optional
notes and its skill names, and kb's own wording is a footer that follows the client mode.

**Architecture:**
- `config.py` and `plugins/marketplace.py` gain the inputs.
- `assemble_libraries` resolves each library's description, falling back to upstream's.
- `Catalogue` carries those texts. It opens a library's index with them and answers which libraries
  a scope selects.
- A pure builder in `catalogue/instructions.py` writes the text.
- A middleware in `mcp/instructions.py` puts it on each `initialize` and `server/discover` answer.

**Tech Stack:** Python ≥3.11, FastMCP 4.1.4 (`Middleware.on_initialize` / `on_discover`), pydantic,
pytest + pytest-asyncio, uvicorn for the HTTP tests.

**Spec:** `docs/superpowers/specs/2026-10-26-library-instructions-design.md`. Read it first; this
plan cites its decisions as D1–D9 and its acceptance cases as AC1–AC12.

## Global Constraints

- **Toolchain.** Run everything from the worktree root with its `.venv`
  (`.venv/bin/python -m pytest -q`, `.venv/bin/ruff check .`,
  `.venv/bin/python scripts/generate_wiki.py --check`). If `.venv` is missing:
  `python3 -m venv .venv && .venv/bin/pip install -e ".[test]"`.
- **Baseline** at `338fd23`: 780 passed, 8 skipped. The wiki tests skip without the submodule;
  `git submodule update --init wiki` checks it out.
- **Python 3.11 is the floor**: no 3.12+ syntax. Lines are at most 88 columns (ruff).
- **Module rules.** `kubed/` stays a PEP 420 namespace package with no `__init__.py`. Nothing under
  `catalogue/` imports FastMCP.
- **Config keys.** The new keys are `notes` (string, default `""`) and `listSkills` (boolean,
  default `true`, Python name `list_skills`). No key is named `instructions` (D9).
- **Exact copy** (spec D3–D5):
  - Pointer without names: `Skills: skill://<library>/_index.md`
  - Pointer with names: `Skills (skill://<library>/_index.md): <path>, <path>, …`, with paths
    joined by `", "`.
  - Heading: `[<library>]`.
  - Resources footer:
    `Read a listed skill at skill://<library>/<path>/SKILL.md; read its _manifest in place of SKILL.md for the other files it ships.`
  - Tools footer: `Read these with read_resource.`
- **Joins.** Lines inside a section are joined by `\n`. Sections, and the footer after them, are
  separated by `\n\n`. Description and notes are stripped of surrounding whitespace, and an empty
  one adds no line.
- **Comments are terse.** Keep the non-obvious why and drop the narration (Dr K trims verbose
  comments).
- **Commits.** End each commit message with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A YAML block `notes: |` ends in a newline, and a description may have trailing spaces. The text
   must have no doubled blank lines and no trailing whitespace. → Task 3,
   `test_block_scalars_leave_no_blank_runs`.
2. grafana-style nested skills share a final name across folders (`a/loki`, `b/loki`). The listed
   paths must keep them apart. → Task 2, `test_skill_paths_are_paths_under_the_library`.
3. A library whose marketplace failed to read but whose `plugins:` still serve is still selected,
   and its description falls back to those plugins'. → Task 1,
   `test_failed_marketplace_falls_back_to_plugin_descriptions`.
4. A scope naming a library that does not exist must still get an `initialize` answer: the footer
   alone, with no crash and no traceback. → Task 4,
   `test_unknown_library_scope_still_initializes`.
5. A marketplace `description` that is not a string (a number, an object) is treated as absent,
   not stringified. → Task 1, `test_non_string_marketplace_description_is_ignored`.

---

### Task 1: Inputs: config keys, the marketplace's description, the resolved description

**Files:**
- Modify: `kubed/mcp_kb/config.py` (`LibraryConfig`)
- Modify: `kubed/mcp_kb/plugins/marketplace.py` (`Marketplace`, `read_marketplace`)
- Modify: `kubed/mcp_kb/server.py` (the marketplace loop around `read_marketplace(`, and the
  `assemble_libraries(` call)
- Modify: `kubed/mcp_kb/catalogue/snapshot.py` (`Library`, `assemble_libraries`)
- Regenerate: `config.schema.json` (`mcp-kb schema > config.schema.json`)
- Test: `tests/test_config.py`, `tests/test_marketplace.py`, `tests/test_assembly.py`,
  `tests/test_server.py` (`/health`)

**Interfaces:**
- Produces:
  - `LibraryConfig.notes: str = ""`
  - `LibraryConfig.list_skills: bool = Field(True, alias="listSkills")`
  - `Marketplace.description: str = ""`
  - `Library.description: str`, now the resolved text (D6)
  - `Library.notes: str = ""`
  - `Library.list_skills: bool = True`
  - `assemble_libraries(config, plugins, *, errors=None, skipped=None, descriptions: dict[str, str] | None = None) -> list[Library]`,
    where `descriptions` maps a library name to its marketplace's description.

- [ ] **Step 1: Write the failing tests**
  - `test_config.py::test_library_notes_and_list_skills`: `listSkills: false` and
    `notes: "x"` load as `list_skills is False`, `notes == "x"`; both default to `True` and `""`;
    `list_skills: false` (snake case) in YAML is rejected like every other unknown key.
  - `test_marketplace.py::test_marketplace_description_top_level_then_metadata`: top-level
    `description` wins; with none, `metadata.description`; with neither, `""`.
  - `test_marketplace.py::test_non_string_marketplace_description_is_ignored`: `description: 3`
    with `metadata.description: "m"` gives `"m"`; `description: {}` alone gives `""`.
  - `test_assembly.py::test_description_chain`, three cases:
    - configured `description` beats `descriptions[name]`;
    - with none configured, `descriptions[name]` is used;
    - with neither, the library's plugins' non-empty descriptions are joined by `"\n"` in the
      library's plugin order.
  - `test_assembly.py::test_failed_marketplace_falls_back_to_plugin_descriptions`: a library with
    `source:` and `plugins: [p]`, whose `errors` holds a message and whose `descriptions` lacks
    it, gets `p`'s description.
  - `test_assembly.py::test_notes_and_list_skills_carry_through`: `Library.notes` and
    `Library.list_skills` equal the config's.
  - `test_server.py::test_health_shows_the_resolved_description`: a library with no configured
    description whose marketplace has `"Upstream words."` shows that text in
    `/health` → `libraries.<name>.description`.

- [ ] **Step 2: Run them to verify they fail**

  Run: `.venv/bin/python -m pytest -q tests/test_config.py tests/test_marketplace.py tests/test_assembly.py tests/test_server.py`
  Expected: the new tests FAIL (missing fields, missing `descriptions` keyword); the old ones pass.

- [ ] **Step 3: Implement**
  - The new fields.
  - `read_marketplace` sets `description` with the existing `_text` helper: top level first, then
    `data["metadata"]["description"]` when `metadata` is a dict.
  - `server.py` collects `market.description` per library and passes it as `descriptions=`.
  - `assemble_libraries` resolves the description. Text that came from a fetch (the marketplace's,
    or the plugins') goes through the same `scrub` the library's `error` already uses.
  - Regenerate `config.schema.json`.

- [ ] **Step 4: Run the whole suite**

  Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check .`
  Expected: all pass, including `test_schema.py::test_the_committed_schema_is_the_model`.

- [ ] **Step 5: Commit** (`feat: a library's description falls back to upstream's; notes and listSkills`)

### Task 2: The catalogue knows each library's text

**Files:**
- Modify: `kubed/mcp_kb/catalogue/uris.py` (new `LibraryText`; `Catalogue.__init__`, `selected`,
  `skill_paths`, `_index_body`)
- Modify: `kubed/mcp_kb/catalogue/snapshot.py` (`build_snapshot` builds the texts and passes them
  to `Catalogue(`)
- Test: `tests/test_uris.py`

**Interfaces:**
- Consumes: `Library.description`, `Library.notes`, `Library.list_skills` (Task 1).
- Produces, in `uris.py`:
  - `@dataclass(frozen=True) class LibraryText: name: str; description: str = ""; notes: str = ""; list_skills: bool = True`
  - `Catalogue(index, resources, revalidate=None, libraries: Sequence[LibraryText] = ())`
  - `Catalogue.selected(scope: Scope = EVERYTHING) -> list[LibraryText]`: the libraries with at
    least one skill visible in `scope`, in the order given to the constructor. A library with
    skills that has no `LibraryText` (an old test constructing `Catalogue` bare) gets a bare
    `LibraryText(name)`, appended in name order.
  - `Catalogue.skill_paths(library: str, scope: Scope = EVERYTHING) -> list[str]`: each visible
    skill's address with the leading `"<library>/"` removed, sorted by address.

- [ ] **Step 1: Write the failing tests**
  - `test_selected_follows_scope_and_constructor_order`: libraries `b` then `a` given; no scope →
    `["b", "a"]`; a scope that admits only `a`'s skills → `["a"]`; a library with no skills is
    never returned.
  - `test_skill_paths_are_paths_under_the_library`: skills at `lib/x/loki` and `lib/y/loki` →
    `["x/loki", "y/loki"]`; a tag scope admitting one → just that one.
  - `test_library_index_opens_with_its_text`: with description `"D."` and notes `"N."`, the
    library-level `_index.md` body is `"# lib — 2 skills\n\nD.\nN.\n\n"` followed by the skill
    lines exactly as before. A folder-level index is unchanged, and a library with neither text
    is byte-identical to today's.

- [ ] **Step 2: Run them to verify they fail**

  Run: `.venv/bin/python -m pytest -q tests/test_uris.py`
  Expected: the three new tests FAIL.

- [ ] **Step 3: Implement.** `build_snapshot` maps each `Library` to a `LibraryText` in config order.
  `_index_body` takes the text from the same place `selected` does.

- [ ] **Step 4: Run the whole suite**

  Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check .`
  Expected: all pass.

- [ ] **Step 5: Commit** (`feat: indexes open with their library's text`)

### Task 3: The instructions text

**Files:**
- Create: `kubed/mcp_kb/catalogue/instructions.py`, with no FastMCP import
- Test: `tests/test_instructions.py` (unit half)

**Interfaces:**
- Consumes: `Catalogue.selected`, `Catalogue.skill_paths`, `LibraryText`, `index_uri` (Task 2).
- Produces:
  `build_instructions(catalogue: Catalogue, scope: Scope, *, resources: bool, skills_extension: bool) -> str`.
  - `resources` is false in tools mode.
  - `skills_extension` is true when the client declared `io.modelcontextprotocol/skills`.

- [ ] **Step 1: Write the failing tests.** Build a `Catalogue` straight from fixture skills, as
  `test_uris.py` does. The exact strings are in Global Constraints.
  - `test_one_library_has_no_heading_and_lists_paths`: one library `penpot`, description `"P."`,
    notes `"Start at router."`, skills `router` and `deck`. The result is exactly:
    ```
    P.
    Start at router.
    Skills (skill://penpot/_index.md): deck, router

    Read a listed skill at skill://<library>/<path>/SKILL.md; read its _manifest in place of SKILL.md for the other files it ships.
    ```
  - `test_several_libraries_get_headings_and_no_names`: two selected libraries give
    `[a]\n…\nSkills: skill://a/_index.md\n\n[b]\n…` then the footer, with no names anywhere.
  - `test_list_skills_false_drops_the_names`: one library with `list_skills=False` gives
    `Skills: skill://penpot/_index.md`.
  - `test_skills_extension_drops_the_names`: `skills_extension=True` gives the same pointer
    without names.
  - `test_tools_mode_footer`: `resources=False` makes the last line
    `Read these with read_resource.`
  - `test_nothing_selected_is_the_footer_alone`.
  - `test_empty_description_and_notes_start_at_the_pointer`.
  - `test_block_scalars_leave_no_blank_runs`: notes `"a\n"` and description `"d  "` produce no
    `"\n\n\n"` and no line ending in a space.

- [ ] **Step 2: Run them to verify they fail**

  Run: `.venv/bin/python -m pytest -q tests/test_instructions.py`
  Expected: FAIL on import (`build_instructions` does not exist).

- [ ] **Step 3: Implement `build_instructions`** to D3–D5 and the exact copy above. A module
  docstring of two or three lines saying what it is and why it is pure.

- [ ] **Step 4: Run the whole suite**

  Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check .`
  Expected: all pass.

- [ ] **Step 5: Commit** (`feat: instructions built from the libraries in scope`)

### Task 4: Served on connect

**Files:**
- Create: `kubed/mcp_kb/mcp/instructions.py`
- Modify: `kubed/mcp_kb/server.py`: remove `INSTRUCTIONS`, pass no `instructions=` to `FastMCP(`,
  and add the middleware next to `AdvertiseLegacySkills()`
- Test: `tests/test_instructions.py` (HTTP half: a module-scoped uvicorn fixture, copied from
  `tests/test_header_scope.py::server_url`)

**Interfaces:**
- Consumes: `build_instructions` (Task 3), `requested_scope`, `client_reads_resources`
  (`mcp/request.py`).
- Produces: `class ScopedInstructions(Middleware)`, constructed with a
  `Callable[[], Catalogue]`. It sets `instructions` on the result of `on_initialize` and
  `on_discover`. The discover result may be a `DiscoverResult` or a `dict`; handle both.
- **Declared extension.**
  - On `initialize`, read the capabilities from `context.message.params.capabilities.extensions`.
  - On `server/discover`, use `fastmcp.server.low_level.client_supports_extension(session, "io.modelcontextprotocol/skills")`.
    The session is `context.fastmcp_context.session`; 2026-07-28 clients send their capabilities
    in each request's `_meta`.
  - Missing anything means not declared.
- **Clients in tests.**
  - `Client(StreamableHttpTransport(url, headers=…), mode="legacy")` uses `initialize`; the
    default mode uses `server/discover`.
  - Read the result with `client.instructions`.
  - Declare the extension with `extensions=[SkillsClientExtension()]` (`fastmcp.skills`).

- [ ] **Step 1: Write the failing tests.** Every case runs over HTTP, through both
  `mode="legacy"` and the default mode (parametrize), which covers AC12.
  - AC1 `test_one_library_scope`: `X-Skill-Library: <fixture library>` gives no `[` heading, the
    pointer with the fixture's paths, and the resources footer.
  - AC2/AC3 `test_unscoped_lists_every_library_without_names`: the fixture's libraries as `[name]`
    sections in config order, no `(…)` names.
  - AC4 `test_list_skills_false`: a second app built from a config whose one library has
    `listSkills: false`.
  - AC5 `test_declared_skills_extension_drops_names`.
  - AC6 `test_resources_off_gets_the_tool_footer`: `X-MCP-Resources: off`.
  - `test_unknown_library_scope_still_initializes`: `X-Skill-Library: nope` connects without
    raising, and `client.instructions` is the footer alone.
  - AC11 `test_refresh_reaches_a_new_connection`: build a `file://` marketplace library in
    `tmp_path` with `description: "One."`, connect, rewrite it to `"Two."`, refresh the way
    `tests/test_refresh.py` does, then connect again and see `"Two."`.

- [ ] **Step 2: Run them to verify they fail**

  Run: `.venv/bin/python -m pytest -q tests/test_instructions.py -m integration`
  Expected: FAIL, because `client.instructions` is still the old fixed text.

- [ ] **Step 3: Implement** `ScopedInstructions` and the `server.py` wiring.

- [ ] **Step 4: Run the whole suite**

  Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check .`
  Expected: all pass. Fix any old test that asserted the removed `INSTRUCTIONS` text by asserting
  the new behaviour, not by deleting it.

- [ ] **Step 5: Commit** (`feat: each connection gets the instructions its scope selects`)

### Task 5: Docs, examples, wiki

**Files:**
- Modify: `examples/config.yaml`: one library with `notes`, one with `listSkills: false`, and a
  comment on the description fallback.
- Modify: `README.md`: at most one feature line (spec, *Docs and release*). It stays under
  `test_readme.py`'s limit and keeps its advert voice.
- Modify: `CHANGELOG.md` (follow its existing format), and `AGENTS.md` (the layout table gains
  `catalogue/instructions.py` and `mcp/instructions.py`).
- Wiki submodule `wiki/`:
  - modify `Libraries.md` and `Scoping.md`;
  - create `Agentgateway.md`;
  - add it to `_Sidebar.md` under **Getting started** after Deployment;
  - regenerate `Configuration.md` with `scripts/generate_wiki.py`.

  The content of each is set by the spec's *Docs and release* section.

- [ ] **Step 1: Write the docs.**
  - `Agentgateway.md` covers every bullet the spec lists for it. Each fact is stated plainly with
    its gateway version (1.6.0).
  - It includes a minimal `AgentgatewayBackend` with two targets (`penpot`, `kb`), and a route
    policy setting `X-Skill-Library: penpot` and `X-MCP-Resources: off`.
  - It shows the merged instructions the client receives.
  - Hostnames are examples (`mcp.example.com`), never a real one.

- [ ] **Step 2: Verify**

  Run: `.venv/bin/python scripts/generate_wiki.py --check && .venv/bin/python -m pytest -q tests/test_wiki.py tests/test_readme.py tests/test_example_config.py`
  Expected: pages up to date, and all pass with no skips (the submodule is checked out).

- [ ] **Step 3: Commit the wiki first, then the superproject.** In `wiki/`, run `git add -A`,
  `git commit`, then `git push origin HEAD:master`. Only after that commit the repo's changes
  together with the `wiki` pointer. CI cannot check out a wiki commit the remote lacks.

  The push to the wiki's `master` publishes the pages before this PR merges. That is the repo's
  existing practice: the wiki is its own repository. Say so in the PR body.

- [ ] **Step 4: Commit** (`docs: what a client sees on connecting, and kb behind agentgateway`)
