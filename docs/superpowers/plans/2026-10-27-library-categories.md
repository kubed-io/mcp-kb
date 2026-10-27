# Library Categories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- A library lists `categories`, and `Kb-Category` selects every library that lists one.
- The scope settings get `Kb-` names, with the old `X-` names as aliases.

**Architecture:**
- `LibraryConfig.categories` flows into the snapshot's `Library`, and from there onto every
  in-library record (`Skill`, `_Root`, `FilePrompt`) as `library_categories`.
- The scope's category check accepts a match on either the plugin's own category or the
  library's.
- `mcp/request.py` reads the new names first and the old ones as aliases.

**Tech Stack:** Python ≥3.11, FastMCP 4.1.4, pydantic, pytest + pytest-asyncio, uvicorn.

**Spec:** `docs/superpowers/specs/2026-10-27-library-categories-design.md` (binding; D1–D5,
Acceptance 1–9).

## Global Constraints

- **Toolchain.** Run everything from the worktree root:
  - `.venv/bin/python -m pytest -q`
  - `.venv/bin/ruff check .`
  - `.venv/bin/python scripts/generate_wiki.py --check`
  - `.venv/bin/mcp-kb schema > config.schema.json`
- **Python and lint.** Python 3.11 is the floor. Lines in `kubed/` are at most 88 columns.
  Nothing under `catalogue/` imports FastMCP. Comments are terse.
- **Names, verbatim (spec D3).** Each header, its query parameter, and the aliases tried in this
  order:

  | Header | Parameter | Old header | Old parameter |
  |---|---|---|---|
  | `kb-library` | `library` | `x-skill-library` | — |
  | `kb-category` | `category` | `x-skill-categories` | `categories` |
  | `kb-tag` | `tag` | `x-skill-tags` | `tags` |
  | `kb-listing` | `listing` | `x-skill-listing` | `skills` |
  | `kb-resource-prefix` | `prefix` | `x-mcp-resource-prefix` | — |

  Precedence: the new header, then the old header, then the new parameter, then the old
  parameter. `x-mcp-resources` and `x-mcp-prompts` are unchanged.
- **Config key:** `categories` (list of strings, default `[]`) on a library.
- **Defaults are unchanged.** With no scope settings every surface returns what `main` returns.
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A plugin in two libraries**, only one of which lists `dev`. Under `Kb-Category: dev` it
   appears in that library and not in the other. → Task 1,
   `test_category_is_per_library_for_a_shared_plugin`.
2. **A library listing `dev` while its plugin's own category is `automation`.** Both
   `Kb-Category: dev` and `Kb-Category: automation` select it. → Task 1,
   `test_library_or_plugin_category_selects`.
3. **Old and new header both sent with different values.** The new one wins. → Task 2,
   `test_new_header_beats_its_alias`.
4. **A pinned library plus a category it doesn't carry.** This is refused the same way an empty
   scope is today, not answered with an empty listing. → Task 1, `test_pin_and_foreign_category`.
5. **Library files (`_files.md` and a file under it) under a category scope** follow the library's
   categories like skills do. → Task 1, `test_library_files_follow_library_categories`.

---

### Task 1: Library categories select libraries

**Files:**
- Modify: `kubed/mcp_kb/config.py` (`LibraryConfig.categories`)
- Regenerate: `config.schema.json`
- Modify: `kubed/mcp_kb/catalogue/snapshot.py`. The `Library` dataclass gains
  `categories: tuple[str, ...] = ()`. `assemble_libraries` fills it from config. Every `Skill`,
  `_Root` and `FilePrompt` built for a library gets `library_categories`. `/health`'s library
  entry gains `"categories"` (spec D5).
- Modify: `kubed/mcp_kb/catalogue/skills.py`. `Skill` and `_Root` gain
  `library_categories: frozenset[str] = frozenset()`; `_admits` and `_Root.admits` pass it.
- Modify: `kubed/mcp_kb/catalogue/prompts/__init__.py`. `FilePrompt` gains `library_categories`.
  `kubed/mcp_kb/mcp/prompts.py`'s scope filter passes it.
- Modify: `kubed/mcp_kb/mcp/scope.py`:
  - `admits(library, category, labels, library_categories=frozenset())`
  - `admits_labels(category, labels, library_categories=frozenset())`
  - The category half passes when `not self.categories or category in self.categories or self.categories & library_categories`.
- Modify: `kubed/mcp_kb/mcp/pins.py`. Known categories include every library's `categories`
  (only the pinned library's when one is pinned).
- Test:
  - `tests/test_scope.py`: unit tests.
  - `tests/test_library_categories.py`: new, HTTP, with the module-scoped uvicorn fixture
    pattern from `tests/test_header_scope.py`. Use the **old** header `X-Skill-Categories` here;
    Task 2 adds the new names.

**Interfaces:**
- Produces:
  - `LibraryConfig.categories: list[str]`
  - snapshot `Library.categories: tuple[str, ...]`
  - `Skill`, `_Root` and `FilePrompt` carry `library_categories: frozenset[str]`
  - `Scope.admits(..., library_categories=frozenset())`

- [ ] **Step 1: Write the failing tests**
  - `test_scope.py::test_library_or_plugin_category_selects`: `Scope.parse(categories=["dev"])`
    admits `(lib, "automation", [], frozenset({"dev"}))`, and
    `Scope.parse(categories=["automation"])` admits the same. `Scope.parse(categories=["x"])`
    doesn't.
  - `test_library_categories.py`, a fixture config with three libraries, where two list
    `categories: [dev]` and no plugin has category `dev`:
    - `test_category_selects_libraries` (AC1): the listing has exactly the two libraries' index
      rows; a skill in each reads; `client.instructions` has exactly those two `[name]`
      headings.
    - `test_plugin_category_still_selects` (AC2): a plugin's own category selects it.
    - `test_pin_and_foreign_category` (AC3): a pin plus a category neither the library nor its
      plugins carry is refused like today's empty scope.
    - `test_tag_narrows_within_categories` (AC4).
    - `test_unknown_category_lists_library_categories` (AC5): the refusal text names `dev`.
    - `test_health_shows_library_categories` (AC7): `/health` → `libraries.<name>.categories`.
    - `test_category_is_per_library_for_a_shared_plugin`: a plugin listed in two libraries,
      only one with `dev`.
    - `test_library_files_follow_library_categories`: needs a fixture library with library
      files.
  - `test_assembly.py` or `test_plugins.py`: `test_selector_ignores_library_categories` (AC8).
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Full suite, ruff, schema test, then commit:** `feat: a library's categories select it`

### Task 2: The Kb- names, with the X- names as aliases

**Files:**
- Modify: `kubed/mcp_kb/mcp/request.py`: the constants and `_read` calls per the Global
  Constraints table. `_read` gains the old *parameter* as a final fallback.
- Modify: every docstring or user-facing string that names the old headers or parameters in
  `kubed/` (`server.py`, `routes.py`, `mcp/pins.py`, `mcp/tools.py`, `spec/builder.py`, …). Use
  `grep -rn -i -E 'x-skill-|x-mcp-resource-prefix|\?(categories|tags|skills)=' kubed`.
- Modify: tests that send the old names. Move them to the new names, except one alias test per
  setting.
- Test: `tests/test_header_scope.py` (or a new `tests/test_kb_headers.py`).

**Interfaces:**
- Consumes: Task 1.
- Produces: `LIBRARY_HEADER = "kb-library"`, `CATEGORY_HEADER = "kb-category"`,
  `TAG_HEADER = "kb-tag"`, `LISTING_HEADER = "kb-listing"`,
  `PREFIX_HEADER = "kb-resource-prefix"`. The old names live as `*_ALIAS` constants.

- [ ] **Step 1: Write the failing tests** (HTTP):
  - `test_new_headers_scope` covers each new header and each new parameter.
  - `test_old_names_still_work` covers each old header and old parameter (AC6).
  - `test_new_header_beats_its_alias`: `Kb-Library: a` with `X-Skill-Library: b` scopes to `a`,
    and likewise for category.
  - The pins refusal messages name the new header.
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement**, then move the existing tests to the new names.
- [ ] **Step 4: Full suite and ruff, then commit:** `feat: Kb- request headers; the X- names stay as aliases`

### Task 3: Docs and wiki

**Files:**
- `README.md`: the per-request table names the `Kb-` headers, with one line saying the old `X-`
  names still work. Keep the README a short advert.
- `CHANGELOG.md` `[Unreleased]`: Added (library categories, `Kb-Category` selecting libraries)
  and Changed (the `Kb-` names, old ones still accepted). One short line each.
- `examples/config.yaml`: one library with `categories`.
- `AGENTS.md`, `.github/copilot-instructions.md`: replace the old header names.
- Wiki (`wiki/`; commit inside it, no push):
  - `Scoping.md`: two ways in (library or category); the header / parameter / alias table and
    precedence; that a category matches the library's list or the plugin's own.
  - `Libraries.md`: `categories`.
  - `Agentgateway.md` and `Installing.md`: the `Kb-` names.
  - Regenerate the generated pages (`scripts/generate_wiki.py`).

- [ ] **Step 1: Write.**
- [ ] **Step 2: Verify:** `generate_wiki.py --check`, then `tests/test_wiki.py`,
  `tests/test_readme.py` and `tests/test_example_config.py` with no skips.
- [ ] **Step 3: Commit the wiki inside `wiki/` (no push), then the superproject with the
  pointer:** `docs: library categories and the Kb- headers`
