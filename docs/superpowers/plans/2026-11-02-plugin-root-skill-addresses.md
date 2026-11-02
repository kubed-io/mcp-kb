# Plugin-Root Citations of a Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `SKILL.md` or prompt body that cites its own plugin's skill as
`${CLAUDE_PLUGIN_ROOT}/skills/<skill>/…` renders that skill's address, which reads.

**Architecture:** `placeholders.substitute` learns one more input: a map from each served
skill's directory below the plugin root to its `skill://` address. Before the plain replace,
it rewrites `${CLAUDE_PLUGIN_ROOT}/<dir>` (longest `<dir>` first, at a path boundary) into the
skill's address. `Catalogue` builds the map for one plugin in one library and uses it for a
`SKILL.md` read. `PromptProvider` hands it to the prompt when `prompts/get` resolves one. What
is *served* does not change: every guard on the old address stays.

**Tech Stack:** Python ≥3.11, FastMCP, pydantic, pytest + pytest-asyncio, uvicorn.

**Spec:** this file's Design section; the requirements it adds are
[SKL-52](../specs/skills.md) and [PRM-61](../specs/prompts.md), both *(proposed)* until Task 4.
Brief and decisions: issue #28 (no separate design doc).

## Design

**The problem.** kb renders `${CLAUDE_PLUGIN_ROOT}` as `skill://<library>` (SKL-25, PRM-48). A
path under that which lands inside a skill directory is deliberately not served there (SKL-31,
SKL-32): that file's address is the skill's. So
`${CLAUDE_PLUGIN_ROOT}/skills/drawio/SKILL.md` renders `skill://drawio/skills/drawio/SKILL.md`,
which reads as nothing, while in Claude Code it is a real file. Official plugins still cite this
way (claude-plugins-official `math-proof`'s `skills/siege/SKILL.md`, the `claude-security`
agent; 7 `SKILL.md` files in that marketplace).

**Decided (Dr K, issue #28):**

- **Fix the rendering only.** No read-side hint for a model that builds
  `skill://<lib>/skills/<skill>/…` itself; that is its own change if real reads show it.
- **The guard stays.** `test_a_path_inside_a_skill_is_refused_at_the_library_base`,
  `test_a_sibling_skills_file_is_not_readable_through_this_skill` and
  `test_a_skipped_skills_files_are_not_readable_through_a_served_one` pass unchanged. The fix
  changes what is written, never what is served.

**The rule (SKL-52, PRM-61).** In a `SKILL.md` and a prompt body,
`${CLAUDE_PLUGIN_ROOT}/<dir><rest>`, where `<dir>` is the directory below the plugin root of a
served skill of the **same plugin in the same library**, renders `skill://<address><rest>`:

| Body says | Renders |
|---|---|
| `${CLAUDE_PLUGIN_ROOT}/skills/drawio/references/xml.md` | `skill://drawio/drawio/references/xml.md` |
| `${CLAUDE_PLUGIN_ROOT}/skills/drawio.` (end of a sentence) | `skill://drawio/drawio.` |
| `${CLAUDE_PLUGIN_ROOT}/skills/drawio.md`, `…/skills/drawio-x/y.md` | `skill://drawio/skills/drawio.md`, … (as today) |
| `${CLAUDE_PLUGIN_ROOT}/shared/x.md`, bare `${CLAUDE_PLUGIN_ROOT}` | `skill://drawio/shared/x.md`, `skill://drawio` (as today) |

- **Prefix match, not path parsing.** `<dir>` matches only when the next character is not one
  that continues a directory name: a letter, digit, `_`, `-`, `~`, `%`, `+`, `@`, or a `.`
  followed by one of those or by another `.`. The longest `<dir>` is tried first, so a nested
  skill wins.
- **Own plugin, own library only**, as in Claude Code. A plugin in two libraries gets each
  library's addresses. Another plugin's skill on a shared root stays as today. Within one plugin
  in one library every skill has the same category, labels and library categories, so the map
  under the requesting scope equals the map under `EVERYTHING`: the rewrite reveals nothing a
  client could not already list. The map is still built under the request's scope, because
  every `Catalogue` method decides about one.
- **Skipped skills are not mapped.** They have no address; their files read as nothing at every
  address, so the citation dangles as today.
- **A plugin root that is itself a skill** maps the empty directory: `${CLAUDE_PLUGIN_ROOT}/x`
  renders `skill://<address>/x`, which reads through the skill-level plugin-root fallback
  (SKL-30). Bare `${CLAUDE_PLUGIN_ROOT}` stays `skill://<library>`.
- **Not normalised:** `./`, `//` and `..` after the placeholder render as today.
- **Order (PRM-47) is unchanged:** dialect placeholders, then this server's (this rewrite, then
  the plain replace), then the gateway prefix. Map values carry no prefix, so it is written once.
- **Follows for free:** the Skills extension hashes what `read` returns (SKL-47), so its digests
  follow. AGT-9 *(proposed)* resolves agent instructions as a prompt body, so agents inherit
  this when they ship.

## Global Constraints

- **Toolchain** (CI's `test.yml`): `pip install -e ".[test]"`, then `ruff check .` and `pytest`
  from the repository root. `tests/test_wiki.py` needs the `wiki/` submodule checked out
  (`git submodule update --init`); it must run, not skip.
- **Python 3.11 is the floor.** No 3.12+ construct; no backslash inside an f-string
  expression. Lines are at most 88 columns.
- **`catalogue/` imports no FastMCP** (`tests/test_boundaries.py`).
- **A provider never stores a `Catalogue`.** Read it through `self._snapshot()` at call time.
- **The three guard tests above pass unchanged**; do not edit them.
- **Markers:** a test without a server is `@pytest.mark.unit`; `tests/test_plugin_root.py` is
  `integration` module-wide already.
- **Public repo:** the maintainer is Dr K; no names or real hostnames in code, tests or docs.
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A citation at the end of a sentence**, `…/skills/writing.`, is the skill, and
   `…/skills/writing.md` is not. → Task 1, `test_a_path_inside_a_skill_renders_its_address`.
2. **A plugin served by two libraries** renders each library's own address, never the other's.
   → Task 2, `test_plugin_skill_dirs_maps_one_plugin_in_one_library`.
3. **Behind a gateway** the prefix is written once (`kb+skill://…`, never `kb+kb+`). → Tasks 2
   and 3, the `_with_a_prefix` tests.
4. **A skill directory with regex metacharacters in its path** (`.claude/skills/x`) matches
   literally, and `Xclaude/skills/x` does not. → Task 1,
   `test_a_skill_directory_is_matched_literally`.
5. **Another plugin's skill on the same library** (`kit-extra`'s `skills/ops`) is not rewritten
   from `kit`'s body. → Task 2, `RENDERED` line F.

---

### Task 1: `substitute` renders a skill's address

**Files:**
- Modify: `kubed/mcp_kb/catalogue/placeholders.py`
- Test: `tests/test_placeholders.py`

**Interfaces:**
- Produces:
  `substitute(text: str, *, plugin_root: str, skill_dir: str | None = None, skills: Mapping[str, str] | None = None) -> str`.
  `skills` maps a skill's directory below the plugin root (posix, no leading or trailing `/`;
  `""` for the root itself) to its `skill://<address>`, unprefixed.

- [ ] **Step 1: Write the failing tests** in `tests/test_placeholders.py`, all `unit`:

```python
SKILLS = {"skills/writing": "skill://kit/writing"}


@pytest.mark.parametrize(
    ("cited", "rendered"),
    [
        ("${CLAUDE_PLUGIN_ROOT}/skills/writing/notes.md", "skill://kit/writing/notes.md"),
        ("${CLAUDE_PLUGIN_ROOT}/skills/writing/SKILL.md", "skill://kit/writing/SKILL.md"),
        ("(${CLAUDE_PLUGIN_ROOT}/skills/writing)", "(skill://kit/writing)"),
        ("`${CLAUDE_PLUGIN_ROOT}/skills/writing`", "`skill://kit/writing`"),
        ("see ${CLAUDE_PLUGIN_ROOT}/skills/writing.", "see skill://kit/writing."),
        ("${CLAUDE_PLUGIN_ROOT}/skills/writing.md", "skill://kit/skills/writing.md"),
        ("${CLAUDE_PLUGIN_ROOT}/skills/writing-x/y.md", "skill://kit/skills/writing-x/y.md"),
        ("${CLAUDE_PLUGIN_ROOT}/skills/writings/y.md", "skill://kit/skills/writings/y.md"),
        ("${CLAUDE_PLUGIN_ROOT}/./skills/writing/a.md", "skill://kit/./skills/writing/a.md"),
        ("${CLAUDE_PLUGIN_ROOT}/shared/x.md", "skill://kit/shared/x.md"),
        ("${CLAUDE_PLUGIN_ROOT}", "skill://kit"),
    ],
)
def test_a_path_inside_a_skill_renders_its_address(cited, rendered):
    assert (
        placeholders.substitute(cited, plugin_root="skill://kit", skills=SKILLS)
        == rendered
    )
```

  - `test_the_deepest_skill_wins`: with
    `{"skills/writing": "skill://kit/writing", "skills/writing/drafts": "skill://kit/elsewhere"}`
    *and* the same map in reverse insertion order, `…/skills/writing/drafts/d.md` →
    `skill://kit/elsewhere/d.md` and `…/skills/writing/a.md` → `skill://kit/writing/a.md`.
  - `test_a_plugin_root_that_is_a_skill_renders_below_its_address`: with
    `{"": "skill://lib/solo", "skills/inner": "skill://lib/inner"}` and
    `plugin_root="skill://lib"`: `${CLAUDE_PLUGIN_ROOT}/scripts/run.py` →
    `skill://lib/solo/scripts/run.py`; `${CLAUDE_PLUGIN_ROOT}/skills/inner/a.md` →
    `skill://lib/inner/a.md`; `${CLAUDE_PLUGIN_ROOT}` → `skill://lib`.
  - `test_a_skill_directory_is_matched_literally`: with `{".claude/skills/x": "skill://kit/x"}`:
    `${CLAUDE_PLUGIN_ROOT}/.claude/skills/x/a.md` → `skill://kit/x/a.md`;
    `${CLAUDE_PLUGIN_ROOT}/Xclaude/skills/x/a.md` → `skill://kit/Xclaude/skills/x/a.md`.
  - `test_every_citation_and_the_skill_dir_are_rendered`:
    `"${CLAUDE_PLUGIN_ROOT}/skills/writing/a.md ${CLAUDE_PLUGIN_ROOT}/skills/writing/b.md ${CLAUDE_SKILL_DIR}/c.md"`
    with `SKILLS` and `skill_dir="skill://kit/cite"` →
    `"skill://kit/writing/a.md skill://kit/writing/b.md skill://kit/cite/c.md"`.
  - `test_without_skills_the_plugin_root_renders_as_before`: `skills` omitted, `None` and `{}`
    all give `${CLAUDE_PLUGIN_ROOT}/skills/writing/a.md` → `skill://kit/skills/writing/a.md`.

- [ ] **Step 2: Run them to verify they fail**

  Run: `pytest tests/test_placeholders.py -v`
  Expected: the new tests FAIL with `TypeError: substitute() got an unexpected keyword argument 'skills'`; the four existing tests pass.

- [ ] **Step 3: Implement `skills` in `substitute`.** One regex built per call from the map:
  `re.escape(PLUGIN_ROOT)`, then `/` and the alternation of the escaped non-empty directories
  sorted by length descending, followed by the boundary lookahead
  `(?![\w~%+@-])(?!\.[\w.~%+@-])`; a `""` key adds a final alternative matching the
  placeholder followed by `(?=/)`. Replace with the mapped address (the `/` after the
  placeholder is kept for `""`), then run the existing plain replaces. Rewrite the module
  docstring's "Plain `str.replace`" paragraph: the plain replace still decides every other
  spelling; the one regex is anchored to directories the caller names, and why (a skill's files
  have one address, SKL-31).

- [ ] **Step 4: Run them to verify they pass**

  Run: `pytest tests/test_placeholders.py -v && ruff check .`
  Expected: all PASS, ruff clean.

- [ ] **Step 5: Commit** `fix: a plugin-root path inside a skill renders the skill's address`

### Task 2: A `SKILL.md` read renders its plugin's skills

**Files:**
- Modify: `kubed/mcp_kb/catalogue/uris.py` (`Catalogue.plugin_skill_dirs`, `Catalogue.read`,
  `Catalogue._skill_file`)
- Test: `tests/test_uris.py`, `tests/test_plugin_root.py`

**Interfaces:**
- Consumes: `placeholders.substitute(..., skills=)` (Task 1).
- Produces:
  `Catalogue.plugin_skill_dirs(self, library: str, plugin: str, scope: Scope = EVERYTHING) -> dict[str, str]`:
  every skill in `self._index.visible(scope)` with that `library` and `plugin`, keyed by
  `skill.path` relative to `skill.root` (try `skill.root`, then `skill.root.resolve()`, as
  `snapshot._relative` does; `""` when equal; skip a skill under neither), valued
  `f"{SCHEME}{skill.address}"`.
- Changes: `_skill_file(self, skill: Skill, file: str, scope: Scope)`; `read` passes its
  `scope`. The `SKILL.md` substitution passes
  `skills=self.plugin_skill_dirs(skill.library, skill.plugin, scope)`.

- [ ] **Step 1: Write the failing unit test** in `tests/test_uris.py`, beside `_skill`:

  `test_plugin_skill_dirs_maps_one_plugin_in_one_library` builds `Skill`s directly
  (`root=Path("/r")`, `path=Path("/r") / <dir>`, `folder` and `name` as the address needs):
  library `a` plugin `p` at `skills/writing` (`writing`) and `skills/writing/drafts`
  (folder `writing`, `drafts`); library `a` plugin `q` at `skills/ops`; library `b` plugin `p`
  at `skills/writing`; library `c` plugin `solo` at the root itself (`path=root=Path("/s")`,
  name `solo`). Give every skill `tags={"t"}`. Assert:

```python
assert cat.plugin_skill_dirs("a", "p") == {
    "skills/writing": "skill://a/writing",
    "skills/writing/drafts": "skill://a/writing/drafts",
}
assert cat.plugin_skill_dirs("b", "p") == {"skills/writing": "skill://b/writing"}
assert cat.plugin_skill_dirs("c", "solo") == {"": "skill://c/solo"}
assert cat.plugin_skill_dirs("a", "nobody") == {}
assert cat.plugin_skill_dirs("a", "p", _tags({"other"})) == {}
```

- [ ] **Step 2: Write the failing integration tests** in `tests/test_plugin_root.py`.

  Extend `_build`'s `kit` tree (the existing files stay as they are):
  - `skills/writing/drafts/SKILL.md` (`name: drafts`, `description: Drafts.`) and
    `skills/writing/drafts/d.md` = `"drafts d\n"`;
  - `skills/cite/SKILL.md` = `"---\nname: cite\ndescription: Cite.\n---\n\n" + CITATIONS`.

  Module constants, shared with Task 3:

```python
CITATIONS = (
    "A ${CLAUDE_PLUGIN_ROOT}/skills/writing/notes.md\n"
    "B ${CLAUDE_PLUGIN_ROOT}/skills/writing/drafts/d.md\n"
    "C ${CLAUDE_PLUGIN_ROOT}/skills/writing.md\n"
    "D ${CLAUDE_PLUGIN_ROOT}/skills/Upper/leak.md\n"
    "E ${CLAUDE_PLUGIN_ROOT}/shared/x.md\n"
    "F ${CLAUDE_PLUGIN_ROOT}/skills/ops/SKILL.md\n"
)
RENDERED = (
    "A skill://kit/writing/notes.md\n"
    "B skill://kit/writing/drafts/d.md\n"
    "C skill://kit/skills/writing.md\n"
    "D skill://kit/skills/Upper/leak.md\n"
    "E skill://kit/shared/x.md\n"
    "F skill://kit/skills/ops/SKILL.md\n"
)
```

  Give `_client` a `prefix=None` keyword that sends `Kb-Resource-Prefix`, and pass it through
  `_read`. Then:
  - `test_a_skill_citing_its_plugins_skills_through_the_root_reads_them`:
    `RENDERED in await _read(url, "skill://kit/cite/SKILL.md")`, the same under `tags="core"`
    and through `_tool`; `skill://kit/writing/notes.md` reads `"skill notes\n"`,
    `skill://kit/writing/drafts/d.md` reads `"drafts d\n"`, and
    `await _missing(url, "skill://kit/skills/Upper/leak.md")`.
  - `test_a_skills_rendered_citation_with_a_prefix`: with `prefix="kb+"`, the body of
    `skill://kit/cite/SKILL.md` contains `"A kb+skill://kit/writing/notes.md\n"` and not
    `"kb+kb+"`.

- [ ] **Step 3: Run them to verify they fail**

  Run: `pytest tests/test_uris.py tests/test_plugin_root.py -v`
  Expected: the new tests FAIL (`AttributeError: … 'plugin_skill_dirs'`; `RENDERED` not in the
  body). Every existing test in both files still PASSES.

- [ ] **Step 4: Implement** `plugin_skill_dirs` and the `_skill_file` change. Update
  `_skill_file`'s comment and `_manifest_json`'s docstring sentence on the substitution so they
  name the skill-directory rewrite.

- [ ] **Step 5: Run the suite**

  Run: `pytest tests/test_uris.py tests/test_plugin_root.py tests/test_skills_extension.py tests/test_address_space.py tests/test_addressing_http.py tests/test_boundaries.py -v && ruff check .`
  Expected: all PASS, including the three guard tests, unedited.

- [ ] **Step 6: Commit** `fix: a skill citing its plugin's skills through the root reads them`

### Task 3: A rendered prompt renders its plugin's skills

**Files:**
- Modify: `kubed/mcp_kb/catalogue/prompts/__init__.py` (`FilePrompt.render`)
- Modify: `kubed/mcp_kb/mcp/prompts.py` (`MCPFilePrompt`, `PromptProvider._get_prompt`)
- Test: `tests/test_placeholders.py`, `tests/test_plugin_root.py`

**Interfaces:**
- Consumes: `substitute(..., skills=)` (Task 1);
  `Catalogue.plugin_skill_dirs(library, plugin, scope)` (Task 2); `CITATIONS`, `RENDERED`,
  `_client(url, tags=None, prefix=None)` (Task 2).
- Produces:
  - `FilePrompt.render(self, arguments=None, *, plugin_root: str | None = None, skills: Mapping[str, str] | None = None) -> str`,
    passing `skills` to `substitute` only where it already passes `plugin_root`.
  - `MCPFilePrompt.skill_dirs: dict[str, str]` (pydantic field, default empty), passed by
    `_filled` as `skills=self.skill_dirs`.
  - `PromptProvider._get_prompt`: after `super()._get_prompt`, take `snapshot = self._snapshot()`
    once, revalidate through it as now, and return
    `prompt.model_copy(update={"skill_dirs": snapshot.catalogue.plugin_skill_dirs(prompt.file.library, prompt.file.plugin, requested_scope())})`.
    The listing is unchanged.

- [ ] **Step 1: Write the failing tests**
  - `tests/test_placeholders.py`,
    `test_rendering_resolves_a_skill_path_in_every_dialect` (parametrized over `DIALECTS`, as
    the existing render test): body `Read ${CLAUDE_PLUGIN_ROOT}/skills/w/a.md.`;
    `render(plugin_root="skill://lib", skills={"skills/w": "skill://lib/w"})` →
    `"Read skill://lib/w/a.md."`; `render(plugin_root="skill://lib")` →
    `"Read skill://lib/skills/w/a.md."`.
  - `tests/test_plugin_root.py`: add `commands/cite.md` to `kit` =
    `"---\ndescription: Cite.\n---\n" + CITATIONS` (served as `kit_cite`).
    - `test_a_prompt_citing_its_plugins_skills_renders_their_addresses`: the text of
      `client.get_prompt("kit_cite")`'s first message contains `RENDERED`; so does the text of
      `client.call_tool("get_prompt", {"name": "kit_cite"})`.
    - `test_a_prompts_rendered_citation_with_a_prefix`: with `prefix="kb+"` the prompt text
      contains `"A kb+skill://kit/writing/notes.md\n"` and not `"kb+kb+"`.

- [ ] **Step 2: Run them to verify they fail**

  Run: `pytest tests/test_placeholders.py tests/test_plugin_root.py -v`
  Expected: the new tests FAIL (`unexpected keyword argument 'skills'`; `RENDERED` not in the
  prompt text).

- [ ] **Step 3: Implement** the three changes above. Update `MCPFilePrompt`'s docstring sentence
  on `${CLAUDE_PLUGIN_ROOT}`, and `FilePrompt.render`'s on `plugin_root`.

- [ ] **Step 4: Run the whole suite**

  Run: `ruff check . && pytest`
  Expected: clean, all PASS, `tests/test_wiki.py` not skipped.

- [ ] **Step 5: Commit** `fix: a prompt citing its plugin's skills through the root renders their addresses`

### Task 4: Spec, wiki and changelog

**Files:**
- Modify: `docs/superpowers/specs/skills.md`: drop `*(proposed; narrows SKL-25)*` from SKL-52;
  SKL-25 opens "In a skill's `SKILL.md`, `${CLAUDE_PLUGIN_ROOT}` reads as `skill://<library>`
  except as SKL-52 says, and …".
- Modify: `docs/superpowers/specs/prompts.md`: drop `*(proposed; narrows PRM-48)*` from PRM-61;
  PRM-48 gains "except as PRM-61 says".
- Modify (submodule `wiki/`):
  - `Skills.md`, "`${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_SKILL_DIR}` in a body": one paragraph
    with the drawio example from the Design table, and that the deepest skill wins.
  - `Plugins.md`, "The plugin root": a table row or sentence for
    `${CLAUDE_PLUGIN_ROOT}/<skill dir>/…` → `skill://<library>/<folder>/<name>/…`, own plugin.
  - `Prompts.md`, "Placeholders this server resolves" (table ~l.159, prose l.162): the same.
- Modify: `CHANGELOG.md` `[Unreleased]`, `### Fixed`, one line:
  `- A command or skill citing its own skill through \`${CLAUDE_PLUGIN_ROOT}/skills/<skill>/…\` now renders an address that reads.`

- [ ] **Step 1: Write the docs.** Copy addresses from the tests; example names only.
- [ ] **Step 2: Verify**

  Run: `python scripts/generate_wiki.py --check && pytest tests/test_wiki.py -v && ruff check . && pytest`
  Expected: pass, no skips.

- [ ] **Step 3: Commit the wiki first, inside `wiki/`, without pushing.** Then commit the
  superproject with the spec, the changelog and the submodule pointer. The controller pushes.
  Commit: `docs: a plugin-root citation of a skill renders the skill's address`
