# K4: Prompts Through kubed-mcp's `command_reader` Implementation Plan

> **History.** Proposed for #82 (PR #97, into `issue-80`), after K3 (#79, PR #89), the gateway
> prefix (#81, PR #93) and the `_publish` race fix (#94, PR #96). The issue's notes are the spec,
> with Dr K's rulings 1 to 4 on #82 and the parent's corrections of 2026-11-25 (13:17): remove
> `prefixed()` from `_filled`, settle the prompt description's prefix, and pin what `issue-80`
> pins. The design is below; there is no separate design file.
>
> **Approved** 2026-11-25 (for Dr K): D8 and P7, D7 and P3, D9 and P5 as written; P8 changed to a
> log filter (see P8 and Task 3); the changelog takes a **BREAKING:** line for P1 and a line for
> P7. Task 0 found rc2 names prompts as PLG-25 does and lists no `prompts://` row (P6).

> **For agentic workers:** REQUIRED SUB-SKILL: Use skill://superpowers/subagent-driven-development/SKILL.md (recommended) or skill://superpowers/executing-plans/SKILL.md to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** kubed-mcp's plugin layer serves kb's prompts. kb's dialect reader is its
`command_reader`, and kb's `PromptProvider`, its prompt rows and its prompt claims go. Every
prompt's name, arguments and rendered text stay as they are, except for the named changes below.

**Architecture:** Each generation `SkillServing.publish` already adds every plugin to a kubed-mcp
plugin set (K3). Now each add also carries kb's prompt selection as the `commands` of the
`manifest=` it passes. The layer reads each command file and hands its text to kb's
`read_command`, which parses it in kb's dialects and returns an `MCPFilePrompt`. The layer names
the prompt (PLUG-62), prefixes it with the namespace's first segment (PLUG-63, PLUG-17), scopes
it by kb's view, and refuses a clash (PLUG-18). Then GW-7 prefixes what it renders. kb's rewriter
now also renders a command's body (qualified names, `${CLAUDE_PLUGIN_ROOT}`) when the build is
made, and the reader parses the rewritten text again. A render only substitutes the dialect's
placeholders and asks for missing arguments.

**Tech Stack:** Python ≥3.11, `kubed-mcp==0.2.0rc2` (rc3 if #92 has merged into `issue-80`),
FastMCP through it, pytest + pytest-asyncio, uvicorn, wsgidav.

**Spec:** this plan's design section; #82's notes in `.issue/issues.md`; the living spec in
[prompts.md](../specs/prompts.md), [plugins-and-libraries.md](../specs/plugins-and-libraries.md),
[skills.md](../specs/skills.md) (SKL-41) and [agents.md](../specs/agents.md).

## Design

### What is on the branch now, read in the code

- `mcp/skills.py::SkillServing.read_command` returns `COMMANDS_ARE_KBS` for every command, so
  the layer serves none. `entry_for(plugin)` passes no `commands`, so the layer would read only
  `commands/`.
- `mcp/prompts.py::PromptProvider` serves `snapshot.prompts`, scoped by
  `Scope.admits(library, category, tags, library_categories)`. That is the same per-plugin test
  `_Row.admitted` makes for the view. `_get_prompt` builds `skill_dirs` and `names` for the render,
  and `_filled` calls `prefixed(text, prefix())`.
- `catalogue/snapshot.py`:
  - `build_plugin` parses every prompt at harvest (`_load_prompts`, `_dialect`, `_mapped`).
  - `PromptRow` records the path, dialect, name and an inline body.
  - `build_snapshot` re-parses the rows (`_serve_library`), `_admit` skips unusable and
    duplicate names, and `_Claims.prompts` fails a later plugin on a clash.
- `catalogue/prompts/__init__.py::FilePrompt.render` rewrites names, substitutes the dialect's
  placeholders, then `${CLAUDE_PLUGIN_ROOT}`. `body()` re-reads a live file on every render.
- **This branch predates #94.** `issue-80` has `_PINNED` in `mcp/skills.py`, and Task 0 merges
  it. #94's rule holds here: anything that reads `_Published` while a build is made reads
  through the pin first, never `self._published`.

### Checked against kubed-mcp 0.2.0rc2 (`kubed/mcp/plugins.py` at tag `v0.2.0-rc.2`)

1. **The reader.** `CommandReader = Callable[[str, str, str, Plugin], Prompt | str]`, which kb
   already registers through `mcp.command_reader`. `_read_command` turns a raise into its message
   and a `str` into a skip reason. It renames a `Prompt` whose name differs from the layer's with
   `model_copy(update={"name": name})`, which keeps kb's subclass.
2. **When it runs.** At read it runs on the raw text: the name's usable-check comes first, then
   the reader, then the claims, so a refused file claims nothing. A `str` is logged
   `prompt <path> is skipped: <reason>` at WARNING and recorded in `Plugin.skipped`. Per build it
   runs again on the rewritten text, but only when a rewriter changed it (site kind `"command"`).
   A `str` then is logged at ERROR and leaves the command out of that build.
3. **Names.** `named = "" if own else prefix.split("/")[0] + "_"`, where `own` is the namespace
   equal to the server's name. The segments are
   `(*folders_in, path.stem.removesuffix(".prompt"))`. A folder entry names its files by the
   folders below it, and a file entry by its stem alone. So `commands/db/migrate.md` is
   `<library>_db_migrate` only when it is read through the `commands` folder.
4. **`commands` in `manifest=`.**
   - The entry's paths are *appended* to `plugin.json`'s, deduplicated by path.
   - A declared `commands` replaces the default `commands/`. When `commands/` is there and no
     path covers it (`.`, `commands`, `commands/…`), the layer notes
     `Default commands/ folder is ignored…`, and it logs every note at WARNING on every read.
   - `strict: false` beside a `plugin.json` with any component named is refused as
     `conflicting manifests`. Without a `plugin.json`, `strict` does nothing.
   - A top-level folder entry is walked even when it is a dot folder; below it, dot folders and
     dot files are skipped. A file entry in a dot folder is read.
   - An object map is not served, and is noted `commands object map is not served`.
5. **Scope and listing.** `prompts/list` and `prompts/get` serve the pinned build of the
   request's view, so an out-of-scope prompt is unknown to both (PRM-2). rc2's `_list_prompts`
   has no `via` check.
6. **GW-7.** `_Prefixed` wraps a prompt when the build has a prefix, and prefixes each text
   message `inner._render` returns. A result with no messages (an `InputRequiredPromptResult`)
   passes through untouched.

### Decisions

- **D1. kb hands the layer exactly its selection.** kb's prompt set is unchanged: what
  `harvest.prompt_files(root, globs)` selects (the conventions, a `commands` declaration, or a
  config's `prompts:`). It is recorded per plugin as root-relative paths
  (`PluginRecord.prompts`), and the paths a `commands` declaration selects as
  `PluginRecord.claude_prompts`. `harvest.command_entries` turns the selection into the
  `commands` list:
  - each selected file under a command folder (`commands`, `.claude/commands`, or a declared
    one; the deepest that contains it, as `prompt_name` decides) brings that folder in, once;
  - every other selected file is a file entry;
  - entries come in the order of their first file, so the layer reads in kb's path order and the
    first of two same-named files wins, as before (PRM-43).

  `entry_for` always sets `commands` to that list (`[]` for none), replacing an entry's own. It
  drops `strict` when it is `false`: kb never adds a plugin whose entry names components beside a
  `plugin.json` (LIB-31 fails it first), so `strict` has nothing left to decide. Then the
  conventions' `prompts/` and `.github/prompts/` reach the layer beside a `plugin.json` too.
- **D2. The reader holds the layer to kb's selection and names.** A folder entry, or a
  `plugin.json`'s appended `commands`, can read files kb did not select. So `read_command` skips
  any path outside `PluginCommands.selected` (`NOT_SELECTED`), and any file whose layer name is
  not `<library>_<prompt_name(…)>` (`RENAMED`). The second check is check 1 kept forever. It also
  settles a file read through two nested folders: the deeper one's name wins. `/health` leaves
  out `NOT_SELECTED` rows, and rows for a path that served under another read.
- **D3. kb parses, the layer serves.** `catalogue/prompts.parse_prompt(text, path, …)` parses
  from text. It never reads disk, since builds never do, and it raises what `load_prompt` raised.
  The dialect is decided at the raw read by `dialect_of` (PRM-14, rules 2 to 5 from the plugin's
  own `dialect:` and `claude_prompts`) and recorded with the read. A build re-reads in that same
  dialect, so a rewritten body never changes a file's dialect. `read_command` returns
  `adapt(file)`: an `MCPFilePrompt` with arguments, description, title (`mcp-kb` dialect only),
  and tags `{library, *labels}`.
- **D4. Rewriting moves to the build.** `rewrite` gains a `"command"` branch. It keeps the
  frontmatter as written, and renders the body with `Catalogue.agent_instructions(library,
  plugin, body, scope)`: qualified names first (PRM-62), then `${CLAUDE_PLUGIN_ROOT}` through the
  plugin's own skills (PRM-48, PRM-61). That is the same text an agent's body gets. A file with no
  frontmatter block is returned as written, and the reader skips it anyway (PRM-5). At render,
  `FilePrompt.render(arguments)` only checks the arguments and substitutes the dialect's
  placeholders. `_filled` loses `prefixed()`, because GW-7 writes the prefix.
- **D5. What kb read is what kb reports.** At add time `read_command` records each `FilePrompt`
  it returns, by `(namespace, address)` and path, in read order. `_narrowed` keeps the reads
  whose names are in `served.prompts` (the first read of a name, which is the one the layer
  claimed). That is `snapshot.prompts`, so `/health`'s counts, `KnowledgeBase.prompts` and
  `RefuseEmptyScope` read what is served. `_narrowed` also writes:
  - each library's and plugin's `prompts` count;
  - the plugin's `skipped` rows for selected paths that did not serve (from `served.skipped`);
  - one parity note for a selected path the layer neither served nor skipped.

  A kept plugin (a live re-read that did not move it) carries the reads it was published with.
  Index and `/health` shrink to fetch records in K6 (#84); until then they count the same prompts.
- **D6. Add time is a context, not a field.** The reader runs while a set is staged, and it runs
  again while a request builds. A refresh publishing from a worker thread must not make a build on
  the loop read the generation being staged. So `self._entering` becomes `_ENTERING`, a
  `ContextVar` shaped like #94's `_PINNED`. `_reading()` gives the reader, `rewrite` and
  `agent_meta` one rule: `_ENTERING` when it is this serving's (add time), then `_PINNED` (build
  time), then `self._published`. A live re-read publishes inside a request whose view set
  `_PINNED`, and its adds still read `_ENTERING`.
- **D7. Live prompts follow K3** (ruling 3, quick-mcp#45). A live plugin's watch also stamps its
  selected command files. A moved one re-reads the plugin, and the edit, arguments and dialect
  included, serves from the next request. Before re-adding a moved plugin, kb parses each prompt
  file it last served. If one now fails, the re-read is refused (`_add`'s kept path): the plugin
  keeps its last good build and kb logs one warning. The plugin stays as it was until a file
  moves again.
- **D8. A library named `mcp-kb` is refused** at config load. Its namespace would equal the
  server's name, and the layer would give its prompts no prefix (check 4). `config.SERVER_NAME` is
  the one spelling, and `create_app` uses it.
- **D9. A prompt's description stays as written** (kept behaviour). GW-7 prefixes the rendered
  text only. SKL-41 states this as fact, and its *(proposed)* clause goes.
- **Deleted:** `PromptProvider`, `_adapt`'s callers and `MCPFilePrompt.skill_dirs`/`names`;
  `PromptRow`, `_load_prompts`, `_mapped`, `_dialect` (moved), the `vanished` bookkeeping, the
  prompt rows in `_admit` and `_Claims.prompts`; `CommandEntry`, `_command_map` and
  `Globs.command_map`; `PromptSource`, `load_prompt`, `load_prompts`, `FilePrompt.body()`,
  `FilePrompt.live` and `render`'s keyword arguments; `COMMANDS_ARE_KBS`.
  Kept until #86: `ReadOnlyPromptsAsTools` and `_mirrored`.

### Named changes for QA's dump

- **P1. Inline object-map commands are removed** (ruling 1). A manifest's or entry's `commands`
  map serves nothing, still replaces the conventions, and the plugin notes
  `commands object map is not served`. At QA the before dump lists the prompts whose `/health`
  path is `.claude-plugin/plugin.json` or `plugin.json`.
- **P2. Rendering order.** Qualified names and `${CLAUDE_PLUGIN_ROOT}` are resolved when the build
  is made, before the dialect's placeholders. An argument value holding `${CLAUDE_PLUGIN_ROOT}`
  now renders as typed.
- **P3. Live prompts.** An edit serves from the request after the one that noticed it. Arguments,
  defaults and dialect follow the edit without a refresh. A broken edit keeps the plugin's last
  good build (its skills and agents included) and logs one warning.
- **P4. `/health` wording.** A prompt's skip reasons quote the full served name
  (`prompt lib_debug is already served by prompts/debug.md`, `prompt name 'lib_a b' is not a
  usable name`). A prompt clash between plugins of one library is the layer's refusal,
  `conflict: prompt <name> is already served by plugin <owner>`, with no cache path.
- **P5. Which plugins' prompts serve.** A plugin the layer refuses serves no prompt in that
  library (LIB-29), and neither does a plugin declared `skills: []` (LIB-33). A plugin with prompts
  and no skill or agent is now added. It serves as before.
- **P6. `prompts://`.** Recorded by Task 0 under rc2: a served command is never listed in
  `resources/list`, but it reads, unlisted, at `prompts://<namespace>/<place>`, where `<place>`
  is its path below the folder entry that read it (`commands/top.md` is
  `prompts://lib/top.md`; `prompts://lib/commands/top.md` misses). The read is the file's raw
  text, frontmatter included. #85 owns the spec rows.
- **P7. A library named `mcp-kb` fails the config.**
- **P8. Log lines.** The layer logs a skipped prompt file at WARNING on every read, beside kb's
  one `/health` line. It logs PLG-23's note when a config's `prompts:` leaves an existing
  `commands/` unread, and that one note stays. A file that a command folder reads and kb's
  selection leaves out on purpose (`not one of the plugin's prompt files`) is *not* logged:
  Dr K ruled that a warning per such file on every read buries real ones, so a kb logging
  filter on `kubed.mcp.plugins` drops exactly that skip line (Task 3). It still shows in
  `Plugin.skipped`.
- **P9.** For a plugin no library serves, `/health`'s plugin `prompts` counts its selected files,
  parsed or not.

Kept: every name (PLG-25), arguments, rendered text, elicitation (PRM-53 to PRM-57), the mirror
tools, and the description (D9).

## Global Constraints

- `pyproject.toml` pins `"kubed-mcp==0.2.0rc2"`. If #92 has merged into `issue-80`, it is
  `==0.2.0rc3`: work on that and re-run Task 0's checks under it. Never `>=0.2,<0.3`.
- FastMCP only through `kubed.mcp` and its submodules. `catalogue/` and `plugins/` import no
  `kubed.mcp`, and `tests/test_boundaries.py` stays green. `parse_prompt` and `dialect_of` live
  in `catalogue/prompts/`; `adapt` and `MCPFilePrompt` in `mcp/prompts.py`.
- Every build-time read of `_Published` goes through `_reading()` (D6).
- Absent and out of scope stay indistinguishable (SCP-21): an out-of-scope prompt is
  `Unknown prompt` exactly as a missing one is.
- No cache path or credential in a reason, a note or a log line kb writes (`unrooted`, `scrub`,
  `SkillServing._clean`).
- Spec rows keep their IDs, no ID is reused, and the spec holds statements only, with no issue
  numbers. Wiki changes go on the wiki's `issue-82` branch, never its `master`.
- Python 3.11 floor; 88 columns; a glob ending `**` is written `dir/**/*`.
- Every task runs `ruff check .` and then its own tests (`pytest tests/<file>.py -v`). The last
  task runs all of `pytest`, `python scripts/generate_wiki.py --check` and
  `python scripts/generate_openapi.py` (its output linted as CI does). CI runs `ruff check .` and
  `pytest` on 3.11 and 3.14, plus the wiki check and the OpenAPI lint.

## Review Focus

1. **A partial `prompts:` glob inside `commands/`** (`prompts: ["commands/*.md"]` beside
   `commands/db/x.md`). The top-level files keep their names and `commands/db/x.md` serves
   nothing, although the layer reads the folder. *(Task 3:
   `test_a_partial_glob_in_commands_serves_only_what_it_selects`.)*
2. **A `strict: false` entry beside a `plugin.json`, on the conventions** (`prompts/x.md`,
   `.github/prompts/y.prompt.md`). Both serve, `lib_x` and `lib_y`, and nothing is refused as
   `conflicting manifests`. *(Task 3: `test_conventions_serve_beside_a_strict_false_entry`.)*
3. **A `plugin.json` that declares `commands` under a config's `prompts:`.** Only the config's
   selection serves (LIB-33). *(Task 3:
   `test_a_declared_prompts_list_beats_the_manifests_commands`.)*
4. **Elicitation under a prefix.** `Kb-Resource-Prefix: kb+` at `2026-07-28` with form
   elicitation returns the input-required result, and the round that answers renders
   `kb+skill://…` once. *(Task 3: `test_elicitation_survives_the_prefix`.)*
5. **Two files of one plugin with one name** (`commands/debug.md`, `prompts/debug.md`). The first
   in path order serves, and `/health` has one row for the other with the layer's reason.
   *(Task 3: `test_a_same_named_prompt_is_skipped_once`.)*

---

### Task 0: Bring in `issue-80`, and check the layer before building on it

**Files:**
- Test: `tests/test_command_layer.py` (create)

**Interfaces:**
- Consumes: kubed-mcp's own `QuickMCP`, `plugin_set()`, `PluginSet.add(address, namespace=…,
  manifest=…)`, `serve(...)` and its default command reader.
- Produces: the go/no-go for every later task, and P6's wording.

- [x] **Step 1: Merge**

Run: `git fetch origin && git merge origin/issue-80`.
Expected: `mcp/skills.py` has `_PINNED` (#94). Read `pyproject.toml`'s pin: rc2, or rc3 if #92
merged. Run `pip install -e '.[test]'`, then `pytest -q`. Expected: green, as `issue-80` is.

- [x] **Step 2: Write the layer checks**

These run against kubed-mcp alone, with no kb code: a `QuickMCP("mcp-kb")` and one plugin folder
in `tmp_path`. It holds `commands/db/migrate.md`, `commands/top.md`, `prompts/x.prompt.md` and
`.github/prompts/y.prompt.md`, each with `---\ndescription: D.\n---\nBody.\n`. Add it with
`manifest={"name": "p", "commands": ["commands", "prompts/x.prompt.md",
".github/prompts/y.prompt.md"]}`, then serve. Build the set the way kubed-mcp's own README
builds one (`plugin_set()`, `add`, `serve`); if a bare folder needs a loader, use kubed-mcp's
`file` loader.

```python
async def test_the_layer_names_commands_as_plg25_does(tmp_path):
    for namespace in ("lib", "lib/sub"):
        names = await _served_names(tmp_path, namespace)
        assert sorted(names) == ["lib_db_migrate", "lib_top", "lib_x", "lib_y"]


async def test_a_namespace_named_like_the_server_has_no_prefix(tmp_path):
    assert "top" in await _served_names(tmp_path, "mcp-kb")  # why D8 refuses it


async def test_a_served_command_adds_no_listing_row(tmp_path):
    rows = await _listed_uris(tmp_path, "lib")
    assert not [uri for uri in rows if uri.startswith("prompts://")]
```

- [x] **Step 3: Run them**

Run: `pytest tests/test_command_layer.py -v`
Expected: all pass. **If the names test fails, stop.** Report on the PR that the pinned rc does
not name prompts as PLG-25 does: the work is blocked upstream and not redesigned in kb (ruling 2).
If the listing test fails, stop too: a listing row per prompt breaks the address-space rule in
AGENTS.md, and that is Dr K's call.

- [x] **Step 4: Record P6**

In the same file, add `test_a_served_commands_prompts_address`. It reads
`prompts://lib/commands/top.md`, and the spelling the layer uses if that one misses (its
`_file_uri("prompts", namespace, place)`), and asserts what rc2 does. Write the outcome into
this plan's P6 and the PR body.

- [x] **Step 5: Commit**

```bash
git add tests/test_command_layer.py docs/superpowers/plans/2026-11-25-k4-prompts-through-command-reader.md
git commit -m "K4: check kubed-mcp's prompt naming and listing under the pinned rc"
```

### Task 1: Parse a prompt from its text

**Files:**
- Modify: `kubed/mcp_kb/catalogue/prompts/__init__.py` (add `parse_prompt`, `dialect_of`,
  `READ_ERRORS`; `load_prompt` reads the file and calls `parse_prompt`)
- Modify: `kubed/mcp_kb/catalogue/snapshot.py` (`_dialect` becomes a call to `dialect_of`)
- Modify: `tests/conftest.py` (add `read_prompt`)
- Test: `tests/test_dialects.py`

**Interfaces:**
- Produces:
  - `parse_prompt(text: str, path: Path, *, name: str, library: str, plugin: str = "", tags: Sequence[str] = (), category: str | None = None, library_categories: frozenset[str] = frozenset(), dialect: str = detect.AUTO) -> FilePrompt`.
    `name` is the full served name. It raises `ValueError`, `TypeError` or `yaml.YAMLError` as
    `load_prompt` does, and never reads disk.
  - `dialect_of(rel: str, *, configured: str, claude: Collection[str]) -> str`: PRM-14 rules 2
    to 5 as `_dialect` decides them, from a root-relative path.
  - `READ_ERRORS = (ValueError, TypeError, yaml.YAMLError)`.
  - `tests/conftest.py::read_prompt(path: Path, library: str = "lib", **kwargs) -> FilePrompt`:
    `parse_prompt(path.read_text(encoding="utf-8"), path, name=f"{library}_{stem(path)}", library=library, **kwargs)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_prompt_reads_text_not_disk(tmp_path):
    path = tmp_path / "gone.md"  # never written
    prompt = parse_prompt(
        "---\ndescription: D.\n---\nHi.\n", path, name="lib_gone", library="lib"
    )
    assert (prompt.name, prompt.dialect, prompt.template) == ("lib_gone", "mcp-kb", "Hi.\n")


@pytest.mark.parametrize(
    ("rel", "configured", "claude", "expected"),
    [
        ("prompts/x.md", "copilot", (), "copilot"),
        ("commands/x.prompt.md", "auto", (), "auto"),
        ("commands/db/x.md", "auto", (), "claude"),
        (".claude/commands/x.md", "auto", (), "claude"),
        ("prompts/brief.md", "auto", ("prompts/brief.md",), "claude"),
        ("prompts/x.md", "auto", (), "auto"),
    ],
)
def test_dialect_of_is_prm14_rules_2_to_5(rel, configured, claude, expected):
    assert dialect_of(rel, configured=configured, claude=claude) == expected
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/test_dialects.py -v`
Expected: the two new tests fail on the import.

- [ ] **Step 3: Implement**

- `parse_prompt` is `load_prompt`'s body from `meta, body = …` on, over `_split(text)`, with
  `name` used as given.
- `load_prompt` reads `path` and calls it, naming the prompt `f"{library}_{source.name}"` as now.
- `snapshot._dialect` calls `dialect_of(_relative(path, root), configured=plugin.dialect,
  claude={_relative(p, root) for p in declared})`.
- In `tests/test_dialects.py`, move the calls that only parse onto `read_prompt`.

- [ ] **Step 4: Run the checks**

Run: `ruff check .` then `pytest tests/test_dialects.py tests/test_prompts.py tests/test_placeholders.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add kubed/mcp_kb/catalogue tests/conftest.py tests/test_dialects.py
git commit -m "Prompts parse from their text: parse_prompt and dialect_of"
```

### Task 2: Inline object-map commands are removed (P1)

**Files:**
- Modify: `kubed/mcp_kb/plugins/manifest.py` (delete `CommandEntry`, `_command_map`,
  `Components.command_map`; `_commands` returns three values)
- Modify: `kubed/mcp_kb/plugins/__init__.py` (delete `Globs.command_map` and its docstring
  sentence)
- Modify: `kubed/mcp_kb/catalogue/snapshot.py` (`with_manifest`, delete `_mapped`)
- Modify: `kubed/mcp_kb/catalogue/index.py` (`PromptRow` loses `content`, `description`,
  `argument_hint`; `_globs_from_dict` loses `command_map`; `INDEX_VERSION = 9`)
- Modify: `kubed/mcp_kb/catalogue/prompts/__init__.py` (`PromptSource` is `path` and `name`;
  delete `_inline` and the inline branch of `load_prompt`)
- Modify: `docs/superpowers/specs/plugins-and-libraries.md` (PLG-12, PLG-15, PLG-21, PLG-23,
  PLG-25, PLG-26), `docs/superpowers/specs/prompts.md` (PRM-7, PRM-15),
  `docs/superpowers/specs/agents.md` (the usable-name reference at line 55), `AGENTS.md` ("a
  `commands` map's key")
- Test: `tests/test_plugins.py`, `tests/test_index.py`, `tests/test_parity.py`,
  `tests/test_marketplace.py`

**Interfaces:**
- Produces: `Components(commands=(), …)` with `notes` holding `commands object map is not served`
  for a map, so the map still replaces the conventions (PLG-21).

- [ ] **Step 1: Write the failing test**

```python
def test_an_object_map_serves_nothing_and_says_so(tmp_path):
    read = read_components({"commands": {"brief": {"source": "./cmds/brief.md"}}})
    assert (read.commands, read.command_files, read.command_dirs) == ((), (), ())
    assert read.notes == ("commands object map is not served",)
```

In `tests/test_parity.py`, the end-to-end map tests become one test. A `plugin.json` with
`{"commands": {"brief": {"content": "Hi."}}}` beside `prompts/x.md` serves no prompt, and the
plugin's `/health` `notes` hold the note. Delete `CommandEntry`'s round trip from
`tests/test_index.py` and the map cases from `tests/test_plugins.py`.

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_plugins.py -k object_map -v`
Expected: FAIL, because `_command_map` still reads the map.

- [ ] **Step 3: Implement**

`_commands(value, notes)`: for a dict it appends the note and returns `((), (), ())`; the rest is
as now, without the map. Remove every `command_map` and `_mapped` use.
`grep -rn "command_map\|CommandEntry\|_mapped\|_inline\|argument_hint" kubed tests` returns
nothing.

- [ ] **Step 4: Update the spec and AGENTS.md**

- PLG-21: a `commands` may be a path or a list of paths. An object map serves nothing. It still
  replaces the conventions, and the plugin notes `commands object map is not served` (PLG-26).
  Drop the map's keys, its item rules and the inline path.
- PLG-12: drop "an object-map command is `claude` whatever the plugin's `dialect` says".
- PLG-15: `commands` takes one string, a list of strings, or an object map, which PLG-21 serves
  as nothing.
- PLG-23: drop "a `commands` map item whose `source` is in `commands/`".
- PLG-25: drop the map row.
- PLG-26: the map bullet becomes the one note.
- PRM-7: drop both "and so is an inline command's".
- PRM-15: drop the map sentence.
- agents.md line 55: "as a `commands` map key is (PLG-21)" becomes "as a name PLG-25 builds is".
- AGENTS.md "Adding a prompt": drop ", a `commands` map's key".

- [ ] **Step 5: Run the checks**

Run: `ruff check .` then `pytest tests/test_plugins.py tests/test_index.py tests/test_parity.py tests/test_marketplace.py tests/test_prompts.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A kubed/mcp_kb tests docs/superpowers/specs AGENTS.md
git commit -m "Object-map commands are not served (P1): CommandEntry and the inline body go"
```

### Task 3: The plugin layer serves kb's prompts

**Files:**
- Modify: `kubed/mcp_kb/catalogue/harvest.py` (add `command_entries` beside `prompt_files`)
- Modify: `kubed/mcp_kb/catalogue/index.py` (delete `PromptRow`; `PluginRecord.prompts:
  tuple[str, ...]`, add `claude_prompts: tuple[str, ...] = ()`; module docstring)
- Modify: `kubed/mcp_kb/catalogue/snapshot.py`:
  - `build_plugin` records paths and parses nothing;
  - add `PluginCommands` and `Snapshot.commands`, `Snapshot.visible_prompts`;
  - `build_snapshot` and `_serve_library` load no prompt; `_plugin_status` counts
    `record.prompts`;
  - delete `_load_prompts`, `_dialect`, `vanished`, `_Admitted.prompts`, the prompt loop in
    `_admit` and `_Claims.prompts`
- Modify: `kubed/mcp_kb/catalogue/prompts/__init__.py` (delete `PromptSource`, `_source`,
  `load_prompt`, `load_prompts`, `FilePrompt.body`, `FilePrompt.live`; `render(arguments)` only;
  module docstring)
- Modify: `kubed/mcp_kb/mcp/skills.py` (`entry_for`, `_ENTERING`, `_reading`,
  `_Published.prompts`, `read_command`, `rewrite`'s `"command"` branch, `_publish`'s skip rule,
  `_narrowed`; delete `COMMANDS_ARE_KBS`; module docstring)
- Modify: `kubed/mcp_kb/mcp/prompts.py` (delete `PromptProvider`; `adapt`; `MCPFilePrompt` holds
  `file` only; `_filled` without `prefixed`; `register(mcp)`)
- Modify: `kubed/mcp_kb/mcp/pins.py:162`, `kubed/mcp_kb/app.py:92`, `kubed/mcp_kb/__init__.py`
  (drop `load_prompts`)
- Modify: `docs/superpowers/specs/prompts.md` (PRM-2, PRM-4, PRM-18, PRM-41 to PRM-44, PRM-47),
  `plugins-and-libraries.md` (PLG-18, PLG-25, LIB-28, LIB-29, LIB-33), `skills.md` (SKL-41),
  `AGENTS.md`, `.github/copilot-instructions.md:106`
- Test: `tests/test_prompt_serving.py` (create); migrate `tests/test_prompts.py`,
  `tests/test_scope_and_prompt_tools.py`, `tests/test_plugin_serving.py`,
  `tests/test_placeholders.py`, `tests/test_dialects.py`, `tests/test_parity.py`,
  `tests/test_refresh.py`, `tests/test_assembly.py`, `tests/test_address_space.py`,
  `tests/test_example_config.py`, `tests/test_index.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: Task 1's `parse_prompt`, `dialect_of`, `READ_ERRORS`; Task 0's merged `_PINNED`.
- Produces:
  - `harvest.command_entries(selected: Sequence[str], command_dirs: Sequence[str]) -> tuple[str, ...]` (D1).
  - In `catalogue/snapshot.py`:

    ```python
    @dataclass(frozen=True)
    class PluginCommands:
        selected: tuple[str, ...]      # kb's prompt files, root-relative, in path order
        claude: frozenset[str]         # those a commands declaration selects (PRM-14 rule 5)
        command_dirs: tuple[str, ...]  # declared command folders, for PLG-25's names
        entries: tuple[str, ...]       # command_entries(selected, command_dirs)
    ```

    `Snapshot.commands: Mapping[str, PluginCommands]` by plugin id, and
    `Snapshot.visible_prompts(scope: Scope = EVERYTHING) -> list[FilePrompt]`.
  - `entry_for(plugin: Plugin, commands: PluginCommands | None = None) -> dict[str, object]`.
  - `SkillServing._reading(self) -> tuple[_Published, bool]`: the `_Published` to read and
    whether it is add time (D6). `rewrite` and `agent_meta` take its first item.
  - `SkillServing.read_command(self, text: str, path: str, name: str, plugin: Served) -> Prompt | str`.
  - `mcp/prompts.adapt(file: FilePrompt) -> MCPFilePrompt`; `register(mcp: QuickMCP) -> set[str]`.
  - `FilePrompt.render(self, arguments: dict[str, object] | None = None) -> str`.
  - `NOT_SELECTED = "not one of the plugin's prompt files"` and
    `RENAMED = "named {name} by the plugin layer and {expected} by kb"` in `mcp/skills.py`.

- [ ] **Step 1: Write the failing tests**

`tests/test_prompt_serving.py` uses `market()` and `_write()` from `tests/test_plugin_serving.py`,
and `server_of`, `serve_http` and `http_client` from `tests/conftest.py`. `CMD` is
`"---\ndescription: D.\n---\nBody.\n"`.

```python
async def test_every_name_is_plg25s(tmp_path):
    kb = KnowledgeBase(market(tmp_path, [{"name": "lib", "source": "./"}], {
        "skills/s/SKILL.md": SKILL, "commands/db/migrate.md": CMD, "commands/top.md": CMD,
        "prompts/sub/debug.md": CMD, ".github/prompts/x.prompt.md": CMD,
    }), tmp_path / "cache")
    async with Client(server_of(kb)) as client:
        names = sorted(p.name for p in await client.list_prompts())
    assert names == ["lib_db_migrate", "lib_debug", "lib_top", "lib_x"]
    assert names == sorted(p.name for p in kb.prompts)
    assert kb.status["libraries"]["lib"]["prompts"] == 4


async def test_a_partial_glob_in_commands_serves_only_what_it_selects(tmp_path):
    # a declared plugin with prompts: ["commands/*.md"]; commands/a.md, commands/db/x.md
    assert names == ["lib_a"]
    assert not [r for r in kb.status["plugins"]["p"].get("skipped", ())
                if r["path"] == "commands/db/x.md"]


async def test_conventions_serve_beside_a_strict_false_entry(tmp_path):
    # entry {"name": "kit", "source": "./", "strict": False}, plugin.json {"name": "kit"},
    # prompts/x.md and .github/prompts/y.prompt.md
    assert names == ["lib_x", "lib_y"]
    assert "conflicts" not in kb.status["libraries"]["lib"]


async def test_a_declared_prompts_list_beats_the_manifests_commands(tmp_path):
    # declared plugin, prompts: ["mine/*.md"]; plugin.json commands ["./commands/"]
    assert names == ["lib_one"]


async def test_a_same_named_prompt_is_skipped_once(tmp_path):
    # commands/debug.md and prompts/debug.md
    assert names == ["lib_debug"]
    rows = [r for r in kb.status["plugins"][pid]["skipped"] if r["path"] == "prompts/debug.md"]
    assert rows == [{"path": "prompts/debug.md",
                     "reason": "prompt lib_debug is already served by commands/debug.md"}]


async def test_a_broken_prompt_is_skipped_with_kbs_reason(tmp_path):
    # prompts/bad.md has no frontmatter
    assert {"path": "prompts/bad.md", "reason": "no YAML frontmatter"} in skipped


async def test_a_later_plugin_with_a_claimed_name_conflicts(tmp_path):
    # two entries a, b in lib, each with prompts/x.md
    conflict = kb.status["libraries"]["lib"]["conflicts"]["b@lib"]
    assert conflict.startswith("conflict: prompt lib_x is already served by plugin")
    assert str(tmp_path / "cache") not in conflict


async def test_out_of_scope_is_unknown(tmp_path):
    # two libraries; a client pinned with Kb-Library: one gets "Unknown prompt" for the other's,
    # the same message as for a name nobody serves


async def test_names_and_plugin_root_render_at_build_and_arguments_as_typed(tmp_path):
    # commands/cite.md: "Read ${CLAUDE_PLUGIN_ROOT}/shared/x.md, use lib:s, say $ARGUMENTS\n"
    text = (await client.get_prompt("lib_cite", {"arguments": "${CLAUDE_PLUGIN_ROOT}"})).messages[0].content.text
    assert text == "Read skill://lib/shared/x.md, use skill://lib/s/SKILL.md, say ${CLAUDE_PLUGIN_ROOT}\n"  # P2


async def test_elicitation_survives_the_prefix(tmp_path):
    # mcp-kb dialect, a required `app`; over serve_http with Kb-Resource-Prefix: kb+ at
    # protocol 2026-07-28 and form elicitation declared, as tests/test_prompts.py's
    # elicitation test connects: prompts/get without `app` is input-required; the answering
    # round renders "kb+skill://lib/…" exactly once ("kb+kb+" absent)


async def test_a_description_is_served_as_written(tmp_path):
    # description "See skill://lib/s/SKILL.md." under Kb-Resource-Prefix: kb+  (D9)
    assert prompt.description == "See skill://lib/s/SKILL.md."


async def test_no_default_folder_note_for_the_conventions(tmp_path, caplog):
    # commands/a.md and prompts/b.md, no manifest commands
    assert "Default commands/ folder is ignored" not in caplog.text


def test_command_entries_follow_the_selection():
    assert command_entries(
        [".github/prompts/y.prompt.md", "commands/a.md", "commands/db/x.md",
         "prompts/b.md", "cmds/sub/c.md"],
        ["cmds/sub"],
    ) == (".github/prompts/y.prompt.md", "commands", "prompts/b.md", "cmds/sub")
```

Write each commented case out in full, in the shape of the first test.

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/test_prompt_serving.py -v`
Expected: `test_command_entries_follow_the_selection` fails on the import. The served tests fail
on names, because kb's `PromptProvider` serves and the layer skips every command. The
elicitation and description tests may pass already; they pin the switch.

- [ ] **Step 3: Implement the harvest side**

- `command_entries`: for each selected path in order, take the deepest of `COMMAND_DIRS` and
  `command_dirs` that contains it (`"."` contains every path), as `prompt_name` decides. Emit
  that folder, or else the file, and each entry once, at its first file. `entry_for` writes
  each entry with a leading `./` (the root as `./`): rc2 notes and logs every manifest path
  that lacks one (`commands path 'x' does not start with ./`), on every read. The test above
  compares the bare entries.
- `build_plugin`:
  - `prompts=tuple(_relative(p, root) for p in harvest.prompt_files(root, globs))`;
  - `claude_prompts` = the subset in `harvest.command_files(root, globs)`;
  - no parsing.
- `build_snapshot`:
  - `commands = {pid: PluginCommands(record.prompts, frozenset(record.claude_prompts), globs.command_dirs, command_entries(...))}`
    for every `ok` record;
  - `prompts=()`;
  - a library's `prompts` count is the sum of `len(record.prompts)` over the plugins it serves,
    which `_narrowed` replaces.
- `visible_prompts`: `scope.admits(p.library, p.category, p.tags, library_categories=p.library_categories)`
  over `self.prompts`.

- [ ] **Step 4: Implement the serving side**

- `entry_for(plugin, commands)`: with `commands`, `entry["commands"] = list(commands.entries)`,
  and `strict` is dropped when it is `False` (D1). `_add` passes
  `snapshot.commands.get(plugin.id)`.
- `_ENTERING` and `_reading()` per D6. `_publish` sets `_ENTERING` around its loop where it set
  `self._entering`, and resets it in the `finally`. `agent_meta` and `rewrite` read
  `_reading()`.
- `_publish`:
  - skip a plugin only when it has no skill, no agent and no selected prompt;
  - `self._prompt_reads: dict[Key, dict[str, FilePrompt]]` is cleared with `_reads`;
  - `_Published(…, prompts=…)` holds, by key, this publish's reads for each plugin added and the
    published reads for each plugin kept.
- `read_command`:

```python
published, adding = self._reading()
key = (plugin.namespace, plugin.address)
row = published.table.get(key)
commands = None if row is None else published.snapshot.commands.get(row.plugin.id)
if commands is None or path not in commands.selected:
    return NOT_SELECTED
root = Path(plugin.root)
expected = f"{row.library}_{prompt_name(root / path, root, commands.command_dirs)}"
if name != expected:
    return RENAMED.format(name=name, expected=expected)
last = published.prompts.get(key, {}).get(path)
dialect = (
    dialect_of(path, configured=row.plugin.dialect, claude=commands.claude)
    if adding or last is None
    else last.dialect
)
try:
    file = parse_prompt(text, root / path, name=name, library=row.library, ...)
except READ_ERRORS as exc:
    return self._clean(str(exc), row.plugin)
if adding:
    self._prompt_reads.setdefault(key, {}).setdefault(path, file)
return adapt(file)
```

- `rewrite`, `site.kind == "command"`: `head, body = split_frontmatter(text)`. With no `head`,
  return the text as written. Otherwise return
  `head + catalogue.agent_instructions(row.library, row.plugin.id, body, requested_scope())`
  (D4), and widen that method's docstring to an agent's or a command's body.
- `_narrowed`, for each added `(lib, plugin, served)` (D5):
  - its prompts are the first read of each name in `served.prompts`, in read order, joined to
    `snapshot.prompts`;
  - the library's `prompts` count is how many it served; the plugin's is set by the first
    library that serves it;
  - its `skipped` gains `{"path", "reason"}` for each `served.skipped` path in
    `commands.selected` that did not serve, whose reason is not `NOT_SELECTED`, first reason
    only;
  - a selected path the layer neither served nor skipped is noted once:
    `prompt file <path> of plugin <id> is not served: the plugin layer did not read it`.

  Status plugins are rebuilt like status libraries.
- `mcp/prompts.py`:
  - `MCPFilePrompt` holds `file`, and `_filled` returns `self.file.render(arguments)`;
  - `adapt` is `_adapt`, made public;
  - `PromptProvider` and the `names`, `Catalogue`, `SCHEME`, `prefix`, `prefixed`, `EVERYTHING`
    and `Scope` imports go;
  - `register(mcp)` adds only `ReadOnlyPromptsAsTools(mcp.server)` and returns `PROMPT_TOOLS`.
- The log filter (P8, Dr K's ruling): `mcp/skills.py` defines `QuietSelection`, a
  `logging.Filter` that `create_app` adds once to the `kubed.mcp.plugins` logger. It drops a
  record whose `msg` is `"prompt %s is skipped: %s"` and whose last arg is `NOT_SELECTED`, and
  nothing else. The skip still reaches `Plugin.skipped`, and so `/health`'s rule above. Adding
  it twice (two apps in one process) must not stack: the filter is added only when the logger
  has none of its class. Test in `tests/test_prompt_serving.py`:
  `test_a_file_kb_left_out_is_not_logged`, a `commands/` folder with one file outside a
  config's `prompts:` glob, asserting no `is skipped` line for it in `caplog` and the
  `Default commands/ folder is ignored` note still logged when that applies.
- `pins._serving`: `if snapshot.visible_prompts(scope): return True`.
  `app.py`: `prompt_tools = prompts.register(mcp)`.
- `catalogue/prompts`: delete what the Files list says. `render` keeps the missing-argument
  check and `DIALECTS[self.dialect].substitute(self.template, values)`.
- `grep -rn "PromptProvider\|PromptRow\|load_prompts\|_load_prompts\|PromptSource\|COMMANDS_ARE_KBS\|\.body()" kubed tests`
  returns nothing.

- [ ] **Step 5: Migrate the suite**

- A test that reads `knowledge_base.prompts` or `snapshot.prompts` calls
  `server_of(knowledge_base)` first, because the prompts are what the layer serves.
- A test that built a `PromptProvider` goes through `Client(server_of(kb))`.
- `tests/test_placeholders.py`'s prompt cases render through the server, or through
  `Catalogue.agent_instructions` for the body.
- `tests/conftest.py`: `load_library_prompts` and `load_all_prompts` go, and so do their callers'
  uses.
- `tests/test_plugin_serving.py::test_kubed_mcp_serves_no_prompt` becomes
  `test_kubed_mcp_serves_the_prompts`: the same names, and P6 as Task 0 recorded it.
- `tests/test_index.py`: a `PluginRecord` with `prompts` and `claude_prompts` paths round-trips.
- Extend #94's worker-thread test in `tests/test_live.py` (a refresh published while a context
  is pinned) with a command whose body cites `lib:s`. The pinned build renders it against its own
  generation's names (D6).

- [ ] **Step 6: Update the spec, AGENTS.md and the Copilot rules**

- PRM-2: a client sees a prompt when the plugin layer's view admits its plugin, which is kb's
  scope (SCP rules), and out of scope reads as absent.
- PRM-4: the skip rows come from the plugin layer's read, with kb's reasons.
- PRM-18: the dialect is decided each time the plugin is read, by PRM-14. A build of the read
  reads it in that dialect.
- PRM-41: the prefix is the namespace's first segment (PLUG-63), shared by every plugin of the
  library (PLUG-17), and the name below it is PLUG-62's, which is PLG-25's.
- PRM-42, PRM-43 and PLG-25: the reasons quote the full name (P4).
- PRM-44 and LIB-28: the plugin layer refuses the later plugin (PLUG-18), reported as LIB-29
  says.
- PRM-47: names (PRM-62) and `${CLAUDE_PLUGIN_ROOT}` (PRM-48, PRM-61) are resolved when the
  build is made. The dialect's placeholders are filled at render, and the gateway prefix is the
  plugin layer's, last (GW-7). An argument's value is never rewritten.
- PLG-18: the prompt rows are the plugin layer's.
- LIB-29: a refused plugin's prompts read as absent too (P5).
- LIB-33: `skills: []` serves no prompt either.
- SKL-41: rendered prompts move to the plugin layer's row of "Written by" (GW-7). The
  description sentence states D9, without its *(proposed)* clause.
- AGENTS.md:
  - the `mcp/skills.py` row: `read_command` is kb's dialect reader, and `rewrite` renders a
    command's body;
  - the `mcp/prompts.py` row: `MCPFilePrompt`, `adapt`, the prompt mirror;
  - "Commands are kb's prompts until K4…" becomes the reader and D2;
  - the "provider that stores a `Catalogue`" bullet no longer names the prompts;
  - "A live read blocks the whole event loop" drops `catalogue/prompts/` (`FilePrompt.body()`).
- `.github/copilot-instructions.md:106`: "`Catalogue`, `SkillIndex` and `PromptProvider` read"
  becomes "`Catalogue` and `SkillIndex` read, and the plugin layer's view,".

- [ ] **Step 7: Run the checks**

Run: `ruff check .` then `pytest -q`
Expected: ruff is clean and the suite is green. `tests/test_live.py`'s three `PromptProvider`
tests are deleted here, and Task 4 writes their replacements.

- [ ] **Step 8: Commit**

```bash
git add -A kubed/mcp_kb tests docs/superpowers/specs AGENTS.md .github/copilot-instructions.md
git commit -m "kubed-mcp serves kb's prompts through kb's command_reader; PromptProvider goes"
```

### Task 4: Live prompts re-read their plugin (P3)

**Files:**
- Modify: `kubed/mcp_kb/mcp/skills.py` (`_Watch.commands`, `_watch`, `_stamp`, `_add`, `_vet`)
- Modify: `docs/superpowers/specs/prompts.md` (PRM-58, PRM-59, PRM-60)
- Test: `tests/test_live.py`

**Interfaces:**
- Consumes: Task 3's `_Published.prompts`, `PluginCommands`, `parse_prompt`, `dialect_of`.
- Produces: `_stamp(snapshot: Snapshot, skills: Sequence[Skill], files: Sequence[Path]) -> tuple`
  (was `agents`), and `SkillServing._vet(self, key: Key, row: _Row, root: Path) -> None`, which
  raises `ValueError(f"prompt {path}: {reason}")`.

- [ ] **Step 1: Write the failing tests**

Replace the three `PromptProvider` tests. Each one changes the file's length (wsgidav's ETag) and
reads twice (AGENTS.md: a live edit reads one request late).

```python
async def test_a_live_prompt_edit_serves_from_the_next_request(webdav, tmp_path):
    webdav.write("prompts/p.md", PROMPT.format(body="the first body"))
    kb = _knowledge_base(webdav, tmp_path)
    async with Client(server_of(kb)) as client:
        assert "the first body" in await _rendered(client, "notes_p")
        webdav.write("prompts/p.md", ARGUED.format(body="the second, longer body {{ who }}"))
        assert "the first body" in await _rendered(client, "notes_p")  # noticed here
        assert "the second, longer body you" in await _rendered(client, "notes_p", who="you")
        (listed,) = [p for p in await client.list_prompts() if p.name == "notes_p"]
        assert [a.name for a in listed.arguments] == ["who"]  # PRM-59


async def test_a_live_prompt_saved_mid_edit_keeps_the_last_good_build(webdav, tmp_path, caplog):
    # write "argument-hint: [a] [b]" (no YAML parser takes it); read twice: the first body both
    # times, and one WARNING naming "was not read again" and prompts/p.md; then a longer valid
    # edit serves from the request after the one that noticed it


async def test_a_live_prompt_saved_too_deep_keeps_the_last_good_build(
    webdav, tmp_path, caplog, frontmatter_out_of_stack
):
    # the same, with DEEP_YAML; the warning says "nested too deeply"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/test_live.py -k live_prompt -v`
Expected: FAIL. The watch does not stamp command files, so the edit never serves.

- [ ] **Step 3: Implement**

- `_Watch.commands: tuple[Path, ...] = ()` holds `root / rel` for each
  `snapshot.commands[plugin.id].selected`. `_watch` fills it, and both `_watch` and
  `_reread_live` stamp `(*watch.agents, *watch.commands)`.
- `_vet(key, row, root)`, for each path in `self._published.prompts.get(key, {})`:
  - read `root / path`;
  - `parse_prompt` it in `dialect_of(...)`'s dialect (PRM-59: the dialect follows the edit);
  - on `OSError` or `READ_ERRORS`, raise `ValueError(f"prompt {path}: {reason}")`, with the
    reason passed through `_clean`.
- `_add` calls `_vet` before `staged.add` when `served_now is not None` (a re-read). The existing
  `except` keeps the plugin as served and notes it once (D7). A moved plugin keeps its new stamp,
  so it is not tried again until a file moves.

- [ ] **Step 4: Update the spec**

- PRM-58: a prompt from a `cache: live` source is revalidated when a request's scope admits its
  plugin, as SKL-37 says for a skill. A moved file re-reads the plugin, and the prompt as edited
  serves from the next request.
- PRM-59: its arguments, defaults and dialect are read from the edited file.
- PRM-60: when an edited prompt file the plugin served does not read (unreadable, no frontmatter
  block, YAML that does not parse or is nested too deeply), the plugin keeps the build it served.
  kb logs one warning, and tries again when a file of the plugin moves.

- [ ] **Step 5: Run the checks**

Run: `ruff check .` then `pytest tests/test_live.py tests/test_prompt_serving.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add kubed/mcp_kb/mcp/skills.py tests/test_live.py docs/superpowers/specs/prompts.md
git commit -m "A live prompt's edit re-reads its plugin, and a broken one keeps the last good build"
```

### Task 5: A library named `mcp-kb` is refused (P7)

**Files:**
- Modify: `kubed/mcp_kb/config.py` (`SERVER_NAME = "mcp-kb"`, and `LibraryConfig`'s name
  validator), `kubed/mcp_kb/app.py:40`
- Modify: `docs/superpowers/specs/plugins-and-libraries.md` (LIB-1's `name`, or the next free
  LIB ID: check with `grep -o 'LIB-[0-9]*' docs/superpowers/specs/*.md | sort -u`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `config.SERVER_NAME`, which `create_app` passes to `QuickMCP`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_library_named_like_the_server_is_refused():
    with pytest.raises(ValidationError, match="the server's own name"):
        Config.model_validate({"libraries": [{"name": "mcp-kb", "source": "file:///x"}]})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_config.py -k server -v`
Expected: FAIL, because the config loads.

- [ ] **Step 3: Implement**

The validator refuses `SERVER_NAME` with
`library name 'mcp-kb' is the server's own name, whose prompts the plugin layer would not prefix`.

- [ ] **Step 4: Run the checks**

Run: `ruff check .`, then `pytest tests/test_config.py tests/test_wiki.py -v`, then
`python -c "import json,kubed.mcp_kb.config as c; assert json.load(open('config.schema.json')) == c.schema()"`
Expected: all pass, and the committed schema still matches.

- [ ] **Step 5: Commit**

```bash
git add kubed/mcp_kb/config.py kubed/mcp_kb/app.py tests/test_config.py docs/superpowers/specs
git commit -m "A library named like the server is refused: its prompts would have no prefix"
```

### Task 6: The wiki, the changelog and the whole suite

**Files:**
- Modify: `wiki/Prompts.md` (drop "the commands map" section; rewrite the live paragraph at
  ~289 to PRM-58 to PRM-60), `wiki/Plugins.md:106-107`, on the wiki's `issue-82` branch
- Modify: `CHANGELOG.md` (`[Unreleased]`: one **BREAKING:** line for P1, one line for P7;
  Dr K's ruling, no `no changelog` label)

- [ ] **Step 1: Update the wiki**

Make the pages say what the spec now says. Run `python scripts/generate_wiki.py`, and commit
whatever it moves on the wiki's `issue-82` branch.

- [ ] **Step 2: Run every check**

Run: `ruff check .`, then `pytest`, then `python scripts/generate_wiki.py --check`, then
`python scripts/generate_openapi.py` and the OpenAPI lint CI runs on its output.
Expected: ruff is clean. pytest is green, with the K3 baseline's skips and its one xfail (N15).
The wiki check and the lint are clean.

- [ ] **Step 3: Commit, and write the PR body**

```bash
git add -A CHANGELOG.md wiki
git commit -m "K4: the wiki and the release notes for prompts through the plugin layer"
```

The PR body carries the named changes P1 to P9 with P6 as Task 0 recorded it, D9, and the checks
from #82's notes with their results: names, elicitation, live, the `mcp-kb` edge and `/health`.
QA's dump is over the ten scopes, with and without `kb+`, before and after deploy.
