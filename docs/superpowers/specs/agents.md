# Agents

kb serves the subagent definitions that plugins ship, through the draft MCP Agent Discovery
Extension (`io.modelcontextprotocol/agents`, agents-wg proposal 0000 at `137d88b`, targeting MCP
`2026-07-28`). It serves definitions only. The host builds and runs the agent. Agents are never
served as prompts or tools, and as a resource only by AGT-18. The extension is kubed-mcp's plugin
layer's: it serves the agents of the plugins kb adds to its plugin set (SKL-58), named, read and
rewritten as this file says.

**The extension is experimental, and kb follows the draft named above.** The README names the
draft and marks the extension experimental. The rule behind every choice here is Claude Code's: a
plugin's agents mean in kb what they mean there.

## Negotiation

**AGT-1.** Once the server serves a plugin with a skill, an agent or a prompt file, it declares
`io.modelcontextprotocol/agents` with `{"listChanged": false}` on both `server/discover` and
legacy `initialize`, beside `io.modelcontextprotocol/skills` as SKL-44 declares it (HTTP-27), and
goes on declaring it for the life of the process. A plugin with only prompt files brings it too,
with no agent to list. Until then (a cold start with every source down, or a config whose plugins
have none of the three) neither answer declares it, and `agents/list` and `agents/get` answer
`-32601` `Method not found`. The server sends no `notifications/agents/list_changed`.

**AGT-2.** `agents/list` and `agents/get` answer any caller, whether or not it
declared the extension, as the Skills extension does (SKL-44). Declaring it, or not, changes
nothing else for anyone: `tools/list`, `resources/list`, `prompts/list` and the server
`instructions` are the same either way.

**AGT-3.** The plugin-root fallback (SKL-30, and the library-wide fallback of
[skills.md](skills.md)) never serves a Claude-format plugin's agent files: nothing under its
`agents/` folder, and no file its manifest or marketplace entry lists under `agents`. A `files`
glob the operator wrote that matches one still serves it as a library file, because the config is
the operator's word (LIB-33).

## Which files are agents

**AGT-4.** Agents come only from Claude-format plugins: a plugin with a `plugin.json`
or a marketplace entry. A plugin declared bare in the config has no agents: kb hands it to the
plugin layer with an empty `agents` list, so nothing in its `agents/` folder is served.

**AGT-5.** A plugin's agents are the `*.md` files under its `agents/` folder,
subfolders included, unless its `plugin.json` or its marketplace entry lists `agents`. Then the
list decides, by the rules in [plugins-and-libraries.md](plugins-and-libraries.md). An entry
whose path does not end in `.md`, a directory included, is dropped with the note
`agents entry '<path>' is not a .md file`. A listed path is a path, not a glob, and names the
one file it spells, in a dot folder too; a `.md` path that names no file in the plugin, or one
that resolves outside it, serves nothing and is noted `agents entry '<path>' is not in the
plugin` (PLG-26). The default scan adds a name segment for each folder between `agents/` and the
file (AGT-7); each segment, and the name they and the frontmatter `name` join into, MUST be a
usable name, as the frontmatter `name` is (AGT-6). A file whose name is not, `agents/x@y/r.md`, is
skipped with `agent name <name> is not a usable name`, the name quoted escaped, and never claims
the name.

**AGT-6.** An agent file is YAML frontmatter and a Markdown body. The plugin layer reads each
agent file as its plugin is added, and is the only reader that decides whether it serves: kb's
harvest records where each file is (AGT-5) and reads none. The frontmatter MUST parse into a
non-empty mapping that converts to JSON, and carry a `description` that is a non-empty string, not
whitespace alone. A `name`, when present, MUST be a non-empty string; a file whose frontmatter has
no `name` is served under its file's stem, and is not listed as skipped. The name an agent is served under MUST be a usable name:
no whitespace, control or other invisible character, `/`, `@` or `:`, so no file can take the
`<name>@<plugin name>` a rename gives (AGT-8). Two files of one plugin that take the same name
(AGT-7): the first in path order is served and the rest are skipped. A file the plugin layer refuses
is listed under its plugin's `skipped` in `/health`, with the layer's reason, and never fails the
plugin:

| The file | Its reason |
|---|---|
| No frontmatter, or frontmatter that is not YAML | `no YAML frontmatter` |
| Frontmatter that is not a non-empty mapping | `its frontmatter is not a non-empty mapping` |
| Frontmatter with no JSON form: a date, `.nan`, a key that is not a string | `its frontmatter is not representable as JSON` |
| A `name` that is present but not a non-empty string | `its name must be a non-empty string` |
| No `description`, or one that is blank | `its description must be a non-empty string` |
| A name that is not usable | `agent name '<name>' is not a usable name`, the served name, library prefix and folders included, quoted escaped |
| A later file of one plugin taking a name already taken in it | `agent <name> is already served by <path>`, the served name and the first file's path |
| A file that is not UTF-8 | The decode error, as `'utf-8' codec can't decode byte 0xe9 in position 11: invalid continuation byte`, which names no path |

kb then reads each file the layer serves for its own `_meta` key (AGT-9), with the plugin layer's own
parser, so a file the layer serves parses for kb too unless it changed between the two reads. A file
kb cannot read is skipped with `agent_meta failed: kb cannot read agent file <path>`: one that is not
a regular file inside its plugin root, by the path kb resolves, or is not UTF-8 text. A file that no
longer parses when kb reads it is skipped with `agent_meta failed: agent file <path>: <reason>`, the
reason one of the table's. For a name that is not usable, that reason quotes the frontmatter name,
or else the stem, with no library prefix or folders. An agent file the plugin layer
finds that kb's harvest did not is not served either, and is not listed under `skipped`: kb logs
`agent file <path> of plugin <id> is not served: kb's harvest did not find it` once, and the plugin
layer logs its own refusal each time the plugin is added.

## The roster: `agents/list`

**AGT-7.** `agents/list` belongs to kubed-mcp's agents extension, which declares
`io.modelcontextprotocol/agents` and binds `agents/list` and `agents/get` (kubed-mcp's PLUG-27).
The list (kubed-mcp's PLUG-30) serves the plugins kb adds to its plugin set (SKL-58) under kb's
view (PLUG-53). It takes no params but an optional `cursor`, and returns a card for every agent in the caller's scope (AGT-15), in name order:

| Card field | Value |
|---|---|
| `name` | The plugin layer's name, which is kb's (PLUG-28, PLUG-63). Found by the default scan: `<library>_<subfolder>_…_<frontmatter name>`, one `_` segment for each folder between `agents/` and the file. Listed in a manifest or an entry: `<library>_<frontmatter name>`. Renamed by AGT-8 when it clashes (PLUG-64) |
| `description` | The frontmatter `description`, whitespace collapsed |
| `capabilities` | The frontmatter `capabilities` when it is a list of strings, else `[]` |

It does not paginate: one page holds every card, and any `cursor` fails with `-32602`
`Invalid agents cursor` (PLUG-30), as SKL-48 does.

**AGT-8.** An agent name is unique within a library, so within anything one client
sees. The plugin layer claims names across the set in the order kb adds plugins: library by
library in config order, and each library's plugins in order (LIB-4). Every name starts with its
library's, so only one library's agents meet, and each served agent claims its name:

- The first plugin to claim `<name>` keeps it.
- A later plugin's agent with that name is served as `<name>@<plugin name>`, and the library's
  `renamed` in `/health` maps the new name to `<name> is already served by plugin '<owner>'`,
  `<owner>` being the first claimant's plugin id. PLG-1's plugin-name pattern has no `@`, so the
  suffix never reads as a subfolder segment.
- When `<name>@<plugin name>` is taken too, that agent alone is not served in that library, and
  the library's `unserved` in `/health` lists it with its plugin, path and reason.
- A plugin that LIB-28 fails in a library serves no agents there either.
- An agent whose file does not read when its plugin is added serves nothing, is listed under its
  plugin's `skipped` (AGT-6), and claims no name, so a later plugin's agent of that name is served
  under the name itself.

The names are decided in library order alone, as Claude Code decides which agent loads first. kb
stores no owner anywhere: the promise is that **a plugin added after a library's existing plugins
never renames an agent**. A plugin added before them, a reordered library, or the first claimant's
agent going away can rename one. Names are the library's and do not depend on the caller's scope,
so a caller that sees only a later plugin sees `<name>@<plugin name>`, and can infer that `<name>`
exists elsewhere in the library.

## The details: `agents/get`

**AGT-9.** `agents/get {name}` returns:

| Field | Value |
|---|---|
| `agent` | The name |
| `instructions` | The body, rendered by kb's rewriter (SKL-60) as a prompt body is: qualified skill names by AGT-17, `${CLAUDE_PLUGIN_ROOT}` by PRM-48 and PRM-61, every client-only placeholder left as written (PRM-50, `${CLAUDE_SKILL_DIR}` included), then the gateway prefix (SKL-41), with leading and trailing whitespace trimmed. Omitted when the body is blank |
| `modelRoutingHint` | From `model`, by family: `opus` → `{"role": "large", "vision": false}`, `sonnet` → `medium`, `haiku` → `small`, whether `model` is an alias or a full id (`claude-opus-5-5`). The value is lowercased and split into words, a word being a run of letters and digits, and the family is the first word by position that is one of the three (`opus-then-sonnet` is `large`, and `opus4` names none). Omitted for `inherit`, a missing or non-string `model`, or a value naming none of the three |
| `tools` | `[]` |
| `_meta["io.kubed.mcp-kb/agent"]` | kb's key: `plugin` (its id), `library`, `path` (the file, relative to its plugin root), `frontmatter` (verbatim, as JSON, as the plugin layer parses it), `servers`: the names of the MCP servers the plugin declares (PLG-27), and `skills` (AGT-17) |
| `_meta["io.kubed/agent"]` | The plugin layer's key: `frontmatter`, and `skills`, the `SKILL.md` URI of each of the agent's own plugin's skills its frontmatter `skills` names |

The plugin layer's agent-meta hook (PLUG-73) adds kb's key as the agent enters the plugin set. kb
reads only a regular file inside the plugin root that its harvest found as an agent file; any other
agent file is not served (AGT-6).

The gateway prefix is written over the whole agent file, so the card's `description` and
`io.kubed/agent`'s `frontmatter` carry it too, and kb's `_meta` key does not.

**AGT-10.** `tools` is always empty. The extension allows only tools from kb's own
`tools/list`, and an agent's tools belong to other servers. `_meta` carries what a host or a
gateway needs to find them. `invalid_agent_definition` therefore never arises.

**AGT-11.** kb never connects to, starts or forwards the MCP servers a plugin declares.

**AGT-16.** An agent of a live fetch is revalidated by every request that reads skills or agents
under a scope admitting its plugin (SKL-37). A file that moved re-reads its plugin, and from the
next request on `agents/list` and `agents/get` both serve the new read: the request that found the
edit still reads what it began with. An edit of the frontmatter `name` serves the agent under the
new name without a refresh, and a later plugin's agent it now clashes with is renamed by AGT-8.

An edit that no longer reads as an agent leaves the plugin serving the build it served, its skills
and prompts and the agent under its name included. It no longer reads when kb cannot read it (it
is not a regular file inside its plugin root, or not UTF-8 text) or when the plugin layer's parser
refuses it for one of AGT-6's reasons: no YAML frontmatter, frontmatter that is not a non-empty
mapping or has no JSON form, a `name` that is present but not a non-empty string, a `description`
that is not a non-empty string, or a frontmatter `name` that is not usable. The server logs one warning and reads the plugin again when
one of its files moves, as PRM-60 says for a prompt.

An edit that gives an agent a name another agent file of the same plugin serves still reads, so
nothing is kept: from the next request the first of the two files in path order is served under
that name and the other is skipped (AGT-6), as a refresh of the same tree serves them. An edit
whose new name is taken in its library, and whose `<name>@<plugin name>` is taken too, still reads
as well: from the next request that agent is not served in that library and is listed under its
`unserved` (AGT-8), as a refresh would leave it. A refresh reads the plugin from its source and has no earlier build to
keep.

**AGT-17.** `instructions` rewrites qualified skill names (SKL-54) as SKL-55 says, for the
request's scope. The agent's plugin is the own plugin and its library is the library, and the
rewrite runs before PRM-48. `_meta["io.kubed.mcp-kb/agent"]` adds `skills`, an object that maps
entries of the frontmatter `skills` to the `SKILL.md` addresses they resolve to. It is decided once
per generation, whatever the caller's scope, because the plugin layer's agent-meta hook runs as the
agent enters the plugin set, never on a read (kubed-mcp's PLUG-73); and from the agent's own plugin
alone, which every scope that sees the agent also sees.

- **Entries.** The frontmatter `skills` is a list, whose string items are the entries, or one
  string, split on `,`. Each entry is trimmed, and is the map's key as written.
- **Resolution.** A qualified name resolves by SKL-55 with the agent's own plugin as its only
  candidate, so a name of another plugin's skill never resolves. A bare `<skill>` resolves to the
  one served skill of that name in the agent's own plugin.
- **The rest.** An entry that does not resolve is left out, and so is one that resolves to a skill
  SKL-3 does not serve, and `skills` is `{}` when none are left.
  `frontmatter` stays verbatim, and the addresses are never prefixed (SKL-41).

**AGT-18.** An agent's file also reads as a resource at
`agents://<namespace>/<path>`: its plugin's namespace in the library (SKL-59), and the file's path
below `agents/`. A file from a listed folder sits below that folder, and a listed file outside both
below the plugin root. A renamed agent (AGT-8) reads at `agents://<namespace>/<name>@<plugin>.md`. It is in no listing unless
the request's `Listed` setting names `agents` (DLV-8). It is held to the request's scope as
`agents/get` is, and out of scope it fails as an absent address does. It reads as the plugin layer
builds the file, after kb's rewriter and the prefix.

## Caching and errors

**AGT-12.** Both results are kubed-mcp's agents extension's, and carry
`resultType: "complete"`, `ttlMs: 0` and `cacheScope: "private"` (kubed-mcp's PLUG-30, PLUG-31),
as the Skills extension's do (SKL-48).

**AGT-13.** An unknown agent, and one outside the caller's scope, fail alike with
`-32602`, the message `Agent not found` and `data: {"reason": "agent_not_found"}`: kubed-mcp's
agents extension's answer to a name it does not serve (kubed-mcp's PLUG-31), and kb's view leaves
an out-of-scope agent's plugin out of the request's build (PLUG-53), so the extension does not
serve it. A refused scope (SCP-29) fails both methods with `-32602` and the refusal message, as
SKL-50 does.

## Scope

**AGT-15.** An agent is in scope when its plugin is in scope in its library (SCP-20,
SCP-27): the request's library, its plugin's `category` or its library's `categories`, and its
plugin's `tags` and `keywords` under LIB-8's comma rule. The settings are those of SCP-2 to
SCP-8: `Kb-Library`, `Kb-Category`, `Kb-Tag`, their `X-Skill-*` aliases, and `?library=`,
`?category=`, `?tag=`, `?categories=`, `?tags=`. Neither method takes a library, category or tag
param (SCP-9): the connection's scope is the only filter. An agent's frontmatter `capabilities`
are not tags and narrow nothing. A scope reaching only agents is served, not refused (SCP-31).

## Health

**AGT-14.** `/health` reports:

- `agents` at the top level: the agents currently served, across libraries;
- `agents` for each plugin and each library: what the plugin layer reports serving for each plugin
  added, its agent files (PLUG-74). A plugin's count is library-independent, from the first library
  that serves it, and a plugin no library serves counts the agent files found (AGT-5);
- each agent file found that the plugin layer skipped (its plugin's skipped files, PLUG-74) under
  its plugin's `skipped`, with the layer's reason (AGT-6), and each dropped or missing `agents`
  entry under its `notes` (AGT-5);
- a library's `renamed` and `unserved` (AGT-8), as the plugin layer reports them, each present
  only when not empty. An agent whose rename is taken too is the library's `unserved`, and not its
  plugin's `skipped`.
