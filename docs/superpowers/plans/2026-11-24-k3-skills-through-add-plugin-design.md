# K3: skills through kubed-mcp's plugin layer — design

> **History.** Proposed for #79 (PR #89, into `issue-80`, epic #80). Shipped in PR #89: D1-D11
> and N1-N18 are as built, and the living spec says what holds now. This is K3's design of
> record, and [the plan](2026-11-24-k3-skills-through-add-plugin.md) implements it.
> There was no draft spec on the branch. Its second round follows Dr K's rulings of 2026-11-24
> (23:01) on PR #89, and his answers of 2026-11-25. Those rulings replaced the first round's staged trees.
> Revised on 2026-11-25 (05:56) when Task 4 found that kb's agents can't stay kb's beside a served
> plugin set: K3 hands them to kubed-mcp too (D11), and K5 (#83) shrinks to what is left. The cluster
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
the plugin-root fallbacks. Prompts stay kb's until K4 (#82). Agents move to kubed-mcp in K3
(D11), so K5 (#83) keeps only what D11 leaves.

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
| The first non-empty `serve()` registers the plugin layer's agents extension (`io.modelcontextprotocol/agents`), whatever the plugins hold. FastMCP refuses a second explicit registration of an extension id, so a server's own agents extension can't stand beside a served set. | `Plugins._providers`; FastMCP `add_extension` |
| `read_plugin` counts an empty list as a declared component (`entry.get(field) is not None`), so an entry carrying `"commands": []` beside a `plugin.json`, with `strict: false`, is refused as conflicting manifests. | `read_plugin` |
| `command_reader(fn)`: a reader that returns a string skips that command, with the warning `prompt <path> is skipped: <reason>` (PLUG-62). | `app.py` |
| An agent is named `<namespace's first segment>_<folders>_<name>`, a clash in the set renamed `<name>@<plugin>` (PLUG-63, PLUG-64). `agent_meta(fn)` adds keys to `agents/get`'s `_meta` beside `io.kubed/agent` (PLUG-73). Rewriters see an agent's file as `kind == "agent"` (PLUG-56). An agent's file also reads as an unlisted `agents://` resource (#20). | `plugins.py`, `agents.py` |
| `resources/list` lists every `SKILL.md` unless `listed` leaves out `skills` (DLV-8). The plugin layer's two read-only resource tools arrive with the first plugin, and `mcp.tool` refuses a server tool of the same name (DLV-6, DLV-7). | #21; rc1 already lists them |

## Design

### D1. A library is a namespace, with its main plugin on top (ruling 1)

**A library's main plugin** is decided once per generation, from the library's resolved plugin
list. It never depends on what serves or on what a request's scope admits. It is:

1. the first of the library's plugins whose `name` is the library's name; else
2. the library's marketplace's only entry, when its `marketplace.json` lists exactly one entry,
   whatever that entry's path (skipped ones count, so a skip never moves an address); else
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
  `{"name": <name>}`, plus its `skills:` folders when it declares them (D3). kb adds no empty
  component lists: kubed-mcp serves the plugin's skills and agents (D11), and kb's
  `command_reader` skips every command, so kb's prompts stay kb's until K4. That also covers a
  `plugin.json` that declares `commands` (penpot-ai-kit's seven `./prompts/*.md`), which an
  entry's `[]` could not empty, and leaves nothing for `read_plugin`'s empty-list check to refuse.
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
- **kubed-mcp's raw notes stay out of `/health`.** kubed-mcp's `Plugin.skipped` doesn't reach
  `/health` in K3 (ruling 2), and nor do the command skips kb's reader causes (one warning per
  command). kb reads `skipped` only to log, and to report the agents D11 says it reports.

### D3. kb discovers skills the way kubed-mcp serves them

kb's harvest still builds the rows its indexes, hints, scope refusals and fallbacks are built
from. Its skill rule is now kubed-mcp's rule, written once in `harvest.skill_dirs(root,
declared)`:

- each direct child of `skills/` holding `SKILL.md`;
- then each declared entry (the manifest's, then the entry's, then a declared plugin's
  `skills:`): the entry itself if it holds `SKILL.md`, else its direct children that do;
- the first claim wins, and dot folders and symlinked folders are skipped.

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
today. On an agent's file it rewrites the body as D11 says. Every text file of a skill, its
`SKILL.md` included, has its CRLF and CR line endings normalised to LF first (SKL-22); every
other site is returned as written. `to_mcp_form` isn't registered.

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
   none, so the listing stays kb's until #86 replaces `Kb-Listing`. With
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

It runs on every request that pins the plugin layer's state, agents included, as SKL-37 says.
kb's catalogue is narrowed again over the same snapshot and swapped in by
`KnowledgeBase.renarrowed`: the same generation, swapped only while the snapshot it narrowed is
still the one served. Three checks leave a refresh to land. A set that is published but not yet
swapped in (kb's snapshot isn't the one published) re-reads nothing. Before re-adding, a moved
plugin whose served root is no longer the one it was added from re-reads nothing: a refresh has
pointed its fetch at a new export and is building it. That check is only a cheap filter, because
a refresh can still move the fetch before the plugin is read. So after staging, and before
`serve()`, each re-added plugin's root as kubed-mcp read it is compared with the recorded one. On
any mismatch the re-read is abandoned: nothing is served, no new stamp is recorded and nothing is
swapped. Adding from that tree would mix two exports.

**One request late (Dr K, 2026-11-25 07:36, option 2).** kubed-mcp's `Plugins._pin` takes the
request's state before it calls the view, so the request that revalidates and re-adds still reads
the old copy, and the next request reads the edit. That is one request on top of the 2 s trust
window: a weaker guarantee than K1's, where the revalidating read was already the new one.
quick-mcp#45 proposes a way for the view's re-read to land in its own request; a later pin move
can restore the first-request read.

### D10. Empty and refused scopes build nothing (ruling 8)

`what_is_wrong` and `_serving` read `snapshot.catalogue`, which `publish` has already narrowed,
and never a build. `admits` runs only when a build is made, so neither a refused request nor a
burst of bogus `Kb-Tag` values fills the LRU. Every scope that admits nothing shares `EMPTY`.

### D11. Agents through kubed-mcp (Dr K, 2026-11-25 05:56)

kb's `AgentsExtension` (`mcp/agents.py`) goes, and kubed-mcp's serves `agents/list` and
`agents/get` from the plugins of the set, under the request's view. No quick-mcp change is
needed: a holding knob that keeps kb's extension would exist only to delay adoption.

- **Names.** kubed-mcp names an agent `<library>_<folders>_<name>`, which is kb's AGT-7, and
  renames a clash `<name>@<plugin name>` (PLUG-64), as kb's AGT-8 does. The claims run across
  the set in the order kb adds plugins, which is library order, then each library's plugin
  order. kb's roster is narrowed to the names kubed-mcp serves (the parity guard, as for
  skills), and `/health`'s `renamed` and `unserved` are read off kubed-mcp's `Plugin.agent_files`
  and `skipped`, in kb's wording.
- **`instructions`.** kb's rewriter also takes `site.kind == "agent"`: it rewrites the body after
  the frontmatter by AGT-17 and PRM-48, and leaves the frontmatter as written, so the file still
  reads as the same agent. The gateway prefix is kubed-mcp's writer, after kb's.
- **`_meta`.** `agent_meta` adds kb's `io.kubed.mcp-kb/agent` (`plugin`, `library`, `path`,
  `frontmatter`, `servers`, `skills`) for the agent's `(namespace, address)`, read off the
  snapshot the set was published from. kubed-mcp's own `io.kubed/agent` is there beside it.
  `agent_meta` runs once per set entry, never per view, so it can't see a scope. `skills`
  therefore resolves only against the agent's own plugin, which every scope that sees the agent
  also sees: a cross-plugin entry (`<plugin>:<skill>`) would name a skill a pinned client can't
  see (SCP-24), so it is left out for everyone (N9). The body's qualified names are the
  rewriter's, which does see the view, so `instructions` keeps them.
- **A bare plugin** (no `plugin.json` and no marketplace entry) has no agents in kb (AGT-4):
  its entry gets `"agents": []`. That can't meet `read_plugin`'s empty-list check, which needs a
  `plugin.json` beside the entry.
- **Scope.** An agent is in scope when the view admits its plugin, which is AGT-15's rule. Out of
  scope and absent stay one answer.
- **Live agents.** A build never reads the disk, so AGT-16's re-read on `agents/get` becomes D9's
  re-add: a live plugin whose agent file moved is added again, and `agents/list` and
  `agents/get` both serve the new read.
- **What K5 keeps:** a scoped `_meta.skills` (N9), which needs `agent_meta` to see the view; kb's own agent parsing (`catalogue/agents.py`), the roster and its
  `/health` bookkeeping, once kubed-mcp's `Plugin` carries what kb reads from it; one `_meta`
  key in place of two; and AGT-16's last-good fallback, if Dr K wants it back (N6).

## The live dump: named changes

- **N1.** A skill's `_manifest` names it by its name (`{"skill": "loki", …}`). Accepted, ruling 5.
- **N2.** tidy's two skills read at `skill://superpowers/tidy/<name>/…`, and their old addresses
  read as absent. Their index lines move to `skill://superpowers/tidy/_index.md`.
- **N3.** n8n-house's `n8n-mcp-instructions` reads at
  `skill://n8n/n8n-house/n8n-mcp-instructions/…`. So does the instruction line that names it,
  once the cluster config's note is updated.
- **N4.** `list_resources` and `read_resource` are kubed-mcp's (D8.2), so their result shape is
  whatever DLV-6 returns, and so are their descriptions: they no longer teach kb's URI grammar
  or its scope headers.

- **N5.** `agents/get`'s `_meta` also carries kubed-mcp's `io.kubed/agent` (`frontmatter`, and
  `skills` as the `SKILL.md` URIs of the agent's own plugin's skills it names), beside kb's
  `io.kubed.mcp-kb/agent`, which is unchanged.
- **N6.** A live skill's or agent's edit reads one request later than K1: the request after trust
  revalidates and re-adds the plugin (D9) but still reads the old copy, and the next request reads
  the edit. A live agent's edit reaches `agents/list` as well as `agents/get`. An edit that no
  longer parses takes the agent away until it parses again, where AGT-16 served the last good
  copy. A live edit of an agent's frontmatter `name` serves it under the new name from the next
  request, without a refresh, and a later plugin's agent it now clashes with is renamed
  `<name>@<plugin>` (PLUG-64). AGT-16 kept the snapshot's name until the next refresh.
- **N7.** An agent's file also reads at `agents://<library>[/<plugin>]/<path below agents/>`, an
  unlisted resource (#20).
- **N8.** An agent kubed-mcp's `parse_agent` refuses and kb's accepted is no longer served: one
  whose frontmatter `description` is empty, or isn't JSON-representable. The dump names any.

- **N9.** `_meta["io.kubed.mcp-kb/agent"].skills` maps only the agent's own plugin's skills.
  A `<plugin>:<skill>` entry naming another plugin is left out, whatever the scope.
- **N10.** kubed-mcp's agent reading, where it differs from kb's AGT-6 and AGT-9: an agent with
  no frontmatter `name` is served under its file's stem; `instructions` is trimmed of leading
  and trailing whitespace; `modelRoutingHint` splits `model` into letter-and-digit words, so
  `opus4` gives no hint where kb gave `large`.
- **N11.** On a cold start from `index.json`, an agent file that no longer parses no longer
  holds its name (AGT-8), so a later plugin's agent of that name keeps the short name.
- **N12.** The gateway prefix is written into an agent's card and kubed-mcp's frontmatter copy
  too, not only into `instructions`.
- **N13.** A skill whose folder holds a hidden path at any depth (a file or folder whose name
  starts with `.`) is not served at all, until kubed-mcp skips hidden files: FastMCP reads a
  skill folder whole, dot files included, so kb fails the skill's `SKILL.md` in its rewriter
  and drops the skill from its catalogue, logging it once. On the live sources this drops one
  skill, `skill://grafana/grafana-k6/k6-perf-test-website`, whose `assets/` holds a
  `.gitignore` and a `.gitkeep`.
- **N14.** A skill holding a symlink is not served at all: FastMCP refuses the skill whole, and
  the parity guard drops it from kb's catalogue, logging it once.
- **N15.** MD-57 per prefix is lost: a skill a build fails under one view alone (PLUG-59), such
  as a prefix that pushes its description past 1024 characters, doesn't read under that view,
  and kb's indexes under that view still name it. kb narrows once per generation.
- **N16.** A skill's file with no extension, or one kubed-mcp doesn't count as text, or bytes
  that aren't UTF-8, is served as an `application/octet-stream` blob (PLUG-75), where kb served
  every file as text, `text/markdown` by default.
- **N17.** The resource tools exist only once a plugin with a skill or an agent is served; before
  K3 kb always registered them. So do the extensions: `server/discover` declares the Skills
  extension once a plugin with a skill is served, and the Agents extension once one with a skill
  or an agent is. Until then `skills/list`, `skills/get`, `agents/list` and `agents/get` answer
  `Method not found`; before K3 kb declared and answered both from boot. Legacy `initialize`
  still declares the Skills extension from boot (SKL-44, AGT-1).
- **N18.** A library's and a folder's `_index.json` carry the gateway prefix, on every address in
  them (each `uri` and any in a description), as their `_index.md` does and kubed-mcp's
  `_index.json` inside a skill does (GW-5): one writer for every text a client reads (SKL-56).
  Before K3 they were written without it.

Everything else stays the same as the before-dump, under all ten scopes, with and without `kb+`.

## The spec, as the PR leaves it

- **[skills.md](../specs/skills.md):**
  - SKL-2 and SKL-7 go;
  - SKL-1, SKL-10, SKL-24, SKL-37, SKL-45, SKL-52 (its plugin-root-skill clause) and SKL-58 are
    reworded;
  - SKL-59 (a library's namespaces and its main plugin) and SKL-60 (kb's rewriter) are new;
  - SKL-3, SKL-13, SKL-14, SKL-21 to SKL-23 and SKL-39 are reworded too (N13, N14, N16, D9);
  - SKL-44 is reworded (N17), and SKL-56 notes the prefix (N18).
- **[plugins-and-libraries.md](../specs/plugins-and-libraries.md):**
  - PLG-9 and PLG-20 are reworded: a skill is found the native way, and a declared plugin's
    `skills:` is folders;
  - LIB-32 goes;
  - LIB-33 is reworded;
  - LIB-29 gains: a plugin kubed-mcp refuses is reported the same way.
- **[config-and-sources.md](../specs/config-and-sources.md):** SRC-53 is reworded: the
  served-tree loader for every scheme replaces `LocalLoader`. CFG-14 refuses a glob in
  `skills:`, and SRC-21 is the one-request-late live re-read.
- **[scoping-and-instructions.md](../specs/scoping-and-instructions.md):** SCP-36 is new: one
  build per admitted set, `EMPTY` shared, and a refused scope builds nothing. SCP-2 and SCP-3
  gain `Kb-Resources` and `Kb-Prompts`.
- **[http-and-tools.md](../specs/http-and-tools.md):** the TOOL rows for `list_resources` and
  `read_resource` point at kubed-mcp's DLV-6, and their `?resources=` switch at DLV-2: TOOL-1
  (up to four tools, N17), TOOL-3, TOOL-4, TOOL-6, TOOL-8, TOOL-10 to TOOL-12 and TOOL-14;
  HTTP-27 says when the extensions are declared (N17).
- **[agents.md](../specs/agents.md):** AGT-1 is reworded (N17); AGT-7 to AGT-9 and AGT-17 say
  kubed-mcp serves them (PLUG-63, PLUG-64, PLUG-73) with kb's `_meta` and rewriter; AGT-16 is
  reworded to D9's re-add (N6); AGT-18 is new and names the `agents://` file (N7).

## Settled by Dr K (2026-11-25)

1. **Rule 2 of the main plugin** is a marketplace with exactly one entry, whatever its path,
   counting skipped entries. On today's live sources, superpowers, n8n-skills, penpot-ai-kit and
   svelte collapse onto their library, and grafana's seven entries nest. svelte's one entry
   (`./plugins/claude/svelte`) is main by rule 2, and by rule 1 as well.
2. **D8.1:** `listed` is none in `config.delivery` until #86, so K3 keeps the index-only
   listing. Dr K is making sure quick-mcp#21 accepts an empty `listed`.
3. **D8.2:** kubed-mcp's resource tools replace kb's in K3, with any change in their output as
   N4. This is the epic's "the generic resources-off tools replace kb's mirror tools", one phase
   early. There is no holding knob in quick-mcp.

`plan approved` follows once `kubed-mcp==0.2.0rc2` is published.

4. **Agents (2026-11-25 05:56), option 3 of three:** kubed-mcp serves kb's agents in K3 (D11), and
   kb's `AgentsExtension` goes. The other two options, a quick-mcp switch that lets a server
   keep its own agents extension or serves skills alone, exist only to stage adoption, the kind
   of knob ruled out for the resource tools. Commands are skipped with a `command_reader` until
   K4, and kb passes no empty component lists, so RF4 no longer arises. The pin stays
   `kubed-mcp==0.2.0rc2` for K3; mcp-kb#92 moves it to rc3 after the merge.
5. **Live re-read (2026-11-25 07:36), option 2 of three:** accept one request late (D9, N6), on
   rc2. Option 1, letting the view's re-read land in its own request, is quick-mcp#45. Option 3,
   a kb middleware before the pin, is ruled out.
