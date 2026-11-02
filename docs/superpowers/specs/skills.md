# Skills

A **skill** is a directory holding a `SKILL.md`. This file covers which directories count as
skills, the `skill://` address space that skills and a library's other files live in, what each
address reads as, the gateway prefix, and the MCP Skills extension. Declaring plugins and their
globs is in [plugins-and-libraries.md](plugins-and-libraries.md); who may see what is in
[scoping-and-instructions.md](scoping-and-instructions.md); the mirror tools are in
[http-and-tools.md](http-and-tools.md).

## What makes a skill

**SKL-1.** A skill is a directory inside its plugin root that holds a regular file named
`SKILL.md` and that the plugin's `skills` patterns select (PLG-9). With no patterns from the
config or the manifest, these conventions apply. A `SKILL.md` at the plugin root is not one of them.

| Pattern | Reaches |
|---|---|
| `skills/**/SKILL.md` | any depth |
| `.github/skills/*/SKILL.md`, `.claude/skills/*/SKILL.md`, `.agents/skills/*/SKILL.md` | one level |

**SKL-2.** A pattern may name the `SKILL.md` or a directory. A matched directory contributes every
`SKILL.md` beneath it, so `skills: ["skills"]` registers every skill under `skills/`.

**SKL-3.** A path is **hidden** when any segment starts with `.`, except `.github`, `.claude` and
`.agents`, kept at any depth. Hidden paths are never harvested, listed or read.

**SKL-4.** A pattern hit is kept only when it resolves inside the plugin root. It is named by the
path the pattern matched, not by its symlink target.

**SKL-5.** A skill's name is its frontmatter `name`, else its directory's name. Its description is
the frontmatter `description` with each run of whitespace collapsed to one space, else empty.
Frontmatter that does not parse counts as absent.

**SKL-6.** A skill's name MUST keep the Agent Skills naming rule: 1 to 64 lowercase letters,
digits and single hyphens, no hyphen first or last. It MUST equal its directory's name, unless the
skill is the plugin root itself. A skill that breaks either, or whose address an earlier skill of
the plugin (in path order) already has, is skipped as in PLG-18.

**SKL-7.** A skill MAY sit inside another skill's directory. Both are served, each at its own
address. Overlapping skills of two plugins in one library are a conflict, as in
[plugins-and-libraries.md](plugins-and-libraries.md).

## Addresses

**SKL-8.** Everything in this area is a `skill://` URI:

| URI | Reads as |
|---|---|
| `skill://<library>/_index.md` | the library's folders and skills |
| `skill://<library>/<folder>/_index.md` | one folder's folders and skills |
| `skill://<library>/<folder>/<name>/SKILL.md` | a skill's instructions |
| `skill://<library>/<folder>/<name>/_manifest` | the files that skill ships, as JSON |
| `skill://<library>/<folder>/<name>/<path>` | one file of that skill |
| `skill://<library>/_files.md` | the library's files outside every skill |
| `skill://<library>/<path>` | one of those files |

**SKL-9.** `<library>` is the library's name, so a plugin served by two libraries has its skills at
two addresses. A skill's **address** is `<library>/<folder>/<name>`, without an empty folder.

**SKL-10.** `<folder>` is the path of the skill directory's parent below the plugin root, with the
deepest of `skills/`, `.github/skills/`, `.claude/skills/` and `.agents/skills/` that contains it
taken off. It may be empty or several segments deep.

| Skill directory | Address in library `grafana` |
|---|---|
| `skills/loki` | `grafana/loki` |
| `skills/grafana-lgtm/loki` | `grafana/grafana-lgtm/loki` |
| `docs/kits/loki` | `grafana/docs/kits/loki` |
| the plugin root, named `loki` | `grafana/loki` |

**SKL-11.** A skill is identified by its full address, never by its name alone. Two skills of one
name in different folders or libraries are both served.

**SKL-12.** A path below a library resolves to the skill whose address is its longest prefix, so a
file under a nested skill belongs to the nested skill.

**SKL-13.** Before any other check, the path below the library has its `.` and `..` segments
removed as in RFC 3986. A `..` with nothing before it is dropped, so no address leaves its library.
Percent-escapes are not decoded. A URI that does not start with `skill://` resolves to nothing.

## The listing

**SKL-14.** `resources/list` holds index rows only. For each library, in name order:

| Row | Present when | Description |
|---|---|---|
| `skill://<library>/_index.md` | a skill of the library is in scope | `The <library> library — N skills in M folders: a, b.` (folder clause only when there are folders) |
| `skill://<library>/<folder>/_index.md`, per top-level folder | a skill under it is in scope | `N skills in the <folder> folder of the <library> library.` |
| `skill://<library>/_files.md` | a library file is in scope | `Files the <library> library ships outside any skill, which its skills reference.` |

**SKL-15.** A row's `name` is its URI without `skill://`, its `mimeType` is `text/markdown`, and
its tags are the library's name and `index`.

**SKL-16.** With the listing set to `full` (`?listing=full` or `Kb-Listing: full`, read as in
SCP-3, any case), the listing adds one row per in-scope skill, by address: its `SKILL.md` URI, the
name `<address>/SKILL.md`, the skill's description, and its library and plugin labels as tags.

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
symlink is followed only while its target stays inside the skill directory. A directory, a hidden
path and a missing file read as nothing.

**SKL-22.** Every file read through this address space is decoded as UTF-8 with invalid bytes
replaced, has its line endings normalised to LF, and is returned as text.

**SKL-23.** A read's media type is `application/json` for a skill's `_manifest`, else the type
guessed from the extension, else `text/markdown`. `.md` is `text/markdown`. A library file named
`_manifest` is not JSON.

**SKL-24.** A skill's `_manifest` lists every regular file under the skill directory, nested
skills' files included, leaving out hidden paths and symlinks, sorted by path. Size and hash
describe the bytes on disk, before any substitution.

```json
{"skill": "grafana/grafana-lgtm/loki",
 "files": [{"path": "SKILL.md", "size": 2310, "hash": "sha256:…"}]}
```

**SKL-25.** In a skill's `SKILL.md`, `${CLAUDE_PLUGIN_ROOT}` reads as `skill://<library>` and
`${CLAUDE_SKILL_DIR}` as `skill://<address>`. Every other `${…}` is served as written, and every
other file is served without substitution. Prompt bodies follow [prompts.md](prompts.md).

**SKL-52.** *(proposed; narrows SKL-25)* In a skill's `SKILL.md`, `${CLAUDE_PLUGIN_ROOT}/<path>`
whose `<path>` is the directory of a served skill of the same plugin in the same library, or lies
below one, reads as that skill's address with the rest of the path kept:
`${CLAUDE_PLUGIN_ROOT}/skills/drawio/references/xml.md` reads as
`skill://drawio/drawio/references/xml.md`. The deepest such skill wins. A directory name ends at
`/` or at a character that cannot continue it; a letter, a digit, `_`, `-`, `~`, `%`, `+` and `@`
continue it, and so does a `.` followed by one of those or by another `.`. So `skills/drawio.md`
and `skills/drawio-x/` are not in `skills/drawio`, and a sentence ending `skills/drawio.` is. When
the plugin root is itself a skill's directory, `${CLAUDE_PLUGIN_ROOT}/<path>` outside every nested
skill reads as `skill://<address>/<path>`. A bare `${CLAUDE_PLUGIN_ROOT}`, a path in a skipped
skill and a path in another plugin's skill read as SKL-25 says. `./`, `//` and `..` after the
placeholder are not normalised. Nothing is served at an address that was not served before.

**SKL-26.** A read returns only the file addressed. Nothing a file cites is fetched with it.

## Library files

**SKL-27.** A library file is one the plugin's `files` patterns select (PLG-10). Its address keeps
its path from the plugin root: `shared/api.md` is `skill://<library>/shared/api.md`.

**SKL-28.** A file inside any skill directory of the library, whichever plugin owns the skill, is
neither listed nor read as a library file. When the skill is another plugin's, this adds no
`skipped` row. A file named `_index.md` or `_files.md`, or whose address meets one of its own
plugin's skill addresses, is skipped (PLG-18).

**SKL-29.** A library file is read from the first plugin, in the library's order, that lists that
path and is in scope.

## The plugin-root fallback

**SKL-30.** When a path under a skill names no file of the skill, it reads the file at the same
path below the root of the skill's own plugin: `skill://penpot/penpot-router/shared/api.md` reads
that plugin's `shared/api.md`. It never reaches another plugin's root.

**SKL-31.** When a library-level path names no library file, it reads the file at that path from
the first in-scope plugin root of the library, in the library's order, that has one. It does not
apply to a path inside any skill's address, under any scope.

**SKL-32.** Both fallbacks refuse a hidden path, a file named `_index.md` or `_files.md`, a target
resolving outside the plugin root, and a target inside any skill directory of the library, served
or skipped.

**SKL-33.** A file the skill has always wins over the fallback. Nothing is redirected: each address
reads the same bytes in place. Neither fallback adds a row to any listing, `_files.md` or
`_manifest`.

## Misses and directories

**SKL-34.** A library, a folder and a skill's directory serve nothing. A `resources/read` of one
fails with `-32602` and `Resource not found: '<uri>'. <hint>`:

| Address | Hint names |
|---|---|
| a library with skills in scope | its `_index.md` |
| a library with only library files in scope | its `_files.md` |
| a skill's directory | its `SKILL.md` and its `_manifest` |
| a folder of skills / of library files | the folder's `_index.md` / the library's `_files.md` |

**SKL-35.** A hint is worked out from the caller's scope. An out-of-scope address, directory or
not, fails exactly as an absent one does. A read that fails for any other reason keeps its error.

**SKL-36.** `resources/read` returns the `uri` the client sent. Its `name` is that URI without the
prefix (SKL-41) and without `skill://`.

## Live reads

**SKL-37.** When a file read belongs to a `cache: live` source
([config-and-sources.md](config-and-sources.md)), the read first revalidates that one file against
the server: a skill's files, library files and both fallbacks alike. A `_manifest` read
revalidates every file it lists first.

**SKL-38.** A revalidated file is trusted for 2 seconds. A revalidation that fails, including a
request that takes over 1 second, serves the copy on disk, and that source is not revalidated for
30 seconds.

**SKL-39.** A live read changes only the bytes of files already harvested. Listing rows, index
lines, descriptions, and files added or removed upstream follow the next refresh.

## Addresses behind a gateway

**SKL-40.** A request MAY name a **resource prefix** (`Kb-Resource-Prefix` or `?prefix=`, read as
in SCP-3). A space in the query value reads as `+`. A valid prefix is a letter, then letters,
digits, `+`, `-` or `.`, ending in `+` (`kb+`). An invalid prefix is ignored.

**SKL-41.** With a prefix, every `skill://` in text a client reads is written `<prefix>skill://`,
except where `skill://` follows a letter, digit, `+`, `-` or `.` (`kb+skill://` and `myskill://`
stay as they are).

| Where | Prefixed |
|---|---|
| resource bodies, listing descriptions, read hints, an extension entry's `frontmatter` | yes |
| tool results ([http-and-tools.md](http-and-tools.md)), instructions (INS-16), rendered prompts | yes |
| a listing row's `uri` and `name`, an extension entry's `uri` and each file `uri` | never |

**SKL-42.** An incoming address (`resources/read`, `read_resource`, `skills/get`) MAY be
`skill://…` or `<prefix>skill://…` for the request's own prefix. Any other prefix resolves to
nothing.

**SKL-43.** Neither a scope nor a prefix removes the library segment from an address.

## The Skills extension

**SKL-44.** The server declares `io.modelcontextprotocol/skills` (value `{}`) on
`server/discover` and on `initialize`, whether or not the client declared it (HTTP-27). The
extension adds nothing to `resources/list`.

**SKL-45.** A skill is **conforming** when its served `SKILL.md` starts with `---` and a newline,
the frontmatter parses and converts to JSON, `name` equals the skill's name, and `description` is a
string of 1 to 1024 characters. A non-conforming skill is still served as resources.

**SKL-46.** An entry describes one conforming skill:

```json
{"uri": "skill://grafana/loki/SKILL.md",
 "frontmatter": {"name": "loki", "description": "Query and troubleshoot logs."},
 "resources": [{"uri": "skill://grafana/loki/SKILL.md", "digest": "sha256:…", "size": 412}]}
```

`frontmatter` is the served `SKILL.md`'s frontmatter. `resources` holds every file a read of the
skill serves, `SKILL.md` included: regular, not hidden, resolving inside the skill directory,
nested skills' files included.

**SKL-47.** Each `digest` and `size` describe the UTF-8 bytes `resources/read` returns for that URI
under the same request headers: after SKL-22, SKL-25 and the prefix. They differ from `_manifest`
for a file those change.

**SKL-48.** `skills/list` returns every conforming in-scope skill's entry, by URI, as
`{"resultType": "complete", "ttlMs": 0, "cacheScope": "private", "skills": [...]}`. It does not
paginate: any `cursor` fails with `-32602` `Invalid skills cursor`.

**SKL-49.** `skills/get` takes `uri`, which MUST be exactly a skill's `SKILL.md` address, and
returns the same envelope with `skill`. Anything else, an out-of-scope skill and a non-conforming
one fail with `-32602` `Skill not found`.

**SKL-50.** Both apply the request's scope. A refused scope fails with `-32602` and the refusal
message, as in [scoping-and-instructions.md](scoping-and-instructions.md).

**SKL-51.** `resources/directory/read` is not implemented and fails with `-32601`.
