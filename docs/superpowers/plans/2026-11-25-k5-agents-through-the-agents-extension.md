# K5: Agents Through kubed-mcp's Agents Extension Implementation Plan

> **History.** Proposed for #83 (PR #100, into `issue-80`), after K3 (#79, PR #89), the gateway
> prefix (#81, PR #93), the `_publish` race fix (#94, PR #96) and K4 (#82, PR #97). The spec is
> #83's notes in `.issue/issues.md`, with Dr K's rulings (b) of 2026-11-24 and the parent's
> messages of 2026-11-25 (`_reading()`, `Catalogue.agent_instructions` kept for commands, the pin
> at what `issue-80` pins). The design is below; there is no separate design file. Three points
> of the notes could not be built as written against rc2's source, and D4, D5 and D7 say what
> replaces each.
>
> **Approved 2026-11-25**, with D4, D5 and D7 checked against kubed-mcp `v0.3.0` as well as rc2.
> In 0.3.0 `agent_meta` still runs once per agent at set entry with no view, so N9 stays and no
> quick-mcp row is raised from K5. A raise still skips one agent and keeps its plugin (PLUG-73),
> which D4 relies on, and D5 is K4's shape, with one warning. Task 0 ran under rc2: `issue-80`
> still pins it, as #99 (0.3.0) has not merged. K6 (#84) writes index v12 and accepts v11's
> `fetches`.
>
> **The pin moved during Task 4.** #99 merged into `issue-80`, and `issue-80` was merged into this
> branch, so the pin is `kubed-mcp>=0.3.0,<0.4`. `tests/test_agent_layer.py` passes unchanged
> under 0.3.0, and Task 4 cites kubed-mcp's rows at `v0.3.0`. Task 4 also found that kb's
> `_meta.skills` named a skill SKL-3 does not serve, because the hook runs before the parity
> guard. It is fixed in `agent_meta`.
>
> **Shipped 2026-11-25**, Tasks 0 to 5 and the whole-branch review. The review found one
> regression from D6: kubed-mcp calls `agent_meta` again for every plugin a live re-read keeps,
> and only a live plugin answered from its last read, so any other kept plugin re-read its agent
> files from disk. Every added plugin's agent reads are now published (`_Published.agent_reads`)
> and carried by `_keep`, so a kept plugin reads no file. The hidden-file check behind
> `_meta.skills` runs once per publish.

> **For agentic workers:** REQUIRED SUB-SKILL: Use skill://superpowers/subagent-driven-development/SKILL.md (recommended) or skill://superpowers/executing-plans/SKILL.md to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** kb stops parsing agents and keeping a roster of them. kubed-mcp's plugin layer is the
one reader of an agent file, and kb keeps its `io.kubed.mcp-kb/agent` key, its containment
check, its `/health` and a broken live edit's last good build. `agents/list` and `agents/get`
are unchanged, renamed clashes included.

**Architecture:** K3 already serves agents through kubed-mcp, and `SkillServing.agent_meta`
already adds kb's key (PLUG-73). What is left of kb's own agent code goes:
- the harvest records agent *paths*, and parses none;
- `/health` and the parity guard read `Plugin.agent_files` and `Plugin.skipped` (PLUG-74);
- `agent_meta` reads an agent's frontmatter with kubed-mcp's own `parse_agent`, from the path
  `readable` returns.

A live re-read vets the agent files a plugin serves before re-adding it, as K4 vets its prompts.

**Tech Stack:** Python ≥3.11, `kubed-mcp==0.2.0rc2` (rc3 if #92 has merged into `issue-80`),
FastMCP through it, pytest + pytest-asyncio, uvicorn, wsgidav.

**Spec:** this plan's design section; #83's notes in `.issue/issues.md`; the living spec in
[agents.md](../specs/agents.md), with SKL-37 and SKL-58 in [skills.md](../specs/skills.md), LIB-29
in [plugins-and-libraries.md](../specs/plugins-and-libraries.md) and PRM-60 in
[prompts.md](../specs/prompts.md).

## Design

### What is on the branch now, read in the code

- `catalogue/agents.py` has `parse_agent`, `ParsedAgent`, `routing_hint`, `Agent` and
  `AgentRoster`. `mcp/agents.py` is already gone (K3).
- `catalogue/snapshot.py`:
  - `build_plugin` parses every agent file into `AgentRow(path, name)` and adds a `skipped` row
    for each that fails;
  - `_admit` skips unusable and twin names;
  - `build_snapshot` re-parses every row (`_read_agents`, `_ReadAgents`), and `_AgentNames`
    claims names per library.

  `_narrowed` then replaces the roster, `renamed`, `unserved` and the library `agents` count with
  what the layer serves. The plugin `agents` count and the agent `skipped` rows are still kb's
  parse.
- `catalogue/index.py`: `AgentRow`, `PluginRecord.agents: tuple[AgentRow, ...]`,
  `PluginRecord.agent_paths`, `INDEX_VERSION = 10`. A file of any other version is ignored, and
  the cold start fetches.
- `catalogue/uris.py`:
  - `Catalogue(…, agents=AgentRoster)`, `.agents`, `.agent()`, `agent_path`, and
    `without(addresses, agents)`;
  - `agent_meta(library, plugin, path, read: Agent)`;
  - `agent_instructions`, which `rewrite` also uses for a command's body (K4), so it stays.
- `mcp/skills.py`:
  - `agent_meta` answers from `_reading()`, then from the roster (`catalogue.agent`), and
    otherwise parses the file itself (`_read_agent`, which calls `readable` and then
    `parse_agent(root / path)`, not the path `readable` returned);
  - a live plugin's `_Watch.read` holds the `Agent`s its last add read;
  - `_narrowed` builds the roster from `served.agent_files`, with kb's `Agent` per file.
- `routes.py` counts `snapshot.catalogue.agents`, and `pins._serving` reads
  `served.agents.visible(scope)`.
- The plugin-root fallback's refusal (AGT-3) reads `LibraryFiles`' `agent_paths`, which comes from
  `harvest.agent_paths` (the folder and the listed files). It needs no parse.

### Checked against kubed-mcp 0.2.0rc2 (`kubed/mcp/plugins.py`, `kubed/mcp/agents.py` at `v0.2.0-rc.2`)

1. **PLUG-73.** `AgentMeta = Callable[[str, Plugin], Mapping[str, object] | None]`. `_enter` calls
   it once per agent named, as a plugin enters a set: "It runs on set entry, never in a build".
   - A raise skips the agent, which claims no name. The layer logs it at ERROR and records
     `(path, "agent_meta failed: <message>")` in `Plugin.skipped`.
   - `None` adds nothing.
   - A non-dict result, or one that is not JSON, is dropped with a warning.
   - The layer's own key is dropped from the result.
2. **PLUG-74.** `AgentFile(name: str, path: str, renamed: bool = False)`, and
   `Plugin.agent_files` lists each agent served, with its file, in path order. `Plugin.agents` is
   the served names. `Plugin` carries no parsed frontmatter.
3. **`kubed.mcp.agents`** exports `parse_agent(text, skills=None, prefix="", *, stem=None,
   folders=()) -> Agent | str` and `META_KEY`.
   - It reads text, never disk.
   - On success its `detail["_meta"][META_KEY]["frontmatter"]` is the frontmatter as parsed.
   - On failure it returns one of these reasons: `no YAML frontmatter`,
     `its frontmatter is not a non-empty mapping`, `its frontmatter is not representable as JSON`,
     `its name must be a non-empty string`, `its description must be a non-empty string`,
     `agent name '<name>' is not a usable name`.
   - A missing `name` takes the stem.
4. **`modelRoutingHint`** is the layer's `routing_hint`: `re.split(r"[^a-z0-9]+", model.lower())`,
   with the first word in `{"opus": "large", "sonnet": "medium", "haiku": "small"}` and
   `"vision": False`. That is AGT-9 word for word, `opus4` naming none included. kb's
   `routing_hint` (`[a-z]+`, which reads `opus4` as `opus`) has served nothing since K3.
5. **`PluginSet`** has `add`, `keep` and `plugins`, and no way to remove a staged plugin.

### Decisions

- **D1. The plugin layer is the one reader of an agent file.** kb's harvest records each
  plugin's agent files as root-relative paths (`harvest.agent_files`, in its order) in
  `PluginRecord.agents: tuple[str, ...]`. `AgentRow` goes, and so does every parse at harvest and
  at snapshot time: `_admit`'s agent loop, `_ReadAgents`, `_read_agents` and `_AgentNames`.
  `INDEX_VERSION` becomes 11. The snapshot carries `agent_files: Mapping[str, tuple[str, ...]]`
  by plugin id: what kb found, which the live watch stamps and the parity guard compares.
- **D2. What is served is the layer's, recorded.** `catalogue/agents.py` keeps one type,
  `ServedAgent`: an agent the layer serves, with the name, library, plugin id and path from
  `Plugin.agent_files`, and its plugin's category, labels and library categories for
  `admitted(scope)`. `_narrowed` builds them into `Snapshot.agents`, and
  `Snapshot.visible_agents(scope)` serves `pins._serving`; `/health` counts them. `AgentRoster`,
  `Agent`, `Catalogue.agents`, `Catalogue.agent`, `agent_path` and `without`'s `agents` go.
- **D3. `/health` reads PLUG-74 (AGT-14).** For each added plugin, from the first library that
  serves it, as K4 does for prompts:
  - its `agents` count is `len(served.agent_files)`;
  - its `skipped` gains `{"path", "reason"}` for each `served.skipped` path that kb found as an
    agent file (`snapshot.agent_files[pid]`) and that is not a taken rename, with the reason
    passed through `_clean`. A taken rename stays the library's `unserved`, as K3 has it.

  A plugin no library serves counts the agent files kb found. A path kb found that the layer
  neither served nor skipped is noted once:
  `agent file <path> of plugin <id> is not served: the plugin layer did not read it`.
- **D4. Containment stays in `agent_meta`, not `ServedTrees`.** *(Replaces notes step 2.)* A
  `PluginLoader` hands the layer a directory, and the layer reads each agent file in it itself,
  so `ServedTrees` cannot leave one file out. kb's veto is PLUG-73's raise.
  - `agent_meta` reads the file at the path `harvest.readable(root, path)` returns, which applies
    K3's parked hardening.
  - It raises when that is None (a link out of the root, a directory, a `..`), and when the path
    is not one of `snapshot.agent_files[pid]`.
  - The second refusal is a fail-closed check, as the rewriter fails a skill kb never found
    (N13). It keeps AGT-3 whole: every agent served is a file kb found, so the fallback refuses it.
- **D5. A broken live edit keeps the plugin's last good build (AGT-16).** *(Replaces notes step
  5's mechanism.)* Serving a file's last good bytes would need a second tree beside the one the
  layer reads. A staged add cannot be taken back (check 5), so a re-read is refused before the
  add, as K4's D7 refuses one for a prompt.
  - `_vet` also reads each `served_now.agent_files` file through `readable` and kubed-mcp's
    `parse_agent`.
  - A file that no longer reads raises `ValueError(f"agent {path}: {reason}")`. `_add` keeps the
    plugin as served and logs one warning, and the re-read is tried again when a file moves.
  - The agent keeps its name, its card and its `_meta`.
  - The plugin's skills and prompts keep their last good build too, as P3 already does for a
    prompt.
  - A refresh re-adds from the source and has no last good build to keep, as PRM-60 has none.
- **D6. kb's key, read through the layer's parser (AGT-9, ruling (b)).** `agent_meta` returns
  `{AGENT_META: Catalogue.agent_meta(library, plugin_id, path, frontmatter, servers)}`, with all
  six fields:
  - `plugin`, `library` and `path`;
  - `frontmatter`, from kubed-mcp's `parse_agent` on the file's text with no prefix (GW-8);
  - `servers`, from the plugin;
  - `skills`.

  It reads `_reading()` and never `self._published`. A kept live plugin answers with the
  frontmatter its last add read (`_Watch.read`, now `Mapping[str, Mapping[str, object]]`).
  `parse_agent`, `ParsedAgent`, `routing_hint` and `_read_agent` go. The layer emits
  `modelRoutingHint` as AGT-9 says (check 4), so dropping kb's makes no difference.
- **D7. `_meta.skills` stays per generation (N9 kept).** *(Notes step 4 is not buildable on
  rc2.)* The hook runs at set entry and never sees a view (check 1). So AGT-17's skills map stays
  what K3 made it: the agent's own plugin, every scope alike. A scoped map needs a quick-mcp row
  that calls `agent_meta` per build with the view in its key. That is Dr K's call. Nothing in kb
  waits for it.
- **D8. Names are claimed in the order kb adds plugins** (ruling 2). A test pins it across two
  forced refreshes and one appended plugin.
- **Deleted:** `parse_agent`, `ParsedAgent`, `_body`, `routing_hint`, `ROLES`, `Agent`,
  `AgentRoster` (`catalogue/agents.py`); `AgentRow` (`index.py`); `_admit`'s agent rows,
  `_Admitted.agents`, `_ReadAgents`, `_read_agents`, `_AgentNames` and the `read_agents`
  plumbing (`snapshot.py`); `agent_path`, `Catalogue.agents`, `Catalogue.agent` and `without`'s
  `agents` (`uris.py`); `_read_agent` (`mcp/skills.py`). Kept: `Catalogue.agent_instructions`,
  `harvest.agent_files`, `harvest.agent_paths` and the AGT-3 refusal in `LibraryFiles`.

### Named changes for QA's dump

- **A1. Agent skip reasons are the layer's.** `/health`'s `skipped` rows for agent files carry
  the layer's reasons (check 3). Task 0 read them under rc2:
  - a twin in the same plugin: `agent <library>_twin is already served by agents/twin-1.md`. It
    is skipped, not renamed: a rename is only for a clash with another plugin;
  - a file that is not UTF-8: Python's decode error, such as `'utf-8' codec can't decode byte
    0xe9 in position 11: invalid continuation byte`, with no path in it;
  - an unusable name: `agent name '<library>_a:b' is not a usable name`, with the name already
    prefixed.
  - A file with no frontmatter `name` serves under its stem, as before, and is no longer listed
    as skipped.
  - A blank `description`, frontmatter with no JSON form, and a name the layer refuses were
    logged only. Now each is a `skipped` row.
- **A2. AGT-16's last good build is back** (reverses K3's N6 clause). A live agent saved
  mid-edit goes on serving until a later save reads. The rest of its plugin is held too, with one
  warning.
- **A3. A plugin's `agents` count is what the layer serves for it.** A plugin that no library
  serves counts the agent files kb found.
- **A4. `index.json` is version 11.** The first boot after deploy ignores the v10 file and
  fetches every source once.
- **A5. An agent file only the layer finds is not served** (D4), and kb notes it once. None is
  expected in the live dump.

Unchanged, and not in the dump diff:
- **N5 superseded:** both keys are served, as they have been since K3.
- **N9 kept:** AGT-17 stays per generation (D7).
- **`modelRoutingHint`** is unchanged (check 4).
- **`agents/list` and `agents/get`** are unchanged, renames included.

## Global Constraints

- `pyproject.toml` pins `"kubed-mcp==0.2.0rc2"`. If #92 has merged into `issue-80`, it is
  `==0.2.0rc3`: work on that and re-run Task 0 under it. Never a range.
- FastMCP only through `kubed.mcp` and its submodules. `kubed.mcp.agents` joins AGENTS.md's list
  of kubed-mcp modules kb imports, and only `mcp/skills.py` imports it. `catalogue/` and
  `plugins/` import no `kubed.mcp`, and `tests/test_boundaries.py` stays green.
- Every hook reads published state through `_reading()` (`_ENTERING`, then `_PINNED`, then
  `_published`), never `self._published`, except `_vet`, as K4 left it.
- Absent and out of scope stay indistinguishable (AGT-13): `Agent not found` for both.
- No cache path or credential in a reason, a note or a log line kb writes (`unrooted`, `scrub`,
  `SkillServing._clean`).
- kb's `_meta` key is never prefixed (GW-8); `instructions` is prefixed by the layer (GW-5), once.
- Spec rows keep their IDs, no ID is reused, and the spec holds statements only, with no issue
  numbers. Wiki changes go on the wiki's `issue-83` branch, never its `master`.
- Python 3.11 floor; 88 columns; a glob ending `**` is written `dir/**/*`.
- Every task runs `ruff check .` and then its own tests (`pytest tests/<file>.py -v`). The last
  task runs all of `pytest`, `python scripts/generate_wiki.py --check` and
  `python scripts/generate_openapi.py` with `npx --yes @redocly/cli@2 lint openapi.yaml`. CI runs
  `ruff check .` and `pytest` on 3.11 and 3.14, plus the wiki check and the OpenAPI lint.

## Review Focus

1. **kb's harvest and the layer disagree on which files are agents.** Expected: the agent kb did
   not find is not served, and kb notes it once (D4, A5). *(Task 1:
   `test_an_agent_only_the_layer_finds_is_not_served`.)*
2. **A nameless agent file** (`---\ndescription: d\n---\nBody.\n` at `agents/helper.md`).
   Expected: served as `<library>_helper`, with no `skipped` row (A1). *(Task 1:
   `test_a_nameless_agent_serves_under_its_stem_and_is_not_skipped`.)*
3. **A non-UTF-8 agent file and a twin, in one plugin.** Expected: one `skipped` row each, with
   the layer's reason and no cache path, and the plugin's other agents served. *(Task 1:
   `test_agent_skip_rows_are_the_layers`.)*
4. **A live edit that renames an agent's frontmatter `name`.** Expected: served under the new
   name from the next request, through D5's vet; a later plugin's agent it now clashes with is
   renamed. *(Task 3: `test_a_live_rename_renames_a_later_clashing_agent`, kept green.)*
5. **A cold start from a v10 `index.json`.** Expected: the file is ignored, the sources are
   fetched, and everything is served; the file is then written at v11 (A4). *(Task 1:
   `test_a_v10_index_is_rebuilt`.)*

---

### Task 0: Check the layer under the pin before building on it

**Files:**
- Test: `tests/test_agent_layer.py` (create)

**Interfaces:**
- Consumes: kubed-mcp's `QuickMCP`, `plugin_set()`, `PluginSet.add(address, namespace=…,
  manifest=…)`, `serve(...)`, `agent_meta(fn)`, and `kubed.mcp.agents.parse_agent`, `META_KEY`.
- Produces: the go/no-go for D4 to D7, and A1's exact reasons.

- [x] **Step 1: Bring in `issue-80`**

Run: `git fetch origin && git merge origin/issue-80`, then `pip install -e '.[test]'` and
`pytest -q`.
Expected: green, with the K4 baseline's skips and its one xfail (N15). Read the pin in
`pyproject.toml`.

- [x] **Step 2: Write the layer checks**

These use kubed-mcp alone, with no kb code: a `QuickMCP("mcp-kb")` and one plugin folder in
`tmp_path` holding `.claude-plugin/plugin.json` `{"name": "p"}`, `skills/s/SKILL.md`, and agents
`a.md` (`model: claude-opus-5-5`), `b.md` (`model: opus4`), `twin-1.md` and `twin-2.md` (both
`name: twin`), `latin.md` (bytes `b"---\nname: l\xe9\n---\n"`) and `colon.md` (`name: "a:b"`).
Count the hook's calls.

```python
async def test_agent_meta_runs_at_entry_and_never_in_a_build(tmp_path):
    # the hook records each name it is called with; serve, then build two views
    # (agents/get under two plugin_view keys)
    entered, after_builds = await _hook_calls(tmp_path, views=2)
    assert sorted(entered) == sorted(plugin.agents)  # once per agent served
    assert after_builds == entered  # no call in either build

async def test_agent_files_name_each_served_file():
    assert [(f.name, f.path, f.renamed) for f in plugin.agent_files] == [...]  # path order

async def test_the_routing_hint_is_agt9s(tmp_path):
    assert hints == {"lib_a": {"role": "large", "vision": False}, "lib_b": None}

def test_parse_agent_reads_text_and_gives_the_frontmatter():
    parsed = parse_agent("---\nname: a\ndescription: d\nx: 1\n---\nBody.\n", stem="a")
    assert parsed.detail["_meta"][META_KEY]["frontmatter"] == {"name": "a", "description": "d", "x": 1}
    assert parse_agent("---\nname: a\n---\n", stem="a") == "its description must be a non-empty string"

async def test_the_layers_skip_reasons(tmp_path):
    assert dict(plugin.skipped) == {...}  # twin-2.md, latin.md, colon.md as rc gives them
```

Write each `...` and the hook helper out in full. Run the tests once, then write the values the
rc gives into the assertions and into A1.

- [x] **Step 3: Run them**

Run: `pytest tests/test_agent_layer.py -v`
Expected: all pass. **If the hook runs in a build (once per view), stop.** A scoped `_meta.skills`
becomes buildable, and D7 goes back to Dr K. **If `parse_agent` or `META_KEY` is not exported,
stop:** D6 then needs a facade row in quick-mcp, and kb does not import around it.

- [x] **Step 4: Commit**

```bash
git add tests/test_agent_layer.py docs/superpowers/plans/2026-11-25-k5-agents-through-the-agents-extension.md
git commit -m "K5: check kubed-mcp's agent hook, files and reasons under the pinned rc"
```

### Task 1: The harvest records agent paths, and `/health` reads what the layer serves

**Files:**
- Modify: `kubed/mcp_kb/catalogue/index.py`: delete `AgentRow`; `PluginRecord.agents:
  tuple[str, ...] = ()`; `INDEX_VERSION = 11`; the loader and the module docstring.
- Modify: `kubed/mcp_kb/catalogue/snapshot.py`:
  - `build_plugin` parses no agent;
  - `_plugin_status` counts `record.agents`;
  - add `Snapshot.agent_files`, `Snapshot.agents` and `visible_agents`;
  - delete what D1 lists;
  - `_serve_library` returns `(entry, skills)`;
  - `build_snapshot` builds `Catalogue` with no roster.
- Modify: `kubed/mcp_kb/catalogue/agents.py`: add `ServedAgent` and update the module docstring.
  `parse_agent` and `Agent` stay until Task 2.
- Modify: `kubed/mcp_kb/catalogue/uris.py`: delete `agent_path`, `Catalogue.agents`,
  `Catalogue.agent` and the `agents` parameter of `__init__` and `without`;
  `agent_meta(library, plugin, path, frontmatter, servers)`.
- Modify: `kubed/mcp_kb/mcp/skills.py`: `_publish`'s `has_agents`, `_watch`, `_narrowed` (D2, D3),
  `agent_meta`'s fail-closed check (D4).
- Modify: `kubed/mcp_kb/routes.py:53`, `kubed/mcp_kb/mcp/pins.py:163`
- Modify: `docs/superpowers/specs/agents.md` (AGT-6, AGT-8's last bullet, AGT-14), `AGENTS.md`
  (the `catalogue/agents.py` row)
- Test: `tests/test_agents.py`, `tests/test_index.py`, `tests/test_parity.py`,
  `tests/test_plugin_serving.py`

**Interfaces:**
- Consumes: Task 0's recorded reasons.
- Produces:
  - in `catalogue/agents.py`:

    ```python
    @dataclass(frozen=True)
    class ServedAgent:
        name: str                       # the layer's, AgentFile.name
        library: str
        plugin: str                     # kb's plugin id
        path: str                       # AgentFile.path, root-relative
        category: str | None
        tags: frozenset[str]
        library_categories: frozenset[str] = frozenset()
        def admitted(self, scope: Scope) -> bool: ...
    ```
  - `Snapshot.agent_files: Mapping[str, tuple[str, ...]]` by plugin id, for every `ok` record;
    `Snapshot.agents: tuple[ServedAgent, ...] = ()` in name order;
    `Snapshot.visible_agents(self, scope: Scope = EVERYTHING) -> list[ServedAgent]`.
  - `Catalogue.agent_meta(self, library: str, plugin: str, path: str, frontmatter: Mapping[str, object], servers: Sequence[str]) -> dict`.
    Its `skills` is `own.preload(frontmatter.get("skills"))`, as now.

- [x] **Step 1: Write the failing tests**

In `tests/test_agents.py`, over `agents_tree` and `server_of`:

```python
def test_the_harvest_records_paths_and_parses_nothing(tmp_path):
    kb = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")
    assert kb._records["extra@drawio"].agents == (
        "agents/broken.md", "agents/db/migrate.md", "agents/diagrammer.md",
        "agents/twin-a.md", "agents/twin-b.md",
    )

def test_agent_skip_rows_are_the_layers(tmp_path):
    kb = agents_tree(tmp_path).knowledge_base(tmp_path / "cache")
    server_of(kb)
    skipped = kb.status["plugins"]["extra@drawio"]["skipped"]
    assert {"path": "agents/broken.md",
            "reason": "its description must be a non-empty string"} in skipped
    assert {"path": "agents/twin-b.md", "reason": TWIN} in skipped  # Task 0's wording
    assert str(tmp_path / "cache") not in json.dumps(kb.status)

def test_a_nameless_agent_serves_under_its_stem_and_is_not_skipped(tmp_path):
    # a kit plugin with agents/helper.md = "---\ndescription: d\n---\nBody.\n"
    assert "kit_helper" in _served(kb)
    assert not [r for r in kb.status["plugins"]["kit"].get("skipped", ())
                if r["path"] == "agents/helper.md"]

def test_an_agent_only_the_layer_finds_is_not_served(tmp_path, monkeypatch, caplog):
    # monkeypatch harvest.agent_files to return [] for the kit plugin
    assert "kit_a" not in _served(kb)
    assert {"path": "agents/a.md",
            "reason": "agent_meta failed: agent file agents/a.md is not one kb found"} \
        not in kb.status["plugins"]["kit"].get("skipped", ())  # not a path kb found (D3)
    assert caplog.text.count("agent file agents/a.md is not one kb found") >= 1

def test_a_v10_index_is_rebuilt(tmp_path):
    # boot once; rewrite index.json with "version": 10; boot again from it
    assert _names(kb, "drawio") == [...as test_names_follow_claude_code]
    assert json.loads(index_path.read_text())["version"] == 11
```

Migrate the rest of `tests/test_agents.py`:
- `test_counts` asserts the layer's counts after `server_of`, with `extra@drawio` at 3
  (`db_migrator`, `diagrammer`, `twin`).
- `test_a_row_that_no_longer_parses_is_reported_and_keeps_its_claim` goes. Its cold-start case is
  N11's `test_a_broken_agent_frees_its_name_on_a_cold_start`.
- Every assertion on `catalogue.agents` reads `snapshot.agents` or `agents/list`.
- `test_an_agent_name_that_is_not_a_name_is_skipped` serves each name and asserts the layer's
  `skipped` row.
- `test_a_twin_in_one_plugin_is_skipped` and `test_an_agent_named_like_a_rename_does_not_squat_it`
  take Task 0's reasons.
- The harvest-level tests that parse files (lines 149 to 385, except the listed-path and bare
  ones) either move to served assertions or are deleted where `tests/test_agent_layer.py` pins the
  layer's rule.

`tests/test_index.py::test_a_record_with_agents_round_trips` round-trips the paths.
`tests/test_parity.py:533,552,573` and `tests/test_plugin_serving.py:634` read `snapshot.agents`.

- [x] **Step 2: Run them to verify they fail**

Run: `pytest tests/test_agents.py -v`
Expected: the new tests fail. `PluginRecord.agents` holds `AgentRow`s, and the skip reasons are
kb's.

- [x] **Step 3: Implement**

- `build_plugin`:
  `agents=tuple(_relative(path, root) for path, _ in harvest.agent_files(root, globs))` inside
  the same `try`. There is no agent `unloadable` row.
- `_narrowed(snapshot, added, refused, skills, noted, live, reads)`, for each added
  `(lib, plugin, served)`:
  - each `served.agent_files` entry becomes a `ServedAgent`, with `renamed` and `owners` as now;
  - `plugin_agents.setdefault(pid, (len(served.agent_files), rows))`, with D3's rows;
  - D3's parity note.

  Then `replace(snapshot, …, agents=tuple(sorted(served_agents, key=lambda a: a.name)))`, and
  each plugin's `agents` and `skipped` come from `plugin_agents`, like `plugin_prompts`.
- `_publish`: `has_agents = bool(snapshot.agent_files.get(pid))`, and the `agents` map built
  from `catalogue.agents` goes.
- `_watch` stamps `root / rel` for each `snapshot.agent_files.get(plugin.id, ())` when
  `plugin.claude_format`.
- `agent_meta`: when `path not in published.snapshot.agent_files.get(row.plugin.id, ())`, raise
  `ValueError(f"agent file {path} is not one kb found")`. Otherwise read as now and call
  `catalogue.agent_meta(row.library, row.plugin.id, path, read.parsed.frontmatter,
  row.plugin.servers)`.
- `routes.report`: `"agents": len(snapshot.agents)`. `pins._serving`:
  `return bool(snapshot.visible_agents(scope))`.
- `grep -rn "AgentRow\|AgentRoster\|_AgentNames\|_read_agents\|agent_path\|catalogue\.agents" kubed tests`
  returns nothing.

- [x] **Step 4: Update the spec and AGENTS.md**

- AGT-6:
  - the plugin layer reads each agent file as its plugin is added, and is the only reader;
  - a file it refuses is listed under its plugin's `skipped` in `/health`, with the layer's
    reason, and never fails the plugin;
  - a file with no `name` serves under its stem and is not listed;
  - list the reasons Task 0 recorded;
  - drop "differs in three ways" and kb's reason strings.
- AGT-8, last bullet: an agent whose file does not read when its plugin is added serves nothing,
  is listed under its plugin's `skipped`, and claims no name.
- AGT-14: the counts, `renamed`, `unserved` and agent `skipped` rows are what the plugin layer
  reports for each plugin added: `Plugin.agent_files` (PLUG-74) and `Plugin.skipped`. A plugin no
  library serves counts the agent files found.
- AGENTS.md's layout row for `catalogue/agents.py`: `ServedAgent`, what the plugin layer serves of
  one agent file. Imports no FastMCP.

- [x] **Step 5: Run the checks**

Run: `ruff check .` then
`pytest tests/test_agents.py tests/test_agents_extension.py tests/test_index.py tests/test_parity.py tests/test_plugin_serving.py tests/test_live.py -v`
Expected: all pass.

- [x] **Step 6: Commit**

```bash
git add -A kubed/mcp_kb tests docs/superpowers/specs AGENTS.md
git commit -m "K5: the harvest records agent paths; /health reads what the plugin layer serves"
```

### Task 2: `agent_meta` reads through kubed-mcp's parser, and kb's parsing goes

**Files:**
- Modify: `kubed/mcp_kb/mcp/skills.py`: add `_frontmatter`; `agent_meta`; `_Watch.read`; delete
  `_read_agent`; update the module docstring.
- Modify: `kubed/mcp_kb/catalogue/agents.py`: delete `parse_agent`, `ParsedAgent`, `_body`,
  `routing_hint`, `ROLES`, `Agent` and `AgentRoster`, and the `frontmatter`, `yaml` and `json`
  imports if unused.
- Modify: `docs/superpowers/specs/agents.md` (AGT-9), `AGENTS.md` (the facade list adds
  `kubed.mcp.agents`; the Agents extension paragraph: containment and kb's key)
- Test: `tests/test_parity.py`, `tests/test_agents.py`

**Interfaces:**
- Consumes: Task 1's `Snapshot.agent_files` and `Catalogue.agent_meta(…, frontmatter, servers)`.
- Produces: `_frontmatter(root: Path, path: str) -> dict[str, object]` in `mcp/skills.py`.
  - It raises `ValueError(f"kb cannot read agent file {path}")` when `readable(root, path)` is
    None, or the read raises `OSError` or `UnicodeDecodeError`.
  - It raises `ValueError(f"agent file {path}: {reason}")` when `parse_agent` gives a reason.
  - Otherwise it returns a copy of the frontmatter.

- [x] **Step 1: Write the failing tests**

Replace `tests/test_parity.py::test_kb_reads_no_agent_file_linked_out_of_the_root`'s
`_read_agent` calls:

```python
def test_kb_reads_no_agent_file_linked_out_of_the_root(tmp_path):
    # the same tree: agents/out.md -> ../elsewhere.md, agents/dir.md a directory, agents/in.md
    for path in ("agents/out.md", "agents/dir.md", "../elsewhere.md"):
        with pytest.raises(ValueError, match=f"kb cannot read agent file {re.escape(path)}"):
            _frontmatter(root, path)
    assert _frontmatter(root, "agents/in.md") == {"name": "in", "description": "I."}
```

In `tests/test_agents.py`, replace `test_routing_hint_by_family` and `test_no_routing_hint` with
one served test:

```python
@pytest.mark.parametrize(("model", "hint"), [
    ("sonnet", {"role": "medium", "vision": False}),
    ("claude-opus-5-5", {"role": "large", "vision": False}),
    ("opus-then-sonnet", {"role": "large", "vision": False}),
    ("opus4", None), ("inherit", None),
])
def test_the_routing_hint_is_agt9s(tmp_path, model, hint):
    got = _served(_kit_agent(tmp_path, f"---\nname: a\ndescription: d\nmodel: {model}\n---\nB.\n"))["kit_a"]
    assert got.get("modelRoutingHint") == hint
```

`test_the_definition` and `test_agent_meta_keeps_kbs_key` stay as they are: all six fields of
kb's key, beside `io.kubed/agent`.

- [x] **Step 2: Run them to verify they fail**

Run: `pytest tests/test_parity.py -k linked_out -v`
Expected: FAIL on the import of `_frontmatter`.

- [x] **Step 3: Implement**

- `_frontmatter`: `target = readable(root, path)`. Read `target.read_text(encoding="utf-8")`, never
  `root / path`. Then `kubed.mcp.agents.parse_agent(text, stem=PurePosixPath(path).stem)`, and
  `dict(parsed.detail["_meta"][META_KEY]["frontmatter"])`.
- `agent_meta`:
  - after Task 1's checks, a kept live plugin's frontmatter is `self._carried[key].read[path]`;
  - otherwise it is `_frontmatter(Path(plugin.root), path)`, recorded in
    `self._reads[key][path]` when the plugin is live;
  - return `{AGENT_META: catalogue.agent_meta(row.library, row.plugin.id, path, frontmatter,
    row.plugin.servers)}` with `skills` kept to `plugin.skills`, as now.
- `_Watch.read: Mapping[str, Mapping[str, object]]`: the frontmatter by path, as its last add read
  it.
- `grep -rn "parse_agent\|ParsedAgent\|routing_hint\|_read_agent\|from ..catalogue.agents import Agent" kubed tests`
  finds only `kubed.mcp.agents`' `parse_agent` in `mcp/skills.py` and `tests/test_agent_layer.py`.

- [x] **Step 4: Update the spec and AGENTS.md**

- AGT-9, kb's key: the plugin layer's agent-meta hook (PLUG-73) adds it as the agent enters the
  set, with `frontmatter` as the plugin layer parses it. kb reads only a regular file inside the
  plugin root that its harvest found as an agent file; any other agent file is not served.
- AGENTS.md:
  - add `kubed.mcp.agents` to the modules kb imports;
  - in the Agents extension paragraph, kb's veto is `agent_meta`'s raise (PLUG-73), read at the
    path `readable` returns; `ServedTrees` hands over a directory and cannot leave one file out.

- [x] **Step 5: Run the checks**

Run: `ruff check .` then
`pytest tests/test_parity.py tests/test_agents.py tests/test_agents_extension.py tests/test_live.py tests/test_boundaries.py -v`
Expected: all pass.

- [x] **Step 6: Commit**

```bash
git add -A kubed/mcp_kb tests docs/superpowers/specs AGENTS.md
git commit -m "K5: kb's agent key reads through kubed-mcp's parser; kb's agent parsing goes"
```

### Task 3: A broken live agent edit keeps the last good build (AGT-16)

**Files:**
- Modify: `kubed/mcp_kb/mcp/skills.py` (`_vet`)
- Modify: `docs/superpowers/specs/agents.md` (AGT-16)
- Test: `tests/test_live.py`

**Interfaces:**
- Consumes: Task 2's `_frontmatter`; K4's `_vet(served_now, row, root, commands)` and `_add`'s
  kept path.

- [x] **Step 1: Write the failing test**

Change `test_a_live_agent_edit_reads_after_trust`'s last two edits:

```python
    first, got, listed = edit(  # an unquoted `[a] [b]` is no YAML at all
        "---\nname: helper\ndescription: [a] [b]\n---\n\nHalfway through a save.\n"
    )
    assert first["instructions"] == "Help, edited."
    assert got["instructions"] == "Help, edited.", "AGT-16: the last good build"
    assert listed[name]["description"] == "Helps, edited upstream."
    assert "was not read again" in caplog.text and "agents/helper.md" in caplog.text

    first, got, listed = edit(AGENT.format(description="Helps again.", body="Help, saved properly."))
    assert first["instructions"] == "Help, edited.", "N6: the re-adding request"
    assert got["instructions"] == "Help, saved properly."
```

Add `caplog` to its fixtures, and add
`test_a_live_agent_saved_with_an_unusable_name_keeps_its_name`: an edit to `name: "a b"` keeps
serving `notes_helper` with the earlier body.

- [x] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_live.py -k live_agent -v`
Expected: FAIL. The broken edit takes the agent away.

- [x] **Step 3: Implement**

At the end of `_vet`, for each `file` in `served_now.agent_files`, call `_frontmatter(root,
file.path)`, and raise `ValueError(f"agent {file.path}: {reason}")` with the reason through
`self._clean` when it raises. A `root` of None raises as the prompt check does. `_add`'s existing
`except` keeps the plugin as served and notes it once.

- [x] **Step 4: Update the spec**

AGT-16's last sentence becomes:
- An edit that no longer reads (D5's failures, or a name the plugin layer refuses) leaves the
  plugin serving the build it served, the agent under its name included.
- The server logs one warning and reads the plugin again when one of its files moves, as PRM-60
  says for a prompt.

- [x] **Step 5: Run the checks**

Run: `ruff check .` then `pytest tests/test_live.py tests/test_prompt_serving.py -v`
Expected: all pass, `test_a_live_rename_renames_a_later_clashing_agent` included.

- [x] **Step 6: Commit**

```bash
git add kubed/mcp_kb/mcp/skills.py tests/test_live.py docs/superpowers/specs/agents.md
git commit -m "K5: a live agent saved mid-edit keeps its plugin's last good build (AGT-16)"
```

### Task 4: Pin the rename order, one generation per read, and the prefix

**Files:**
- Modify: `docs/superpowers/specs/agents.md` (AGT-7, AGT-12, AGT-13 as pointers; AGT-17's
  timing sentence)
- Test: `tests/test_agents.py`, `tests/test_live.py`, `tests/test_agents_extension.py`

**Interfaces:**
- Consumes: Tasks 1 to 3.

- [x] **Step 1: Write the tests**

```python
def test_rename_order_holds_across_refreshes(tmp_path):  # tests/test_agents.py, D8
    tree = agents_tree(tmp_path)
    kb = tree.knowledge_base(tmp_path / "cache")
    before = _owners(kb)
    for _ in range(2):
        kb.refresh(force=True)
        assert _owners(kb) == before
        assert kb.status["libraries"]["drawio"]["renamed"] == {
            "drawio_diagrammer@extra": "drawio_diagrammer is already served by plugin 'drawio@drawio'"}
    _entries(tree, after=[("late", {"agents/d.md": _agent("diagrammer")})])
    kb.refresh(force=True)
    assert _owners(kb) == {**before, "drawio_diagrammer@late": "late@drawio"}
```

In `tests/test_live.py`, extend
`test_a_build_pinned_before_a_refresh_publishes_reads_its_own_state` with an agent
`agents/a.md` whose `skills: [x]` and body `Use notes:x.`:
- an `agents/get` pinned before a worker-thread refresh, which renames skill `x` to `y`, answers
  with kb's `_meta` `skills` and `instructions` from its own generation;
- the next `agents/get` answers from the new one.

In `tests/test_agents_extension.py::test_a_prefix_reaches_instructions_only`, under
`Kb-Resource-Prefix: kb+`:
- `instructions` holds `kb+skill://` and no `kb+kb+`;
- `_meta["io.kubed.mcp-kb/agent"]["skills"]` values start with `skill://`;
- its `frontmatter` holds no `kb+`.

- [x] **Step 2: Run them**

Run: `pytest tests/test_agents.py::test_rename_order_holds_across_refreshes tests/test_live.py::test_a_build_pinned_before_a_refresh_publishes_reads_its_own_state tests/test_agents_extension.py::test_a_prefix_reaches_instructions_only -v`
Expected: PASS. They pin behaviour the earlier tasks keep. A failure is a bug in Tasks 1 to 3's
code: fix it there, not in the test.

- [x] **Step 3: Update the spec**

- AGT-17: "It is decided once per generation…" gains a reason: the plugin layer's agent-meta hook
  runs as the agent enters the set (PLUG-73), not per build.
- AGT-7, AGT-12 and AGT-13 say that kubed-mcp's agents extension serves them. Cite its row IDs
  from quick-mcp's spec at the pinned tag, keep kb's rows' IDs, and keep the statements that
  still apply.

- [x] **Step 4: Run the checks**

Run: `ruff check .` then `pytest tests/test_agents.py tests/test_live.py tests/test_agents_extension.py -v`
Expected: all pass.

- [x] **Step 5: Commit**

```bash
git add tests docs/superpowers/specs/agents.md
git commit -m "K5: pin agent rename order, one generation per read, and the prefix"
```

### Task 5: The wiki, the changelog and the whole suite

**Files:**
- Modify: the wiki pages that describe agents' `/health` rows or a broken live edit (find them
  with `grep -rln "agents/get\|agent.*skipped\|no longer parses" wiki`), on the wiki's `issue-83`
  branch
- Modify: `CHANGELOG.md` (`[Unreleased]` only):
  - line 35 names kb's `io.kubed.mcp-kb/agent` beside kubed-mcp's `io.kubed/agent`;
  - line 55 adds "a live agent or prompt saved mid-edit goes on serving its last good version"

- [x] **Step 1: Update the wiki**

Make the pages say what the spec now says (A1 to A3). Run `python scripts/generate_wiki.py`, and
commit whatever it moves on the wiki's `issue-83` branch.

- [x] **Step 2: Run every check**

Run: `ruff check .`, then `pytest`, then `python scripts/generate_wiki.py --check`, then
`python scripts/generate_openapi.py` and `npx --yes @redocly/cli@2 lint openapi.yaml`.
Expected: ruff is clean. pytest is green, with the K4 baseline's skips and its one xfail (N15).
The wiki check and the lint are clean.

- [x] **Step 3: Commit, and write the PR body**

```bash
git add -A CHANGELOG.md wiki
git commit -m "K5: the wiki and the release notes for agents through the plugin layer"
```

The PR body carries:
- the named changes A1 to A5;
- the unchanged list (N5 superseded, N9 kept, `modelRoutingHint`);
- Task 0's checks of PLUG-73 and PLUG-74 under the pin, with their results.

QA's dump covers the ten scopes, with and without `kb+`, before and after deploy. `agents/list`
and `agents/get` must match, renamed clashes included.
