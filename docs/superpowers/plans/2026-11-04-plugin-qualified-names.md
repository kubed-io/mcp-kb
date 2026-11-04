# Plugin-Qualified Skill Names Implementation Plan

> **History.** Shipped in #54 (628aeb5), into `issue-38`, then to `main` in #62. What it asked
> for now lives in the living spec: [skills](../specs/skills.md) (SKL-54–55, SKL-41 reworded),
> [prompts](../specs/prompts.md) (PRM-62, PRM-47 reworded), [agents](../specs/agents.md) (AGT-17,
> AGT-9 reworded).
> **Overtaken:**
> - *What a name is*: `{`, `$` and `#` are on the list of characters a name may not follow, too,
>   so `${input:topic}` and `#tool:x` stay placeholders (SKL-54). The review on #54 added them.
> - *How it resolves*, "Commands are not rewritten": a command's name is served as written only
>   when no in-scope skill shares it. A skill and a command of one name read as the skill, as in
>   Claude Code (SKL-55), and the fixture pins `/kit:cite`.
> - Task 1's `split_frontmatter` takes any delimiter line python-frontmatter does (three or more
>   `-` and trailing blanks), not only `---`.
> - "fenced code included" had no test until #62 added `test_a_name_in_fenced_code_is_rewritten_alike`.
> - Deferred, not yet filed: the name table is rebuilt on every `SKILL.md`, prompt and agent read
>   (about 3 ms a read on a 1000-skill library), and no test covers a prompt whose plugin is empty.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `<plugin>:<skill>` name in served text reads as the skill's `skill://` address, and
an agent's frontmatter `skills:` comes with a resolved map, so a client reading kb over MCP finds
the skill on the first call, not after an `Unknown skill`.

**Architecture:** A new pure module, `catalogue/names.py`, recognises a qualified name and
rewrites it through a `QualifiedNames` table. `Catalogue.qualified_names(library, plugin, scope)`
builds that table from the skills the caller can see. Four places use it: `_skill_file` for a
`SKILL.md` body, `agent_definition` for an agent's `instructions` and its `_meta`, and
`FilePrompt.render` for a prompt body. Nothing in `sources/`, `plugins/` or the harvest changes.

**Tech Stack:** Python ≥3.11, FastMCP 4 (`fastmcp>=4.0.0,<5`), pytest + pytest-asyncio, uvicorn.

**Spec:** this file's Design section, and SKL-54, SKL-55, PRM-62 and AGT-17 in
[skills.md](../specs/skills.md), [prompts.md](../specs/prompts.md) and
[agents.md](../specs/agents.md). The brief is gap 1 of issue #38. Its decision is
on #50 and in #38's notes. There is no separate design doc.

## Design

**The problem.** kb resolves `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_SKILL_DIR}` to addresses
(SKL-25, SKL-52, PRM-48). It leaves a plugin-qualified name such as `drawio:drawio` as written,
and over MCP that name points at nothing. drawio's `agents/diagrammer.md` says to load the skill
"with the Skill tool (`drawio:drawio`)". A subagent that got that text through `agents/get` called
the Skill tool, got `Unknown skill`, and only then found `skill://drawio/drawio/SKILL.md`. It loses
that call on every run.

**Decided (#50, #38): approach (c).** A client can't register kb's skills with its Skill tool,
and the mod's API has nothing for that. A kb agent reaches a skill only by its `skill://` address.
So:

- kb rewrites a resolved name to an **address**, never to another name. Claude Code's built-in
  MCP-skills client, still disabled in 2.1.317, would pick its own per-server names, and any name
  kb picked could be wrong for it.
- An agent's frontmatter `skills:` stays verbatim (AGT-9). kb adds a resolved map beside it, in
  `_meta`.

**What a name is (SKL-54).** In Claude Code, a plugin's skill is `<plugin>:<skill>`, and a slash
invokes it: `/<plugin>:<skill>`. The plugin segment is the plugin's `name`, and the skill segment
is its frontmatter `name`, else its directory's name. A command in a subfolder adds a segment:
`commands/db/migrate.md` is `/<plugin>:db:migrate`.

- `<plugin>` matches PLG-1's pattern, `[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?`. `<skill>` is
  `[a-z0-9][a-z0-9-]*`, and a lookup then needs it to equal a served skill's name exactly.
- A name stands alone or it is not one. Before it (before its `/` when it has one) there is no
  letter, digit, or any of `_ . / : @ + ~ % -`. After it there is no letter, digit, any of
  `_ : / ~ % + @ -`, and no `.` followed by one of those. So:
  - `https://drawio:drawio`, `a/drawio:drawio` and `kb+drawio:drawio` are not names;
  - neither are `drawio:drawio.md`, `drawio:drawio/x` and `drawio:drawio:x`;
  - a sentence ending in `drawio:drawio.` is one.
- The pattern runs over the whole body, fenced code included, as the placeholder rewrite does. A
  match that resolves to nothing is put back unchanged, so a false match costs nothing: it is
  rewritten only when its first segment is the name of a plugin in that library *and* its second
  is a skill which that plugin serves to the caller.

**How it resolves (SKL-55).**

- **The candidates.** These are the plugins that serve in the text's own library and whose `name`
  equals `<plugin>`. The text's own plugin comes first, then the library's plugins in library order
  (LIB-4). A plugin's `name` is kb's: a marketplace entry's name, or the `name` a declared plugin
  has in the config. `plugin.json`'s own `name` is not read, so a declared plugin answers to its
  config name. A plugin that LIB-28 fails in the library serves no skills there, so it is never a
  candidate.
- **The answer.** It comes from the first candidate that serves an in-scope skill named `<skill>`:
  `skill://<address>/SKILL.md`, with the `/` dropped. If that candidate serves two such skills, in
  different folders (SKL-11), the name is ambiguous and stays as written. kb never guesses.
- **Scope.** Resolution sees only what the caller's scope admits. An out-of-scope target is left
  as written, exactly as an absent one is (SKL-35), so the rewrite confirms nothing the caller
  could not list.
- **Commands are not rewritten.** A command has no address, and the decision rules out rewriting
  to names. A gateway renames prompts anyway, so a `<library>_<name>` written into text could be
  wrong behind one. `/<plugin>:<command>` and `/<plugin>:a:b` therefore stay as written.
- **Bare names are not rewritten in text.** penpot's skills say "use penpot-build-screen". In
  prose a bare word is too ambiguous to touch. The `_meta` map below is the one place where a bare
  name resolves.

**Where it applies.**

| Text | What is rewritten | Rule |
|---|---|---|
| A skill's `SKILL.md` | The body after the frontmatter block. The frontmatter is served as written, so `skills/list`'s `frontmatter` and conformance (SKL-45) can't change | SKL-55 |
| A prompt body, every dialect | The body as written, *before* the dialect's placeholders, so an argument's value is never rewritten | PRM-62 |
| An agent's `instructions` | The body | AGT-17 |
| An agent's `_meta["io.kubed.mcp-kb/agent"]["skills"]` | A new key: frontmatter `skills` resolved | AGT-17 |

- **The order of the steps.** The name rewrite runs first, on the text as written. Placeholders
  come next (SKL-25, SKL-52, PRM-48), and the gateway prefix last (SKL-41), so a rewritten address
  is prefixed once, `kb+skill://…`. The first two steps never overlap: a rewritten name holds no
  `${`, and a resolved placeholder holds no qualified name.
- **Every other file** is still served as on disk. `_manifest` hashes disk bytes (SKL-24), and the
  Skills extension's digests follow the served bytes (SKL-47) because they are computed through
  `Catalogue.read`.
- **The `_meta` map.** `skills` maps each entry of the agent's frontmatter `skills` to the
  `SKILL.md` address it resolves to. The frontmatter value is either a list of strings or one
  string of comma-separated names, and each entry is trimmed. The map keeps the entry as written as
  its key.
  - An entry that is a qualified name resolves by SKL-55.
  - A bare `<skill>` resolves to the agent's own plugin's in-scope skill of that name, when there
    is exactly one.
  - An entry that doesn't resolve is left out, and the key is `{}` when none do.
  - The map values are never prefixed. They are structured URIs, like a listing row's `uri`
    (SKL-41), and an incoming address may carry the prefix or not (SKL-42).

**Who uses these names.** I checked against the libraries in `examples/config.yaml` and the
running catalogue:

- **superpowers** cites `superpowers:<skill>` throughout its `SKILL.md` bodies, e.g.
  `superpowers:subagent-driven-development` in writing-plans. It is the largest beneficiary.
- **drawio**: `agents/diagrammer.md` has `drawio:drawio`.
- **penpot** uses bare names, which stay as they are.
- **grafana and n8n** weren't searched. The rule needs no list, so a survey changes nothing about
  the design.

**Limits.**

- A client with the plugin installed natively reads the files from disk, so the rewrite doesn't
  reach it, and it doesn't need to: there, the names resolve.
- Prompts matter less to the mod, whose agents run with prompts off, but they still matter in
  main sessions.

## Global Constraints

- **Toolchain** (CI's `test.yml`): `pip install -e ".[test]"`, then `ruff check .` and `pytest`
  from the repository root. Check out the `wiki/` submodule (`git submodule update --init`), so
  that `tests/test_wiki.py` runs rather than skips.
- **Python 3.11 is the floor.** No 3.12+ construct; no backslash inside an f-string
  expression. Lines are at most 88 columns.
- **`catalogue/` and `plugins/` import no FastMCP** (`tests/test_boundaries.py`). `names.py`
  imports only the standard library.
- **A provider never stores a `Catalogue`.** The prompt provider builds the table from the
  snapshot it already holds in `_get_prompt`, beside `skill_dirs`.
- **Absent and out-of-scope stay indistinguishable.** A table is built from
  `self._index.visible(scope)` and from nothing else.
- **These pass unchanged; do not edit them:** `tests/test_plugin_root.py` (its `CITATIONS`
  contain no qualified name), `tests/test_placeholders.py`, and `tests/test_skills_extension.py`.
- **Markers:** a test with no server is `@pytest.mark.unit`, one with a server
  `@pytest.mark.integration`.
- **Public repo:** the maintainer is Dr K; no names or real hostnames in code, tests or docs.
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A name in a URL or a path is never rewritten.** `https://kit:writing`, `a/kit:writing`,
   `kit:writing.md` and `kit:writing/x` stay as written, even though `kit:writing` resolves. →
   Task 1, `test_a_name_inside_a_longer_token_is_left_alone`.
2. **A scoped client learns nothing from the rewrite.** Under a scope that excludes
   `kit-extra`, `kit-extra:ops` stays as written in `kit`'s own skill. Without a scope, it reads as
   an address. → Task 2, `test_an_out_of_scope_skill_is_left_as_written`.
3. **Behind a gateway, the prefix is written once.** A rewritten name reads
   `kb+skill://kit/writing/SKILL.md`, never `kb+kb+`. → Task 2,
   `test_a_rewritten_name_takes_the_prefix_once`.
4. **The Skills extension's digest still matches the bytes read.** → Task 2,
   `test_the_extension_digest_follows_the_rewrite`.
5. **A person's argument is not rewritten.** A prompt rendered with the argument value
   `kit:writing` shows `kit:writing`, while the same text in its body is rewritten. → Task 3,
   `test_an_argument_value_is_never_rewritten`.

---

### Task 1: `catalogue/names.py`, the grammar and the table

**Files:**
- Create: `kubed/mcp_kb/catalogue/names.py`
- Test: `tests/test_names.py` (`pytestmark = pytest.mark.unit`)

**Interfaces:**
- Produces, in `kubed/mcp_kb/catalogue/names.py`:
  - `QUALIFIED: re.Pattern[str]`: the module docstring quotes SKL-54. Groups are `slash`,
    `plugin` and `skill`. The lookbehind sits before the optional `/`, and the trailing lookaheads
    are `(?![\w~%+@:/-])(?!\.[\w~%+@-])`.
  - `@dataclass(frozen=True) class QualifiedNames` with one field,
    `plugins: tuple[tuple[str, Mapping[str, tuple[str, ...]]], ...] = ()`. Each item is a plugin
    name, and a map from each skill name it serves in scope to the unprefixed `SKILL.md` URIs of
    those skills. `plugins[0]` is the text's own plugin, then the rest in library order. The
    default, empty table rewrites nothing.
  - `QualifiedNames.address(self, plugin: str, skill: str) -> str | None`: SKL-55's answer.
  - `QualifiedNames.rewrite(self, text: str) -> str`: `QUALIFIED.sub` that puts an unresolved
    match back exactly as it was matched.
  - `QualifiedNames.preload(self, skills: object) -> dict[str, str]`: AGT-17's map. A list is
    taken as its `str` items, a `str` is split on `,`, and anything else gives `{}`. An entry that
    fully matches `QUALIFIED` goes through `address`. Otherwise a bare skill name looks only in
    `plugins[0]`, and needs exactly one URI.
  - `split_frontmatter(text: str) -> tuple[str, str]`: `(head, body)`. `head` runs through the
    closing `---` line when `text` starts with `---\n` and has one; otherwise it is `("", text)`.

- [ ] **Step 1: Write the failing tests**

```python
from kubed.mcp_kb.catalogue.names import QualifiedNames, split_frontmatter

W = "skill://kit/writing/SKILL.md"
NAMES = QualifiedNames(
    plugins=(
        ("kit", {"writing": (W,), "twin": ("skill://kit/a/twin/SKILL.md",
                                           "skill://kit/b/twin/SKILL.md")}),
        ("kit-extra", {"ops": ("skill://kit/ops/SKILL.md",)}),
        ("kit", {"late": ("skill://kit/late/SKILL.md",)}),
    )
)


def test_a_qualified_name_reads_as_the_skill_address():
    assert NAMES.rewrite("Load kit:writing, then /kit:writing.") == (
        f"Load {W}, then {W}."
    )
    assert NAMES.rewrite("(`kit-extra:ops`)") == "(`skill://kit/ops/SKILL.md`)"


def test_the_first_plugin_of_that_name_that_serves_it_answers():
    assert NAMES.rewrite("kit:late") == "skill://kit/late/SKILL.md"


def test_a_name_inside_a_longer_token_is_left_alone():
    for text in ("https://kit:writing", "a/kit:writing", "kb+kit:writing",
                 "kit:writing.md", "kit:writing/x", "kit:writing:x", "xkit:writing",
                 "skill://kit:writing", "kit:writing-"):
        assert NAMES.rewrite(text) == text


def test_what_does_not_resolve_is_served_as_written():
    for text in ("kit:nope", "other:writing", "kit:twin", "/kit:db:migrate",
                 "kit:Writing", "Note: kit"):
        assert NAMES.rewrite(text) == text
    assert QualifiedNames().rewrite("kit:writing") == "kit:writing"


def test_preload_resolves_qualified_and_own_bare_names():
    assert NAMES.preload(["kit:writing", " writing ", "ops", "kit-extra:ops",
                          "twin", "nope", 3]) == {
        "kit:writing": W,
        "writing": W,
        "kit-extra:ops": "skill://kit/ops/SKILL.md",
    }
    assert NAMES.preload("kit:writing, writing") == {"kit:writing": W, "writing": W}
    assert NAMES.preload(None) == {} and NAMES.preload({"a": 1}) == {}


def test_split_frontmatter_keeps_the_block_whole():
    assert split_frontmatter("---\nname: a\n---\nbody kit:writing\n") == (
        "---\nname: a\n---\n", "body kit:writing\n"
    )
    assert split_frontmatter("no block\n") == ("", "no block\n")
    assert split_frontmatter("---\nunterminated\n") == ("", "---\nunterminated\n")
```

- [ ] **Step 2: Run them to verify they fail**

  Run: `pytest tests/test_names.py -v`
  Expected: FAIL at import (`No module named 'kubed.mcp_kb.catalogue.names'`).

- [ ] **Step 3: Implement** the Interfaces above in `kubed/mcp_kb/catalogue/names.py`. The
  module docstring states SKL-54 and SKL-55 in prose. It also says why kb writes an address and
  never a name, and why commands and bare words are left alone, from the Design's bullets.

- [ ] **Step 4: Run the tests and the boundary guard**

  Run: `pytest tests/test_names.py tests/test_boundaries.py -v && ruff check .`
  Expected: all PASS, clean.

- [ ] **Step 5: Commit** `feat: recognise plugin-qualified skill names`

### Task 2: `SKILL.md` bodies and agents resolve names through `Catalogue`

**Files:**
- Modify: `kubed/mcp_kb/catalogue/uris.py`:
  - `LibraryText` gains `plugins: tuple[tuple[str, str], ...] = ()`, the `(plugin id, plugin
    name)` pairs in library order;
  - add `Catalogue.qualified_names`;
  - in `_skill_file`, rewrite the body of `MAIN_FILE` before `placeholders.substitute`;
  - in `agent_definition`, rewrite `instructions` before `placeholders.substitute`, and add
    `"skills"` to the `AGENT_META` dict after `"servers"`.
- Modify: `kubed/mcp_kb/catalogue/snapshot.py`, `build_snapshot`'s `LibraryText(...)`: pass
  `tuple((pid, by_id[pid].name) for pid in lib.plugins if pid in by_id)`.
- Test: create `tests/test_qualified_names.py` (`pytestmark = pytest.mark.integration`). It runs a
  real uvicorn server as `tests/test_plugin_root.py` does, reusing `_free_port` from
  `tests.test_header_scope` and the same `_write` and `_build` shape.

**Interfaces:**
- Consumes: Task 1's `QualifiedNames`, `split_frontmatter`.
- Produces: `Catalogue.qualified_names(self, library: str, plugin: str, scope: Scope =
  EVERYTHING) -> QualifiedNames`.
  - `plugin` is a plugin **id**.
  - The table groups `self._index.visible(scope)`'s skills of `library` by `skill.plugin`. The
    order is: that id first (present even with no skills), then the ids in that library's
    `LibraryText.plugins` order, then any others by id.
  - Each id's name comes from `LibraryText.plugins`; when an id isn't there (a `Catalogue` built
    without them, as unit tests do), the name is the id itself.
  - Each skill maps `skill.name` to `uri_for(skill)` (`skill://<address>/SKILL.md`), kept in
    address order.

- [ ] **Step 1: Write the failing tests.** The fixture follows `tests/test_plugin_root.py`.
  Declared plugin `kit` (`tags: [core]`) has skills `skills/writing` and `skills/cite`, and
  declared plugin `kit-extra` (`tags: [extra]`) has `skills/ops`. Library `kit` has
  `plugins: [kit, kit-extra]`. `kit` also ships `.claude-plugin/plugin.json` (`{"name": "kit"}`),
  which makes it Claude-format so it has agents. Its `agents/helper.md` has the frontmatter
  `name: helper`, `description: Helps.`, and `skills` as a YAML *block* list of `kit:writing`,
  `writing`, `kit-extra:ops` and `nope`. Use a block list, not a flow list: PyYAML can refuse a
  `:` inside `[…]`. The body, directly after the closing `---\n`, is `NAMES`.

```python
NAMES = (
    "A kit:writing\n"
    "B /kit:writing\n"
    "C kit-extra:ops\n"
    "D kit:nope\n"
    "E https://kit:writing\n"
    "F /kit:db:migrate\n"
)
RESOLVED = (
    "A skill://kit/writing/SKILL.md\n"
    "B skill://kit/writing/SKILL.md\n"
    "C skill://kit/ops/SKILL.md\n"
    "D kit:nope\n"
    "E https://kit:writing\n"
    "F /kit:db:migrate\n"
)
HEAD = "---\nname: cite\ndescription: See kit:writing.\n---\n\n"
SKILL_ON_DISK = HEAD + NAMES  # what _build writes to kit's skills/cite/SKILL.md


async def test_a_skill_body_reads_qualified_names_as_addresses(url):
    body = await _read(url, "skill://kit/cite/SKILL.md")
    assert body == HEAD + RESOLVED


async def test_an_out_of_scope_skill_is_left_as_written(url):
    body = await _read(url, "skill://kit/cite/SKILL.md", tags="core")
    assert "C kit-extra:ops\n" in body and "A skill://kit/writing/SKILL.md\n" in body


async def test_a_rewritten_name_takes_the_prefix_once(url):
    body = await _read(url, "skill://kit/cite/SKILL.md", prefix="kb+")
    assert "A kb+skill://kit/writing/SKILL.md\n" in body and "kb+kb+" not in body


async def test_the_extension_digest_follows_the_rewrite(url):
    entry = await _skills_get(url, "skill://kit/cite/SKILL.md")
    body = await _read(url, "skill://kit/cite/SKILL.md")
    (main,) = [r for r in entry["resources"] if r["uri"].endswith("/cite/SKILL.md")]
    assert main["digest"] == "sha256:" + hashlib.sha256(body.encode()).hexdigest()
    assert entry["frontmatter"]["description"] == "See kit:writing."


async def test_the_manifest_still_describes_disk_bytes(url):
    manifest = json.loads(await _read(url, "skill://kit/cite/_manifest"))
    (main,) = [f for f in manifest["files"] if f["path"] == "SKILL.md"]
    assert main["size"] == len(SKILL_ON_DISK.encode())


async def test_an_agent_reads_names_as_addresses_and_preloads_its_skills(url):
    definition = await _agent(url, "kit_helper")
    assert definition["instructions"] == RESOLVED
    meta = definition["_meta"]["io.kubed.mcp-kb/agent"]
    assert meta["skills"] == {
        "kit:writing": "skill://kit/writing/SKILL.md",
        "writing": "skill://kit/writing/SKILL.md",
        "kit-extra:ops": "skill://kit/ops/SKILL.md",
    }
    assert meta["frontmatter"]["skills"] == [
        "kit:writing", "writing", "kit-extra:ops", "nope"
    ]


async def test_a_scoped_agent_preloads_only_what_it_can_see(url):
    meta = (await _agent(url, "kit_helper", tags="core"))["_meta"][
        "io.kubed.mcp-kb/agent"
    ]
    assert "kit-extra:ops" not in meta["skills"]


async def test_the_preload_map_is_never_prefixed(url):
    meta = (await _agent(url, "kit_helper", prefix="kb+"))["_meta"][
        "io.kubed.mcp-kb/agent"
    ]
    assert meta["skills"]["writing"] == "skill://kit/writing/SKILL.md"
```

  `_read(url, uri, tags=None, prefix=None)`, `_skills_get` and `_agent` are module helpers:
  - each opens a `Client(StreamableHttpTransport(...))`, sending `Kb-Tag` and
    `Kb-Resource-Prefix` headers when the argument is given;
  - `_skills_get` and `_agent` send `skills/get {uri}` and `agents/get {name}` as raw requests,
    as `tests/test_skills_extension.py` and `tests/test_agents_extension.py` do (copy their
    helper, don't import a private one).

- [ ] **Step 2: Run them to verify they fail**

  Run: `pytest tests/test_qualified_names.py -v`
  Expected: the rewrite tests FAIL with the names as written; the `_meta` tests FAIL with
  `KeyError: 'skills'`. `test_the_manifest_still_describes_disk_bytes` passes already: it is a
  guard.

- [ ] **Step 3: Implement** the Interfaces and the file changes above. In `_skill_file`:
  `head, body = split_frontmatter(text)`, then `text = head + names.rewrite(body)`, then the
  existing `placeholders.substitute`. Build `names` once per call, from the same `scope`. In
  `agent_definition`, build one table for both `instructions` and `preload`, and pass `preload`
  `parsed.frontmatter.get("skills")`. Then extend `agent_definition`'s docstring by a sentence on
  the rewrite and the map.

- [ ] **Step 4: Run the whole suite**

  Run: `ruff check . && pytest`
  Expected: clean, all PASS, the guard files listed in Global Constraints unchanged,
  `tests/test_wiki.py` not skipped.

- [ ] **Step 5: Commit** `feat: serve plugin-qualified skill names as addresses`

### Task 3: Prompt bodies resolve names before the dialect runs

**Files:**
- Modify: `kubed/mcp_kb/catalogue/prompts/__init__.py`. `FilePrompt.render` gains the keyword
  `names: QualifiedNames | None = None`. When it is given, the template is
  `names.rewrite(self.body())`, and that goes into `DIALECTS[self.dialect].substitute`. Its
  docstring gains a sentence: before the dialect, so a value is never rewritten.
- Modify: `kubed/mcp_kb/mcp/prompts.py`:
  - `MCPFilePrompt` gains `names: QualifiedNames = Field(default_factory=QualifiedNames)`;
  - `_filled` passes `names=self.names`;
  - the provider's `_get_prompt` adds `"names": snapshot.catalogue.qualified_names(
    prompt.file.library, prompt.file.plugin, requested_scope())` to the same `model_copy`
    update as `skill_dirs`, and its docstring's map sentence covers both.
- Test: `tests/test_qualified_names.py`. `_build` also writes `kit`'s
  `commands/cite.md`: `"---\ndescription: Cite.\n---\n" + NAMES + "G $ARGUMENTS\n"`.

**Interfaces:**
- Consumes: Task 1's `QualifiedNames`, Task 2's `Catalogue.qualified_names`.
- Produces: `FilePrompt.render(arguments=None, *, plugin_root=None, skills=None, names=None)`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_prompt_body_reads_qualified_names_as_addresses(url):
    assert await _prompt(url, "kit_cite") == RESOLVED + "G \n"


async def test_an_argument_value_is_never_rewritten(url):
    text = await _prompt(url, "kit_cite", {"arguments": "kit:writing"})
    assert text == RESOLVED + "G kit:writing\n"


async def test_the_prompt_mirror_rewrites_alike(url):
    assert await _prompt_tool(url, "kit_cite") == RESOLVED + "G \n"
```

  `_prompt(url, name, arguments=None)` returns the single message's text from
  `client.get_prompt`. `_prompt_tool` calls the `get_prompt` tool with `X-MCP-Prompts: off`
  and returns its text.
  - If the claude dialect renders an empty `$ARGUMENTS` differently from `"G \n"`, check what it
    does in `tests/test_dialects.py`. Then fix the expected tail in all three tests to match, and
    leave the dialect alone.

- [ ] **Step 2: Run them to verify they fail**

  Run: `pytest tests/test_qualified_names.py -v -k prompt`
  Expected: FAIL, with the names as written in the rendered text.

- [ ] **Step 3: Implement** the file changes above.

- [ ] **Step 4: Run the whole suite**

  Run: `ruff check . && pytest`
  Expected: clean, all PASS, `tests/test_placeholders.py` and `tests/test_prompts.py` unchanged.

- [ ] **Step 5: Commit** `feat: resolve plugin-qualified skill names in prompt bodies`

### Task 4: Spec, AGENTS.md, wiki and changelog

**Files:**
- Modify: `docs/superpowers/specs/skills.md`:
  - drop `*(proposed)* ` from SKL-54 and SKL-55;
  - in SKL-41's table, append "an agent definition's `_meta…skills` values" to the "never" row.
- Modify: `docs/superpowers/specs/prompts.md`:
  - drop `*(proposed)* ` from PRM-62;
  - reword PRM-47 to say rendering runs in this order: the qualified skill names in the body
    (PRM-62), then the dialect's placeholders, then the placeholders this server resolves
    (PRM-48), then the gateway prefix.
- Modify: `docs/superpowers/specs/agents.md`:
  - drop `*(proposed)* ` from AGT-17;
  - in AGT-9's table, the `instructions` row reads "rendered as a prompt body is: qualified skill
    names by AGT-17, `${CLAUDE_PLUGIN_ROOT}` by …";
  - the `_meta` row gains ", and `skills` (AGT-17)".
- Modify: `AGENTS.md`, "Where code goes". After the "A library referencing files outside its
  skills" bullet, add one bullet. A `<plugin>:<skill>` name in served text goes to
  `catalogue/names.py`, resolved through `Catalogue.qualified_names`. It is rewritten to an
  address, never to a name, because a client picks its own names for kb's skills. Commands and
  bare words are left alone.
- Modify (submodule `wiki/`):
  - `Plugins.md`, "The plugin root": one row in the placeholder table, `` `<plugin>:<skill>`,
    `/<plugin>:<skill>` `` → `skill://<library>/<folder>/<name>/SKILL.md`, in a `SKILL.md` body,
    a prompt body or an agent body. Then one paragraph after it: a plugin of the same library, own
    plugin first; in scope only; commands and bare names left as written.
  - "What `agents/list` and `agents/get` return": the `_meta` row gains `skills`, the
    frontmatter's `skills` resolved to addresses.
  - `Prompts.md`, the placeholder table: the same row, and a sentence that an argument's value
    is never rewritten.
- Modify: `CHANGELOG.md` `[Unreleased]`, `### Added`, last line:
  `` - A `<plugin>:<skill>` name in a skill, prompt or agent reads as the skill's `skill://` address. ``

- [ ] **Step 1: Write the docs.** Use the fixture's names (`kit`, `kit-extra`) or drawio's as
  examples, and nothing else.
- [ ] **Step 2: Verify**

  Run: `python scripts/generate_wiki.py --check && pytest tests/test_wiki.py -v && ruff check . && pytest`
  Expected: pass, no skips. No generated page changes, because no tool, endpoint or config key
  changed.

- [ ] **Step 3: Commit the wiki first, inside `wiki/`, without pushing.** Then commit the
  superproject with the specs, `AGENTS.md`, the changelog and the submodule pointer. The
  controller pushes.
  Commit: `docs: plugin-qualified skill names`
