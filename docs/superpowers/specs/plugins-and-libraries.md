# Plugins and libraries

A **plugin** is a folder of skills, prompts and library files at an address under a source. A
**library** picks plugins: from a marketplace, by name, or by query. This file covers how plugins
are declared, how a `plugin.json` and a `marketplace.json` are read, how libraries resolve, and what
happens when plugins collide. Sources and fetching are in
[config-and-sources.md](config-and-sources.md); what a skill is, and the harvest conventions, are in
[skills.md](skills.md); prompt dialects are in [prompts.md](prompts.md).

## Declaring a plugin

**PLG-1.** A plugin is an entry under `plugins:` with these keys. Any other key fails the config.

| Key | Type | Default |
|---|---|---|
| `name` | string, `^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$`, unique among plugins | required |
| `source` | an address (PLG-3) | required |
| `description` | string | `""` |
| `category` | string | none |
| `tags`, `keywords` | list of strings | `[]` |
| `version` | string | none |
| `skills`, `prompts`, `files` | list of glob patterns (PLG-9) | absent |
| `dialect` | `auto`, `mcp-kb`, `claude` or `copilot` | `auto` |

**PLG-2.** A declared plugin's id is its name. Its **labels** are its `tags` and `keywords`
together, and selectors (LIB-9) and tag scopes match labels, never the two fields apart.

## The address

**PLG-3.** An address is `<scheme>://<path>[//<subdir>][?ref=<ref>]`. The scheme is the name of a
declared source, or `file`, which needs no source entry and takes an absolute path
(`file:///srv/prompts`).

**PLG-4.** The first `//` after the scheme separates the path from the subdir. Trailing `/` is
stripped from the path; leading and trailing `/` from the subdir.

**PLG-5.** An address is refused when it has no path, has a `..` segment in its path or subdir, is a
`file://` address whose path is not absolute, is a source address whose path starts with `/`,
carries any query key other than `ref`, or has `?ref=` with no value.

**PLG-6.** Loading the config refuses an address whose scheme names no declared source (the message
lists the declared ones), and an address with `?ref=` whose source is not git.

**PLG-7.** A fetch is identified by `<scheme>://<path>[?ref=<ref>]`, without the subdir. Plugins
whose addresses share that key share one fetch: one materialisation, however many plugins and
libraries read it.

**PLG-8.** The **plugin root** is the fetch's tree joined with the subdir. When that is not a
directory, or resolves outside the tree through a symlink, the plugin fails with
`<subdir> is not a directory in <fetch key>`.

## What a plugin serves

**PLG-9.** `skills`, `prompts` and `files` are glob patterns relative to the plugin root. Loading
the config refuses an empty pattern, an absolute one, and one with a `..` segment.

| The key | Means |
|---|---|
| absent | the conventions, the manifest and the entry, merged per kind (PLG-17) |
| a list | exactly these patterns, replacing the conventions |
| `[]` | serve nothing of this kind |

**PLG-10.** `files` has no convention. A plugin serves library files only when a `files` list
names them.

**PLG-11.** A pattern whose last component is `**` is read as `**/*`, so it matches files on every
Python version.

**PLG-12.** A `dialect` other than `auto` reads every prompt file of the plugin in that dialect, and
an object-map command is `claude` whatever the plugin's `dialect` says (PLG-21). With `auto`, a file
ending `.prompt.md` is left to detection; a file under `commands/` or `.claude/commands/` (relative
to the plugin root), or one matched by a `commands` declaration from a manifest or a marketplace
entry, is read as `claude`; every other file is left to detection. A config's own `prompts:` list is
not a `commands` declaration. Dialects are in [prompts.md](prompts.md).

## The plugin manifest

**PLG-13.** A plugin's manifest is the first of `.claude-plugin/plugin.json` and `plugin.json`
under its root. A manifest that is a symlink resolving outside the root is not read.

**PLG-14.** Seven fields are read: `description`, `version`, `keywords`, `skills`, `commands`,
`agents` and `mcpServers`. Every other field, `name` included, is ignored.

**PLG-15.** A manifest that is not readable JSON, or not a JSON object, fails the plugin.
`keywords`, `skills` and `agents` each take one string or a list of strings, and `commands` takes
one string, a list of strings or an object map (PLG-21); any other type fails the plugin, naming
the field. A non-string `description` or `version` is ignored.

**PLG-16.** A component path (`skills`, `commands`, `agents`, `mcpServers`) loses a leading `./`,
and `.` and `./` name the plugin root. A path that is empty, absolute or holds a `..` segment is
dropped with a note (PLG-26) and the rest are kept. A `commands` path ending `.md` names that file;
any other names a directory, read recursively for `*.md` (PLG-25). Either is a path, not a glob
(PLG-21).

**PLG-17.** The manifest and the marketplace entry complete the plugin, for declared plugins and
marketplace entries alike. The manifest's `description` is used only when the plugin's own is
empty. Its `version` overrides a marketplace entry's, as in Claude Code, while a declared plugin's
own `version:` overrides the manifest's; either side fills in when the other has none. Its
`keywords` are appended to the plugin's, duplicates dropped. Each kind of component is decided by
the first rule that applies:

| Kind | Rule |
|---|---|
| skills | a declared plugin's own `skills:` is exactly what it serves (LIB-33); an entry at the marketplace root that lists `skills` serves the entry's and the manifest's, without the conventions (LIB-32); a manifest or an entry that lists `skills` adds to the conventions, the manifest's then the entry's (PLG-20, LIB-30); otherwise the conventions |
| prompts | a declared plugin's own `prompts:` is exactly what it serves (LIB-33); a manifest or an entry that sets `commands` serves the manifest's then the entry's, without the conventions (PLG-21, LIB-30); otherwise the conventions |
| agents | a plugin with neither a manifest nor an entry has none (AGT-4); a manifest or an entry that sets `agents` names the manifest's then the entry's (PLG-22, LIB-30); otherwise the `agents/` folder |

`files` never comes from a manifest or an entry. The manifest is read on every assembly, so its
keywords reach selectors, scopes and `/health`.

## Inside one plugin

**PLG-18.** What a plugin's harvest finds is admitted per plugin, the same way in every library. A
thing left out is a row `{path, reason}` under the plugin's `skipped` in `/health`; the rest of the
plugin serves.

| Left out | When |
|---|---|
| a skill | its `name` breaks the naming rule in [skills.md](skills.md) |
| a skill | its `name` differs from its directory's name, unless the skill is the plugin root |
| a skill | an earlier skill of the plugin has its address |
| a library file | its name is `_index.md` or `_files.md` |
| a library file | its address is a served skill's, lies inside one, or contains one |
| a prompt | the name its path builds is not a usable name (PLG-25) |
| a prompt | an earlier prompt of the plugin has its name (PLG-25) |
| an agent | the name its folders and frontmatter `name` build is not a usable name (AGT-5) |

**PLG-19.** A plugin **fails** when its fetch has no servable tree, its root is refused (PLG-8), its
manifest is refused (PLG-15), its entry conflicts with its manifest (LIB-31), or reading its files
errors. A failed plugin serves nothing in any library and carries `status: failed` and an `error` in
`/health`. No other plugin or library is affected.

## Libraries

**LIB-1.** A library is an entry under `libraries:` with these keys. Any other key fails the config.

| Key | Type | Default |
|---|---|---|
| `name` | string, same pattern as a plugin name, unique among libraries | required |
| `description` | string | `""` |
| `notes` | string | `""` |
| `listSkills` | boolean | `true` |
| `source` | an address (PLG-3) | none |
| `plugins` | list of plugin ids | `[]` |
| `pluginSelector` | `{categories: [..], tags: [..]}` | none |
| `categories` | list of strings | `[]` |

**LIB-2.** A library's plugins are the union of three ways to pick them: `source` (every entry of
the marketplace there), `plugins` (by id) and `pluginSelector` (by query).

**LIB-3.** Loading the config refuses a library with none of the three, a library with both
`source` and `pluginSelector`, and a `plugins` item without `@` that names no declared plugin. An
item with `@` names a marketplace entry and is not checked at load.

**LIB-4.** Libraries resolve in two phases. First every marketplace is read and its entries join
the declared plugins. Then each library resolves against that whole set, each plugin completed by
its manifest: its marketplace's entries in catalogue order, then its `plugins` in listed order,
then its selector's matches. Duplicates keep their first place.

**LIB-5.** The selector runs over declared plugins in config order, then every marketplace's
entries in library order, so a selector can gather entries from any marketplace.

**LIB-6.** A `plugins` item with `@` that matches no plugin is an `error` on the library,
`no plugin named '<id>'; <library> publishes: <names>` (the list is left off when that marketplace
publishes nothing). The rest of the library serves.

## The selector

**LIB-7.** `categories` is any of: a plugin matches when its `category` is one of them. A plugin
with no category matches no non-empty list. A comma inside a category is refused at load.

**LIB-8.** Each `tags` item is a group, and a comma inside an item means all of: `["ui,tokens",
penpot]` is (ui and tokens) or penpot. Blank pieces are dropped.

**LIB-9.** A plugin matches when its category matches and some tag group is a subset of its
labels. An empty field constrains nothing, so `pluginSelector: {}` selects every plugin. A
selector never reads a library's `categories`.

## Marketplaces

**LIB-10.** A library with a `source` is a marketplace library. Its marketplace root is the fetch's
tree joined with the address's subdir.

**LIB-11.** The catalogue is the first of `.claude-plugin/marketplace.json`,
`.github/plugin/marketplace.json` and `.agents/plugins/marketplace.json` under that root. A file
that is a symlink resolving outside the root is not read.

**LIB-12.** When the catalogue cannot be read, the library carries an `error` and still serves its
`plugins` list:

| Case | `error` |
|---|---|
| the fetch has no servable tree | the fetch's error, else `the marketplace could not be fetched` |
| the subdir is not a directory in the tree | `<subdir> is not a directory in <fetch key>` |
| none of the three files exists | `no marketplace.json under <subdir, or />` |
| the file is not readable JSON | `<file> is not readable JSON: …` |
| the JSON is nested too deeply to parse | `<file> is nested too deeply to read` |
| the JSON is not an object with a `plugins` list | `<file> must be an object holding a plugins list` |

**LIB-13.** Each entry becomes a plugin with id `<entry name>@<library>`, and with the entry's
`name`, `description` (`""` unless a string), `category` (a string or none), `tags` and `keywords`
(lists; non-string items dropped, any other type read as empty) and `version`, which the plugin's
own `plugin.json` overrides when it sets one (PLG-17). Other entry fields are ignored, except as
LIB-14 and LIB-31 say.

**LIB-14.** An entry's `skills`, `commands`, `agents` and `mcpServers` are read as a manifest's are
(PLG-15, PLG-16), except that a wrong type skips the entry (LIB-19) rather than failing it, and its
`commands` count as a `commands` declaration (PLG-12). Its lists append to the manifest's (LIB-30),
and a kind it does not list is left to the manifest and the conventions (PLG-17). An entry never
sets `files`.

**LIB-15.** An entry's `source` takes these forms:

| Form | Read as |
|---|---|
| a string (`"./"`, `"./plugins/x"`) | a subdir under the marketplace's own subdir, in the marketplace's own fetch |
| `{source: github, repo, sha\|ref}` | `repo` under the declared git source whose URL is `https://github.com` |
| `{source: url, url, sha\|ref}` | the repository below the declared git source whose URL prefixes `url` |
| `{source: git-subdir, url, path, sha\|ref}` | as `url`, with `path` as the subdir |

**LIB-16.** A string source drops `.` segments. Its `..` segments may climb back only through what
it added, never above the marketplace's subdir.

**LIB-17.** For `url` and `git-subdir`, a source's URL prefixes `url` when `url` starts with that
URL (less `git+` and any trailing `/`) followed by `/`. A trailing `.git` is removed from the path
below it.

**LIB-18.** The pin is `sha` when set, else `ref`. An empty string counts as unset. The repository
is spelled `<source name>://<path>[?ref=<pin>]` and parsed as an address (PLG-5), so an entry on the
same repository and pin as a declared plugin shares its fetch (PLG-7).

**LIB-19.** An entry that cannot be served is **skipped**, never guessed at, and nothing an entry
names is executed or unpacked:

| Entry | Reason given |
|---|---|
| not an object | `an entry must be an object` |
| `name` missing or not a valid plugin name | `<name> is not a plugin name` |
| `source` missing or not a string/object with a string `source` | `an entry needs a source` |
| a string source that is absolute, or climbs out | `… is not a relative path`, `… escapes the marketplace` |
| `github` without `repo`; no `https://github.com` git source | `a github entry needs a repo`; `no source for github.com is declared` |
| `url`/`git-subdir` without `url`; no source prefixes it | `a <kind> entry needs a url`; `no source for <host> is declared` |
| `git-subdir` with a blank `path` | `a git-subdir entry needs a path` |
| `sha` or `ref` that is not a string | `<field> must be text naming a commit or a ref` |
| `skills` or `agents` that is not a string or a list of strings, or `commands` that is none of those nor an object | `<field> must be a string or a list of strings` |
| any other `source` type (`npm`, `archive`, `command`, …) | `source type <kind> is not supported` |
| an address the parse refuses | the parse's message |

**LIB-20.** Each skip is a row `{plugin, reason}` under the library's `skipped` in `/health`, with
`plugin` set to `?` for a nameless entry. A skip never costs the other entries. A reason names a
host, never a URL, and URL userinfo in any row is masked.

**LIB-21.** The catalogue is re-read from its tree on every assembly, cold start and refresh alike,
so a refreshed marketplace serves the entries it holds at that refresh.

**LIB-22.** No config key overrides a marketplace entry's fields. A plugin declared against the
same address serves beside it, with its own metadata and globs, from the same fetch.

## What a library says

**LIB-23.** A library's **resolved description** is the first non-blank of: its configured
`description`; its marketplace's top-level `description`, else `metadata.description` (non-strings
ignored); its plugins' descriptions, each trimmed, blanks and duplicates dropped, one per line in
the library's plugin order; else `""`. URL userinfo in the second and third is masked.

**LIB-24.** `notes` follows the resolved description, whichever tier it came from.

**LIB-25.** The resolved description and the notes open the library's section of the server
instructions ([scoping-and-instructions.md](scoping-and-instructions.md)) and its `_index.md`
([skills.md](skills.md)). `/health` reports the resolved description under the library.

**LIB-26.** `listSkills: false` keeps the library's skill names out of the server instructions.
When `true`, whether names are listed is decided as in
[scoping-and-instructions.md](scoping-and-instructions.md).

**LIB-27.** `categories` items are trimmed, blanks and duplicates dropped, and an item with a comma
is refused at load. They label the library for a category scope
([scoping-and-instructions.md](scoping-and-instructions.md)) and nothing else: no plugin's
`category` changes. `/health` reports them under the library.

## Between plugins in one library

**LIB-28.** A library walks its plugins in order, and each plugin claims what it serves there. A
later plugin **conflicts** with the claims when:

- one of its skill URIs is, lies inside, or contains a claimed skill URI or library file URI;
- one of its library file URIs (`skill://<library>/<path>`) is, lies inside, or contains a claimed
  library file URI or skill URI;
- one of its prompt names is a claimed prompt name.

**LIB-29.** A conflicting plugin serves nothing in that library. The earlier plugin keeps serving,
and the library's `conflicts` in `/health` maps the later plugin's id to
`conflict: <uri or prompt name> is already served by plugin '<owner>'`. The same plugin serves
normally in every other library. A failed plugin (PLG-19) claims nothing.

## Reading a plugin the way Claude Code does

These requirements make one `plugin.json` mean the same in kb as in Claude Code, for the kinds kb
serves.

**PLG-20.** A manifest `skills` list **adds** to the default skill scan, across all of kb's skill
roots. `"."` and `"./"` name the plugin root.

**PLG-21.** A manifest `commands` **replaces** the default prompt scan, across all of kb's prompt
conventions. It may be a path, a list of paths, or an **object map**. In a map, the key is the
prompt's name, `source` names a file or `content` holds an inline body (exactly one of the two),
and `description` and `argumentHint`, when set, are the prompt's description and its free-text
argument's hint, ahead of any the body's own frontmatter gives. `model` and `allowedTools` are
dropped like the other client-only keys. A map item that is not an object, that has both or
neither of `source` and `content`, whose `source` is not a path inside the plugin, or whose
`content` is not text, is dropped with a note (PLG-26), and the rest of the map serves. So is one
whose key is not a usable name: empty, or holding whitespace, a control or other invisible
character, `/` or `@`, noted `commands entry <key> is not a usable name` with the key quoted
escaped. A `source`
that is not a file in the plugin is skipped with `not a file in the plugin`. An inline command's
path in `/health` is the manifest's. Every map command is read in the `claude` dialect.
A path in a `commands` list, from a manifest or an entry, is a path and not a glob, as in Claude
Code: `./cmds/[draft].md` is that file and never `cmds/d.md`, `./stars/*.md` names no file, and
`./v[1]` is that folder and not `v1/`. A listed file is served in a dot folder too
(`./.private/x.md`); one that names no file in the plugin, or resolves outside it, serves nothing
and is noted `commands entry '<path>' is not in the plugin` (PLG-26). A listed folder is read
without any hidden folder (SKL-3) on its path from the plugin root, its own included, so a listed
`./.private/cmds` serves nothing and neither does `more/.h/x.md` under a listed `./more`. Claude
Code reads both; this is a known difference. Every file a `commands` list selects is read in the
`claude` dialect. A declared plugin's own `prompts:` is a glob (LIB-33).

**PLG-22.** A manifest `agents` list of `.md` files **replaces** the default `agents/` scan (see
[agents.md](agents.md)). An item that does not name a `.md` file is dropped with a note (PLG-26).

**PLG-23.** When `commands` or `agents` is set and the plugin root has the folder of that name, the
folder is read only for what the key names. When no path the key declares names the folder, a
path inside it or the plugin root, the plugin notes
`Default <folder>/ folder is ignored because the manifest sets "<key>"`, whether the manifest or
the entry set it. As in Claude Code, `"agents": ["./agents/reviewer.md"]`, `"commands": "./commands/"`,
a `commands` map item whose `source` is in `commands/`, and `"commands": "./"` earn no note.

**PLG-24.** A component path that doesn't start with `./` is still served, and the plugin notes it.
This is a deliberate deviation: `claude plugin validate` refuses such a path, and kb serves rather
than validates.

**PLG-25.** A prompt's name below its library is decided where it was found:

| Found | Name |
|---|---|
| under `commands/` or `.claude/commands/`, or under a directory a `commands` declaration names | each folder between that directory and the file, then the file stem, joined with `_`: `commands/db/migrate.md` is `<library>_db_migrate` |
| as a key of a `commands` object map | the key |
| anywhere else | the file stem (PRM-42) |

The `commands/` convention reads its subfolders (`commands/**/*.md`), and so does a directory
named in a `commands` list. Files come in path order, then the map's commands. A name built from a
path, the folders and the stem together, MUST be a usable name, as a map key is (PLG-21): a file
whose name is not, `commands/my db/x.md` or `prompts/a b.md`, is skipped with
`prompt name <name> is not a usable name`, the name quoted escaped, and never claims the name. A
later prompt of the plugin with an earlier one's name is skipped with
`prompt <name> is already served by <path>`.

**PLG-26.** A plugin's `notes` in `/health` lists what its manifest, its entry and its `.mcp.json`
got wrong without failing it:

- a component path dropped for leaving the plugin root (PLG-16), and one served without `./`
  (PLG-24);
- an object-map item dropped (PLG-21), for its key as for its value, an `agents` item dropped
  (PLG-22), and an `agents` item that names no file in the plugin,
  `agents entry '<path>' is not in the plugin` (AGT-5);
- a listed `commands` file that names no file in the plugin,
  `commands entry '<path>' is not in the plugin` (PLG-21);
- a default folder ignored (PLG-23);
- an `mcpServers` that is neither an object nor a path, a file it names that is not in the plugin,
  and a root `.mcp.json` or named file that is not a JSON object (PLG-27).

Each note is listed once, with no cache path, and is present only when not empty. A note never
fails the plugin. kb logs a new note once, at `WARNING`.

**PLG-27.** The MCP servers a plugin declares are the names in its root `.mcp.json` (the keys of its
`mcpServers` object, else its top-level keys), in its manifest's `mcpServers` (an object's keys, or
the file a string names, read the same way), and, only when it has no `plugin.json`, in its
entry's `mcpServers`: beside a `plugin.json`, an entry's `mcpServers` don't apply, as in Claude
Code. Only the names are kept, sorted and deduplicated. AGT-9 serves them as an agent definition's `_meta…servers`, and kb
never connects to, starts or forwards a server.

**LIB-30.** A marketplace entry beside a `plugin.json` with `strict` absent or true **appends** its
`skills`, `commands` and `agents` to the manifest's. Its `mcpServers` don't apply beside a
`plugin.json` (PLG-27).

**LIB-31.** Without a `plugin.json`, the entry is the manifest, whatever `strict` says. Beside a
`plugin.json`, an entry with `strict: false` that names any of `skills`, `commands`, `agents`,
`hooks`, `outputStyles` or `themes` is a conflict: the plugin fails (PLG-19) with the error
`conflicting manifests`. An entry with `strict: false` that names none of them is ordinary.

**LIB-32.** An entry whose `source` is the marketplace root and that lists `skills` serves those
and its manifest's `skills`, and the default skill scan is off for it.

**LIB-33.** A declared plugin's own `skills:` and `prompts:` override its manifest and the
conventions completely, per kind.
