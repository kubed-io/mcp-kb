# K3: skills through kubed-mcp's plugin layer — design

> **History.** Proposed for #79 (PR #89, into `issue-80`, epic #80). Not shipped. This is K3's
> design of record, and [the plan](2026-11-24-k3-skills-through-add-plugin.md) implements it.
> There was no draft spec on the branch. Its second round follows Dr K's rulings of 2026-11-24
> (23:01) on PR #89. Those rulings replaced the first round's staged trees. The cluster
> repository's `2026-11-23-kb-onto-the-plugin-layer-design.md` is where K3 started; it couldn't
> be read from here.

## What K3 does

kb stops serving a skill's files. kubed-mcp's plugin layer serves them, from each plugin as
itself: every file, the `_manifest`, the Skills extension entry, and the indexes and folders
inside a skill. The plugin layer here means `plugin_set`, `serve`, `plugin_view` and
`add_rewriter`, pinned at `kubed-mcp==0.2.0rc2`, which carries quick-mcp#37 and #21.

kb's scope becomes a kubed-mcp **view**, and kb's placeholder and name rewriting becomes its one
**rewriter**. K1's provider (`mcp/skill_catalogue.py`) goes. kb stops serving the skill layouts
Claude Code doesn't load.

kb keeps collecting plugins from sources and grouping them into libraries, refresh, `/health`,
`/reindex`, and its kb-only surfaces: library and folder indexes, `_files.md`, library files and
the plugin-root fallbacks. Prompts and agents stay kb's until K4 (#82) and K5 (#83).

## Facts this rests on

kubed-mcp is read at tag `v0.2.0-rc.1`, and the two issues the rc2 carries at their text.

| Fact | Where |
|---|---|
| A plugin's skill is served at `skill://<namespace>/<dir>/SKILL.md`. A skill is a direct child of `skills/` that holds `SKILL.md`, or a declared `skills` entry: the entry itself if it holds `SKILL.md`, else its direct children that do. Declared entries add to the `skills/` scan, the first claim winning. Dot folders are pruned. | `plugins.py` `_skill_folders`, `read_plugin`, `_merged` |
| A declared `commands` or `agents` list replaces its folder, with a note `Default <kind>/ folder is ignored because the manifest sets "<kind>"`. Declared lists from `plugin.json` and the entry are unioned. | `read_plugin` |
| A set is `plugin_set()` → `add(address, namespace=, manifest=)` / `keep(plugin)` → `serve()`. A refused add raises `PluginError` and leaves the set as it was. | `PluginSet` |
| Files are read at `add`, and builds never touch the disk. | `_load` |
| `View(key, admits)`: `fn()` runs once per request that reads skills, and `admits` only when a build is made. The build key is `(generation, view key, prefix)`, in an LRU of 64. | `plugins.py` |
| Rewriters run in the order added, then the gateway prefix writer (GW-5). `to_mcp_form` is opt-in. | `_rewrite.py` |
| `_manifest` is FastMCP's, `{"skill": <name>, …}`. A skill's file with a text-type extension reads as text (quick-mcp#37). | FastMCP `v4.2.5`; #37 |
| A namespace inside an earlier plugin's skill folder, or the reverse, refuses the later plugin with `<namespace> is inside skill <uri> of plugin <name>` (#37). | #37 |
| `QuickMCP(..., header_prefix="Kb")` reads `Kb-<Name>` beside `X-MCP-<Name>`, with the prefixed one winning, then the query, then `config.delivery`, then the default. That covers `Resource-Prefix`, `Resources`, `Listed` and `Via` (#21, DLV-16). | #21 |
| `resources/list` lists every `SKILL.md` unless `listed` leaves out `skills` (DLV-8). The plugin layer's two read-only resource tools arrive with the first plugin, and `mcp.tool` refuses a server tool of the same name (DLV-6, DLV-7). | #21; rc1 already lists them |

## Design

### D1. A library is a namespace, with its main plugin on top (ruling 1)

**A library's main plugin** is decided once per generation, from the library's resolved plugin
list. It never depends on what serves or on what a request's scope admits. It is:

1. the first of the library's plugins whose `name` is the library's name; else
2. the library's marketplace's only entry, when its `marketplace.json` lists exactly one entry
   (skipped ones count) and that entry's `source` is the marketplace root; else
3. none.

The main plugin is added under namespace `<library>`, and every other plugin under
`<library>/<plugin name>`. kb's own addresses follow the same rule: a skill's address is
`<library>/<name>` in the main plugin, and `<library>/<plugin name>/<name>` in any other. Its
**folder** (SKL-10) is the plugin's name, empty for the main plugin. A plugin in two libraries
has one address in each.

**Three live addresses move,** as named changes N2 and N3: tidy's two skills, to
`skill://superpowers/tidy/…`, and n8n-house's `n8n-mcp-instructions`, to
`skill://n8n/n8n-house/n8n-mcp-instructions/…`. The n8n library's note that names it lives in
the cluster repository's `mcp/mcp-kb/config.yaml`, outside this repository. It is changed beside
the deploy, like the gateway was.

### D2. Each plugin is added as itself (rulings 2, 3)

`set.add(plugin.address, namespace=…, manifest=entry)`.

- **The address** is kb's own `<source>://<path>[//<subdir>][?ref=]`, so no cache path reaches a
  kubed-mcp log line or error.
- **The entry** is the marketplace entry as published, less `source`. A declared plugin's is
  `{"name": <name>}`, plus its `skills:` folders when it declares them (D3). Either way, kb adds
  `"commands": []` and `"agents": []`, so kubed-mcp serves skills and nothing else, and kb's
  prompts and agents stay kb's.
- **Plugins kb does not add:**
  - a plugin that serves no skills, such as penpot-shared with `skills: []`;
  - a plugin LIB-28 has failed in that library;
  - a plugin whose record isn't `ok`.
- **The loader.** kubed-mcp reads the plugin through kb's **served-tree loader**: one
  `PluginLoader` for `file` and every declared source's name. It replaces `LocalLoader`
  (PLUG-61). Its `materialise(address)` is the tree kb's record serves for that fetch, last good
  included, with the subdir guarded by `plugin_root`.
  - It is the fetch memo the notes asked for, as a getter over `KnowledgeBase._fetches`, which
    the cold start, `_fetch_record` and `refresh` (after `keep_last_good`) already set under the
    lock. So it never clones.
  - A fetch kb doesn't serve fails with `<key> is not materialised`.
  - `build_fetch` keeps the `SourceLoader`s it uses today, and never goes through this loader.
- **A refused add** is caught and reported under the library's `conflicts` as
  `conflict: <reason>`, scrubbed, and that plugin's skills are taken out of kb's catalogue for
  that library (rulings 3, 8). A refused add is a `PluginError`, which covers #37's nesting
  guard, or a `ValueError` for a namespace kubed-mcp can't take. kb's LIB-28 claims run first and
  already refuse overlapping skill addresses, so the nesting guard is a backstop.
- **Notes from kb's own entry stay out of `/health`.** kubed-mcp's `Plugin.skipped` doesn't reach
  `/health` in K3 (ruling 2). kb reads it only to log, and drops the two "Default commands/ … /
  agents/ folder is ignored" notes that kb's entry causes.

### D3. kb discovers skills the way kubed-mcp serves them

kb's harvest still builds the rows its indexes, hints, scope refusals and fallbacks are built
from. Its skill rule is now kubed-mcp's rule, written once in `harvest.skill_dirs(root,
declared)`:

- each direct child of `skills/` holding `SKILL.md`;
- then each declared entry (the manifest's, then the entry's, then a declared plugin's
  `skills:`): the entry itself if it holds `SKILL.md`, else its direct children that do;
- the first claim wins, and dot folders are skipped.

**What goes:**
- kb's skill globs;
- the `.claude/skills`, `.github/skills` and `.agents/skills` conventions;
- deeper folders;
- a skill at a plugin root;
- LIB-32's root-entry exception (native discovery gives grafana's entries the same skills).

A declared plugin's `skills:` becomes a list of folders. A glob character in one is refused at
load, and `skills: []` serves none.

**Parity guard.** After `serve()`, kb narrows its catalogue to the `SKILL.md` URIs kubed-mcp
reports serving for each added plugin, and logs once any skill either side has that the other
lacks. No index line can name a skill that does not read. That covers a skill FastMCP refuses
(SKL-45) and one the nesting guard drops.

### D4. One plugin set per generation

`SkillServing.publish(snapshot)` builds the set: library by library in config order, each
library's plugins in its order, then `mcp.serve(set)`.

- **Its result.** It returns the snapshot kb swaps in, with its `catalogue` narrowed (D2, D3) and
  its `status` carrying any new `conflicts`.
- **When it runs.** `KnowledgeBase.serve_through(publish)` runs it under kb's lock, on the
  current snapshot at once, then on every rebuilt snapshot before the swap.
- **Registration order.** `create_app` attaches it before `resources.register`, so kubed-mcp's
  `_Skills` comes before `CatalogueProvider` whenever the boot generation has a skill.

### D5. The view (rulings 7, 9)

`mcp.plugin_view(serving.view)`:

- **The key** is the frozenset of `(library, address)` pairs that the request's scope admits
  among the added plugins, and nothing else. A scope that admits nothing gets `EMPTY`.
- **The table.** `admits(plugin)` looks up `(plugin.namespace.split("/")[0], plugin.address)` in
  kb's table. Each entry holds the category, the labels (`tags` with `keywords`) and the
  library's categories.

### D6. kb's rewriter alone (ruling 4)

`mcp.add_rewriter(serving.rewrite)`. On a skill's root `SKILL.md`, it applies
`Catalogue.instructions(address, text, requested_scope())`: SKL-55, then SKL-25 and SKL-52, as
today. Every other site is returned as written. `to_mcp_form` isn't registered.

The request's scope is safe to read here: a build runs in the request that pinned its key, and
every scope with that key admits the same plugins. GW-5 writes the prefix after it.

### D7. The prefix: `header_prefix="Kb"` (ruling 6)

`QuickMCP(..., header_prefix="Kb")`. kubed-mcp then reads `Kb-Resource-Prefix`, then
`X-MCP-Resource-Prefix`, then `?prefix=`, and it is the one writer on a skill's files. kb's own
surfaces keep `requested_addressing()`, which reads the same three in the same order, so the two
always agree. There is no gateway switch and no kb prefix rewriter.

### D8. What #21 brings that K3 must settle

1. **The listing.** With `listed` at its default, `skills`, `resources/list` would gain a row per
   skill: 102 at QA, against today's index rows (SKL-14). K3 sets `config.delivery`'s `listed` to
   none, so the listing stays kb's until the delivery sub-issue replaces `Kb-Listing`. With
   `header_prefix="Kb"`, a client's `Kb-Listed` or `X-MCP-Listed` would still override it, and no
   client sends either today.
2. **The resource tools (DLV-7).** kb's mirror tools `list_resources` and `read_resource` clash
   with the plugin layer's at the first `add`. K3 removes kb's pair, and kubed-mcp's serve the
   mirror (DLV-6). They're hidden unless `Kb-Resources`, `X-MCP-Resources` or `?resources=` is
   off, which are the switches kb reads today. kb keeps its prompt mirror tools and their hiding.
   Any difference in the tools' output is named change N4.

### D9. Live skills (ruling 7)

`view()` revalidates the live plugins its scope admits, once per request that reads skills, with
`Catalogue.live_stamp(skill)` over each one's skills. When a stamp moved, it builds a new set:
`keep` every other plugin, and `add` the moved one again, which kubed-mcp reads afresh through
the served-tree loader. Then it `serve`s that set. All of this runs under the serving lock taken
without blocking: a refresh that holds it is about to publish anyway.

### D10. Empty and refused scopes build nothing (ruling 8)

`what_is_wrong` and `_serving` read `snapshot.catalogue`, which `publish` has already narrowed,
and never a build. `admits` runs only when a build is made, so neither a refused request nor a
burst of bogus `Kb-Tag` values fills the LRU. Every scope that admits nothing shares `EMPTY`.

## The live dump: named changes

- **N1.** A skill's `_manifest` names it by its name (`{"skill": "loki", …}`). Accepted, ruling 5.
- **N2.** tidy's two skills read at `skill://superpowers/tidy/<name>/…`, and their old addresses
  read as absent. Their index lines move to `skill://superpowers/tidy/_index.md`.
- **N3.** n8n-house's `n8n-mcp-instructions` reads at
  `skill://n8n/n8n-house/n8n-mcp-instructions/…`. So does the instruction line that names it,
  once the cluster config's note is updated.
- **N4.** `list_resources` and `read_resource` are kubed-mcp's (D8.2), so their result shape is
  whatever DLV-6 returns.

Everything else stays the same as the before-dump, under all ten scopes, with and without `kb+`.

## The spec, as the PR leaves it

- **[skills.md](../specs/skills.md):**
  - SKL-2 and SKL-7 go;
  - SKL-1, SKL-10, SKL-24, SKL-37, SKL-45, SKL-52 (its plugin-root-skill clause) and SKL-58 are
    reworded;
  - SKL-59 (a library's namespaces and its main plugin) and SKL-60 (kb's rewriter) are new.
- **[plugins-and-libraries.md](../specs/plugins-and-libraries.md):**
  - PLG-9 and PLG-20 are reworded: a skill is found the native way, and a declared plugin's
    `skills:` is folders;
  - LIB-32 goes;
  - LIB-33 is reworded;
  - LIB-29 gains: a plugin kubed-mcp refuses is reported the same way.
- **[config-and-sources.md](../specs/config-and-sources.md):** SRC-53 is reworded: the
  served-tree loader for every scheme replaces `LocalLoader`. A CFG row refuses a glob in
  `skills:`.
- **[scoping-and-instructions.md](../specs/scoping-and-instructions.md):** SCP-36 is new: one
  build per admitted set, `EMPTY` shared, and a refused scope builds nothing.
- **[http-and-tools.md](../specs/http-and-tools.md):** the TOOL rows for `list_resources` and
  `read_resource` point at kubed-mcp's DLV-6, and their `?resources=` switch at DLV-2.

## For Dr K

1. **Rule 2 of the main plugin.** Is "the library's own source when that source is a single
   plugin" a marketplace whose only entry sits at its root (D1)? kb's library `source` is always
   a marketplace.
2. **D8.1.** Keep `resources/list` index-only by setting `config.delivery` `listed` to none until
   the delivery sub-issue. This needs #21's config to accept an empty `listed`.
3. **D8.2.** kubed-mcp's resource tools replace kb's in K3, because DLV-7 won't let both exist,
   with N4 as a named change. The alternative is a quick-mcp knob that holds them back until the
   delivery sub-issue.
