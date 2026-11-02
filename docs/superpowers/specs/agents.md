# Agents

kb serves the subagent definitions that plugins ship, through the draft MCP Agent Discovery
Extension (`io.modelcontextprotocol/agents`, agents-wg proposal 0000). It serves definitions only.
The host builds and runs the agent. Agents are never served as resources, prompts or tools.

**Every requirement in this file is proposed.** kb follows the newest draft of the extension and
names it in the README, where the extension is marked experimental.

## Negotiation

**AGT-1.** *(proposed)* kb declares `io.modelcontextprotocol/agents` in its capabilities, the same
way it declares the Skills extension, legacy `initialize` included, with `listChanged: false`.

**AGT-2.** *(proposed)* A client that doesn't declare the extension sees nothing different: no
added tools, resources, prompts or instructions.

**AGT-3.** *(proposed)* No resource serves an agent file. The plugin-root fallback (see
[skills.md](skills.md)) refuses any path under a plugin's agent paths.

## Which files are agents

**AGT-4.** *(proposed)* Agents come only from Claude-format plugins: a plugin with a `plugin.json`
or a marketplace entry. A plugin declared bare in the config has no agents.

**AGT-5.** *(proposed)* A plugin's agents are the `*.md` files under its `agents/` folder,
subfolders included, unless `plugin.json` or the marketplace entry lists `agents`. Then the list
decides, by the rules in [plugins-and-libraries.md](plugins-and-libraries.md).

**AGT-6.** *(proposed)* An agent file is YAML frontmatter and a Markdown body. Its frontmatter MUST
carry `name` and `description`. A file without them, or one that doesn't parse, is skipped and
listed with its reason under its plugin in `/health`.

## The roster: `agents/list`

**AGT-7.** *(proposed)* `agents/list` returns a card for every agent in the caller's scope (see
[scoping-and-instructions.md](scoping-and-instructions.md)), paginated by the standard MCP cursor:

| Card field | Value |
|---|---|
| `name` | `<library>_<frontmatter name>`, with any subfolder that Claude Code makes part of the agent's name joined in with `_` |
| `description` | The frontmatter `description` |
| `capabilities` | The frontmatter `capabilities` list when present, else `[]` |

**AGT-8.** *(proposed)* Agent names are unique within what one client sees. Two agents that would
take the same name in one library follow the same claim rule as prompts.

## The details: `agents/get`

**AGT-9.** *(proposed)* `agents/get {name}` returns:

| Field | Value |
|---|---|
| `agent` | The name |
| `instructions` | The body, with `${CLAUDE_PLUGIN_ROOT}` resolved as in a prompt body. Client-only placeholders such as `${user_config.*}` and `${CLAUDE_PROJECT_DIR}` are left as written |
| `modelRoutingHint` | From `model`: `haiku` → `small`, `sonnet` → `medium`, `opus` → `large`, with `vision: false`. Omitted for `inherit`, a missing `model`, or any other value |
| `tools` | `[]` |
| `_meta["io.kubed.mcp-kb/agent"]` | `plugin`, `library`, `path` (the file in its plugin), `frontmatter` (verbatim), and `servers`: the names of the MCP servers the plugin declares in `.mcp.json` or `mcpServers`, names only |

**AGT-10.** *(proposed)* `tools` is always empty. The extension allows only tools from kb's own
`tools/list`, and an agent's tools belong to other servers. `_meta` carries what a host or a
gateway needs to find them.

**AGT-11.** *(proposed)* kb never connects to, starts or forwards the MCP servers a plugin declares.

## Caching and errors

**AGT-12.** *(proposed)* Both results carry `cacheScope: "private"` and a `ttlMs`.

**AGT-13.** *(proposed)* An unknown agent, or one outside the caller's scope, is `-32602` with
`data.reason: "agent_not_found"`. The two cases look the same to the caller.

## Health

**AGT-14.** *(proposed)* `/health` counts agents for each plugin and each library, and lists
skipped agent files with their reasons.
