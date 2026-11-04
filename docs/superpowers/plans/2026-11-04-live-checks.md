# Live Checks Against a Running kb Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A repeatable `pytest -m live --kb-url <url>` run that checks a running kb (a local
`mcp-kb`, or a deployment) against AGT-6/7/8/16/17, PLG-17 and PLG-20 to PLG-27, and the rows
#47, #49 and #50 added, using committed fixture plugins.

**Architecture:** A `live` marker and a `--kb-url` option. Without the option, every live check is
skipped, so CI's plain `pytest` never runs one. The checks live in `tests/live/` and talk to kb only
over HTTP (MCP at `/mcp`, `/health` and `/openapi.yaml`). The fixtures are a Claude-format
marketplace under `tests/fixtures/live/`. Locally, kb reads it as a `file://` library. A deployment
reads it as a git library pinned to a commit
(`<git source>://kubed-io/mcp-kb//tests/fixtures/live?ref=<sha>`). The live re-read (AGT-16) needs
a WebDAV share that the check can edit, so it also takes `--kb-dav-dir` and skips without it.

**Tech Stack:** Python ≥3.11, pytest + pytest-asyncio (`asyncio_mode = "auto"`), FastMCP 4's
`Client` over `StreamableHttpTransport`, httpx, PyYAML, and `tests/webdav_server.py` (wsgidav and
cheroot) run as a standalone process.

**Spec:** issue #51 (the brief and Dr K's ruling of 2026-11-04 05:06), and this file's Design
section. No requirement changes: this pull request adds checks, not behaviour. The requirements it
checks are in `docs/superpowers/specs/agents.md`, `plugins-and-libraries.md`, `skills.md`,
`prompts.md` and `http-and-tools.md`.

## Design

**What is settled (Dr K, #51).**
- **Split.** The server-side checks are kept in the repo as `tests/live/`, under a `live` marker,
  with their fixtures in `tests/fixtures/live/`. The client half (the Claude Code mod) is run once,
  and its recipe and results are posted on #51. Neither goes in the repo.
- **Report only.** A check that finds kb breaking its spec is not fixed here. It becomes its own
  Bug (see Global Constraints).
- **#35's six review follow-ups are not rows.** These are: listed commands still matched as globs,
  deep YAML frontmatter as a parser limit, folder segments, `version` precedence against Claude
  Code, re-harvesting cross-repository entries, and an `agents:` config key. Each is filed on its
  own. Where a row touches one, it checks kb's *current* specified behaviour and says so in a
  comment: PLG-17's "the entry's `version` wins" is checked as specified, not as Claude Code might
  differ.

**What this plan settles beyond the issue.**
- **The fixtures are one marketplace.** `tests/fixtures/live/.claude-plugin/marketplace.json`
  lists one entry per case, each at `./plugins/<case>`, each with a `.claude-plugin/plugin.json`.
  A deployment then needs one library line per marketplace and nothing else. Every plugin is
  Claude-format, so agents apply (AGT-4).
- **AGT-8's unserved row needs a second marketplace.** It needs two plugins of the same *name*,
  and one marketplace cannot hold two entries of one name. So `tests/fixtures/live/other/` is a
  marketplace of its own, with one entry, `second`, whose source is `./`. In a deployment, both
  marketplaces share one fetch (PLG-7).
- **"An appended plugin renames nothing" compares two libraries; it does not reindex.** A pinned
  git ref cannot change in the middle of a run. `clash` lists `first@live, second@live,
  second@live-other`, and `clash-appended` lists the same three plus `late@live`. The appended
  library's owners, with the library prefix stripped, must be `clash`'s plus `reviewer@late`. This
  is the claim AGT-8 makes: names are decided by library order alone.
- **The sibling rows go in now.** #47 (HTTP-41), #49 (SKL-53) and #50 (AGT-17, SKL-55, PRM-62)
  are already in the code on `issue-38`.
- **Every request that concerns one library is scoped with `Kb-Library`.** A deployment serves its
  own libraries beside the fixtures, and a scoped request cannot see them.
- **AGT-16 runs against a WebDAV share that the check writes to directly.** `--kb-dav-dir` is the
  local folder that the running kb's `dav` source serves. Locally, that folder is served by
  `python -m tests.webdav_server`. A deployment has no such folder by default, so the check skips.
  Each edit changes the file's length, because wsgidav's ETag is `inode-mtime-size`. Each edit
  then waits `sources.live.TTL_SECONDS + 0.5` before reading. The check restores the file in a
  `finally`.
- **Module names.** The modules are `tests/live/test_live_*.py`, with a `tests/live/__init__.py`.
  The issue's working name `tests/live/test_live.py` would read as the existing
  `tests/test_live.py` (the `cache: live` unit tests).
- **The local config** is `tests/fixtures/live/config.yaml`. It carries the literal token `@ROOT@`
  for the checkout's absolute path, because a `file://` address must be absolute (PLG-5). The
  recipe in CONTRIBUTING.md substitutes the token with `sed`.

**After the code (Dr K, not the code agent).** These steps are in the Handoff section at the end:
a run against a deployment of the branch image `:<sha>`, and the client half. Results for both go
on #51.

## Global Constraints

- **CI's checks** (`test.yml`): `pip install -e ".[test]"`, `ruff check .`, `pytest`, from the
  repository root with the `wiki/` submodule checked out (`git submodule update --init`). Plain
  `pytest` must report every `tests/live/` test as skipped and none as failed.
- **The live run** is the recipe in CONTRIBUTING.md's "Live checks" section, which ends in
  `pytest -m live --kb-url http://127.0.0.1:8000 [--kb-dav-dir="$LIVE/dav"]`.
- **No change under `kubed/`.** When a live check fails, first check the fixture and the
  expectation against the spec. If kb is what is wrong, keep the assertion as the spec says. Mark
  the test `@pytest.mark.xfail(strict=True, reason="<REQ>: <what kb does instead>; bug to file")`
  and list it in the PR description for Dr K to file. Never loosen an assertion so that it passes.
- **Every live module** sets `pytestmark = pytest.mark.live`. Every test's docstring opens with
  the requirement IDs it checks (`"""AGT-8: …"""`).
- **No new dependency.** httpx, PyYAML, FastMCP, wsgidav and cheroot are already in `.[test]`.
- **Fixtures** are never added to `examples/config.yaml`.
  - No real hostnames: an MCP server's URL is `https://example.invalid/<name>`.
  - No people's names. The test WebDAV credential is the one `tests/webdav_server.py` already
    holds.
  - Every file is written as frontmatter, then a line `---`, then the body with no blank line
    before it, then a final newline.
- **Python 3.11 is the floor.** Lines are at most 88 columns (`tests/*` ignores E501).
- **No changelog line.** The pull request takes the `no changelog` label (internal work,
  CONTRIBUTING.md).
- **Commits** are conventional (`test: …`) and end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **CI never runs a live check, and never silently drops one.** Plain `pytest` skips every
   `tests/live/` test with the reason `a live check: needs --kb-url`, and exits 0. → Task 1,
   `test_the_live_checks_skip_without_a_url`.
2. **A deployment that serves other libraries.** A scoped request sees only its fixture library,
   so a deployment's own agents and prompts cannot make an exact-list assertion fail. → every
   helper in Task 1's `tests/live/kb.py` takes `library` and sends `Kb-Library`. Tasks 2 and 3
   assert exact lists through those helpers.
3. **An edit read before kb looks again.** A same-length edit, or a read inside the 2-second TTL,
   would pass AGT-16 for the wrong reason or fail it for no reason. → Task 4's `_edit` asserts the
   length changed and sleeps `TTL_SECONDS + 0.5`.
4. **A failed run leaves the share edited.** The next run must start from the fixture. → Task 4
   restores the file in `finally`. The recipe also copies the fixture fresh into `$LIVE` each run.
5. **A credential or backend URL in what the run prints.** An assertion failure prints `/health`
   and definitions into CI logs and #51. → Task 4,
   `test_health_names_no_dav_url_or_credential`.

---

### Task 1: The harness, and the two server rows

**Files:**
- Modify: `pyproject.toml`, `[tool.pytest.ini_options].markers`: add
  `"live: a check against a running kb, skipped without --kb-url"`.
- Modify: `tests/conftest.py`: add `pytest_addoption` and `pytest_collection_modifyitems`.
- Modify: `tests/webdav_server.py`: add `serve()`, `main()` and `if __name__ == "__main__"`.
- Create: `tests/live/__init__.py` (empty), `tests/live/conftest.py`, `tests/live/kb.py`,
  `tests/live/test_live_server.py`.
- Create: `tests/fixtures/live/.claude-plugin/marketplace.json`, holding
  `{"name": "live", "owner": {"name": "kubed-io"}, "plugins": []}`.
- Create: `tests/fixtures/live/config.yaml`. It opens with a comment naming `@ROOT@` and pointing
  at CONTRIBUTING.md's "Live checks". It has no sources and no plugins, and one library:
  `{name: live, source: "file://@ROOT@/tests/fixtures/live"}`.
- Modify: `CONTRIBUTING.md`:
  - in "Getting set up", end the sentence "…that is as far out as anything reaches." with
    "; `tests/live/` reaches a running kb, and skips unless it is given `--kb-url`";
  - add a section `## Live checks` before `## The changelog`. Its content is listed under Step 5.
- Test: `tests/test_live_harness.py` (new), `tests/live/test_live_server.py`.

**Interfaces:**
- Produces, in `tests/conftest.py`:
  - options `--kb-url` (default `None`; "a running kb's base URL, for tests/live") and
    `--kb-dav-dir` (default `None`; "the folder the running kb's dav source serves; AGT-16 edits
    it");
  - every item with `get_closest_marker("live")` gets
    `pytest.mark.skip(reason="a live check: needs --kb-url")` when `--kb-url` is unset.
- Produces, in `tests/live/conftest.py`:
  - fixture `kb_url(pytestconfig) -> str`, the option with the trailing `/` stripped (session
    scope);
  - fixture `dav_dir(pytestconfig) -> Path`, which calls
    `pytest.skip("needs --kb-dav-dir: the folder the running kb's dav source serves")` when unset.
- Produces, in `tests/live/kb.py`. Every `library` parameter becomes the header
  `Kb-Library: <library>`, and `None` sends no header.
  - `connect(kb_url: str, library: str | None = None, mode: str = "auto") -> Client`:
    `Client(StreamableHttpTransport(f"{kb_url}/mcp", headers=…), mode=mode)`
  - `async rpc(kb_url: str, method: str, library: str | None = None, **params) -> dict`, through
    `tests.test_skills_extension.request`
  - `health(kb_url: str) -> dict`, a sync `httpx.get(f"{kb_url}/health")`, which raises on a
    status that is not 2xx
  - `async agent_names(kb_url: str, library: str) -> list[str]`, the `agents/list` card names in
    the order served
  - `async definition(kb_url: str, name: str, library: str | None = None) -> dict`, the
    `agents/get` result
  - `async owners(kb_url: str, library: str) -> dict[str, str]`: each agent's name with its
    `"<library>_"` prefix removed, mapped to `definition(…)["_meta"]["io.kubed.mcp-kb/agent"]["plugin"]`
  - `async prompts(kb_url: str, library: str) -> dict[str, str | None]`, from prompt name to
    description
  - `async prompt_text(kb_url: str, name: str, library: str) -> str`, the first message's text
    from `get_prompt(name)`
  - `async read(kb_url: str, uri: str, library: str | None = None) -> str`, the text of
    `read_resource(uri)[0]`
  - `META = "io.kubed.mcp-kb/agent"`
- Produces, in `tests/webdav_server.py`:
  - `serve(root: Path, port: int) -> None`, blocking: `wsgi.Server(("127.0.0.1", port),
    _app(root, []))`, then `safe_start()`;
  - `main(argv: list[str] | None = None) -> None`, with `--root` (required, `Path`) and `--port`
    (int, default `8090`). It serves `--root` as the `kb` share, with `USERNAME`/`PASSWORD`.

- [ ] **Step 1: Write the failing tests.** Add `tests/test_live_harness.py`:

```python
@pytest.mark.unit
def test_the_live_checks_skip_without_a_url():
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/live", "-q", "-rs", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    assert run.returncode == 0, run.stdout
    assert "a live check: needs --kb-url" in run.stdout
    summary = run.stdout.strip().splitlines()[-1]
    assert " skipped" in summary and "passed" not in summary and "failed" not in summary
```

  Add `tests/live/test_live_server.py` with `pytestmark = pytest.mark.live`:
  - `test_serverinfo_is_kbs_own_version` (HTTP-41). Let `expected = {"name": "mcp-kb",
    "version": yaml.safe_load(httpx.get(f"{kb_url}/openapi.yaml").text)["info"]["version"]}`.
    - `connect(kb_url, mode="legacy")`'s `initialize_result.serverInfo` gives
      `{"name", "version"} == expected`.
    - `(await rpc(kb_url, "agents/list"))["_meta"][SERVER_INFO_META_KEY] == expected`, with the
      key from `mcp_types`.
    - `expected["version"] != "0.0.0"`.
  - `test_one_template_names_the_skill_space` (SKL-53):
    `[(t.uriTemplate, t.name) for t in await client.list_resource_templates()] ==
    [("skill://{library}/{+path}", "skill")]`.
  - `test_every_fixture_plugin_is_ok`: in `health(kb_url)`:
    - every plugin whose id ends `@live` or `@live-other` has `status == "ok"` and no `error`;
    - the libraries `live` (and `live-other`, `clash`, `clash-appended`, `dav` when present) carry
      no `error` and no `conflicts`.

- [ ] **Step 2: Run them to verify they fail.**
  Run: `pytest tests/test_live_harness.py -v`
  Expected: FAIL. Before the marker and the skip exist, the live tests error or fail, and do not
  skip.

- [ ] **Step 3: Implement** the Interfaces block, the marker, `marketplace.json` and
  `config.yaml`.

- [ ] **Step 4: Run the harness test and the whole suite.**
  Run: `ruff check . && pytest`
  Expected: clean, all PASS, and the `tests/live/` tests are reported as skipped.

- [ ] **Step 5: Write CONTRIBUTING.md's "Live checks" section.** It says:
  - The live checks need a running kb and are not part of CI.
  - Locally, run this block, which Task 4 extends with the WebDAV lines:

```bash
LIVE=$(mktemp -d)
sed "s#@ROOT@#$PWD#g" tests/fixtures/live/config.yaml > "$LIVE/config.yaml"
mcp-kb --config "$LIVE/config.yaml" --cache-dir "$LIVE/cache" --host 127.0.0.1 --port 8000 &
until curl -sf http://127.0.0.1:8000/health >/dev/null; do sleep 1; done
pytest -m live --kb-url http://127.0.0.1:8000
```

  - Against a deployment:
    - add the config's libraries to the deployment's config, with each `file://@ROOT@/tests/fixtures/live…`
      source rewritten as `<its git source>://kubed-io/mcp-kb//tests/fixtures/live…?ref=<sha>`;
    - push the fixtures first, because a ref names a pushed commit;
    - run with `--kb-url <its URL>`.
  - The re-read check skips without `--kb-dav-dir`.

- [ ] **Step 6: Run the live checks locally.** Run Step 5's block.
  Expected: 3 passed. If `initialize_result` is `None` over HTTP in `legacy` mode, report what
  FastMCP's `Client` exposes. Do not drop the assertion.

- [ ] **Step 7: Commit** `test: a live marker and --kb-url, for checks against a running kb (#51)`

### Task 2: Agent names, definitions and qualified names

**Files:**
- Create the fixture plugins below under `tests/fixtures/live/plugins/`. Append their entries to
  `marketplace.json` in this order: `first`, `second`, `late`, `folders`, `listed-agents`,
  `deep-yaml`, `servers`, `servers-file`, `names`.
- Create the second marketplace, `tests/fixtures/live/other/`:
  - `.claude-plugin/marketplace.json`: `{"name": "live-other", "owner": {"name": "kubed-io"},
    "plugins": [{"name": "second", "source": "./"}]}`;
  - `.claude-plugin/plugin.json`: `{"name": "second"}`;
  - `agents/reviewer.md`.
- Modify: `tests/fixtures/live/config.yaml`. Add these libraries:
  - `live-other`, with `source: "file://@ROOT@/tests/fixtures/live/other"`;
  - `clash`, with `plugins: [first@live, second@live, second@live-other]`;
  - `clash-appended`, with the same plugins plus `late@live`.
- Create: `tests/live/test_live_agents.py`.

Each entry is `{"name": <case>, "source": "./plugins/<case>"}` plus the extra fields listed below.
Each plugin has `.claude-plugin/plugin.json` = `{"name": <case>}` plus the manifest fields listed.
In an agent file, frontmatter `name: n, description: d` with body `b` is written
`---\nname: n\ndescription: d\n---\nb\n`.

| Case | Entry / manifest extras | Files |
|---|---|---|
| `first`, `second`, `late`, and `other/` | — | `agents/reviewer.md`: `reviewer`, "Reviews, from <case>.", body "Review it." |
| `folders` | — | `agents/ops/oncall.md` (`oncall`, "On call."); `commands/db/migrate.md` (description "Migrate.", body "Migrate it."); `prompts/sub/check.md` (description "Check.", body "Check it.") |
| `listed-agents` | manifest `agents: ["./agents/deep/picked.md", "./agents/notes.txt", "./agents/gone.md"]` | `agents/deep/picked.md` (`picked`); `agents/stray.md` (`stray`); `agents/notes.txt` ("not an agent") |
| `deep-yaml` | — | `agents/hooked.md`, frontmatter as `HOOKED` below, body "Hooked." |
| `servers` | manifest `mcpServers: {"alpha": {"type": "http", "url": "https://example.invalid/alpha"}}`; **entry** `mcpServers: {"ignored": {"type": "http", "url": "https://example.invalid/ignored"}}` | `.mcp.json`: `{"mcpServers": {"beta": {"type": "http", "url": "https://example.invalid/beta"}}}`; `agents/wired.md` (`wired`) |
| `servers-file` | manifest `mcpServers: "./config/servers.json"` | `config/servers.json`: `{"mcpServers": {"gamma": {"type": "http", "url": "https://example.invalid/gamma"}}}`; `agents/filed.md` (`filed`) |
| `names` | — | `skills/lookup/SKILL.md` (`lookup`, "Looks things up.", body "Pairs with names:helper."); `skills/helper/SKILL.md` (`helper`, "Helps.", body "Helper body."); `agents/finder.md` (`finder`, "Finds things.", plus `skills: [lookup, "names:lookup", nowhere]`, body "Load names:lookup first, then run /names:lookup-cmd."); `commands/use.md` (description "Use the helper.", body "Use names:helper.") |

`HOOKED`, the YAML and the dict the test compares against:

```yaml
name: hooked
description: Has deep frontmatter.
hooks:
  PreToolUse:
    - matcher: Bash
      hooks:
        - type: command
          command: echo never-run
metadata:
  owners: [a, b]
  limits: {depth: 3, nested: {ok: true}}
```

**Interfaces:**
- Consumes: Task 1's `kb_url`, `health`, `agent_names`, `definition`, `owners`, `prompts`,
  `prompt_text`, `read` and `META`.

- [ ] **Step 1: Write the tests** in `tests/live/test_live_agents.py`. Every scoped call passes
  the library named, and `health` below means `health(kb_url)`. Write `HOOKED` as a dict literal.
  - `test_names_follow_library_order_and_folders` (AGT-7, AGT-8, AGT-5):
    `await agent_names(kb_url, "live") == ["live_filed", "live_finder", "live_hooked",
    "live_ops_oncall", "live_picked", "live_reviewer", "live_reviewer@late",
    "live_reviewer@second", "live_wired"]`.
  - `test_a_clash_is_renamed_and_its_rename_clash_unserved` (AGT-8):
    - `health(kb_url)["libraries"]["clash"]`:
      - `["renamed"] == {"clash_reviewer@second": "clash_reviewer is already served by plugin 'first@live'"}`
      - `["unserved"] == [{"plugin": "second@live-other", "path": "agents/reviewer.md", "reason": "clash_reviewer@second is already served by plugin 'second@live'"}]`
      - `["agents"] == 2`
    - `await owners(kb_url, "clash") == {"reviewer": "first@live", "reviewer@second": "second@live"}`.
  - `test_an_appended_plugin_renames_nothing` (AGT-8): `await owners(kb_url, "clash-appended") ==
    {**await owners(kb_url, "clash"), "reviewer@late": "late@live"}`. The docstring says this
    compares two libraries and does not reindex, and why.
  - `test_a_listed_agent_list_replaces_the_scan` (PLG-22, AGT-5, PLG-23, PLG-26):
    `set(health["plugins"]["listed-agents@live"]["notes"]) == {"agents entry 'agents/notes.txt' is
    not a .md file", "agents entry 'agents/gone.md' is not in the plugin"}`. The name list in the
    first test already shows `live_picked` served, and `live_stray` and `live_deep_picked` absent.
  - `test_deep_frontmatter_is_served_verbatim` (AGT-6, AGT-9):
    `(await definition(kb_url, "live_hooked", "live"))["_meta"][META]["frontmatter"] == HOOKED`.
  - `test_declared_servers_are_names` (PLG-27, AGT-9):
    - `live_wired`'s `["_meta"][META]["servers"] == ["alpha", "beta"]`, so the entry's `ignored`
      does not apply beside a `plugin.json`;
    - `live_filed`'s is `["gamma"]`.
  - `test_folders_name_prompts` (PLG-25, PRM-42):
    `{"live_db_migrate", "live_check"} <= set(await prompts(kb_url, "live"))`.
  - `test_qualified_names_become_addresses` (AGT-17, SKL-55, PRM-62):
    - `finder = await definition(kb_url, "live_finder", "live")`;
    - `finder["instructions"] == "Load skill://live/lookup/SKILL.md first, then run /names:lookup-cmd.\n"`;
    - `finder["_meta"][META]["skills"] == {"lookup": "skill://live/lookup/SKILL.md", "names:lookup": "skill://live/lookup/SKILL.md"}`;
    - `finder["_meta"][META]["frontmatter"]["skills"] == ["lookup", "names:lookup", "nowhere"]`;
    - `"Pairs with skill://live/helper/SKILL.md." in await read(kb_url, "skill://live/lookup/SKILL.md", "live")`;
    - `"Use skill://live/helper/SKILL.md." in await prompt_text(kb_url, "live_use", "live")`.

- [ ] **Step 2: Write the fixtures and the config lines.**

- [ ] **Step 3: Run the suite.**
  Run: `ruff check . && pytest`
  Expected: clean. Every new test is skipped, and `test_the_live_checks_skip_without_a_url`
  still passes.

- [ ] **Step 4: Run the live checks.** Restart kb with the recipe, so the new config is read.
  Run: `pytest -m live --kb-url http://127.0.0.1:8000 -v`
  Expected: all PASS. A failure is handled as Global Constraints says.

- [ ] **Step 5: Commit** `test: live checks for agent names, renames and definitions (#51)`

### Task 3: plugin.json parity

**Files:**
- Create the fixture plugins below. Append their entries to `marketplace.json` after `names`, in
  this order: `skills-add`, `undotted`, `commands-map`, `commands-list`, `commands-path`,
  `versioned`, `manifest-versioned`. None of them has an `agents/` folder, so Task 2's name list
  does not move.
- Create: `tests/live/test_live_plugins.py`.

A command file with description `d` and body `b` is `---\ndescription: d\n---\nb\n`. A skill file
is written as in Task 2.

| Case | Entry / manifest extras | Files |
|---|---|---|
| `skills-add` | manifest `skills: ["./extra"]` | `skills/added-base/SKILL.md`; `extra/added-extra/SKILL.md` |
| `undotted` | manifest `skills: ["more", "../outside"]` | `more/undotted-skill/SKILL.md` |
| `commands-map` | manifest `commands`, the map below | `tasks/deploy.md` (description "From the file.", body "Deploy now."); `commands/unlisted.md` |
| `commands-list` | manifest `commands: ["./cmds/listed.md", "./commands/"]` | `cmds/listed.md`; `cmds/unlisted-two.md`; `commands/kept.md` |
| `commands-path` | manifest `commands: "./more-commands/"` | `more-commands/ops/restart.md`; `commands/ignored.md` |
| `versioned` | **entry** `version: "2.0.0"`; manifest `version: "1.0.0"` | — |
| `manifest-versioned` | manifest `version: "1.5.0"` | — |

The `commands-map` map:

```json
{"deploy": {"source": "./tasks/deploy.md", "description": "Deploy the service."},
 "greet": {"content": "Say hello to $ARGUMENTS.\n", "description": "Greet someone."},
 "both": {"source": "./tasks/deploy.md", "content": "x"}}
```

**Interfaces:**
- Consumes: Task 1's `kb_url`, `health`, `prompts` and `read`.

- [ ] **Step 1: Write the tests** in `tests/live/test_live_plugins.py`, with
  `COMMANDS_NOTE = 'Default commands/ folder is ignored because the manifest sets "commands"'`.
  - `test_a_manifest_skills_list_adds` (PLG-20):
    - `health["plugins"]["skills-add@live"]["skills"] == 2`;
    - both `skill://live/added-base/SKILL.md` and `skill://live/extra/added-extra/SKILL.md` read,
      and each holds its own `name:`.
  - `test_a_path_without_dot_slash_is_served_and_noted` (PLG-24, PLG-16, PLG-26):
    - `skill://live/more/undotted-skill/SKILL.md` reads;
    - `set(health["plugins"]["undotted@live"]["notes"]) == {"skills path 'more' does not start with ./", "skills path '../outside' leaves the plugin root"}`.
  - `test_the_prompts_are_exactly_these` (PLG-21, PLG-23, PLG-25):
    `set(await prompts(kb_url, "live")) == {"live_check", "live_db_migrate", "live_deploy",
    "live_greet", "live_kept", "live_listed", "live_ops_restart", "live_use"}`. So `live_unlisted`,
    `live_unlisted-two`, `live_ignored` and `live_both` are not served.
  - `test_a_commands_map_names_and_describes` (PLG-21):
    - `prompts["live_deploy"] == "Deploy the service."` (the map's description wins over the
      file's);
    - `prompts["live_greet"] == "Greet someone."`;
    - `set(notes of commands-map@live) == {COMMANDS_NOTE, "commands entry 'both' needs exactly one of source and content"}`.
  - `test_a_key_naming_its_folder_earns_no_note` (PLG-23): `"notes" not in
    health["plugins"]["commands-list@live"]`, and `health["plugins"]["commands-path@live"]["notes"]
    == [COMMANDS_NOTE]`.
  - `test_version_precedence_as_kb_specifies` (PLG-17, LIB-13):
    `health["plugins"]["versioned@live"]["version"] == "2.0.0"` and
    `health["plugins"]["manifest-versioned@live"]["version"] == "1.5.0"`. A comment says this is
    kb's rule, and that whether Claude Code agrees is one of #35's follow-ups.

- [ ] **Step 2: Write the fixtures.**

- [ ] **Step 3: Run the suite.** Run: `ruff check . && pytest`. Expected: clean, with the new
  tests skipped.

- [ ] **Step 4: Run the live checks.** Restart kb, then run
  `pytest -m live --kb-url http://127.0.0.1:8000 -v`. Expected: all PASS, Task 2's
  `test_names_follow_library_order_and_folders` included.

- [ ] **Step 5: Commit** `test: live checks for plugin.json parity (#51)`

### Task 4: The live re-read, over a real WebDAV share

**Files:**
- Create: `tests/fixtures/live/dav/.claude-plugin/plugin.json` (`{"name": "dav-kit"}`) and
  `tests/fixtures/live/dav/agents/editable.md` (`editable`, "Edited live.", body
  "Original body.").
- Modify: `tests/fixtures/live/config.yaml`. Add:
  - the source `{name: dav, url: "webdav+http://127.0.0.1:8090", cache: live, auth: {username:
    dr-k, password: {env: LIVE_DAV_PASSWORD}}}`, with no `refresh`, and a comment saying so: an
    unrefreshed fetch is never rebuilt, so the snapshot's name stands for AGT-16;
  - the plugin `{name: dav-kit, source: "dav://kb"}`;
  - the library `{name: dav, plugins: [dav-kit]}`.
- Modify: `CONTRIBUTING.md`, the "Live checks" block. Before `mcp-kb` starts, add:

```bash
cp -r tests/fixtures/live/dav "$LIVE/dav"
python -m tests.webdav_server --root "$LIVE/dav" --port 8090 &
```

  Prefix the `mcp-kb` line with `LIVE_DAV_PASSWORD=s3cret-app-password` (the test server's
  password, not a secret), and add `--kb-dav-dir="$LIVE/dav"` to the `pytest` line.
- Create: `tests/live/test_live_reread.py`.

**Interfaces:**
- Consumes: Task 1's `kb_url`, `dav_dir`, `health`, `definition` and `agent_names`, and
  `tests/webdav_server.py`'s `serve`/`main` and `PASSWORD`.

- [ ] **Step 1: Write the tests.** The module has a helper
  `async _edit(path: Path, text: str) -> None`:
  - assert `len(text.encode()) != path.stat().st_size`;
  - write the file;
  - `await asyncio.sleep(live.TTL_SECONDS + 0.5)`, with `live` imported from
    `kubed.mcp_kb.sources`.

  `test_a_live_agent_is_reread` (AGT-16) takes `kb_url` and `dav_dir`, sets
  `path = dav_dir / "agents/editable.md"` and `original = path.read_text()`, and in a
  `try`/`finally` that ends with `await _edit(path, original)`:
  - `(await definition(kb_url, "dav_editable", "dav"))["instructions"] == "Original body.\n"`;
  - after an edit to the body "The edited body, which is longer.", the instructions read
    `"The edited body, which is longer.\n"`;
  - after an edit to `"---\nname: [unclosed\n---\nHalf saved.\n"`, the instructions read
    `"Original body.\n"`, the copy the snapshot parsed;
  - after an edit to frontmatter `name: renamed-on-disk` with the body "Renamed on disk.",
    `definition(…, "dav_editable", "dav")` answers with `agent == "dav_editable"` and the
    instructions `"Renamed on disk.\n"`, and `await agent_names(kb_url, "dav") ==
    ["dav_editable"]`.

  `test_health_names_no_dav_url_or_credential` takes `kb_url` and `dav_dir`, the latter only so
  that it skips where `dav` is not configured. With `text = json.dumps(health(kb_url))`:
  - `PASSWORD not in text`, `"127.0.0.1:8090" not in text` and `"webdav+" not in text`;
  - `health(kb_url)["fetches"]` has an entry with `"live": true`.

- [ ] **Step 2: Write the fixture, the config lines and the CONTRIBUTING lines.**

- [ ] **Step 3: Run the suite.** Run: `ruff check . && pytest`. Expected: clean, with the new
  tests skipped.

- [ ] **Step 4: Run the whole live recipe**, with the WebDAV server and `--kb-dav-dir`.
  Run: `pytest -m live --kb-url http://127.0.0.1:8000 --kb-dav-dir="$LIVE/dav" -v`
  Expected:
  - every live test PASSes (or is a strict xfail, under Global Constraints);
  - kb's stderr has one warning naming `dav_editable` for the broken edit.

  Paste the pytest summary, and that warning line with its timestamp, into the PR description.
  Then run it once more without `--kb-dav-dir`. Expected: only the two tests in this module skip.

- [ ] **Step 5: Commit** `test: a live check of the AGT-16 re-read over WebDAV (#51)`

---

## Handoff (Dr K, after the fixtures are pushed)

These steps are not the code agent's. They need a deployment, and a Claude Code with the mod.
Post their results on #51 as one comment. The comment records the fixture commit `<sha>` and the
image `kubed/mcp-kb:<sha>`, and holds no credential, no internal hostname and no token.

1. **The deployment.** Deploy the branch image `:<sha>`. Add the libraries `live`, `live-other`, `clash` and `clash-appended` from
   `tests/fixtures/live/config.yaml` to its config, pinned to `<sha>` (CONTRIBUTING.md, "Live
   checks"). Run `pytest -m live --kb-url <its URL>`. AGT-16 skips unless the deployment has a
   WebDAV source with a folder you can edit.
2. **The client half.**
   - Run headless `claude -p`:
     - with the mod loaded through `--plugin-dir`;
     - enabled as `<name>@inline` through `--settings`, with its options in `pluginConfigs`;
     - with `--output-format stream-json --verbose --debug`.
   - Delegate a task to a registered `kb-agents:<agent>`, then read the subagent's calls back
     from the transcript.
   - At the least, check that:
     - the clash rename reaches the client as `clash_reviewer@second` (AGT-8);
     - an edit in the share shows on the next `agents/get` (AGT-16);
     - drawio's `diagrammer` reaches `skill://drawio/drawio/SKILL.md` with no `Unknown skill`
       call (#50);
     - `live_hooked`'s fixture hook (`echo never-run`) did not run, if the mod registers it.
