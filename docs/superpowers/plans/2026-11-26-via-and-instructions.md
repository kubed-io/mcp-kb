# Via and the Instructions Implementation Plan

> **History.** Proposed for #87 (PR #106, into `issue-80`). It follows K3 (#79, PR #89), the
> gateway prefix (#81, PR #93), the `_publish` race fix (#94, PR #96), K4 (#82, PR #97), K5 (#83,
> PR #100), the kubed-mcp 0.3.0 pin (#92, PR #99), K6 (#84, PR #102), #85 (PR #104) and the
> delivery inputs (#86, PR #105, `bb2cbd3`). The spec is #87's notes in `.issue/issues.md`, with
> Dr K's rulings of 2026-11-24 05:58 and the parent's messages up to 2026-11-26 04:16, which
> approved it. The design is below. There is no separate design file, and the branch had no draft
> spec.
>
> **#86 already did half of the notes.** Its D5 (Dr K, 2026-11-26 02:58) made `ScopedInstructions`
> the `mcp.instructions(fn)` hook. It also moved the footer and the Skills-extension check onto
> kubed-mcp's `Resolved`, deleted `declared_on_initialize` and `declared_on_discover`, and left the
> prefix to kubed-mcp. So this plan covers what is left: the Via modes (INS-20 to INS-22), the
> `fn` that never fails (INS-23, the parent's addition), and legacy `initialize` advertising what
> `server/discover` advertises (N17). `ScopedInstructions` keeps its name, because #86 kept it as
> the hook. The notes ruled out keeping it as a middleware, and it no longer is one.

> **For agentic workers:** REQUIRED SUB-SKILL: Use skill://superpowers/subagent-driven-development/SKILL.md (recommended) or skill://superpowers/executing-plans/SKILL.md to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A client's instructions follow kubed-mcp's Via mode. Under `mcp` they are unchanged.
Under `extension` they point at the material and carry a fixed extension footer. Under `local`
they carry each library's description and notes only. Building them never fails a handshake, and
legacy `initialize` advertises exactly the extensions `server/discover` does.

**Architecture:** `catalogue/instructions.py::build_instructions` gains a `via` keyword and a
`footer()` beside it. `mcp/instructions.py::ScopedInstructions` passes `delivery.via` and wraps
the whole build: on any failure it logs a redacted traceback and returns `footer()`.
`SkillServing` adds kubed-mcp's `AdvertiseLegacyExtensions` for the Skills id the first time a set
it serves has a skill, which is when kubed-mcp registers the Skills provider on discover.
`app.py`'s unconditional one goes.

**Tech Stack:** Python ≥3.11, `kubed-mcp>=0.3.0,<0.4` (FastMCP through it), pytest +
pytest-asyncio, uvicorn.

**Spec:** this plan's Design section and #87's notes in `.issue/issues.md`. These living spec rows
change in the tasks that own them:
- [scoping-and-instructions.md](../specs/scoping-and-instructions.md): SCP-2, SCP-3, INS-2,
  INS-14, INS-15 and INS-19; new INS-20 to INS-23.
- [skills.md](../specs/skills.md): SKL-44.
- [agents.md](../specs/agents.md): AGT-1.
- [http-and-tools.md](../specs/http-and-tools.md): HTTP-26, HTTP-27 and HTTP-42.
- [prompts.md](../specs/prompts.md): new PRM-64.

kubed-mcp's rows are cited from its wiki at `v0.3.0`: DLV-9, DLV-11 and DLV-16.

## Design

### Checked against kubed-mcp 0.3.0 (its source at `v0.3.0`, read for this plan)

- **`Resolved`** (`delivery.py`) is a frozen dataclass with these fields:
  `resources: Literal["on", "off"]`, `listed: frozenset[str]`,
  `via: Literal["mcp", "extension", "local"]`, `prefix: str | None` and
  `extensions: frozenset[str] | None = None` (None when the request does not say).
- **The hook** (`_handshake.py::_written`). A raise is logged with `log.exception("instructions
  failed: the built instructions stay")` on `kubed.mcp.delivery`, and the built instructions stay.
  A None return keeps them silently. A non-string is logged at error and also keeps them. Any
  string, `""` included, is written as `prefixed(text, resolved.prefix)` and replaces them
  (`_describe` checks `is not None`). So `""` is a valid answer, and INS-22 relies on it.
- **Agents on legacy `initialize`** (`plugins.py::Plugins._providers`). The first time a set with a
  served plugin is served, kubed-mcp adds the Agents extension and
  `AdvertiseLegacyExtensions({agents id: SETTINGS})`, once. So Agents already agrees on both
  handshakes, and kb changes nothing for it.
- **Skills on `server/discover`** (same function). The provider is registered once, when
  `any(each.catalogue for each in served)` first holds, and it is never removed. Legacy
  `initialize` gets nothing from kubed-mcp for Skills. kb's `app.py` adds
  `AdvertiseLegacyExtensions({skills id: …})` unconditionally, which is K3's parked N17: legacy
  says Skills when discover does not.
- **`AdvertiseLegacyExtensions(declared: Mapping[str, dict])`** (`protocol.py`) takes a fixed
  mapping, merges it into `initialize`'s `capabilities.extensions`, and leaves `server/discover`
  alone.

Not read, and pinned by Task 0 instead:
- the names kubed-mcp reads Via under with `header_prefix="Kb"` (`Kb-Via`, `X-MCP-Via`, `?via=`);
- what an unknown value resolves to;
- whether a value matches case-insensitively;
- whether `prompts/list` drops plugin prompts under `extension` and `local` (DLV-9).

### Decisions

- **D1. The three shapes** (Dr K's ruling 1), in `build_instructions(…, via=…)`:

  | Via | Description | `notes` | `Skills:` pointer + INS-19 lines | Names (INS-11) | Footer |
  |---|---|---|---|---|---|
  | `mcp` | yes | yes | yes | per INS-11 | INS-15 |
  | `extension` | yes | yes | yes | never | INS-21 |
  | `local` | yes | yes | no | never | none |

  INS-6 (which libraries), INS-7 (order) and INS-13 (`[<library>]` headings when several are
  selected) hold in every mode.
- **D2. The extension footer** (INS-21) is fixed whatever `resources` says, and uses the notes'
  draft wording: `Skills arrive through the Skills extension; each reads at
  skill://<library>/<path>/SKILL.md, and its _manifest lists the other files it ships.` kubed-mcp
  prefixes it like any other text.
- **D3. `local` with nothing to say is empty.** With no library selected, the text is `""`
  (INS-22). A library whose description and notes are both empty has no section under `local`, and
  no heading either: a bare `[lib]` tells a client nothing. So a `local` text can be `""` with
  libraries selected. This corner was not ruled on (see the reply).
- **D4. `fn` never fails** (INS-23, the parent's addition). `ScopedInstructions.__call__` puts
  everything inside one `try`: the snapshot read, `requested_scope()`, `folders` and the build. On
  `Exception` it logs `"instructions failed; the footer stands in\n%s"` at ERROR on
  `kubed.mcp_kb.mcp.instructions`, with the formatted traceback passed through
  `config.redact(trace, secrets())`, as `/reindex` does. It then returns
  `footer(resources=…, via=…)`: the mode's footer, or `""` under `local`. So kubed-mcp's own
  `log.exception` never fires for kb, and the client never gets the built text silently.
  `ScopedInstructions(snapshot, secrets)` takes `config.secrets` as its second argument, which is
  required.
- **D5. Legacy `initialize` follows discover for Skills (N17).** The `AdvertiseLegacyExtensions`
  line and the `SkillsExtension` import leave `app.py`. `SkillServing._publish`, after
  `self._mcp.serve(staged)` returns, calls `self._advertise_skills(added)`. The first time any
  served plugin in `added` serves a skill, that adds
  `AdvertiseLegacyExtensions({EXTENSION_ID: SkillsExtension().settings()})` to `self._mcp`, once
  per `SkillServing`. That is the same moment, the same condition and the same stickiness as
  kubed-mcp's discover registration. A refresh that drops every skill leaves both handshakes
  declaring Skills (SKL-44's "for the life of the process"). The condition reads the public
  per-plugin skills field of kubed-mcp's `Served` that `_narrowed` already reads. The test that
  compares both handshakes decides whether it is right, not this sentence. When quick-mcp mirrors
  Skills onto legacy itself, as it does for Agents, kb's call goes. That would be a quick-mcp row,
  and raising it is Dr K's call.
- **D6. `via` is a plain string in `catalogue/`.** `catalogue/instructions.py` defines
  `Via = Literal["mcp", "extension", "local"]` and imports nothing from kubed-mcp
  (`tests/test_boundaries.py`). `ScopedInstructions` hands it `delivery.via` as it is.
- **D7. The wiki names Via.** `mcp/tools.py` gains `VIA_PARAM = "via"` and `VIA_HEADER =
  "kb-via"`, for the generator and `tests/test_wiki.py` only, beside `LISTED_*`.
- **D8. The prompts that Via hides are kubed-mcp's** (DLV-9). kb adds no filter. PRM-64 records
  the rule if Task 0 finds it true of 0.3. If 0.3 does not hide them, PRM-64 is written
  *(proposed)* and the gap goes to Dr K.

### Named changes, for QA's dump

- **V1.** `Kb-Via: extension` (or `X-MCP-Via`, or `?via=`) gives INS-20's `extension` shape and the
  INS-21 footer. This is an addition: no client sends Via today.
- **V2.** `Kb-Via: local` gives descriptions and notes only, and `""` when there is nothing to say.
  This is an addition.
- **V3.** Legacy `initialize` declares Skills only once a skill is served, as discover does (N17).
  It shows only on a deployment with no served skill, so it does not show in the ten-scope dump.
- **V4.** Under `extension` and `local`, kubed-mcp's presets list no `SKILL.md` rows (DLV-9; #86's
  check) and no plugin prompts in `prompts/list` (if Task 0 confirms it). Both are kubed-mcp's,
  named here for the dump. This is an addition.
- **V5.** `_meta["io.kubed/delivery"].via` echoes the mode sent (HTTP-42, present since #92).

Under no Via, or `mcp`, the dump is byte-identical to `issue-80` before this PR (Task 1's golden).

## Global Constraints

- Pin `kubed-mcp>=0.3.0,<0.4`, as `issue-80` has. kb imports `kubed.mcp*` only, never `fastmcp`,
  `mcp` or `mcp_types`, outside tests. `catalogue/` imports no FastMCP.
- kb never imports a private kubed-mcp name. A missing public name is a quick-mcp row for Dr K.
- Footer copy is exact:
  - Resources: `Read a listed skill at skill://<library>/<path>/SKILL.md; read its _manifest in
    place of SKILL.md for the other files it ships.`
  - Tools: `Read these with read_resource.`
  - Extension: `Skills arrive through the Skills extension; each reads at
    skill://<library>/<path>/SKILL.md, and its _manifest lists the other files it ships.`
- kb's text is unprefixed. kubed-mcp writes the prefix (DLV-11).
- A credential never reaches a log: every traceback kb logs goes through
  `config.redact(…, config.secrets())`.
- Spec IDs are stable, and no number is reused. New rows are INS-20 to INS-23 and PRM-64. Spec
  files hold statements only: no dates, issue numbers or "used to".
- Changelog: one short line under `[Unreleased]` → `### Added`. No line for N17. It is a
  correction to a handshake no released client relies on, and the epic's PR #95 carries the
  family's lines.
- The wiki change goes on the wiki's `issue-87` branch, never `master`. Generated pages come from
  `python scripts/generate_wiki.py` only. Commits are signed (`git commit -S`).
- Markers: in-process tests are `@pytest.mark.unit`, and uvicorn ones `@pytest.mark.integration`.
- Every task passes from the repository root, with the `wiki/` submodule checked out:
  `ruff check . && pytest && python scripts/generate_wiki.py --check`.
- Do not weaken an assertion to make it pass. A failing test the Design does not explain is a
  finding: stop and report it with the output.

## Review Focus

1. **A refused scope that sends Via.** `Kb-Library: nope` with each of `mcp`, `extension` and
   `local` still fails `initialize` and `server/discover` with SCP-31's message (INS-5), and no
   instructions are written. Task 2, `test_a_refused_scope_fails_under_every_via`.
2. **`extension` behind the gateway.** With `Kb-Resource-Prefix: kb+`, the pointer, the INS-19
   lines and the INS-21 footer are each prefixed once, with no `kb+kb+`. Task 2,
   `test_extension_text_carries_the_prefix_once`.
3. **`local` for a library with neither description nor notes.** No bare `[lib]` heading. One such
   library alone gives `""`, and beside a described one only the described section is left. Task 1,
   `test_local_drops_a_library_with_nothing_to_say`.
4. **A build that fails under `local`.** The answer is `""`, not kubed-mcp's built text, and the
   ERROR line is logged. Task 2, `test_a_failing_build_logs_and_answers_the_footer`, parametrised
   over the three modes.
5. **The first skill arriving at a refresh.** A boot with no skill declares Skills on neither
   handshake. After a refresh brings one, both declare it. After a refresh that drops it again,
   both still declare it. Task 3, `test_a_refresh_moves_both_handshakes_alike`.

---

### Task 0: What kubed-mcp 0.3 does with Via

These are go/no-go facts about kubed-mcp, read through kb's served app. They describe 0.3.x and
are expected to pass at once. A failure is a finding, not a bug to fix:
- **Via is not read under the `Kb` names, or an unknown value fails the handshake:** stop and
  report to Dr K. kb adds no read of its own.
- **Plugin prompts are still listed under `extension` or `local`:** go on. Write PRM-64 as
  *(proposed)* in Task 2, and name the gap in the PR body for Dr K (D8).

**Files:**
- Test: `tests/test_instructions.py` (new section `# -- kubed-mcp's Via, as pinned`)

**Interfaces:**
- Consumes: `served(kb)`, `ERAS` (this file); `tests.test_server.delivery(client, mode)` and
  `DELIVERY_META`; `tests.test_plugin_serving.market`; `_three(tmp_path)` (this file, a library
  with prompts).
- Produces: nothing new for later tasks. The facts are recorded in this plan's History if any
  differs.

- [ ] **Step 1: Write the pinning tests**

```python
VIA_INPUTS = [
    ({"Kb-Via": "local"}, "", "local"),
    ({"X-MCP-Via": "extension"}, "", "extension"),
    ({}, "?via=local", "local"),
    ({"Kb-Via": "extension", "X-MCP-Via": "local"}, "", "extension"),  # Kb- first (DLV-16)
    ({"Kb-Via": "nonsense"}, "", "mcp"),
    ({}, "", "mcp"),
]

@pytest.mark.integration
@ERAS
@pytest.mark.parametrize(("headers", "query", "via"), VIA_INPUTS)
async def test_via_is_read_under_kb_names(tmp_path, mode, headers, query, via):
    # served(KnowledgeBase(_three(tmp_path), …)); connect in `mode` with `headers`
    # to url + query; assert (await delivery(client, mode))["via"] == via

@pytest.mark.integration
@pytest.mark.parametrize("via", ["extension", "local"])
async def test_via_presets_list_no_plugin_prompts(tmp_path, via):
    # with Kb-Via: via, [p.name for p in await client.list_prompts()] == []
    # and with no Via, the same server lists ["lib_hello", "lib_top"]
```

Also record the case question, without asserting: run `{"Kb-Via": "Local"}` once and write what
`via` resolved to in the PR body. kb does not depend on it.

- [ ] **Step 2: Run them**

Run: `pytest tests/test_instructions.py -k "via_is_read or via_presets" -v`
Expected: PASS. On a failure, follow the go/no-go rules above.

- [ ] **Step 3: Commit**

```bash
git add tests/test_instructions.py
git commit -S -m "test: how kubed-mcp 0.3 reads Via and what its presets list (#87)"
```

### Task 1: The three shapes, as text

**Files:**
- Modify: `kubed/mcp_kb/catalogue/instructions.py`
- Modify: `docs/superpowers/specs/scoping-and-instructions.md` (INS-14, INS-15 and INS-19; new
  INS-20, INS-21 and INS-22)
- Test: `tests/test_instructions.py`

**Interfaces:**
- Produces:
  - `Via = Literal["mcp", "extension", "local"]`;
  - `EXTENSION_FOOTER: str` (D2's copy);
  - `footer(*, resources: bool, via: Via = "mcp") -> str`;
  - `build_instructions(catalogue, scope, *, resources: bool, skills_extension: bool,
    folders: Mapping[str, Folders] | None = None, via: Via = "mcp") -> str`.

  All four are in `kubed/mcp_kb/catalogue/instructions.py`.

- [ ] **Step 1: Capture the `mcp` golden before touching code**

On the branch as it is, add `test_mcp_text_is_unchanged` (integration, `ERAS`, over the
`server_url` fixture). For each case it connects and asserts the text equals a literal in
`MCP_TEXTS`. Capture the literals by running the current server, and paste them in as written.

The cases:
- unscoped;
- `Kb-Library: flatsource`;
- `Kb-Library: deepsource`;
- `Kb-Tag: flat`;
- `?tag=flat&tag=deep`;
- `X-MCP-Resources: off`;
- `Kb-Library: flatsource` with the Skills extension declared.

Each case runs three ways:
- as is;
- with `Kb-Via: mcp`;
- with `Kb-Resource-Prefix: kb+`, where the expected text is `prefixed(literal, "kb+")`.

Run: `pytest tests/test_instructions.py::test_mcp_text_is_unchanged -v`
Expected: PASS on the unchanged code. It must still pass after every later task.

- [ ] **Step 2: Write the failing unit tests**

Use `_catalogue`, `_build(…, via=…)` and `Folders` as in this file:

```python
def test_extension_keeps_pointer_and_lines_but_never_names(tmp_path):
    cat = _catalogue(tmp_path, {LibraryText("lib", "L.", "N."): ["x"]})
    folders = {"lib": Folders(prompts=("lib",), agents=("lib/b",))}
    assert _build(cat, folders=folders, via="extension") == (
        "L.\nN.\nSkills: skill://lib/_index.md\nPrompts: prompts://lib/_index.md\n"
        "Agents: agents://lib/b/_index.md\n\n" + EXTENSION_FOOTER
    )

def test_extension_footer_ignores_resources(tmp_path):
    # _build(cat, resources=False, via="extension").endswith(EXTENSION_FOOTER)

def test_local_is_description_and_notes_only(tmp_path):
    # two libraries a ("A.", "N."), b ("B."), folders for both:
    # == "[a]\nA.\nN.\n\n[b]\nB."   (no pointer, no Prompts/Agents, no footer)

def test_local_drops_a_library_with_nothing_to_say(tmp_path):
    # LibraryText("bare") alone -> ""
    # LibraryText("bare") beside LibraryText("a", "A.") -> "[a]\nA."

def test_local_with_nothing_selected_is_empty(tmp_path):
    # _build(cat, Scope(library="absent"), via="local") == ""
    # and via="extension" == EXTENSION_FOOTER (INS-14 holds there)

def test_footer_per_mode():
    # footer(resources=True) == RES_FOOTER; footer(resources=False) == TOOLS_FOOTER
    # footer(resources=True/False, via="extension") == EXTENSION_FOOTER
    # footer(resources=True/False, via="local") == ""

def test_via_mcp_is_the_default(tmp_path):
    # for scope in (EVERYTHING, Scope(library="a")), resources/ext in both values:
    # _build(..., via="mcp") == _build(...) without via
```

Extend `test_the_text_is_built_unprefixed` to loop over all three `via` values too.

- [ ] **Step 3: Run them to see them fail**

Run: `pytest tests/test_instructions.py -m unit -v`
Expected: FAIL, because `build_instructions` takes no `via`, and `EXTENSION_FOOTER` and `footer`
are undefined.

- [ ] **Step 4: Implement**

In `catalogue/instructions.py`, add `Via`, `EXTENSION_FOOTER` and `footer`.
`build_instructions` then follows D1 and D3:
- names only when `via == "mcp"` and INS-11 holds;
- `_section` takes the mode and stops after the notes under `local`;
- under `local`, an empty section is skipped, heading included;
- the result is `"\n\n".join(sections + [footer(...)] if footer(...) else sections)`.

Update the module docstring: three inputs (resources, the Skills extension, Via), not two flags.

- [ ] **Step 5: Write the spec rows**

In `scoping-and-instructions.md`:
- INS-14: "With no library selected, the text is the footer alone" holds under `mcp` and
  `extension`. Point to INS-22 for `local`.
- INS-15: the table is the `mcp` footer, and INS-21 gives `extension`'s.
- INS-19: "written in both modes" becomes "written under `mcp` and `extension` (INS-20)".
- Add INS-20 (D1's table, with the sentence that INS-6, INS-7 and INS-13 hold in every mode).
- Add INS-21 (D2, with the exact copy).
- Add INS-22 (D3, both halves).

Add an example block after INS-18 for `extension` over two libraries.

- [ ] **Step 6: Run the checks**

Run: `ruff check . && pytest tests/test_instructions.py tests/test_boundaries.py -v`
Expected: PASS, `test_mcp_text_is_unchanged` included.

- [ ] **Step 7: Commit**

```bash
git add kubed/mcp_kb/catalogue/instructions.py tests/test_instructions.py docs/superpowers/specs/scoping-and-instructions.md
git commit -S -m "feat: the instructions text in each Via mode (#87)"
```

### Task 2: The hook reads Via and never fails

**Files:**
- Modify: `kubed/mcp_kb/mcp/instructions.py`
- Modify: `kubed/mcp_kb/app.py:94-96`
- Modify: `docs/superpowers/specs/scoping-and-instructions.md` (SCP-2, SCP-3 and INS-2; new
  INS-23)
- Modify: `docs/superpowers/specs/http-and-tools.md` (HTTP-26 and HTTP-42)
- Modify: `docs/superpowers/specs/prompts.md` (new PRM-64)
- Test: `tests/test_instructions.py`

**Interfaces:**
- Consumes: `build_instructions(…, via=)`, `footer(*, resources, via)` and `Via` (Task 1);
  `config.redact(text, secrets)`; `Config.secrets() -> list[str]`.
- Produces: `ScopedInstructions(snapshot: Callable[[], Snapshot], secrets: Callable[[], list[str]])`,
  with `__call__(self, delivery: Resolved) -> str`, which never raises. `create_app` builds it as
  `ScopedInstructions(serving.served_snapshot, config.secrets)`.

- [ ] **Step 1: Write the failing tests**

Unit, extending `test_the_fn_builds_from_the_resolution`:
- construct with `secrets=lambda: []`;
- `SimpleNamespace(…, via="extension")` ends with `EXTENSION_FOOTER` and has no `Skills (`;
- `via="local"` gives `""` for a library with no description.

Update `test_a_refresh_between_the_pin_and_the_instructions` to the two-argument constructor,
with `via="mcp"` on its namespace.

```python
@pytest.mark.unit
@pytest.mark.parametrize(("via", "resources", "expected"), [
    ("mcp", "on", RES_FOOTER), ("mcp", "off", TOOLS_FOOTER),
    ("extension", "off", EXTENSION_FOOTER), ("local", "on", ""),
])
def test_a_failing_build_logs_and_answers_the_footer(
    tmp_path, monkeypatch, caplog, via, resources, expected
):
    secret = "s3cret-token"
    def boom(*args, **kwargs):
        raise RuntimeError(f"broke on {secret} at https://user:pw@host/x")
    monkeypatch.setattr("kubed.mcp_kb.mcp.instructions.build_instructions", boom)
    fn = ScopedInstructions(lambda: SimpleNamespace(catalogue=None, folders=lambda s: {}),
                            lambda: [secret])
    got = fn(SimpleNamespace(resources=resources, extensions=None, prefix=None, via=via))
    assert got == expected
    [record] = [r for r in caplog.records if r.name == "kubed.mcp_kb.mcp.instructions"]
    assert record.levelname == "ERROR"
    assert "Traceback" in record.getMessage() and "RuntimeError" in record.getMessage()
    assert secret not in record.getMessage() and "user:pw" not in record.getMessage()

@pytest.mark.unit
def test_a_failing_snapshot_read_is_caught_too(caplog):
    # snapshot callable raises -> answer is footer(resources=True), ERROR logged
```

Integration (`ERAS`, `served(KnowledgeBase(_three(tmp_path), …))`):

```python
async def test_each_via_on_both_handshakes(tmp_path, mode):
    # mcp: Prompts/Agents lines present, footer RES_FOOTER
    # extension: _pointers(text) == the mcp ones; text ends with EXTENSION_FOOTER;
    #            with ?library=lib no "Skills (" form, even undeclared
    # local: _pointers(text) == [], no "Skills:" line, no footer
    # each via sent as Kb-Via, X-MCP-Via and ?via= gives the same text

async def test_extension_text_carries_the_prefix_once(tmp_path, mode):
    # Kb-Via: extension + Kb-Resource-Prefix: kb+ ->
    # "Skills: kb+skill://lib/_index.md", "Prompts: kb+prompts://lib/_index.md" in lines,
    # last line == prefixed(EXTENSION_FOOTER, "kb+"), "kb+kb+" not in text

async def test_local_with_nothing_to_say_is_empty(tmp_path, mode):
    # make_config() (nothing served), Kb-Via: local -> not text

async def test_a_refused_scope_fails_under_every_via(server_url, mode):
    # for via in mcp/extension/local: Kb-Library: nope + Kb-Via: via
    # -> pytest.raises(Exception, match="no such library")

async def test_via_follows_a_refresh(tmp_path, mode):
    # as test_refresh_reaches_a_new_connection, with Kb-Via: extension and local
```

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_instructions.py -k "via or failing" -v`
Expected: FAIL. The constructor takes one argument, `via` is not passed, and the build is not
caught.

- [ ] **Step 3: Implement `ScopedInstructions`**

`__call__` follows D4: one `try` around reading the snapshot, `requested_scope()`, `folders` and
`build_instructions(…, via=delivery.via)`. In the `except Exception` branch:
- compute `trace = "".join(traceback.format_exception(exc))`;
- call `log.error("instructions failed; the footer stands in\n%s", redact(trace, self._secrets()))`;
- return `footer(resources=delivery.resources == "on", via=delivery.via)`.

Add `log = logging.getLogger(__name__)`. Update the module docstring with the mode and the
never-fails rule. In `app.py`, pass `config.secrets`.

- [ ] **Step 4: Write the spec rows**

- SCP-2: add a Via row to the table (`Kb-Via`, `via`, `X-MCP-Via`, —).
- SCP-3: name Via among kubed-mcp's inputs, read with the `Kb` prefix (DLV-16). Its values are
  `mcp` (the default), `extension` and `local`. Write what an unknown value resolves to as Task 0
  found it.
- INS-2: the text is built from the served catalogue, the request's scope and kubed-mcp's
  resolution for the request (`resources`, `via` and `extensions`). The prefix is INS-16's.
- Add INS-23: building the text never fails a handshake. On a failure, the traceback is logged at
  ERROR with credentials masked, and the text is the mode's footer (INS-15 or INS-21), or empty
  under `local`.
- HTTP-26: the instructions follow the Via mode (INS-20).
- HTTP-42: the echo's `via` is the mode the instructions were written for.
- PRM-64: under Via `extension` or `local`, `prompts/list` lists no plugin prompt and `prompts/get`
  still serves one (DLV-9). Mark it *(proposed)* if Task 0 found otherwise.

- [ ] **Step 5: Run the checks**

Run: `ruff check . && pytest tests/test_instructions.py tests/test_addressing_http.py tests/test_server.py -v`
Expected: PASS, `test_mcp_text_is_unchanged` included.

- [ ] **Step 6: Commit**

```bash
git add kubed/mcp_kb/mcp/instructions.py kubed/mcp_kb/app.py tests/test_instructions.py docs/superpowers/specs/
git commit -S -m "feat: the instructions follow X-MCP-Via, and a failed build answers the footer (#87)"
```

### Task 3: Legacy `initialize` advertises what discover does (N17)

**Files:**
- Modify: `kubed/mcp_kb/mcp/skills.py` (`SkillServing.__init__` and `_publish` after
  `self._mcp.serve(staged)`; new `_advertise_skills`)
- Modify: `kubed/mcp_kb/app.py:19-20,87-93` (drop the import and the middleware)
- Modify: `docs/superpowers/specs/skills.md` (SKL-44), `agents.md` (AGT-1) and `http-and-tools.md`
  (HTTP-27)
- Test: `tests/test_skills_extension.py`

**Interfaces:**
- Consumes: `kubed.mcp.protocol.AdvertiseLegacyExtensions`, `kubed.mcp.skills.SkillsExtension`,
  and `EXTENSION_ID` from `mcp/request.py`.
- Produces: `SkillServing._advertise_skills(self, added: Sequence[tuple[Library, Plugin, Served]]) -> None`,
  which is idempotent per instance (`self._skills_advertised: bool`).

- [ ] **Step 1: Write the failing tests**

```python
async def _extensions(server, mode):
    async with Client(server_of(server), mode=mode) as client:
        return dict(client.session.server_capabilities.extensions or {})

CONFIGS = ["skills", "prompts-only", "agents-only", "nothing"]  # built with market()/make_config()

@pytest.mark.unit
@pytest.mark.parametrize("config", CONFIGS)
async def test_both_handshakes_advertise_the_same_extensions(tmp_path, config):
    kb = KnowledgeBase(<config>, tmp_path / "cache")
    legacy, current = await _extensions(kb, "legacy"), await _extensions(kb, "auto")
    assert legacy == current
    assert (EXTENSION_ID in legacy) == (config == "skills")
    assert (AGENTS_EXTENSION_ID in legacy) == (config != "nothing")

@pytest.mark.unit
async def test_a_refresh_moves_both_handshakes_alike(tmp_path):
    # boot prompts-only: Skills on neither; add skills/x/SKILL.md, kb.refresh(force=True):
    # Skills on both ({"directoryRead": True}); remove it, refresh: still on both
```

The agents-only config is a plugin with `agents/helper.md` and no `skills/`. The "nothing" config
is `make_config()`.

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_skills_extension.py -k "handshakes" -v`
Expected: FAIL for prompts-only, agents-only and nothing, where legacy has Skills and discover
does not.

- [ ] **Step 3: Implement**

`_advertise_skills` follows D5. Call it only after `serve` returns, so a `serve` that raises
advertises nothing. Delete the `AdvertiseLegacyExtensions` block, its comment and the two imports
from `app.py`. Search the tests for anything that relied on legacy declaring Skills with none
served, and fix them to the new rows. A test that asserts the old behaviour is updated, and named
in the PR body.

- [ ] **Step 4: Write the spec rows**

- SKL-44: "declares it on `server/discover` and on legacy `initialize` alike, once a plugin with a
  skill is served", then the life-of-the-process clause. "Legacy `initialize` declares it all the
  same" is removed.
- AGT-1 and HTTP-27: "on both handshakes alike", with AGT-1's wording otherwise unchanged.

- [ ] **Step 5: Run the checks**

Run: `ruff check . && pytest tests/test_skills_extension.py tests/test_agents_extension.py tests/test_server.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add kubed/mcp_kb/mcp/skills.py kubed/mcp_kb/app.py tests/ docs/superpowers/specs/
git commit -S -m "fix: legacy initialize declares Skills only once a skill is served (#87)"
```

### Task 4: Via in the manual, AGENTS.md and the changelog

**Files:**
- Modify: `kubed/mcp_kb/mcp/tools.py` (`VIA_PARAM` and `VIA_HEADER`, D7)
- Modify: `tests/test_wiki.py::test_installing_documents_every_url_parameter_and_header`
- Modify: `wiki/Installing.md`: a `?via=<mode>` row beside `?listed=`, reading `` `Kb-Via` (or
  `X-MCP-Via`) | What the instructions point at: `mcp` (the default), `extension` or `local` ``
- Modify: `wiki/Scoping.md` (the section on what a client sees when it connects, and the settings
  table at line 220: a Via row)
- Modify: `AGENTS.md` (the `mcp/instructions.py` layout row; the "Both `server/discover` and legacy
  `initialize` advertise the Skills extension" sentence, which becomes "once a skill is served,
  both alike")
- Modify: `CHANGELOG.md` (`[Unreleased]` → `### Added`)

**Interfaces:**
- Consumes: Tasks 1 to 3 as built.

- [ ] **Step 1: Write the failing test**

Add `tools.VIA_PARAM` to `parameters`, and `tools.VIA_HEADER` and `"x-mcp-via"` to `headers`, in
`test_installing_documents_every_url_parameter_and_header`.

- [ ] **Step 2: Run it to see it fail**

Run: `pytest tests/test_wiki.py -v`
Expected: FAIL. `VIA_PARAM` is undefined until it is added, and then `?via= is missing from
Installing.md`.

- [ ] **Step 3: Write the names, the pages and the lines**

Add the constants to `tools.py`, then:
- **Installing.md:** the row above.
- **Scoping.md:** the three shapes in prose, with an `extension` example, and the rule that a
  `local` client gets descriptions and notes only.
- **AGENTS.md:** the two places above.
- **CHANGELOG:** `- Send \`X-MCP-Via: extension\` or \`local\` (or \`?via=\`) and the
  instructions point at where your client gets its skills.`

Regenerate with `python scripts/generate_wiki.py`, and commit the wiki on its `issue-87` branch.

- [ ] **Step 4: Run every check**

Run: `ruff check . && pytest && python scripts/generate_wiki.py --check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add kubed/mcp_kb/mcp/tools.py tests/test_wiki.py AGENTS.md CHANGELOG.md wiki
git commit -S -m "docs: X-MCP-Via in the manual, AGENTS.md and the changelog (#87)"
```
