# Skills

A **skill** is a directory holding a `SKILL.md`. This file covers which directories count as
skills, the `skill://` address space that skills and a library's other files live in, what each
address reads as, the gateway prefix, folders, and the MCP Skills extension. Declaring plugins and their
globs is in [plugins-and-libraries.md](plugins-and-libraries.md); who may see what is in
[scoping-and-instructions.md](scoping-and-instructions.md); the resource tools are in
[http-and-tools.md](http-and-tools.md).

## What makes a skill

**SKL-1.** A skill is a folder inside its plugin root that holds a regular file named
`SKILL.md`, found as Claude Code finds one. Each folder directly in the plugin's `skills/` that
holds one is a skill. Then come the folders the plugin declares: its manifest's `skills`
(PLG-20), then its marketplace entry's (LIB-30), then a declared plugin's own `skills:` (LIB-33).
A declared folder that holds a `SKILL.md` is a skill itself; otherwise each folder directly in it
that holds one is. The first to reach a folder claims it, and a folder reached again is not found
twice. A child folder whose name starts with `.`, or that is itself a symlink, is never a skill.
Nothing deeper is found: `skills/g/b/SKILL.md` is a skill only when `skills/g` or `skills/g/b` is
declared. A declared `skills: []` serves no skill (PLG-9).

**SKL-3.** A path is **hidden** when any segment starts with `.`, except `.github`, `.claude` and
`.agents`, kept at any depth. Hidden paths are never harvested, listed or read. A skill whose
folder holds a file or a folder whose name starts with `.`, at any depth, is served without it:
inside a skill, kubed-mcp's plugin layer leaves out every such path with no exception (quick-mcp's
SKL-24, kubed-mcp 0.5.2 and later), so it is in no read, folder, index, `_manifest` or entry, and
reads as a missing one. A skill whose folder holds a symlink that is not hidden is not served at
all (SKL-45).

**SKL-4.** A skill folder, like a pattern hit, is kept only when it resolves inside the plugin
root. It is named by the path it was reached by, not by its symlink target.

**SKL-5.** A skill's name is its frontmatter `name`, else its directory's name. Its description is
the frontmatter `description` with each run of whitespace collapsed to one space, else empty.
Frontmatter that does not parse, is nested too deeply to read, or has a key that is not a string,
counts as absent.

**SKL-6.** A skill's name MUST keep the Agent Skills naming rule: 1 to 64 lowercase letters,
digits and single hyphens, no hyphen first or last. It MUST equal its directory's name, unless the
skill is the plugin root itself. A skill that breaks either, or whose address a skill the plugin
claimed earlier (SKL-1) already has, is skipped as in PLG-18. Overlapping skills of two plugins in
one library are a conflict, as in [plugins-and-libraries.md](plugins-and-libraries.md).

## Addresses

**SKL-8.** A skill's and a library's addresses are `skill://` URIs:

| URI | Reads as |
|---|---|
| `skill://<library>/_index.md` | the library's folders and skills |
| `skill://<library>/<folder>/_index.md` | one folder's folders and skills |
| `skill://<library>/_index.json`, `skill://<library>/<folder>/_index.json` | the same directory's children, as JSON (SKL-56) |
| `skill://<library>/<folder>/<name>/SKILL.md` | a skill's instructions |
| `skill://<library>/<folder>/<name>/_manifest` | the files that skill ships, as JSON |
| `skill://<library>/<folder>/<name>/<path>` | one file of that skill |
| `skill://<library>/<folder>/<name>[/<dir>]/_index.md`, `…/_index.json` | the children of the skill's root or of a folder inside it (SKL-57) |
| `skill://<library>/_files.md` | the library's files outside every skill |
| `skill://<library>/<path>` | one of those files |

**SKL-61.** `prompts://` and `agents://` are the plugin layer's address spaces beside `skill://`,
by the same namespaces (SKL-59): PRM-63 and AGT-18 to AGT-19. kb's `Catalogue` answers neither. The
prefix is accepted and written on them as on `skill://` (GW-4, SKL-41).

**SKL-9.** `<library>` is the library's name, so a plugin served by two libraries has its skills at
two addresses. A skill's **address** is `<library>/<folder>/<name>`, without an empty folder.

**SKL-10.** `<folder>` is the name of the skill's plugin, and empty for the library's main plugin
(SKL-59). It never comes from where the skill sits inside its plugin.

| Plugin | Skill directory | Address in library `grafana` |
|---|---|---|
| the main plugin | `skills/loki` | `grafana/loki` |
| `grafana-lgtm` | `skills/grafana-lgtm/loki`, declared | `grafana/grafana-lgtm/loki` |
| `k6` | `skills/k6-load` | `grafana/k6/k6-load` |

**SKL-59.** A library's **main plugin** is decided once per generation from the library's resolved
plugin list, never from what serves or from what a request's scope admits. It is the first of the
library's plugins whose name is the library's name. Failing that, when the library's
`marketplace.json` lists exactly one entry, skipped entries counted, it is that entry's plugin,
whatever its path, unless that entry was skipped. Otherwise the library has none. The main plugin's
**namespace** is `<library>`, and every other plugin's is `<library>/<plugin name>`: a skill's
address is its plugin's namespace followed by its name, and a plugin in two libraries has a
namespace in each. A scope never moves an address (SCP-26).

**SKL-11.** A skill is identified by its full address, never by its name alone. Two skills of one
name in different folders or libraries are both served.

**SKL-12.** A path below a library resolves to the skill whose address is its longest prefix, so a
file under a nested skill belongs to the nested skill.

**SKL-13.** Before any other check, the path below `skill://` has its `.` and `..` segments
resolved as in RFC 3986, over the whole path: the library is a segment, not an authority. A `..`
with nothing left to pop makes the address resolve to nothing, so no address climbs past the root.
Scope applies to the resolved address. The plugin layer resolves the dots before kb sees the
address, on `resources/read` (GW-4), and so for its `read_resource` tool, which reads through
`resources/read` (DLV-6), on `resources/directory/read` and on `skills/get`; kb's own `uris.parse`
resolves them again, which changes nothing. So a dotted address reads, lists and gets what its
resolved one does, a skill's directory and a folder inside one included. The library is a
segment, so a `..` that climbs out of one resolves to another address (`skill://grafana/../n8n` is
`skill://n8n`), read under the request's scope like any address; only a `..` with nothing left to
pop names nothing, and a directory read of it is `Directory not found`. A miss is reported under
the address as sent (GW-4).
An escaped `/` (`%2F`) anywhere in an incoming address resolves to nothing (GW-4), and
percent-escapes are never decoded. A URI that does not start with `skill://` resolves to nothing.

## The listing

**SKL-14.** `resources/list` holds what the plugin layer lists for the request's `Listed` setting
(`Kb-Listed`, `X-MCP-Listed` or `?listed=`, DLV-8). By default under Via `mcp` that is one row per
served skill in scope: the URI `skill://<namespace>/<skill>/SKILL.md`, the name
`<namespace>/<skill>/SKILL.md`, the skill's own `description` and the `mimeType` `text/markdown`.
Under Via `extension` and `local` the default lists none (DLV-9). A `Listed` setting read from the
level Via was read from, or an earlier one (the `Kb-` header, then `X-MCP-`, then the query),
replaces the default under every Via; one from a later level is ignored (DLV-9). Under every Via
and `Listed` setting, the skill rows are at most the request's max (SCP-3): 100 unless the request
or the config sets another. SKL-64 says which are kept. `skills` lists the
skills, `prompts` the prompt files and `agents` the agent files, and `none` lists none. Then, under
every setting, one row per
library with a library file in scope, in library name order: `skill://<library>/_files.md`, with the
description `Files the <library> library ships outside any skill, which its skills reference.` A
`_files.md` row is not a skill row, and the max never cuts one. No
`_index.md` is listed, and each one still reads (SKL-17).

**SKL-15.** The `_files.md` row's `name` is its URI without `skill://`, its `mimeType` is
`text/markdown`, and its tags are the library's name and `index`.

**SKL-53.** `resources/templates/list` returns one template under every scope a
request is not refused for (SCP-29): `uriTemplate` `skill://{library}/{+path}`, `name` `skill`,
no `mimeType`, and the description `A skill, index or file this server serves: {library} is a
library's name and {path} a path below it. Start at skill://{library}/_index.md; resources/list
lists each skill's SKILL.md by default.` The description is text and carries the prefix (SKL-41); the `uriTemplate`
never does. The template is for discovery only: a read resolves exactly as it would without it,
and no tool lists it.

## Indexes

**SKL-17.** An `_index.md` lists only what sits directly under it, one `<uri>: <text>` line each:
each child folder as `<its _index.md>: N skills`, counting skills anywhere below it; then each
skill whose folder is exactly this one as `<its SKILL.md>: <description>`, by address; then, in a
library's index only, `skill://<library>/_files.md: N library-level files` when there are any.

**SKL-18.** An index opens with `# <library> — N skills` (a folder: `# <library>/<folder> — N
skills`), N counting the in-scope skills under it. A library's index follows the heading with the
library's description and notes, each with blank lines and trailing spaces removed. Every index
ends with a sentence naming what to read next: a folder's `_index.md`, a skill's `SKILL.md` or its
`_manifest`.

```
# grafana — 50 skills

skill://grafana/grafana-lgtm/_index.md: 9 skills
skill://grafana/loki/SKILL.md: Query and troubleshoot logs in Grafana Loki.
```

**SKL-19.** An index with no in-scope skill under it reads as nothing, so a library that ships only
library files has a `_files.md` and no `_index.md`.

**SKL-20.** `_files.md` opens with `# <library> — N library-level files`, one sentence, then one
URI per line. With no library file in scope it reads as nothing.

## Reading a skill's files

**SKL-21.** A path under a skill reads the regular file at that path in the skill's directory. A
served skill holds no symlink (SKL-45), and a hidden path in it reads as nothing (SKL-3). A
directory and a missing file read as nothing. A file named `_index.md` or `_index.json` at any depth of a
skill, and one named `_manifest` at its root, is not one of its files: the server answers that URI
with an index or the manifest.

**SKL-58.** A skill's files, its `_manifest`, its extension entry and the folders inside it are
served by kubed-mcp's plugin layer. kb adds each plugin it serves to one plugin set per generation,
under its namespace in each library (SKL-59), and the plugin layer builds what a request reads per
view and prefix (SCP-36). A file's text is rewritten when the build is made, never on read
(SKL-60). kb's own provider is registered after the plugin layer and answers only what it misses
(indexes, `_files.md`, library files, the plugin-root fallbacks), so it never serves a skill's
file.

**SKL-22.** A skill's file is a **text file** when its extension or its media type (SKL-23) is a
text one and its bytes are UTF-8. A text file has its line endings normalised to LF (SKL-60) and
is returned as text. Any other file of a skill, one with no extension included, is returned as a
blob of its bytes. Every other file read through this address space (an index, `_files.md`, a
library file, a fallback) is decoded as UTF-8 with invalid bytes replaced, has its line endings
normalised to LF, and is returned as text.

**SKL-23.** A read's media type is `application/json` for a skill's `_manifest` and for an
`_index.json`. A skill's other files take the plugin layer's type for their extension (`.md` is
`text/markdown`), else the type guessed from the extension, else `application/octet-stream`. Any
other file takes the type guessed from its extension, else `text/markdown`, and is returned as
text whatever its type. A library file named `_manifest` is not JSON.

**SKL-24.** A skill's `_manifest` names the skill by its `name` and lists every file a read of the
skill serves (SKL-21), sorted by path: the same files as its extension entry (SKL-46). Size and
hash describe the bytes a read returns under the same request headers, after kb's rewriter
(SKL-60) and the prefix, so they equal the entry's. The `_manifest` is a view: it reads at its
exact URI and is in no entry's `resources` (SKL-46), as the `_index.md` and `_index.json` beside
every directory are (SKL-56, SKL-57). A host that verifies a skill by SEP-2640 refuses a view
reached from inside the skill.

```json
{"skill": "loki",
 "files": [{"path": "SKILL.md", "size": 2310, "hash": "sha256:…"}]}
```

**SKL-25.** In a skill's `SKILL.md`, `${CLAUDE_PLUGIN_ROOT}` reads as `skill://<library>` except as
SKL-52 says, and `${CLAUDE_SKILL_DIR}` as `skill://<address>`. Every other `${…}` is served as
written, and every other file is served without substitution. Prompt bodies follow
[prompts.md](prompts.md).

**SKL-52.** In a skill's `SKILL.md`, `${CLAUDE_PLUGIN_ROOT}/<path>` whose `<path>` is the directory
of a served skill of the same plugin in the same library, or lies below one, reads as that skill's
address with the rest of the path kept: `${CLAUDE_PLUGIN_ROOT}/skills/drawio/references/xml.md`
reads as `skill://drawio/drawio/references/xml.md`. The deepest such skill wins. A directory name
ends at `/` or at a character that cannot continue it; a letter, a digit, `_`, `-`, `~`, `%`, `+`
and `@` continue it, and so does a `.` followed by one of those or by another `.`. So
`skills/drawio.md` and `skills/drawio-x/` are not in `skills/drawio`, and a sentence ending
`skills/drawio.` is. A bare `${CLAUDE_PLUGIN_ROOT}`, a path in a skipped skill and a path in another plugin's skill read
as SKL-25 says. `./`, `//` and `..` after the placeholder are not normalised. Nothing is served at
an address that was not served before.

**SKL-54.** A **qualified skill name** is `<plugin>:<skill>`, optionally preceded by
`/`. `<plugin>` matches PLG-1's name pattern and `<skill>` is a lowercase letter or digit followed
by lowercase letters, digits and `-`.

- A name is recognised only where it is not part of a longer token. The character before it
  (before its `/` when it has one) is not a letter, a digit, or any of `_ . / : @ + ~ % - { $ #`. The
  character after it is not a letter, a digit, or any of `_ : / ~ % + @ -`, nor a `.` followed by
  one of those.
- So `drawio:drawio` and `/drawio:drawio` are names, and a sentence ending `drawio:drawio.` holds
  one.
- `https://drawio:drawio`, `a/drawio:drawio`, `kb+drawio:drawio`, `drawio:drawio.md`,
  `drawio:drawio/x`, `drawio:drawio:x` and `${input:topic}` are not names.

**SKL-55.** In a skill's `SKILL.md`, a qualified skill name (SKL-54) in the body
reads as `skill://<address>/SKILL.md` when it resolves, without its `/`. The body is the text after
the frontmatter block, and the frontmatter is served as written.

- **Candidates.** These are the plugins serving in the same library whose name is `<plugin>`. The
  skill's own plugin comes first, then the library's plugins in order (LIB-4). A plugin's name is a
  marketplace entry's name, or a declared plugin's `name` in the config.
- **Answer.** The name resolves to the first candidate's skill named `<skill>`, among those in the
  caller's scope. When that plugin serves two such skills (SKL-11), the name is served as written.
- **Unresolved names.** An out-of-scope skill, an absent one, and a command's name that no
  in-scope skill shares, such as `/<plugin>:<command>` or `/<plugin>:a:b`, are served as
  written. A skill and a command of one name read as the skill, as in Claude Code.
- **Order.** The rewrite runs before SKL-25 and SKL-52, and the prefix (SKL-41) applies after
  both. Every other file is served without it, and `_manifest` describes the bytes served
  (SKL-24).

**SKL-60.** kb rewrites what the plugin layer serves in one place, its one rewriter, which runs when
a build is made (SKL-58). In a skill's own `SKILL.md` it applies SKL-55, then SKL-25 and SKL-52, for
the request's scope. In an agent file it rewrites the body by AGT-17, then PRM-48, and leaves the
frontmatter as written. Every text file of a skill (SKL-22) has its line endings normalised to LF.
Everything else is served as written. The gateway prefix (SKL-41) is the plugin layer's to write,
after kb's rewriter.

**SKL-63.** No text kb's rewriter writes into a skill's file (SKL-60) names a view (SKL-24). A
qualified name reads as a skill's `SKILL.md` (SKL-55), and a placeholder as a library, a skill's
directory or a path below one (SKL-25, SKL-52). A view's address the skill's author wrote is served
as written.

**SKL-26.** A read returns only the file addressed. Nothing a file cites is fetched with it.

## Library files

**SKL-27.** A library file is one the plugin's `files` patterns select (PLG-10). Its address keeps
its path from the plugin root: `shared/api.md` is `skill://<library>/shared/api.md`.

**SKL-28.** A file inside any skill directory of the library, whichever plugin owns the skill, is
neither listed nor read as a library file. When the skill is another plugin's, this adds no
`skipped` row. A file named `_index.md`, `_index.json` or `_files.md`, or whose address meets one
of its own plugin's skill addresses, is skipped (PLG-18).

**SKL-29.** A library file is read from the first plugin, in the library's order, that lists that
path and is in scope.

## The plugin-root fallback

**SKL-30.** When a path under a skill names no file of the skill, it reads the file at the same
path below the root of the skill's own plugin: `skill://penpot/penpot-router/shared/api.md` reads
that plugin's `shared/api.md`. It never reaches another plugin's root. Neither serves an agent file
(AGT-3). The fallback reads through `resources/read`, and so through the
`read_resource` tool, alone. Its file is in no entry (SKL-33), so a host that verifies a skill's
files against its entry, as a Via `extension` client does, refuses it.

**SKL-31.** When a library-level path names no library file, it reads the file at that path from
the first in-scope plugin root of the library, in the library's order, that has one. It does not
apply to a path inside any skill's address, under any scope. Neither serves an agent file (AGT-3).

**SKL-32.** Both fallbacks refuse a hidden path, a file named `_index.md`, `_index.json` or
`_files.md`, a target resolving outside the plugin root, and a target inside any skill directory of
the library, served or skipped.

**SKL-33.** A file the skill has always wins over the fallback. Nothing is redirected: each address
reads the same bytes in place. Neither fallback adds a row to any listing, `_files.md`,
`_manifest` or extension entry.

## Misses and directories

**SKL-34.** A library, a folder and a skill's directory serve nothing. A `resources/read` of one
fails with `-32602` and `Resource not found: '<uri>'. <hint>`:

| Address | Hint names |
|---|---|
| a library with skills in scope | its `_index.md` |
| a library with only library files in scope | its `_files.md` |
| a skill's directory | its `SKILL.md` and its `_manifest` |
| a folder of skills / of library files | the folder's `_index.md` / the library's `_files.md` |
| a folder inside a skill | the folder's `_index.md` (`<uri> is a folder: read <uri>/_index.md to list it.`) |

A hint is given only for an address the plugin layer would read as kb does: none for one holding
`%2F` (SKL-13), and none when its `..` segments, resolved over the whole path as in SKL-13,
climb past the library and name another address. A hint names the address as sent.

**SKL-35.** A hint is worked out from the caller's scope. An out-of-scope address, directory or
not, fails exactly as an absent one does. A read that fails for any other reason keeps its error.

**SKL-36.** `resources/read` returns the `uri` the client sent. Its `name` is that URI without the
prefix (SKL-41) and without `skill://`.

## Live reads

**SKL-37.** When a file read, or a request that reads skills, agents or prompts, touches a
`cache: live` source ([config-and-sources.md](config-and-sources.md)), it starts that fetch's
revalidation in the background if one is due (SKL-38), and serves what is on disk now. That
covers library files and both fallbacks, and every file of each live skill, and each agent and
prompt file, of the plugins its scope admits. A read never waits for the server. A revalidation
lists the fetch once and downloads each of its files whose ETag moved. The first request after a
revalidation that moved a file re-reads that plugin and serves it again, every other plugin kept
as it is served. From that request on, a skill's files, its `_manifest`, its extension entry and
the plugin's agents and prompts describe the new bytes. So an edit is served once a revalidation
has seen it: about 2 seconds and one revalidation behind under steady traffic, and one request
behind on a quiet server. A request that arrives while a refresh is publishing re-reads nothing.

**SKL-38.** A fetch revalidated within the last 2 seconds, counted from when that revalidation
ended, is not revalidated again. One revalidation request times out after 1 second. A
revalidation that fails serves the copy on disk, and that fetch is not revalidated for 30
seconds. One revalidation at a time runs for the generation being served, and it covers every
live fetch that is due.

**SKL-39.** A live read changes only the bytes of files already harvested. What the plugin layer
serves follows a live re-read (SKL-37): a skill's files, its `_manifest`, its extension entry and
the plugin's agents and prompts. kb's own listing rows, index lines and their descriptions, and
files added or removed upstream, follow the next refresh, except that a skill a re-read leaves
unserved drops out of them, and comes back when it serves again (SKL-45). Only files already
harvested are watched, served or not: a prompt file skipped as broken serves from the request that
notices its fix, and a skill or a prompt file added to a live plugin is served from the next
refresh.

## Addresses behind a gateway

**SKL-40.** A request MAY name a **resource prefix**. It is the plugin layer's input (GW-1 to
GW-3), read with the server's header prefix `Kb` (DLV-16): `Kb-Resource-Prefix`, then
`X-MCP-Resource-Prefix`, then `?prefix=`, as in SCP-3. A space in the query value reads as `+`. A
valid prefix is a letter, then letters, digits, `+`, `-` or `.`, ending in `+` (`kb+`). An invalid
prefix is ignored.

**SKL-41.** With a prefix, every `skill://`, `prompts://` and `agents://` address in text a client
reads is written with the prefix in front (`kb+skill://`), except where the scheme follows a
letter, digit, `+`, `-` or `.` (`kb+skill://` and `myskill://` stay as they are).

| Where | Prefixed |
|---|---|
| resource bodies, listing descriptions, read hints, an extension entry's `frontmatter`, an agent's card and its `io.kubed/agent` `frontmatter` (AGT-9), the template's description | yes |
| tool results ([http-and-tools.md](http-and-tools.md)), instructions (INS-16), rendered prompts | yes |
| a listing row's `uri` and `name`, an extension entry's `uri` and each file `uri`, the template's `uriTemplate`, an agent definition's `_meta…skills` values | never |

| Written by | Where |
|---|---|
| the plugin layer | a skill's files, the indexes inside a skill and an agent's card (GW-5), rendered prompts (GW-7), the server instructions kb's instructions hook returns (DLV-11), and `list_resources`, which writes the prefix into each row's `uri` (DLV-6, GW-5) |
| kb, through the plugin layer's writer (GW-11) | everything else: resource bodies and listing descriptions outside a skill, read hints, the template's description |

A prompt's description in `prompts/list` is written as its library wrote
it, with no prefix: the plugin layer prefixes the text a prompt renders, and a prompt's
frontmatter is served as its file wrote it.

**SKL-42.** An incoming address (`resources/read`, `read_resource`, `skills/get`,
`resources/directory/read`) MAY be `skill://…` or `<prefix>skill://…` for the request's own prefix.
Any other prefix resolves to nothing. The plugin layer takes the prefix off before any
provider is asked (GW-4), so every provider sees the plain address; a read still answers with
the URI the client sent.

**SKL-43.** Neither a scope nor a prefix removes the library segment from an address.

## The Skills extension

**SKL-44.** Once the server serves a plugin with a skill, it declares
`io.modelcontextprotocol/skills` (value `{"directoryRead": true}`) on `server/discover` and on
legacy `initialize` alike, whether or not the client declared it (HTTP-27), and goes on declaring it for the
life of the process. The extension is FastMCP's, through kubed-mcp's plugin layer (SKL-58), and
adds nothing to `resources/list`. Until then (a deployment whose plugins serve only prompts or
agents, or a cold start with every source down) `server/discover` does not declare it, and
`skills/list` and `skills/get` answer `-32601` `Method not found`, and legacy `initialize`
does not declare it either.

**SKL-45.** Every served skill passes FastMCP's checks: strict YAML frontmatter that converts to
JSON, a `name` matching its address's last segment, a `description` of 1 to 1024 characters,
relative paths, no symlink, at most 512 files and 16 MiB. Its hidden paths count for none of
these: the plugin layer leaves them out, and one reads as nothing (SKL-3). A skill that fails is not served at all: none of its files reads, and no index, listing row, entry,
hint or rewritten name points at it. The server logs why, once. kb's catalogue is narrowed to what
the plugin layer serves once per generation, and again after a live re-read (SKL-37). A skill that
fails only in one view's build, such as under a prefix that takes its description past 1024
characters, does not read under that view and prefix, and kb's indexes, hints and rewritten names
under it still name it.

**SKL-46.** An entry describes one conforming skill:

```json
{"uri": "skill://grafana/loki/SKILL.md",
 "frontmatter": {"name": "loki", "description": "Query and troubleshoot logs."},
 "resources": [{"uri": "skill://grafana/loki/SKILL.md", "digest": "sha256:…", "size": 412}]}
```

`frontmatter` is the served `SKILL.md`'s frontmatter as FastMCP parses it: the YAML between the
`---` lines, so a block-scalar value ending the block has no final newline. `resources` holds every
file a read of the skill serves (SKL-21), `SKILL.md` included, by URI, and no view (SKL-24).

**SKL-47.** Each `digest` and `size` describe the UTF-8 bytes `resources/read` returns for that URI
under the same request headers, and equal the skill's `_manifest` (SKL-24). An entry is offered
only when every file it names reads as listed (F59).

**SKL-48.** `skills/list` returns the in-scope skills' entries, at most the request's max of them
(SKL-64), except under SKL-62, by URI, as
`{"resultType": "complete", "ttlMs": 0, "cacheScope": "private", "skills": [...]}`. It pages by the
server's page size, and kb sets none, so one page holds every entry listed. A skill the max leaves
out still answers `skills/get` and `resources/read`, and stays in every `_index.md` and
`_index.json`. A `cursor` the server never issued is ignored, which is kubed-mcp's known deviation
from SEP-2640.

**SKL-62.** Under Via `local`, `skills/list` lists no skill, and `skills/get` still serves each one
in scope (DLV-9, DLV-10). Under `mcp` and `extension` it lists them up to the request's max
(SKL-64). `Listed` does not change it. kb adds no filter of its own. Under `local` none is listed
and none counts as cut.

**SKL-64.** A listing the max cuts (SKL-14, SKL-48) keeps the first skills in the plugin layer's
order and leaves out the rest. That order is the one kb adds plugins in (SKL-58): libraries in
config order, each library's plugins in its order, and a plugin served by two libraries once in
each. A plugin's skills come folder by folder as the plugin layer finds them (SKL-1), and each
folder's skills by name. So a route over the max loses the last skills of its last library's last
plugins, and an operator chooses what is left out by the order of the config's libraries and of
each library's plugins. A scope cuts from what it admits. kb sets no `delivery.max`.

**SKL-49.** `skills/get` takes `uri`, which MUST be exactly a skill's `SKILL.md` address (after
SKL-42), and returns the same envelope with `skill`. Anything else, and an out-of-scope skill, fail
with `-32602` `Unknown skill URI: <uri>`.

**SKL-50.** Both apply the request's scope. A refused scope fails with `-32602` and the refusal
message, as in [scoping-and-instructions.md](scoping-and-instructions.md).

**SKL-51.** `resources/directory/read` takes `uri` and lists one directory's direct children as
`Resource` objects, sorted by URI, a page of 100 at a time with a decimal `cursor`. Every result
carries `resultType: "complete"`: a skill's directory's, a library's and a folder's. A directory is a
library, a folder, a skill's root or a folder inside a skill (SEP-2640): its URI has no trailing `/`
and it is never listed. A subdirectory is a child with `mimeType` `inode/directory`; the indexes,
`_files.md` and `_manifest` are beside a directory, not in it. A library's or folder's children are
its folders and skills (description: the skill count, or the skill's description) and its library
files and their folders, as the scope admits them (SCP-22); a skill's are its folders and files. A
file, an absent address and an out-of-scope one fail alike with `-32602` `Directory not found`.

## Folder indexes

**SKL-56.** Beside every directory of SKL-51 an `_index.json` reads as the JSON array
`resources/directory/read` returns for it, every page at once, with `mimeType`
`application/json`. Like the directory, it is not found where the directory is. It is text a client
reads, so with a prefix (SKL-41) every address in it, each `uri` included, carries the prefix, as
the `_index.md` beside it does and the plugin layer's `_index.json` inside a skill does (N18). It is a view (SKL-24).

**SKL-57.** Inside a skill, an `_index.md` beside its root and each of its folders reads one
`<uri>: <description>` line per child, a file's description being its first `# ` heading, else
`File from <name> skill`, and a folder's `A folder of the <name> skill`. Its text carries the prefix
(SKL-41). A library's and a folder's `_index.md` are SKL-17's. It is a view (SKL-24).
