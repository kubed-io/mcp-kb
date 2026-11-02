# The spec audit — 2026-11-02

> **History.** Written when the living spec in [specs/](../specs/) was first drafted from the code
> (`main` at `45d76c7`). Each area was written by reading the code and the tests, then compared
> with the wiki, README, AGENTS.md and the design docs. These are what didn't match, and what looked
> like a bug on the way. None of it is fixed here. Each item is a lead to confirm, not a verdict:
> the suite couldn't run in the pod that wrote this (an installed `kubed` package shadows the
> namespace).

## Docs that say something the code doesn't do

### Wiki

- **Scoping.**
  - Refusal messages are quoted shorter than the code's. The code adds "(or the Kb-Category and
    Kb-Tag headers)".
  - "A bad category or tag always fails" leaves out two cases the code skips: a category listed by
    a library that is down, and a server that serves nothing.
  - With a library set, a category refusal says no library lists the category even when another
    library does. The tests expect this; the wording misleads.
  - Not said anywhere: a proxy that folds repeated `Kb-Tag` headers into one comma-separated value
    turns *any of* into *all of*.
- **Libraries.**
  - The no-marketplace error doesn't list the paths it looked at; the wiki says it does.
  - Entry `source` forms resolve only through declared **git** sources, and `{source: github}` only
    through one whose URL is exactly `git+https://github.com`.
  - Entries read `keywords`, and never set `files`. Neither is mentioned.
  - `pluginSelector: {}` selects every plugin. Not mentioned.
- **Plugins.**
  - "Four fields are read", followed by five.
  - Besides unreadable JSON, a non-object manifest and a wrongly typed `keywords`, `skills` or
    `commands` also fail the plugin.
- **Skills.**
  - "Name equals folder" has an exception: a skill that is the plugin root.
  - "Directories become real listings": the server answers `resources/directory/read` with -32601.
  - The Skills extension isn't documented: `skills/list`, `skills/get`, the rules a skill must meet
    to be listed, and that a skill missing them is still readable as a resource.
  - "One row per library": a library with only library files gets only `_files.md`.
- **Prompts.**
  - An explicit `dialect:` doesn't always win. `applyTo`/`globs` files are refused first.
  - The own dialect's `title` key isn't documented.
  - A prompt file must have frontmatter, or it is skipped. Not documented.
  - "What is dropped" lists eight keys. The rule is every key the dialect doesn't read.
  - Elicitation needs *form* elicitation, and the `get_prompt` mirror never asks.
  - `.claude/commands/` is not a default glob. It only decides the dialect when a `prompts:` glob
    reaches it.
- **Endpoints, generated from `spec/builder.py` and `scripts/generate_wiki.py`.**
  - `/reindex`'s `rebuilt` is not "every fetch": a fetch failing the same way is left out, and fetches
    a marketplace re-read added are in.
  - The route table says "sources" where the code means fetches.
  - `/health` ignores every scope and prefix setting, not just `Kb-Library`.
- **Hostname.** `spec/builder.py` hard-codes a cluster-internal server URL into the generated
  Endpoints page and `wiki/Tools.md`. Public-repo rule.
- **Deployment and Operations.**
  - An unwritable cache doesn't just make restarts slow. Remote fetches fail outright, and only
    `file://` plugins serve.
  - A refused credential exits with code 3 only at a cold start, for a fetch not reused from
    `index.json`.
  - A bare `file://` plugin (the recommended ConfigMap pattern) never refreshes on a schedule.
- **Config-File.** Mentions exit 2, not exit 3.
- **Sources.** "One recursive PROPFIND" vs `_etags`' "one PROPFIND per directory". Unverified which
  holds.

### In the repo

- `AGENTS.md` said the prompt mirror is subclassed "only to add read-only annotations". It also
  wraps errors and turns elicitation off. *Fixed with the spec.*
- `AGENTS.md` and `README.md` linked a `saga/` folder that had moved to `docs/saga/`. *Fixed with
  the spec.*
- `spec/builder.py` speaks of a "committed openapi.yaml". The file is gitignored.
- The `Catalogue.read` docstring in `uris.py` describes a library-wide fallback from inside a skill,
  which the code refuses.
- `mcp/announce.py` and `mcp/resources.py` reason about FastMCP 4.0.3. 4.1.4 is installed.
- Past-tense wording in current docs: `README.md` ("no longer holds"), the `pins.py` docstring
  ("used to be served").

## Looked like bugs

| Area | What | Where |
|---|---|---|
| Skills | Binary files are read as UTF-8 text, so a PNG or PDF comes back mangled, and its manifest hash won't match | `uris.py _skill_file`, `skills.py LibraryFiles._serve` |
| Skills | `_manifest` leaves symlinks out; `skills/get` lists them | `_manifest_files` vs `skill_entry` |
| Skills | A real file named `_manifest` at a skill's root can't be read | `uris.py` |
| Skills | `skills/list` has no memo and `ttlMs: 0`: every call hashes every file in scope | `mcp/skills.py` |
| Prompts | A Claude command that declares names and uses `$N` publishes a free-text argument whose value is dropped | `claude.py parse`/`substitute` |
| Prompts | A declared name `arguments` in last place is stripped as if it were the free text | `claude.py substitute` |
| Prompts | Live prompt bodies skip the undeclared-placeholder check, so `{{ typo }}` renders empty | `FilePrompt.body`, `mcpkb.substitute` |
| Prompts | `required: "false"` (quoted) counts as required | `bool(raw.get("required"))` |
| Prompts | Duplicate argument names aren't refused | prompt dialects |
| Scoping | A down library turns off typo checks for every requested category and tag | `pins.py` |
| Scoping | `stale` counts as down for checks, though a stale library still serves | `pins._up` vs `SERVABLE` |
| Plugins | Two marketplace entries with one name: the later replaces the earlier, silently | `server._assemble`, `snapshot.py` |
| Plugins | A marketplace's single-string `tags`/`keywords` read as empty; a manifest's are accepted | `marketplace._strings` vs `manifest._strings` |
| Plugins | An entry `source` written as a URL string is joined as a path and fails late | `marketplace.py` |
| Plugins | A whitespace-only declared description blocks the manifest's | `with_manifest` |
| Config | An empty config, or one with no libraries, is accepted and serves nothing | `load_config` |
| Config | A warm `index.json` hides refused credentials at boot; the exit-3 guard is bypassed | `_cold_start` |
| Config | Fetch errors in `/health` aren't scrubbed | `/health` |
| Config | `file:///` is refused with "has no path" | `plugins/address.py` |
| HTTP | A failing list-changed notification fails the client's request | `AnnounceChanges._announce` |
| HTTP | Unauthenticated `/reindex` forces a full rebuild each time, with no rate limit | `routes.py` |
