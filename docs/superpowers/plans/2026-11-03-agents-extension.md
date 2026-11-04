# plugin.json Parity and the Agents Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** kb reads a `plugin.json` and a marketplace entry the way Claude Code does. On top of
that, a client calls `agents/list` and `agents/get` and gets the agents that Claude-format plugins
ship. They are scoped by the connection's library, category and tag, and named as Claude Code
names them. drawio's `agents/diagrammer.md` is served as `drawio_diagrammer`.

**Architecture:** Part A comes first.
- `plugins/manifest.py` reads every component key into one `Components` value, and both a
  manifest and a marketplace entry produce one.
- `snapshot.with_manifest` merges the two with the config by Claude Code's rules (add, replace,
  append, conflict).
- Prompt names come from where a file was found.

Part B builds on it.
- The harvest records agent files as rows on the `PluginRecord`.
- The snapshot claims agent names per library, in library order, into an `AgentRoster` that
  `Catalogue` holds and answers under a `Scope`.
- `mcp/agents.py` is a FastMCP `ServerExtension` beside `mcp/skills.py`.
- The plugin-root fallback refuses agent files, and `/health` counts agents.

**Tech Stack:** Python ≥3.11, FastMCP 4 (`ServerExtension`, `MethodBinding`), pydantic, PyYAML,
python-frontmatter, pytest + pytest-asyncio, uvicorn.

**Spec:**
- **Part A:** [plugins-and-libraries.md](../specs/plugins-and-libraries.md), the section *Proposed:
  reading a plugin the way Claude Code does*: PLG-20 to PLG-27 and LIB-30 to LIB-33, with the
  table there of what each one supersedes.
- **Part B:** [agents.md](../specs/agents.md), AGT-1 to AGT-16.

Both are still *(proposed)*, until Tasks 5 and 11. The why is in the design
[2026-11-02-agents-extension-design.md](2026-11-02-agents-extension-design.md). Its History header
says what this plan overtakes. Brief and decisions: issue #33, PR #35.

## Design

**The rule for everything (Dr K): do what Claude Code does.** Both specs are complete for what they
cover. This section records the decisions behind them, and what they mean for the code.

**Decided (Dr K, issue #33 and PR #35):**

1. **One PR, parity first.** Part A's tasks come before Part B's, and the extension builds on
   their interfaces. Commands in subfolders are in Part A, with PLG-18's clash keyed on the prompt
   name (PLG-25).
2. **A clash between agents keeps both, and never drops a plugin (AGT-8).** The first plugin in
   library order keeps `<library>_<name>`. A later plugin's agent is served as
   `<library>_<name>@<plugin name>`, and the library's `renamed` in `/health` says so. If that
   name is taken too, only that agent is left unserved. kb stores no owner anywhere. The only
   promise is that a plugin *appended* to a library renames nothing.
3. **An operator `files` glob over `agents/` serves those files as library files.** AGT-3
   refuses only the plugin-root fallback.
4. **Scope comes from the connection (AGT-15).** No method takes a scope param, because SCP-9
   already forbids one.
5. **`modelRoutingHint` by family (AGT-9).** `opus` → `large`, `sonnet` → `medium`, `haiku` →
   `small`, alias or full id. It is omitted only for `inherit`, a missing `model`, or a value
   naming none of the three.
6. **Kept as proposed:**
   - one page, and any `cursor` is `-32602`;
   - `ttlMs: 0`;
   - `_meta.frontmatter` verbatim, with the gateway prefix on `instructions` only;
   - `agents/a/x.md` and `agents/b/x.md` are two agents, `…_a_x` and `…_b_x`;
   - `renamed` and `unserved` under a library in `/health`.

**My calls, now in the spec, open to Dr K before `plan approved`:**

- **PLG-21:** a map item's `description` and `argumentHint` are used ahead of the source
  file's own frontmatter. The design said "fill", which was ambiguous, and the manifest is the
  publisher's later word.
- **PLG-21, PLG-26:** a bad map item, and every other manifest defect that isn't a file, becomes
  a **note** under the plugin. It is not a `skipped` row, which keeps `{path, reason}` for files.
- **LIB-31:** a conflicting `strict: false` entry **fails the plugin** (PLG-19). Skipping it at
  marketplace read time isn't possible: whether a `plugin.json` exists is only known once the
  entry's own tree is fetched, which may be another repository.
- **PLG-25:** the `prompts/**/*.md` convention keeps naming by file stem. Only `commands/` trees,
  and directories a `commands` declaration names, add folder segments, because those are Claude
  Code's commands.

**How a plugin's components merge (`with_manifest`, Part A).** "Manifest" means `plugin.json`,
"entry" its marketplace entry, and "config" a declared plugin's own keys:

| Kind | Rule, first that applies |
|---|---|
| skills | config `skills` → exactly it (LIB-33). An entry at the marketplace root that lists `skills` → the entry's plus the manifest's, no conventions (LIB-32). Otherwise → the conventions + manifest + entry (PLG-20, LIB-30) |
| prompts | config `prompts` → exactly it (LIB-33). The manifest or the entry sets `commands` → manifest + entry, no conventions (PLG-21, LIB-30), with PLG-23's note if `commands/` exists. Otherwise → the conventions |
| agents | not Claude-format → none (AGT-4). The manifest or the entry sets `agents` → manifest + entry (PLG-22, LIB-30), with PLG-23's note if `agents/` exists. Otherwise → `agents/**/*.md` |
| conflict | a manifest exists, the entry has `strict: false` and names any of `skills`, `commands`, `agents`, `hooks`, `outputStyles`, `themes` → the plugin fails with `conflicting manifests` (LIB-31) |

A plugin is **Claude-format** when it has a manifest or is a marketplace entry.

**How names fall out:**

| Where, in library `lib` | Served as |
|---|---|
| `commands/db/migrate.md` (convention, or a declared `commands` dir `commands`) | prompt `lib_db_migrate` |
| `prompts/sub/debug.md` | prompt `lib_debug`, as today |
| manifest `commands: {"about": {"content": "…"}}` | prompt `lib_about` |
| `agents/diagrammer.md`, frontmatter `name: diagrammer` | agent `lib_diagrammer` |
| `agents/db/migrate.md`, `name: migrator` | agent `lib_db_migrator` |
| the same file listed in `agents: ["./agents/db/migrate.md"]` | agent `lib_migrator` |
| a later plugin `extra`'s `agents/diagrammer.md` | agent `lib_diagrammer@extra` |
| `agents/x.md` in a plugin declared bare | nothing (AGT-4) |

**What does not change:**
- `tools/list`, `resources/list`, `prompts/list` and the server `instructions` (INS-6 counts skills
  only);
- the `skill://` grammar;
- LIB-28 and LIB-29 between plugins;
- `config.schema.json`, since no config key is added.

## File Structure

| File | Responsibility in this plan |
|---|---|
| `kubed/mcp_kb/plugins/manifest.py` | `Components`, `CommandEntry`, `read_components`: one reader for a manifest's and an entry's component keys |
| `kubed/mcp_kb/plugins/__init__.py` | `Globs` and `Plugin` gain the fields the merge produces |
| `kubed/mcp_kb/plugins/marketplace.py` | entries keep their `Components`; `strict: false` is no longer skipped here |
| `kubed/mcp_kb/catalogue/snapshot.py` | `with_manifest` merges; `_admit` keys prompts on name and agents on name; libraries claim agent names |
| `kubed/mcp_kb/catalogue/harvest.py` | `commands/**/*.md`; `COMMAND_DIRS` moves here; `agent_files`, `agent_paths` |
| `kubed/mcp_kb/catalogue/prompts/__init__.py` | `PromptSource`, `prompt_name`; `load_prompts` takes sources |
| `kubed/mcp_kb/catalogue/index.py` | `PromptRow` and `AgentRow` rows; `INDEX_VERSION` + 1 |
| `kubed/mcp_kb/catalogue/agents.py` (new) | `parse_agent`, `routing_hint`, `Agent`, `AgentRoster`; no FastMCP |
| `kubed/mcp_kb/catalogue/uris.py` | `Catalogue.agent_cards`, `Catalogue.agent_definition` |
| `kubed/mcp_kb/catalogue/skills.py` | `LibraryFiles` refuses agent paths in the fallback |
| `kubed/mcp_kb/mcp/agents.py` (new) | `AgentsExtension` |
| `kubed/mcp_kb/mcp/skills.py`, `request.py`, `pins.py`, `server.py` | shared envelope, both ids declared, agents count toward SCP-31, wiring |
| `kubed/mcp_kb/routes.py`, `spec/builder.py` | `/health` fields and their schema |

## Global Constraints

- **Toolchain** (CI's `test.yml`): `pip install -e ".[test]"`, then `ruff check .` and `pytest`
  from the repository root. Check out the `wiki/` submodule (`git submodule update --init`), so
  `tests/test_wiki.py` runs rather than skips.
- **Python 3.11 is the floor.** No 3.12+ construct, and no backslash inside an f-string
  expression. Lines are at most 88 columns. A glob in code is `dir/**/*.md`, never one with a
  trailing `**`. Every new module starts with `from __future__ import annotations` and a docstring
  saying why it exists.
- **`catalogue/` and `plugins/` import no FastMCP** (`tests/test_boundaries.py`).
- **Read through the getter.** The extension is handed `lambda: self.snapshot.catalogue`.
- **Every `Catalogue` method takes a `Scope`**, and an out-of-scope agent is answered exactly as
  an absent one is.
- **Nothing fetched is executed.** `hooks`, `.mcp.json` and `mcpServers` are read for names or
  presence only. kb never connects to, starts or forwards a server (AGT-11).
- **No cache path in `/health`.** Every path and reason goes through `_relative` / `unrooted`, and
  every note through `scrub`.
- **A wrong-typed manifest field still fails the plugin** (PLG-15), naming the field. An object
  `commands` is no longer wrong-typed. A wrong-typed entry field still skips the entry (LIB-19).
- **The regression tests pass unchanged:** `tests/test_example_config.py`'s grafana and penpot
  tests (`test_an_entrys_skills_list_is_what_that_plugin_serves`,
  `test_a_declared_command_is_the_prompt_and_its_neighbour_is_not`). A test that pins behaviour
  this plan supersedes is updated in the task that supersedes it, and the commit body names each
  one.
- **Markers:** a test with no server is `@pytest.mark.unit`. One that runs uvicorn is
  `integration`.
- **Don't grow the shared trees in `tests/conftest.py`.** Other tests count what they hold.
- **Public repo:** no names or real hostnames in code, tests or docs. The maintainer is Dr K.
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **grafana's seven root entries still each serve only their own skills** once a manifest's
   `skills` adds (PLG-20). Without LIB-32, every entry claims all of them and six fail with LIB-28
   conflicts. → Task 3, `test_seven_root_entries_each_serve_their_own_skills`.
2. **A plugin's served skills grow when its manifest lists `skills`**, because the conventions
   now come along. A manifest that listed `./skills/a` to *hide* `skills/b` now serves both, as
   Claude Code does. → Task 3, `test_a_manifest_skills_list_adds_to_the_conventions`.
3. **Names are the library's, not the caller's.** A tag scope that sees only `extra` still sees
   `drawio_diagrammer@extra`. → Task 9, `test_a_scoped_caller_sees_the_library_name`.
4. **Out of scope looks exactly like absent:** the same code, message and `data`. → Task 9,
   `test_out_of_scope_is_agent_not_found`.
5. **A plugin that ships only agents** is a scope that names something. SCP-31 row 9 must not
   refuse it. → Task 9, `test_a_scope_of_only_agents_is_served`.

## The test trees

**Part A**, in `tests/test_parity.py` (new), helpers written as `tests/test_marketplace.py`
writes a marketplace and `tests/test_plugins.py` a manifest:

- `grafana_root(tmp_path)`: one marketplace, seven entries all `source: "./"`, each listing its own
  `skills` (copy the shape of `GRAFANA` in `tests/test_marketplace.py`). Add `skills/template`,
  which no entry lists, and no `plugin.json`.
- `penpot_root(tmp_path)`: `.claude-plugin/plugin.json` whose `commands` lists 8 files under
  `prompts/`. Add `prompts/README.md`, and one marketplace entry with no component keys.
- `object_map_root(tmp_path)`: a `plugin.json` whose `commands` is
  `{"brief": {"source": "./cmds/brief.md", "description": "Write a brief.", "argumentHint": "<topic>"}, "about": {"content": "Say what this plugin does."}, "bad": {"source": "./x.md", "content": "y"}}`.

**Part B**, the fixture `agents_tree(tmp_path)` in `tests/test_agents.py`, which later tasks import.
It mirrors kubed-io/skills at `d8a83e5` in the parts that matter:

```
market/.claude-plugin/marketplace.json  name "kubed"; entries, in order:
                                          drawio (./plugins/drawio, category diagrams)
                                          extra  (./plugins/extra,  category other)
market/plugins/drawio/.claude-plugin/plugin.json
                                        keywords drawio, diagrams.net, diagrams, mxgraph, mcp
market/plugins/drawio/agents/diagrammer.md
                                        name diagrammer, a description, model sonnet,
                                        color cyan; body cites
                                        ${CLAUDE_PLUGIN_ROOT}/skills/drawio/SKILL.md
                                        and ${CLAUDE_PROJECT_DIR}
market/plugins/drawio/skills/drawio/SKILL.md
market/plugins/drawio/.mcp.json         {"mcpServers": {"drawio": {}}}
market/plugins/extra/.claude-plugin/plugin.json  keywords extra
market/plugins/extra/agents/diagrammer.md        name diagrammer (clashes)
market/plugins/extra/agents/db/migrate.md        name migrator (subfolder)
market/plugins/extra/agents/broken.md            no description (skipped)
market/plugins/extra/agents/twin-a.md, twin-b.md both name twin (second skipped)
lone/.claude-plugin/plugin.json         keywords lonely; only agents/solo.md
drive/agents/x.md                       declared bare: no agents
```

Its libraries are `drawio` (the marketplace at `market/`), `lone` (plugin `lone`) and `drive`
(plugin `drive`). The uvicorn tests serve it on their own port, by `tests/test_header_scope.py`'s
`_free_port` pattern.

---

## Part A: plugin.json parity

### Task 1: Read every component key, from a manifest or an entry

**Files:**
- Modify: `kubed/mcp_kb/plugins/manifest.py`
- Test: `tests/test_plugins.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class CommandEntry:
    name: str                     # the map key
    source: str | None            # root-relative, escapes refused
    content: str | None
    description: str | None
    argument_hint: str | None

@dataclass(frozen=True)
class Components:
    skills: tuple[str, ...] | None = None       # "." is the plugin root
    commands: tuple[str, ...] | None = None     # patterns; () when only a map is set
    command_dirs: tuple[str, ...] = ()          # the directories among them
    command_map: tuple[CommandEntry, ...] = ()
    agents: tuple[str, ...] | None = None       # .md files only
    mcp_servers: tuple[str, ...] = ()           # names from an inline object
    mcp_files: tuple[str, ...] = ()             # paths a string mcpServers names
    named: frozenset[str] = frozenset()         # which of COMPONENT_KEYS are present
    notes: tuple[str, ...] = ()

COMPONENT_KEYS = ("skills", "commands", "agents", "hooks", "outputStyles", "themes")
def read_components(data: dict) -> Components: ...   # ValueError names a wrong-typed field
```

  `Manifest` keeps `name`, `description`, `version` and `keywords`, and its `skills` and `commands`
  fields become `components: Components`. `paths` and `command_patterns` stay public.
  `marketplace.py` uses them.

- [ ] **Step 1: Write the failing tests** in `tests/test_plugins.py`, all `unit`:
  - `test_a_command_directory_is_read_recursively`: `"commands": "./cmds"` gives
    `commands == ("cmds/**/*.md",)` and `command_dirs == ("cmds",)`. This replaces the assertion
    in `test_a_command_directory_becomes_a_markdown_glob`.
  - `test_an_object_map_of_commands_loads`: the `object_map_root` manifest gives two
    `CommandEntry`s. `brief` has `source="cmds/brief.md"`, `description="Write a brief."` and
    `argument_hint="<topic>"`. `about` has `content` set and `source=None`. Its `commands == ()`,
    and `notes` names `bad` and says it needs exactly one of `source` and `content`.
  - `test_a_map_item_that_is_not_an_object_is_a_note`: `"commands": {"x": "y"}` gives no entry and
    one note. The manifest still reads.
  - `test_dot_names_the_plugin_root`: `"skills": ["./", "."]` gives `skills == (".",)`.
  - `test_agents_keep_md_files_and_note_the_rest`: `"agents": ["./agents/a.md", "./agents",
    "./x.txt"]` gives `agents == ("agents/a.md",)` and two notes (AGT-5, PLG-22).
  - `test_a_path_without_dot_slash_is_kept_and_noted`: `"skills": ["skills/a"]` gives
    `skills == ("skills/a",)` and a note naming `skills/a` (PLG-24).
  - `test_mcp_servers_are_names_or_a_file`: `{"a": {}, "b": {}}` gives
    `mcp_servers == ("a", "b")`, `"./servers.json"` gives `mcp_files == ("servers.json",)`, and
    `3` gives a note.
  - `test_named_lists_every_component_key_present`: `{"hooks": "./h.json", "commands": []}` gives
    `named == {"hooks", "commands"}`.
  - `test_a_wrong_typed_agents_fails_the_manifest`: `"agents": 3` raises `ValueError` naming
    `agents`.
  - Update `test_penpots_manifest_shape_is_read_as_published` and
    `test_superpowers_manifest_shape_carries_keywords_and_nothing_else` to the new `Manifest`
    shape, with the same values.

- [ ] **Step 2: Run them and watch them fail.**
  Run: `pytest tests/test_plugins.py -v`
  Expected: FAIL (`Components` undefined).

- [ ] **Step 3: Implement** in `plugins/manifest.py`.
  - `_inside` keeps `"."` for `./` or `.`.
  - A path not starting `./` adds the note
    `<field> path '<path>' does not start with ./`.
  - Notes never quote anything but the item itself.

- [ ] **Step 4: Keep the one consumer working, and run everything.** `with_manifest` reads
  `manifest.components.skills` and `.commands` with today's semantics (Task 3 changes them).
  Run: `ruff check . && pytest tests/test_plugins.py -v && pytest`
  Expected: PASS.

- [ ] **Step 5: Commit.** `Read every component key of a plugin.json`

---

### Task 2: A marketplace entry keeps its components, and `strict` waits for the manifest

**Files:**
- Modify: `kubed/mcp_kb/plugins/__init__.py` (`Plugin`), `kubed/mcp_kb/plugins/marketplace.py`
  (`_plugin`, `_globs`)
- Test: `tests/test_marketplace.py`

**Interfaces:**
- Consumes: `read_components` (Task 1).
- Produces, on `Plugin`:
  - `entry: Components | None = None`, the entry's components (None for a declared plugin);
  - `strict: bool = True`;
  - `root_entry: bool = False`, true when the entry's string source resolves to the marketplace's
    own subdir in the marketplace's own fetch.

  An entry's `globs` is `Globs()`.

- [ ] **Step 1: Write the failing tests** (unit):
  - `test_a_non_strict_entry_is_a_plugin`: `strict: false` now gives a plugin with
    `strict is False`, not a skip. This replaces `test_a_non_strict_entry_is_skipped`.
  - `test_a_grafana_entry_is_a_root_entry_listing_skills`: `GRAFANA`'s first entry has
    `root_entry is True` and `entry.skills ==` the three paths. An entry at `./plugins/x` has
    `root_entry is False`.
  - `test_an_entrys_agents_and_object_commands_are_read`: `agents` and an object `commands` reach
    `entry`. `"agents": 3` skips the entry with `agents must be a string or a list of strings`.
  - Update `test_a_grafana_entry_carries_its_metadata_and_its_skill_paths`,
    `test_penpots_entry_leaves_its_components_to_its_manifest` and
    `test_an_entrys_commands_become_prompt_patterns` to read `plugin.entry`. Only the commands value
    changes, to `commands/**/*.md`, with `command_dirs == ("commands",)`.
  - Search `tests/` for other asserts on an entry's `globs` (`tests/test_config.py` among them)
    and move them the same way.

- [ ] **Step 2: Run them and watch them fail.** Run: `pytest tests/test_marketplace.py -v`

- [ ] **Step 3: Implement.**
  - Drop the `strict` skip at `marketplace.py:139`.
  - `_globs` becomes `read_components(raw)`, and a `ValueError` becomes `_Skip`, as today.
  - `with_manifest` reads an entry's `skills` and `commands` from `plugin.entry` exactly as it
    read them from `plugin.globs`, so serving is unchanged until Task 3. The one exception is a
    `strict: false` entry, which now loads as an ordinary one.

- [ ] **Step 4: Run everything.**
  Run: `ruff check . && pytest tests/test_marketplace.py tests/test_config.py -v && pytest`

- [ ] **Step 5: Commit.** `Keep a marketplace entry's components beside its manifest`

---

### Task 3: Merge config, manifest and entry as Claude Code does

**Files:**
- Modify: `kubed/mcp_kb/plugins/__init__.py` (`Globs`, `Plugin`),
  `kubed/mcp_kb/catalogue/snapshot.py` (`with_manifest`, `effective_globs`, `_plugin_status`,
  `log_changes`), `kubed/mcp_kb/catalogue/harvest.py` (`DEFAULTS`, `skill_dirs` for `"."`),
  `kubed/mcp_kb/spec/builder.py` (`PluginStatus.notes`)
- Regenerate: `wiki/Endpoints.md`
- Test: `tests/test_parity.py` (new), `tests/test_openapi.py`

**Interfaces:**
- Consumes: `Components` (Task 1), `Plugin.entry`, `strict` and `root_entry` (Task 2).
- Produces:
  - `Globs` gains `agents: tuple[str, ...] | None = None` (None is the default scan),
    `command_dirs: tuple[str, ...] = ()` and `command_map: tuple[CommandEntry, ...] = ()`.
  - `Plugin` gains `claude_format: bool = False`, `servers: tuple[str, ...] = ()` and
    `notes: tuple[str, ...] = ()`, which `with_manifest` sets.
  - `with_manifest(plugin, root) -> tuple[Plugin, Globs]` keeps its shape. It follows *How a
    plugin's components merge* in Design, raises `ValueError("conflicting manifests")` for LIB-31,
    adds PLG-23's notes, and reads PLG-27's server names (`.mcp.json`, `mcp_files`,
    `mcp_servers`).
  - For a non-Claude-format plugin, `Globs.agents == ()`.
  - `harvest.DEFAULTS["prompts"]` has `commands/**/*.md`, and `"."` as a skills pattern is the
    plugin root as a directory hit.
  - `/health` gains a plugin's `notes` (a list of strings) when it is not empty, and `log_changes`
    logs each new note once.

- [ ] **Step 1: Write the failing tests** in `tests/test_parity.py`, through `KnowledgeBase` and
  its `status`:
  - `test_a_manifest_skills_list_adds_to_the_conventions`: a manifest with
    `"skills": ["./extra"]` serves `skills/a` and `extra/b`.
  - `test_seven_root_entries_each_serve_their_own_skills`: over `grafana_root`, all seven plugins
    are `ok`, the library has no `conflicts`, and each plugin's `skills` count equals what its
    entry lists. `template` is served by none.
  - `test_commands_replace_the_conventions_and_note_the_folder`: a manifest `commands` with a
    `commands/` folder present serves only the listed ones. `notes` holds
    `Default commands/ folder is ignored because the manifest sets "commands"`.
  - `test_penpot_still_serves_its_eight_commands`: over `penpot_root`, the library's `prompts`
    is 8, `prompts/README.md` is not served, and each prompt's dialect is `claude`.
  - `test_an_entry_appends_to_its_manifest`: a manifest `skills: ["./a"]` and an entry
    `skills: ["./b"]` (not a root entry) serve both, plus the conventions.
  - `test_strict_false_beside_a_manifest_that_names_components_fails`: the plugin's status is
    `failed` with `error == "conflicting manifests"`. Run it once each for `hooks` and
    `outputStyles` as the only key named.
  - `test_strict_false_without_a_manifest_is_the_manifest`: it serves its entry's skills.
  - `test_a_declared_plugins_config_globs_still_win`: config `skills: ["x/**/SKILL.md"]` beside
    a manifest `skills` serves `x` only (LIB-33).
  - `test_claude_format`: a manifest plugin and an entry are Claude-format, and a bare declared
    plugin is not.
  - `test_servers_are_names_from_every_place`: `.mcp.json`, a manifest object and a manifest file
    give the sorted union of names. An unparsable `.mcp.json` adds a note and costs nothing else.
  - `tests/test_openapi.py`: a `/health` with `notes` validates.

- [ ] **Step 2: Run them and watch them fail.** Run: `pytest tests/test_parity.py -v`

- [ ] **Step 3: Implement**, as the Interfaces say. `server.py`'s `_plugin_record` already calls
  `with_manifest` and turns a `ValueError` into a failed plugin, so LIB-31 needs no new path.

- [ ] **Step 4: Run everything, then regenerate and check.**
  Run: `ruff check . && pytest`, then `python scripts/generate_wiki.py && python scripts/generate_wiki.py --check`.
  Expected: PASS, including `tests/test_example_config.py` unchanged.

- [ ] **Step 5: Commit** `wiki/Endpoints.md` inside `wiki/` (no push), then the superproject:
  `Merge a plugin's components as Claude Code does`.

---

### Task 4: Prompt names from where they were found, and the object map

**Files:**
- Modify: `kubed/mcp_kb/catalogue/prompts/__init__.py` (`PromptSource`, `prompt_name`,
  `load_prompt`, `load_prompts`), `kubed/mcp_kb/catalogue/harvest.py` (`COMMAND_DIRS` moves here
  from `snapshot.py`), `kubed/mcp_kb/catalogue/index.py` (`PromptRow`, `INDEX_VERSION`),
  `kubed/mcp_kb/catalogue/snapshot.py` (`build_plugin`, `_load_prompts`, `_dialect`, `_admit`)
- Test: `tests/test_parity.py`, `tests/test_prompts.py`, `tests/test_index.py`

**Interfaces:**
- Consumes: `Globs.command_dirs`, `Globs.command_map` (Task 3).
- Produces:

```python
@dataclass(frozen=True)
class PromptSource:
    path: Path                  # the file; for inline content, the manifest it came from
    name: str                   # below the library: "db_migrate", "about"
    content: str | None = None  # an inline body (PLG-21)
    description: str | None = None
    argument_hint: str | None = None

def prompt_name(path: Path, root: Path, command_dirs: Sequence[str]) -> str: ...
def load_prompts(sources: Sequence[PromptSource], *, library: str, ...) -> list[FilePrompt]: ...
```

  - `prompt_name` gives the folders below the deepest of `COMMAND_DIRS` + `command_dirs`
    containing `path`, then `stem(path)`, joined with `_`. Anywhere else, it gives `stem(path)`.
  - `FilePrompt.name` is `f"{library}_{source.name}"`.
  - An inline source parses `content` as a file body: frontmatter optional, `claude` dialect. Its
    `live` is always false.
  - A source's `description` and `argument_hint`, when set, replace the frontmatter's
    `description` and `argument-hint` before the dialect parses.
- `PromptRow` becomes `PromptRow(path, dialect, name, content=None, description=None,
  argument_hint=None)` and converts to and from `PromptSource`. `INDEX_VERSION` goes up by one.
  It is the one bump in this PR, and Part B's new record fields come under it.
- `_admit` keys a prompt on `row.name`, with the reason
  `prompt <name> is already served by <path>`.
- A map entry with `source` is matched like a declared command, so its dialect is `claude`.

- [ ] **Step 1: Write the failing tests:**
  - `test_commands_in_subfolders_carry_their_folders`: `commands/db/migrate.md` and
    `commands/top.md` under the convention are `lib_db_migrate` and `lib_top`.
  - `test_a_declared_commands_directory_reads_its_subfolders`: `"commands": "./cmds"` with
    `cmds/a/b.md` gives `lib_a_b`.
  - `test_the_prompts_convention_still_names_by_stem`: `prompts/sub/debug.md` is `lib_debug`,
    and `prompts/debug.md` beside it skips the later one with
    `prompt debug is already served by prompts/debug.md`.
  - `test_a_name_clash_is_on_the_name_not_the_stem`: `commands/a/x.md` and `commands/b/x.md` are
    two prompts, `lib_a_x` and `lib_b_x`.
  - `test_an_object_map_plugin_loads`: over `object_map_root`, `lib_brief` has the description
    `Write a brief.` and one free-text argument whose description is `<topic>`. `lib_about`
    renders `Say what this plugin does.` Both have dialect `claude`, and `notes` names `bad`.
  - `test_an_inline_prompt_survives_a_cold_start`: build, drop the server, start a new
    `KnowledgeBase` over the same cache. `lib_about` is served from the index with the same body.
  - `tests/test_index.py`: a `PromptRow` with `content` round-trips, and an index at the old
    version reads as `None`.

- [ ] **Step 2: Run them and watch them fail.**
  Run: `pytest tests/test_parity.py tests/test_prompts.py tests/test_index.py -v`

- [ ] **Step 3: Implement**, as the Interfaces say.

- [ ] **Step 4: Run everything.**
  Run: `ruff check . && pytest`
  Expected: PASS, with `tests/test_example_config.py` and `tests/test_dialects.py` unchanged.

- [ ] **Step 5: Commit.** `Name a command by its folders, and serve an object map of commands`

---

### Task 5: Part A's spec, docs and changelog

**Files:**
- Modify: `docs/superpowers/specs/plugins-and-libraries.md`, `docs/superpowers/specs/prompts.md`,
  `CHANGELOG.md`
- Modify (submodule `wiki/`): `Plugins.md`, `Prompts.md`

- [ ] **Step 1: The spec, now true of the code.**
  - In `plugins-and-libraries.md`, apply the supersession table to PLG-14, PLG-15, PLG-16,
    PLG-17, PLG-18, LIB-14 and LIB-19, rewording each in place.
  - Drop *(proposed)* from PLG-20 to PLG-27 and LIB-30 to LIB-33. Rename the section *Reading a
    plugin the way Claude Code does*, and delete the table.
  - In `prompts.md`:
    - PRM-41 reads "A prompt's name is `<library>_<name>`, where the name is as PLG-25 says";
    - PRM-43's clash is on that name, with the reason `prompt <name> is already served by
      <path>`;
    - the dialect table's row 4 adds "or is a `commands` map item".
  - Keep every ID, and reuse none.
- [ ] **Step 2: Wiki** (commit inside `wiki/`, no push).
  - `Plugins.md`: how a `plugin.json` and an entry merge (the Design table, in prose), `strict`,
    and `notes` in `/health`.
  - `Prompts.md`: command names with folders, and the object map.
- [ ] **Step 3: Changelog,** under `[Unreleased]`.
  - `### Added`:
    - `- A plugin's \`commands\` may be an object map, and commands in subfolders are served as \`<library>_<folder>_<name>\`.`
  - `### Changed`:
    - `- A plugin's \`plugin.json\` reads as Claude Code reads it: its \`skills\` add to the usual skill folders, and a marketplace entry's lists append to it.`
    - `- Marketplace entries marked \`strict: false\` now load, unless they conflict with the plugin's own \`plugin.json\`.`
- [ ] **Step 4: Verify.**
  Run: `ruff check . && pytest && python scripts/generate_wiki.py --check`.
  Expected: clean. `tests/test_wiki.py` runs.
- [ ] **Step 5: Commit** the wiki first, then the superproject: `Document plugin.json parity`.

---

## Part B: the agents extension

### Task 6: Harvest agents into the plugin record

**Files:**
- Create: `kubed/mcp_kb/catalogue/agents.py`
- Modify: `kubed/mcp_kb/catalogue/harvest.py`, `kubed/mcp_kb/catalogue/index.py`,
  `kubed/mcp_kb/catalogue/snapshot.py` (`build_plugin`)
- Test: `tests/test_agents.py` (new), `tests/test_index.py`

**Interfaces:**
- Consumes: `Globs.agents`, which is `()` for a plugin that isn't Claude-format (Task 3).
- Produces:

```python
@dataclass(frozen=True)
class ParsedAgent:
    name: str
    description: str                # whitespace collapsed
    capabilities: tuple[str, ...]
    model: str | None
    frontmatter: dict               # verbatim, JSON-safe
    body: str

def parse_agent(path: Path) -> ParsedAgent | str: ...   # a str is why it is skipped (AGT-6)
def routing_hint(model: str | None) -> dict | None: ...  # AGT-9, by family

# harvest.py
def agent_files(root: Path, globs: Globs) -> list[tuple[Path, tuple[str, ...]]]: ...
def agent_paths(root: Path, globs: Globs) -> tuple[Path, ...]: ...
```

  - `agent_files` returns each file, sorted by path below the root, with its folder segments. The
    default scan (`agents/**/*.md`) gives the folders between `agents/` and the file, and a listed
    file gives `()`.
  - `agent_paths` returns the `agents/` directory plus every listed file, or `()` when
    `globs.agents == ()`. Task 8 refuses them.
  - `AgentRow(path: str, name: str)` in `index.py`, where `name` is
    `"_".join((*segments, parsed.name))`. `PluginRecord` gains
    `agents: tuple[AgentRow, ...] = ()` and `agent_paths: tuple[str, ...] = ()`, both read back in
    `_plugin_record_from_dict`, under Task 4's index version.

- [ ] **Step 1: Write the failing tests** (unit):
  - `test_parse_agent_reads_the_diagrammer`: `name == "diagrammer"`, `model == "sonnet"`,
    `frontmatter["color"] == "cyan"`, and the body is the text after the frontmatter.
  - `test_what_makes_an_agent_file_skipped`, parametrised. These give a `str` naming the problem:
    no `description`; no `name`; `name: 3`; frontmatter that doesn't parse; frontmatter with no
    JSON form (`.nan`, using the `allow_nan=False` check of `uris.py::skill_entry`).
  - `test_capabilities_are_a_list_of_strings_or_nothing`: `["a", "b"]` is kept, and `"a"` and
    `[1]` give `()`.
  - `test_routing_hint_by_family`:

```python
@pytest.mark.parametrize(("model", "role"), [
    ("opus", "large"), ("sonnet", "medium"), ("haiku", "small"),
    ("claude-opus-5-5", "large"), ("claude-3-5-sonnet-20241022", "medium"),
    ("us.anthropic.claude-haiku-4-5-v1:0", "small"), ("Opus[1m]", "large"),
])
def test_routing_hint_by_family(model, role):
    assert routing_hint(model) == {"role": role, "vision": False}

@pytest.mark.parametrize("model", [None, "inherit", "gpt-5", "opusx", ""])
def test_no_routing_hint(model):
    assert routing_hint(model) is None
```

  - `test_the_default_scan_adds_a_segment_per_folder`: `extra` records `diagrammer`,
    `db_migrator`, `twin`, `twin` in path order, and `broken.md` is in `skipped`.
  - `test_a_listed_agent_has_no_folder_segment`: a manifest listing `./agents/db/migrate.md`
    records only `migrator`.
  - `test_a_bare_plugin_has_no_agents`: `drive` records `agents == ()` and `agent_paths == ()`.
  - `tests/test_index.py`: a record with agents round-trips.

- [ ] **Step 2: Run them and watch them fail.**
  Run: `pytest tests/test_agents.py tests/test_index.py -v`

- [ ] **Step 3: Implement.** Do it in `build_plugin`'s existing `try`: a reason goes into
  `unloadable`, which becomes `skipped`. `parse_agent` never raises on content. An `OSError`
  propagates, and fails the plugin as for prompts.

- [ ] **Step 4: Run everything.** Run: `ruff check . && pytest`

- [ ] **Step 5: Commit.** `Harvest plugin agents into the plugin record`

---

### Task 7: Claim names per library, and hold the roster in the catalogue

**Files:**
- Modify: `kubed/mcp_kb/catalogue/agents.py`, `kubed/mcp_kb/catalogue/snapshot.py` (`_Admitted`,
  `_admit`, `_serve_library`, `build_snapshot`, `_plugin_status`, `log_changes`),
  `kubed/mcp_kb/catalogue/uris.py` (`Catalogue`)
- Test: `tests/test_agents.py`

**Interfaces:**
- Consumes: `AgentRow`, `parse_agent` and `routing_hint` (Task 6); `Plugin.servers` (Task 3).
- Produces:

```python
@dataclass(frozen=True)
class Agent:
    name: str                       # served name
    library: str
    plugin: str                     # plugin id
    root: Path
    path: Path
    parsed: ParsedAgent
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

# Catalogue(..., agents: AgentRoster | None = None)
def agent_cards(self, scope: Scope = EVERYTHING) -> list[dict]: ...
def agent_definition(self, name: str, scope: Scope = EVERYTHING) -> dict | None: ...
```

  - An agent is admitted by `scope.admits(library, category, tags,
    library_categories=...)`.
  - `agent_definition` returns AGT-9's fields, without the envelope and without the gateway
    prefix. `instructions` is
    `placeholders.substitute(body, plugin_root=f"{SCHEME}{library}", skills=self.plugin_skill_dirs(library, plugin, scope))`
    with no `skill_dir`, and is omitted when blank.
  - For a `live` agent, `agent_definition` revalidates the file and parses it again first. It
    keeps `parsed` when that fails, and logs a warning (AGT-16).
- `/health`:
  - `agents` per plugin (admitted, library-independent) and per library (served);
  - a library's `renamed` (`{name: "<base> is already served by plugin '<owner>'"}`) and
    `unserved` (`[{plugin, path, reason}]`), each only when not empty.

- [ ] **Step 1: Write the failing tests** (unit, `build_snapshot` over `agents_tree`):
  - `test_names_follow_claude_code`: `drawio` holds `drawio_diagrammer`,
    `drawio_diagrammer@extra`, `drawio_db_migrator` and `drawio_twin`. `lone` holds
    `lone_solo`, and `drive` holds nothing.
  - `test_a_clash_is_renamed_and_reported`: `status["libraries"]["drawio"]["renamed"] ==
    {"drawio_diagrammer@extra": "drawio_diagrammer is already served by plugin 'drawio@drawio'"}`.
  - `test_a_clash_on_the_renamed_name_is_unserved`: put a plugin whose agent is named
    `diagrammer@extra` ahead of `extra`. Then `extra`'s diagrammer is absent, and `unserved`
    holds its plugin, `agents/diagrammer.md` and a reason.
  - `test_a_twin_in_one_plugin_is_skipped`: `extra`'s `skipped` holds `agents/twin-b.md` with
    `agent twin is already served by agents/twin-a.md`.
  - `test_an_appended_plugin_renames_nothing` and `test_a_prepended_plugin_takes_the_short_name`:
    the two sides of AGT-8's promise.
  - `test_a_conflicting_plugin_serves_no_agents`: a plugin that LIB-28 fails in a library serves
    no agents there.
  - `test_counts`: drawio's plugin `agents == 1`, extra's `== 3`, and library drawio's `== 4`.
  - `test_cards_and_definition_under_scope`: `agent_cards(Scope.parse(tags="diagrams"))` names
    only `drawio_diagrammer`. `categories="other"` names `extra`'s three, and
    `agent_definition("drawio_diagrammer", Scope.parse(tags="extra")) is None`.
  - `test_the_definition`:
    - `instructions` contains `skill://drawio/drawio/SKILL.md`, and `${CLAUDE_PROJECT_DIR}` as
      written;
    - `modelRoutingHint == {"role": "medium", "vision": False}`;
    - `tools == []`;
    - `_meta["io.kubed.mcp-kb/agent"] == {"plugin": "drawio@drawio", "library": "drawio",
      "path": "agents/diagrammer.md", "frontmatter": <verbatim>, "servers": ["drawio"]}`.
  - `test_a_live_agent_is_reread` (with a revalidate stub): an edited body is served on the next
    definition, and a broken edit serves the last parsed copy.

- [ ] **Step 2: Run them and watch them fail.** Run: `pytest tests/test_agents.py -v`

- [ ] **Step 3: Implement.**
  - `_Admitted` gains `agents`. `_admit` keeps the first row of each name in path order (AGT-6).
  - In `_serve_library`, after a plugin passes `claims.conflict`, each of its rows claims a name
    against the library's `taken: dict[str, str]`. The rule is AGT-8's: try `base`, then
    `f"{base}@{plugin.name}"`, else `unserved`.
  - A row whose file fails `parse_agent` at snapshot time is reported under the plugin as a
    vanished prompt is. Its claim stands for that snapshot, so the renames depend on the rows
    alone.
  - Add `"agents"`, `"renamed"` and `"unserved"` to `log_changes`' `watched`, and log a rename
    and an unserved agent once each.

- [ ] **Step 4: Run everything.** Run: `ruff check . && pytest`
  Expected: PASS, apart from `tests/test_openapi.py` on the new keys, if it fails at all. If it
  does, leave it for Task 10 and name it in the commit body.

- [ ] **Step 5: Commit.** `Claim agent names per library and hold the roster in the catalogue`

---

### Task 8: The plugin-root fallback refuses agent files (AGT-3)

**Files:**
- Modify: `kubed/mcp_kb/catalogue/skills.py` (`_Root`, `LibraryFiles.add`, `read_any`,
  `read_under`), `kubed/mcp_kb/catalogue/snapshot.py` (the `resources.add` call)
- Test: `tests/test_agents.py`. `tests/test_plugin_root.py` runs unchanged.

**Interfaces:**
- Consumes: `PluginRecord.agent_paths` (Task 6).
- Produces: `LibraryFiles.add(..., agent_paths: Sequence[Path] = ())`.
  - `read_any` and `read_under` refuse a target that is one of the library's agent paths, or lies
    under one. They are gathered across the library's roots, as `_skill_dirs` is.
  - `read` and `files` are unchanged, because the harvested list is the operator's glob.

- [ ] **Step 1: Write the failing tests** (unit, through `Catalogue.read`):
  - `test_the_library_fallback_refuses_an_agent_file`:
    `read("skill://drawio/agents/diagrammer.md") is None`.
  - `test_the_skill_fallback_refuses_an_agent_file`:
    `read("skill://drawio/drawio/agents/diagrammer.md") is None`.
  - `test_a_listed_agent_file_is_refused_wherever_it_sits`: a manifest listing
    `./roles/reviewer.md` makes `skill://<lib>/roles/reviewer.md` read `None`.
  - `test_an_operator_files_glob_still_serves_agents`: a declared Claude-format plugin with
    `files: ["agents/**/*.md"]` lists the file in `_files.md` and reads it.
  - `test_a_bare_plugins_agents_folder_is_not_guarded`: `drive`'s `agents/x.md` still reads
    through the fallback.

- [ ] **Step 2: Run them and watch them fail.** Run: `pytest tests/test_agents.py -k fallback -v`

- [ ] **Step 3: Implement**, as the Interfaces say.

- [ ] **Step 4: Run everything.**
  Run: `ruff check . && pytest tests/test_agents.py tests/test_plugin_root.py tests/test_uris.py -v && pytest`

- [ ] **Step 5: Commit.** `Keep agent files out of the plugin-root fallback`

---

### Task 9: `agents/list` and `agents/get`

**Files:**
- Create: `kubed/mcp_kb/mcp/agents.py`
- Modify: `kubed/mcp_kb/mcp/request.py`, `kubed/mcp_kb/mcp/skills.py`, `kubed/mcp_kb/mcp/pins.py`,
  `kubed/mcp_kb/server.py`
- Test: `tests/test_agents_extension.py` (new)

**Interfaces:**
- Consumes: `Catalogue.agent_cards` and `Catalogue.agent_definition` (Task 7).
- Produces:
  - `AGENTS_EXTENSION_ID = "io.modelcontextprotocol/agents"`, in `mcp/request.py`.
  - In `mcp/skills.py`, `checked_scope(problem) -> Scope` and `complete(**fields) -> dict`, lifted
    out of `SkillsExtension`. They are used by both extensions, and `SkillsExtension` behaves
    exactly as before.
  - `AdvertiseLegacyExtensions(declared: Mapping[str, dict])` replaces `AdvertiseLegacySkills`.
    `server.py` passes `{EXTENSION_ID: {}, AGENTS_EXTENSION_ID: {"listChanged": False}}`.
  - On `server/discover`, the agents value is `{"listChanged": False}`. Read the installed
    `fastmcp/server/extensions` source. If `ServerExtension` can declare a value, declare it
    there. If it can't, set it on the `server/discover` answer in the same middleware, through
    the hook `ScopedInstructions` uses.
  - `mcp/agents.py`:

```python
class GetAgentParams(RequestParams):
    name: str = Field(min_length=1)

class AgentsExtension(ServerExtension):
    identifier = AGENTS_EXTENSION_ID
    def __init__(self, catalogue: Callable[[], Catalogue],
                 scope_problem: Callable[[Scope], str | None]): ...
    # MethodBinding("agents/list", PaginatedRequestParams, self.list_agents)
    # MethodBinding("agents/get", GetAgentParams, self.get_agent)
```

  - Any `cursor` → `MCPError(INVALID_PARAMS, "Invalid agents cursor")`.
  - An absent or out-of-scope agent → `MCPError(code=INVALID_PARAMS, message="Agent not found",
    data={"reason": "agent_not_found"})`. Use whatever spelling the installed `MCPError` has for
    `data`.
  - `instructions` passes through `requested_addressing().text(...)`.
  - `pins._serving` is true when `snapshot.catalogue.agent_cards(scope)` is non-empty too.
  - `server.py` registers
    `AgentsExtension(lambda: self.snapshot.catalogue, lambda scope: what_is_wrong(scope, config, self.snapshot))`.

- [ ] **Step 1: Write the failing tests.** In-process ones use
  `@pytest.mark.parametrize("mode", ["auto", "legacy"])` and the `request` helper of
  `tests/test_skills_extension.py`:
  - `test_both_extensions_are_declared`: `caps.extensions[AGENTS_EXTENSION_ID] ==
    {"listChanged": False}`, and `caps.extensions[EXTENSION_ID] == {}`.
  - `test_list_returns_cards`: `resultType == "complete"`, `ttlMs == 0`,
    `cacheScope == "private"`, and every card's keys are exactly
    `{"name", "description", "capabilities"}`.
  - `test_get_returns_the_definition`: the Task 7 values, wrapped in the envelope.
  - `test_unknown_is_agent_not_found`: `-32602`, `Agent not found`,
    `data == {"reason": "agent_not_found"}`.
  - `test_a_cursor_is_refused`: `-32602`, `Invalid agents cursor`.
  - `test_nothing_else_changes`: `list_tools()`, `list_resources()` and `list_prompts()` equal a
    server's over the same tree with every `agents/` removed.
  - `test_a_prefix_reaches_instructions_only`: under `Kb-Resource-Prefix: kb+`, `instructions`
    holds `kb+skill://drawio/drawio/SKILL.md`, and `_meta`'s frontmatter is unchanged.

  Over real uvicorn (`integration`):
  - `test_tag_and_category_scope_list_the_diagrammer`: each of `?tag=diagrams`,
    `Kb-Tag: diagrams` and `?category=diagrams` lists exactly `drawio_diagrammer`.
  - `test_out_of_scope_is_agent_not_found`: under `Kb-Tag: extra`, `agents/get
    drawio_diagrammer` fails exactly as an unknown name does, with the same code, message and
    data.
  - `test_a_scoped_caller_sees_the_library_name`: under `Kb-Category: other`, the list holds
    `drawio_diagrammer@extra` and not `drawio_diagrammer`.
  - `test_a_scope_of_only_agents_is_served`: `Kb-Tag: lonely` lists `lone_solo`.
  - `test_a_refused_scope_fails_both_methods`: `Kb-Tag: nonesuch` fails both with `-32602` and
    SCP-31 row 7's message.
  - `test_a_library_scope`: `Kb-Library: lone` lists only `lone_solo`.

- [ ] **Step 2: Run them and watch them fail.** Run: `pytest tests/test_agents_extension.py -v`

- [ ] **Step 3: Implement**, as the Interfaces say.

- [ ] **Step 4: Run everything.**
  Run: `ruff check . && pytest tests/test_agents_extension.py tests/test_skills_extension.py tests/test_header_scope.py tests/test_boundaries.py -v && pytest`

- [ ] **Step 5: Commit.** `Serve agents/list and agents/get`

---

### Task 10: `/health` and the published contract

**Files:**
- Modify: `kubed/mcp_kb/routes.py` (`report`), `kubed/mcp_kb/spec/builder.py`
  (`PLUGIN_STATUS`, `LIBRARY_STATUS`, `HEALTH`)
- Regenerate: `wiki/Endpoints.md`
- Test: `tests/test_openapi.py`

**Interfaces:**
- Consumes: the roster's `__len__` (Task 7), and the status keys from Task 7.
- Produces:
  - `/health` gets a top-level `"agents": len(snapshot.catalogue.agents)`. Expose a count property
    on `Catalogue` if that reads better.
  - `agents` is an integer in all three schemas, required wherever `prompts` is.
  - `LIBRARY_STATUS` gains `renamed`, with `additionalProperties: string` and the description
    "Present when a later plugin's agent took `<name>@<plugin>`: keyed by the served name, the
    value says who has the short one". It also gains `unserved`, an array of
    `{plugin, path, reason}`.
  - `PluginStatus.skipped` mentions agent files.

- [ ] **Step 1: Write the failing test:** over `agents_tree`, `/health` has `agents == 5`, and the
  body validates against the published schema, `renamed` included.

- [ ] **Step 2: Run it and watch it fail.** Run: `pytest tests/test_openapi.py -v`

- [ ] **Step 3: Implement**, as the Interfaces say.

- [ ] **Step 4: Verify the contract.**
  Run: `python scripts/generate_openapi.py && npx --yes @redocly/cli@2 lint openapi.yaml`.
  That is lint.yml's check; skip only the lint if `npx` is missing, and say so. Then
  `python scripts/generate_wiki.py && python scripts/generate_wiki.py --check`, then
  `ruff check . && pytest`.

- [ ] **Step 5: Commit** `wiki/Endpoints.md` inside `wiki/` (no push), then the superproject:
  `Count agents in /health`.

---

### Task 11: Part B's spec, docs and changelog

**Files:**
- Modify: `docs/superpowers/specs/agents.md`, `scoping-and-instructions.md`,
  `http-and-tools.md`, `skills.md`, `AGENTS.md`, `README.md`, `CHANGELOG.md`
- Modify (submodule `wiki/`): `Plugins.md`, `Scoping.md`, `Agentgateway.md`

- [ ] **Step 1: The spec, now true of the code.**
  - `agents.md`: drop every *(proposed)*. "Every requirement in this file is proposed" becomes
    "The extension is experimental, and kb follows the draft named above."
  - SCP-21: "…to skills, prompts, agents and library-level files alike, … `skills/list`,
    `skills/get`, `agents/list`, `agents/get` and the four mirror tools."
  - SCP-24: add "`agents/get` (`Agent not found`, with `data.reason: "agent_not_found"`)".
  - SCP-29: "`initialize`, `server/discover`, `skills/list`, `skills/get`, `agents/list` and
    `agents/get` are refused alike".
  - SCP-31 row 9: "…no listing row, no prompt and no agent".
  - HTTP-8: the row `| agents | agents currently served, across libraries |` after `prompts`.
  - HTTP-27: "Both answers advertise the `io.modelcontextprotocol/skills` and
    `io.modelcontextprotocol/agents` extensions. Their methods are in skills.md and agents.md."
  - HTTP-29, last sentence: "The Skills and Agents extensions' own results are in skills.md and
    agents.md."
  - SKL-30 and SKL-31: append "Neither serves an agent file (AGT-3)."
- [ ] **Step 2: `AGENTS.md`.**
  - Add `mcp/agents.py` and `catalogue/agents.py` to Layout.
  - After the Skills extension paragraph in *The surface*, add one paragraph on the Agents
    extension: a separate surface, with no rows, tools or instructions. Names are the library's,
    claimed in library order, and no owner is stored. Agent files never go through the plugin-root
    fallback. No method takes a scope param.
  - Under *Where code goes*, `plugin.json` parity is `plugins/manifest.py`'s `Components` and
    `snapshot.with_manifest`'s merge.
- [ ] **Step 3: README.** One paragraph after the Skills extension's. Agent-aware clients can
  call `agents/list` and `agents/get`. This is **experimental** and follows the MCP Agent
  Discovery draft (agents-wg proposal 0000 at `137d88b`), and the same scopes apply. Link the wiki.
  `tests/test_readme.py` passes.
- [ ] **Step 4: Wiki** (commit inside `wiki/`, no push).
  - `Plugins.md`: a section "Agents (experimental)" covering which files are agents, the names
    table, what `agents/get` returns, and that kb never runs a plugin's MCP servers.
  - `Scoping.md`: an agents client scoped by `Kb-Tag: diagrams` or `?category=diagrams`.
  - `Agentgateway.md`: `agents/*` is refused until agentgateway#3579, as `skills/*` is.
- [ ] **Step 5: Changelog,** under `[Unreleased]` → `### Added`:
  `- **Discover the agents your plugins ship** through the experimental \`agents/list\` and \`agents/get\`, scoped like everything else.`
- [ ] **Step 6: Verify everything CI runs.**
  Run: `ruff check . && pytest && python scripts/generate_wiki.py --check && python scripts/generate_openapi.py && python -m kubed.mcp_kb schema | diff - config.schema.json`.
  Expected: clean, all PASS, no diff, and `tests/test_wiki.py` not skipped.
- [ ] **Step 7: Commit** the wiki first, then the superproject: `Document the agents extension`.

## Acceptance, after deploy (Dr K, not CI)

- **grafana/skills** still serves its seven plugins, each with its own skills, and no conflicts.
- **penpot** still serves its 8 commands and nothing else from `prompts/`.
- Against **kubed-io/skills at `d8a83e5`**, with a library named `drawio` over the `kubed`
  marketplace:
  - `agents/list` under `Kb-Library: drawio` returns one card, `drawio_diagrammer`, with
    `capabilities: []`;
  - `agents/get` returns the body, `{"role": "medium", "vision": false}`, `tools: []`,
    `servers: []` and the frontmatter;
  - `skill://drawio/agents/diagrammer.md` no longer reads;
  - `/health` shows `agents: 1` for `drawio@drawio`.
- Through **agentgateway**, `agents/*` is refused until agentgateway#3579. That is expected.
