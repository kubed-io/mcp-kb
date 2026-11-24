# K3: skills through kubed-mcp's plugin layer — design

> **History.** Proposed for #79 (PR #89, into `issue-80`, epic #80). Not shipped. This file is the
> design of record for K3; [the plan](2026-11-24-k3-skills-through-add-plugin.md) implements it.
> It replaces nothing on the branch: there was no draft spec. The cluster repository's
> `2026-11-23-kb-onto-the-plugin-layer-design.md` is the design K3 started from, and it could not
> be read from here.

## What K3 does

kb stops serving a skill's files. kubed-mcp's plugin layer (0.2.0rc1: `plugin_set`, `serve`,
`plugin_view`, `add_rewriter`) serves every file of every skill, its `_manifest`, its Skills
extension entry, and the indexes and folders inside it. kb's scope becomes a kubed-mcp **view**,
and kb's placeholder and name rewriting becomes a kubed-mcp **rewriter**. K1's provider
(`mcp/skill_catalogue.py`) goes, and so do the parts of `catalogue/uris.py` that turned a skill
into served text.

kb keeps what the epic leaves it: collecting plugins from sources, grouping them into libraries,
refresh, `/health`, `/reindex`, and the kb-only surfaces. Those are library and folder indexes,
`_files.md`, library files, and the plugin-root fallbacks. Prompts and agents stay kb's until
K4 (#82) and K5 (#83).

## What kubed-mcp 0.2.0rc1 does, read at tag `v0.2.0-rc.1`

These facts decide the design. Each one is in the source, not only in the spec.

| Fact | Where |
|---|---|
| A plugin's skills are served at `skill://<namespace>/<dir name>/SKILL.md`. A skill is a directory directly under `skills/`, or one listed in `skills`; nothing sits between the namespace and the skill's directory. | `plugins.py` `_skill_folders`, `_read` |
| The default `skills/` scan always runs. A listed `skills` adds to it; `skills: []` does not turn it off. There is no `.claude/skills`, `.github/skills` or `.agents/skills` convention. A `SKILL.md` two levels down only earns a note. | `read_plugin` |
| `add` / `PluginSet.add` serve every kind a plugin has. A `commands: []` or `agents: []` entry only replaces the folder when `plugin.json` declares none of its own. | `read_plugin`, `_merged` |
| The first non-empty `serve()` adds kubed-mcp's own `_Prompts` provider and `_Agents` extension, even when the set has no prompt or agent. `_Skills` is added at the first `serve()` that has a skill, after any provider the server already registered. | `Plugins._providers` |
| A set is replaced only as `plugin_set()` → `add` / `keep` → `serve()`. `keep` carries a served plugin without reading it again. There is no remove or replace. | `PluginSet` |
| Files are read once, at `add`. A build never touches the disk. | `_load` |
| A view is `View(key, admits)` from `kubed.mcp.plugins`. `fn()` runs once per request that reads skills; `admits` runs only when a build is made. The build key is `(generation, view.key, prefix)`, in an LRU of 64. | `plugins.py` `_key`, `BUILDS` |
| Rewriters run in the order added, then the gateway prefix writer (GW-5) when the key has a prefix. `to_mcp_form` is opt-in. A rewriter that raises drops that skill from that build only (PLUG-59), and only the log says so. | `_rewrite.py` |
| The `_manifest` is FastMCP's: `{"skill": <frontmatter name>, "files": [...]}`. A skill's file is FastMCP's `SkillFileResource`: text when its guessed type is `text/*` and it decodes, a blob otherwise, `application/octet-stream` when the type can't be guessed. | FastMCP `v4.2.5` `skills/provider.py` |
| The build a request reads is private (`Plugins.pinned()`). Nothing public says which skills a build dropped. | `plugins.py` |
| The gateway prefix comes from `X-MCP-Resource-Prefix` or `?prefix=`. `_TakeThePrefix` strips the request's own prefix from incoming addresses. | `gateway.py` |
| A server's `file` loader replaces `LocalLoader` once (PLUG-61). | `add_loader` |

## Where this departs from the rulings, and why

Four points of #79's notes don't survive those facts. Dr K confirms or overrules each one before
`plan approved`.

1. **Ruling 3's namespace `<library>/<plugin>` would move most addresses.** Under that namespace,
   `skill://superpowers/writing-plans/SKILL.md` becomes
   `skill://superpowers/superpowers/writing-plans/SKILL.md`. That breaks SKL-9 and SKL-10, the
   addresses written into every agent's prompt, and CONTRIBUTING's rule that an address keeps
   resolving. grafana's addresses survive only because each entry's name equals its folder. A
   plugin's own globs (PLG-9), the conventions of SKL-1, deeper folders and the plugin-root skill
   would stop serving. kubed-mcp would also serve the plugin's commands and agents beside kb's.
   So this design hands kubed-mcp **staged plugins**: one per (library, plugin, folder), under
   namespace `<library>/<folder>`. Every address stays as it is. Ruling 3's other half still
   holds: one plugin set per generation, in config order, library by library. A refusal is
   reported under the library's `conflicts`.
2. **Ruling 6: kb's rewriter does all of SKL-25, SKL-52 and SKL-55, and `to_mcp_form` is not
   registered.** `to_mcp_form` resolves `${CLAUDE_PLUGIN_ROOT}/<dir>` against the staged tree's
   paths. It resolves `<plugin>:<skill>` across every admitted plugin, in every library. SKL-52
   and SKL-55 resolve within one library, own plugin first, against the plugin's real paths. kb's
   rewriter is today's tested code, `placeholders.substitute` over `names.rewrite`. Run alone, it
   leaves nothing for `to_mcp_form` to do, and it removes ruling 6's named change (a). Every file
   other than `SKILL.md` stays as written, as now.
3. **The deletion list shrinks.** kb keeps the skill harvest (`harvest.skill_dirs`, `folder_of`),
   `catalogue/skills.py`'s `Skill` and `SkillIndex`, and the index half of `uris.py`. They are
   what decides which directories are skills, and what kb's indexes, hints, scope refusals and
   fallbacks are built from. That is kb's job under the epic ("collecting plugins … grouping them
   into libraries") and its kb-only surfaces. It isn't serving code. What goes is K1's provider,
   `Catalogue.skill_files`'s rewriting, `_text`, `_instructions` (it becomes the rewriter's
   `instructions`), `live_stamp(scope)`, and the build memo.
4. **No fetch memo.** The memo existed so that `add_plugin("<source>://…")` would not
   re-materialise a clone on every generation. kubed-mcp is never handed a source address, only a
   staged tree, so nothing re-fetches. kb's `FetchRecord`s already hold the tree kb serves, the
   last good one included. kb's `file` loader still replaces `LocalLoader` (PLUG-61). No other
   loader is registered with kubed-mcp, because without a memo one would clone again on every
   `add`.

## Design

### D1. Staged plugins

Each generation, kb **stages** every group of skills that one plugin serves in one folder of one
library:

- **What a group is.** Its skills are kb's admitted skills (`_admit`, LIB-28/29) for that
  library, plugin and folder. Skills FastMCP refuses (D5) and skills inside another skill (SKL-7)
  are left out of it.
- **What the tree holds.** Each skill's directory is at its path below the plugin root. A plugin
  root that is itself a skill is staged at `<name>/`. Each file is written as kb reads it (SKL-22:
  UTF-8 with bad bytes replaced, LF line endings).
  - A file is copied only when it's a regular file, not hidden (SKL-3), resolves inside the skill,
    and isn't named `_index.md` or `_index.json`, or `_manifest` at the skill's root (SKL-21).
  - Beside the skills, the tree holds `.claude-plugin/plugin.json`:
    `{"name": "<plugin name>", "skills": ["./<path>", ...]}`. That is all it holds: no commands,
    no agents and no library files. So kubed-mcp serves skills only, and its `_Prompts` and
    `_Agents` have nothing to serve.
- **Its namespace** is `<library>/<folder>`, or `<library>` when the folder is empty. A skill's
  URI is then `skill://<namespace>/<name>/SKILL.md`, which is its address (SKL-9). Several
  plugins of one library share a namespace when they share a folder. LIB-28 already keeps their
  addresses apart.
- **Where it lives.** A staged tree is `<cache>/stage/<digest>`. The digest is SHA-256 over the
  namespace, the plugin name and every staged `(path, bytes)`. A tree that already exists is
  reused, across refreshes and restarts. A new one is written to a temporary sibling and renamed
  into place, so a killed write leaves nothing a later `add` reads.
- **Cleanup.** After `serve()`, every staged tree that no served plugin reads is deleted.
  kubed-mcp holds every byte in memory from `add` on.
- **Its address** is `file://<staged root>`. It goes through kb's `file` loader (PLUG-61), so it
  gets the same subdir guard as every other `file://` address.

`catalogue/stage.py` does the grouping and writing, with no FastMCP import. The FastMCP check is
passed in (D5).

### D2. One plugin set per generation

`mcp/skills.py`'s `SkillServing.publish(snapshot)` builds the set: `mcp.plugin_set()`, then
`add(stage.address, namespace=stage.namespace)` for each stage, in library order, the library's
plugin order, then folder order. Then `mcp.serve(set)`.

- **A refused add.** A `PluginError`, or a `ValueError` for a namespace kubed-mcp can't take, is
  caught. It's logged at error level and reported under the library's `conflicts` as
  `conflict: <reason>`. The reason is scrubbed and unrooted. The rest of the set still serves.
  kb's own claims (LIB-28) run first, so this is a defect backstop, not a path a valid config
  takes.
- **When it runs.** `KnowledgeBase.serve_through(publish)` registers `publish`. kb calls it under
  its lock, on the current snapshot at once, and then on every rebuilt snapshot before the swap.
  So kubed-mcp serves the new skills a moment before kb's indexes name them. `publish` returns
  the snapshot kb swaps in, which differs in three fields:
  - `catalogue` is less the refused skills;
  - `status` carries the new conflicts;
  - `stages` holds what it staged.
- **Registration order.** `create_app` calls `attach()` before `resources.register`, so `_Skills`
  is registered before `CatalogueProvider` whenever the boot snapshot has a skill. When it has
  none, `_Skills` arrives after `CatalogueProvider`. That is safe because `Catalogue.read`
  answers nothing at a skill's file or inside a skill (Review Focus 1).

### D3. The view

`mcp.plugin_view(serving.view)`:

- **The key.** `view()` returns `View(key, admits)`. The key is the frozenset of `(library,
  plugin id)` pairs that the request's scope admits among the served stages, and nothing else
  (ruling 7). A scope that admits nothing gets the one constant `EMPTY = frozenset()`.
- **What admits reads.** `admits(plugin)` looks up `plugin.address` in kb's **stage table**. The
  table is keyed by stage address, and each entry holds the library, the plugin id, the
  category, the labels (`tags` with `keywords`) and the library's categories (ruling 9).
  `Scope.admits` decides on that entry. It isn't the request's scope at build time: it is the key
  that decides.
- **What the key buys.** Scope admits whole plugins per library (SCP-20), so two scopes with one
  key see exactly the same skills and share one build.

### D4. kb's rewriter

`mcp.add_rewriter(serving.rewrite)`, registered once:

- **What it touches.** It returns `text` unchanged unless `site.kind == "skill"` and the file is
  the skill's root `SKILL.md`.
- **What it writes.** It returns `Catalogue.instructions(address, text, requested_scope())`.
  That is today's `_instructions` made public and keyed by address: SKL-55, then SKL-25 and
  SKL-52.
- **Why the request's scope is safe here.** A build runs inside the request that pinned its key,
  and every scope with that key admits the same plugins. So the request's scope resolves exactly
  as the key would (Review Focus 3). Outside a request the scope is `EVERYTHING`, which is also
  what the key is outside a request.
- **The prefix.** GW-5 writes it after this rewriter. kb registers no prefix rewriter: this is
  option (a) on #79, open there, and recommended.

### D5. What FastMCP refuses is kb's to decide, once per generation

Staging asks `check(files: dict[str, bytes]) -> str | None` of each skill. In `mcp/skills.py`
that check is `kubed.mcp.skills.Skill.from_files`, with today's `_reason` for the message. A
refused skill:

- is not staged;
- is logged at error level, as K1 logs it;
- is taken out of the snapshot's `catalogue` (`Catalogue.without`), so no index, hint, listing
  row or rewritten name points at it (SKL-45).

A skill that fails only under one key is dropped by kubed-mcp, and kb's surfaces still name it
(named change N3). The usual cause is a prefix pushing its description past 1024 characters.

### D6. Live skills

kubed-mcp never re-reads a file, so a live edit reaches it only as a new set. `view()` does it,
once per request that reads skills:

1. Revalidate each live stage the scope admits (`Catalogue.live_stamp(skill)` over its skills,
   through the snapshot's `Revalidator`, with its 2 s trust and 30 s cooldown, SKL-38).
2. If a stamp moved, re-stage those groups.
3. Serve a new set: `keep` every other served plugin, `add` the re-staged ones.

It all happens under the serving lock, taken without blocking. When a refresh holds the lock,
the check is skipped, because the refresh is about to publish anyway. This settles #79's "live
skills" question as option (a). #82 asks the same question for prompts, and its answer should
match.

### D7. Empty and refused scopes build nothing (ruling 8)

With K1 gone, `what_is_wrong` and `_serving` read `snapshot.catalogue`, kb's own table, which is
already less the refused skills. No refusal check reaches a kubed-mcp build. `admits` only runs
when a build is made, so a refused request never fills the LRU of 64, and nor does a burst of
bogus `Kb-Tag` values. Every scope that admits nothing shares `EMPTY`.

### D8. The prefix (option (a), #79)

Skill files carry the prefix that kubed-mcp resolves: `X-MCP-Resource-Prefix` or `?prefix=`.
kb's own surfaces keep `requested_addressing()` (`Kb-Resource-Prefix`, its alias
`X-MCP-Resource-Prefix`, `?prefix=`) until #81. They agree whenever a gateway sends the new
header. So QA's gateway switch to `X-MCP-Resource-Prefix` (ruled on #81) has to happen before
K3 deploys. kubed-mcp's GW-4 and kb's `ReadTheAddress` both strip the prefix until #81, and
stripping twice changes nothing.

## The live dump: named changes

Each of these appears in the ten-scope dump, with and without `kb+`, and nothing else should.

- **N1.** A skill's `_manifest` names the skill by its frontmatter `name`, not its address
  (`{"skill": "loki", …}`, SKL-24).
- **N2.** A skill's file whose guessed type isn't `text/*` reads as a blob, with FastMCP's type:
  `application/json` for `.json`, `application/octet-stream` when it can't guess, and whatever
  the host guesses for `.sh` (SKL-23). Library files and the fallbacks still read as text.
- **N3.** A skill that only one scope and prefix can't build is still named by kb's index,
  listing and hints under that key (SKL-45). No skill in the QA catalogue is near the limit.
- **N4.** Under `Kb-Resource-Prefix` alone, skill files are unprefixed and kb's surfaces are
  prefixed. QA sends `X-MCP-Resource-Prefix` before the deploy, so the dump shouldn't show it.

**What stays the same:** every address, listing row, index, hint, `_files.md`, library file,
fallback, `SKILL.md` body, entry digest, `skills/list`, `skills/get`, `resources/directory/read`,
prompt, agent and `/health` body, except a `conflicts` row should a staged add ever be refused.
The log also gains kubed-mcp's per-plugin notes. Staged trees hold no other group's skills, so
grafana's ~45 PLUG-40 notes per entry don't arise (ruling 2's check).

## The spec, as the PR leaves it

- **[skills.md](../specs/skills.md):**
  - SKL-23, SKL-24, SKL-37, SKL-40, SKL-42, SKL-45 and SKL-58 are reworded, as Task 6 of the plan
    spells out;
  - SKL-59 (staged plugins), SKL-60 (staged trees reused and deleted) and SKL-61 (kb's rewriter)
    are new.
- **[config-and-sources.md](../specs/config-and-sources.md):** SRC-53 is reworded: kb's `file`
  loader replaces `LocalLoader`, and no other loader is registered.
- **[plugins-and-libraries.md](../specs/plugins-and-libraries.md):** LIB-29 gains a sentence: a
  staged plugin that kubed-mcp refuses is reported the same way.
- **[scoping-and-instructions.md](../specs/scoping-and-instructions.md):** SCP-36 is new: one
  build per admitted set, `EMPTY` shared, and a refused scope builds nothing.

## For Dr K

1. Staged plugins under `<library>/<folder>` in place of ruling 3's `<library>/<plugin>`, which
   keeps every address. Or accept the address change and the loss of kb's skill globs.
2. kb's rewriter alone, with no `to_mcp_form`. Ruling 6's named change (a) then never happens.
3. N1 and N2 as named changes, or a quick-mcp ask first: name `_manifest` by path, and serve a
   skill's files as text.
4. Prefix option (a), with QA's gateway switch moved to before K3's deploy.
5. Live skills as option (a), re-staged on the request that sees the edit, matching #82.
