# Addresses that fit where kb is served — design

**Date:** 2026-10-27 · **Branch:** `addressing` · **Status:** revised, for review

## Goal

kb's resource addresses read correctly wherever kb is served, so a client uses kb's resources and
nothing else, even behind a multiplexing gateway. One request setting drives it: a **prefix
hint**. The client, or the route in front of it, tells kb what a gateway puts in front of its
addresses, e.g. `kb+`. kb then writes that prefix into every address **inside text**:
`kb+skill://penpot/penpot-router/SKILL.md`.

The motivating setup is Penpot's MCP and kb on one agentgateway backend, with kb scoped to the
`penpot` library. The client should see Penpot's tools and kb's skills as resources, with every
link working.

**Revised 2026-10-27.** The first draft also shortened addresses under an `X-Skill-Library` pin
(`skill://penpot-router/SKILL.md`). That was dropped (Dr K) for two reasons:

- The library segment is kb's equivalent of a plugin's namespace locally (`plugin:skill`), and the
  Skills extension spec's own example uses such a prefix.
- Stripping it made the skill name the URI host. URI normalisation can't climb past a host, so a
  client that normalises (the Python MCP SDK does) breaks `../` links between skills.

Addresses keep their library segment always.

## Background

Checked on 2026-10-27 against agentgateway v1.6.0 (`crates/agentgateway/src/mcp/handler.rs`) and
the 1.7.0-rc.1 release notes.

- **What the gateway does to resources.** A multiplexed backend lists, reads and merges
  resources, templates and list-changed/updated notifications. It rewrites every resource URI in a
  **structured** field to `<target>+<uri>` (`skill://penpot/x` → `kb+skill://penpot/x`). It
  refuses a read without a known `<target>+` prefix. Before forwarding a read, it removes the
  prefix again. A backend with one target rewrites nothing.
- **Text is not rewritten.** Addresses inside text go through untouched: server instructions,
  resource bodies, tool results. kb's instructions, its `_index.md` and `_files.md` bodies, read
  hints and resolved `${CLAUDE_*}` placeholders all write plain `skill://…`, which the gateway then
  refuses. Before this change, the only workaround was kb's tools mode, which hides the resources.
- **The Skills extension.** The gateway merges the extension's capability declaration but answers
  `skills/list` and `skills/get` with `unsupported method` (agentgateway#3579, still open, not in
  1.7.0-rc.1). Claude Code doesn't call them either. This design keeps the extension consistent
  without depending on it.
- **The query string is dropped**, but headers are forwarded. So the setting is read header-first,
  like kb's existing settings. In a query string, `+` decodes to a space, so kb maps a space in
  the parameter back to `+`.

## Decisions

### D1. One request setting

| Header | Query parameter | Value |
|---|---|---|
| `X-MCP-Resource-Prefix` | `prefix` | the text a gateway puts in front of kb's addresses, e.g. `kb+`: a letter, then letters, digits, `+`, `-`, `.`, ending in `+` |

The prefix applies to every resource address kb writes, not only skills, because a gateway
prefixes every resource URI. Today all of kb's resources are `skill://` addresses: indexes,
`_files.md`, manifests, library files and skills. Resources from other schemes that kb may serve
later follow the same rule.

It is read by the same header-then-query rule as the other settings. A prefix that isn't valid is
ignored, as if absent. With no prefix, nothing changes for any client. `X-Skill-Library` keeps
its meaning, a scope, and never changes an address.

### D2. Canonical inside, translated at the edge

The catalogue keeps its one grammar, `skill://<library>/<path>`. Scoping, the memoised listings,
containment checks and the index are untouched. A per-request **`Addressing`** value carries the
prefix. It translates in three directions, at the MCP boundary only:

- **Outgoing, structured:** a `uri` field kb returns. Unchanged. The prefix is **never** applied
  here: a gateway adds its own, and both together would give `kb+kb+skill://`.
- **Outgoing, text:** any text a client reads. `skill://` → `<prefix>skill://`, but only where
  `skill://` is not already part of a longer scheme. So `kb+skill://` and `myskill://` are left
  alone.
- **Incoming:** an address a client sends. kb accepts `skill://…` and `<prefix>skill://…` for the
  request's prefix, the latter mapped to `skill://…`. Everything else behaves as an unknown
  address does today.

`Addressing` is pure: it lives in `catalogue/` and imports no FastMCP. `mcp/request.py` builds it
from the request, like `requested_scope()`.

### D3. Where each kind applies

| Surface | Kind |
|---|---|
| `resources/list` rows: `uri`, `name` | structured (unchanged) |
| `resources/read`: the incoming URI | incoming |
| `resources/read`: the returned body | text |
| `resources/read`: the returned `uri` | as the client sent it |
| `NameTheFileToRead` hints and every other error message naming an address | text |
| `list_resources` tool result | text (a tool result is text; the gateway doesn't rewrite it) |
| `read_resource` tool: argument / result / error hint | incoming / text / text |
| `skills/list`, `skills/get` entries: `uri` and each file `uri` | structured (unchanged) |
| `skills/list`, `skills/get` entries: each file's digest and size | of the bytes `resources/read` serves under the same headers |
| `skills/get` argument | incoming |
| Rendered prompt text (resolved `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_SKILL_DIR}`) | text |
| Server instructions | built with the `Addressing` (D4) |

A skill's own markdown is resource body text. Any `skill://` address in it is translated,
including a placeholder kb already resolved there. Relative links inside a skill need nothing: a
client resolves them against the address it read, and the library stays the URI host.

### D4. Instructions follow the addressing

`build_instructions` takes the `Addressing`. The pointer and the footer name the addresses the
client will use. With prefix `kb+`:

- Pointer: `Skills (kb+skill://penpot/_index.md): …` (one library) or
  `Skills: kb+skill://penpot/_index.md`.
- Resources footer: `Read a listed skill at kb+skill://<library>/<path>/SKILL.md; read its
  _manifest in place of SKILL.md for the other files it ships.`
- Description and notes go through the text rule.

With no prefix, the output is byte-identical to today. The tools footer (`Read these with
read_resource.`) is unchanged.

## Example

`X-Skill-Library: penpot`, `X-MCP-Resource-Prefix: kb+`, resources mode, behind a gateway target
named `kb`. The client lists `kb+skill://penpot/_index.md` (the gateway's prefix). Reading it
(the gateway sends kb `skill://penpot/_index.md`) returns:

```
# penpot — 14 skills

Penpot design tooling.
Start at penpot-router. …

kb+skill://penpot/penpot-anti-slop/SKILL.md: Opt-in layer that keeps Penpot designs …
…
kb+skill://penpot/penpot-router/SKILL.md: Thin dispatcher / entry point for any Penpot request. …
```

Every link reads through the gateway: `kb+skill://penpot/penpot-router/SKILL.md` reaches kb as
`skill://penpot/penpot-router/SKILL.md`.

## Where it goes

- **`catalogue/addressing.py`** (new, pure): `Addressing` and its translations.
- **`mcp/request.py`**: the `X-MCP-Resource-Prefix` / `prefix` setting and
  `requested_addressing()`.
- **`mcp/resources.py`**: the provider (listing, read) and `NameTheFileToRead`.
- **`mcp/tools.py`**: the mirror tools.
- **`mcp/skills.py`**: `skills/list`, `skills/get`, including the digests of translated bytes.
- **`mcp/prompts.py`**: rendered prompt text.
- **`catalogue/instructions.py`** and **`mcp/instructions.py`**: the pointer and footer.

No `Catalogue` method changes its grammar. `Addressing` sits beside the catalogue at the edge,
not inside it.

## Acceptance

Every case runs through an MCP client over HTTP against the app. Each must fail when its rule
breaks.

1. **Defaults.** With no prefix, listings, reads, hints, tool results, prompts and instructions
   are byte-identical to before. A library pin changes no address.
2. **Prefix.** Listing `uri`s are unchanged (structured). Bodies and hints use
   `kb+skill://<library>/…`. A read sent as `kb+skill://…` works.
3. **Behind a simulated gateway.** With the prefix:
   - list, then read `_index.md`;
   - for each address in its body that starts `kb+skill://`, strip `kb+` as the gateway does and
     read it;
   - every one succeeds, and so does the `_manifest` of one skill.
4. **Query form.** `?prefix=kb+` in the URL works like the header.
5. **Instructions.** The prefixed pointer and footer match D4 exactly, and a `notes` line holding a
   `skill://` address is translated. With no prefix, the text is unchanged.
6. **Tools mode with the prefix.** `list_resources` returns text addresses with the prefix.
   `read_resource` accepts both the plain and the prefixed form.
7. **Skills extension with the prefix.** `skills/list` entries never carry the prefix. Each
   file's digest and size equal the bytes `resources/read` serves under the same headers, and
   those bytes differ from the no-prefix read for a file that holds an address.
8. **Prompts.** A prompt whose body uses `${CLAUDE_PLUGIN_ROOT}` renders the prefixed address.
9. **Invalid prefix.** `X-MCP-Resource-Prefix: kb` behaves as if absent.
10. **No double prefix.** A body already holding `kb+skill://…` or `myskill://…` is not rewritten.

## Docs and release

- **README.** At most one line, if any.
- **Wiki `Scoping.md`.** The prefix setting and the three kinds of address.
- **Wiki `Agentgateway.md`.** The combined-backend recipe is in resources mode: route headers
  `X-Skill-Library: penpot` and `X-MCP-Resource-Prefix: <target>+`. The prefix must match the
  target name.
- **CHANGELOG** `[Unreleased]`: one line.
- **Wiki changes** are committed and pushed in the submodule before the superproject's pointer.

## Not in scope

- Shortening addresses. The library segment always stays (see *Revised*).
- Rewriting addresses inside `_manifest` JSON fields other than URIs. Its paths are relative
  already.
- The mirror tools' static descriptions.
- Prompt names (`<library>_<stem>`).
- agentgateway itself, and the penpot component. That is the installer's change, next.
