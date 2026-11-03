# Agents Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A client calls `agents/list` and `agents/get` and gets the agents that Claude-format
plugins ship, scoped by the connection's library, category and tag, and named as Claude Code
would name them. drawio's `agents/diagrammer.md` is served as `drawio_diagrammer`.

**Architecture:** The harvest finds agent files beside skills and prompts and records them as rows
on the `PluginRecord`. The snapshot claims names per library, in library order, and builds an
`AgentRoster` that `Catalogue` holds. `Catalogue` answers cards and definitions under a `Scope`,
with no FastMCP. `mcp/agents.py` is a FastMCP `ServerExtension` beside `mcp/skills.py`, reading
through the snapshot getter. The plugin-root fallback learns to refuse agent files. `/health`
counts agents.

**Tech Stack:** Python ≥3.11, FastMCP 4 (`ServerExtension`, `MethodBinding`), pydantic, PyYAML /
python-frontmatter, pytest + pytest-asyncio, uvicorn.

**Spec:** [agents.md](../specs/agents.md), AGT-1 to AGT-16, rewritten this round and still all
*(proposed)* until Task 6. Task 6 also edits SCP-21, SCP-24, SCP-29 and SCP-31 in
[scoping-and-instructions.md](../specs/scoping-and-instructions.md), HTTP-8, HTTP-27 and HTTP-29
in [http-and-tools.md](../specs/http-and-tools.md), and SKL-30 and SKL-31 in
[skills.md](../specs/skills.md). The why is in the design
[2026-11-02-agents-extension-design.md](2026-11-02-agents-extension-design.md), Part 1. Its
History header now says what this plan overtakes. Brief and decisions: issue #33, PR #35.

## Design

This plan settles Part 1 of the design. Part 2 (parity) is its own issue and **lands first**.
`agents.md` is the whole spec of what ships here. What follows is what the spec doesn't say on
its own: the decisions behind it, and how they map onto the code.

**The rule for everything (Dr K): do what Claude Code does.**

**Decided (Dr K, issue #33):**

1. **A name clash keeps both agents and never drops a plugin (AGT-8).** The first plugin in
   library order keeps `<library>_<name>`. A later plugin's agent is served as
   `<library>_<name>@<plugin name>`, and the library's `renamed` in `/health` says so. If that
   name is taken too, only that agent is left unserved. kb stores no owner, in `index.json` or
   anywhere else. The promise is only that a plugin *appended* to a library renames nothing.
2. **Parity first, as its own issue.** This plan consumes what that PR adds (see *Precondition*).
3. **An operator `files` glob over `agents/` serves those files as library files.** AGT-3 refuses
   only the plugin-root fallback.
4. **Scope comes from the connection (AGT-15).** `agents/*` honour `Kb-Library`, `Kb-Category`,
   `Kb-Tag`, their aliases and their params, through `requested_scope()`, as `skills/*` do. An
   agent is in scope when its plugin is. Neither method takes a scope param of its own, because
   SCP-9 already forbids one ("No tool, prompt or method takes a library, category or tag as an
   argument"). That answers the question left open in turn 4.

**My calls, now in the spec:**

- One page, and any `cursor` is `-32602` (AGT-7). `ttlMs: 0` (AGT-12). Both copy SKL-48.
- `modelRoutingHint` is omitted for a full model id (AGT-9). Only the three aliases map.
- `_meta.frontmatter` is verbatim. The gateway prefix applies to `instructions` only.
- `capabilities` is used only when it is a list of strings. Anything else is `[]`.
- Two files of one plugin that take the same *served* name: the first in path order wins. So
  `agents/a/x.md` and `agents/b/x.md` are `…_a_x` and `…_b_x`, two agents, as in Claude Code
  (`plugin:a:x`, `plugin:b:x`).
- A live agent is re-read on `agents/get`, as a prompt is (AGT-16, after PRM-60).
- `/health` adds a library's `renamed` (a map) and `unserved` (rows). A library's existing
  `skipped` is about marketplace entries, and `conflicts` means a whole plugin is out, so neither
  fits.

**How names fall out (AGT-7, AGT-8):**

| Plugin `p` in library `lib` | File | Frontmatter `name` | Served as |
|---|---|---|---|
| first | `agents/diagrammer.md` | `diagrammer` | `lib_diagrammer` |
| first | `agents/db/migrate.md` | `migrator` | `lib_db_migrator` |
| first, manifest lists `./agents/db/migrate.md` | same file | `migrator` | `lib_migrator` |
| later, `extra` | `agents/diagrammer.md` | `diagrammer` | `lib_diagrammer@extra` |
| later, `extra`, and `lib_diagrammer@extra` already taken | | | not served in `lib`; in `unserved` |
| a plugin declared bare in the config | `agents/x.md` | `x` | nothing (AGT-4) |

**What does not change:** `tools/list`, `resources/list`, `prompts/list`, the server
`instructions` (INS-6 counts skills only), the `skill://` grammar, LIB-28 and LIB-29 for skills
and prompts, and `config.schema.json` (no config key is added).

## Precondition: parity is on main

This plan reads agents as the parity PR parses them. Before Task 1:

- [ ] **Rebase `issue-33` on `main`** once the parity PR has merged. Then confirm what it added,
  and use those names wherever this plan says *parity's*:
  - the manifest's and the marketplace entry's `agents`, as harvest patterns, with a directory or
    a non-`.md` entry already dropped with a note (AGT-5, PLG-22). This plan calls them
    `Globs.agents: tuple[str, ...] | None`, where `None` means the default scan;
  - the manifest's and the entry's `mcpServers`, as server names;
  - the `INDEX_VERSION` main ends at.
- [ ] **If parity has not merged, stop.** Report it on the PR and do no task. Don't add a
  stand-in `agents` field: the parity PR owns that parsing, and two copies would conflict.

## Global Constraints

- **Toolchain** (CI's `test.yml`): `pip install -e ".[test]"`, then `ruff check .` and `pytest`
  from the repository root. Check out the `wiki/` submodule (`git submodule update --init`), so
  `tests/test_wiki.py` runs instead of skipping.
- **Python 3.11 is the floor.** No 3.12+ construct, and no backslash inside an f-string
  expression. Lines are at most 88 columns. Write a glob as `dir/**/*.md`, never with a trailing
  `**`. Every new module starts with `from __future__ import annotations` and a docstring that
  says why it exists.
- **`catalogue/` and `plugins/` import no FastMCP** (`tests/test_boundaries.py`).
  `catalogue/agents.py` is pure.
- **Read through the getter.** The extension is handed `lambda: self.snapshot.catalogue`, never a
  `Catalogue`.
- **Every `Catalogue` method takes a `Scope`**, and an out-of-scope agent is answered exactly as
  an absent one is.
- **Nothing fetched is executed.** `.mcp.json` and `mcpServers` are read for their *names* only.
  kb never connects to, starts or forwards a server (AGT-11).
- **No cache path in `/health`.** Use `_relative` and `unrooted` for every path and reason, as
  prompts do.
- **Markers:** a test with no server is `@pytest.mark.unit`. One that runs uvicorn is
  `integration`, as `tests/test_header_scope.py` is.
- **Don't grow the shared trees in `tests/conftest.py`.** Other tests count what they hold. The
  agents tree is its own fixture in `tests/test_agents.py`.
- **Public repo:** no names or real hostnames in code, tests or docs. The maintainer is Dr K.
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Names are the library's, not the caller's.** A tag scope that sees only `extra` still sees
   `drawio_diagrammer@extra`. → Task 4, `test_a_scoped_caller_sees_the_library_name`.
2. **Appending a plugin renames nothing; prepending one may.** → Task 2,
   `test_an_appended_plugin_renames_nothing`, `test_a_prepended_plugin_takes_the_short_name`.
3. **Out of scope looks exactly like absent:** the same code, message and `data`. → Task 4,
   `test_out_of_scope_is_agent_not_found`.
4. **AGT-3 against the operator's glob.** The fallback refuses an agent file at the library base
   and under a skill, and a declared `files: ["agents/**/*.md"]` still serves it. → Task 3.
5. **A plugin that ships only agents** is a scope that names something. SCP-31 row 9 must not
   refuse it. → Task 4, `test_a_scope_of_only_agents_is_served`.
6. **The capability value** is `{"listChanged": false}` in both eras, beside the skills id, not
   instead of it. → Task 4, `test_both_extensions_are_declared`.

## The test tree

`tests/test_agents.py` defines one fixture, `agents_tree(tmp_path)`, that later tasks import.
It mirrors kubed-io/skills at `d8a83e5` in the parts that matter:

```
market/.claude-plugin/marketplace.json   name "kubed"; entries, in this order:
                                           drawio  (source ./plugins/drawio, category diagrams)
                                           extra   (source ./plugins/extra,  category other)
market/plugins/drawio/.claude-plugin/plugin.json
                                         name drawio; keywords drawio, diagrams.net, diagrams,
                                         mxgraph, mcp
market/plugins/drawio/agents/diagrammer.md
                                         name diagrammer, a description, model sonnet,
                                         color cyan, no tools; body cites
                                         ${CLAUDE_PLUGIN_ROOT}/skills/drawio/SKILL.md
                                         and ${CLAUDE_PROJECT_DIR}
market/plugins/drawio/skills/drawio/SKILL.md
market/plugins/drawio/.mcp.json          {"mcpServers": {"drawio": {...}}}
market/plugins/extra/.claude-plugin/plugin.json   name extra; keywords extra
market/plugins/extra/agents/diagrammer.md          name diagrammer  (clashes)
market/plugins/extra/agents/db/migrate.md          name migrator    (subfolder)
market/plugins/extra/agents/broken.md              no description   (skipped)
market/plugins/extra/agents/twin-a.md, twin-b.md   both name twin   (second skipped)
lone/.claude-plugin/plugin.json          name lone; keywords lonely; only agents/solo.md
drive/agents/x.md                        declared bare: no agents (AGT-4)
```

The config has libraries `drawio` (the marketplace at `market/`), `lone` (plugin `lone`), and
`drive` (plugin `drive`, bare). Write it as `tests/test_marketplace.py` writes a marketplace
library. The test that runs uvicorn serves this tree on its own port, using
`tests/test_header_scope.py`'s `_free_port` pattern.

---

### Task 1: Harvest agents into the plugin record

**Files:**
- Create: `kubed/mcp_kb/catalogue/agents.py`
- Modify: `kubed/mcp_kb/catalogue/harvest.py`, `kubed/mcp_kb/catalogue/index.py`,
  `kubed/mcp_kb/catalogue/snapshot.py` (`with_manifest`, `build_plugin`)
- Test: `tests/test_agents.py` (new), `tests/test_index.py`

**Interfaces:**
- Produces, in `catalogue/agents.py`:

```python
@dataclass(frozen=True)
class ParsedAgent:
    name: str                       # the frontmatter name
    description: str                # whitespace collapsed
    capabilities: tuple[str, ...]
    model: str | None
    frontmatter: dict               # verbatim, JSON-safe
    body: str

def parse_agent(path: Path) -> ParsedAgent | str: ...   # a str is why it was skipped
def routing_hint(model: str | None) -> dict | None: ...  # AGT-9
ROLES = {"haiku": "small", "sonnet": "medium", "opus": "large"}
```

- Produces, in `catalogue/harvest.py`:
  `agent_files(root: Path, globs: Globs, *, claude_format: bool) -> list[tuple[Path, tuple[str, ...]]]`.
  It returns each agent file, sorted by path below the root, with its folder segments: the
  folders between `agents/` and the file for the default scan (`agents/**/*.md`), and `()` for a
  listed file. It returns `[]` when `claude_format` is false. Hidden files are excluded, as
  everywhere. Also `agent_paths(root, globs, *, claude_format) -> tuple[Path, ...]`: the
  `agents/` directory and every listed file, which Task 3 refuses.
- Produces, in `catalogue/index.py`: `AgentRow(path: str, name: str)`, where `name` is the
  plugin-local served name, `"_".join((*segments, frontmatter_name))`, with no library.
  `PluginRecord` gains `agents: tuple[AgentRow, ...] = ()`, `agent_paths: tuple[str, ...] = ()`
  and `servers: tuple[str, ...] = ()`, all three read back in `_plugin_record_from_dict`.
  `INDEX_VERSION` goes up by one from what main has.
- `with_manifest` also returns whether the plugin is Claude-format: a `plugin.json` was found, or
  `plugin.marketplace is not None`. Carry it the way parity left `Globs`, either a field on
  `Globs` or a third return value. The caller in `server.py` and `effective_globs` follow.

- [ ] **Step 1: Write the failing tests** in `tests/test_agents.py`, all `unit`:
  - `test_parse_agent_reads_name_description_and_model`: diagrammer parses, `model == "sonnet"`,
    `frontmatter["color"] == "cyan"`, and the body is the text after the frontmatter.
  - `test_an_agent_without_a_description_is_a_reason`: `broken.md` gives a `str` naming
    `description`. Do the same for a missing `name`, a non-string `name`, frontmatter that does
    not parse, and frontmatter with no JSON form (an unquoted date is fine once converted; a
    `.nan` is not). Reuse the JSON check `uris.py::skill_entry` makes (`allow_nan=False`).
  - `test_capabilities_are_a_list_of_strings_or_nothing`: `["a", "b"]` is kept, while `"a"` and
    `[1]` give `()`.
  - `test_routing_hint`: `haiku`, `sonnet`, `opus` → small, medium, large, each with
    `vision: False`. `inherit`, `None` and `claude-sonnet-4-5` → `None`.
  - `test_the_default_scan_adds_a_segment_per_folder`: the `extra` plugin harvests `diagrammer`,
    `db_migrator`, `twin` and `twin`, in path order, and `broken.md` lands in `skipped` with its
    reason.
  - `test_a_listed_agent_has_no_folder_segment`: a `plugin.json` listing
    `./agents/db/migrate.md` harvests just `migrator`, and only that file.
  - `test_a_bare_plugin_has_no_agents`: `drive` records `agents == ()` and `agent_paths == ()`.
  - `test_servers_are_names_only`: drawio's `servers == ("drawio",)`. A `.mcp.json` that does not
    parse leaves `servers` from the manifest alone, and adds a `skipped` row for `.mcp.json`.
  - In `tests/test_index.py`: a record with agents round-trips through `Index.write`/`read`,
    and an index at the previous version reads as `None`.

- [ ] **Step 2: Run them and watch them fail.**
  Run: `pytest tests/test_agents.py tests/test_index.py -v`
  Expected: FAIL (no `catalogue.agents`, no `AgentRow`).

- [ ] **Step 3: Implement.**
  - `parse_agent` uses `frontmatter.loads` on the file's text (`utf-8`, `errors="replace"`). It
    returns a reason string for every failure in AGT-6 and never raises on bad content. An
    `OSError` propagates, because `build_plugin` turns it into a failed plugin, as for prompts.
  - `build_plugin`, inside the existing `try`: for each `(path, segments)` from `agent_files`,
    parse it. On success, append `AgentRow(str(path), "_".join((*segments, parsed.name)))`. On a
    reason, append `(path, reason)` to `unloadable`, which already becomes `skipped`. Then read
    the server names: the keys of `mcpServers` in `readable(root, ".mcp.json")` when it is an
    object, plus parity's manifest and entry names, deduplicated and sorted.
  - Keep `build_plugin`'s signature apart from what is needed to pass `claude_format` in.

- [ ] **Step 4: Run them and watch them pass.** Then run the whole suite.
  Run: `ruff check . && pytest tests/test_agents.py tests/test_index.py -v && pytest`
  Expected: clean, all PASS. No other test changes: nothing serves agents yet.

- [ ] **Step 5: Commit.** `Harvest plugin agents into the plugin record`

---

### Task 2: Claim names per library and hold the roster in the catalogue

**Files:**
- Modify: `kubed/mcp_kb/catalogue/agents.py` (`Agent`, `AgentRoster`),
  `kubed/mcp_kb/catalogue/snapshot.py` (`_Admitted`, `_admit`, `_serve_library`,
  `build_snapshot`, `_plugin_status`, `log_changes`), `kubed/mcp_kb/catalogue/uris.py`
  (`Catalogue`)
- Test: `tests/test_agents.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class Agent:
    name: str                      # served: library-prefixed, maybe "@<plugin name>"
    library: str
    plugin: str                    # plugin id
    root: Path                     # plugin root
    path: Path
    parsed: ParsedAgent            # as of this snapshot
    servers: tuple[str, ...]
    category: str | None
    tags: frozenset[str]
    library_categories: frozenset[str] = frozenset()
    live: bool = False

class AgentRoster:
    def __init__(self, agents: Sequence[Agent]): ...
    def visible(self, scope: Scope = EVERYTHING) -> list[Agent]: ...   # name order
    def get(self, name: str, scope: Scope = EVERYTHING) -> Agent | None: ...
    def __len__(self) -> int: ...
```

  `Agent.admits(scope)` is `scope.admits(library, category, tags,
  library_categories=...)`, the call `skills._admits` makes.
- `Catalogue.__init__` gains `agents: AgentRoster | None = None`. New methods, each taking a
  `Scope`:
  - `agent_cards(scope) -> list[dict]`: `{"name", "description", "capabilities"}` for each
    visible agent, in name order.
  - `agent_definition(name, scope) -> dict | None`: AGT-9's result *without* the envelope and
    *without* the gateway prefix. `instructions` is `placeholders.substitute(body,
    plugin_root=f"{SCHEME}{library}", skills=self.plugin_skill_dirs(library, plugin, scope))`,
    with no `skill_dir`, and omitted when blank. For a `live` agent it first revalidates the file
    and parses it again, and keeps `agent.parsed` when that fails, logging a warning (AGT-16).
    `None` covers absent and out of scope alike.
- `Snapshot.status` gains `agents` counts and, per library, `renamed` and `unserved` when they
  are not empty.

- [ ] **Step 1: Write the failing tests** (unit, built with `build_snapshot` from the fixture):
  - `test_names_follow_claude_code`: in `drawio`, the roster holds `drawio_diagrammer`,
    `drawio_diagrammer@extra`, `drawio_db_migrator` and `drawio_twin`. In `lone`, it holds
    `lone_solo`. `drive` holds nothing.
  - `test_a_clash_is_renamed_and_reported`: `status["libraries"]["drawio"]["renamed"] ==
    {"drawio_diagrammer@extra": "drawio_diagrammer is already served by plugin 'drawio@drawio'"}`.
  - `test_a_clash_on_the_renamed_name_is_unserved`: give a third plugin an agent named
    `diagrammer@extra`, ahead of `extra` in the library. `extra`'s diagrammer is then absent, and
    `unserved` holds `{"plugin": "extra@drawio", "path": "agents/diagrammer.md", "reason": …}`.
  - `test_a_twin_in_one_plugin_is_skipped`: `twin-b.md` is in `extra`'s plugin `skipped` with
    `agent twin is already served by agents/twin-a.md`.
  - `test_an_appended_plugin_renames_nothing`: append a plugin with a `diagrammer` agent to the
    library. Every name served before is still served, and the new one is `…@<its name>`.
  - `test_a_prepended_plugin_takes_the_short_name`: the boundary of the promise, as AGT-8 states
    it.
  - `test_a_conflicting_plugin_serves_no_agents`: a plugin that LIB-28 fails in a library serves
    no agents there.
  - `test_counts`: drawio's plugin `agents == 1`, extra's `agents == 3` (diagrammer, migrator,
    one twin), and library `drawio`'s `agents == 4`.
  - `test_cards_and_definition_under_scope`: `agent_cards(Scope.parse(tags="diagrams"))` is
    drawio's diagrammer alone, and `Scope.parse(categories="other")` is extra's three.
    `agent_definition("drawio_diagrammer", Scope.parse(tags="extra"))` is `None`.
  - `test_instructions_render_like_a_prompt`: diagrammer's instructions contain
    `skill://drawio/drawio/SKILL.md` and `${CLAUDE_PROJECT_DIR}` as written, and
    `routing == {"role": "medium", "vision": False}`.
  - `test_meta_names_servers_and_keeps_frontmatter`:
    `_meta["io.kubed.mcp-kb/agent"] == {"plugin": "drawio@drawio", "library": "drawio",
    "path": "agents/diagrammer.md", "frontmatter": {...verbatim...}, "servers": ["drawio"]}`.
  - `test_a_live_agent_is_reread` (with a revalidate stub): an edited body is served on the next
    definition, and a broken edit serves the last parsed copy.

- [ ] **Step 2: Run them and watch them fail.**
  Run: `pytest tests/test_agents.py -v`

- [ ] **Step 3: Implement.**
  - `_Admitted` gains `agents: list[AgentRow]`. `_admit` keeps the first row of each local name in
    path order and skips the rest, using the existing `skip` (AGT-6).
  - In `_serve_library`, after a plugin passes `claims.conflict(...)`, claim its agents against a
    per-library `taken: dict[str, str]` (name → plugin id):

```python
for row in admitted[pid].agents:
    base = f"{lib.name}_{row.name}"
    name = base if base not in taken else f"{base}@{plugin.name}"
    if name in taken:
        unserved.append({
            "plugin": pid,
            "path": _relative(Path(row.path), root),
            "reason": f"{base} and {name} are already served",
        })
        continue
    if name != base:
        renamed[name] = f"{base} is already served by plugin '{taken[base]}'"
    taken[name] = pid
    parsed = parse_agent(Path(row.path))
    if isinstance(parsed, str):  # vanished or broken since the harvest
        gone.append((Path(row.path), parsed))
        continue
    agents.append(Agent(name=name, ...))
```

    A row whose file broke since the harvest is reported like a vanished prompt, under the plugin
    (`vanished`). The name it claimed stays claimed for this snapshot. That keeps the rename table
    a function of the rows alone.
  - `_serve_library` returns the library's agents too. `build_snapshot` builds
    `AgentRoster(all_agents)` and hands it to `Catalogue`.
  - Counts: add `"agents"` to the library `entry` and to the `counts` that `served` records, and
    to `_plugin_status`'s fallback counts (`len(admitted.agents)`). Add `"agents"`, `"renamed"`
    and `"unserved"` to `log_changes`' `watched`, and log a rename and an unserved agent once each,
    as conflicts are logged.

- [ ] **Step 4: Run them and watch them pass.** Then run the whole suite.
  Run: `ruff check . && pytest tests/test_agents.py -v && pytest`
  Expected: clean, all PASS. `tests/test_openapi.py` may now fail on the new `/health` keys.
  If so, leave it for Task 5, and say so in the commit body.

- [ ] **Step 5: Commit.** `Claim agent names per library and hold the roster in the catalogue`

---

### Task 3: The plugin-root fallback refuses agent files (AGT-3)

**Files:**
- Modify: `kubed/mcp_kb/catalogue/skills.py` (`_Root`, `LibraryFiles.add`, `read_any`,
  `read_under`), `kubed/mcp_kb/catalogue/snapshot.py` (the `resources.add` call)
- Test: `tests/test_agents.py`, and `tests/test_plugin_root.py`, run unchanged

**Interfaces:**
- `LibraryFiles.add(..., agent_paths: Sequence[Path] = ())`. `_Root` gains
  `agents: tuple[Path, ...]`, resolved. A private `_agent_paths(library)` gathers them across the
  library's roots, as `_skill_dirs` does.
- `read_any` and `read_under` refuse a target that is one of those paths, or lies under one
  (`_inside`). `read` and `files` do not: the harvested list is the operator's `files` glob
  (decision 3).

- [ ] **Step 1: Write the failing tests** (unit, through `Catalogue.read`):
  - `test_the_library_fallback_refuses_an_agent_file`:
    `read("skill://drawio/agents/diagrammer.md")` is `None`.
  - `test_the_skill_fallback_refuses_an_agent_file`:
    `read("skill://drawio/drawio/agents/diagrammer.md")` is `None`.
  - `test_a_listed_agent_file_is_refused_wherever_it_sits`: a manifest listing
    `./roles/reviewer.md` makes `skill://<lib>/roles/reviewer.md` read `None`.
  - `test_an_operator_files_glob_still_serves_agents`: a declared Claude-format plugin with
    `files: ["agents/**/*.md"]` lists `agents/…` in `_files.md`, and reads it.
  - `test_a_bare_plugins_agents_folder_is_not_guarded`: `drive`'s `agents/x.md` still reads
    through the fallback, as it does today (AGT-4: it has no agents).

- [ ] **Step 2: Run and fail.** Run: `pytest tests/test_agents.py -k fallback -v`

- [ ] **Step 3: Implement.** Pass `[Path(p) for p in records[pid].agent_paths]` from
  `_serve_library` into `resources.add`.

- [ ] **Step 4: Run and pass**, with the plugin-root and address tests unchanged.
  Run: `ruff check . && pytest tests/test_agents.py tests/test_plugin_root.py tests/test_uris.py -v && pytest`

- [ ] **Step 5: Commit.** `Keep agent files out of the plugin-root fallback`

---

### Task 4: `agents/list` and `agents/get`

**Files:**
- Create: `kubed/mcp_kb/mcp/agents.py`
- Modify: `kubed/mcp_kb/mcp/request.py` (`AGENTS_EXTENSION_ID`), `kubed/mcp_kb/mcp/skills.py`
  (share the scope check and the envelope; generalise the legacy advertiser),
  `kubed/mcp_kb/mcp/pins.py` (`_serving`), `kubed/mcp_kb/server.py` (wiring)
- Test: `tests/test_agents_extension.py` (new)

**Interfaces:**
- `AGENTS_EXTENSION_ID = "io.modelcontextprotocol/agents"` beside `EXTENSION_ID` in
  `mcp/request.py`.
- Lift `SkillsExtension._scope` and `_result` into module functions in `mcp/skills.py`:
  `checked_scope(problem: Callable[[Scope], str | None]) -> Scope` and
  `complete(**fields) -> dict`. Both extensions call them, and `SkillsExtension`'s behaviour is
  unchanged.
- Rename `AdvertiseLegacySkills` to `AdvertiseLegacyExtensions(declared: Mapping[str, dict])`. It
  merges every id into `initialize`'s `capabilities.extensions`. `server.py` passes
  `{EXTENSION_ID: {}, AGENTS_EXTENSION_ID: {"listChanged": False}}`.
- **`server/discover`'s value.** Find out what FastMCP's `ServerExtension` declares for a
  registered extension; read the installed `fastmcp/server/extensions` source. If it can declare
  a value, declare `{"listChanged": False}` there. If it can only declare `{}`, set the value on
  `server/discover`'s answer in the same middleware, using the hook `ScopedInstructions` already
  uses on that answer. Either way, AGT-1's value is what both eras see.
- `mcp/agents.py`:

```python
class GetAgentParams(RequestParams):
    name: str = Field(min_length=1)

class AgentsExtension(ServerExtension):
    identifier = AGENTS_EXTENSION_ID
    def __init__(self, catalogue: Callable[[], Catalogue],
                 scope_problem: Callable[[Scope], str | None]): ...
    def methods(self) -> Sequence[MethodBinding]:
        return (
            MethodBinding("agents/list", PaginatedRequestParams, self.list_agents),
            MethodBinding("agents/get", GetAgentParams, self.get_agent),
        )
```

  `list_agents` refuses any `cursor` with `MCPError(INVALID_PARAMS, "Invalid agents cursor")` and
  returns `complete(agents=catalogue.agent_cards(scope))`. `get_agent` returns
  `complete(**definition)`, with `instructions` passed through `requested_addressing().text(...)`.
  A `None` raises `MCPError(code=INVALID_PARAMS, message="Agent not found",
  data={"reason": "agent_not_found"})`. Check that the installed `mcp.shared.exceptions.MCPError`
  takes `data`, and use whatever spelling it has.
- `pins._serving` also returns true when `snapshot.catalogue.agent_cards(scope)` is non-empty
  (SCP-31 rows 8 and 9).
- `server.py` registers `AgentsExtension(lambda: self.snapshot.catalogue, lambda scope:
  what_is_wrong(scope, config, self.snapshot))` beside `SkillsExtension`.

- [ ] **Step 1: Write the failing tests.** In-process, `@pytest.mark.parametrize("mode",
  ["auto", "legacy"])`, using the `request` helper `tests/test_skills_extension.py` defines:
  - `test_both_extensions_are_declared`: `caps.extensions[AGENTS_EXTENSION_ID] ==
    {"listChanged": False}`, and the skills id is still `{}`.
  - `test_list_returns_cards`: `resultType == "complete"`, `ttlMs == 0`,
    `cacheScope == "private"`, and the cards are exactly `{name, description, capabilities}`.
  - `test_get_returns_the_definition`: for `drawio_diagrammer`, check `agent`, the
    `instructions`, `modelRoutingHint == {"role": "medium", "vision": False}`, `tools == []` and
    the `_meta` from Task 2.
  - `test_unknown_is_agent_not_found`: `-32602`, `Agent not found`,
    `data == {"reason": "agent_not_found"}`.
  - `test_a_cursor_is_refused`: `-32602`, `Invalid agents cursor`.
  - `test_nothing_else_changes`: `list_tools()`, `list_resources()` and `list_prompts()` are the
    same as for a server over the same tree with every `agents/` folder removed.
  - `test_a_prefix_reaches_instructions_only`: with `Kb-Resource-Prefix: kb+`,
    `instructions` has `kb+skill://drawio/drawio/SKILL.md`, and `_meta.frontmatter` is unchanged.

  Over real uvicorn (`integration`, a module fixture serving `agents_tree`):
  - `test_tag_and_category_scope_list_the_diagrammer`: `?tag=diagrams`, `Kb-Tag: diagrams` and
    `?category=diagrams` each list exactly `drawio_diagrammer`.
  - `test_out_of_scope_is_agent_not_found`: under `Kb-Tag: extra`, `agents/get
    drawio_diagrammer` fails exactly as an unknown name does: the same code, message and data.
  - `test_a_scoped_caller_sees_the_library_name`: under `Kb-Category: other`, the list holds
    `drawio_diagrammer@extra`, not `drawio_diagrammer`.
  - `test_a_scope_of_only_agents_is_served`: `Kb-Tag: lonely` lists `lone_solo`, not a refusal.
  - `test_a_refused_scope_fails_both_methods`: `Kb-Tag: nonesuch` fails `agents/list` and
    `agents/get` with `-32602` and SCP-31 row 7's message.
  - `test_a_library_scope`: `Kb-Library: lone` lists `lone_solo` only.

- [ ] **Step 2: Run and fail.** Run: `pytest tests/test_agents_extension.py -v`

- [ ] **Step 3: Implement**, as the interfaces say.

- [ ] **Step 4: Run and pass**, with the Skills extension tests unchanged.
  Run: `ruff check . && pytest tests/test_agents_extension.py tests/test_skills_extension.py tests/test_header_scope.py tests/test_boundaries.py -v && pytest`

- [ ] **Step 5: Commit.** `Serve agents/list and agents/get`

---

### Task 5: `/health` and the published contract

**Files:**
- Modify: `kubed/mcp_kb/routes.py` (`report`), `kubed/mcp_kb/spec/builder.py`
  (`PLUGIN_STATUS`, `LIBRARY_STATUS`, `HEALTH`)
- Regenerate: `wiki/Endpoints.md` (`scripts/generate_wiki.py`)
- Test: `tests/test_openapi.py`, `tests/test_server.py` (or wherever `/health` is asserted)

- [ ] **Step 1: Write the failing tests:** `/health` has a top-level `agents` equal to
  `len(roster)`. With the agents tree, the body validates against the published schema, including
  a library with `renamed` and `unserved`.

- [ ] **Step 2: Implement.**
  - `report()` adds `"agents": len(snapshot.catalogue.agents)`. Expose a count, not the roster
    itself, if that reads better.
  - `builder.py`: `agents` is an integer in each of the three schemas, required wherever
    `prompts` is required.
  - `LIBRARY_STATUS.renamed` is `additionalProperties: string`, described as "Present when a
    later plugin's agent took `<name>@<plugin>`: keyed by the served name, the value says who has
    the short one." `unserved` is an array of `{plugin, path, reason}`.
  - `PluginStatus.skipped`'s description mentions agent files.

- [ ] **Step 3: Verify the contract.**
  Run: `python scripts/generate_openapi.py && npx --yes @redocly/cli@2 lint openapi.yaml`
  (lint.yml's check; skip the lint only if `npx` is missing, and say so), then
  `python scripts/generate_wiki.py && python scripts/generate_wiki.py --check`, then
  `ruff check . && pytest tests/test_openapi.py tests/test_wiki.py -v && pytest`.
  Expected: clean. `tests/test_wiki.py` runs, not skipped.

- [ ] **Step 4: Commit** the regenerated `wiki/Endpoints.md` inside `wiki/` (no push). Then commit
  the superproject with the pointer: `Count agents in /health`.

---

### Task 6: Spec, docs and changelog

**Files:**
- Modify: `docs/superpowers/specs/agents.md`, `scoping-and-instructions.md`,
  `http-and-tools.md`, `skills.md`, `AGENTS.md`, `README.md`, `CHANGELOG.md`
- Modify (submodule `wiki/`): `Plugins.md`, `Scoping.md`, `Agentgateway.md`

- [ ] **Step 1: The spec, now true of the code.**
  - `agents.md`: drop every *(proposed)*. The opening's "Every requirement in this file is
    proposed" becomes "The extension is experimental, and kb follows the draft named above."
  - SCP-21: "…to skills, prompts, agents and library-level files alike, … `skills/list`,
    `skills/get`, `agents/list`, `agents/get` and the four mirror tools."
  - SCP-24: add "`agents/get` (`Agent not found`, with `data.reason: "agent_not_found"`)".
  - SCP-29: "`initialize`, `server/discover`, `skills/list`, `skills/get`, `agents/list` and
    `agents/get` are refused alike".
  - SCP-31 row 9: "…would be shown no listing row, no prompt and no agent".
  - HTTP-8: add the row `| agents | agents currently served, across libraries |` after `prompts`.
  - HTTP-27: "Both answers advertise the `io.modelcontextprotocol/skills` and
    `io.modelcontextprotocol/agents` extensions. Their methods are in skills.md and agents.md."
  - HTTP-29's last sentence: "The Skills and Agents extensions' own results are in skills.md and
    agents.md."
  - SKL-30 and SKL-31: append "Neither serves an agent file (AGT-3)."
  - Keep every ID, and reuse none.
- [ ] **Step 2: AGENTS.md.** Add `mcp/agents.py` and `catalogue/agents.py` to the Layout table.
  After the Skills extension paragraph in *The surface*, add one paragraph on the Agents
  extension. It is a separate surface: no rows, tools or instructions. Names are the library's,
  claimed in library order, and kb stores no owner. Agent files never go through the plugin-root
  fallback. A request can't widen the scope, and no method takes a scope param.
- [ ] **Step 3: README.** After the Skills extension paragraph, add one paragraph. It says that
  agent-aware clients can call `agents/list` and `agents/get`, that this is **experimental** and
  follows the MCP Agent Discovery draft (agents-wg proposal 0000 at `137d88b`), and that the same
  scopes apply. Link the wiki section. `tests/test_readme.py` must pass.
- [ ] **Step 4: Wiki** (commit inside `wiki/`, no push):
  - `Plugins.md`, a new section "Agents (experimental)". It covers which files are agents, how
    names fall out (the table in *Design*), what `agents/get` returns, and that kb never runs the
    plugin's MCP servers.
  - `Scoping.md`: show an agents client scoped by `Kb-Tag: diagrams` or
    `?category=diagrams`.
  - `Agentgateway.md`: `agents/*` is refused through agentgateway until agentgateway#3579, like
    `skills/*`.
- [ ] **Step 5: Changelog,** under `[Unreleased]` → `### Added`, one line:
  `- Discover the agents your plugins ship through the experimental \`agents/list\` and \`agents/get\`, scoped like everything else.`
- [ ] **Step 6: Verify everything CI runs.**
  Run: `ruff check . && pytest`, then `python scripts/generate_wiki.py --check`, then
  `python scripts/generate_openapi.py`, then
  `python -m kubed.mcp_kb schema | diff - config.schema.json` (expected: no diff, because no
  config key changed).
  Expected: clean, all PASS, `tests/test_wiki.py` not skipped.
- [ ] **Step 7: Commit** the wiki first, inside `wiki/`, without pushing. Then the superproject:
  `Document the agents extension`.

## Acceptance, after deploy (Dr K, not CI)

Against kubed-io/skills at `d8a83e5`, with a library named `drawio` over the `kubed` marketplace:

- `agents/list` with `Kb-Library: drawio` returns one card, `drawio_diagrammer`, with
  `capabilities: []`.
- `agents/get` returns the body, `{"role": "medium", "vision": false}`, `tools: []`,
  `servers: []` (no `.mcp.json` there), and the frontmatter.
- `skill://drawio/agents/diagrammer.md` no longer reads.
- `/health` shows `agents: 1` for `drawio@drawio`.
- Through agentgateway, `agents/*` is refused until agentgateway#3579. That is expected.
