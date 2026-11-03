# Agents

kb serves the subagent definitions that plugins ship, through the draft MCP Agent Discovery
Extension (`io.modelcontextprotocol/agents`, agents-wg proposal 0000 at `137d88b`, targeting MCP
`2026-07-28`). It serves definitions only. The host builds and runs the agent. Agents are never
served as resources, prompts or tools.

**The extension is experimental, and kb follows the draft named above.** The README names the
draft and marks the extension experimental. The rule behind every choice here is Claude Code's: a
plugin's agents mean in kb what they mean there.

## Negotiation

**AGT-1.** kb declares `io.modelcontextprotocol/agents` with `{"listChanged": false}` on both
`server/discover` and legacy `initialize`, beside
`io.modelcontextprotocol/skills` (HTTP-27). kb sends no `notifications/agents/list_changed`.

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
or a marketplace entry. A plugin declared bare in the config has no agents.

**AGT-5.** A plugin's agents are the `*.md` files under its `agents/` folder,
subfolders included, unless its `plugin.json` or its marketplace entry lists `agents`. Then the
list decides, by the rules in [plugins-and-libraries.md](plugins-and-libraries.md). An entry
whose path does not end in `.md`, a directory included, is dropped with the note
`agents entry '<path>' is not a .md file`. A listed path is a path, not a glob, and names the
one file it spells, in a dot folder too; a `.md` path that names no file in the plugin, or one
that resolves outside it, serves nothing and is noted `agents entry '<path>' is not in the
plugin` (PLG-26).

**AGT-6.** An agent file is YAML frontmatter and a Markdown body. Its frontmatter MUST parse into
a non-empty mapping with string keys, convert to JSON, and carry `name` and `description` as
non-empty strings. The `name` MUST be a usable name, as a `commands` map key is (PLG-21): no
whitespace, control or other invisible character, `/` or `@`, so no file can take the
`<name>@<plugin name>` a rename gives (AGT-8); one that is not is skipped with
`agent frontmatter name is not a usable name`. A file that breaks any of these, that cannot be read, or that is not UTF-8 is
skipped and listed with its reason under its plugin's `skipped` in `/health`; it never fails the
plugin. Two files of one plugin that take the same name (AGT-7): the first in path order is served
and the rest are skipped, each with `agent <name> is already served by <path>`.

## The roster: `agents/list`

**AGT-7.** `agents/list` takes no params but an optional `cursor`, and returns a card
for every agent in the caller's scope (AGT-15), in name order:

| Card field | Value |
|---|---|
| `name` | Found by the default scan: `<library>_<subfolder>_…_<frontmatter name>`, one `_` segment for each folder between `agents/` and the file. Listed in a manifest or an entry: `<library>_<frontmatter name>`. Renamed by AGT-8 when it clashes |
| `description` | The frontmatter `description`, whitespace collapsed |
| `capabilities` | The frontmatter `capabilities` when it is a list of strings, else `[]` |

It does not paginate: one page holds every card, and any `cursor` fails with `-32602`
`Invalid agents cursor`, as SKL-48 does.

**AGT-8.** An agent name is unique within a library, so within anything one client
sees. A library walks its plugins in order (LIB-4) and each served agent claims its name:

- The first plugin to claim `<name>` keeps it.
- A later plugin's agent with that name is served as `<name>@<plugin name>`, and the library's
  `renamed` in `/health` maps the new name to `<name> is already served by plugin '<owner>'`,
  `<owner>` being the first claimant's plugin id. PLG-1's plugin-name pattern has no `@`, so the
  suffix never reads as a subfolder segment.
- When `<name>@<plugin name>` is taken too, that agent alone is not served in that library, and
  the library's `unserved` in `/health` lists it with its plugin, path and reason.
- A plugin that LIB-28 fails in a library serves no agents there either.
- An agent whose recorded file no longer parses when a snapshot is built, as on a cold start from
  `index.json`, still claims its name in that snapshot, serves nothing, and is listed under its
  plugin's `skipped`.

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
| `instructions` | The body, rendered as a prompt body is: `${CLAUDE_PLUGIN_ROOT}` by PRM-48 and PRM-61, every client-only placeholder left as written (PRM-50, `${CLAUDE_SKILL_DIR}` included), then the gateway prefix (SKL-41). Omitted when the body is blank |
| `modelRoutingHint` | From `model`, by family: `opus` → `{"role": "large", "vision": false}`, `sonnet` → `medium`, `haiku` → `small`, whether `model` is an alias or a full id (`claude-opus-5-5`). The value is lowercased and split into words, a word being a run of letters, and the family is the first word by position that is one of the three (`opus-then-sonnet` is `large`). Omitted for `inherit`, a missing or non-string `model`, or a value naming none of the three |
| `tools` | `[]` |
| `_meta["io.kubed.mcp-kb/agent"]` | `plugin` (its id), `library`, `path` (the file, relative to its plugin root), `frontmatter` (verbatim, as JSON), and `servers`: the names of the MCP servers the plugin declares (PLG-27) |

**AGT-10.** `tools` is always empty. The extension allows only tools from kb's own
`tools/list`, and an agent's tools belong to other servers. `_meta` carries what a host or a
gateway needs to find them. `invalid_agent_definition` therefore never arises.

**AGT-11.** kb never connects to, starts or forwards the MCP servers a plugin declares.

**AGT-16.** An agent of a live fetch is re-read on `agents/get`, as a prompt is
(PRM-60): its file is revalidated, then parsed again. When that read fails, or the file no longer
parses, `agents/get` answers from the copy parsed when the snapshot was built, and kb logs a
warning. A re-read keeps the name the snapshot serves the agent under, even when the edit changes
its frontmatter `name`, until the next refresh. `agents/list` answers from the snapshot.

## Caching and errors

**AGT-12.** Both results carry `resultType: "complete"`, `ttlMs: 0` and
`cacheScope: "private"`, as the Skills extension's do (SKL-48).

**AGT-13.** An unknown agent, and one outside the caller's scope, fail alike with
`-32602`, the message `Agent not found` and `data: {"reason": "agent_not_found"}`. A refused scope
(SCP-29) fails both methods with `-32602` and the refusal message, as SKL-50 does.

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
- `agents` for each plugin (what it yields, library-independent) and each library (what it serves);
- each skipped agent file under its plugin's `skipped`, with its reason (AGT-6, AGT-8), and each
  dropped or missing `agents` entry under its `notes` (AGT-5);
- a library's `renamed` and `unserved` (AGT-8), each present only when not empty.
