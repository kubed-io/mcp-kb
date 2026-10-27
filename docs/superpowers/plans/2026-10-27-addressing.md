# Addressing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** kb's addresses follow two request settings: an `X-MCP-Resource-Prefix` hint used inside text,
and an `X-Skill-Library` pin that drops the library segment. Every link then works behind a
multiplexing gateway in resources mode.

**Architecture:**
- A pure `Addressing` value in `catalogue/addressing.py` translates canonical
  `skill://<library>/<path>` addresses three ways: outgoing structured fields, outgoing text, and
  incoming addresses.
- `mcp/request.py` builds it per request.
- Each MCP surface applies it at the edge. The `Catalogue` grammar is unchanged.

**Tech Stack:** Python ≥3.11, FastMCP 4.1.4, pytest + pytest-asyncio, uvicorn for HTTP tests.

**Spec:** `docs/superpowers/specs/2026-10-27-addressing-design.md` (binding). This plan cites its
decisions as D1–D6 and acceptance cases as AC1–AC10.

## Global Constraints

- **Toolchain.** Run everything from the worktree root:
  - `.venv/bin/python -m pytest -q`
  - `.venv/bin/ruff check .`
  - `.venv/bin/python scripts/generate_wiki.py --check`

  Baseline at the branch start (`0fa2569`): run it once and record the count in your report.
- **Python and lint.** Python 3.11 is the floor. Lines in `kubed/` are at most 88 columns.
  `kubed/` has no `__init__.py`. Nothing under `catalogue/` imports FastMCP. Comments are terse.
- **Setting names**, verbatim:
  - header `x-mcp-resource-prefix` (sent as `X-MCP-Resource-Prefix`);
  - query parameter `prefix`;
  - the pin is the existing `x-skill-library` / `library`.

  A prefix is valid when it matches `^[A-Za-z][A-Za-z0-9+.-]*\+$`, so prefix + `skill` is always a valid scheme. An invalid one is ignored.
- **The canonical form never changes.** `Catalogue` methods keep taking and returning
  `skill://<library>/<path>`. Translation happens only at the MCP edge.
- **Structured fields never carry the prefix** (D2): a gateway adds its own prefix.
- **Instruction copy** (D5), verbatim:
  - Pinned pointer: `Skills (<prefix>skill://_index.md): …` and `Skills: <prefix>skill://_index.md`.
  - Pinned resources footer:
    `Read a listed skill at <prefix>skill://<path>/SKILL.md; read its _manifest in place of SKILL.md for the other files it ships.`
  - Unpinned footer with a prefix: `… at <prefix>skill://<library>/<path>/SKILL.md; …`.

  `<prefix>` is the request's prefix, empty by default. `<path>` and `<library>` are literal
  text in the footer.
- **Defaults are byte-identical.** With neither setting, every surface returns exactly what it
  returns on `main` (AC1).
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A library name that prefixes another** (`n8n` and `n8n-extra`). Pinned text translation
   must not touch `skill://n8n-extra/…`. → Task 1,
   `test_text_leaves_a_longer_library_name_alone`.
2. **A pinned library with a top-level folder named like the library**
   (`skill://penpot/penpot/x`). Incoming must try short then long and resolve the right one. →
   Task 1, `test_incoming_tries_short_then_long`.
3. **A client reusing an old long-form link under a pin.** It reads the same body as before. →
   Task 2, inside `test_pinned_listing_and_links_are_short`.
4. **A prefixed address sent straight to kb with no gateway** (`kb+skill://…` in
   `resources/read`). It resolves. → Task 2, `test_prefix_only_bodies_and_prefixed_reads`.
5. **`X-MCP-Resource-Prefix: kb`** (the target name without its `+`). It is invalid and ignored, so the
   output equals no header rather than writing `kbskill://`. → Task 1,
   `test_invalid_prefix_is_ignored`.

---

### Task 1: `Addressing` and the request setting

**Files:**
- Create: `kubed/mcp_kb/catalogue/addressing.py`
- Modify: `kubed/mcp_kb/mcp/request.py` (constants and `requested_addressing()`)
- Test: `tests/test_addressing.py` (unit)

**Interfaces:**
- Produces, in `catalogue/addressing.py`:
  - `@dataclass(frozen=True) class Addressing: prefix: str = ""; library: str = ""`
  - `Addressing.parse(prefix: str = "", library: str = "") -> Addressing`: strips both. An
    invalid prefix becomes `""`.
  - `Addressing.structured(uri: str) -> str`: D2 outgoing structured. Pinned
    `skill://<lib>/<p>` → `skill://<p>`. Anything else is returned unchanged.
  - `Addressing.text(body: str) -> str`: D2 outgoing text.
    - Pinned: `skill://<lib>/` → `<prefix>skill://`, and a bare `skill://<lib>` not followed by
      `[A-Za-z0-9._~%/-]` → `<prefix>skill://`.
    - Unpinned with a prefix: `skill://` → `<prefix>skill://`.
    - Otherwise the body is returned unchanged (same object is fine).
  - `Addressing.incoming(uri: str) -> list[str]`: canonical candidates in order.
    - A leading `<prefix>skill://` (when a prefix is set) is first rewritten to `skill://`.
    - Pinned: `[f"skill://{lib}/{rest}"]`, then `uri` itself when `rest`'s first segment is
      `lib`.
    - Unpinned: `[uri]`.
    - A string that isn't `skill://` after the rewrite: `[uri]`.
  - `Addressing.first(uri: str, look: Callable[[str], T | None]) -> T | None`: the first non-None
    `look(candidate)`.
  - `DEFAULT = Addressing()`
- Produces, in `mcp/request.py`:
  - `PREFIX_HEADER = "x-mcp-resource-prefix"`, `PREFIX_PARAM = "prefix"`
  - `requested_addressing() -> Addressing`, built from `_read(PREFIX_HEADER, PREFIX_PARAM)` and
    the same library value `requested_scope()` uses. Only the explicit pin counts (D3);
    categories and tags never shorten.

- [ ] **Step 1: Write the failing tests** in `tests/test_addressing.py`:
  - `test_default_changes_nothing`: `DEFAULT.text(s) == s` and `DEFAULT.structured(u) == u` for
    `u = "skill://penpot/a/SKILL.md"`; `DEFAULT.incoming(u) == [u]`.
  - `test_empty_prefix_is_the_default`: `Addressing.parse("") == DEFAULT`.
  - `test_invalid_prefix_is_ignored`: `Addressing.parse("kb").prefix == ""`;
    `Addressing.parse("1b+").prefix == ""`.
  - `test_pinned_structured_is_short`: `Addressing.parse(library="penpot")`:
    - `structured("skill://penpot/_index.md") == "skill://_index.md"`;
    - `structured("skill://penpot/router/SKILL.md") == "skill://router/SKILL.md"`;
    - `Addressing.parse("kb+", "penpot").structured(...)` never contains `kb+`.
  - `test_text_pinned_and_prefixed`: `Addressing.parse("kb+", "penpot").text(...)`:
    - `"see skill://penpot/router/SKILL.md and skill://penpot."` →
      `"see kb+skill://router/SKILL.md and kb+skill://."`;
    - `"skill://penpot/_index.md"` → `"kb+skill://_index.md"`.
  - `test_text_prefix_only`: `Addressing.parse("kb+").text("skill://penpot/a")` →
    `"kb+skill://penpot/a"`.
  - `test_text_leaves_a_longer_library_name_alone`: pinned `n8n`,
    `text("skill://n8n-extra/a skill://n8n/b")` → `"skill://n8n-extra/a skill://b"`.
  - `test_incoming_tries_short_then_long`: pinned `penpot`:
    - `incoming("skill://router/SKILL.md") == ["skill://penpot/router/SKILL.md"]`;
    - `incoming("skill://penpot/router/SKILL.md") == ["skill://penpot/penpot/router/SKILL.md", "skill://penpot/router/SKILL.md"]`;
    - with prefix `kb+`, `incoming("kb+skill://_index.md") == ["skill://penpot/_index.md"]`.
  - `test_first_returns_the_first_hit`: `first` with a dict lookup returns the long-form value
    when only the long form exists.

- [ ] **Step 2: Run them to verify they fail**

  Run: `.venv/bin/python -m pytest -q tests/test_addressing.py`
  Expected: FAIL on import.

- [ ] **Step 3: Implement `Addressing`** with the regex rules above (`re.escape` the library),
  and `requested_addressing()`. A two-line module docstring: what it is, and why it is pure.

- [ ] **Step 4: Run the whole suite, then commit**

  Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check .`
  Commit: `feat: Addressing — canonical addresses translated at the edge`

### Task 2: Resources: listing, reads and hints

**Files:**
- Modify: `kubed/mcp_kb/mcp/resources.py` (`CatalogueProvider._list_resources`,
  `_get_resource`, `NameTheFileToRead.on_read_resource`)
- Test: `tests/test_addressing_http.py` (new, HTTP). Copy the module-scoped uvicorn fixture
  pattern from `tests/test_header_scope.py` (`server_url`). The fixture libraries are
  `flatsource` (flat skills `alpha`, `beta`) and `deepsource` (folders); see `tests/conftest.py`.

**Interfaces:**
- Consumes: `requested_addressing()`, `Addressing.structured`, `.text`, `.first` (Task 1).
- Produces: listing rows with `uri = a.structured(entry.uri)` and
  `name = a.structured(entry.uri).removeprefix("skill://")`. Reads resolve via
  `a.first(uri, lambda c: catalogue.read(c, scope))`. The body is `a.text(body)`, and the
  returned `uri` is the one the client sent. The `mime` comes from the resolved canonical
  address. Hints resolve the same way, and their message text goes through `a.text`.

- [ ] **Step 1: Write the failing tests** in `tests/test_addressing_http.py`. Use a plain
  `Client(StreamableHttpTransport(url, headers=…))` and read with `client.read_resource`.
  - `test_defaults_are_unchanged` (AC1): no headers; listing contains
    `skill://flatsource/_index.md`; its body contains `skill://flatsource/alpha/SKILL.md`.
  - `test_pinned_listing_and_links_are_short` (AC2):
    - `X-Skill-Library: flatsource`: listing `uri`s include `skill://_index.md`, and `name`
      `_index.md`;
    - the body links `skill://alpha/SKILL.md`, and reading that returns alpha's body;
    - reading the long form `skill://flatsource/alpha/SKILL.md` returns the same body.
  - `test_prefix_only_bodies_and_prefixed_reads` (AC3): `X-MCP-Resource-Prefix: kb+`, no pin.
    - listing `uri`s are unchanged (`skill://flatsource/_index.md`);
    - the body links `kb+skill://flatsource/alpha/SKILL.md`;
    - reading `kb+skill://flatsource/alpha/SKILL.md` directly returns alpha's body.
  - `test_behind_a_simulated_gateway` (AC4): pin `flatsource` + prefix `kb+`.
    - Read `skill://_index.md`.
    - For every token matching `kb\+skill://\S+?(?=[:\s]|$)` in the body, strip `kb+` and read
      it. Every read succeeds.
    - Also read `skill://alpha/_manifest`.
  - `test_a_tag_scope_keeps_long_addresses` (AC5): `X-Skill-Tags: flat` (selects only
    `flatsource`). Listing still has `skill://flatsource/_index.md`.
  - `test_invalid_prefix_is_ignored` (AC10): `X-MCP-Resource-Prefix: kb`. Body identical to
    the default case's body.
  - `test_directory_hint_is_translated`: pin + prefix; reading `skill://alpha` (a directory)
    fails with a message naming `kb+skill://alpha/SKILL.md`.

- [ ] **Step 2: Run them to verify they fail**

  Run: `.venv/bin/python -m pytest -q tests/test_addressing_http.py`
  Expected: the AC1 and AC5 tests PASS; the rest FAIL.

- [ ] **Step 3: Implement** the provider and middleware changes.

- [ ] **Step 4: Run the whole suite, then commit**

  Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check .`
  Commit: `feat: resources follow the request's addressing`

### Task 3: Mirror tools, the Skills extension, prompts

**Files:**
- Modify: `kubed/mcp_kb/mcp/tools.py` (`list_resources`, `read_resource`)
- Modify: `kubed/mcp_kb/mcp/skills.py` (`SkillsExtension.list_skills`, `get_skill`)
- Modify: `kubed/mcp_kb/mcp/prompts.py` (the rendered messages)
- Test: `tests/test_addressing_http.py` (append)

**Interfaces:**
- Consumes: Task 1, and the resolve pattern from Task 2.
- **Tools.**
  - `list_resources` returns rows with `uri = a.text(entry.uri)`. A tool result is text.
  - `read_resource(uri)` resolves with `a.first`, returns `a.text(body)`, and its error hint goes
    through `a.text`.
- **Skills extension.**
  - Entries' `uri` and each file's `uri` go through `a.structured`. Never the prefix.
  - `skills/get` resolves its argument with `a.first`.
  - Digests and sizes stay those of the bytes `resources/read` serves. A body changed by
    `a.text` is a different byte string. So for a pinned or prefixed request, the entry's digests
    must match the translated bytes. Compute the entry from the translated body, or keep
    translation out of skill-file bodies when the Skills extension's entry is served. Choose the
    first; test it.
- **Prompts.** Every text content in a rendered prompt goes through `a.text`.

- [ ] **Step 1: Write the failing tests** (append):
  - `test_tools_mode_with_both` (AC7): headers pin `flatsource`, prefix `kb+`,
    `X-MCP-Resources: off`.
    - `list_resources` rows contain `kb+skill://_index.md`.
    - `read_resource` accepts `skill://alpha/SKILL.md`, `skill://flatsource/alpha/SKILL.md` and
      `kb+skill://alpha/SKILL.md`, all with the same body.
  - `test_skills_extension_with_a_pin` (AC8): a client declaring the extension (pattern in
    `tests/test_skills_extension.py`) with pin + prefix.
    - `skills/list` entries' `uri` start `skill://` with no library segment and never contain
      `kb+`.
    - `skills/get` with `skill://alpha/SKILL.md` succeeds.
    - The digest of the `SKILL.md` file entry equals the sha256 of the bytes `resources/read`
      returns for it under the same headers.
  - `test_prompt_renders_pinned_prefixed_root` (AC9): a fixture prompt using
    `${CLAUDE_PLUGIN_ROOT}` (add one to the fixture tree if none exists) renders `kb+skill://`
    with no library segment under pin + prefix. With no headers, it renders
    `skill://<library>` as before.

- [ ] **Step 2: Run them to verify they fail.**

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the whole suite, then commit**

  Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check .`
  Commit: `feat: tools, skills entries and prompts follow the addressing`

### Task 4: Instructions follow the addressing

**Files:**
- Modify: `kubed/mcp_kb/catalogue/instructions.py`
  (`build_instructions(catalogue, scope, *, resources, skills_extension, addressing: Addressing = DEFAULT)`)
- Modify: `kubed/mcp_kb/mcp/instructions.py` (pass `requested_addressing()`)
- Test: `tests/test_instructions.py` (append unit and HTTP cases)

**Interfaces:**
- Consumes: `Addressing`, `DEFAULT` (Task 1).
- Produces:
  - The pointer uses `a.text(index_uri(library))`.
  - The resources footer is built from the prefix and the pin, per Global Constraints.
  - Description and notes text goes through `a.text`.

- [ ] **Step 1: Write the failing tests** (AC6):
  - `test_pinned_prefixed_pointer_and_footer` (unit, one library `flatsource`):
    - the pointer line is `Skills (kb+skill://_index.md): alpha, beta`;
    - the last line is
      `Read a listed skill at kb+skill://<path>/SKILL.md; read its _manifest in place of SKILL.md for the other files it ships.`
  - `test_unpinned_prefixed_footer`: two libraries, prefix only. Pointers are
    `Skills: kb+skill://<lib>/_index.md`, and the footer has `kb+skill://<library>/<path>/SKILL.md`.
  - `test_default_addressing_is_byte_identical`: for the existing unit cases, the output with
    `addressing=DEFAULT` equals the output with the argument omitted.
  - `test_instructions_follow_headers` (HTTP, both eras): pin + prefix headers give the pinned
    pointer and footer.

- [ ] **Step 2: Run them to verify they fail.**

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the whole suite, then commit**

  Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check .`
  Commit: `feat: instructions name the addresses the client will use`

### Task 5: Docs and wiki

**Files:**
- Modify: wiki `Scoping.md` (the two settings, the three kinds of address, D3) and
  `Agentgateway.md`. The combined recipe switches to resources mode: route headers
  `X-Skill-Library: penpot` and `X-MCP-Resource-Prefix: kb+`, and the prefix must equal
  `<target>+`. Drop `X-MCP-Resources: off` from the recipe, and show the new example
  instructions.
- Modify: `CHANGELOG.md` `[Unreleased]` `### Added`: one short user-facing line.
- Modify: `README.md`: at most one line, only if it fits the advert voice.
- Regenerate: `scripts/generate_wiki.py`, if a generated page changed.

- [ ] **Step 1: Write the docs.** Copy strings from the code. Use example hosts only.
- [ ] **Step 2: Verify**

  Run: `.venv/bin/python scripts/generate_wiki.py --check && .venv/bin/python -m pytest -q tests/test_wiki.py tests/test_readme.py`
  Expected: pass, no skips.

- [ ] **Step 3: Commit the wiki first, inside `wiki/`, without pushing.** Then commit the
  superproject with the pointer. The controller pushes. Commit:
  `docs: addresses that fit where kb is served`
