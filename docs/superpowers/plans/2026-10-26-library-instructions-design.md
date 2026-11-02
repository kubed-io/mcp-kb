# Library instructions — design

**Date:** 2026-10-26 · **Branch:** `library-instructions` · **Status:** draft, for review

## Goal

The MCP `instructions` a client receives on connecting are built from the libraries that
connection's scope selects, not one fixed text. Each library carries its own text. It defaults
to what its upstream publishes, and `config.yaml` can replace it or add notes after it. kb's own
wording shrinks to a short footer on how to read skills.

The aim is parity with a client's native skills: the model knows what a library is for and what
skills it holds from the moment it connects, and reads a skill only when it uses one.

## Background

Checked on 2026-10-26.

**The protocol.**

- `instructions` is one optional string on the `initialize` result and, from 2026-07-28, on
  `server/discover`. The schema calls it guidance that "should focus on information that helps
  the model use the server effectively".
- The Skills extension (`io.modelcontextprotocol/skills`) says skills suit "workflows too large to
  fit in server instructions". Under *Pointer from Server Instructions* it says a server **may**
  point the agent at skill URIs from its instructions.
- A host that implements the extension builds its own skill list from `skills/list`.
- Client capabilities, `extensions` included, travel on every request in 2026-07-28
  (`_meta["io.modelcontextprotocol/clientCapabilities"]`), and servers must not infer them from
  earlier requests. In the handshake era they arrive in `initialize`.

**Claude Code** (2.1.310, docs at code.claude.com):

- **Skills.** It does not consume `skills/list`, and `skill://` resources never reach its native
  skill listing.
- **What loads at session start.** Only tool names and server instructions; tool definitions load
  through tool search. Server instructions sit in the system prompt, so they are re-sent every turn
  and survive compaction. A resource read is chat history and does not.
- **The cut.** Server instructions are cut at **4,096 characters** by default, and the model sees
  only the text before the cut. `CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH` changes that.
- **Its own list.** The native skill listing always carries every name. Descriptions share a budget
  of 1% of the context window, are capped at 1,536 characters each, and are dropped for the
  least-used skills first.

**Upstream "instructions".** The Agent Skills spec defines nothing above a single skill. A
marketplace has a one-line `description` (top level, or `metadata.description`), and so does each
plugin. A repository's `AGENTS.md` or `CLAUDE.md` is guidance for contributors to that repo
(grafana, superpowers, n8n), with penpot the exception. superpowers and n8n inject their real
always-on text with SessionStart hooks, which are shell commands.

**Sizes on the live server.** "Full list" is name plus description; "names" is the URI-derived
name, an upper bound on the paths this design lists.

| Library | Skills | Full list | Names |
|---|---|---|---|
| grafana | 52 | 41,221 chars | 2,457 |
| penpot | 14 | 8,285 | 525 |
| n8n | 15 | 7,462 | 604 |
| superpowers | 15 | 3,019 | 656 |
| svelte | 2 | 627 | 77 |

**agentgateway** (1.6.0, `crates/agentgateway/src/mcp/handler.rs`):

- A multiplexed backend merges its targets' instructions as
  `<preamble>\n\n[<target>]\n<instructions>`.
- It rewrites every resource URI to `<target>+<uri>` and refuses a bare one. kb served behind it
  therefore has to run in tools mode (`X-MCP-Resources: off`), because skill text cites bare
  `skill://` URIs.

## Decisions

### D1. Instructions are built per connection

They are built for each `initialize` and `server/discover` answer, from the current snapshot, the
request's scope (`X-Skill-Library`, `X-Skill-Categories`, `X-Skill-Tags` or their query
parameters), its resources mode and its client capabilities. The fixed `INSTRUCTIONS` text in
`server.py` is removed.

A session keeps the text it was given. MCP has no notification for changed instructions, and a
reconnect picks up a new text.

### D2. A library is selected when it has a skill in scope

A library appears in the instructions when at least one of its skills is in the request's scope.
How the scope got there does not matter: `X-Skill-Library: penpot` and a tag that matches only
penpot's plugins both select penpot alone. A library with nothing in scope, `kubed` today, is
left out.

### D3. A library's section

In order:

1. **Text.** The library's resolved description (D6).
2. **Notes.** The library's `notes`, when set.
3. **Pointer.** One line naming the library's index:

   ```
   Skills: skill://penpot/_index.md
   ```

4. **Names**, appended to the pointer line, only when every one of these holds:
   - the scope selects exactly one library;
   - that library has `listSkills` true (the default);
   - the request's client capabilities do not declare `io.modelcontextprotocol/skills`. A client
     that consumes `skills/list` builds its own list.

   Each skill is written as its path under the library, so the footer's rule turns it into a URI:

   ```
   Skills (skill://penpot/_index.md): penpot-router, penpot-build-screen, penpot-build-deck, …
   Skills (skill://grafana/_index.md): grafana-lgtm/loki, grafana-lgtm/tempo, …
   ```

The skills listed are those in scope, in index order. A scope narrowed by tag lists only the
skills it admits.

### D4. Layout

- **One library selected:** its section with no heading, then the footer.
- **Several:** each section under a `[<library>]` heading in config order, blank line between,
  then the footer once. This is the shape agentgateway uses when it merges servers.
- **None selected:** the footer alone. What an empty scope does to other requests (`pins.py`) is
  unchanged.

The footer comes last, because a client that cuts the text cuts from the end and the library
sections matter more.

### D5. The footer follows the client's mode

- **Resources mode** (the default). Claude Code's own resource reader knows nothing of
  `skill://`, so the footer gives the two rules: a listed path `<path>` is read at
  `skill://<library>/<path>/SKILL.md`, and its `_manifest` in place of `SKILL.md` lists what else
  it ships.
- **Tools mode** (`X-MCP-Resources: off` / `?resources=off`). One line: read these with
  `read_resource`. That tool's description already carries the address format, and naming it is
  what lets a client that defers tools find it.

The footer is not configurable. Anything a library needs to add goes in its `notes`.

### D7. Indexes open with the same text

A library's `_index.md` opens with its resolved description and notes, between the heading and the
skill lines. Reading the index then says what the instructions say.

### D8. `/health`

A library's `description` in `/health` is the resolved one, configured or upstream, so an operator
sees the text clients get.

### D9. Names

The new config keys are `notes` and `listSkills`. There is no config key called `instructions`:
the saga's carried-forward E5 reserves that word for `instructions://` resources (files such as
`AGENTS.md` served as resources), which are a different thing.

## Config (D6)

```yaml
libraries:
- name: penpot
  # The library's text in the instructions, its index and /health. Leave it out
  # to use upstream's.
  description: Penpot design tooling.
  source: github://penpot/penpot-ai-kit?ref=fe4f99e51c7149512d50cd75f0d55204c2458664
  # Added after the description, configured or upstream.
  notes: |
    Start at penpot-router. Call high_level_overview before any Penpot write.

- name: grafana
  source: github://grafana/skills?ref=cc33318b60a7fbc2c69a25122164baf00e805f79
  listSkills: false   # default true
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `description` | string | `""` | Replaces the upstream text. Unchanged as a key; it gains a use. |
| `notes` | string | `""` | Added after the description. Works over an upstream description too. |
| `listSkills` | boolean | `true` | Whether D3's names may appear. |

**The resolved description** is the first non-empty of:

1. the library's configured `description`;
2. a marketplace library's own `marketplace.json` description: top-level `description`, else
   `metadata.description`;
3. the descriptions of the library's plugins, one per line in the library's plugin order;
4. nothing. The section then starts at its notes or its pointer.

Fetched text is untrusted, like every other field kb reads from a marketplace. The guard that
already scrubs marketplace fields for `/health` and logs applies to the resolved description too.

## Examples

Unscoped connection, resources mode, today's cluster config (`kubed` has no skills, so it is left
out):

```
[grafana]
Grafana, Loki and the rest of the LGTM stack — skills and prompts.
Skills: skill://grafana/_index.md

[n8n]
n8n workflows — the upstream skills and the n8n MCP server's own material.
Skills: skill://n8n/_index.md

[penpot]
…

Read a listed skill at skill://<library>/<path>/SKILL.md; read its _manifest in place of
SKILL.md for the other files it ships.
```

`X-Skill-Library: penpot` with `X-MCP-Resources: off`, as it would sit behind a multiplexed
gateway:

```
Penpot design tooling.
Start at penpot-router. Call high_level_overview before any Penpot write.
Skills (skill://penpot/_index.md): penpot-anti-slop, penpot-audit-accessibility, …, penpot-router

Read these with read_resource.
```

## Where it goes

This follows AGENTS.md's *Where code goes*:

- **`config.py`.** `LibraryConfig` gains `notes` and `list_skills` (alias `listSkills`).
  `config.schema.json` is regenerated.
- **`plugins/marketplace.py`.** `Marketplace` carries the catalog's own description.
- **`catalogue/`.** The resolved description lives on the snapshot's `Library`. Building the text
  from (snapshot, scope, mode, extension declared) is pure, imports no FastMCP, and lives in its
  own module. The index body (D7) takes the same text.
- **`mcp/`.** A middleware sets `instructions` on the `initialize` and `server/discover` results,
  beside `AdvertiseLegacySkills`. Reading whether the client declared the Skills extension sits in
  `request.py` with the other "what does this request say" helpers.

## Acceptance

Each case goes through the real entry point: an MCP client over HTTP against the app, with the
headers set. It does not call the builder alone. Each case must fail when its rule is broken.

1. `X-Skill-Library: penpot` gets no heading, penpot's description and notes, and a pointer with
   every penpot skill's path.
2. A tag scope that admits plugins of two libraries gets two `[name]` sections and no names.
3. No scope gets every library that has a skill, in config order, and no names. A library with
   none is absent.
4. `listSkills: false` on the one selected library gives the pointer with no names.
5. A client declaring `io.modelcontextprotocol/skills` gets no names, through `initialize` and
   through a 2026-07-28 request's `_meta`.
6. `X-MCP-Resources: off` gets the `read_resource` footer, and the default mode gets the
   `skill://` rules.
7. A configured `description` replaces the marketplace's, and with none configured the
   marketplace's is used. Each is followed by `notes` when set.
8. A library whose marketplace has no description falls back to its plugins' descriptions.
9. `skill://<library>/_index.md` opens with the same description and notes.
10. `/health` shows the resolved description.
11. A refresh that changes upstream's description reaches a new connection's instructions.
12. `server/discover` and `initialize` carry the same text for the same request.

## Docs and release

- **The README stays a short advert.** At most one line, among its feature bullets, saying a client
  connects already knowing what each library is for. The explanation goes in the wiki.
- **The wiki goes deeper.**
  - `Libraries.md` (hand-written) covers `description`, `notes` and `listSkills`, and the upstream
    fallback.
  - `Scoping.md` (hand-written) gets a section on what a client sees when it connects: the
    one-library and several-library layouts, names, and the footer by mode.
  - `Configuration.md` is generated and picks the new fields up from the schema.
- **A new hand-written wiki page, `Agentgateway.md`,** linked from `_Sidebar.md`, on serving kb
  behind agentgateway, as this cluster does:
  - one kb per scope, or kb as one target of a multiplexed backend beside the server its skills
    are for (penpot plus kb scoped to penpot);
  - why that target runs in tools mode: the `<target>+<uri>` rewrite, and bare `skill://` refused;
  - setting `X-Skill-Library` and `X-MCP-Resources` as route headers;
  - how the instructions arrive, under `[kb]` after the gateway's preamble;
  - the gateway facts that bite: the caller's Host is forwarded, MCP calls time out at 10 s
    unless the route sets `requestTimeout`, `failureMode: FailOpen` keeps one dead target from
    taking the rest down, and `skills/list` is refused through the gateway (agentgateway#3579).
- Wiki changes are committed and pushed in the wiki submodule before the superproject's pointer.
  CI checks the submodule out and fails in seconds on a commit the wiki remote lacks.
- CHANGELOG entry. The AGENTS.md layout table gets the new module.
- After release, the cluster install (`cluster/mcp/mcp-kb/config.yaml`) moves to the new tag and
  adds notes where they help, such as penpot's start skill. That is the installer's change, not
  this repo's.

## Not in scope

- Skill descriptions in the instructions, or a character budget. The pointer, plus names for one
  library, stands in for both.
- Reading `AGENTS.md`, `CLAUDE.md` or SessionStart hooks as library text.
- A configurable footer or preamble.
- agentgateway's preamble, or any gateway configuration. The wiki page documents it; this repo
  ships none.
- E5's `instructions://` and `agent://` resources.
