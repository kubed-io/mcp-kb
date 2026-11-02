---
description: 'GitHub Actions workflow conventions for this repo'
applyTo: '.github/workflows/*.yml,.github/workflows/*.yaml,.github/actions/*/*.yml'
---
# GitHub Actions workflow conventions

Applies to CI workflows and composite actions. YAML formatting rules come from
[yaml.instructions.md](./yaml.instructions.md); this file is the Actions-specific
review rules. These are hard conventions in this repo — flag violations.

## Naming
- Every **job** has a `name` that summarises what it does.
- Every **step** has a `name`. Add an `id` only when a later step references its
  outputs (keep ids short, lowercase, hyphenated).

## No `${{ }}` inside `run:` scripts — bind to `env:` instead
GitHub interpolates `${{ }}` into the script *before* the shell runs — that mixes
templating with logic, is a shell-injection risk, and makes the step impossible to
run or debug outside Actions. Bind the expression to an `env:` entry on the step and
read the clean `$VAR` in bash. The step then works locally with the same env set.

```yaml
# Bad — expression woven into the script
- name: Tag image
  run: docker tag app:latest app:${{ github.sha }}

# Good — expression on env:, plain $VAR in the script (portable + injection-safe)
- name: Tag image
  env:
    SHA: ${{ github.sha }}
  run: docker tag app:latest "app:$SHA"
```
Prefer `env:` for static/derivable values too. This is the single most important
rule here.

## Keep `run:` blocks pure — comment *above* the step, not inside it
Put explanatory `#` comments as YAML comments above the step so the `run:` body
stays a clean, readable script. Don't narrate inside the script.

```yaml
# Wait for the DB to accept connections before migrating — the container reports
# ready before the socket is actually up.
- name: Wait for database
  run: |
    until pg_isready -h localhost; do sleep 1; done
```

## One function per step — don't build a mega-script
If a step does several logical things (build → sign → upload), split it into
separate `run:` steps, each doing one functional part with a clear tool and clear
inputs/outputs. Small steps are easier to read, cache, retry, and debug; a failure
points at the exact function. Pass data between them via step outputs (below).

## `GITHUB_ENV` only for flow-wide values; otherwise use step outputs
- Write to `GITHUB_ENV` **only** when a value is genuinely useful to the whole job
  (many later steps need it) — everything after it can see it, so it pollutes the
  env if overused.
- When data belongs to one producer→consumer hop, isolate it with a **step output**
  (`echo "key=value" >> "$GITHUB_OUTPUT"`, read as `${{ steps.<id>.outputs.key }}`)
  or a **job output**. Keep the shared env small and intentional.

## Don't guess action or tool versions — verify
LLMs (and humans) routinely pin stale majors. Before adding or bumping any
`uses:` pin, confirm the current version with the CLI, e.g.
`gh api repos/<owner>/<repo>/releases/latest --jq .tag_name`. Never assume `@vN`.

## Other conventions
- **Provision first, act second.** Group install/setup steps up front, then a
  readiness gate, then the actual work — don't stagger "install A → use A → install
  B → use B".
- **Invoke scripts as `bash path/to/x.sh`**, not via the executable bit.
- **Multiline output**: use a `cat` heredoc, not many `echo`s:
  ```yaml
  - name: Print summary
    run: |
      cat <<'EOF'
      line one
      line two
      EOF
  ```
- **Secrets**: never `echo` a secret; if a value is derived from one, `::add-mask::`
  it. Don't put secrets in step names or outputs.

## Bash by default — reach for `actions/github-script` when bash is the wrong tool
Bash is the default and most steps should stay bash: it's readable, portable, and
runs the same locally. But there are jobs where bash actively gets in the way, and
forcing them into `curl | sed` is where pipelines get finicky and flaky. In those
cases use [`actions/github-script`](https://github.com/actions/github-script) —
it runs JS in the runner with an authenticated Octokit (`github`), `context`,
`core`, and `exec` already wired up.

**Use it when:**
- **The call is more than a fetch.** Anything needing real JSON handling, paging,
  retries with backoff, or reading one response to build the next. `json_field() {
  sed -n "s/.*\"$1\":\"\([^\"]*\)\".*/\1/p"; }` works right up until a value
  contains a quote, is nested, or is a number — and then it silently returns empty.
- **Concurrency helps.** Polling several endpoints, fanning out N requests, or
  racing a timeout against a readiness check. `Promise.all` / `Promise.race` beat
  backgrounded subshells and `wait`.
- **You're talking to the GitHub API.** `github.rest.*` is authenticated, typed,
  and paginated (`github.paginate`) — no `curl -H "Authorization: …"`, no
  hand-rolled `Link` header parsing.
- **The logic has real branching.** Once a step grows conditionals over parsed
  data, JS is easier to read and to reason about than nested `if`/`case` on
  string comparisons.

**Keep bash when:** running a build/test tool, a few sequential commands, simple
file wrangling, or anything a developer would want to paste into their own shell.
Don't rewrite working bash for its own sake.

**Rules when you do use it:**
- The `${{ }}` rule above still applies — **never interpolate into `script:`**.
  Pass values through `env:` and read `process.env.VAR`. The injection risk is
  worse here, not better: `${{ }}` lands inside a JS program.
- Return values with `core.setOutput()`; fail with `core.setFailed()` so the step
  actually goes red. A thrown promise rejection that isn't awaited will not.
- Log with `core.info()` / `core.warning()`, and `core.setSecret()` anything
  derived from a secret — the `::add-mask::` equivalent.
- Keep it to one function per step, same as bash. If it needs its own file, it
  wants to be a real script (or a composite action), not a giant inline `script:`.

```yaml
# Bad — bash doing JSON surgery with sed, and interpolating into the script
- name: Wait for service
  run: |
    for i in $(seq 1 60); do
      t=$(curl -s ${{ env.URL }}/api/status | sed -n 's/.*"ready":\([^,]*\).*/\1/p')
      if [ "$t" = "true" ]; then exit 0; fi
      sleep 1
    done
    exit 1

# Good — real JSON, a real timeout, values via env:
- name: Wait for service
  uses: actions/github-script@v9
  env:
    URL: ${{ env.URL }}
  with:
    script: |
      const deadline = Date.now() + 60_000;
      while (Date.now() < deadline) {
        try {
          const res = await fetch(`${process.env.URL}/api/status`);
          if (res.ok && (await res.json()).ready) {
            core.info('service is ready');
            return;
          }
        } catch { /* not up yet — keep polling */ }
        await new Promise(r => setTimeout(r, 1000));
      }
      core.setFailed('service did not become ready in 60s');
```
