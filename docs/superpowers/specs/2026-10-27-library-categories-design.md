# Library categories and the Kb- headers — design

**Date:** 2026-10-27 · **Branch:** `categories` · **Status:** draft, for review

## Goal

A client can select **several libraries at once** by naming one category. Each library gets a
`categories` list in the config, and `Kb-Category: dev` selects every library that lists `dev`.
Each selected library keeps its own address (`skill://n8n/…`), description and notes, and gets
its own `[name]` section in the instructions.

So a client enters one of two ways: **one library** (`Kb-Library`) or **one category**
(`Kb-Category`). Tags still narrow within either.

The scope settings also get a product prefix. `X-` is deprecated for new headers (RFC 6648), and
"Skill" undersells a library, which also serves prompts and library files. They become `Kb-…`,
and the old `X-…` names stay as optional aliases.

## Background

Checked on 2026-10-27, mcp-kb `main` at `aa35875`.

- **Scope today.**
  - A request names at most **one** library (`X-Skill-Library`; only the first value is read).
  - Categories and tags filter plugins: a plugin has one category; tags follow the comma rule,
    with a comma meaning *all of* and repeated values meaning *any of*.
  - A library carries no category of its own.
- **One header value is all most clients can send.**
  - Claude Code's `.mcp.json` can't repeat a header.
  - The agentgateway drops the query string.
  - So "any of" across several values is out of reach for them, and a library-level category is
    what lets one value select several libraries.
- **Live plugins** (n8n, kubed, superpowers) share no category or tag. superpowers' marketplace
  entry has none at all, and marketplace plugins are not editable in the config.
- **Several libraries already render.** The instructions builder lays several selected libraries
  out as `[name]` sections (#25). Addresses keep their library segment (#26), so several libraries
  on one connection never collide.
- **Shared headers.** `X-MCP-Resources` and `X-MCP-Prompts` describe the *client*, not kb's
  content, and selenium-flow reads `X-MCP-Resources` too. They are out of scope here
  (kubed-io/selenium-flow#90 tracks a joint decision).
- **`X-` deprecation.** RFC 6648 deprecates the `X-` prefix for new headers. MCP's 2026-07-28
  spec defines its own `Mcp-Method` and `Mcp-Name` headers, so a server's own headers should not
  take `Mcp-`.

## Decisions

### D1. A library lists its categories

```yaml
libraries:
- name: n8n
  source: github://n8n-io/skills?ref=…
  categories: [dev, automation]
```

`categories` is a list of strings, default empty. It labels the library for selection only. It
does not change any plugin's own category, `/health`'s per-plugin category, or what a
`pluginSelector` matches; a selector still reads plugins' own categories, so a library can't
select itself.

### D2. A category selects libraries, and still selects plugins

A thing in a library is in scope for `Kb-Category: c` when either:

- the library lists `c` in its `categories`; or
- the plugin's own category is `c`, as today.

"A thing" means a skill, a prompt, a library file. With several requested categories, any of
them counts. The check runs per (library, plugin) pair, because a plugin can sit in several
libraries with different categories.

Tags (`Kb-Tag`) and the library pin (`Kb-Library`) narrow on top, exactly as today. A pinned
library must also match the category when both are sent.

### D3. The Kb- headers, with the X- names as aliases

| New header | Query parameter | Old header (alias) | Old parameter (alias) |
|---|---|---|---|
| `Kb-Library` | `library` | `X-Skill-Library` | — (same) |
| `Kb-Category` | `category` | `X-Skill-Categories` | `categories` |
| `Kb-Tag` | `tag` | `X-Skill-Tags` | `tags` |
| `Kb-Listing` | `listing` | `X-Skill-Listing` | `skills` |
| `Kb-Resource-Prefix` | `prefix` | `X-MCP-Resource-Prefix` | — (same) |

- **Precedence:** the `Kb-` header first, then the old header, then the new parameter, then the
  old parameter. So a client sending both a new and an old header gets the new one.
- **Values and rules are unchanged:** one library; a comma in a category value is refused;
  commas in a tag value mean *all of*; repeats mean *any of*.
- `X-MCP-Resources` and `X-MCP-Prompts` are unchanged.
- Docs and examples name only the `Kb-` headers, and mention the old ones as accepted aliases.

### D4. What a scope that names nothing does

An unknown category is refused today, with the categories that exist. "Exist" now includes
every library's `categories` (within the pinned library, when one is pinned). An unknown library
is refused as today. An empty `Kb-Category` value means no category filter.

### D5. `/health` shows the library categories

A library's `/health` entry gains `categories`, its configured list.

## Example

```yaml
libraries:
- name: n8n
  source: github://n8n-io/skills?ref=…
  categories: [dev]
- name: superpowers
  source: github://obra/superpowers?ref=…
  categories: [dev]
- name: kubed
  plugins: [drive]
  categories: [dev]
```

A client sending `Kb-Category: dev` sees three libraries:

```
[n8n]
n8n workflows — …
Skills: skill://n8n/_index.md

[superpowers]
Workflow discipline — …
Skills: skill://superpowers/_index.md

[kubed]
This homelab's own material.
Skills: skill://kubed/_index.md

Read a listed skill at skill://<library>/<path>/SKILL.md; …
```

A library with no skills in scope is left out of the instructions, as today.

## Where it goes

- **`config.py`:** `LibraryConfig.categories: list[str]`, and a regenerated `config.schema.json`.
- **`mcp/scope.py`:** the category match takes the library's categories as well as the plugin's.
- **`catalogue/`:** every in-library thing (skill, prompt, library-file entry) carries its
  library's categories, set where the snapshot builds it, so each scope check has them without a
  lookup.
- **`mcp/request.py`:** the new header and parameter names, and the aliases.
- **`mcp/pins.py`:** known categories include the libraries' own.
- **`catalogue/snapshot.py`:** `/health` gains a library's `categories`.
- **Docs.** The OpenAPI builder, `routes.py` and `server.py` docstrings that name the old headers.

## Acceptance

Every case runs through an MCP client over HTTP against the app, unless noted. Each must fail when
its rule breaks.

1. **Category selects libraries.** Two of three libraries list `dev`, and none of their plugins
   has category `dev`. `Kb-Category: dev`:
   - lists both libraries' indexes and not the third's;
   - reads a skill in each;
   - the instructions have exactly those two `[name]` sections.
2. **Plugin category still selects.** A plugin's own category (as today) still selects it.
3. **Pin plus category.** `Kb-Library` with a category the library doesn't list (and none of its
   plugins has) gives nothing: the existing empty-scope refusal.
4. **Tag narrows.** `Kb-Category: dev` with `Kb-Tag` narrows within the selected libraries.
5. **Unknown category refused**, and the refusal lists library categories too (`dev` appears).
6. **Aliases.**
   - Each old header and old parameter still works.
   - When a `Kb-` header and its old alias disagree, the `Kb-` header wins.
7. **`/health`** shows each library's `categories`.
8. **`pluginSelector`** ignores library categories. A selector on category `dev` doesn't pick up
   plugins of a library that merely lists `dev` (unit test).
9. **Defaults.** With no scope settings, every surface is unchanged.

## Docs and release

- **README:** the per-request table names the `Kb-` headers, with one line saying the `X-` names
  still work.
- **Wiki:**
  - `Scoping.md`: the two ways in (library or category), the alias table, and the precedence.
  - `Libraries.md`: `categories`.
  - `Agentgateway.md` and `Installing.md`: switch to the `Kb-` names.
  - The generated pages are regenerated.
- **CHANGELOG** `[Unreleased]`:
  - Added: a library's categories, and `Kb-Category` selecting libraries.
  - Changed: the `Kb-` header names, with the old ones still accepted.
- **After release** (installer changes, not this repo):
  - the cluster config gets `categories: [dev]` on n8n, superpowers and kubed, and `.mcp.json`'s
    `kb` gets `"Kb-Category": "dev"`;
  - the penpot and grafana routes, the cluster `mcp-kb` routes and the runner profiles switch to
    the `Kb-` names. The aliases mean this can happen any time.

## Not in scope

- `X-MCP-Resources` / `X-MCP-Prompts` (kubed-io/selenium-flow#90).
- Several libraries in `Kb-Library`. Selecting several is what categories are for.
- Library tags. Tags stay a plugin facet.
- Removing the `X-` aliases.
