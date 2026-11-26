# prompts:// and agents:// for Every Library Implementation Plan

> **History.** Proposed for #85 (PR #104, into `issue-80`). It follows K3 (#79, PR #89), the gateway
> prefix (#81, PR #93), the `_publish` race fix (#94, PR #96), K4 (#82, PR #97), K5 (#83, PR #100),
> the kubed-mcp 0.3.0 pin (#92, PR #99) and K6 (#84, PR #102). The spec is #85's notes in
> `.issue/issues.md`, with Dr K's rulings of 2026-11-24 05:58 (ruling (a), the pointer lines) and the
> parent's messages of 2026-11-25 and 2026-11-26. The design is below, and there is no separate
> design file. The branch had no draft spec.
>
> **Approved 2026-11-26** (spec), with the pin at `kubed-mcp>=0.3.0,<0.4`. One point in the notes
> is settled differently here, because kubed-mcp 0.3.0 does it differently. A library's
> `prompts://<library>/_index.md` exists only when the library's **main plugin** serves a prompt in
> the request's scope. When only its other plugins serve one, the folder is not there. D2 says
> where the pointer goes then, as ruling (a) asked.
>
> **Task 0 ran 2026-11-26**, and D2's fallback stands. Against 0.3.0, `prompts://lib/_index.md`
> and `agents://lib/_index.md` are `NotFoundError` when only `lib/sub` serves that kind. When
> `lib` serves one too, its index has the row `prompts://lib/sub: A folder of prompts in lib/sub`.
> In a place collision the manifest's first entry wins. kb lists entries in path order
> (`harvest.command_entries`), so `commands/prompts/x.md` (`lib_prompts_x`) beats `prompts/x.md`
> (`lib_x`). The skip lands in `Plugin.skipped` as `prompts://lib/prompts/x.md is already served
> by commands/prompts/x.md`. Dr K's approval of 01:23 adds a test to Task 1: a refresh that lands
> between the pin and the instructions. If the snapshot cannot be tied to the pinned build, the
> instructions read through `_reading()`.
>
> **Task 1 ran 2026-11-26, and D1 changed.** Neither `initialize` nor `server/discover` pins a build:
> `SkillServing.view` was called zero times on connect, in both modes. So no pinned build exists to
> tie `knowledge_base.snapshot` to, and by Dr K's rule the instructions read through `_reading()`.
> `ScopedInstructions` is handed the new `SkillServing.served_snapshot`, which returns
> `_reading()[0].snapshot`, not `lambda: knowledge_base.snapshot`. It gives the pinned state
> inside a request that pinned, otherwise the published one. `_published` is set before `serve()`,
> so it never names a generation the layer does not serve yet.
> `test_a_refresh_between_the_pin_and_the_instructions` holds this.
> Two of Task 2's AGENTS.md edits, the Agents-extension paragraph and the provider-getter note,
> moved into Task 1, so that no commit leaves the manual false.
> `tests/test_agents_extension.py::test_nothing_else_changes` now allows exactly the `Agents:` line.
>
> **Task 2 ran 2026-11-26, and the plan is complete.** The collision skip reaches `/health` as
> `skipped: [{"path": "prompts/x.md", "reason": "prompts://lib/prompts/x.md is already served by
> commands/prompts/x.md"}]`, so no assertion is xfail. The scope test reads a second library's
> addresses too, so the `?library=else` arm runs against a view that selects something. The
> whole-branch review found no Critical or Important issues. Its seven doc and test fixes landed with
> Task 2:
> - the changelog line no longer names only `<library>/_index.md`;
> - INS-19 cites SKL-58 and LIB-29, not SKL-45;
> - agents.md's opening names AGT-3;
> - SKL-8's lead no longer claims every address is `skill://`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use skill://superpowers/subagent-driven-development/SKILL.md (recommended) or skill://superpowers/executing-plans/SKILL.md to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a client's instructions name where each selected library's prompts and agents read
(`Prompts:` and `Agents:` lines, INS-19). The PR also proves that kubed-mcp's unlisted `prompts://`
and `agents://` resources follow kb's scope and the gateway prefix.

**Architecture:** kb builds no resource. kubed-mcp 0.3.0 already serves both schemes for every
plugin kb adds (PLUG-66 to PLUG-68): P6 from K4, AGT-18 from K5, and the mirror from N4.
kb's code change is two things:
- `Snapshot.folders(scope)` says which namespaces of each library serve the scope a prompt, and
  which serve it an agent;
- `build_instructions` writes one pointer line per kind from that.

Everything else is tests and spec.

**Tech Stack:** Python ≥3.11, `kubed-mcp>=0.3.0,<0.4` (FastMCP through it), pytest +
pytest-asyncio, uvicorn.

**Spec:** this plan's design section and #85's notes in `.issue/issues.md`. The living spec is
[scoping-and-instructions.md](../specs/scoping-and-instructions.md) (INS-10, new INS-19),
[prompts.md](../specs/prompts.md) (new PRM-63), [agents.md](../specs/agents.md) (the opening,
AGT-18, new AGT-19) and [skills.md](../specs/skills.md) (new SKL-61). kubed-mcp's rows are cited
from its wiki's `plugins` page at `v0.3.0`: PLUG-54 and PLUG-66 to PLUG-68.

## Design

### What is on the branch now, read in the code

- `catalogue/instructions.py::_section` writes the description, the notes and the one `Skills`
  pointer. `build_instructions(catalogue, scope, *, resources, skills_extension)` sees only a
  `Catalogue`, and a `Catalogue` holds no prompts or agents.
- `mcp/instructions.py::ScopedInstructions(catalogue)` is handed `create_app`'s `catalogue()`
  getter. It writes the prefix with `prefixed(text, prefix())` (GW-11), which already covers
  `prompts://` and `agents://` (G3).
- `Snapshot.prompts` holds `FilePrompt`s and `Snapshot.agents` holds `ServedAgent`s. Each carries
  `library` and `plugin` (kb's plugin id) and is kept to what kubed-mcp serves (the parity guard,
  K4 and K5). `visible_prompts(scope)` and `visible_agents(scope)` filter them as the view does.
  `Snapshot.libraries` and `Snapshot.plugins` give each library's plugin order and its `main`.
  `namespace_for(library, plugin)` is the namespace `SkillServing.publish` adds a plugin under.
- `tests/test_command_layer.py` already pins P6: `prompts://lib/top.md` reads and
  `prompts://lib/commands/top.md` misses. `tests/test_plugin_serving.py` reads
  `prompts://lib/a/hello.md` and `prompts://lib/b/prompts/x.md` through kb.
  `tests/test_agents.py::test_an_out_of_scope_agents_file_reads_as_absent` pins AGT-18's scope.

### Checked against kubed-mcp 0.3.0 (`kubed/mcp/plugins.py` at `v0.3.0`, and its wiki)

- **PLUG-68: folders.** Each proper prefix of a file's place, from depth 0, is a folder:
  `_folders_in` makes `<scheme>://<namespace>` and the folders below it. A namespace's folder
  becomes a row in the folder above it **only if that folder exists** (`if parent in children`).
  So `prompts://lib` is a folder only when the namespace `lib` itself, the main plugin, serves a
  prompt. Then `lib/<plugin>` appears in it as a folder row. kubed-mcp's own design page says it
  plainly: "Without a plugin under `kit` that serves a prompt, `prompts://kit` is no folder."
  Its test sketch reads `prompts://kit` as `Directory not found` when only `kit/tools` serves.
- **The index.** Every folder has `_index.md` and `_index.json`, rendered with the build.
  An `_index.md` row is `<uri>: <description>`. The folder is held to the view (PLUG-54), so an
  out-of-scope plugin adds no row and makes no folder.
- **The place collision.** Within one plugin, `_claim` keeps the first file at an address. A later
  file is skipped whole with `<address> is already served by <first path>`, so its prompt goes
  too. Across plugins, a prompt at an address an earlier plugin serves refuses the later plugin.
- The index text is rendered by `skills._index_of`, which was not read. Task 0 pins what it holds.

### Decisions

- **D1. The pointer data comes from the snapshot, not the catalogue.** `ScopedInstructions` takes
  a snapshot getter (`lambda: knowledge_base.snapshot`) and reads the snapshot once per answer.
  The catalogue and the folders therefore come from one generation. The instructions are not a
  build-time hook, so `_reading()` does not apply to them. That rule is for code that kubed-mcp
  calls while it builds (`view`, `rewrite`, `agent_meta`, `read_command`). The snapshot getter is
  as safe as the catalogue getter it replaces, because it reads the current snapshot on every
  call. The `Catalogue` transient and `resources.register(mcp, catalogue)` are unchanged.
- **D2. Where a pointer points.** For each kind, take the namespaces of the library's plugins that
  serve the request's scope at least one file of that kind, in the library's plugin order.
  - When the library's own namespace (its main plugin) is among them, the line names the
    library's index: `Prompts: prompts://<library>/_index.md`. That index lists the main plugin's
    files and a folder row for each other plugin that serves one.
  - Otherwise the line names each of those namespaces' indexes, joined by `, `:
    `Prompts: prompts://grafana/k6/_index.md, prompts://grafana/loki/_index.md`. This is ruling
    (a)'s "the folder that does". With several plugins there are several such folders.
  - A library with no main plugin (SKL-59) always takes the second form.

  `Agents:` follows the same rule. Every address named is one Task 1's HTTP test reads.
- **D3. The lines sit after the `Skills` pointer, `Prompts` first.** They are written in both
  modes (resources and tools: kubed-mcp's `read_resource` reads both schemes), with or without the
  Skills or Agents extension declared, and in the names form of INS-11 too. INS-6 is unchanged, so
  a library with prompts or agents in scope and no skill still has no section. #87 later decides
  which modes keep them.
- **D4. No kb workaround for the place collision.** It is K4's limit, already reported to
  quick-mcp (the `prompts://` place collision). The PR names it and tests what 0.3.0 does.
- **D5. Nothing is removed.** kb serves nothing by hand that these resources cover. An agent under
  an operator's `files:` glob stays a library file (AGT-3, LIB-33), and the plugin-root fallback
  still refuses agent files. Those tests stay green unchanged.

### Named changes, for QA's dump

- **R1.** A selected library whose in-scope plugins serve a prompt gains a `Prompts:` line after
  its `Skills` pointer, addressed by D2.
- **R2.** The same for agents: an `Agents:` line after it.
- **R3.** The dump adds reads of every `Prompts:` and `Agents:` address, and of one file under
  each, under all ten scopes, with and without `kb+`. These reads are additions. The resources
  themselves were already served before this PR (P6, AGT-18), so they are not a change.

Unchanged and only tested: P6, G3, N4 and N7.

## Global Constraints

- Pin `kubed-mcp>=0.3.0,<0.4`, as `issue-80` has. kb imports `kubed.mcp*` only, never `fastmcp`
  or `mcp`, outside tests.
- `catalogue/` imports no FastMCP (`tests/test_boundaries.py`).
- The instruction text is built unprefixed. The prefix is written once over it by
  `prefixed(text, prefix())` (GW-11).
- Spec IDs: INS-19 (INS-20 onward is #87's), PRM-63, AGT-19 and SKL-61 are new. No ID is reused.
- Pointer copy is exact: `Prompts: <scheme>://<namespace>/_index.md[, …]` and
  `Agents: <scheme>://<namespace>/_index.md[, …]`.
- The wiki change goes on the wiki's `issue-85` branch, never `master`. Commits are signed.
- Every task passes `ruff check .`, `pytest` and `python scripts/generate_wiki.py --check`.

## Review Focus

1. **A library whose main plugin serves no prompt and two other plugins do.** The pointer names
   both plugin folders and never `prompts://<library>/_index.md`. Task 1,
   `test_the_pointer_falls_back_to_each_plugin_folder`.
2. **A tag scope that admits only a non-main plugin, in a library whose main plugin has prompts.**
   The pointer for that request falls back to the plugin's folder, and every address it names
   reads. Task 1, `test_every_pointed_index_reads`.
3. **A library with no main plugin** (two marketplace entries, neither named like the library).
   It takes the second form. Task 1, `test_a_library_without_a_main_plugin_points_at_its_folders`.
4. **A plugin refused for a prompt name clash (LIB-29).** It contributes no folder, because its
   prompts are not in `snapshot.prompts`. Task 1, `test_a_refused_plugin_adds_no_folder`.
5. **A refresh that removes a library's last prompt.** A new connection gets no `Prompts:` line.
   Task 1, `test_a_refresh_drops_the_prompts_line`.

---

### Task 0: What kubed-mcp 0.3.0 serves at `prompts://` and `agents://`

The go/no-go for D2, against kubed-mcp alone, with no kb code. If `prompts://lib` turns out to be a
folder whenever any plugin under `lib` serves a prompt, D2 loses its fallback: the pointer is always
`<scheme>://<library>/_index.md`. Record that in this plan's History, simplify Task 1's rule, and
tell Dr K in the PR.

**Files:**
- Test: `tests/test_command_layer.py`, `tests/test_agent_layer.py`

**Interfaces:**
- Consumes: `QuickMCP`, `plugin_set()`, `PluginSet.add(folder, namespace=, manifest=)`,
  `serve`, `server.read_resource` (as the files already use them).
- Produces: the observed facts Task 1 and Task 2 rely on, written in each test's docstring.

- [x] **Step 1: Write the tests** (they describe 0.3.0 and are expected to pass at once; a failure
  is a finding, not a bug to fix)

`tests/test_command_layer.py`:

```python
async def test_the_namespace_folder_needs_a_prompt_of_its_own(tmp_path):
    # set A: "lib" serves commands/top.md, "lib/sub" serves commands/x.md
    index = await _text(a, "prompts://lib/_index.md")
    assert "prompts://lib/top.md: D." in index
    assert "prompts://lib/sub" in index                     # the folder row
    assert "prompts://lib/sub/x.md: D." in await _text(a, "prompts://lib/sub/_index.md")
    # set B: only "lib/sub" serves
    with pytest.raises(Exception) as miss:
        await b.server.read_resource("prompts://lib/_index.md")
    assert type(miss.value).__name__ == "NotFoundError"
    assert "prompts://lib/sub/x.md" in await _text(b, "prompts://lib/sub/_index.md")

async def test_two_commands_at_one_place(tmp_path):
    # one plugin at "lib", manifest commands ["commands", "prompts/x.md"],
    # files commands/prompts/x.md and prompts/x.md: both at prompts://lib/prompts/x.md
    names = [p.name for p in await mcp.server.list_prompts()]
    assert len({"lib_prompts_x", "lib_x"} & set(names)) == 1
    index = await _text(mcp, "prompts://lib/prompts/_index.md")
    assert index.count("prompts://lib/prompts/x.md") == 1
```

`tests/test_agent_layer.py`: `test_the_agents_namespace_folder_needs_an_agent_of_its_own`, the
first test above for `agents://`, with `agents/helper.md` at `lib` and `agents/other.md` at
`lib/sub`, built with that file's own plugin helper and manifest shape.

`_text(mcp, uri)` returns the first content's text. Each docstring records what was seen,
including which of the two colliding names 0.3.0 keeps.

- [x] **Step 2: Run them**

Run: `pytest tests/test_command_layer.py tests/test_agent_layer.py -v`
Expected: PASS. On a failure, stop and record the finding (see above).

- [x] **Step 3: Commit**

```bash
git add tests/test_command_layer.py tests/test_agent_layer.py
git commit -S -m "test: what kubed-mcp 0.3.0 serves at prompts:// and agents:// folders (#85)"
```

### Task 1: The `Prompts:` and `Agents:` pointer lines (INS-19)

**Files:**
- Modify: `kubed/mcp_kb/catalogue/snapshot.py` (`Folders`, `Snapshot.folders`)
- Modify: `kubed/mcp_kb/catalogue/instructions.py` (`kind_pointer`, `_section`, `build_instructions`)
- Modify: `kubed/mcp_kb/mcp/instructions.py` (`ScopedInstructions` takes a snapshot getter)
- Modify: `kubed/mcp_kb/app.py:95`
- Modify: `docs/superpowers/specs/scoping-and-instructions.md` (INS-10, new INS-19),
  `wiki/Scoping.md` ("What a client sees when it connects"), `CHANGELOG.md`
- Test: `tests/test_instructions.py`

**Interfaces:**
- Consumes: Task 0's facts. `namespace_for(library, plugin)`, `Snapshot.visible_prompts(scope)`,
  `Snapshot.visible_agents(scope)`, `Snapshot.libraries`, `Snapshot.plugins`.
- Produces:
  - `snapshot.Folders`, a frozen dataclass with `prompts: tuple[str, ...] = ()` and
    `agents: tuple[str, ...] = ()`: namespaces in library plugin order.
  - `Snapshot.folders(self, scope: Scope = EVERYTHING) -> dict[str, Folders]`, keyed by library
    name and holding only libraries with at least one namespace.
  - `instructions.kind_pointer(label: str, scheme: str, library: str, namespaces: Sequence[str]) -> str | None`.
  - `build_instructions(catalogue, scope, *, resources, skills_extension, folders: Mapping[str, Folders] | None = None) -> str`.
  - `ScopedInstructions(snapshot: Callable[[], Snapshot])`.

- [x] **Step 1: Write the failing unit tests** in `tests/test_instructions.py`, using the file's
  `_catalogue` and `_build` (`_build` gains a `folders=None` pass-through)

```python
def test_kind_pointer_names_the_library_index_when_the_main_plugin_serves():
    assert kind_pointer("Prompts", "prompts", "lib", ("lib", "lib/a")) == (
        "Prompts: prompts://lib/_index.md")

def test_the_pointer_falls_back_to_each_plugin_folder():
    assert kind_pointer("Agents", "agents", "lib", ("lib/a", "lib/b")) == (
        "Agents: agents://lib/a/_index.md, agents://lib/b/_index.md")
    assert kind_pointer("Agents", "agents", "lib", ()) is None

def test_prompt_and_agent_lines_follow_the_skills_pointer(tmp_path):
    text = LibraryText("lib", "L.", list_skills=False)
    cat = _catalogue(tmp_path, {text: ["x"]})
    folders = {"lib": Folders(prompts=("lib",), agents=("lib/a", "lib/b"))}
    assert _build(cat, folders=folders) == (
        "L.\nSkills: skill://lib/_index.md\nPrompts: prompts://lib/_index.md\n"
        "Agents: agents://lib/a/_index.md, agents://lib/b/_index.md\n\n" + RES_FOOTER)

def test_the_names_form_keeps_the_lines(tmp_path):
    cat = _catalogue(tmp_path, {LibraryText("lib"): ["x"]})
    out = _build(cat, folders={"lib": Folders(prompts=("lib",))})
    assert out.startswith("Skills (skill://lib/_index.md): x\nPrompts: prompts://lib/_index.md\n\n")

def test_each_section_gets_its_own_lines_and_an_unselected_library_none(tmp_path):
    a, b = LibraryText("a", "A."), LibraryText("b", "B.")
    cat = _catalogue(tmp_path, {a: ["x"], b: ["y"]})
    folders = {"b": Folders(agents=("b",)), "c": Folders(prompts=("c",))}
    assert _build(cat, folders=folders) == (
        "[a]\nA.\nSkills: skill://a/_index.md\n\n"
        "[b]\nB.\nSkills: skill://b/_index.md\nAgents: agents://b/_index.md\n\n" + RES_FOOTER)
    assert _build(cat, folders=folders, resources=False).endswith(
        "Agents: agents://b/_index.md\n\n" + TOOLS_FOOTER)

def test_the_lines_are_prefixed_once(tmp_path):
    cat = _catalogue(tmp_path, {LibraryText("lib", list_skills=False): ["x"]})
    out = prefixed(_build(cat, folders={"lib": Folders(prompts=("lib",), agents=("lib",))}), "kb+")
    assert "Prompts: kb+prompts://lib/_index.md" in out.splitlines()
    assert "Agents: kb+agents://lib/_index.md" in out.splitlines()
    assert "kb+kb+" not in prefixed(out, "kb+")
```

`test_a_missing_message_still_gets_instructions` changes to
`ScopedInstructions(lambda: SimpleNamespace(catalogue=cat, folders=lambda scope: {}))`, with the
same assertions.

- [x] **Step 2: Write the failing snapshot and HTTP tests** in `tests/test_instructions.py`

They use `market` from `tests/test_plugin_serving.py`, a library `lib` with the entries
`lib` (`./main`: `commands/top.md`, a skill), `a` (`./a`: `commands/hello.md`, a skill, tags `["t"]`)
and `b` (`./b`: `agents/helper.md`, a skill). They are served with this file's `served` and `told`.

```python
def test_folders_are_the_namespaces_serving_each_kind(tmp_path):
    kb = KnowledgeBase(_three(tmp_path), tmp_path / "cache")
    assert kb.snapshot.folders() == {"lib": Folders(prompts=("lib", "lib/a"), agents=("lib/b",))}
    assert kb.snapshot.folders(Scope.parse(tags="t")) == {"lib": Folders(prompts=("lib/a",))}
    assert kb.snapshot.folders(Scope.parse(library="else")) == {}

@ERAS
async def test_every_pointed_index_reads(tmp_path, mode):
    # for query in ("", "?tag=t"): told(url + query, mode); for every address on a
    # "Prompts:" or "Agents:" line, read_resource succeeds over the same URL;
    # unscoped: lines == ["Prompts: prompts://lib/_index.md", "Agents: agents://lib/b/_index.md"]
    # ?tag=t:   lines == ["Prompts: prompts://lib/a/_index.md"], and
    #           prompts://lib/_index.md fails as prompts://nope/_index.md does

async def test_a_library_without_a_main_plugin_points_at_its_folders(tmp_path):
    # market entries "a" and "c", both with commands, none named "lib":
    # the line is "Prompts: prompts://lib/a/_index.md, prompts://lib/c/_index.md"

async def test_a_refused_plugin_adds_no_folder(tmp_path):
    # entries "a" and "c" each ship commands/hello.md: "c" is refused (LIB-29, PRM-44);
    # kb.snapshot.folders()["lib"].prompts == ("lib/a",)

@ERAS
async def test_a_refresh_drops_the_prompts_line(tmp_path, mode):
    # serve _three; delete main/commands/top.md and a/commands/hello.md; kb.refresh(force=True);
    # a new connection's text has no line starting "Prompts:"

@ERAS
async def test_the_lines_carry_the_prefix(tmp_path, mode):
    # headers {"Kb-Resource-Prefix": "kb+"}: "Prompts: kb+prompts://lib/_index.md" and
    # "Agents: kb+agents://lib/b/_index.md" are lines of the text
```

`_three(tmp_path) -> Config` is a helper in the test file.

- [x] **Step 3: Run them to see them fail**

Run: `pytest tests/test_instructions.py -v`
Expected: FAIL with `ImportError` (`Folders`, `kind_pointer`) and, once those exist, on the
missing lines.

- [x] **Step 4: Implement**

- `snapshot.py`: `Folders` and `Snapshot.folders`. For each library in `self.libraries`, walk
  `library.plugins` in order. Keep `namespace_for(library, plugin)` for each plugin id that has a
  prompt in `visible_prompts(scope)` (matched on `library` and `plugin`), and the same for agents
  in `visible_agents(scope)`. Look up `Plugin` by id from `self.plugins`.
- `instructions.py`: `kind_pointer` follows D2, with each address written as
  `f"{scheme}://{namespace}/_index.md"`. `_section` takes the library's `Folders` and appends the
  `Prompts` line, then the `Agents` line, after the `Skills` line. `build_instructions` passes
  `(folders or {}).get(text.name, Folders())`.
- `mcp/instructions.py`: `_text` reads `snapshot = self._snapshot()` once and passes
  `snapshot.catalogue` and `snapshot.folders(scope)`, with one `requested_scope()` for both. Update
  the module docstring.
- `app.py`: `mcp.add_middleware(ScopedInstructions(lambda: knowledge_base.snapshot))`.

- [x] **Step 5: Run the tests to see them pass**

Run: `pytest tests/test_instructions.py tests/test_boundaries.py -v`
Expected: PASS.

- [x] **Step 6: Spec, wiki and changelog**

- INS-10: "The pointer names the library's index: `Skills: skill://<library>/_index.md`. INS-19
  adds the prompt and agent pointers after it."
- INS-19, after INS-13. Its content is:
  - After the pointer, a section has a `Prompts:` line when a prompt of the library is in the
    request's scope, then an `Agents:` line when an agent is. A prompt is in scope by SCP-27 and an
    agent by AGT-15, and only what the plugin layer serves counts (SKL-45).
  - Each line names `<scheme>://<library>/_index.md` when the library's main plugin (SKL-59) serves
    the scope one of that kind. Only then is that folder there (kubed-mcp's PLUG-68).
  - Otherwise the line names the `_index.md` of each plugin namespace that serves one, in the
    library's plugin order, joined by `, `.
  - The lines are written in both modes, whether or not the client declared an extension, and in
    the INS-11 form. INS-6 still decides which libraries have a section.
  - The prefix is written as INS-16 says.
  - Example:

    ```
    [grafana]
    Grafana, Loki and the rest of the LGTM stack.
    Skills: skill://grafana/_index.md
    Prompts: prompts://grafana/_index.md
    Agents: agents://grafana/k6/_index.md
    ```

  INS-17 and INS-18 stay: their libraries are shown without prompts or agents.
- `wiki/Scoping.md`, "What a client sees when it connects": one paragraph and the example above.
  Commit it on the wiki's `issue-85` branch, then bump the submodule pointer.
- `CHANGELOG.md`, `[Unreleased]` → `### Added`: `- A client's instructions now point at each
  library's prompts and agents, at prompts://<library>/_index.md and agents://<library>/_index.md.`

- [x] **Step 7: Run every check**

Run: `ruff check . && pytest && python scripts/generate_wiki.py --check`
Expected: all pass.

- [x] **Step 8: Commit**

```bash
git add kubed/mcp_kb/catalogue/snapshot.py kubed/mcp_kb/catalogue/instructions.py \
  kubed/mcp_kb/mcp/instructions.py kubed/mcp_kb/app.py tests/test_instructions.py \
  docs/superpowers/specs/scoping-and-instructions.md CHANGELOG.md wiki
git commit -S -m "feat: point the instructions at each library's prompts and agents (#85)"
```

### Task 2: Scope, prefix and the collision through kb, and the resource rows

These are tests only. The behaviour is kubed-mcp's and is already served; the tests pin it to kb's
view and prefix. If one fails, the finding goes to Dr K. kb grows no workaround (D4).

**Files:**
- Create: `tests/test_kinds_as_resources.py`
- Modify: `docs/superpowers/specs/prompts.md` (new PRM-63), `docs/superpowers/specs/agents.md`
  (the opening, AGT-18's pointer, new AGT-19), `docs/superpowers/specs/skills.md` (new SKL-61),
  `AGENTS.md`

**Interfaces:**
- Consumes: Task 1's `_three` fixture shape (copy it in the new file, or import it from
  `tests.test_instructions`). Also `serve_http`, `http_client` and `ext_request` from
  `tests.conftest`, and `market` from `tests.test_plugin_serving`.
- Produces: nothing later tasks use.

- [x] **Step 1: Write the tests**

```python
URIS = ["prompts://lib/_index.md", "prompts://lib/top.md", "prompts://lib/a/_index.md",
        "prompts://lib/a/hello.md", "agents://lib/b/_index.md", "agents://lib/b/helper.md"]

def test_every_scope_reads_an_addition_or_an_absence(tmp_path):
    # library "lib" (_three) plus "else" (one skill, one command)
    # unscoped: every URI reads -> baseline texts
    # for query in ("?library=lib", "?library=else", "?tag=t"), with and without
    #   {"Kb-Resource-Prefix": "kb+"} (the prefixed URI against the prefixed baseline):
    #   each URI either reads the baseline text, or fails with the same
    #   (code, message.replace(uri, "<uri>")) as its absent twin
    #   (".../_index.md" -> "prompts://nope/_index.md", a file -> "<folder>/nope.md")
    # ?library=else: every lib URI fails; ?tag=t: only the a/ prompts read

def test_the_prefixed_address_reads_through_both_paths(tmp_path):
    # headers {"Kb-Resource-Prefix": "kb+"}:
    #   resources/read "kb+prompts://lib/top.md" == resources/read "prompts://lib/top.md"
    #   "kb+prompts://lib/_index.md" body contains "kb+prompts://lib/top.md"
    #   "kb+agents://lib/b/helper.md" reads
    # headers + {"X-MCP-Resources": "off"}: call_tool("read_resource", {"uri": "kb+prompts://lib/top.md"})
    #   returns the same text

def test_two_files_at_one_prompts_place_serve_one(tmp_path):
    # a declared plugin, prompts: ["commands/**/*.md", "prompts/*.md"], with
    # commands/prompts/x.md and prompts/x.md, in library "lib"
    # exactly one of lib_prompts_x / lib_x in prompts/list, the one Task 0 recorded
    # [p.name for p in kb.snapshot.prompts] == that one name
    # kb.status["plugins"][id]["prompts"] == 1
    # prompts://lib/prompts/_index.md names prompts://lib/prompts/x.md once
    # the other file's path is under the plugin's "skipped" with "is already served by"
```

The `skipped` assertion is the one fact not checked against code. If 0.3.0's skip does not reach
`/health`, mark that assertion `xfail(strict=True)` with the reason "K4's place collision is not
reported (quick-mcp ask)", and name it in the PR.

- [x] **Step 2: Run them**

Run: `pytest tests/test_kinds_as_resources.py tests/test_agents.py -v`
Expected: PASS. The `test_agents.py` fallback tests (`test_the_library_fallback_refuses_an_agent_file`,
`test_the_skill_fallback_refuses_an_agent_file`) pass unchanged, which is D5.

- [x] **Step 3: Spec rows and AGENTS.md**

- **PRM-63**, in a new `## As a resource` section after "Naming". Its content is:
  - A served prompt's file also reads, unlisted, at `prompts://<namespace>/<place>`. The namespace
    is its plugin's (SKL-59). The place is its path below the commands folder it was read from:
    `commands/db/migrate.md` reads at `prompts://lib/db/migrate.md`. For a file a manifest lists
    by path, the place is that path: `./prompts/x.md` of plugin `b` reads at
    `prompts://lib/b/prompts/x.md`.
  - It reads as the plugin layer builds it, frontmatter kept, after kb's rewriter and the prefix.
  - Every folder holding one is a directory with `_index.md` and `_index.json`.
    `prompts://<library>` is one only when the main plugin serves a prompt (kubed-mcp's PLUG-66
    to PLUG-68).
  - It is held to the scope as `prompts/get` is, and out of scope it fails as an absent address
    does. It is listed only when `Listed` names `prompts` (DLV-8).
  - Two files of one plugin at one place serve the first, and the later one is skipped whole, its
    prompt included. This is K4's limit, reported to quick-mcp.
  - The instructions point at the index (INS-19).
- **AGT-19**, after AGT-18. Every folder holding a served agent file is a directory with
  `_index.md` and `_index.json` (kubed-mcp's PLUG-68), under the request's scope.
  `agents://<library>` is one only when the main plugin serves an agent. The instructions point at
  it, or at each plugin folder that serves one (INS-19). In agents.md's opening, "and as a resource
  only by AGT-18" becomes "and as a resource only at `agents://` (AGT-18, AGT-19), which the
  instructions point at (INS-19)".
- **SKL-61**, after SKL-8's table. `prompts://` and `agents://` are the plugin layer's address
  spaces beside `skill://`, by the same namespaces (SKL-59): PRM-63 and AGT-18 to AGT-19. kb's
  `Catalogue` answers neither. The prefix is accepted and written on them as on `skill://` (GW-4,
  SKL-41).
- **AGENTS.md:**
  - In the Agents-extension paragraph, "add no listing row, no tool and no line of instructions"
    becomes "add no listing row and no tool; an agent's file reads, unlisted, at
    `agents://<namespace>/<path>`, and the instructions name the folder index (INS-19)".
  - In the surface section, after the skills paragraph, add one paragraph: a served prompt reads,
    unlisted, at `prompts://<namespace>/<place>` and an agent at `agents://…`, with folder indexes,
    all kubed-mcp's. `prompts://<library>` exists only when the main plugin serves one, which is
    why INS-19 can point at plugin folders. kb serves neither scheme.
  - In "A provider that stores a `Catalogue`…", `ScopedInstructions` now takes
    `SkillServing.served_snapshot`, not `catalogue()`. *(Done in Task 1, with the Agents paragraph.)*

- [x] **Step 4: Run every check**

Run: `ruff check . && pytest && python scripts/generate_wiki.py --check`
Expected: all pass.

- [x] **Step 5: Commit**

```bash
git add tests/test_kinds_as_resources.py docs/superpowers/specs AGENTS.md
git commit -S -m "test: prompts:// and agents:// follow kb's scope and prefix; spec rows (#85)"
```
