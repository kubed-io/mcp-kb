# Scoping and instructions

A **scope** is the slice of the catalogue one request may see: one library, some categories,
some tag groups. It is read from the request's headers and query string, and every listing and
every read goes through it. The **instructions** are the text a client gets when it connects,
built for that connection from its scope. This file covers both. It does not cover the client
capability settings (`X-MCP-Resources`, `X-MCP-Prompts`), which are in
[http-and-tools.md](http-and-tools.md), or what a library's description and categories are,
which is in [plugins-and-libraries.md](plugins-and-libraries.md).

## Reading the settings

**SCP-1.** A scope has three selectors: a library, a set of categories, and a set of tag groups.
Each is read per MCP request from an HTTP header or a query parameter on the MCP URL.

**SCP-2.** Each setting has four names:

| Setting | Header | Parameter | Alias header | Alias parameter |
|---|---|---|---|---|
| Library | `Kb-Library` | `library` | `X-Skill-Library` | — |
| Category | `Kb-Category` | `category` | `X-Skill-Categories` | `categories` |
| Tag | `Kb-Tag` | `tag` | `X-Skill-Tags` | `tags` |
| Listing | `Kb-Listing` | `listing` | `X-Skill-Listing` | `skills` |
| Resource prefix | `Kb-Resource-Prefix` | `prefix` | `X-MCP-Resource-Prefix` | — |

**SCP-3.** The listing and the resource prefix are read by the same rules as the scope
(SCP-4 to SCP-7). What they do is specified in [skills.md](skills.md).

**SCP-4.** Header names match case-insensitively. Parameter names match exactly.

**SCP-5.** Sources are tried in this order: the header, the alias header, the parameter, the alias
parameter. The first source with at least one non-empty value supplies every value of that
setting. Sources are never merged.

**SCP-6.** An empty value counts as not sent. `Kb-Category: ""` with `X-Skill-Categories: ops`
scopes to `ops`.

**SCP-7.** A repeated header or a repeated parameter supplies several values, and every one is
kept.

**SCP-8.** Because a header beats a parameter, a header set by a credential or a gateway route
is a ceiling the caller cannot widen through the URL. A pin set under an alias header does not
hold against a client that sends the `Kb-` header.

**SCP-9.** No tool, prompt or method takes a library, category or tag as an argument. The scope
comes only from the request's headers and URL.

**SCP-10.** A request that is not HTTP (stdio, in-memory) has no scope and sees everything.
When the headers are reachable but the request object is not, the headers are read and there are
no parameters.

## What the values mean

**SCP-11.** The library is the first value only, trimmed. It matches a library's name exactly,
case included. A scope names at most one library.

**SCP-12.** Each category value is trimmed and empty ones are dropped. Several category values
mean *any of* them.

**SCP-13.** The comma rule: a comma inside one tag value means *all of*, and separate values mean
*any of*. Each value is split on commas, each tag trimmed, and empty tags and empty groups
dropped.

```
?tag=oncall,runbooks&tag=lgtm      (oncall AND runbooks) OR lgtm
?category=design&category=ops      design OR ops
```

**SCP-14.** A thing's tags are its plugin's `tags` and `keywords` together. A library has no tags
of its own.

**SCP-15.** A thing matches the categories when its plugin's own category is one of them, or the
library serving it lists one of them in `categories`.

**SCP-16.** The category check is per library. A plugin served by two libraries is in scope
through the one whose categories match and out of scope through the other, unless its own
category matches.

**SCP-17.** A thing matches the tags when every tag of at least one group is among its tags.

**SCP-18.** The selectors AND together. `?library=grafana&category=observability` is the
observability part of `grafana`.

**SCP-19.** A scope with no selectors admits everything.

## What a scope reaches

**SCP-20.** A thing is in scope when it belongs to the scoped library (if one is set) and its
plugin, in that library, matches the categories and the tags (SCP-15 to SCP-17).

**SCP-21.** The scope applies to skills, prompts, agents and library-level files alike, and to
every surface that lists or reads them: `resources/list`, `resources/read`, `prompts/list`,
`prompts/get`, `skills/list`, `skills/get`, `agents/list`, `agents/get` and the four mirror tools.

**SCP-22.** Out of scope means not listed and not readable. An index (`_index.md`) lists only the
skills in scope, and `_files.md` lists only the library files in scope. An index or `_files.md`
with nothing in scope does not exist for that request.

**SCP-23.** A library-level file is in scope when its plugin is in scope in that library. A read
that falls back to a plugin root (see [skills.md](skills.md)) tries only the roots of plugins in
scope, or the root of the in-scope skill it was addressed under.

**SCP-24.** A read of an out-of-scope address fails exactly as a read of an absent one does, on
`resources/read`, the `read_resource` tool, `skills/get` (`Skill not found`), `agents/get`
(`Agent not found`, with `data.reason: "agent_not_found"`) and `prompts/get` or `get_prompt` alike:
the same error code and the same message.

**SCP-25.** A hint that names the file to read instead of a directory is computed from the
request's scope. A directory the scope cannot see fails as an absent address does.

**SCP-26.** A scope narrows what is listed and never changes an address. Addresses keep their
library segment under every scope.

**SCP-27.** A prompt is in scope by its library, its plugin's category, its library's categories
and its plugin's tags and keywords, as for a skill.

**SCP-28.** `/health` ignores the scope; see [http-and-tools.md](http-and-tools.md).

## Refusing a scope that names nothing

**SCP-29.** A scope that names nothing fails every MCP request with invalid params (-32602) and a
message saying what there is instead. `initialize`, `server/discover`, `skills/list`, `skills/get`,
`agents/list` and `agents/get` are refused alike, so the first request a client makes is the one
that fails.

**SCP-30.** A scope with no selectors is never refused.

**SCP-31.** The checks run in this order, and the first that applies decides:

| # | Condition | Outcome |
|---|---|---|
| 1 | the library contains `/` | refused: `A scope names a library, not a folder: use ?category= or ?tag= (or the Kb-Category and Kb-Tag headers) to narrow inside it.` |
| 2 | the library is not declared in the config | refused: `The scope names library '<x>', and there is no such library. The libraries are: <sorted names>.` |
| 3 | a category value contains a comma | refused: `A plugin has one category, so 'a,b' matches nothing; repeat ?category= (or the Kb-Category header) to mean any of them.` |
| 4 | a library is set and none of its plugins has status `ok` | served, not refused |
| 5 | no library is set and a requested category is listed by a library with no plugin at status `ok` | served, not refused |
| 6 | a requested category is unknown (SCP-32) | refused: `The scope names category '<x>', which no library lists and no plugin declares. The categories are: <sorted>.` |
| 7 | a requested tag is unknown (SCP-33) | refused: `The scope names tag '<x>', which nothing carries. The tags are: <sorted>.` |
| 8 | no library is set and the server serves nothing at all | served, not refused |
| 9 | categories or tags are set and the scope would be shown no listing row, no prompt and no agent | refused: `The scope names things that exist, but nothing in library '<x>' carries the combination: <what was asked>.` (`any library` when none is set) |

Rows 6 and 7 use the plural (`categories`, `tags`) when several are unknown. An empty list is
written `none`.

**SCP-32.** The known categories are the own categories of every plugin `/health` reports and the
`categories` of every library. When a library is set, only that library's plugins and that
library's categories count.

**SCP-33.** The known tags are the tags and keywords of the same plugins as SCP-32.

**SCP-34.** A scope is refused for what it names, never for what is served at the moment. A
declared library whose plugins are down, or up with nothing in them, is served empty.

**SCP-35.** The refusal names libraries, categories and tags from the operator's config. A scope
that is not refused learns nothing about what lies outside it.

## Server instructions

**INS-1.** The `instructions` on every `initialize` result and every `server/discover` result
are built for that request. The same request gets the same text from either.

**INS-2.** The text is built from the current catalogue, the request's scope, whether the client
reads resources (see [http-and-tools.md](http-and-tools.md)), whether the client declared the
Skills extension, and the request's resource prefix.

**INS-3.** The client declared the Skills extension when `io.modelcontextprotocol/skills` is in
the `initialize` request's `capabilities.extensions`, or, for `server/discover`, among the client
capabilities that request carries. A request with no message or no session has not declared it.

**INS-4.** A session keeps the text it was given. No notification changes it. A new connection
gets text built from the catalogue as it is then.

**INS-5.** A scope that names nothing (SCP-29) gets no instructions: its `initialize` fails.

### Which libraries

**INS-6.** A library is selected when at least one of its skills is in the request's scope. A
library with only prompts or library files in scope is not selected.

**INS-7.** Selected libraries appear in config order.

### A library's section

**INS-8.** A section is, in order: the library's resolved description, its `notes`, and a
pointer line. The description and the notes are each left out when empty. What the resolved
description is: [plugins-and-libraries.md](plugins-and-libraries.md).

**INS-9.** Blank lines and trailing whitespace are removed from the description and the notes, so
neither can open a new section.

**INS-10.** The pointer names the library's index: `Skills: skill://<library>/_index.md`.

**INS-11.** The pointer also lists skill names when all of these hold: exactly one library is
selected, that library's `listSkills` is true, and the client has not declared the Skills
extension. It then reads `Skills (skill://<library>/_index.md): <names>`.

**INS-12.** The names are the paths below the library of the skills in scope, sorted, joined by
`, `. A scope narrowed by tag lists only the skills it admits.

**INS-13.** With one library selected, its section has no heading. With several, each section
starts with a `[<library>]` line and no names are listed.

### Layout and footer

**INS-14.** Sections are separated by one blank line, and the footer comes last after one blank
line. With no library selected, the text is the footer alone.

**INS-15.** The footer follows the client's mode and is not configurable:

| Mode | Footer |
|---|---|
| Resources (default) | `Read a listed skill at skill://<library>/<path>/SKILL.md; read its _manifest in place of SKILL.md for the other files it ships.` |
| Tools | `Read these with read_resource.` |

**INS-16.** With a resource prefix, every `skill://` address in the description, the notes, the
pointer and the resources footer is written with the prefix in front (`kb+skill://…`). The
prefix's rules are in [skills.md](skills.md).

**INS-17.** One library selected, names listed, a prefix of `kb+`:

```
Penpot design tooling.
Start at penpot-router.
Skills (kb+skill://penpot/_index.md): penpot-anti-slop, penpot-router

Read a listed skill at kb+skill://<library>/<path>/SKILL.md; read its _manifest in place of SKILL.md for the other files it ships.
```

**INS-18.** Several libraries selected, tools mode:

```
[grafana]
Grafana, Loki and the rest of the LGTM stack.
Skills: skill://grafana/_index.md

[penpot]
Penpot design tooling.
Skills: skill://penpot/_index.md

Read these with read_resource.
```
