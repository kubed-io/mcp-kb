# Telemetry from kubed-mcp: a `telemetry` Config Section, and the Image's Extra — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use skill://superpowers/subagent-driven-development/SKILL.md (recommended) or skill://superpowers/executing-plans/SKILL.md to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A deployment turns on kubed-mcp's profiles, traces and metrics with a `telemetry`
section in kb's config file, and only the image carries the packages that send them.

**Architecture:** `Config` gains one field, `telemetry: TelemetrySettings`. That is kubed-mcp's
model, embedded as it is, and `QuickMCP` already reads it off the config `create_app` passes it
(`getattr(config, "telemetry", None)`, TEL-2). So kb writes no telemetry code. It writes the field,
a credential guard, and the config hash that leaves the section out. `pyproject.toml` gains a
`telemetry` extra, and the Dockerfile installs it.

**Tech Stack:** Python ≥3.11, pydantic 2, `kubed-mcp>=0.3.0,<0.4` (FastMCP through it), pytest +
pytest-asyncio.

**Spec:** this file's Design section, [CFG-14](../specs/config-and-sources.md#telemetry) and
[HTTP-42](../specs/http-and-tools.md#the-container), both *(proposed)* until Task 3. The brief is
issue #78's notes and Dr K's rulings there (2026-11-24, 2026-11-25). There is no separate design
doc. Shipped as CFG-15 and HTTP-43: issue-80 had taken CFG-14 and HTTP-42 by the time Task 3 landed.

## Design

**Upstream, checked against the `v0.3.0` tag (kubed-io/quick-mcp#12):**

- `from kubed.mcp import TelemetrySettings` is an eager import of `kubed/mcp/telemetry.py`. That
  module imports the stdlib and pydantic, with FastMCP only under `TYPE_CHECKING`. Every other
  `kubed.mcp` name resolves lazily (FAC-11), so importing `kubed.mcp_kb.config` still loads no
  FastMCP.
- `TelemetrySettings(BaseModel)` has `extra="forbid"` and is not frozen. Its fields are `profiles:
  str | None = None`, `profile_cpu: bool = True`, `profile_memory: bool = True`, `otel: bool =
  False` and `tags: dict[str, str] = {}`.
- `kubed-mcp[telemetry]` brings `pyroscope-io>=1.2,<2` and the OpenTelemetry SDK, the OTLP/HTTP
  exporter and the Prometheus exporter. pyroscope-io ships `abi3` manylinux wheels for x86_64 and
  aarch64, so the 3.14 two-arch image needs no toolchain.
- A signal that is on but whose package is missing logs one warning that names
  `kubed-mcp[telemetry]`, and the server serves without that signal (TEL-4). A signal that is off
  imports nothing.

**Decided:**

| # | Decision | Why |
|---|---|---|
| D1 | `Config.telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)`. kb has no local copy and does not subclass it (Dr K, ruling 1) | The model's own `extra="forbid"` keeps CFG-5 true. The default is every signal off, so a config with no section starts exactly as before |
| D2 | **File only.** `main.py` maps no variable into `telemetry` (the issue's option (a)) | CFG-2 holds for kb's own settings. `OTEL_*`, `POD_NAME` and `POD_NAMESPACE` are read by kubed-mcp and the OpenTelemetry SDK, never by kb. A per-environment Pyroscope address goes in that environment's config file |
| D3 | `config_hash` leaves `telemetry` out: `config.model_dump(mode="json", exclude={"telemetry"})` | Telemetry changes nothing served, so editing it must not cost a refetch of everything at the next boot (SRC-36, SRC-40). It also keeps every existing `index.json` reusable across the upgrade, because a config's hash is the same as before the field existed |
| D4 | `Config` refuses a `telemetry.profiles` address with userinfo: `telemetry.profiles must not embed a credential` | House rule: the file is safe to commit and to publish as a ConfigMap, and a source URL carrying `user:token@` is refused (SRC-3). `load_config` already masks userinfo in the error (CFG-8). A Pyroscope that needs auth waits for an upstream setting that takes an `{env:}` reference |
| D5 | The image's `scripts/requirements.py runtime` line gets `--extra telemetry` and nothing else. The runner's build-time import check imports `pyroscope` and `opentelemetry.sdk` as well | PKG-22 and Dr K's ruling: the image carries the profiler and nothing else does. A wheel that does not load on `-slim` or on arm64 then fails the build, not a pod |
| D6 | Two CI checks follow the extra. `lint.yml`'s Dependency Audit installs `.[telemetry]`, and `package.yml` fails if `pyroscope` imports from a plain wheel install | The audit says it covers "what the IMAGE actually installs", and from now on that includes the extra. "A wheel install doesn't have it" is a done-when of #78, so a check holds it |
| D7 | No `/metrics` route, and no doc mentions `OTEL_METRICS_EXPORTER=none` (Dr K, rulings 4 and 5) | Metrics are pushed over OTLP, or scraped from the exporter's own port with `OTEL_METRICS_EXPORTER=prometheus` and `OTEL_EXPORTER_PROMETHEUS_HOST=0.0.0.0` for a scrape from another pod (TEL-17) |

**Checked, and needs nothing:** nothing in kb hashes or freezes a whole `Config`. `hash(config)`
already raises, because its fields are lists, and no `lru_cache` or dict key takes one. So the
non-frozen nested model needs no upstream change. The pod and namespace labels (TEL-9) are the
deployment's downward-API change, not this repository's.

**Not in this change:** the `kubed-mcp` pin. #92 moves it to `>=0.3.0,<0.4` first, and this branch
takes it from `main` (Dr K, 2026-11-25). There is also no env mapping (D2), no telemetry in
`examples/config.yaml`, and no image tag without the profiler.

## Global Constraints

- **Toolchain** (CI's `test.yml`): `pip install -e ".[test]"`, then `ruff check .` and `pytest`
  from the repository root. Check out the `wiki/` submodule (`git submodule update --init`), so
  `tests/test_wiki.py` runs rather than skips. `python scripts/generate_wiki.py --check` and
  `mcp-kb schema` must agree with what is committed.
- **The pin is #92's, `kubed-mcp>=0.3.0,<0.4`.** This PR does not edit that line. If the branch's
  `pyproject.toml` still says `<0.2`, merge `main` first. If `main` does not have #92 yet, stop and
  report: nothing here imports on 0.1.
- **The facade only:** `from kubed.mcp import TelemetrySettings` in `kubed/`. Never
  `kubed.mcp.telemetry`, `fastmcp` or `pyroscope`. Tests may import `fastmcp.Client`, as they
  already do.
- **`catalogue/` and `plugins/` import no FastMCP** (`tests/test_boundaries.py`), and both import
  `config.py`.
- **Python 3.11 is the floor.** Every module starts `from __future__ import annotations`. Lines are
  at most 88 columns.
- **Markers:** `tests/test_app.py` is `unit` module-wide. A new test in `tests/test_config.py`,
  `tests/test_schema.py` or `tests/test_index.py` follows its neighbours.
- **Wording:** metrics are "pushed over OTLP, or scraped from the exporter's own port with
  `OTEL_METRICS_EXPORTER=prometheus`", and "the server adds no metrics route". No file this PR
  ships writes `/metrics` or `OTEL_METRICS_EXPORTER=none`.
- **Public repo:** the maintainer is Dr K. Use `pyroscope.example.com` and no real hosts or names.
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Upgrading the image costs no refetch.** A config with no `telemetry` section hashes exactly
   as it did before the field existed, so the `index.json` on a deployment's volume is reused. →
   Task 1, `test_config_hash_leaves_the_telemetry_section_out` pins the empty config's hash to the
   old formula.
2. **A token in the Pyroscope address is refused and never echoed.** → Task 1,
   `test_a_credential_in_the_profiles_address_is_refused`.
3. **A typo'd key does not leave profiles silently off.** `telemetry: {profile: …}` exits 2 and names
   the key. → Task 1, `test_a_typod_telemetry_key_exits_2`.
4. **A plain wheel install with profiles on serves, with one warning.** It also proves the section
   reaches `QuickMCP` at all. → Task 1, `test_the_telemetry_section_reaches_the_server`.
5. **Reading the config still imports no FastMCP**, now that `config.py` imports `kubed.mcp`. →
   Task 1, `test_the_config_imports_no_fastmcp`.

---

### Task 1: `Config.telemetry`, and the hash that leaves it out

**Files:**
- Modify: `kubed/mcp_kb/config.py`. Import `TelemetrySettings`, add the field and
  `_telemetry_carries_no_credential` to `Config`, and update the `Config` docstring and the module
  docstring.
- Modify: `kubed/mcp_kb/catalogue/index.py:344-347`, `config_hash`.
- Modify: `scripts/generate_wiki.py:68-80`. Append `"TelemetrySettings"` to `MODELS`, and make the
  comment say the last one is kubed-mcp's.
- Regenerate: `config.schema.json` (`mcp-kb schema > config.schema.json`) and `wiki/Configuration.md`
  (`python scripts/generate_wiki.py`).
- Test: `tests/test_config.py`, `tests/test_schema.py`, `tests/test_index.py`,
  `tests/test_boundaries.py`, `tests/test_app.py`

**Interfaces:**
- Produces, in `kubed/mcp_kb/config.py`:
  - `Config.telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings, description=
    "What the process reports: kubed-mcp's profiles, traces and metrics. Absent, every signal is
    off.")`
  - `Config._telemetry_carries_no_credential(self) -> Config`, an after-validator. If
    `self.telemetry.profiles` parses with `urlsplit` to a `username` or a `password`, it raises
    `ValueError("telemetry.profiles must not embed a credential")`.
- Produces, in `kubed/mcp_kb/catalogue/index.py`: `config_hash(config: Config) -> str`, the same
  signature, over `config.model_dump(mode="json", exclude={"telemetry"})`. Its docstring says why
  (D3).

- [ ] **Step 1: Check the pin.** `grep kubed-mcp pyproject.toml` must show `>=0.3.0,<0.4`.
  Otherwise see Global Constraints. Run `pip install -e ".[test]"`.

- [ ] **Step 2: Write the failing tests.**

  `tests/test_config.py`. Import `TelemetrySettings` from `kubed.mcp` and use the module's `write`:

```python
def test_no_telemetry_section_is_every_signal_off(tmp_path):
    config = load_config(write(tmp_path, ""))
    assert config.telemetry == TelemetrySettings()
    assert config.telemetry.profiles is None and config.telemetry.otel is False


def test_a_telemetry_section_parses(tmp_path):
    config = load_config(write(tmp_path, (
        "telemetry:\n  profiles: http://pyroscope.example.com:4040\n"
        "  otel: true\n  tags: {team: platform}\n"
    )))
    assert config.telemetry.profiles == "http://pyroscope.example.com:4040"
    assert config.telemetry.otel is True
    assert config.telemetry.tags == {"team": "platform"}
    assert config.telemetry.profile_cpu is True


def test_a_typod_telemetry_key_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="profile"):
        load_config(write(tmp_path, "telemetry:\n  profile: http://pyroscope.example.com\n"))


def test_a_credential_in_the_profiles_address_is_refused(tmp_path):
    text = "telemetry:\n  profiles: http://me:s3cret@pyroscope.example.com:4040\n"
    with pytest.raises(ConfigError) as raised:
        load_config(write(tmp_path, text))
    assert "must not embed a credential" in str(raised.value)
    assert "s3cret" not in str(raised.value)


def test_the_schema_carries_the_telemetry_section():
    published = schema()
    assert published["properties"]["telemetry"]["$ref"].endswith("/TelemetrySettings")
    model = published["$defs"]["TelemetrySettings"]
    assert {"profiles", "otel", "tags"} <= set(model["properties"])
    assert model["additionalProperties"] is False
```

  `tests/test_schema.py`:

```python
def test_a_typod_telemetry_key_exits_2(tmp_path, capsys):
    path = tmp_path / "config.yaml"
    path.write_text("telemetry:\n  profile: http://pyroscope.example.com:4040\n")
    with pytest.raises(SystemExit) as raised:
        main(["serve", "--config", str(path)])
    assert raised.value.code == 2
    err = capsys.readouterr().err
    assert "mcp-kb:" in err and "profile" in err
```

  `tests/test_index.py`. Import `hashlib` and `json`. The literal is what `config_hash` returned
  for an empty file before the field existed:

```python
@pytest.mark.unit
def test_config_hash_leaves_the_telemetry_section_out(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("")
    watched = tmp_path / "watched.yaml"
    watched.write_text("telemetry:\n  profiles: http://pyroscope.example.com:4040\n")
    before = json.dumps({"libraries": [], "plugins": [], "sources": []}, sort_keys=True)
    assert config_hash(load_config(empty)) == hashlib.sha256(before.encode()).hexdigest()
    assert config_hash(load_config(watched)) == config_hash(load_config(empty))
```

  `tests/test_boundaries.py`:

```python
def test_the_config_imports_no_fastmcp():
    """`config.py` embeds kubed-mcp's `TelemetrySettings`; `kubed.mcp` resolves
    every other name lazily, so reading a config still loads no FastMCP."""
    result = imports_clean(("kubed.mcp_kb.config",))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
```

  `tests/test_app.py`. Import `logging`, `sys` and `TelemetrySettings`. pyroscope is blocked so
  that nothing is sent even where it is installed:

```python
async def test_the_telemetry_section_reaches_the_server(
    skills_dir, tmp_path, monkeypatch, caplog
):
    monkeypatch.setitem(sys.modules, "pyroscope", None)
    on = TelemetrySettings(profiles="http://pyroscope.example.com:4040")
    config = make_config(skills_dir).model_copy(update={"telemetry": on})
    app = create_app(KnowledgeBase(config, tmp_path / "cache"))
    with caplog.at_level(logging.WARNING):
        async with Client(app.server) as client:
            assert await client.list_resources()
    warned = [r for r in caplog.records if "kubed-mcp[telemetry]" in r.getMessage()]
    assert len(warned) == 1


async def test_no_telemetry_section_starts_no_signal(skills_dir, tmp_path, caplog):
    app = create_app(KnowledgeBase(make_config(skills_dir), tmp_path / "cache"))
    with caplog.at_level(logging.WARNING):
        async with Client(app.server) as client:
            assert await client.list_resources()
    assert not [r for r in caplog.records if "telemetry" in r.getMessage()]
```

- [ ] **Step 3: Run them to verify they fail.**

  Run: `pytest tests/test_config.py tests/test_schema.py tests/test_index.py tests/test_boundaries.py tests/test_app.py -v -k "telemetry or fastmcp"`
  Expected: the telemetry tests FAIL. Without the field, `telemetry:` is an unknown key, so
  `load_config` raises and `make_config(...).model_copy` adds a field nobody reads.
  `test_config_hash_leaves_the_telemetry_section_out` fails on its second assertion.
  `test_the_config_imports_no_fastmcp` and `test_no_telemetry_section_starts_no_signal` already
  pass. They are guards and must stay green.

- [ ] **Step 4: Implement** the Interfaces above.
  - The module docstring's "Three lists, each answering one question:" gains a fourth bullet. The
    **telemetry** section is kubed-mcp's `TelemetrySettings`, as it is: what the process reports,
    never what it serves. A setting for it is added upstream, never here.
  - The `Config` docstring ends "…the libraries, and the process's telemetry."
  - Then run `mcp-kb schema > config.schema.json` and `python scripts/generate_wiki.py`.
  - If `test_the_telemetry_section_reaches_the_server` sees no warning, find where kubed-mcp 0.3.0
    starts its signals. If that is `run()` rather than the server's lifespan, drive the test through
    `tests/test_header_scope.py`'s uvicorn harness instead of the in-memory `Client`. If the
    once-per-process ownership (TEL-5) suppresses the warning, use the reset kubed-mcp's own tests
    use, and say so in the test's docstring. If there is no such reset, stop and report. Do not
    patch kubed-mcp's private state.

- [ ] **Step 5: Run the whole suite.**

  Run: `ruff check . && python scripts/generate_wiki.py --check && pytest`
  Expected: clean, all PASS, `tests/test_wiki.py` not skipped. `wiki/Configuration.md` has a
  `TelemetrySettings` section, and `config.schema.json` has the `telemetry` property.

- [ ] **Step 6: Commit the wiki first,** inside `wiki/`, without pushing, as
  `Configuration: the telemetry section`. Then commit the superproject:
  `feat: a telemetry section in the config, read by kubed-mcp`

### Task 2: The `telemetry` extra, in the image and nowhere else

**Files:**
- Modify: `pyproject.toml`. Add, under `[project.optional-dependencies]` after `test`:

```toml
# Profiles to Pyroscope, and traces and metrics over OpenTelemetry, switched on by
# the config's `telemetry` section. The image installs it (the Dockerfile's
# --extra telemetry) and nothing else does, so a pip install of kb carries no
# profiler unless asked for. kubed-mcp owns the pins.
telemetry = ["kubed-mcp[telemetry]"]
```

- Modify: `Dockerfile`.
  - Line 56 becomes `python scripts/requirements.py runtime --extra telemetry > /tmp/requirements.txt`.
  - The comment on lines 53-55 keeps its first sentence. Its last one becomes: "`--extra
    telemetry` and no other: the profiler and OpenTelemetry belong in the image and in no plain
    install, and [build] and [test] are tooling."
  - Line 101 becomes `RUN python -c "import pyroscope, opentelemetry.sdk; from kubed.mcp_kb.server import KnowledgeBase"`.
    Add one sentence to the comment above it: the telemetry packages are imported too, so a wheel
    that will not load on `-slim` fails the build.
- Modify: `scripts/requirements.py:37-41`, the `runtime()` docstring. `telemetry` is the one
  runtime extra, and only the image asks for it. `build` and `test` are tooling. Keep the sentence
  saying the choice is the Dockerfile's.
- Modify: `.github/workflows/package.yml`. Add a step after "Verify the Wheel Installs":

```yaml
    # The profiler is the image's alone (the Dockerfile's --extra telemetry), so a
    # plain install of the wheel must not carry it.
    - name: Verify the Wheel Carries No Profiler
      run: |
        if /tmp/verify/bin/python -c "import pyroscope" 2>/dev/null; then
          echo "::error::pyroscope imports from a plain wheel install"
          exit 1
        fi
```

  Use `if`, not `! cmd`: under `bash -e` a negated command never fails the step.
- Modify: `.github/workflows/lint.yml`. "Install Runtime Dependencies" runs
  `pip install --editable ".[telemetry]"`. The comment above it says the telemetry extra is
  installed because the image installs it, and the test extra still is not.
- Test: `tests/test_packaging.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: the `telemetry` extra, which Task 3's docs name.

- [ ] **Step 1: Write the failing tests** in `tests/test_packaging.py`.
  - Replace `test_no_extra_is_a_runtime_extra_here` (Dr K, ruling 3).
  - Extend `test_the_copied_venv_is_proved_to_work_at_build_time` with
    `assert any("import pyroscope" in ln and "kubed.mcp_kb.server" in ln for ln in runner)`.
  - Add the two tests below.

```python
def test_telemetry_is_the_one_runtime_extra_and_the_image_asks_for_it():
    """[build] and [test] are tooling; [telemetry] is the image's alone."""
    data = tomllib.loads(PYPROJECT.read_text())
    extras = data["project"]["optional-dependencies"]
    assert set(extras) == {"build", "test", "telemetry"}
    assert extras["telemetry"] == ["kubed-mcp[telemetry]"]
    generate = next(
        ln for ln in dockerfile_stages()["builder"] if "requirements.py runtime" in ln
    )
    assert re.findall(r"--extra\s+(\S+)", generate) == ["telemetry"]


def test_the_package_alone_does_not_require_the_profiler():
    data = tomllib.loads(PYPROJECT.read_text())
    plain = requirements.runtime(data, [])
    assert not [d for d in plain if "[telemetry]" in d or "pyroscope" in d]
    assert requirements.runtime(data, ["telemetry"]) == [*plain, "kubed-mcp[telemetry]"]


def test_the_audit_covers_what_the_image_installs():
    lint = yaml.safe_load((REPO / ".github" / "workflows" / "lint.yml").read_text())
    steps = lint["jobs"]["deps"]["steps"]
    install = next(s for s in steps if s.get("name") == "Install Runtime Dependencies")
    assert install["run"].strip() == 'pip install --editable ".[telemetry]"'
```

- [ ] **Step 2: Run them to verify they fail.**

  Run: `pytest tests/test_packaging.py -v`
  Expected: the three new tests and the extended one FAIL. The rest PASS.

- [ ] **Step 3: Implement** the Files above, exactly as given.

- [ ] **Step 4: Verify.**

  Run: `ruff check . && pytest && python scripts/requirements.py runtime --extra telemetry`
  Expected: clean, all PASS. The printed list ends with `kubed-mcp[telemetry]`.
  `test_the_dependencies_are_installed_before_the_source` and
  `test_the_runner_receives_a_venv_and_installs_nothing` pass unchanged. hadolint runs in CI as
  `Lint / Dockerfile Lint`.

- [ ] **Step 5: Commit** `build: the image installs the telemetry extra, and nothing else does`

### Task 3: Spec, AGENTS.md, README, wiki and changelog

**Files:**
- Modify: `docs/superpowers/specs/config-and-sources.md`.
  - Drop `*(proposed; rewords CFG-2, CFG-4 and SRC-36)* ` from CFG-14.
  - CFG-2 reads: "The config file says what to serve, and in its `telemetry` section what the
    process reports; flags and environment say how to run. No setting exists in both. The
    `OTEL_*`, `POD_NAME` and `POD_NAMESPACE` variables are read by kubed-mcp's telemetry and the
    OpenTelemetry SDK, never by kb, and are no kb setting. Transport, host and port are in
    [http-and-tools.md](http-and-tools.md)."
  - CFG-4's first two sentences read: "The file is YAML with three optional top-level lists,
    `sources`, `plugins` and `libraries`, and an optional `telemetry` mapping (CFG-14). An empty
    file is a valid config with all three lists empty and every telemetry signal off."
  - SRC-36 gains a last sentence: "The hash leaves `telemetry` out, so editing that section costs
    no refetch."
- Modify: `docs/superpowers/specs/http-and-tools.md`. Drop `*(proposed)* ` from HTTP-42.
- Modify: `AGENTS.md`.
  - The `config.py` row of the Layout table ends "…`EnvRef`, `schema()`, and `telemetry`,
    kubed-mcp's `TelemetrySettings` as it is".
  - "Where code goes" gains a bullet after "A new flag or env var": **A telemetry setting** →
    kubed-io/quick-mcp's `TelemetrySettings`, never a field of kb's. `Config.telemetry` embeds it
    as it is, `QuickMCP` reads it off the config, and `config_hash` leaves it out because it
    changes nothing served. Metrics are pushed over OTLP, or scraped from the exporter's own port
    with `OTEL_METRICS_EXPORTER=prometheus` and `OTEL_EXPORTER_PROMETHEUS_HOST=0.0.0.0` for a
    scrape from another pod. The server adds no metrics route. Only the image installs the
    `telemetry` extra.
- Modify: `README.md`, "⚙️ Configuration". After the env table, two sentences. Profiles to
  Pyroscope and OpenTelemetry traces and metrics are switched on in the config file's `telemetry`
  section (`profiles: http://pyroscope.example.com:4040`, `otel: true`), with metrics pushed over
  OTLP or scraped from the exporter's own port with `OTEL_METRICS_EXPORTER=prometheus`. The image
  ships the packages, and a pip install needs `kubed-mcp-kb[telemetry]`.
- Modify (submodule `wiki/`): `notes/Configuration.notes.md` gains a section, "## `telemetry` is
  what the process reports, not what it serves". It covers:
  - every signal is off without the section;
  - the YAML example from CFG-14;
  - the service name is `OTEL_SERVICE_NAME`, else `mcp-kb`;
  - `OTEL_*` configures OpenTelemetry, and `POD_NAME` and `POD_NAMESPACE`, set from the downward
    API, label profiles by pod;
  - the metrics sentence from the Global Constraints;
  - an address with `user:token@` is refused;
  - editing the section costs no refetch;
  - the image has the packages, and a pip install needs `[telemetry]`.

  Then regenerate the page: `python scripts/generate_wiki.py`.
- Modify: `CHANGELOG.md` `[Unreleased]`, `### Added`, last line:
  `- **Send profiles to Pyroscope, and traces and metrics over OpenTelemetry**, from a \`telemetry\` section in the config; the image ships the packages.`

- [ ] **Step 1: Write the docs,** with the wording above and the Global Constraints' metrics
  wording. Check that no file this PR touches says `/metrics` or `OTEL_METRICS_EXPORTER=none`:
  `git diff main -- . ':!docs/superpowers/plans' | grep -nE '^\+.*(/metrics|OTEL_METRICS_EXPORTER=none)'` prints
  nothing.
- [ ] **Step 2: Verify.**

  Run: `python scripts/generate_wiki.py --check && pytest tests/test_wiki.py -v && ruff check . && pytest`
  Expected: pass, no skips.

- [ ] **Step 3: Commit the wiki first,** inside `wiki/`, without pushing. Then commit the
  superproject with the spec, `AGENTS.md`, the README, the changelog and the submodule pointer. The
  controller pushes.
  Commit: `docs: the telemetry section`

## QA, outside the runner

These are the #78 done-whens that CI cannot reach, for Dr K or the deployment:

- Run Publish with `push: false` (or Image's `workflow_dispatch` with push off). The two-arch build
  passes the runner's `import pyroscope, opentelemetry.sdk` check.
- `docker run --rm --entrypoint python <image> -c "import pyroscope"` succeeds.
  `pip install <wheel>` into a fresh venv fails that import, which `package.yml` now checks too.
- Point the deployed config's `telemetry.profiles` at the cluster's Pyroscope, and set `POD_NAME`
  and `POD_NAMESPACE` from the downward API. Profiles then appear under `service_name="mcp-kb"`,
  labelled by pod.
