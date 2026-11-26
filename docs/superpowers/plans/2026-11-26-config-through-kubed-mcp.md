# Config Through kubed-mcp 0.5: One Composed Config, an Env Var and a Flag for Every Item — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use skill://superpowers/subagent-driven-development/SKILL.md (recommended) or skill://superpowers/executing-plans/SKILL.md to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** kb loads one composed config through kubed-mcp 0.5's public loader, and every item can be
set in the file, from an env var or with a flag. The snapshots hold, except for the changes named
under "Changelog".

**Architecture:** `config.py` registers three sections: kb's `Config` as the root (`@config()`),
`Serving` (kb's defaults over kubed-mcp's `serving`) and `Telemetry` (kubed-mcp's `telemetry` plus
kb's credential guard). `delivery` stays kubed-mcp's built-in. `main.py` loads them once with
`kubed.mcp.load_config(...)` and hands the `LoadedConfig` to `create_app`, which builds
`QuickMCP(SERVER_NAME, loaded=…)`. kb's argparse goes, apart from the `serve`/`schema` word and
`--help`. Because the pin moves past 0.4.2 (quick-mcp#45), kb's view now re-reads a live plugin
before it pins, so a live edit is served by the request that found it.

**Tech Stack:** Python ≥3.11, pydantic 2, `kubed-mcp>=0.5.0,<0.6` (FastMCP through it), pytest +
pytest-asyncio.

**Spec:** this file's Design section is the record. It replaces the draft spec in #103's notes, and
there is no separate design doc. What ships rewrites kb's CFG-1, CFG-2, CFG-3, CFG-4, CFG-7, CFG-8,
CFG-15, SRC-21, SRC-36, SKL-37, SKL-39, AGT-16, PRM-58, HTTP-6, HTTP-34 and HTTP-39 in place, and
adds CFG-16 to CFG-20 (Task 2). The brief is #103's notes and Dr K's rulings (2026-11-25, 2026-11-26
15:53, 20:23 and 20:52). **IDs:** kb's CFG-n and quick-mcp's CFG-n are separate series. This file
writes quick-mcp's as `quick-mcp CFG-n`.

## Design

### Upstream, read at the `v0.5.0` tag

- `kubed.mcp` exports `Config`, `Field`, `config`, `config_schema`, `load_config`, `LoadedConfig`,
  `ServingSettings`, `TelemetrySettings`, `DeliverySettings`, `NoDecode` and `Source`. None of them
  loads FastMCP.
- `load_config(*, sections=(), components=(), argv=None, environ=None, config=None, hooks=None)`.
  - `argv=None` reads **no** flags: kubed-mcp never reads `sys.argv`. `environ=None` reads
    `os.environ`.
  - `config=` takes a mapping, a section instance or an iterable of them, and then reads no file,
    env var or flag (source `code`). A root instance is spread into its fields and validated again.
  - Precedence is default < file < env < arg. Mappings merge key by key, and anything else (a list
    included) replaces what is below it whole. A blank value counts as unset.
  - **The file is read only when it is named**, by `--config-file`, else `CONFIG_FILE`. There is no
    default path. A named file that is missing, not a file, not YAML or not a mapping stops the load
    with `  config file <path> <trouble>`, which never quotes the text.
  - A list, dict or model item reads JSON from its env var or flag.
  - Errors: one `ValueError`, `the config did not load:` followed by one `  <path> (<source>):
    <msg>` line per error, all collected together. An unknown flag is `  the arguments (arg
    --flag): no item takes this flag`, and a positional is counted and never quoted. No input is
    ever echoed, a path stops at a sensitive field, and a server validator's message is kept as
    written (pydantic's `Value error, ` prefix included).
- `QuickMCP(name, *, loaded=…, header_prefix=…, **fastmcp_options)`.
  - `loaded=` together with `sections`, `components`, `hooks`, `config`, `argv` or `environ` is a
    `TypeError`.
  - One `LoadedConfig` builds one server: a second `QuickMCP(loaded=…)` with it is a `TypeError`.
  - `lifespan`, `version`, `cache_ttl` and `cache_scope` still pass through to FastMCP.
  - The boot line (`config: <path>=<json> (<source>), …`, or `config: all defaults`) is logged on
    `kubed.mcp.config` when the lifespan is entered. It names every leaf not at its default and
    shows a secret as `***`. Models are dumped by attribute name.
- `run(**http_options)` serves as `serving` says and takes `uvicorn_config`. `transport`, `host`,
  `port` or `log_level` passed to it is a `TypeError`. It sets `serving.log_level` on the root
  logger, and adds `basicConfig()`'s handler only when the root has none.
- Section rules (quick-mcp CFG-4 to CFG-10):
  - every model reached needs `extra="forbid"`;
  - a root field named like a built-in key (`serving`, `telemetry`, `delivery`) is a `ValueError`,
    and so is a root attribute of that name;
  - a subclass that redefines a field must restate its `env` and `arg`;
  - `Field(description=…)` is a `TypeError`, and only `kubed.mcp.Field` takes `doc=`, `env=` and
    `arg=`;
  - a nested model reached through a list may carry no `env` or `arg`, and kb's carry none;
  - `CONFIG_FILE` and `--config-file` are reserved.
- `ServingSettings`:
  - `transport` (`stdio`, `http`, `sse` or `streamable-http`, default `stdio`), env `TRANSPORT`;
  - `host` (`127.0.0.1`), env `HOST`;
  - `port` (`8000`), env `PORT`;
  - `log_level` (`INFO`, read case-insensitively), env `LOG_LEVEL`;
  - each flag is its env name, lower-cased and dashed, after `--`.
- `TelemetrySettings`: `profiles: SecretStr | None` (`TELEMETRY_PROFILES`,
  `--telemetry-profiles`), `profile_cpu`, `profile_memory`, `otel` and `tags`, all under
  `TELEMETRY_*` and `--telemetry-*`. `DeliverySettings`: `resources`, `listed` and `via`, under
  `DELIVERY_*` and `--delivery-*`.
- `config_schema(*sections)` composes the built-ins first. Every built-in therefore appears without
  being named, `delivery` included. A sensitive field is marked `"sensitive": true` and has no
  default.
- kb jumps from 0.3 to 0.5, so it takes 0.4.0's breaking changes too, and these are the ones that
  reach kb:
  - `QuickMCP(config=)` takes values;
  - `run()` takes no serving settings;
  - `TelemetrySettings.profiles` is a `SecretStr`;
  - the boot line logs at serving start.

  It also takes 0.4.1 (`skills/get` and `resources/directory/read` resolve `.` and `..`), 0.4.2
  (quick-mcp#45: "the view runs first, so a set it serves is what the request reads"), 0.4.3 and
  0.4.4.

### Decided

| # | Decision | Why |
|---|---|---|
| D1 | `SECTIONS = (Config, Serving, Telemetry)` in `config.py`. `Config` stays kb's `Strict` model, marked `@config()`. It does not subclass `kubed.mcp.Config`: a section may be any model that forbids unknown keys. `Serving` and `Telemetry` are named for their keys, which is how they read in the wiki | One composed config (Dr K, 2026-11-25). The draft's `KbServing` and `KbTelemetry` would put `Kb` into every wiki heading and schema `$def` |
| D2 | The root's `telemetry` field and `_telemetry_carries_no_credential` go. `Telemetry(TelemetrySettings)` gains a `field_validator("profiles")` that refuses userinfo with `CREDENTIAL_REFUSAL`, unparseable-with-`@` included, reading `get_secret_value()` | A root field named `telemetry` is refused. A field validator's error path is `telemetry.profiles`, and kubed-mcp stops the path there without the value (kb's own validators stay: Dr K) |
| D3 | `sources`, `plugins` and `libraries` are `kubed.mcp.Field(default_factory=list, doc=, env=, arg=)`, with env `KB_SOURCES`, `KB_PLUGINS` and `KB_LIBRARIES` and flags `--sources`, `--plugins` and `--libraries`, each read as JSON | Dr K, 2026-11-26 20:52. A bare `SOURCES` could clash with other software in the container. Each name is literal (quick-mcp CFG-7) |
| D4 | `Config.cache_dir: Path`, default `/var/cache/mcp-kb`, env `CACHE_DIR`, flag `--cache-dir`. `KnowledgeBase(config, cache_dir)` keeps its signature, and `main` passes `loaded.config.cache_dir` | Every item in one config. It can now be set in the file too (a named change) |
| D5 | `Serving(ServingSettings)`, `@config("serving")`, redefines `transport: Literal["stdio", "http"]` (default `http`) and `host` (default `0.0.0.0`), each restating `env` and `arg`. `port` and `log_level` are inherited | Epic answer 3, unchanged by 0.5.0. Narrowing `transport` to `stdio` and `http` is kb's own (Dr K, 20:52): `sse` and `streamable-http` are a config error |
| D6 | `config.load(argv, environ=None) -> LoadedConfig` is `kubed.mcp.load_config(sections=SECTIONS, argv=list(argv), environ=environ)`, its `ValueError` re-raised as `ConfigError(scrub(str(exc)))` with no cause chained. kb's own `load_config(path)` is deleted. `config.schema()` is `config_schema(*SECTIONS)` | The public loader alone (Dr K, 20:23). `scrub` is a belt for one of kb's own messages that quotes an address. `ConfigError` keeps exit 2 a single `except` |
| D7 | `main(argv=None)`: argv is `sys.argv[1:]`. `-h` or `--help` before any `--` prints `help_text()` and returns. A first token of `serve` or `schema` is the command, and anything else serves with every token passed on (`split_command`). `schema` prints the composed schema and reads nothing. Serving runs the D13 guard, then `load(rest)` (a `ConfigError` exits 2), then `configure_logging(serving.log_level)`, then `KnowledgeBase(...)` (an `AccessRefused` exits 3), then `create_app(kb, loaded=loaded).run(uvicorn_config={"log_config": None})` | argparse's optional positional would take `9000` in `mcp-kb --port 9000` as the command, and kubed-mcp counts positionals as errors. The help keeps `mcp-kb --help` working, built from the schema as selenium-flow#218 builds its own |
| D8 | `create_app(knowledge_base, *, loaded: LoadedConfig \| None = None)`. With `None` it loads `load_config(sections=SECTIONS, config=knowledge_base.config)`. A `loaded` whose `.config` is not `knowledge_base.config` raises `ValueError`. `QuickMCP` gets `loaded=` and no `config=` or `sections=` | One load builds one server, so every test app needs a load of its own. Loading from the knowledge base's config keeps the ~500 test call sites (`server_of`, `KnowledgeBase(make_config(…))`) as they are. The guard stops `main` serving one config while kb harvests another |
| D9 | `config_hash` reads `model_dump(mode="json", include={"sources", "plugins", "libraries"})` | `serving`, `cache_dir`, `telemetry` and `delivery` change nothing served. The dump is the same bytes as `exclude={"telemetry"}` gave, so every `index.json` on a volume is reused (SRC-36, SRC-40) |
| D10 | No default config path in kb. The image sets `CONFIG_FILE=/etc/mcp-kb/config.yaml`. Outside the image, no file is read unless one is named, and the boot line then says what was loaded | kubed-mcp reads a file only when it is named (quick-mcp CFG-3). Filling in a default `CONFIG_FILE` would make "no file" impossible to ask for, since a blank value counts as unset. **For Dr K:** say so if `mcp-kb` with nothing set should still read `/etc/mcp-kb/config.yaml` |
| D11 | `SkillServing.view()` runs `_reread_live(scope)` first, then reads `self._published` and pins that. SKL-37 and N6 are reworded so the request that re-reads serves the edit | Epic answer 2. Since 0.4.2 kubed-mcp takes its state after the view. With kb's pin still taken before the re-read, kubed-mcp would build the new set while kb's rewriter read the old one |
| D12 | No `hide_input_in_errors` on kb's models | The draft's belt has nothing to hold: kubed-mcp's loader never echoes input, and nothing else in `kubed/` validates a kb model |
| D13 | `mcp-kb serve` with a non-blank `CONFIG` in the environment exits 2 with `mcp-kb: CONFIG is no longer read: name the config file with CONFIG_FILE`. This is the one read of `os.environ` in `main.py` | Without the guard, an image whose deployment still sets `CONFIG=/config/kb.yaml` would serve the image's own example config through its `CONFIG_FILE`, with nothing to say so. That is a config that serves the wrong thing, silently. `--config` is an unknown flag and already exits 2. **For Dr K:** a guard you did not ask for. Say if it should go |

**Checked, and needs nothing:**
- `catalogue/uris.parse` resolving dots that kubed-mcp has already resolved is idempotent. Task 1
  pins it with a `skills/get` test.
- `docker-compose.yaml` names no `CONFIG` and mounts the file where the image's `CONFIG_FILE`
  points.
- `examples/config.yaml` validates as the root alone.
- The composed model subclasses kb's `Config`, so `config.sources`, `secrets()`,
  `min_refresh_seconds` and `source()` work unchanged, and `KnowledgeBase.config` stays typed
  `Config`.
- kb injects no `Config` (`Inject[...]`), so 0.4.0's injection change does not reach it.

**The boot line** lists `sources`, `plugins` and `libraries` whole, so with `examples/config.yaml`
it is one long line. It is accepted. A source URL with userinfo is refused at load, and `auth` holds
`{env: NAME}` references, so only the names print. Task 1 pins that the value never does.

### Changelog (`[Unreleased]`, one short line each)

- `### Changed`: `- **BREAKING:** \`CONFIG_FILE\` and \`--config-file\` name the config file, in
  place of \`CONFIG\` and \`--config\`; a leftover \`CONFIG\` stops the boot, and outside the
  image no file is read unless one is named.`
- `### Added`: `- Set any config item from an env var or a flag: \`KB_SOURCES\`, \`KB_PLUGINS\`,
  \`KB_LIBRARIES\` (JSON), \`CACHE_DIR\`, \`TRANSPORT\`, \`HOST\`, \`PORT\`, \`LOG_LEVEL\`,
  \`TELEMETRY_*\` and \`DELIVERY_*\`.`
- `### Added`: `- The config file can set \`cache_dir\`, \`serving\` and \`delivery\` too.`
- `### Changed`: `- A \`cache: live\` edit is served by the request that finds it, not the next one.`
- `### Changed`: `- \`mcp-kb schema\` prints the whole config's schema, with each item's env var and
  flag.`

## Global Constraints

- **Toolchain** (CI's `test.yml`):
  - `pip install -e ".[test]"`, then `ruff check .` and `pytest` from the repository root;
  - `git submodule update --init`, so `tests/test_wiki.py` runs rather than skips;
  - `python scripts/generate_wiki.py --check` and `mcp-kb schema` must agree with what is
    committed.
- **The pin** is `"kubed-mcp>=0.5.0,<0.6"` in `pyproject.toml`. Its comment says the range takes
  0.5's patches and stops short of 0.6. selenium-flow#218's 0.4.1 floor is not copied.
- **The facade only.** `kubed/` imports these names from `kubed.mcp` and nowhere else:
  - `Field`, `config`, `config_schema`, `load_config`, `LoadedConfig`, `ServingSettings` and
    `TelemetrySettings`;
  - never `kubed.mcp._config`, `kubed.mcp._builtins` or `fastmcp`.

  In `config.py`, kubed-mcp's `Field` is imported as `Item`, because pydantic's `Field` stays for
  the nested models.
- **`catalogue/` and `plugins/` import no FastMCP**, and both import `config.py`
  (`tests/test_boundaries.py`).
- **The names, verbatim:**

  | Item | Env | Flag | Default |
  |---|---|---|---|
  | the file | `CONFIG_FILE` | `--config-file` | none (the image: `/etc/mcp-kb/config.yaml`) |
  | `sources` | `KB_SOURCES` | `--sources` | `[]` |
  | `plugins` | `KB_PLUGINS` | `--plugins` | `[]` |
  | `libraries` | `KB_LIBRARIES` | `--libraries` | `[]` |
  | `cache_dir` | `CACHE_DIR` | `--cache-dir` | `/var/cache/mcp-kb` |
  | `serving.transport` | `TRANSPORT` | `--transport` | `http` (`stdio` or `http`) |
  | `serving.host` | `HOST` | `--host` | `0.0.0.0` |
  | `serving.port` | `PORT` | `--port` | `8000` |
  | `serving.log_level` | `LOG_LEVEL` | `--log-level` | `INFO` |
  | `telemetry.*` | kubed-mcp's `TELEMETRY_*` | `--telemetry-*` | kubed-mcp's |
  | `delivery.*` | kubed-mcp's `DELIVERY_*` | `--delivery-*` | none |
- **Python 3.11 is the floor.** Every module starts `from __future__ import annotations`, and lines
  are at most 88 columns.
- **Tests pass `environ=`.** A test that loads uses `environ={}` or an explicit mapping, never the
  runner's environment, except a test of `main` itself.
- **Public repo:** examples use `example.com`, and the maintainer is Dr K.
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Upgrading costs no refetch.** A config's hash is the bytes it was before, and setting
   `serving`, `cache_dir`, `telemetry` or `delivery` leaves it there. → Task 1,
   `test_config_hash_reads_the_three_lists_alone`.
2. **`mcp-kb --port 9000` serves on 9000.** A flag with no command in front of it is not taken for
   the command. → Task 1, `test_split_command`.
3. **`KB_SOURCES` replaces the file's `sources` whole,** never merged by index, and a source in it
   with a login is refused without the login echoed. → Task 1,
   `test_kb_sources_replaces_the_files_list_whole` and
   `test_a_login_in_kb_sources_is_refused_unechoed`.
4. **The boot line never prints a credential.** With `auth.password: {env: KB_TEST_TOKEN}` set in
   the environment, the line names `KB_TEST_TOKEN` and never its value. → Task 1,
   `test_the_boot_line_names_a_reference_never_its_value`.
5. **A deployment still setting `CONFIG` is stopped,** not served the image's example config. →
   Task 1, `test_a_leftover_config_variable_exits_2`.

---

### Task 1: One composed config, loaded once and served from the load

The config, the entry point, the app and the live view land together. Bumping the pin breaks
`create_app`'s `QuickMCP(config=…)` and `run(args)`, and it moves the live timing. Deleting kb's
`load_config` breaks `main.py`, which `tests/test_schema.py` and `tests/test_wiki.py` import. No
smaller step leaves the suite green.

**Files:**
- Modify: `pyproject.toml:28-33`, the pin and its comment.
- Modify: `kubed/mcp_kb/config.py`:
  - imports;
  - the module docstring (one composed config, the sections and the names table);
  - `Config`;
  - new `Serving`, `Telemetry`, `SECTIONS` and `load`;
  - delete `load_config`;
  - `schema()`.
- Modify: `kubed/mcp_kb/catalogue/index.py:140-149`, `config_hash` and its docstring.
- Modify: `kubed/mcp_kb/main.py`:
  - the module docstring;
  - drop `build_parser`, `DEFAULT_CONFIG`, `DEFAULT_CACHE_DIR` and `LOG_LEVELS`;
  - add `COMMANDS`, `named_items`, `split_command` and `help_text`;
  - `main`, as D7 and D13 say.
- Modify: `kubed/mcp_kb/app.py:33-50`: `create_app`'s signature and the `QuickMCP(...)` call (D8).
- Modify: `kubed/mcp_kb/mcp/skills.py`:
  - `view()` (D11);
  - the docstrings of `view` and `_reread_live`;
  - the module docstring's D9 paragraph (lines 73-79);
  - the comment at line 1351.
- Modify: `Dockerfile:112-116`: `ENV CONFIG_FILE=/etc/mcp-kb/config.yaml \` in place of `CONFIG=`.
  The other four are kept as they are.
- Modify: `scripts/generate_wiki.py`:
  - `MODELS` becomes `["Config", "SourceConfig", "PluginConfig", "LibraryConfig", "Selector",
    "BasicAuth", "EnvRef", "Serving", "Telemetry", "DeliverySettings"]`; the `missing` check names
    any other `$defs`;
  - `fields()` adds `Env` and `Flag` columns, after `Default`, to a model whose properties carry
    any `env` or `arg`;
  - the `Config` section's description falls back to `clean(Config.__doc__)` when the composed
    root has none;
  - the intro's first paragraph reads: "Every item below can be set in the config file, from its
    environment variable or with its flag; a flag beats the variable, which beats the file, which
    beats the default. A key this page does not list is an error rather than a value quietly
    ignored, because a config that serves nothing is the worst failure a config file has."
- Modify (submodule `wiki/`): `Deployment.md:19-21` and `:167`. The env table has a row for
  `CONFIG_FILE` and one for every name `named_items(schema())` returns, each with its flag and
  default. The example at line 167 is `CONFIG_FILE=./config.yaml CACHE_DIR=./.cache
  TRANSPORT=stdio mcp-kb`.
- Regenerate: `config.schema.json` (`mcp-kb schema > config.schema.json`) and
  `wiki/Configuration.md` (`python scripts/generate_wiki.py`).
- Test: `tests/test_config.py`, `tests/test_index.py`, `tests/test_schema.py`, `tests/test_app.py`,
  `tests/test_wiki.py:153-161`, `tests/test_packaging.py:410-419`, `tests/test_webdav_source.py:598`,
  `tests/test_live.py`, `tests/test_skills_extension.py`, `tests/test_boundaries.py`.

**Interfaces:**
- Produces, in `kubed/mcp_kb/config.py`:
  - `@config() class Config(Strict)`:
    - `sources: list[SourceConfig] = Item(default_factory=list, doc=…, env="KB_SOURCES",
      arg="--sources")`, and the same shape for `plugins` (`KB_PLUGINS`, `--plugins`) and
      `libraries` (`KB_LIBRARIES`, `--libraries`);
    - `cache_dir: Path = Item(Path("/var/cache/mcp-kb"), doc=…, env="CACHE_DIR",
      arg="--cache-dir")`;
    - every other validator and method as today, less `telemetry`.
  - `@config("serving") class Serving(ServingSettings)`:
    - `transport: Literal["stdio", "http"] = Item("http", doc=…, env="TRANSPORT",
      arg="--transport")`;
    - `host: str = Item("0.0.0.0", doc=…, env="HOST", arg="--host")`.
  - `@config("telemetry") class Telemetry(TelemetrySettings)` with
    `_profiles_carry_no_credential(cls, profiles: SecretStr | None) -> SecretStr | None`, a
    `field_validator("profiles")`.
  - `SECTIONS: tuple[type[BaseModel], ...] = (Config, Serving, Telemetry)`.
  - `load(argv: Sequence[str], environ: Mapping[str, str] | None = None) -> LoadedConfig` (D6).
  - `schema() -> dict`, which is `config_schema(*SECTIONS)`.
- Produces, in `kubed/mcp_kb/catalogue/index.py`: `config_hash(config: Config) -> str`, with the
  same signature, over `include={"sources", "plugins", "libraries"}`.
- Produces, in `kubed/mcp_kb/main.py`:
  - `COMMANDS = ("serve", "schema")`.
  - `named_items(published: dict) -> list[tuple[str, str, str]]`: `(arg, env, description)` for
    each property that has an `arg`, in schema order. That is the root's properties first, then the
    properties of each section the root's properties `$ref` into `$defs`, one level down.
  - `split_command(argv: Sequence[str]) -> tuple[str, list[str]]`: the first token when it is in
    `COMMANDS`, and the rest; else `("serve", list(argv))`.
  - `help_text() -> str`:
    - the first line is `usage: mcp-kb [serve|schema] [--config-file PATH] [--<item> VALUE ...]`;
    - then a line `  --config-file PATH  (env CONFIG_FILE)  The YAML config file; none is read
      unless named.`;
    - then one line per `named_items(schema())`, as `  {arg}  (env {env})  {description}`.
  - `main(argv: list[str] | None = None) -> None`.
- Produces, in `kubed/mcp_kb/app.py`: `create_app(knowledge_base: KnowledgeBase, *, loaded:
  LoadedConfig | None = None) -> QuickMCP`.

- [ ] **Step 1: Pin and install.** Set the pin, then run `pip install -e ".[test]"`.
  `python -c "import kubed.mcp as m; print(m.load_config, m.LoadedConfig)"` must print both.

- [ ] **Step 2: Write the config tests.** Move `tests/test_config.py` onto the loader first:
  - its import of `load_config` becomes `load, SECTIONS, CREDENTIAL_REFUSAL`;
  - add a module-level helper, `def load_file(path: Path) -> Config: return
    load(["--config-file", str(path)], environ={}).config`, and rename every `load_config(` call
    to `load_file(`;
  - a test whose `match=` named kb's old wording (`is not YAML`, `cannot read`) matches kubed-mcp's:
    `is not valid YAML` and `does not exist`;
  - the telemetry tests read `profiles.get_secret_value()`.

  Then add:

```python
def test_an_env_var_sets_each_kind_of_item(tmp_path):
    environ = {
        "KB_SOURCES": json.dumps([{"name": "local", "url": "file:///srv"}]),
        "CACHE_DIR": str(tmp_path / "c"),
        "PORT": "9001",
        "TELEMETRY_PROFILE_CPU": "false",
        "DELIVERY_VIA": "local",
    }
    config = load([], environ=environ).config
    assert [s.name for s in config.sources] == ["local"]
    assert config.cache_dir == tmp_path / "c"
    assert (config.serving.port, config.serving.transport) == (9001, "http")
    assert config.serving.host == "0.0.0.0"
    assert config.telemetry.profile_cpu is False
    assert config.delivery.via == "local"


def test_a_flag_beats_its_env_var_and_the_file(tmp_path):
    path = write(tmp_path, "serving:\n  port: 7000\n")
    loaded = load(["--config-file", str(path), "--port", "9002"], environ={"PORT": "9001"})
    assert loaded.config.serving.port == 9002
    assert str(loaded.sources["serving.port"]) == "arg --port"


def test_kb_sources_replaces_the_files_list_whole(tmp_path):
    path = write(tmp_path, "sources:\n- name: a\n  url: file:///a\n- name: b\n  url: file:///b\n")
    env = {"KB_SOURCES": json.dumps([{"name": "c", "url": "file:///c"}])}
    loaded = load(["--config-file", str(path)], environ=env)
    assert [s.name for s in loaded.config.sources] == ["c"]


def test_a_login_in_kb_sources_is_refused_unechoed():
    env = {"KB_SOURCES": json.dumps([{"name": "g", "url": "git+https://me:s3cret@example.com"}])}
    with pytest.raises(ConfigError) as raised:
        load([], environ=env)
    assert "must not embed a credential" in str(raised.value)
    assert "s3cret" not in str(raised.value) and "me:" not in str(raised.value)


@pytest.mark.parametrize(
    "address",
    ["http://me:s3cret@pyroscope.example.com:4040", "http://me:s3cret@[pyroscope.example.com"],
)
def test_a_login_in_telemetry_profiles_is_refused_unechoed(address):
    with pytest.raises(ConfigError) as raised:
        load([], environ={"TELEMETRY_PROFILES": address})
    assert CREDENTIAL_REFUSAL in str(raised.value)
    assert "s3cret" not in str(raised.value)


def test_config_file_names_the_file_and_config_is_not_read(tmp_path):
    path = write(tmp_path, "sources:\n- name: local\n  url: file:///srv\n")
    assert load([], environ={"CONFIG": str(path)}).config.sources == []
    named = load([], environ={"CONFIG_FILE": str(path)}).config
    assert [s.name for s in named.sources] == ["local"]
    with pytest.raises(ConfigError, match=r"arg --config\)"):
        load(["--config", str(path)], environ={})


def test_a_missing_named_file_is_refused_by_its_path():
    with pytest.raises(ConfigError, match="config file /nope does not exist"):
        load(["--config-file", "/nope"], environ={})


@pytest.mark.parametrize("transport", ["sse", "streamable-http"])
def test_kb_serves_stdio_or_http_alone(transport):
    with pytest.raises(ConfigError, match="serving.transport"):
        load(["--transport", transport], environ={})


def test_log_level_reads_case_insensitively_and_a_flag_beats_it():
    assert load([], environ={"LOG_LEVEL": "debug"}).config.serving.log_level == "DEBUG"
    flagged = load(["--log-level", "error"], environ={"LOG_LEVEL": "debug"})
    assert flagged.config.serving.log_level == "ERROR"
    assert load([], environ={}).config.serving.log_level == "INFO"


def test_the_schema_is_the_composed_one():
    published = schema()
    assert published == config_schema(*SECTIONS)
    props = published["properties"]
    assert {"sources", "plugins", "libraries", "cache_dir", "serving", "telemetry", "delivery"} <= set(props)
    assert (props["sources"]["env"], props["sources"]["arg"]) == ("KB_SOURCES", "--sources")
    assert (props["cache_dir"]["env"], props["cache_dir"]["arg"]) == ("CACHE_DIR", "--cache-dir")
    serving = published["$defs"]["Serving"]["properties"]
    assert serving["transport"]["enum"] == ["stdio", "http"]
    assert (serving["transport"]["default"], serving["host"]["default"]) == ("http", "0.0.0.0")
    profiles = published["$defs"]["Telemetry"]["properties"]["profiles"]
    assert profiles["sensitive"] is True and "default" not in profiles
```

  `config_schema` is imported from `kubed.mcp` in the test. If `transport`'s enum sits under an
  `anyOf` or a `$ref`, assert it where the schema puts it. The values are fixed.

  `tests/test_index.py` (with `hashlib`, `json`, `load_config` from `kubed.mcp` and
  `make_config`):

```python
@pytest.mark.unit
def test_config_hash_reads_the_three_lists_alone(skills_dir):
    empty = load([], environ={}).config
    before = json.dumps({"libraries": [], "plugins": [], "sources": []}, sort_keys=True)
    assert config_hash(empty) == hashlib.sha256(before.encode()).hexdigest()
    busy = load([], environ={
        "PORT": "9001", "CACHE_DIR": "/tmp/elsewhere",
        "TELEMETRY_PROFILE_CPU": "false", "DELIVERY_VIA": "local",
    }).config
    assert config_hash(busy) == config_hash(empty)
    root = make_config(skills_dir)
    composed = load_config(sections=SECTIONS, config=root).config
    assert config_hash(composed) == config_hash(root)
```

  `tests/test_boundaries.py`: the existing `test_the_config_imports_no_fastmcp` stays and must pass.
  `kubed.mcp_kb.config` now imports `load_config` and `config_schema`, which are the names that
  could pull FastMCP in.

- [ ] **Step 3: Write the entry-point and app tests.**

  `tests/test_schema.py`:
  - drop `build_parser` from its imports and add `split_command`;
  - `test_serve_is_the_default_command` and the log-level test go (Step 2 covers the log level);
  - the two `--config` tests pass `--config-file`;
  - add:

```python
def test_split_command():
    assert split_command([]) == ("serve", [])
    assert split_command(["schema"]) == ("schema", [])
    assert split_command(["serve", "--port", "9000"]) == ("serve", ["--port", "9000"])
    assert split_command(["--port", "9000"]) == ("serve", ["--port", "9000"])


def test_schema_reads_no_config(monkeypatch, capsys):
    monkeypatch.setenv("CONFIG_FILE", "/nope")
    main(["schema", "--port", "not-a-port"])
    assert json.loads(capsys.readouterr().out) == schema()


def test_help_names_every_item_and_exits_0(capsys):
    main(["--help"])
    out = capsys.readouterr().out
    assert out.startswith("usage: mcp-kb")
    for flag, env in [("--config-file", "CONFIG_FILE"), ("--sources", "KB_SOURCES"),
                      ("--cache-dir", "CACHE_DIR"), ("--port", "PORT"),
                      ("--telemetry-profiles", "TELEMETRY_PROFILES"),
                      ("--delivery-via", "DELIVERY_VIA")]:
        assert flag in out and env in out


def test_an_unknown_flag_or_a_positional_exits_2(monkeypatch, capsys):
    monkeypatch.delenv("CONFIG", raising=False)
    for argv in (["serve", "--config", "x.yaml"], ["serve", "extra"]):
        with pytest.raises(SystemExit) as raised:
            main(argv)
        assert raised.value.code == 2
        assert "mcp-kb: the config did not load" in capsys.readouterr().err


def test_a_leftover_config_variable_exits_2(tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.yaml"
    path.write_text("")
    monkeypatch.setenv("CONFIG", str(path))
    with pytest.raises(SystemExit) as raised:
        main(["serve", "--config-file", str(path)])
    assert raised.value.code == 2
    assert "CONFIG is no longer read" in capsys.readouterr().err
```

  `tests/test_app.py`. Imports: `load`, `SECTIONS` and `Telemetry` from `kubed.mcp_kb.config`,
  and `load_config` from `kubed.mcp`.
  - `test_the_telemetry_section_reaches_the_server` builds its app as
    `loaded = load_config(sections=SECTIONS, config=[make_config(skills_dir),
    Telemetry(profiles="http://pyroscope.example.com:4040")])`, then
    `create_app(KnowledgeBase(loaded.config, tmp_path / "cache"), loaded=loaded)`.
  - Add the two tests below. The second declares a source and no plugin, so nothing is fetched.

```python
def test_a_load_of_another_config_is_refused(skills_dir, tmp_path):
    knowledge_base = KnowledgeBase(make_config(skills_dir), tmp_path / "cache")
    with pytest.raises(ValueError, match="loaded="):
        create_app(knowledge_base, loaded=load([], environ={}))


async def test_the_boot_line_names_a_reference_never_its_value(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("KB_TEST_TOKEN", "s3cret-boot")
    path = tmp_path / "config.yaml"
    path.write_text(
        "sources:\n- name: dav\n  url: webdav+https://dav.example.com/kb\n"
        "  auth:\n    username: kb\n    password: {env: KB_TEST_TOKEN}\n"
    )
    loaded = load(["--config-file", str(path)], environ={})
    app = create_app(KnowledgeBase(loaded.config, tmp_path / "cache"), loaded=loaded)
    with caplog.at_level(logging.INFO, logger="kubed.mcp.config"):
        async with Client(app.server):
            pass
    line = next(r.getMessage() for r in caplog.records if r.name == "kubed.mcp.config")
    assert "KB_TEST_TOKEN" in line and "s3cret-boot" not in line
```

  `tests/test_wiki.py`: its import of `build_parser` becomes `named_items`, and
  `test_deployment_documents_every_environment_variable` (lines 153-161) reads the names off the
  schema: `declared = {"CONFIG_FILE", *(env for _, env, _ in
  named_items(schema()))}`. Its docstring says the schema is where every name is written.

  `tests/test_packaging.py`: `test_the_env_defaults_match_mains` becomes:

```python
def test_the_image_names_the_config_file_and_matches_the_defaults():
    from kubed.mcp_kb.config import Config, Serving

    runner = "\n".join(dockerfile_stages()["runner"])
    env = dict(re.findall(r"\b([A-Z_]+)=(\S+?)\s*\\?$", runner, re.MULTILINE))
    assert "CONFIG" not in env
    assert env["CONFIG_FILE"] == "/etc/mcp-kb/config.yaml"
    assert f"COPY examples/config.yaml {env['CONFIG_FILE']}" in runner
    assert pathlib.Path(env["CACHE_DIR"]) == Config.model_fields["cache_dir"].default
    serving = Serving()
    assert (env["TRANSPORT"], env["HOST"], int(env["PORT"])) == (
        serving.transport, serving.host, serving.port)
```

  `tests/test_webdav_source.py:598`: `--config` becomes `--config-file`.

  `tests/test_skills_extension.py`, using the module's `request` helper and its client set-up:

```python
plain = await request(client, "skills/get", uri=ALPHA)
dotted = await request(client, "skills/get", uri="skill://flatsource/./alpha/SKILL.md")
assert dotted["skill"] == plain["skill"]
```

  It goes in a new test, `test_skills_get_resolves_a_dot_segment_once`.

- [ ] **Step 4: Flip the live tests.** In `tests/test_live.py`, every assertion labelled `N6: the
  re-adding read` or `N6: the re-adding request` now asserts the edit. Where it read `"first"`, it
  reads what the edit wrote.
  - Each docstring that says "one request late", "from the next request" or "read twice" says the
    request that re-reads serves the edit.
  - A test that read a second time only to see the edit drops that read. A test that reads twice to
    prove a later read keeps the edit keeps both reads, and both now assert the edit.
  - `test_live.py:477` (`the read that re-adds still prices its pin`) is about build counting.
    Assert what the build cache holds after the one re-adding read, and say so in its docstring.
  - Line 1162's comment drops "one request late".

- [ ] **Step 5: Run them to verify they fail.**

  Run: `pytest tests/test_config.py tests/test_index.py tests/test_schema.py tests/test_app.py tests/test_packaging.py tests/test_live.py tests/test_skills_extension.py -v`
  Expected:
  - an ImportError on `load`, `SECTIONS` and `split_command`;
  - once those exist, the new items are missing, `create_app` takes no `loaded`, the Dockerfile
    still says `CONFIG=`, and the flipped `N6` assertions still see `first`.

  The dot-segment test may already pass on 0.5: it is a guard.

- [ ] **Step 6: Implement the config** (D1 to D6, D9, D10, D12): `config.py` and `index.py`, as the
  Interfaces say.
  - `Item` docs, word for word:
    - `sources`: "Backends, named once: where bytes come from and how to log in.";
    - `plugins`: "Folders of skills, agents and prompts under a source.";
    - `libraries`: "Saved queries over plugins: the first segment of every address served.";
    - `cache_dir`: "Where a non-file:// source materialises, and where index.json lives.";
    - `transport`: "The transport kb serves on: http or stdio.";
    - `host`: "The address the http transport binds."
  - The module docstring drops "Environment variables and flags say *how* to run … and never
    overlap with it". In its place: one composed config, whose root is this file's `Config` and
    whose sections are kubed-mcp's `serving`, `telemetry` and `delivery` (the first two with kb's
    defaults and guard), every item set from the file, an env var or a flag.
- [ ] **Step 7: Implement the entry point and the app** (D7, D8, D13), and the Dockerfile line.
  - `main.py`'s docstring says the `serve`/`schema` word, `--help` and the `CONFIG` guard are kb's,
    and that every other token goes to kubed-mcp's loader with the environment. The names are
    written in `config.py`'s sections.
  - The comment above `create_app(...).run(...)` says `run()` reads `serving`, and that uvicorn is
    given no log config of its own.
  - `create_app`'s ValueError reads `loaded= is a load of another config: load the knowledge base's
    own`.
- [ ] **Step 8: Implement D11** in `SkillServing.view()`: call `self._reread_live(scope)`, then read
  `published = self._published` and pin that. The docstrings and the module paragraph say that
  kubed-mcp takes its state after the view (0.4.2), so the request whose view re-reads a moved
  plugin reads the re-read, its pin for the rewriter included. Line 1351's `(N6)` becomes
  `(SKL-37)`.
- [ ] **Step 9: Regenerate.**
  - Run `mcp-kb schema > config.schema.json`.
  - Update `scripts/generate_wiki.py` and `wiki/Deployment.md` as the Files say.
  - Run `python scripts/generate_wiki.py`.
- [ ] **Step 10: Run the whole suite.**

  Run: `ruff check . && python scripts/generate_wiki.py --check && mcp-kb schema | diff - config.schema.json && pytest`
  Expected: clean, no diff, all PASS. `tests/test_header_scope.py` (real uvicorn) and
  `tests/test_wiki.py` must run rather than skip.
- [ ] **Step 11: Commit the wiki first,** inside `wiki/`, without pushing, as `Configuration and
  Deployment: every item's env var and flag`. Then commit the superproject:
  `feat: one composed config through kubed-mcp 0.5, an env var and a flag for every item`

### Task 2: Spec, AGENTS.md, README, CONTRIBUTING, wiki and changelog

**Files:**
- Modify: `docs/superpowers/specs/config-and-sources.md`. Each item below is an ID and the text it
  takes:
  - **CFG-1:** "Every config item is set by, from lowest to highest: its default, the config file,
    its environment variable, its flag. A mapping merges key by key; a list or a value replaces
    what is below it whole. A blank value is unset." Then the names table from the Global
    Constraints, `telemetry.*` and `delivery.*` spelled out item by item from `mcp-kb schema`.
  - **CFG-2:** "There is one config. What to serve, how to run, what the process reports and the
    delivery defaults are all items of it, and each one can be set in the file, an env var or a
    flag." Keep the `OTEL_*`, `POD_NAME` and `POD_NAMESPACE` sentence.
  - **CFG-3:** add "It is the whole config's schema, each item with its `env` and `arg`."
  - **CFG-4:** "…top-level lists `sources`, `plugins` and `libraries`, a `cache_dir`, and the
    mappings `serving`, `telemetry` (CFG-15) and `delivery` (CFG-19). An empty file, or none, is a
    valid config with all three lists empty, kb's run defaults, and every telemetry signal off."
  - **CFG-7:** "…exits with code 2 and `mcp-kb: the config did not load:` on stderr, then one line
    per error, `<path> (<source>): <reason>`. A bad env var or flag, an unknown flag, and a
    positional argument other than `serve` or `schema` are config errors too."
  - **CFG-8:** "No config error quotes a value it was given. One of kb's own messages that names an
    address has its `user:password@` masked as `***@`."
  - **CFG-15:** the `telemetry` mapping is kubed-mcp's built-in section with its `TELEMETRY_*`
    names, and kb adds only the `profiles` guard.
  - **SRC-36:** "The hash covers `sources`, `plugins` and `libraries` alone, so editing `serving`,
    `cache_dir`, `telemetry` or `delivery` costs no refetch."
  - **SRC-21:** its last sentence becomes "…found that way is served to the request that found it."
  - New **CFG-16:** the file is named by `--config-file`, else `CONFIG_FILE`, and with neither no
    file is read. A named file that does not exist, is not a file, is not YAML or is not a mapping
    exits 2 naming its path.
  - New **CFG-17:** `KB_SOURCES`, `KB_PLUGINS` and `KB_LIBRARIES` (and their flags) take a JSON
    array.
  - New **CFG-18:** when serving starts, the server logs one line on `kubed.mcp.config` naming each
    item not at its default, its value and where it came from. A secret prints as `***`.
  - New **CFG-19:** the `delivery` mapping is kubed-mcp's defaults for the delivery inputs
    (`resources`, `listed`, `via`). A request's own header or query parameter wins over it.
  - New **CFG-20:** `mcp-kb serve` with `CONFIG` set exits 2 with `mcp-kb: CONFIG is no longer
    read: name the config file with CONFIG_FILE`. `--config` is an unknown flag (CFG-7).
  - The SRC-41 exit-code table's row for 2 adds "or `CONFIG` is set".
- Modify: `docs/superpowers/specs/http-and-tools.md`.
  - **HTTP-6:** the `serving` items. `transport` is `http` (default) or `stdio`, kb's narrowing of
    kubed-mcp's four transports, and `sse` or `streamable-http` is a config error.
  - **HTTP-34:** `CONFIG_FILE=/etc/mcp-kb/config.yaml` in place of `CONFIG=…`.
  - **HTTP-39:** `LOG_LEVEL` is read case-insensitively.
- Modify:
  - `docs/superpowers/specs/skills.md`:
    - **SKL-37:** "…from that request on…, and the request that re-reads reads the new bytes";
    - **SKL-39:** "a prompt file skipped as broken serves from the request that notices its fix";
  - `agents.md` **AGT-16**: "from the request that found the edit", in its three places;
  - `prompts.md` **PRM-58**: "serves from the request that found it".
- Modify: `AGENTS.md`:
  - the `main.py` and `config.py` Layout rows (`config.py` holds the sections and `load`; `main.py`
    is the `serve`/`schema` word, `--help`, the `CONFIG` guard and the run);
  - "A new flag or env var" becomes **A new config item** → a field of a section in `config.py`,
    with its `env` and `arg` written out, never derived. `main.py` loads, and reads `os.environ`
    for the `CONFIG` guard alone; `EnvRef.resolve` is still the one other reader;
  - the telemetry bullet: `Telemetry` subclasses kubed-mcp's section for the guard alone, and
    `config_hash` reads the three lists;
  - "A live edit reads one request late" is deleted. The live paragraph in "The surface" says the
    request that re-reads serves the edit.
- Modify: `README.md:160-175`, the env table, to the Global Constraints' names, with a sentence
  that every item can be set in the file too.
- Modify: `CONTRIBUTING.md:157`: `--config-file`.
- Modify (submodule `wiki/`):
  - `Quick-Start.md:93-105` passes `--config-file`, and its sentence says no file is read unless
    named;
  - `Config-File.md:6` names `--config-file` / `CONFIG_FILE`;
  - `Plugins.md:312-325` and `Sources.md:175`: a live edit serves in the request that finds it;
  - `notes/Configuration.notes.md` gains "## Setting an item without the file": precedence,
    `KB_SOURCES` as JSON, and the boot line.

  Then run `python scripts/generate_wiki.py`.
- Modify: `CHANGELOG.md` `[Unreleased]`, with the Design's five lines, under `### Changed` and
  `### Added` as given.

- [ ] **Step 1: Write the docs** with the wording above. Check that nothing still names the old
  setting:

  ```bash
  git grep -nE 'CONFIG([^_A-Z]|$)|--config([^-]|$)' -- . ':!docs/superpowers/plans' ':!docs/saga' ':!CHANGELOG.md'
  ```

  It prints only CFG-20, the guard in `main.py`, its test, and the config tests that prove
  `CONFIG` and `--config` are not read.
- [ ] **Step 2: Verify.**

  Run: `python scripts/generate_wiki.py --check && pytest tests/test_wiki.py -v && ruff check . && pytest`
  Expected: pass, no skips.
- [ ] **Step 3: Commit the wiki first,** inside `wiki/`, without pushing. Then commit the
  superproject with the specs, `AGENTS.md`, the README, CONTRIBUTING, the changelog and the
  submodule pointer:
  `docs: one composed config, CONFIG_FILE, and a live edit in its own request`

## QA, outside the runner

- Run Publish with `push: false`. The image builds, and `docker run --rm <image> --help` lists
  every item.
- `docker compose up` serves `examples/config.yaml`. Its first log lines include `config:
  cache_dir=… (env CACHE_DIR), …, serving.transport="http" (env TRANSPORT)`, and `/health` shows
  the four libraries.
- A deployment that still sets `CONFIG=` exits 2 at boot naming `CONFIG_FILE` (D13), until it is
  renamed. Its release note is the BREAKING line.
