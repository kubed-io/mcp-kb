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
| absent | the plugin's manifest decides (PLG-17), and failing that the harvest conventions |
| a list | exactly these patterns, replacing the conventions |
| `[]` | serve nothing of this kind |

**PLG-10.** `files` has no convention. A plugin serves library files only when a `files` list
names them.

**PLG-11.** A pattern whose last component is `**` is read as `**/*`, so it matches files on every
Python version.

**PLG-12.** A `dialect` other than `auto` reads every prompt of the plugin in that dialect. With
`auto`, a file ending `.prompt.md` is left to detection; a file under `commands/` or
`.claude/commands/` (relative to the plugin root), or one matched by a `commands` declaration from
a manifest or a marketplace entry, is read as `claude`; every other file is left to detection.
A config's own `prompts:` list is not a `commands` declaration. Dialects are in
[prompts.md](prompts.md).

## The plugin manifest

**PLG-13.** A plugin's manifest is the first of `.claude-plugin/plugin.json` and `plugin.json`
under its root. A manifest that is a symlink resolving outside the root is not read.

**PLG-14.** Five fields are read: `description`, `version`, `keywords`, `skills` and `commands`.
Every other field, `name` included, is ignored.

**PLG-15.** A manifest that is not readable JSON, or not a JSON object, fails the plugin.
`keywords`, `skills` and `commands` each take one string or a list of strings; any other type fails
the plugin, naming the field. A non-string `description` or `version` is ignored.

**PLG-16.** A component path (`skills`, `commands`) loses a leading `./`. A path that is empty,
absolute or holds a `..` segment is dropped and the rest are kept. A `commands` path ending `.md`
names that file; any other names a directory and becomes `<path>/*.md`, not recursive.

**PLG-17.** The manifest completes the plugin, for declared plugins and marketplace entries alike:

| Field | Rule |
|---|---|
| `description`, `version` | used only when the plugin's own is empty |
| `keywords` | appended to the plugin's keywords, duplicates dropped |
| `skills` | the skills patterns, when the plugin's `skills` is absent |
| `commands` | the prompts patterns, when the plugin's `prompts` (an entry's `commands`) is absent |

`files` never comes from a manifest. The manifest is read on every assembly, so its keywords
reach selectors, scopes and `/health`.

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
| a prompt | an earlier prompt of the plugin has its file stem |

**PLG-19.** A plugin **fails** when its fetch has no servable tree, its root is refused (PLG-8),
its manifest is refused (PLG-15), or reading its files errors. A failed plugin serves nothing in
any library and carries `status: failed` and an `error` in `/health`. No other plugin or library is
affected.

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
| the JSON is not an object with a `plugins` list | `<file> must be an object holding a plugins list` |

**LIB-13.** Each entry becomes a plugin with id `<entry name>@<library>`, and with the entry's
`name`, `description` (`""` unless a string), `category` (a string or none), `tags` and `keywords`
(lists; non-string items dropped, any other type read as empty) and `version`. Other entry fields
are ignored.

**LIB-14.** An entry's `skills` and `commands` are read as manifest component paths (PLG-16). Its
`commands` are its prompts patterns and count as a `commands` declaration (PLG-12). An entry that
lists neither leaves both to its manifest (PLG-17). An entry never sets `files`.

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
| `strict: false` | `strict: false entries are not supported` |
| `source` missing or not a string/object with a string `source` | `an entry needs a source` |
| a string source that is absolute, or climbs out | `… is not a relative path`, `… escapes the marketplace` |
| `github` without `repo`; no `https://github.com` git source | `a github entry needs a repo`; `no source for github.com is declared` |
| `url`/`git-subdir` without `url`; no source prefixes it | `a <kind> entry needs a url`; `no source for <host> is declared` |
| `git-subdir` with a blank `path` | `a git-subdir entry needs a path` |
| `sha` or `ref` that is not a string | `<field> must be text naming a commit or a ref` |
| `skills` or `commands` of the wrong type | `<field> must be a string or a list of strings` |
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

## Proposed: reading a plugin the way Claude Code does

These requirements replace PLG and LIB requirements that disagree with them once built. They make
one `plugin.json` mean the same in kb as in Claude Code, for the kinds kb serves.

**PLG-20.** *(proposed)* A manifest `skills` list **adds** to the default skill scan, across all of
kb's skill roots. `"."` and `"./"` name the plugin root.

**PLG-21.** *(proposed)* A manifest `commands` **replaces** the default prompt scan, across all of
kb's prompt conventions. It may be a path, a list of paths, or an **object map**. In a map, the key is
the prompt's name, `source` names a file or `content` holds an inline body (exactly one of the
two), and `description` and `argumentHint` fill the prompt's description and free-text argument.
`model` and `allowedTools` are dropped like the other client-only keys.

**PLG-22.** *(proposed)* A manifest `agents` list of `.md` files **replaces** the default `agents/`
scan (see [agents.md](agents.md)).

**PLG-23.** *(proposed)* When a replacing key is set and its default folder exists, the folder is
ignored, and `/health` notes `Default <folder>/ folder is ignored because the manifest sets "<key>"`.

**PLG-24.** *(proposed)* A component path that doesn't start with `./` is still served, and
`/health` notes it.

**LIB-30.** *(proposed)* A marketplace entry beside a `plugin.json` with `strict` absent or true
**appends** its `skills`, `commands` and `agents` to the manifest's.

**LIB-31.** *(proposed)* An entry with `strict: false` that names any of `skills`, `commands` or
`agents` beside a `plugin.json` is a conflict, and the plugin is skipped with the reason
`conflicting manifests`.

**LIB-32.** *(proposed)* An entry whose `source` is the marketplace root and that lists `skills`
loads **only** those directories, and the default skill scan is off for it.

**LIB-33.** *(proposed)* A config's own `skills:` and `prompts:` still override the manifest and the
entry completely.
