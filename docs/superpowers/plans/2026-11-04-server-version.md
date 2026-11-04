# kb's Own Version in `serverInfo` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `serverInfo.version` reports kb's package version instead of FastMCP's.

**Architecture:** `spec/builder.py::_info()` already reads kb's version from the installed
distribution for the OpenAPI document. A public `package_version()` beside it returns that
version, and `server.py` passes it to `FastMCP(..., version=...)`. Then the document and the
handshake share one lookup and cannot disagree.

**Tech Stack:** Python ≥3.11, FastMCP 4 (`fastmcp>=4.0.0,<5`), pytest + pytest-asyncio.

**Spec:** this file's Design section, and [HTTP-41](../specs/http-and-tools.md), which is
*(proposed)* until Task 1 lands. The brief is gap 2 of issue #38, filed as #47. The change is small
enough that it has no separate design doc.

## Design

**The bug.** `server.py` builds `FastMCP("mcp-kb", ...)` with no `version=`, so FastMCP fills in
its own. Every result's `_meta["io.modelcontextprotocol/serverInfo"]` reads
`{"name": "mcp-kb", "version": "4.1.5"}`, which is the installed `fastmcp`. kb in the same image
is `0.1.1.dev30+gd43f47cd4.d20261103` (setuptools_scm).

**The fix (HTTP-41).** The server's `serverInfo` is `{"name": "mcp-kb", "version": <v>}`, where
`<v>` is whatever HTTP-20 puts in the OpenAPI `info.version`:
- with the `kubed-mcp-kb` distribution installed, its `Version` metadata, passed through
  unchanged (a dev version with a local part is still a plain string);
- without it, `PLACEHOLDER_VERSION`, `"0.0.0"`.

This holds for the `initialize` answer, and for the `_meta` stamp on results in whichever eras
FastMCP stamps them.

**Not in this change:** the name stays the literal `"mcp-kb"`, and nothing else in `serverInfo`
(title, icons, website) is added.

## Global Constraints

- **Toolchain** (CI's `test.yml`): `pip install -e ".[test]"`, then run `ruff check .` and
  `pytest` from the repository root. The version tests need an *installed* distribution, which
  `pip install` gives. Check out the `wiki/` submodule (`git submodule update --init`) so that
  `tests/test_wiki.py` runs and is not skipped.
- **Python 3.11 is the floor.** Lines are at most 88 columns.
- **One lookup.** `server.py` gets the version only from `package_version()`. Do not read
  `importlib.metadata` in `server.py` or `main.py`, and do not add a second constant.
- **Do not edit** `test_info_is_drawn_from_pyproject` (`tests/test_openapi.py`). It must pass
  unchanged.
- **Markers:** every new test is `@pytest.mark.unit` (in-process, no uvicorn).
  `tests/test_openapi.py` already sets it module-wide.
- **Public repo:** the maintainer is Dr K; no names or real hostnames in code, tests or docs.
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Nothing installed still starts.** From a source tree with no `kubed-mcp-kb` metadata, the
   server serves with version `0.0.0` and does not raise. → Task 1,
   `test_without_the_distribution_the_version_is_the_placeholder`.
2. **A handshake-era client sees kb's version.** `initialize`'s `serverInfo.version` is kb's. →
   Task 1, `test_initialize_names_kb_and_its_version`.
3. **A modern sessionless client sees it on every result,** which is where the bug was seen. →
   Task 1, `test_every_result_names_kb_and_its_version`.
4. **The document and the handshake agree.** Both come from `package_version()`. →
   `test_info_is_drawn_from_pyproject` (unchanged) together with Task 1's tests, which compare
   against the same `importlib.metadata.version("kubed-mcp-kb")`.
5. **A dev version passes through verbatim.** CI checks out with `fetch-depth: 0` off a tag, so
   the installed version is a `.devN+g<sha>` string, and the tests compare it exactly, with no
   normalising. → Task 1's tests, as written.

---

### Task 1: Pass kb's version to FastMCP

**Files:**
- Modify: `kubed/mcp_kb/spec/builder.py`:
  - add `package_version()` below `_info()`;
  - in the module docstring's last paragraph, add a sentence: the same version names the MCP
    server (`server.py`), so the document and the handshake never disagree.
- Modify: `kubed/mcp_kb/spec/__init__.py`: re-export `package_version`, and add it to `__all__`.
- Modify: `kubed/mcp_kb/server.py:123-133`: add `version=package_version()` to the
  `FastMCP("mcp-kb", ...)` call, and import it with `from .spec import package_version`.
- Modify: `docs/superpowers/specs/http-and-tools.md`: remove `*(proposed)* ` from HTTP-41.
- Modify: `CHANGELOG.md`, `[Unreleased]` → `### Fixed`, as the last line:
  `` - `serverInfo` now reports kb's own version, not FastMCP's. ``
- Test: `tests/test_server.py`, `tests/test_openapi.py`

**Interfaces:**
- Produces, in `kubed/mcp_kb/spec/builder.py`: `package_version() -> str`, which returns
  `_info()[1]`. It is exported from `kubed.mcp_kb.spec`.

- [ ] **Step 1: Write the failing tests.** Add these to `tests/test_server.py`, which already
  imports `Client`, `KnowledgeBase`, `make_config` and `pytest`, and has the `skills_dir`
  fixture:

```python
from importlib.metadata import version as dist_version

import fastmcp
from mcp_types import SERVER_INFO_META_KEY

from tests.test_skills_extension import request

KB_INFO = {"name": "mcp-kb", "version": dist_version("kubed-mcp-kb")}


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_every_result_names_kb_and_its_version(skills_dir, mode):
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    async with Client(server.mcp, mode=mode) as client:
        listing = await request(client, "skills/list")
    assert listing["_meta"][SERVER_INFO_META_KEY] == KB_INFO
    assert KB_INFO["version"] != fastmcp.__version__


@pytest.mark.unit
async def test_initialize_names_kb_and_its_version(skills_dir):
    server = KnowledgeBase(make_config(skills_dir), skills_dir / "cache")
    async with Client(server.mcp, mode="legacy") as client:
        info = client.initialize_result.serverInfo
    assert {"name": info.name, "version": info.version} == KB_INFO
```

  Add this one to `tests/test_openapi.py`:

```python
def test_without_the_distribution_the_version_is_the_placeholder(monkeypatch):
    from importlib.metadata import PackageNotFoundError

    from kubed.mcp_kb.spec import builder

    def missing(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr(builder, "metadata", missing)
    assert builder.package_version() == "0.0.0"
    assert builder.build_spec()["info"]["version"] == "0.0.0"
```

- [ ] **Step 2: Run them to verify they fail**

  Run: `pytest tests/test_server.py tests/test_openapi.py -v -k "version"`
  Expected: the two `test_server.py` tests FAIL, because the version is FastMCP's (for example
  `'4.1.5' != '0.1.1.dev…'`). The `test_openapi.py` test FAILs with `AttributeError: ...
  package_version`.

  Two facts this plan could not check without FastMCP installed. Settle each from this run
  before Step 3:
  - **Legacy era, no stamp.** If the `legacy` case of
    `test_every_result_names_kb_and_its_version` fails with `KeyError` on `_meta` or on
    `SERVER_INFO_META_KEY`, FastMCP does not stamp results in that era. Narrow that test's
    parametrize to `["auto"]`, and say so in the commit body.
    `test_initialize_names_kb_and_its_version` covers that era.
  - **No `initialize_result`.** If `client.initialize_result` is missing or `None`, stop and
    report the attribute FastMCP's `Client` uses for the handshake result. Do not weaken the
    assertion.

- [ ] **Step 3: Implement** the Interfaces block and the `server.py` change. If `FastMCP.__init__`
  in the installed release has no `version` parameter, stop and report its signature. Do not
  set the version by patching a private attribute.

- [ ] **Step 4: Edit the docs.** Make the HTTP-41 marker removal, the changelog line and the
  `builder.py` docstring sentence listed under Files.

- [ ] **Step 5: Run the whole suite**

  Run: `ruff check . && python scripts/generate_wiki.py --check && pytest`
  Expected: clean, every test PASSes, `test_info_is_drawn_from_pyproject` is unchanged, and
  `tests/test_wiki.py` is not skipped. The generator should report no change, since no tool,
  config field or endpoint moved.

- [ ] **Step 6: Commit** `fix: serverInfo reports kb's version, not FastMCP's (#47)`
