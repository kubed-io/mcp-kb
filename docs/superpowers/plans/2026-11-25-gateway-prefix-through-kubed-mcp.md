# The Gateway Prefix Through kubed-mcp Implementation Plan

> **History.** Proposed for #81 (PR #93, into `issue-80`), after K3 (#79, PR #89). The issue's
> notes are the spec. Dr K's rulings of 2026-11-24 and 2026-11-25 (rulings 41 to 43) apply: no
> gateway switch at QA, `Kb-Resource-Prefix` stays and kubed-mcp reads it, and kb deletes the
> prefix code K3 left behind. The design is below; there is no separate design file.
> Approved as written by Dr K on 2026-11-25 (11:25 UTC):
> - G1 is a named change, and no dot-resolving middleware is kept.
> - G2 and G3 are accepted.
> - Both corrections to the notes stand.
> - The PR takes `no changelog`.
> - quick-mcp#46 asks GW-4 to resolve dots on all three methods and for a public `unprefixed()`.
>   A later pin bump that carries it undoes G1, and D2's own strip moves onto `unprefixed()`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use skill://superpowers/subagent-driven-development/SKILL.md (recommended) or skill://superpowers/executing-plans/SKILL.md to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** kb stops reading the gateway prefix and stops taking it off incoming addresses.
Every writer kb keeps calls kubed-mcp's `prefixed(text, prefix())` (GW-11).

**Architecture:** kubed-mcp's `_TakeThePrefix` (GW-4) already sits outside every kb provider and
hands each one the plain address, so kb's `ReadTheAddress` and `canonical()` go. Then
`catalogue/addressing.py` goes, and `request.py` loses its `PREFIX_*` names and
`requested_addressing()`. kb's writers move to `kubed.mcp.gateway.prefix` and `prefixed`.

**Tech Stack:** Python ≥3.11, `kubed-mcp==0.2.0rc2` (FastMCP through it), pytest +
pytest-asyncio, uvicorn.

**Spec:** this plan's design section; #81's notes in `.issue/issues.md`; the living spec in
[skills.md](../specs/skills.md), [scoping-and-instructions.md](../specs/scoping-and-instructions.md)
and [http-and-tools.md](../specs/http-and-tools.md).

## Design

### What K3 left, read in the code on `issue-80`

- `mcp/request.py` still defines `PREFIX_PARAM`, `PREFIX_HEADER` and `PREFIX_ALIAS`, and none of
  them is read. `requested_addressing()` returns `Addressing.parse(kubed.mcp.gateway.prefix() or "")`,
  so the input is already kubed-mcp's: `Kb-Resource-Prefix`, then `X-MCP-Resource-Prefix`, then
  `?prefix=` (`app.py`: `header_prefix="Kb"`).
- `catalogue/addressing.py` (`Addressing`, `.text`, `.canonical`, `DEFAULT`) is used by
  `mcp/request.py`, `mcp/resources.py`, `mcp/instructions.py`, `mcp/prompts.py` and
  `catalogue/instructions.py`. Tests use it in `test_addressing.py`, `test_instructions.py` and
  `test_skills_extension.py`.
- `mcp/resources.py` has `ReadTheAddress`, `canonical()`, `NOWHERE` and `_ENCODED_SLASH`.
  `register` appends `ReadTheAddress`, so it runs *inside* kubed-mcp's `_TakeThePrefix`.
- The instructions are still `catalogue/instructions.py::build_instructions`. K3's design
  mentioned `instructions(...)` in `uris.py`, but it did not ship.
- No kb code prefixes an agent. `agents/get` is kubed-mcp's since K3 (GW-5, K3's N12), so that
  row of the issue's split table is already done.

### Checked against kubed-mcp 0.2.0rc2 (`kubed/mcp/gateway.py` at tag `v0.2.0-rc.2`)

1. **GW-11 is there.** `prefix() -> str | None` gives the request's resolved prefix, and `None`
   off a request. `prefixed(text, prefix)` returns the text unchanged for `None`. It is
   idempotent and raises `ValueError` on an invalid prefix, which `prefix()` never returns. It
   writes in front of `skill://`, `prompts://` and `agents://`, using the same lookbehind as
   `Addressing.text` (`(?<![A-Za-z0-9+.-])`).
2. **GW-4 refuses `%2F`.** `_plain` checks this before it takes the prefix off: any served-scheme
   address holding `%2f` (any case) becomes `<scheme>://%2F`. This holds on `resources/read`,
   `skills/get` and `resources/directory/read`, and for a wrong-prefix address too.
3. **GW-4 resolves dot segments on `resources/read` only.** It resolves them over the whole path
   (the library is a segment), and a `..` with nothing to pop goes nowhere. `skills/get` and
   `resources/directory/read` lose the prefix only, so their dot segments reach the providers as
   sent. rc3 is the same.
4. **The prefix is taken off before kb's providers see the address.** `_TakeThePrefix` is
   `server.middleware[3]`, and kb's middleware is appended after it, so `CatalogueProvider`
   already sees plain addresses. `NameTheFileToRead` is inserted at index 0, outside it, and sees
   the URI as sent. `_as_sent` renames a miss back to the sent URI.
5. **Inputs and precedence.** `header_prefix="Kb"` makes `Kb-Resource-Prefix` beat
   `X-MCP-Resource-Prefix`, which beats `?prefix=` (DLV-16). A space in the query value reads as
   `+`.

### Decisions

- **D1. kubed-mcp owns incoming addresses.** `ReadTheAddress`, `canonical()`, `NOWHERE` and
  `_ENCODED_SLASH` go, and so does their registration. kb keeps no `%2F` check (Dr K, 2026-11-24).
  kb's `Catalogue` still resolves dot segments itself, in `uris.parse`, for every read, hint and
  directory it answers. So kb's own directories (a library, a folder) still resolve
  `resources/directory/read` dots by kb's rule. A skill's directories are kubed-mcp's, matched
  exactly, and a dotted one no longer resolves (G1). Dr K ruled against keeping a
  dot-resolving middleware for `directory/read`, because it would be a second address layer.
  quick-mcp#46 asks GW-4 to resolve dots on every method.
- **D2. The hint takes the prefix off itself.** `NameTheFileToRead` stays outermost (AGENTS.md:
  inside, the hint came out `kb+kb+`). It takes `prefix()` off the URI as sent when the URI starts
  with `<prefix>skill://`. This is the one place kb takes a prefix off, because GW-4's `_plain` is
  private in rc2; quick-mcp#46 asks for a public `unprefixed()` to replace it. It then resolves the address with a new pure `uris.resolved(uri)`. A wrong-prefix
  address, and a prefixed one on a request with no prefix, stay as sent, parse as nothing, and get
  no hint.
- **D3. Every kb writer calls `prefixed(text, prefix())`.** These are `CatalogueProvider` (listing
  and template descriptions, bodies, `_index.json`), `NameTheFileToRead` (hints), the rendered
  prompt, and the instructions. `catalogue/` imports no FastMCP, so `build_instructions` returns
  unprefixed text and `ScopedInstructions` prefixes the whole text. That gives the same result as
  prefixing each piece, because the other lines (`[name]`, skill paths, the tools footer) hold no
  address.
- **D4. The split, as the spec records it** (SKL-41; the spec carries no issue numbers):

  | Surface | Writer | Moves to kubed-mcp in |
  |---|---|---|
  | skill files, kubed-mcp's indexes inside a skill, an agent's card | GW-5 | K3 (done) |
  | resource mirror tools (results, input) | kubed-mcp's tools (DLV-6, GW-4, GW-7) | K3 (done) |
  | instructions | kb, `prefixed()` | #87 |
  | rendered prompts | kb, `prefixed()` | #82 |
  | library files, `_files.md`, plugin-root fallbacks, kb's library indexes and `_index.json` children, hints, listing and template descriptions | kb, `prefixed()` | never (kb-only) |

### Named changes for QA's dump

- **G1.** A `resources/directory/read` of a skill's directory, or of a folder inside one, that is
  spelled with `.` or `..` segments fails with `Directory not found`. Before, kb resolved the dots
  first. kb's own directories, and every `resources/read`, resolve as before.
- **G2.** A `resources/read` of a skill's file with a trailing `/`
  (`skill://<library>/<skill>/SKILL.md/`) is `Resource not found`. Before, kb dropped the slash.
- **G3.** kb's own text now prefixes `prompts://` and `agents://` addresses too, as GW-5 already
  does in a skill's files. It shows only where upstream text holds one.

Nothing changes for an operator. The gateway routes keep sending `Kb-Resource-Prefix: kb+`.
The PR takes the `no changelog` label (Dr K).

## Global Constraints

- `pyproject.toml` pins `"kubed-mcp==0.2.0rc2"`. If #92 (rc3) has merged into `issue-80`, work on
  top of it: rc3's `gateway.py` behaves as checked above.
- FastMCP is reached only through `kubed.mcp`. The prefix comes from `kubed.mcp.gateway`'s
  `prefix` and `prefixed`, never `_plain` or `_TakeThePrefix`. `catalogue/` and `plugins/` import
  no `kubed.mcp`, and `tests/test_boundaries.py` stays green.
- Absent and out of scope stay indistinguishable (SKL-35). A hint never names an address GW-4
  refused.
- Spec rows keep their IDs, and no ID is reused. The spec holds statements only, with no issue
  numbers.
- Python 3.11 floor; 88 columns.
- The checks every task runs: `ruff check .`, then its tests (`pytest tests/<file>.py -v`). The
  last task runs all of `pytest` and `python scripts/generate_wiki.py --check`. CI runs `ruff
  check .` and `pytest` on 3.11 and 3.14, the wiki check, and the OpenAPI lint, which this change
  does not touch.

## Review Focus

1. **A directory address holding `%2F`** (`kb+skill://flatsource%2Falpha`,
   `skill://flatsource/alpha%2Frefs`). GW-4 sends the read nowhere, and kb's hint, which no longer
   guards `%2F`, must name nothing. *(Task 1: `test_an_escaped_slash_is_hinted_nothing`.)*
2. **A wrong prefix, or a prefixed address on a request with none** (`other+skill://…` under
   `kb+`; `kb+skill://…` with no prefix). Either one is a bare miss: no read and no hint. *(Task 1:
   `test_a_foreign_prefix_is_a_bare_miss`.)*
3. **A request carrying both headers and the parameter.** One prefix wins in every kb writer, not
   only in the instructions. *(Task 2: `test_the_header_beats_the_parameter_in_every_writer`.)*
4. **Library notes that already hold `kb+skill://`, or `myskill://`.** These are prefixed once and
   left alone now that the instructions are prefixed whole. *(Task 2:
   `test_prefixed_instructions_never_double_prefix`.)*
5. **An `agents://` or `prompts://` address in kb's text** (G3). It now carries the prefix.
   *(Task 2: `test_addressing_http.py::test_every_served_scheme_is_prefixed_in_the_instructions`.)*

---

### Task 1: Incoming addresses are kubed-mcp's

**Files:**
- Modify: `kubed/mcp_kb/catalogue/uris.py` (add `resolved` beside `parse`, ~line 150)
- Modify: `kubed/mcp_kb/mcp/resources.py` (`NameTheFileToRead`; delete `canonical`,
  `ReadTheAddress`, `NOWHERE`, `_ENCODED_SLASH` and the `ReadTheAddress` line in `register`; drop
  the imports nothing uses any more, such as `re` and `Mapping`; module and `register` docstrings)
- Modify: `docs/superpowers/specs/skills.md` (SKL-13, SKL-42)
- Modify: `AGENTS.md` (the layout row for `resources.py`, and the `ReadTheAddress` sentence under
  "A skill's files are kubed-mcp's to serve")
- Test: `tests/test_uris.py`, `tests/test_skills_extension.py`, `tests/test_addressing_http.py`

**Interfaces:**
- Produces: `uris.resolved(uri: str) -> str | None`, the address `parse` reads:
  `skill://<library>/<path>`, or `skill://<library>` for a bare library, and None when `parse`
  gives None.
- Produces: `NameTheFileToRead` reading the prefix through `kubed.mcp.gateway.prefix()` and
  writing it with `prefixed(hint, p)`. Task 2 relies on `resources.py` importing both.

- [ ] **Step 1: Write the failing tests**

`tests/test_uris.py`:

```python
def test_resolved_names_the_address_parse_reads():
    assert resolved("skill://grafana/a/../b/SKILL.md") == "skill://grafana/b/SKILL.md"
    assert resolved("skill://grafana/") == "skill://grafana"
    assert resolved("skill://grafana/../../x") == "skill://grafana/x"
    assert resolved("kb+skill://grafana/x") is None
    assert resolved("skill://") is None
```

`tests/test_skills_extension.py`: rename
`test_dot_segments_and_escaped_slashes_read_alike_everywhere` to
`test_dot_segments_resolve_for_reads_and_escaped_slashes_for_nothing`. Its docstring becomes
`SKL-13: ".." resolves for every resources/read; a skill's directories match as sent (G1); an
escaped "/" names nothing anywhere.` Then replace its `up == plain` assertion:

```python
        with pytest.raises(MCPError, match="Directory not found"):  # G1
            await request(client, "resources/directory/read", uri=f"{root}/references/..")
        assert (await request(client, "resources/directory/read", uri=root))["resources"]
```

and add, after the escaped-read loop:

```python
        with pytest.raises(MCPError, match="Directory not found"):
            await request(client, "resources/directory/read", uri="skill://flatsource%2Falpha")
        with pytest.raises(MCPError, match="Unknown skill URI"):
            await request(client, "skills/get", uri=f"{root}%2FSKILL.md")
        with pytest.raises(MCPError, match="Resource not found"):  # G2
            await client.read_resource(f"{root}/SKILL.md/")
```

`tests/test_addressing_http.py`:

```python
@pytest.mark.integration
async def test_an_escaped_slash_is_hinted_nothing(server_url):
    for uri in ("kb+skill://flatsource%2Falpha", "skill://flatsource/alpha%2Frefs"):
        message = await _missed(server_url, uri, BOTH, tools=False)
        assert "Resource not found" in message
        assert not _HINTED.findall(message), message


@pytest.mark.integration
async def test_a_foreign_prefix_is_a_bare_miss(server_url):
    for uri, headers in (
        ("other+skill://flatsource/alpha", BOTH),
        ("kb+skill://flatsource/alpha", PIN),
    ):
        message = await _missed(server_url, uri, headers, tools=False)
        assert "Resource not found" in message
        assert not _HINTED.findall(message), message
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/test_uris.py tests/test_skills_extension.py tests/test_addressing_http.py -v`
Expected: `test_resolved_names_the_address_parse_reads` fails on the import (`resolved` is not
defined). In the renamed test, the G1 and G2 assertions fail, because `ReadTheAddress` still
resolves them. The two hint tests may already pass; they pin D2 through the rewrite.

- [ ] **Step 3: Implement**

- `uris.resolved(uri: str) -> str | None`: `parse`, then `f"{SCHEME}{library}/{path}"` when there
  is a path, else `f"{SCHEME}{library}"`.
- `NameTheFileToRead.on_read_resource`, on a miss:
  - `p = prefix()`.
  - `sent` is the URI as sent, minus `p` when it starts with `f"{p}{SCHEME}"`.
  - `address = resolved(sent)`, and `hint = catalogue.hint(address, scope)` when `address` is not
    None.
  - A hint has `address` replaced by `sent.rstrip("/")`, as it is now. Otherwise a
    `FolderNotFound` gives its own `miss.hint`.
  - `prefixed(hint, p)` writes the prefix, and the `MCPError` is as it is now.
  - The docstring names D2: the one strip kb keeps, and why.
- Delete `canonical`, `ReadTheAddress`, `NOWHERE` and `_ENCODED_SLASH`, and
  `mcp.add_middleware(ReadTheAddress())`.
- `register`'s docstring says kubed-mcp hands every provider the plain address (GW-4).
- Leave `CatalogueProvider` to Task 2.

- [ ] **Step 4: Check the trailing slash on a skill's directory**

Run a `resources/directory/read` of `skill://flatsource/alpha/` in the renamed test, before and
after the change.
- If it served before and fails now, add it to G1 (in this plan's design section and the PR body)
  with `pytest.raises(MCPError, match="Directory not found")`.
- If it serves either way, assert that it serves.

- [ ] **Step 5: Update the spec and AGENTS.md**

- SKL-13:
  - It keeps the RFC 3986 sentence and the `..`-past-the-root sentence.
  - It says the plugin layer resolves dots on `resources/read` (GW-4), and so for its
    `read_resource` tool (DLV-6).
  - On `resources/directory/read`, the plugin layer passes dots on as sent. kb's own directories,
    a library and a folder, resolve them by kb's rule: a `..` at the library is dropped. A
    skill's directory, and a folder inside one, match exactly, so a dotted one is
    `Directory not found`.
  - A miss is reported under the address as sent (GW-4).
  - An escaped `/` (`%2F`) anywhere in an incoming address resolves to nothing (GW-4), and
    percent-escapes are never decoded.
  - A URI that does not start with `skill://` resolves to nothing.
- SKL-42 says the plugin layer takes the prefix off before any provider is asked (GW-4), and
  keeps the rest of its text.
- AGENTS.md's layout row lists `NameTheFileToRead` and `HideMirrorTools`. The sentence
  "`ReadTheAddress` hands every provider the canonical address…" becomes: kubed-mcp's GW-4 hands
  every provider the plain address (the request's prefix off, and dot segments resolved on
  `resources/read`), because skill URIs are matched exactly, and kb's `Catalogue` resolves dots
  itself in `uris.parse`.

- [ ] **Step 6: Run the checks**

Run: `ruff check .` then
`pytest tests/test_uris.py tests/test_skills_extension.py tests/test_addressing_http.py tests/test_address_space.py tests/test_plugin_root.py -v`
Expected: all pass. `test_address_space.py::test_a_directory_read_drops_a_dot_segment_at_the_library`
and `::test_a_dot_segment_address_of_a_directory_names_the_file_to_read` pass unchanged.

- [ ] **Step 7: Commit**

```bash
git add kubed/mcp_kb/catalogue/uris.py kubed/mcp_kb/mcp/resources.py tests/test_uris.py \
  tests/test_skills_extension.py tests/test_addressing_http.py docs/superpowers/specs/skills.md AGENTS.md
git commit -m "Incoming addresses are kubed-mcp's: ReadTheAddress and kb's %2F guard go (GW-4)"
```

### Task 2: kb's writers through `prefixed(text, prefix())`; `Addressing` goes

**Files:**
- Delete: `kubed/mcp_kb/catalogue/addressing.py`, `tests/test_addressing.py`
- Modify: `kubed/mcp_kb/catalogue/instructions.py` (drop `addressing`, `_footer`, the `{prefix}`
  in `_FOOTER`)
- Modify: `kubed/mcp_kb/mcp/instructions.py:32-39`, `kubed/mcp_kb/mcp/prompts.py:48,128`,
  `kubed/mcp_kb/mcp/resources.py` (`CatalogueProvider`)
- Modify: `kubed/mcp_kb/mcp/request.py` (delete `PREFIX_PARAM`, `PREFIX_HEADER`, `PREFIX_ALIAS`,
  `requested_addressing`, and the `Addressing` and `resolved_prefix` imports)
- Modify: `docs/superpowers/specs/skills.md` (SKL-40, SKL-41),
  `docs/superpowers/specs/scoping-and-instructions.md` (INS-16),
  `docs/superpowers/specs/http-and-tools.md` (TOOL-11), `AGENTS.md` (`Addressing.text` in
  "`NameTheFileToRead` runs outside…")
- Test: `tests/test_instructions.py`, `tests/test_skills_extension.py:305`,
  `tests/test_addressing_http.py`

**Interfaces:**
- Consumes: Task 1's `resources.py` imports of `prefix` and `prefixed`.
- Produces:
  `build_instructions(catalogue: Catalogue, scope: Scope, *, resources: bool, skills_extension: bool) -> str`,
  always unprefixed.

- [ ] **Step 1: Write the failing tests**

`tests/test_addressing_http.py`:

```python
INPUTS = {
    "kb-header": ({"Kb-Resource-Prefix": "kb+"}, ""),
    "x-mcp-header": ({"X-MCP-Resource-Prefix": "kb+"}, ""),
    "parameter": ({}, "?prefix=kb%2B"),
}


async def _written(url, headers):
    """What each kb writer wrote under ``headers``, one string per writer."""
    async with _client(url, headers) as client:
        (template,) = await client.list_resource_templates()
        with pytest.raises(Exception) as hint:
            await client.read_resource("skill://flatsource/alpha")
        return {
            "instructions": client.instructions,
            "index": (await client.read_resource("skill://flatsource/_index.md"))[0].text,
            "children": (await client.read_resource("skill://flatsource/_index.json"))[0].text,
            "template": template.description,
            "prompt": (await client.get_prompt("flatsource_cite")).messages[0].content.text,
            "hint": str(hint.value),
        }


@pytest.mark.integration
@pytest.mark.parametrize("sent", INPUTS.values(), ids=INPUTS.keys())
async def test_every_kb_writer_follows_each_prefix_input(server_url, sent):
    headers, query = sent
    written = await _written(server_url + query, {**PIN, **headers})
    assert "kb+skill://flatsource/_index.md" in written["instructions"]
    assert "kb+skill://flatsource/alpha/SKILL.md" in written["index"]
    assert '"uri": "kb+skill://flatsource/alpha"' in written["children"]
    assert "Start at kb+skill://{library}/_index.md;" in written["template"]
    assert written["prompt"] == "Read kb+skill://flatsource/shared/x.md.\n"
    assert "kb+skill://flatsource/alpha/SKILL.md" in written["hint"]
    assert "kb+kb+" not in "".join(written.values())


@pytest.mark.integration
async def test_the_header_beats_the_parameter_in_every_writer(server_url):
    for headers in (
        {"Kb-Resource-Prefix": "kb+", "X-MCP-Resource-Prefix": "other+"},
        {"X-MCP-Resource-Prefix": "kb+"},
    ):
        written = await _written(f"{server_url}?prefix=other%2B", {**PIN, **headers})
        for writer, text in written.items():
            assert "kb+skill://" in text, writer
            assert "other+" not in text, writer
```

`tests/test_instructions.py`:
- Import `prefixed` from `kubed.mcp.gateway`, and drop the `addressing` import.
- `test_prefixed_pointer_and_footer`, `test_prefixed_pointer_without_names_and_notes` and
  `test_prefixed_multi_library_pointers` call
  `prefixed(build_instructions(cat, EVERYTHING, resources=True, skills_extension=False), "kb+")`
  and keep their assertions.
- `test_default_addressing_is_byte_identical` becomes `test_the_text_is_built_unprefixed`, over
  the same loop: `"kb+" not in build_instructions(cat, scope, **kw)`, and the last
  `endswith(RES_FOOTER)` assertion is kept.
- Add:

```python
@pytest.mark.unit
def test_prefixed_instructions_never_double_prefix(tmp_path):
    a = LibraryText("a", "A.", "See kb+skill://a/x/SKILL.md and myskill://a.")
    out = prefixed(_build(_catalogue(tmp_path, {a: ["x"]}), EVERYTHING), "kb+")
    assert "See kb+skill://a/x/SKILL.md and myskill://a." in out.splitlines()


```

`tests/test_addressing_http.py::test_library_notes_are_addressed_in_the_instructions` becomes
`test_every_served_scheme_is_prefixed_in_the_instructions` (G3):
- Its `notes` are `"Start at skill://lib/s/SKILL.md. Ask agents://lib/agents/x.md or prompts://lib/p."`.
- `plain` still holds the notes as written.
- `both` holds `"Start at kb+skill://lib/s/SKILL.md. Ask kb+agents://lib/agents/x.md or kb+prompts://lib/p."`.

`tests/test_skills_extension.py:305-306` becomes
`assert index == json.loads(prefixed(json.dumps(listed["resources"]), headers.get("Kb-Resource-Prefix")))`.

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/test_instructions.py tests/test_addressing_http.py -v`
Expected: `test_every_served_scheme_is_prefixed_in_the_instructions` fails on `kb+agents://`,
because `Addressing.text` writes in front of `skill://` only. The other tests pass already:
the input has been kubed-mcp's since K3, and `prefixed` over today's unprefixed text gives the
same lines. They pin every writer through the rewrite.

- [ ] **Step 3: Implement**

- `catalogue/instructions.py`:
  - `_FOOTER` is the plain text of INS-15's resources footer, with `skill://` and no
    placeholder. `_footer` and the `Addressing` import go.
  - `_section(catalogue, scope, text, names)` writes the description and the notes as `tidy`
    gives them.
  - The module docstring says the text is unprefixed and `mcp/instructions.py` prefixes it.
- `mcp/instructions.py`: `_text` returns `prefixed(build_instructions(...), prefix())`.
- `mcp/prompts.py`: `_filled` returns `prefixed(text, prefix())`.
- `mcp/resources.py`, in `CatalogueProvider`:
  - Each call reads `p = prefix()` once and writes `prefixed(..., p)` where it wrote `a.text(...)`.
  - The `a.canonical(...)` calls go, because the provider is handed the plain address (GW-4).
  - `_get_resource`'s `name` is `uri.removeprefix(SCHEME)`.
- `mcp/request.py`: delete the three `PREFIX_*` names, `requested_addressing`, and the imports
  only they used. The module docstring no longer mentions the prefix.
- Delete `catalogue/addressing.py` and `tests/test_addressing.py`.
- `grep -rn "addressing\|requested_addressing\|PREFIX_" kubed tests scripts` returns nothing.

- [ ] **Step 4: Update the spec and AGENTS.md**

- SKL-40:
  - The resource prefix is the plugin layer's input (GW-1 to GW-3), read with the server's header
    prefix `Kb` (DLV-16): `Kb-Resource-Prefix`, then `X-MCP-Resource-Prefix`, then `?prefix=`,
    as in SCP-3.
  - It keeps the `+`-for-space, validity and invalid-is-ignored sentences.
- SKL-41:
  - With a prefix, every `skill://`, `prompts://` and `agents://` address in text a client reads
    is written with the prefix in front. The same exceptions apply.
  - It keeps the Where/Prefixed table.
  - After it comes a "Written by" table, D4 without the last column, and with no issue numbers:
    the plugin layer for skill files, the indexes inside a skill and an agent's card (GW-5) and
    for the resource mirror tools (DLV-6, GW-7); kb, through the plugin layer's writer (GW-11),
    for the rest.
- INS-16 names every address in the description, the notes, the pointer and the resources
  footer. kb writes the prefix over the whole text with the plugin layer's writer (GW-11), and its
  rules are SKL-40 and SKL-41.
- TOOL-11: both tools are the plugin layer's (DLV-6). The prefix in their results is its own
  (GW-7), and so is taking the prefix off `read_resource`'s `uri` (GW-4).
- AGENTS.md: "(`Addressing.text` is idempotent)" becomes "(`prefixed` is idempotent)".

- [ ] **Step 5: Run every check**

Run: `ruff check .`, then `pytest`, then `python scripts/generate_wiki.py --check`
Expected: ruff is clean. pytest shows K3's 1307-passed baseline, minus `tests/test_addressing.py`'s
tests, plus this plan's, with 20 skipped and 1 xfail (N15). The wiki check is clean, because no
generated page reads a `PREFIX_*` name.

- [ ] **Step 6: Commit**

```bash
git add -A kubed/mcp_kb tests docs/superpowers/specs AGENTS.md
git commit -m "kb's writers call kubed-mcp's prefixed(text, prefix()) (GW-11); Addressing goes"
```

The PR body carries D4's table and G1–G3 for QA's dump. The dump is over the ten scopes, with and
without `kb+`, before and after deploy. The routes keep `Kb-Resource-Prefix: kb+`. The wiki needs
no commit: nothing an operator sets or reads changes.
