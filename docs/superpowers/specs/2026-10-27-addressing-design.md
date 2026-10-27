# Addresses that fit where kb is served — design

**Date:** 2026-10-27 · **Branch:** `addressing` · **Status:** draft, for review

## Goal

kb's `skill://` addresses read correctly wherever kb is served, so a client uses kb's
resources and nothing else, even behind a multiplexing gateway. Two request settings drive it:

1. **A prefix hint.** The client, or the route in front of it, tells kb what a gateway puts in
   front of its addresses, e.g. `kb+`. Every address kb writes **inside text** carries it:
   `kb+skill://…`.
2. **A pinned library.** With `X-Skill-Library` set, addresses drop the `<library>/` segment:
   `skill://penpot-router/SKILL.md` instead of `skill://penpot/penpot-router/SKILL.md`.

The motivating setup is Penpot's MCP and kb combined on one agentgateway backend, with kb
pinned to the `penpot` library. The client should see Penpot's tools and kb's skills as
resources, with every link working.

## Background

Checked on 2026-10-27 against agentgateway v1.6.0 (`crates/agentgateway/src/mcp/handler.rs`) and
the 1.7.0-rc.1 release notes.

- **What the gateway does to resources.** A multiplexed backend lists, reads and merges
  resources, templates and list-changed/updated notifications. It rewrites every resource URI in
  a **structured** field to `<target>+<uri>` (`skill://penpot/x` → `kb+skill://penpot/x`). It
  refuses a read without a known `<target>+` prefix. Before forwarding a read, it removes the
  prefix again. A backend with one target rewrites nothing.
- **Text is not rewritten.** Addresses inside text go through untouched: server instructions,
  resource bodies, tool results. kb's instructions, its `_index.md` and `_files.md` bodies,
  read hints and resolved `${CLAUDE_*}` placeholders all write plain `skill://…`, which the
  gateway then refuses. Today the only workaround is kb's tools mode, which hides the resources.
- **The Skills extension.** The gateway merges the extension's capability declaration but answers
  `skills/list` and `skills/get` with `unsupported method` (agentgateway#3579, still open, not in
  1.7.0-rc.1). Claude Code doesn't call them either. This design keeps the extension consistent
  without depending on it.
- **The query string is dropped**, but headers are forwarded. So the settings are read
  header-first, like kb's existing scope settings.
- **Short forms are valid.** `skill://_index.md`, `skill://penpot-router/SKILL.md` and
  `kb+skill://_index.md` all validate as MCP resource URIs (checked with the `mcp` types in the
  pinned FastMCP).

## Decisions

### D1. Two request settings

| Header | Query parameter | Value |
|---|---|---|
| `X-MCP-Resource-Prefix` | `prefix` | the text a gateway puts in front of kb's addresses, e.g. `kb+`: a letter, then letters, digits, `+`, `-`, `.`, ending in `+` |
| `X-Skill-Library` (existing) | `library` (existing) | one library |

The prefix applies to every resource address kb writes, not only skills: a gateway prefixes
every resource URI. Today all of kb's resources are `skill://` addresses (indexes, `_files.md`,
manifests, library files, skills). Resources from other schemes that kb may serve later follow
the same rule.

Both are read by the same header-then-query rule as the other settings. A prefix that
isn't valid is ignored, as if absent. With neither set, nothing changes for any
existing client.

### D2. Canonical inside, translated at the edge

The catalogue keeps its one grammar, `skill://<library>/<path>`. Scoping, the memoised listings,
containment checks and the index are untouched. A per-request **`Addressing`** value carries the
prefix and the pinned library. It translates in three directions, at the MCP boundary only:

- **Outgoing, structured:** a `uri` field kb returns. With a pin,
  `skill://<library>/<path>` → `skill://<path>`. The prefix is **never** applied here: a gateway
  adds its own prefix to structured fields, and both together would give `kb+kb+skill://`.
- **Outgoing, text:** any text a client reads. With a pin, `skill://<library>/<path>` →
  `<prefix>skill://<path>`, and the bare `skill://<library>` (not followed by a path character) →
  `<prefix>skill://`. Without a pin, `skill://` → `<prefix>skill://`. With neither setting the text is
  unchanged.
- **Incoming:** an address a client sends. kb accepts `skill://…` and `<prefix>skill://…` for the
  request's prefix. With a pin it tries the short form first (`skill://<path>` →
  `skill://<library>/<path>`), then the long form (`skill://<library>/<path>` as written), so an
  old link still works. The first that resolves wins. Everything else behaves as an unknown
  address does today.

`Addressing` is pure: it lives in `catalogue/` and imports no FastMCP. `mcp/request.py` builds
it from the request, like `requested_scope()`.

### D3. Only an explicit pin shortens addresses

`X-Skill-Library` (or `?library=`) shortens. A categories or tags scope that happens to select one
library does not. Addresses must not change shape when a tag starts matching a second library.

### D4. Where each kind applies

| Surface | Kind |
|---|---|
| `resources/list` rows: `uri`, and `name` (the address without its scheme) | structured |
| `resources/read`: the incoming URI | incoming |
| `resources/read`: the returned body | text |
| `resources/read`: the returned `uri` | as the client sent it |
| `NameTheFileToRead` hints and every other error message naming an address | text |
| `list_resources` tool result | text (a tool result is text; the gateway doesn't rewrite it) |
| `read_resource` tool: argument / result / error hint | incoming / text / text |
| `skills/list`, `skills/get` entries: `uri` and each file `uri` | structured |
| `skills/get` argument | incoming |
| Rendered prompt text (resolved `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_SKILL_DIR}`) | text |
| Server instructions | built with the `Addressing` (D5) |

A skill's own markdown is resource body text. Any `skill://<library>/…` in it is translated,
including a placeholder kb already resolved there. Relative links inside a skill need nothing:
a client resolves them against the address it read.

### D5. Instructions follow the addressing

`build_instructions` takes the `Addressing`. The pointer and the footer name the addresses the
client will actually use:

- Pinned, `kb+skill`: `Skills (kb+skill://_index.md): …`, and the resources footer
  `Read a listed skill at kb+skill://<path>/SKILL.md; read its _manifest in place of SKILL.md for
  the other files it ships.`
- Unpinned, `kb+skill`: `Skills: kb+skill://penpot/_index.md`, and the footer with
  `kb+skill://<library>/<path>/SKILL.md`.
- Neither: byte-identical to today.

The tools footer (`Read these with read_resource.`) is unchanged.

### D6. A pinned library's own files

With a pin, the library index is `skill://_index.md` and the library files list is
`skill://_files.md`. A library file is `skill://<path>`, the same rule as a skill.

## Examples

`X-Skill-Library: penpot`, `X-MCP-Resource-Prefix: kb+`, resources mode, behind a gateway target
named `kb`. The client's listing, after the gateway's prefix:

```
kb+skill://_index.md          penpot/_index.md is now _index.md
```

Reading it (the gateway sends kb `skill://_index.md`):

```
# penpot — 14 skills

Penpot design tooling.
Start at penpot-router. …

kb+skill://penpot-anti-slop/SKILL.md: Opt-in layer that keeps Penpot designs …
…
kb+skill://penpot-router/SKILL.md: Thin dispatcher / entry point for any Penpot request. …
```

Every link in it reads through the gateway: `kb+skill://penpot-router/SKILL.md` reaches kb as
`skill://penpot-router/SKILL.md`, which resolves under the pin.

## Where it goes

- **`catalogue/addressing.py`** (new, pure): `Addressing` and its three translations.
- **`mcp/request.py`**: the `X-MCP-Resource-Prefix` / `prefix` setting and `requested_addressing()`.
- **`mcp/resources.py`**: the provider (listing, read) and `NameTheFileToRead`.
- **`mcp/tools.py`**: the mirror tools.
- **`mcp/skills.py`**: `skills/list`, `skills/get`.
- **`mcp/prompts.py`**: rendered prompt text.
- **`catalogue/instructions.py`** and **`mcp/instructions.py`**: the pointer and footer.

No `Catalogue` method changes its grammar. The repo rule "every `Catalogue` method takes a
`Scope`" is unchanged. `Addressing` sits beside it at the edge, not inside it.

## Acceptance

Every case runs through an MCP client over HTTP against the app. Each must fail when its rule
breaks.

1. **Defaults.** With neither setting, listings, reads, hints, tool results, prompts and
   instructions are byte-identical to before for a sample of addresses.
2. **Pinned only.** Listing `uri`s and `name`s are short. An `_index.md` body links
   `skill://<path>/SKILL.md`. Every link in it reads back. A long-form read still works.
3. **Prefix only.** Listing `uri`s are unchanged (structured). Bodies and hints use
   `kb+skill://<library>/…`. A read sent as `kb+skill://…` works.
4. **Both, behind a simulated gateway.** List; read `_index.md`; for each address in its body
   that starts `kb+skill://`, strip `kb+` as the gateway does and read it. Every one succeeds,
   and so does the `_manifest` of one skill.
5. **Tag scope selecting one library.** Addresses stay long (D3).
6. **Instructions.** The pinned and hinted pointer and footer match D5 exactly. With neither
   setting, the text is unchanged.
7. **Tools mode with both.** `list_resources` returns text addresses with the prefix.
   `read_resource` accepts the short, long and prefixed forms.
8. **Skills extension with a pin.** `skills/list` entries are short and never carry the prefix.
   `skills/get` accepts the short form.
9. **Prompts.** A prompt whose body uses `${CLAUDE_PLUGIN_ROOT}` renders the pinned and prefixed
   address.
10. **Invalid prefix.** `X-MCP-Resource-Prefix: "kb"` behaves as if absent.

## Docs and release

- **README.** At most one line, if any.
- **Wiki `Scoping.md`.** The two settings, the three kinds of address, and the D3 rule.
- **Wiki `Agentgateway.md`.** The combined-backend recipe moves from tools mode to resources
  mode: route headers `X-Skill-Library` and `X-MCP-Resource-Prefix: <target>+`. The prefix must
  match the target name.
- **CHANGELOG** `[Unreleased]`: one line.
- **Wiki changes** are committed and pushed in the submodule before the superproject's pointer,
  as last time.

## Not in scope

- Rewriting addresses inside `_manifest` JSON fields other than URIs. Its paths are relative
  already.
- The mirror tools' static descriptions, which describe the long grammar. Long forms are still
  accepted.
- Prompt names (`<library>_<stem>`).
- agentgateway itself, and the penpot component. That is the installer's change, next.
