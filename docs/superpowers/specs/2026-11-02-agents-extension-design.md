# Agents over MCP, and plugin.json parity — design

**Date:** 2026-11-02 · **Branch:** `agents-extension` · **Status:** draft, for review

## Intent

Plugins ship agents beside their skills and commands: kubed-io/skills' drawio plugin now has
`agents/diagrammer.md`. kb serves the skills and the commands; the agent it ignores.

An agent definition is not something to read. A host loads it and runs it as a subagent with its
own prompt, model and tools. Serving one as a `skill://`-style resource would hand a client a page
of Markdown it can do nothing with, and could even be taken as instructions by whoever reads it.
So kb serves agents the way MCP itself proposes to: the draft **Agent Discovery Extension**
(`io.modelcontextprotocol/agents`), `agents/list` and `agents/get`. No client uses it yet. kb
supports the proposed interface now and follows the draft as it moves.

The second half is parity. Dr K wants kb to read a plugin exactly as Claude Code does, so one
`plugin.json` means one thing everywhere. Today it doesn't, in two ways that can drop content or a
whole plugin.

## Background

Checked on 2026-11-02, mcp-kb `main` at `45d76c7`, Claude Code 2.1.316.

**The draft extension.**
[agents-wg proposal 0000](https://github.com/modelcontextprotocol/agents-wg/blob/main/proposals/0000-mcp-agent-discovery-extension.md):
it's a draft created 2026-08-20, has no spec PR yet, and specifies against protocol revision
2026-07-28. Its Agents group became an interest group on 2026-10-16.

- `agents/list` returns paginated cards: `name`, optional `description`, `capabilities: string[]`
  (routing labels, not tool names), plus `ttlMs` and `cacheScope`.
- `agents/get {name}` returns `agent`, optional `instructions`, optional
  `modelRoutingHint {role: small|medium|large, vision: boolean}`, and `tools: Tool[]`.
- **Every returned tool MUST be in the same server's `tools/list`** for that caller. A tool the
  server doesn't have is `invalid_agent_definition` (-32603).
- An unknown or hidden agent is `-32602` with `data.reason: "agent_not_found"`.
- The draft rejects "resources as agent cards" by name: a client would show them as ordinary
  content.
- There's no execution method. The host builds a local subagent from the instructions and tools.

**Claude Code.**
- Subagents come only from managed settings, `--agents`, `.claude/agents/`, the user's `agents/`
  and enabled plugins. No MCP source.
- A plugin agent is named `<plugin>:<agent>`, and subfolders of `agents/` become part of the name.
- Plugin agents ignore `mcpServers`, `hooks` and `permissionMode`.
- A model can't load an agent from Markdown it reads. It can only write the file where Claude Code
  looks and wait for the next turn. Building the agent is the host's job, which is what the draft's
  host-side construction is for.

**kb today.**
- No agents are harvested.
- `skill://drawio/agents/diagrammer.md` is readable through the plugin-root fallback, but no listing
  shows it.
- The Skills extension (#23) is the precedent for this one: a FastMCP `ServerExtension` with its own
  JSON-RPC methods beside the resources.
- Through agentgateway 1.6, unknown methods are refused (agentgateway#3579, the reason `skills/list`
  only works in-cluster). The same will hold for `agents/*`.
- Saga §C1.8 planned agents as `agent://` resources. **This spec supersedes that**, for the reason
  the draft gives.

**Parity gaps** (Claude Code per the [plugin manifest reference](https://code.claude.com/docs/en/plugins-reference)):

| `plugin.json` key | Claude Code | kb today |
|---|---|---|
| `skills` | **Adds** to the `skills/` scan | Replaces it (`manifest.py`) |
| `commands` | Replaces the `commands/` scan; a path, a list, **or an object map** of name → `{source \| content, description, argumentHint, model, allowedTools}` | Path or list only. **A map raises, and the plugin fails to load** |
| `agents` | Replaces the `agents/` scan; `.md` files, not directories | Not read |
| Marketplace entry beside a `plugin.json` | `strict` (default true): the entry's `commands`, `agents`, `skills` are **appended**. `strict: false` with any of them: conflict, the plugin doesn't load | The entry is never merged with the manifest |

## Goals

1. Serve plugin agents through `io.modelcontextprotocol/agents`, as the draft specifies.
2. Read `plugin.json` and marketplace entries the way Claude Code does, for every kind kb serves:
   skills, commands, agents.
3. Report agents in `/health` like skills and prompts: counts per plugin and library, and skipped
   files with their reasons.

## Non-goals

- **A tool mirror** (`list_agents`/`get_agent` for clients without the extension). Dr K: an agent
  handed over as data is useless to a model; extension only.
- **`agent://` resources.** Superseded, above.
- **Agents from anywhere but plugins.** Copilot `.github/agents/*.agent.md` and the drive's
  `agents/` wait. This round is about fitting the plugin format properly.
- **Running agents.** kb serves definitions; the host runs them.
- **The preloader.** See *Notes*.
- **The other plugin kinds.** Hooks, MCP and LSP servers, monitors, workflows and `bin/` are
  executable or configuration, and kb never runs what it fetches. Output styles and themes aren't
  served either.

## Anti-goals

- **A tool claimed that kb doesn't have.** The draft forbids it, and a host acting on it would call
  a tool that isn't there.
- **An agent definition served as plain content** that a client lists or a model reads as
  instructions.
- **A plugin that loads in Claude Code and fails in kb, or the reverse.**

## Part 1 — The agents extension

### Where agents come from

Plugins only, and only **Claude-format plugins**: those with a `plugin.json` or a marketplace
entry. A plugin declared bare in the config (the `drive` folder, whose `agents/` waits) gets no
agent scan. **My call**, following "plugins only". A config `agents:` glob can come with the drive
later. Read as Claude Code reads them:

- **The default scan.** `agents/` at the plugin root, `*.md`, with subfolders.
- **The manifest.** `plugin.json`'s `agents` (a path or a list of `.md` files) replaces the default
  scan.
- **The marketplace entry.** A marketplace entry's `agents` follows the merge rules in Part 2.

An agent file is YAML frontmatter plus a Markdown body. Claude Code requires `name` and
`description` and knows the agent by `name`, so kb does too. A file missing either, or one that
doesn't parse, is skipped with its reason in `/health`, the way a bad prompt file is.

### The card (`agents/list`)

| Field | From |
|---|---|
| `name` | `<library>_<frontmatter name>`, the same pattern as prompts: `drawio_diagrammer`. **The frontmatter `name`, not the file stem**, because that's the name Claude Code uses; a file whose stem differs is served under its `name`. Where Claude Code adds a subfolder segment to the name, kb adds it with `_`. The builder checks Claude Code's exact rule. The draft only requires names to be unique within what a client sees, and the library prefix guarantees it across libraries |
| `description` | The frontmatter `description` |
| `capabilities` | The frontmatter `capabilities` list when the author wrote one, else `[]`. **My call:** plugin keywords (`mcp`, `drawio`) are discovery tags, not routing labels |

### The details (`agents/get`)

| Field | From |
|---|---|
| `agent` | The name |
| `instructions` | The body, with `${CLAUDE_PLUGIN_ROOT}` rendered as it is for prompts and skills (`skill://<library>`). Placeholders only the client can fill (`${user_config.*}`, `${CLAUDE_PROJECT_DIR}`) are left as written |
| `modelRoutingHint` | From `model`: `haiku` → `small`, `sonnet` → `medium`, `opus` → `large`. `inherit`, no `model`, or anything else → omitted. `vision: false` |
| `tools` | **Always `[]`.** See *The tools question* |
| `_meta["io.kubed.mcp-kb/agent"]` | The rest of the definition, so a host can rebuild the exact agent: the plugin, its library, the file's path in the plugin, the **frontmatter verbatim** (`tools`, `model`, `skills`, `mcpServers`, `color`, …), and the **names of the MCP servers its plugin declares** (root `.mcp.json` or the manifest's `mcpServers`). Names only, never their configuration |

### Scope, caching, negotiation, errors

- **Scope** works as it does for prompts: library, category and tag pick the plugins, and their
  agents come with them. An agent outside the caller's scope is `agent_not_found`, the same answer
  as an agent that doesn't exist.
- **Caching:** `cacheScope: "private"`, because responses differ by scope. The TTL is the builder's
  call; the source's `refresh` is a sensible default.
- **Negotiation** works the way the Skills extension does today, legacy `initialize` included.
  `listChanged: false` for now. A reindex could notify later.
- **Errors:** `agent_not_found` as the draft words it. `invalid_agent_definition` can't arise
  while `tools` is empty.
- **Nothing changes for a client that doesn't declare the extension.** No new tools, no new
  resources.
- **The plugin-root fallback stops serving files under a plugin's agent paths. My call:** that is
  the "plain content" anti-goal, and today it's only an accident of the fallback.

### The tools question, and the gateway

`tools` is empty because kb's own tools are the read mirror, and an agent's tools live elsewhere:
drawio:diagrammer needs the draw.io editor's MCP tools and Claude Code's built-ins. The draft lets
a server return only tools from its own `tools/list`.

Two ideas, recorded here and not built:

- **The gateway is the server that has both.** Where agentgateway multiplexes kb with the tool
  server (the drawio, penpot and grafana gateways do), the client sees one server whose `tools/list`
  holds the tool server's tools. That gateway could answer `agents/get` by joining kb's definition
  (from `_meta`) with its own merged catalogue, under its prefix rules. That's agentgateway's job,
  not kb's, and it needs agentgateway to pass the extension through first (#3579).
- **A plugin's own MCP servers.** A plugin declares MCP servers (root `.mcp.json` or
  `mcpServers`). Their names go in `_meta` today, so a host or a gateway knows which servers the
  agent expects. Serving the configuration itself, perhaps as Server Cards (SEP-2127), is a later
  idea. kb never connects to them or runs them.

## Part 2 — plugin.json parity for skills, commands and agents

kb reads `plugin.json` and the marketplace entry exactly as Claude Code does, for the three kinds
it serves:

| Key | Behaviour to match |
|---|---|
| `skills` | **Adds** directories to the default `skills/` scan. `"."` and `"./"` mean the plugin root |
| `commands` | **Replaces** the default `commands/` scan. A path or list (a file is itself, a directory is its `*.md`), **or an object map**: the key is the prompt's name, `source` is a file, `content` is an inline body, and `description` and `argumentHint` fill the prompt's description and free-text argument. `model` and `allowedTools` are dropped like the other client-only keys |
| `agents` | **Replaces** the default `agents/` scan. `.md` files only |
| Marketplace entry, no `plugin.json` | The entry is the manifest |
| Marketplace entry whose `source` is the marketplace root and that lists `skills` | **Only those directories** load; the default skill scan is off. Only for root-source entries, as Claude Code documents. This is grafana/skills' shape: seven entries, all `./`, each naming its own skills. Without this rule every entry would claim all 51 skills, and every one after the first would fail in the library |
| Marketplace entry and `plugin.json`, `strict` absent or true | The entry's `skills`, `commands`, `agents` are **appended** to the manifest's |
| Marketplace entry and `plugin.json`, `strict: false` | An entry naming any of them is a conflict: the plugin is skipped with Claude Code's reason (`conflicting manifests`) |
| A replacing key set while its default folder exists | Served as Claude Code does (the folder is ignored), with a `/health` note matching Claude Code's warning: `Default <folder>/ folder is ignored because the manifest sets "<key>"` |

**kb's conventions are wider than Claude Code's**, so "the default scan" needs pinning down. **My
calls:**

- A replacing key (`commands`, `agents`) replaces **all** of kb's conventions for that kind, as
  `commands` does today. So penpot, which declares its commands under `prompts/`, keeps serving
  exactly those, and not `prompts/README.md`.
- The adding key (`skills`) adds to **all** of kb's skill roots, so nothing kb serves today drops
  out.
- The config's own `skills:` and `prompts:` still override the manifest completely, as today. The
  config is the operator's word.

Paths that don't start with `./` fail `claude plugin validate`. **My call:** kb keeps accepting
them, since it serves rather than validates, and notes them in `/health`.

## Acceptance

- **drawio** (kubed-io/skills at `d8a83e5`), in the drawio scope:
  - `agents/list` returns one card, `drawio_diagrammer`, with its description and
    `capabilities: []`.
  - `agents/get` returns the body as `instructions`, `modelRoutingHint {role: medium, vision:
    false}`, `tools: []`, and `_meta` holding the frontmatter.
  - `skill://drawio/agents/diagrammer.md` no longer reads.
- **Out of scope.** A client scoped to another library sees no drawio agent, and `agents/get` for
  it is `agent_not_found`.
- **No extension.** A client that doesn't declare the extension sees exactly what it saw before.
- **`/health`** shows `agents: 1` for the drawio plugin.
- **Parity:**
  - A plugin whose manifest says `"skills": ["./extra/"]` serves `skills/` and `extra/`.
  - A plugin with an object-map `commands` loads, and serves both `source` and `content` commands.
  - A manifest `agents` list hides the rest of `agents/`.
  - An entry under `strict: false` that names components is skipped with the conflict reason.
  - grafana/skills still serves each of its seven plugins with its own skills.
  - penpot still serves its 8 commands and nothing else from `prompts/`.
  - An agent file without `name` is skipped with that reason.
  - The drive gets no agents.
- **Through agentgateway**, `agents/*` is refused like `skills/list` until #3579. That's expected,
  not a failure of this work.

## Left to the builder

- Where the extension lives (beside `mcp/skills.py`) and how it reads the snapshot.
- Whether parity lands before, with, or after the extension.
- Pagination size, TTL, and how a skipped agent file is worded.
- The README and wiki text, which marks the extension **experimental** and names the draft it
  follows.

## Notes

- **The preloader is not kb's.** Until a host speaks the extension, a small client-side script
  could stand in. It would call `agents/list` and `agents/get` and write each agent from its `_meta`
  into `.claude/agents/<name>.md`, the user's `agents/`, or an `--agents` JSON file. Claude Code
  picks up a changed file in an existing `agents/` folder by itself. The script is a stopgap that
  lives outside this repository, and `_meta` keeping the frontmatter verbatim is what makes it
  possible.
- **Plugin features to weigh later:**
  - Output styles (Markdown that changes the main session's system prompt).
  - `dependencies`: a library could pull in what its plugins need.
  - `userConfig` placeholders, already left as written.
  - `settings.agent`: a plugin that runs the whole session as one of its agents.
- **The draft will move.** Track agents-wg. If the wire shape changes before kb ships this, follow
  the newest draft, and say which one in the README.
