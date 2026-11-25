# HTTP and tools

How mcp-kb is reached: the MCP endpoint and the plain HTTP routes beside it, the protocol eras it
answers, the up to four mirror tools for clients without resources or prompts, and the container it
ships in. What the catalogue holds, how a scope narrows it and what a prompt renders are other
areas, and this file points at them.

## The HTTP surface

**HTTP-1.** Over the `http` transport the server answers MCP Streamable HTTP at `/mcp`, and three
plain HTTP routes beside it:

| Route | Answers |
|---|---|
| `GET /health` | what this process is serving |
| `POST /reindex` | a forced rebuild of every fetch, then what is served |
| `GET /openapi.yaml` | the OpenAPI document for `/health` and `/reindex` |

**HTTP-2.** The plain routes are outside the MCP protocol: they need no MCP client, no session
and no handshake.

**HTTP-3.** The plain routes ignore every scope setting (`Kb-Library`, `Kb-Category`, `Kb-Tag`,
their aliases and query parameters) and are never refused for one. Scope refusal applies to MCP
requests only, as in [scoping-and-instructions.md](scoping-and-instructions.md).

**HTTP-4.** `/health` and `/reindex` read the snapshot current when they are called, never one
captured at startup.

**HTTP-5.** Over the `stdio` transport there are no HTTP routes, no headers and no query
parameters, so every request setting in this file takes its default.

**HTTP-6.** The server binds `HOST` (default `0.0.0.0`) and `PORT` (default `8000`), chosen with
`--host`/`--port` or those environment variables. `TRANSPORT` (`--transport`) is `http` (default)
or `stdio`. The rest of the command line is in [config-and-sources.md](config-and-sources.md).

## `GET /health`

**HTTP-7.** `/health` always answers `200` with `status: "ok"` while the process serves. A fetch,
plugin or library that failed is reported inside the body, never as a failed request.

**HTTP-8.** The body has exactly these top-level fields:

| Field | Is |
|---|---|
| `status` | `"ok"` |
| `generation` | snapshots swapped in since the process started, from `0` |
| `built` | when the current snapshot was assembled |
| `skills` | skills in the current index |
| `prompts` | prompts currently served |
| `agents` | agents currently served, across libraries |
| `libraries` | one entry per configured library, keyed by name |
| `plugins` | one entry per plugin, declared or from a marketplace, keyed by plugin id |
| `fetches` | one entry per materialised tree, keyed by fetch key |

**HTTP-9.** The shape of each `libraries`, `plugins` and `fetches` entry is the one the OpenAPI
document publishes (`LibraryStatus`, `PluginStatus`, `FetchStatus`). A real response MUST validate
against it.

**HTTP-10.** A `cache: live` fetch's counters (`revalidated`, `fetched`, `cooling`) are read when
`/health` is called, not when the snapshot was built.

**HTTP-11.** Nothing in a `/health` body names a cache path or carries a credential.

## `POST /reindex`

**HTTP-12.** `/reindex` takes no input. It forces a rebuild of every fetch the config's plugins and
marketplaces name, without first comparing fingerprints.

**HTTP-13.** A successful `/reindex` answers `200` with the `/health` body plus `rebuilt`: the fetch
keys rebuilt by this pass.

**HTTP-14.** `rebuilt` leaves out a fetch whose rebuild failed with the same status and error it
already had. It includes a fetch first materialised in this pass because a re-read marketplace
gained an entry on another repository.

**HTTP-15.** When nothing is rebuilt, no snapshot is swapped in and `generation` does not move.

**HTTP-16.** A `/reindex` and the background refresh never rebuild at the same time; refreshes are
serialised and each swaps in one whole snapshot.

**HTTP-17.** If the rebuild raises, `/reindex` answers `500` with exactly
`{"status": "error", "error": "reindex failed; see the server log"}`. The exception and its
traceback go to the log at `ERROR`, with every configured credential redacted, and never into the
body.

## `GET /openapi.yaml`

**HTTP-18.** `/openapi.yaml` serves an OpenAPI `3.1.0` document as `text/yaml`. It is built once,
when the routes are registered, and the same text is served for the life of the process.

**HTTP-19.** The document describes `/health` and `/reindex`, and every plain route registered
except `/openapi.yaml` itself MUST appear in its `paths`.

**HTTP-20.** `info.title` is `mcp-kb`. `info.version` and `info.description` come from the installed
`kubed-mcp-kb` distribution's metadata; without one they are `0.0.0` and a fixed description.
`info.license` is MIT.

**HTTP-21.** The document declares `security: []`.

**HTTP-22.** `openapi.yaml` in the repository is a generated copy for linting and is not committed.

## No authentication

**HTTP-23.** No route and no MCP request is authenticated. The server has no write path; its only
credentials are the outbound `{env: NAME}` references in the config.

**HTTP-24.** Because `/reindex` takes no input, an unauthenticated caller can only make the server
re-read what the config already names.

## Protocol eras

**HTTP-25.** The server answers both MCP eras that its FastMCP release supports: handshake-era
clients, which open with `initialize` and may hold a session (`mcp-session-id`), and modern clients
(MCP `2026-07-28`), which are sessionless and use `server/discover`.

**HTTP-26.** Both `initialize` and `server/discover` answers carry the server `instructions` built
for the caller, as in [scoping-and-instructions.md](scoping-and-instructions.md).

**HTTP-27.** Both answers advertise the `io.modelcontextprotocol/skills` and
`io.modelcontextprotocol/agents` extensions: the first once a plugin with a skill is served
(SKL-44), the second once one with a skill, an agent or a prompt file is (AGT-1). Their methods are in [skills.md](skills.md) and [agents.md](agents.md).

**HTTP-28.** Asking for a missing prompt argument by elicitation happens only on a modern
connection whose client declared form elicitation, as in [prompts.md](prompts.md).

**HTTP-41.** The server names itself `mcp-kb` with the version HTTP-20 gives
`info.version`: the installed `kubed-mcp-kb` distribution's, or `0.0.0` without one. That is the
`serverInfo` of a handshake-era `initialize` answer, and the `io.modelcontextprotocol/serverInfo`
entry FastMCP stamps in a modern-era result's `_meta`. It is never FastMCP's own version.

**HTTP-42.** Both answers also carry `_meta["io.kubed/delivery"]`: kubed-mcp's report of what it
resolved for the request, from the `Kb-` and `X-MCP-` headers, their query parameters, kb's
defaults and its table of known clients. Its `resources` is the setting that lists the resource
pair (TOOL-2), and its `prefix` is the resource prefix every served address carries (GW-4, GW-11),
or `null`.

**HTTP-29.** Every cacheable result (`tools/list`, `prompts/list`, `resources/list`,
`resources/templates/list`, `resources/read`, `server/discover`) carries `ttlMs` equal to the
shortest `refresh` interval in the config and `cacheScope: "private"`. A config with no `refresh`
sets neither. The Skills and Agents extensions' own results are in [skills.md](skills.md) and
[agents.md](agents.md).

**HTTP-30.** An HTTP request that carries an `mcp-session-id` is told once that the catalogue moved:
on its first request after the generation changes, the server sends
`notifications/resources/list_changed` and `notifications/prompts/list_changed` before answering.

**HTTP-31.** A session's first request records the current generation and announces nothing. An
HTTP request without `mcp-session-id` is never sent a list-changed notification.

**HTTP-32.** Failing to read or record a session's generation never fails the request.

## The container

**HTTP-33.** The image's entrypoint is `mcp-kb`, which serves by default; `mcp-kb schema` prints the
config JSON Schema and exits.

**HTTP-34.** The image sets `CONFIG=/etc/mcp-kb/config.yaml`, `CACHE_DIR=/var/cache/mcp-kb`,
`TRANSPORT=http`, `HOST=0.0.0.0` and `PORT=8000`, the same defaults the command line has, and
`EXPOSE`s `8000`.

**HTTP-35.** The image runs as `USER 65534`. The user MUST be numeric, because a pod with
`runAsNonRoot: true` cannot verify a named user.

**HTTP-36.** `/var/cache/mcp-kb` exists in the image, is owned by `65534:65534` and is a `VOLUME`.

**HTTP-37.** The image ships an example config at `/etc/mcp-kb/config.yaml`, so it starts with no
config mounted. It bakes in no skills; everything served is read from the config's sources at
start.

**HTTP-42.** *(proposed)* The image installs kb's `telemetry` extra, so the profiler and the
OpenTelemetry packages import in it. A plain install of the package carries neither; with a
telemetry signal on (CFG-14), such an install logs one warning naming the extra and serves without
that signal.

**HTTP-38.** The process writes only under the cache directory, so the root filesystem MAY be
read-only when the cache directory is a writable mount.

**HTTP-39.** Every log line goes to stderr in one format, `<UTC time> <LEVEL> <logger>: <message>`,
at the level set by `LOG_LEVEL` (`--log-level`, default `INFO`) for every logger in the process.

**HTTP-40.** Per-request traffic lines (uvicorn's access log, httpx's per-request lines) are
written only when the level is `DEBUG`.

## The mirror tools

**TOOL-1.** The server has up to four tools, each mirroring a native MCP feature. The prompt pair
is kb's and always registered. The resource pair is kubed-mcp's plugin layer's (DLV-6), registered
once kb adds its first plugin to the plugin set, which needs a plugin with a skill, an agent or
a prompt file; until then the server has only the prompt pair. It is switched by the request's
resources setting (DLV-2).

| Tool | Mirrors | Listed when the request says |
|---|---|---|
| `list_resources` | `resources/list` | `Kb-Resources: off`, `X-MCP-Resources: off` or `?resources=off`, or the client is VS Code (TOOL-2) |
| `read_resource` | `resources/read` | `Kb-Resources: off`, `X-MCP-Resources: off` or `?resources=off`, or the client is VS Code (TOOL-2) |
| `list_prompts` | `prompts/list` | `Kb-Prompts: off`, `X-MCP-Prompts: off` or `?prompts=off` |
| `get_prompt` | `prompts/get` | `Kb-Prompts: off`, `X-MCP-Prompts: off` or `?prompts=off` |

**TOOL-2.** A request that declares neither sees no tools in `tools/list`, unless kubed-mcp knows
its client: one whose `clientInfo.name` starts `Visual Studio Code` is taken to declare resources
off, and sees the resource pair (DLV-15). A resources setting the request sends beats the known
client, in TOOL-4's order. Each pair is listed independently of the other.

**TOOL-3.** `off`, `false`, `0`, `no` and `none` declare the feature absent, ignoring case and
surrounding space. For prompts, any other value, or none, means the client has the feature. For
resources, `on`, `true`, `1` and `yes` declare it present, any other value is passed over for the
next source with a warning (DLV-2), and none means the client has the feature, unless TOOL-2's
known clients say otherwise.

**TOOL-4.** The `Kb-` header beats the `X-MCP-` one, which beats the query parameter (SCP-3). Only
the first value of the winning one counts, and an empty value counts as not sent.

**TOOL-5.** Hiding is a listing decision only: a mirror tool is callable whether or not it is
listed.

**TOOL-6.** Every mirror tool is annotated `readOnlyHint: true`, `destructiveHint: false`,
`idempotentHint: true` and `openWorldHint: false`, with a title: "List resources", "Read a
resource", "List prompts", "Get a prompt".

**TOOL-7.** A mirror tool is held to the caller's scope exactly as the feature it mirrors is. A
scope that names nothing refuses a tool call like any other request
([scoping-and-instructions.md](scoping-and-instructions.md)).

## `list_resources` and `read_resource`

**TOOL-8.** `list_resources` takes no arguments and returns a JSON object whose `resources` is the
rows `resources/list` returns for the same request, each as it is on the wire. Its result shape and both tools'
descriptions are the plugin layer's (DLV-6): they teach neither kb's URI grammar nor its scope
settings.

**TOOL-9.** `list_resources` honours `?listing=full` (or `Kb-Listing: full`, `?skills=full`,
`X-Skill-Listing: full`) exactly as `resources/list` does. Without it the listing is indexes, as in
[skills.md](skills.md).

**TOOL-10.** `read_resource` takes one argument, `uri`, and reads it through `resources/read`, so
the same middleware, scope and addressing apply. Text comes back as text, a `text/*` or SVG blob
that is UTF-8 as its text, an image blob as image content, and any other blob as a JSON description
saying it is not returned as text (DLV-6).

**TOOL-11.** Both tools are the plugin layer's (DLV-6). `list_resources` writes the prefix into each
row's `uri` (GW-5); `read_resource` returns what `resources/read` returns, its prefix included
(SKL-41), and taking the prefix off its `uri` is GW-4's. Addressing is in [skills.md](skills.md).

**TOOL-12.** A `read_resource` that finds nothing is an error result (`isError: true`) carrying the
message `resources/read` fails with: `Resource not found: '<uri>'. <hint>` when the URI is a
directory in the caller's scope (SKL-34), and `Resource not found: '<uri>'` otherwise.

**TOOL-13.** An out-of-scope URI and an absent one give the same `read_resource` error.

**TOOL-14.** A missed `read_resource` is logged with no traceback.

## `list_prompts` and `get_prompt`

**TOOL-15.** `list_prompts` and `get_prompt` are FastMCP's prompts-as-tools, routed through the
server's own `prompts/list` and `prompts/get`, so they see exactly the prompts the caller's scope
admits.

**TOOL-16.** `list_prompts` takes no arguments and returns JSON: a list of prompts, each with its
`name`, `description` and `arguments` (`name`, `description`, `required`).

**TOOL-17.** `get_prompt` takes `name` and an optional `arguments` object, and returns JSON with a
`messages` array of role-tagged messages, as `prompts/get` renders them.

**TOOL-18.** An unknown prompt name is an error result reading
`Unknown prompt: '<name>'. Call list_prompts() for the prompts available and the arguments each one
takes.`

**TOOL-19.** A missing required argument is an error result carrying the same message
`prompts/get` refuses with. Through `get_prompt` the server never asks for it by elicitation.

**TOOL-20.** A `get_prompt` mistake is logged at `DEBUG` only, with no traceback.
