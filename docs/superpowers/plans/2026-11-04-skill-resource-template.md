# A Resource Template for `skill://` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `resources/templates/list` tells a client that this server serves the `skill://`
address space, so a client with several servers can pick the one to read an address from.

**Architecture:** `CatalogueProvider` already serves every `skill://` resource. It gains two
FastMCP `Provider` hooks. `_list_resource_templates` returns one fixed `SkillTemplate`, built per
request so its description carries the request's prefix. `_get_resource_template` always returns
None, so no read ever resolves through the template. Nothing in `catalogue/` changes.

**Tech Stack:** Python ≥3.11, FastMCP 4 (`fastmcp>=4.0.0,<5`), pytest + pytest-asyncio, uvicorn.

**Spec:** this file's Design section, and [SKL-53](../specs/skills.md), *(proposed)* until
Task 2. The brief is gap 3 of issue #38, and its decisions are on #49. There is no separate
design doc.

## Design

**The problem.** The `skill://` space is open-ended: an address is readable without being listed
(SKL-8, SKL-21). But `resources/templates/list` is empty, so a client can only learn which
connected server serves `skill://<library>/…` from the index rows in `resources/list` or by
trying reads. Neither core MCP nor the Skills extension requires a template, so this is an
optional gap, not a violation.

**Decided (#38, #49):** one fixed row, the request's prefix as SKL-41 says, discovery only, no
mirror tool.

**The row (SKL-53).**

| Field | Value |
|---|---|
| `uriTemplate` | `skill://{library}/{+path}` (RFC 6570; `+` lets `path` hold `/`) |
| `name` | `skill` |
| `description` | `A skill, index or file this server serves: {library} is a library's name and {path} a path below it. Start at skill://{library}/_index.md; resources/list names the libraries.` |
| `mimeType` | absent |

- **The prefix goes on the description and never on the `uriTemplate`.** `uriTemplate` is a
  structured field, like a listing row's `uri` (SKL-41). agentgateway v1.6.0 rewrites it itself:
  `merge_resource_templates` passes each `uri_template` through `resource_uri`, which writes
  `<target>+<uri>`. If kb also prefixed it, the client would get `kb+kb+skill://…`. The
  description is text, so `requested_addressing().text()` prefixes it, exactly as it prefixes
  listing descriptions.
- **No `mimeType`.** MCP says to give one only when every match has the same type, and the
  matches here don't: `text/markdown`, `application/json` for a `_manifest`, and a library file's
  guessed type (SKL-23). FastMCP's `ResourceTemplate.mime_type` defaults to `text/plain` and a
  validator replaces an empty one with it, so `SkillTemplate` drops it in `to_mcp_template`.
- **Discovery only, and this has to be enforced.** In FastMCP 4, `FastMCP.read_resource` falls
  back to `get_resource_template(uri)` and then `template._read(uri, params)` whenever
  `_get_resource` returns None. The default `Provider._get_resource_template` matches every listed
  template. A template that matched would turn every miss into a template read, which breaks
  `NameTheFileToRead`'s hints and SCP-24 (an out-of-scope read fails exactly as an absent one).
  Today the default would happen not to match: FastMCP's `build_regex` turns `{+path}` into an
  invalid group name, swallows the `re.error` and matches nothing. That is an accident, not a
  contract, so `CatalogueProvider._get_resource_template` returns None outright.
- **The same under every scope.** The row names no library, so it confirms nothing about any
  library, and absent and out-of-scope stay indistinguishable. A scope that names nothing is
  refused by `RefuseEmptyScope.on_request`, as every request is (SCP-29). An empty catalogue
  still lists the row.
- **Listed in tools mode too.** `?resources=off` hides nothing from `resources/templates/list`.
  `list_resources` keeps returning `resources/list`'s rows only (TOOL-8), and no tool is added.
- **Follows for free:** `ttlMs` and `cacheScope` on `resources/templates/list` (HTTP-29) come from
  the `FastMCP(cache_ttl=…, cache_scope=…)` that `server.py` already builds.
- **Not in this change:** `resources/directory/read` (SKL-51, a FastMCP limit).

## Global Constraints

- **Toolchain** (CI's `test.yml`): `pip install -e ".[test]"`, then `ruff check .` and `pytest`
  from the repository root. Check out the `wiki/` submodule (`git submodule update --init`), so
  `tests/test_wiki.py` runs rather than skips.
- **Python 3.11 is the floor.** No 3.12+ construct; no backslash inside an f-string
  expression. Lines are at most 88 columns.
- **`catalogue/` and `plugins/` import no FastMCP** (`tests/test_boundaries.py`). The template
  lives in `mcp/resources.py`.
- **A provider never stores a `Catalogue`.** The template reads nothing from one, and the
  provider keeps its getter.
- **These guard tests pass unchanged; do not edit them:**
  `test_a_missing_address_names_no_file`,
  `test_a_directory_is_not_found_and_names_the_file_to_read` and
  `test_an_out_of_scope_directory_reads_as_a_missing_one` (`tests/test_address_space.py`);
  `test_directory_hint_is_translated` (`tests/test_addressing_http.py`).
- **Markers:** `tests/test_address_space.py` is `integration` module-wide. A new test elsewhere
  with no server is `@pytest.mark.unit`; one with a server is `@pytest.mark.integration`.
- **Public repo:** the maintainer is Dr K; no names or real hostnames in code, tests or docs.
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A miss still reads as a miss.** A URI the template's shape covers
   (`skill://grafana/nope/deep/x.md`) fails with `not found` and names no file, as before. →
   Task 1, `test_a_read_never_resolves_through_the_template`, and the guard tests.
2. **Behind a gateway, the prefix is written once.** The description reads
   `kb+skill://{library}/_index.md`, and the `uriTemplate` stays `skill://{library}/{+path}`. →
   Task 1, `test_the_template_description_follows_the_prefix`.
3. **A scoped client learns nothing from the row.** It is identical under `Kb-Library` and
   `Kb-Tag` scopes, and a refused scope fails with the refusal message. → Task 1,
   `test_the_template_is_the_same_under_every_scope` and
   `test_a_refused_scope_refuses_the_template_listing`.
4. **No `text/plain` leaks out of FastMCP's default.** → Task 1,
   `test_one_template_names_the_address_space` asserts `mimeType is None`.
5. **A tools-mode client lists no new tool.** `tools/list` with `X-MCP-Resources: off` still has
   exactly `list_resources` and `read_resource`. → Task 1,
   `test_the_template_adds_no_tool`.

---

### Task 1: `CatalogueProvider` lists the template and never reads through it

**Files:**
- Modify: `kubed/mcp_kb/mcp/resources.py`: add `SkillTemplate`, `TEMPLATE_URI`,
  `TEMPLATE_DESCRIPTION`, and `CatalogueProvider._list_resource_templates` and
  `_get_resource_template`. Extend the module docstring's last paragraph by a sentence: the
  template is how a client learns the space exists, and it is never matched.
- Test: `tests/test_address_space.py`, `tests/test_addressing_http.py`

**Interfaces:**
- Produces, in `kubed/mcp_kb/mcp/resources.py`:
  - `TEMPLATE_URI: str = "skill://{library}/{+path}"`
  - `TEMPLATE_DESCRIPTION: str`, the canonical (unprefixed) description from the Design table,
    verbatim.
  - `class SkillTemplate(ResourceTemplate)` (`from fastmcp.resources.template import
    ResourceTemplate`). It overrides `to_mcp_template(self, **overrides)` to return
    `super().to_mcp_template(**{"mimeType": None, **overrides})`.
  - `CatalogueProvider._list_resource_templates(self) -> Sequence[ResourceTemplate]`:
    `[SkillTemplate(uri_template=TEMPLATE_URI, name="skill",
    description=requested_addressing().text(TEMPLATE_DESCRIPTION), parameters={...})]`, built on
    every call. `parameters` is a JSON schema object with string properties `library` and `path`,
    both required.
  - `CatalogueProvider._get_resource_template(self, uri: str, version: VersionSpec | None = None)
    -> ResourceTemplate | None`: returns None. Its docstring says why: FastMCP's miss fallback.

- [ ] **Step 1: Write the failing tests** in `tests/test_address_space.py` (module-level
  `integration` already; uses the module's `url` fixture and `_client`, `_read_error` helpers):

```python
from kubed.mcp_kb.mcp.resources import CatalogueProvider

TEMPLATE = (
    "skill://{library}/{+path}",
    "skill",
    "A skill, index or file this server serves: {library} is a library's name"
    " and {path} a path below it. Start at skill://{library}/_index.md;"
    " resources/list names the libraries.",
    None,
)


async def _templates(url, library=None, tags=None):
    async with _client(url, library=library, tags=tags) as client:
        return [
            (t.uriTemplate, t.name, t.description, t.mimeType)
            for t in await client.list_resource_templates()
        ]


async def test_one_template_names_the_address_space(url):
    assert await _templates(url) == [TEMPLATE]


async def test_the_template_is_the_same_under_every_scope(url):
    assert await _templates(url, library="other") == [TEMPLATE]
    assert await _templates(url, library="handbook") == [TEMPLATE]
    assert await _templates(url, tags="extra") == [TEMPLATE]


async def test_a_refused_scope_refuses_the_template_listing(url):
    with pytest.raises(Exception, match="no such library"):
        await _templates(url, library="nope")


async def test_a_read_never_resolves_through_the_template(url):
    error = await _read_error(url, "skill://grafana/nope/deep/x.md")
    assert "not found" in error and "_index.md" not in error
    provider = CatalogueProvider(lambda: None)
    assert await provider._get_resource_template("skill://grafana/nope/x.md") is None
    assert await provider._get_resource_template(TEMPLATE[0]) is None


async def test_the_template_adds_no_tool(url):
    async with Client(
        StreamableHttpTransport(url, headers={"X-MCP-Resources": "off"})
    ) as client:
        names = {t.name for t in await client.list_tools()}
        templates = await client.list_resource_templates()
    assert names == {"list_resources", "read_resource"}
    assert [t.uriTemplate for t in templates] == [TEMPLATE[0]]
```

  And in `tests/test_addressing_http.py` (its `server_url` fixture and `_client`, with `PREFIX`
  and `BOTH`):

```python
@pytest.mark.integration
async def test_the_template_description_follows_the_prefix(server_url):
    for headers in (PREFIX, BOTH):
        async with _client(server_url, headers) as client:
            (template,) = await client.list_resource_templates()
        assert template.uriTemplate == "skill://{library}/{+path}"
        assert "Start at kb+skill://{library}/_index.md;" in template.description
        assert "kb+kb+" not in template.description
    async with _client(server_url) as client:
        (plain,) = await client.list_resource_templates()
    assert "Start at skill://{library}/_index.md;" in plain.description
```

- [ ] **Step 2: Run them to verify they fail**

  Run: `pytest tests/test_address_space.py tests/test_addressing_http.py -v -k "template"`
  Expected: the listing tests FAIL (`[] != [TEMPLATE]`, or no template to unpack).
  `test_a_read_never_resolves_through_the_template` may already pass its read assertion. Its
  provider assertions pass by FastMCP's default only because `{+path}` fails to compile, and
  `TEMPLATE[0]` is listed by nobody yet. It is a guard, and it must stay green after Step 3.

- [ ] **Step 3: Implement** the Interfaces above in `kubed/mcp_kb/mcp/resources.py`. If
  `fastmcp.resources.template.ResourceTemplate` rejects `uri_template="skill://{library}/{+path}"`
  at construction in the installed FastMCP, stop and report the error text. Do not change the
  template's shape to fit: `{+path}` is what a standard RFC 6570 client expands with `/` intact.
  The same goes if the listing does not pass through `to_mcp_template` and `mimeType` comes back
  `text/plain`: report where FastMCP builds the wire row.

- [ ] **Step 4: Run the whole suite**

  Run: `ruff check . && pytest`
  Expected: clean, all PASS, the four guard tests unchanged, `tests/test_wiki.py` not skipped.

- [ ] **Step 5: Commit** `feat: declare a resource template for the skill:// address space`

### Task 2: Spec, AGENTS.md, wiki and changelog

**Files:**
- Modify: `docs/superpowers/specs/skills.md`:
  - drop `*(proposed)* ` from SKL-53;
  - in SKL-41's table, append "the template's description" to the first row's list (the
    "yes" row that starts "resource bodies"), and "the template's `uriTemplate`" to the
    "never" row's list.
- Modify: `AGENTS.md`, "The surface, and why the tools are a mirror", after the progressive
  disclosure table and its paragraph: one paragraph. `resources/templates/list` holds one fixed
  row, `skill://{library}/{+path}`, for discovery. `CatalogueProvider._get_resource_template`
  returns None because FastMCP falls back to a matching template on every read miss, and one that
  matched would turn a miss, and its hint, into a template read. The `uriTemplate` is never
  prefixed, because a gateway prefixes it itself.
- Modify (submodule `wiki/`): `Skills.md`, "Directories serve nothing", one paragraph after the
  one ending "the only way a caller learns what to read next". `resources/templates/list` answers
  `skill://{library}/{+path}`, so a client with several servers knows which one serves
  `skill://` addresses. It reads nothing itself; start at a library's `_index.md`. Behind a
  gateway, the gateway prefixes the template and kb prefixes the description.
- Modify: `CHANGELOG.md` `[Unreleased]`, `### Added`, last line:
  `- A client can tell kb serves \`skill://\` addresses from \`resources/templates/list\`.`

- [ ] **Step 1: Write the docs.** Copy the template and the description from Task 1's
  `TEMPLATE`. Use example names only.
- [ ] **Step 2: Verify**

  Run: `python scripts/generate_wiki.py --check && pytest tests/test_wiki.py -v && ruff check . && pytest`
  Expected: pass, no skips. Nothing the generator owns changes: `Tools.md` lists tools, and no
  tool changed.

- [ ] **Step 3: Commit the wiki first, inside `wiki/`, without pushing.** Then commit the
  superproject with the spec, `AGENTS.md`, the changelog and the submodule pointer. The
  controller pushes.
  Commit: `docs: the skill:// resource template`
