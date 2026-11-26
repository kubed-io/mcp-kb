# Prompts

A prompt is a Markdown file a plugin ships, which a person picks and fills in. kb reads three
dialects of prompt file and serves each as the same MCP prompt. This file covers how a file becomes
a prompt and how it renders, not which files a plugin offers or scope.

## Neighbours

**PRM-1.** Which files are a plugin's prompt files (its `prompts:` globs, its manifest's or
marketplace entry's `commands`, or the conventions) is decided as in
[plugins-and-libraries.md](plugins-and-libraries.md).

**PRM-2.** A prompt belongs to the library that serves its plugin and carries that plugin's
category and tags. kubed-mcp's plugin layer serves it: a client sees it when the layer's view
admits its plugin, and the view is kb's scope, decided as in
[scoping-and-instructions.md](scoping-and-instructions.md). A prompt out of scope is neither listed
by `prompts/list` nor found by `prompts/get`, and reads as absent: `Unknown prompt`, as a name
nobody serves does.

**PRM-4.** A skipped prompt file is reported under its plugin's `skipped` in `/health`, as a
plugin-relative path and a reason, as in [plugins-and-libraries.md](plugins-and-libraries.md). The
rows come from the plugin layer's read of the plugin, with kb's reasons: kb's command reader parses
each file, and a file it cannot parse is skipped with the reason this file gives. A file the
layer's read reaches and kb did not select is not a row.

## The file

**PRM-5.** A prompt file is a YAML frontmatter block followed by a body. A file with no frontmatter
block, or with an unterminated one, is skipped with the reason `no YAML frontmatter`. An empty
block (`---` then `---`) is valid.

**PRM-6.** The body is the text after the frontmatter block exactly as written.

**PRM-7.** A file that cannot be read, whose YAML does not parse, or whose frontmatter breaks a rule
below is skipped with a reason. A frontmatter key that is not a string (`1:`, `true:`) is skipped
with `frontmatter has a key that is not a string`.
Frontmatter nested too deeply for the parser is skipped with `frontmatter is nested too deeply to
read`. The plugin's other prompts, skills and files still serve.

**PRM-8.** A frontmatter field of the wrong type (a mapping or a list where text is expected, a
non-list where a list is expected) skips the file with a reason naming the field. It MUST NOT stop
the server.

**PRM-9.** In every dialect, the description is the frontmatter `description` with each run of
whitespace collapsed to one space. An empty description is no description.

**PRM-10.** Every argument is a string argument with a name, an optional description and a
`required` flag. The served prompt lists its arguments in the order the dialect yields them.

**PRM-11.** A rendered prompt is one message with the role `user` holding the rendered text.

**PRM-12.** Nothing in a body is ever executed. A `` !`…` `` line, a `!{…}` block and an `@path`
reference are text and render as written.

## Which dialect a file is

**PRM-13.** The dialects are `mcp-kb` (this server's own), `claude` (Claude Code commands) and
`copilot` (VS Code `.prompt.md` files). A plugin's `dialect:` setting is `auto` (the default),
`mcp-kb`, `claude` or `copilot`.

**PRM-14.** Each file is read in one dialect, decided by the first rule below that answers:

| # | Signal | Result |
|---|---|---|
| 1 | The frontmatter has `applyTo` or `globs` | Not a prompt: skipped with the reason ``not a prompt: has `applyTo` `` (or `globs`) |
| 2 | The plugin's `dialect:` is not `auto` | That dialect |
| 3 | The file name ends in `.prompt.md` | `copilot` |
| 4 | The file sits under `commands/` or `.claude/commands/` in the plugin root | `claude` |
| 5 | A manifest's or marketplace entry's `commands` pattern matched the file | `claude` |
| 6 | The frontmatter has `agent` or `tools` | `copilot` |
| 7 | The frontmatter has `argument-hint`, or `arguments` is a list of strings or a non-blank string | `claude` |
| 8 | The frontmatter `arguments` is a list of mappings | `mcp-kb` |
| 9 | The body has a `{{ name }}` placeholder | `mcp-kb` |
| 10 | The body has a `${input:…}` placeholder | `copilot` |
| 11 | The body has `$ARGUMENTS`, `$ARGUMENTS[N]` or `$N` | `claude` |
| 12 | Nothing above answered | `mcp-kb` |

**PRM-15.** Rule 1 holds whatever the plugin declares and wherever the file sits.

**PRM-16.** A config's own `prompts:` glob is not a `commands` declaration. A file it selects gets
no help from rule 5.

**PRM-17.** When rule 7 is reached, an `arguments` list that mixes strings and mappings skips the
file. An empty `arguments` list counts as absent.

**PRM-18.** The dialect is decided by PRM-14 each time the plugin is read. Nothing about a
prompt is kept on disk, so a boot decides it afresh. A build of that read reads the file in that
same dialect, so a body rewritten for a build never changes a file's dialect. A configured dialect
kb does not know skips the file with the reason `unknown dialect '<name>'`.

## The `mcp-kb` dialect

```markdown
---
title: Debug logs
description: Debug a workload's recent logs in Loki.
arguments:
- name: app
  description: The workload to look at.
  required: true
- name: since
  default: 1h
---
Investigate the logs of **{{ app }}** over the last {{ since }}.
```

**PRM-19.** The frontmatter keys read are `description`, `title` and `arguments`. Only this dialect
publishes a title.

**PRM-20.** `arguments` is a list of mappings, one per argument, in the order served:

| Key | Meaning |
|---|---|
| `name` | The argument's name. Required; an entry without one skips the file |
| `description` | Shown to whoever fills it in |
| `required` | `true` makes the argument required. Default `false` |
| `default` | The value used when the argument is not given |

**PRM-21.** An argument that is required and has a `default` skips the file.

**PRM-22.** A placeholder is `{{ name }}`, spaces inside the braces optional, where `name` matches
`[A-Za-z_][A-Za-z0-9_]*`. Single braces are text, so LogQL, PromQL and JSON render as written.

**PRM-23.** Every placeholder in the body MUST name a declared argument. A file with an undeclared
placeholder is skipped, and the reason names each one.

**PRM-24.** Each placeholder renders as the given value, else the argument's default, else the empty
string.

## The `claude` dialect

**PRM-25.** The frontmatter keys read are `description`, `arguments` and `argument-hint`.

**PRM-26.** `arguments` is a list of names or one whitespace-separated string of names. Each name
becomes an optional argument with no description, in the order declared.

**PRM-27.** The body's placeholders render as follows:

| Placeholder | Renders as |
|---|---|
| `$name`, a declared name | That argument's value, or empty |
| `$name`, not a declared name | Itself, as written |
| `$ARGUMENTS` | The free text (PRM-36) |
| `$ARGUMENTS[N]` and `$N` | The value of the declared name at 0-based index `N`; with no names declared, word `N` of the free text; empty when out of range |

**PRM-28.** `$N` is one digit. A digit followed by another digit, or by `.` and a digit, is text:
`$12` and `$5.00` render as written.

**PRM-29.** A file that declares the name `arguments` publishes it once, as declared, and gets no
free-text argument added.

## The `copilot` dialect

**PRM-30.** The frontmatter keys read are `description` and `argument-hint`.

**PRM-31.** The arguments are the distinct inputs the body names, in order of first appearance. An
input is `${input:name}` or `${input:name:text}`. `name` matches `[A-Za-z0-9_][A-Za-z0-9_-]*`, and
`text` runs to the next `}`, colons included.

**PRM-32.** An input's description is the `text` of its first spelling that has one. Every input is
optional.

**PRM-33.** Every spelling of an input renders as that argument's value, or empty.

## The free-text `arguments` argument

**PRM-34.** Under the conditions below, a `claude` or `copilot` prompt gets one more optional
argument, named `arguments`: the text a person types after the command. It is always the last one.

**PRM-35.** Its description is the file's `argument-hint`, else `Everything typed after the
command.` An `argument-hint` written as a YAML list is joined into one line with spaces. An empty
hint gives the default description.

**PRM-36.** A `claude` file gets it when it declares no names, or when its body uses `$ARGUMENTS`,
`$ARGUMENTS[N]` or `$N`.

**PRM-37.** A `copilot` file gets it only when its body has no `${input:…}` and its frontmatter has
an `argument-hint`.

**PRM-38.** When a body places no free text, a non-empty free text is appended after a blank line:

| Dialect | Appended | When |
|---|---|---|
| `claude` | `ARGUMENTS: <text>` | No names declared and no `$ARGUMENTS`, `$ARGUMENTS[N]` or `$N` in the body |
| `copilot` | `<text>`, unlabelled | No `${input:…}` in the body |

**PRM-39.** The `mcp-kb` dialect never adds a free-text argument.

## Dropped keys

**PRM-40.** Every frontmatter key a dialect does not read (PRM-19, PRM-25, PRM-30), such as
`model`, `tools` or `allowed-tools`, is dropped. kb names a file's dropped keys once, at `DEBUG`.

## Naming

**PRM-41.** A prompt's name is `<library>_<name>`, where the name is as PLG-25 says
([plugins-and-libraries.md](plugins-and-libraries.md)). The prefix is the first segment of the
plugin's namespace (kubed-mcp's PLUG-63), which every plugin of the library shares (PLUG-17), and
the name below it is the plugin layer's (PLUG-62), which is PLG-25's. A file the layer names
otherwise than PLG-25 is skipped. A library name has no `_`, so the name splits back
unambiguously.

**PRM-42.** The stem of `x.prompt.md` is `x`. The stem of any other file is its name without its
last extension. `prompts/debug.md` in a plugin the `grafana` library serves is `grafana_debug`.
The stem is held to the usable-name rule PLG-25 gives: `prompts/a b.md` in library `lib` is skipped
with `prompt name 'lib_a b' is not a usable name`, the reason quoting the full name.

**PRM-43.** The plugin is not part of the name. Two prompts in one plugin with the same name
(`prompts/debug.md`, `prompts/sub/debug.md`, `debug.prompt.md`) serve the first, in the order
PLG-25 gives. Each later one is skipped with the reason `prompt <name> is already served by
<path>`, quoting the full name: `prompt lib_debug is already served by prompts/debug.md`.

**PRM-44.** Two plugins of one library that yield the same prompt name are a conflict between
plugins: the plugin layer refuses the later plugin (PLUG-18), reported as LIB-29 says in
[plugins-and-libraries.md](plugins-and-libraries.md).

## As a resource

**PRM-63.** A served prompt's file also reads, unlisted, at `prompts://<namespace>/<place>`. The
namespace is its plugin's (SKL-59). The place is its path below the commands folder it was read
from: `commands/db/migrate.md` reads at `prompts://lib/db/migrate.md`. For a file a manifest lists
by path, the place is that path: `./prompts/x.md` of plugin `b` reads at
`prompts://lib/b/prompts/x.md`. It reads as the plugin layer builds it, frontmatter kept, after
kb's rewriter and the prefix. Every folder holding one is a directory with `_index.md` and
`_index.json`; `prompts://<library>` is one only when the main plugin serves a prompt (kubed-mcp's
PLUG-66 to PLUG-68). It is held to the scope as `prompts/get` is, and out of scope it fails as an
absent address does. It is listed only when `Listed` names `prompts` (DLV-8). Two files of one
plugin at one place serve the first in kb's path order (`harvest.command_entries`), and the later
one is skipped whole, its prompt included, with its reason in `/health`'s `skipped`:
`prompts://lib/prompts/x.md is already served by commands/prompts/x.md`. This is kubed-mcp's limit,
reported to quick-mcp. The instructions point at the index (INS-19).

## Rendering

**PRM-45.** An argument whose value is missing, `null` or the empty string counts as not given. A
default applies to it, and a required argument is missing.

**PRM-46.** Every argument value is rendered as its string form.

**PRM-47.** The qualified skill names in the body (PRM-62), then `${CLAUDE_PLUGIN_ROOT}` (PRM-48,
PRM-61), are resolved when the plugin layer's build is made, against the request's scope. The
dialect's placeholders are filled in at render. The gateway prefix on every `skill://` address in
the text is the plugin layer's, written last (GW-7), as in [skills.md](skills.md). kb never
rewrites an argument's value: `${CLAUDE_PLUGIN_ROOT}` given as an argument renders as typed. The
gateway prefix, written over the whole rendered text, is the one change that reaches it.

## Placeholders resolved and left alone

**PRM-48.** In every dialect, `${CLAUDE_PLUGIN_ROOT}` renders as `skill://<library>`, the library
serving the prompt, except as PRM-61 says. `${CLAUDE_PLUGIN_ROOT}/shared/tokens.md` renders as
`skill://<library>/shared/tokens.md`.

**PRM-61.** In every dialect, `${CLAUDE_PLUGIN_ROOT}/<path>` inside a served skill of the prompt's
own plugin, in the library serving the prompt, renders as that skill's address, by the rule in
SKL-52 of [skills.md](skills.md): `${CLAUDE_PLUGIN_ROOT}/skills/drawio/SKILL.md` renders as
`skill://drawio/drawio/SKILL.md`. The gateway prefix then applies as PRM-47 says.

**PRM-62.** In every dialect, a qualified skill name (SKL-54) in a prompt's body
renders as [skills.md](skills.md)'s SKL-55 says. The prompt's plugin is the own plugin, and the
library is the one serving the prompt. Only a skill that is served for the request's scope and
prefix is a candidate (SKL-45). The rewrite runs on the body as written, before the
dialect's placeholders, so an argument's value is never rewritten. It is the first step of PRM-47's
order.

**PRM-49.** `${CLAUDE_SKILL_DIR}` renders as written in a prompt: a prompt has no skill directory.

**PRM-50.** Every placeholder that names something only the client has renders exactly as written,
in every dialect, and no argument is published for it. This includes `${selection}`, `${file}`,
`${workspaceFolder}`, `#file:`, `#tool:`, `@path` references, `${CLAUDE_PROJECT_DIR}` and
`${CLAUDE_SESSION_ID}`.

**PRM-51.** A placeholder of one dialect is text in another. A `$ARGUMENTS` in an `mcp-kb` body or a
`$env` in a `copilot` body renders as written.

## Missing required arguments

**PRM-52.** `prompts/get` without a required argument fails with invalid params (`-32602`) and the
message `Prompt '<name>' needs the argument <a>.`, or `needs the arguments <a>, <b>.` for several.
kb logs it at `DEBUG` only.

**PRM-53.** On a connection at MCP `2026-07-28` whose client declared form elicitation,
`prompts/get` instead returns an input-required result. It carries one form elicitation, keyed
`arguments`:

```json
{"message": "The kit_debug prompt needs app.",
 "requestedSchema": {"type": "object", "required": ["app"],
   "properties": {"app": {"type": "string", "description": "The workload."}}}}
```

**PRM-54.** The form asks for every missing required argument at once. Each property's description
is the argument's description, or empty.

**PRM-55.** On the round that answers, an `accept` with content is merged over the arguments that
round sent, and the prompt renders. A required argument still missing after the merge fails as in
PRM-52.

**PRM-56.** A `decline`, a `cancel`, or an `accept` with no content fails as in PRM-52, whatever
content came with it.

**PRM-57.** An older protocol and a client that declared no form elicitation are never asked. They
get the failure in PRM-52.

## Live prompts

**PRM-58.** A prompt file of a `cache: live` source (see
[config-and-sources.md](config-and-sources.md)) is revalidated with its plugin's skill and agent
files, on each request whose scope admits the plugin (SKL-37). One that moved re-reads its plugin,
and the prompt as edited serves from the next request.

**PRM-59.** The edit's arguments, defaults and dialect are read from the edited file and served
with it; no refresh is needed.

**PRM-60.** When an edited prompt file the plugin served no longer reads as a prompt (for
example unreadable, not a prompt, no frontmatter block, YAML that does not parse or is nested too
deeply, a placeholder that is not a declared argument, or a required argument with a default), the
re-read is refused: the plugin keeps its last good build, its skills and agents included, and kb
logs one warning. It tries again when a file of the plugin moves.

**PRM-64.** Under Via `extension` or `local`, `prompts/list` lists no plugin prompt, and
`prompts/get` still serves one (DLV-9). kb adds no filter of its own.
