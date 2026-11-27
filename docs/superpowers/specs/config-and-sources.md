# Config and sources

The config file and the backends it names: how the file is read and validated, how a credential
is referenced, how a source turns an address into a directory on this machine, and how that
directory is kept current. What a plugin or a library selects out of a source is
[plugins-and-libraries.md](plugins-and-libraries.md); the wire shape of `/health` and `/reindex`
is [http-and-tools.md](http-and-tools.md).

## Running it

**CFG-1.** Every config item is set by, from lowest to highest: its default, the config file,
its environment variable, its flag. A mapping merges key by key; a list or a value replaces what is
below it whole. A blank value is unset.

| Item | Env | Flag | Default |
|---|---|---|---|
| the file | `CONFIG_FILE` | `--config-file` | none (the image: `/etc/mcp-kb/config.yaml`) |
| `sources` | `KB_SOURCES` | `--sources` | `[]` |
| `plugins` | `KB_PLUGINS` | `--plugins` | `[]` |
| `libraries` | `KB_LIBRARIES` | `--libraries` | `[]` |
| `cache_dir` | `CACHE_DIR` | `--cache-dir` | `/var/cache/mcp-kb` |
| `serving.transport` | `TRANSPORT` | `--transport` | `http` (`stdio` or `http`) |
| `serving.host` | `HOST` | `--host` | `0.0.0.0` |
| `serving.port` | `PORT` | `--port` | `8000` |
| `serving.log_level` | `LOG_LEVEL` | `--log-level` | `INFO` |
| `telemetry.profiles` | `TELEMETRY_PROFILES` | `--telemetry-profiles` | none |
| `telemetry.profile_cpu` | `TELEMETRY_PROFILE_CPU` | `--telemetry-profile-cpu` | `true` |
| `telemetry.profile_memory` | `TELEMETRY_PROFILE_MEMORY` | `--telemetry-profile-memory` | `true` |
| `telemetry.otel` | `TELEMETRY_OTEL` | `--telemetry-otel` | `false` |
| `telemetry.tags` | `TELEMETRY_TAGS` | `--telemetry-tags` | `{}` |
| `delivery.resources` | `DELIVERY_RESOURCES` | `--delivery-resources` | none |
| `delivery.listed` | `DELIVERY_LISTED` | `--delivery-listed` | none |
| `delivery.via` | `DELIVERY_VIA` | `--delivery-via` | none |

**CFG-2.** There is one config. What to serve, how to run, what the process reports and the
delivery defaults are all items of it, and each one can be set in the file, an env var or a flag.
The `OTEL_*`, `POD_NAME` and `POD_NAMESPACE` variables are read by kubed-mcp's telemetry and the
OpenTelemetry SDK, never by kb, and are no kb setting. What the `serving` items do is in
[http-and-tools.md](http-and-tools.md).

**CFG-3.** `mcp-kb schema` prints the config's JSON Schema and exits 0 without reading a config.
It is the whole config's schema, each item with its `env` and `arg`. `config.schema.json` in the
repository is the same document.

**CFG-16.** The file is named by `--config-file`, else `CONFIG_FILE`, and with neither no file is
read. A named file that does not exist, is not a file, is not YAML or is not a mapping exits 2
naming its path (CFG-7).

**CFG-17.** `KB_SOURCES`, `KB_PLUGINS` and `KB_LIBRARIES`, and their flags, take a JSON array.
`TELEMETRY_TAGS` and `--telemetry-tags` take a JSON object.

**CFG-18.** When serving starts, the server logs one line on `kubed.mcp.config` naming each item
not at its default, its value and where it came from: `config: <item>=<value> (<source>), …`, the
source `file <path>`, `env <NAME>` or `arg <flag>`, or `config: all defaults`. A secret prints as
`***`. A credential is an `{env: NAME}` reference (CFG-9), so the line names its variable, never
its value.

**CFG-20.** `mcp-kb serve` with `CONFIG` set exits 2 with `mcp-kb: CONFIG is no longer read: name
the config file with CONFIG_FILE`. `--config` is an unknown flag (CFG-7).

## The config file

**CFG-4.** The file is YAML with three optional top-level lists `sources`, `plugins` and
`libraries`, a `cache_dir`, and the mappings `serving`, `telemetry` (CFG-15) and `delivery`
(CFG-19). An empty file, or none, is a valid config with all three lists empty, kb's run defaults,
and every telemetry signal off.

```yaml
sources:
- name: github
  url: git+https://github.com
plugins:
- name: runbooks
  source: github://example/handbook//runbooks?ref=main
libraries:
- name: ops
  plugins: [runbooks]
```

**CFG-5.** A key the schema does not define, at any level, is a config error, never ignored.

**CFG-6.** Every source, plugin and library `name` matches `^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$`
and is unique within its own list.

**CFG-7.** The whole config is validated before anything is fetched. A file that cannot be read,
is not YAML or fails validation exits with code 2 and `mcp-kb: the config did not load:` on
stderr, then one line per error, `<path> (<source>): <reason>`. A bad env var or flag, an unknown
flag, and a positional argument other than `serve` or `schema` are config errors too.

**CFG-8.** No config error quotes a value it was given. One of kb's own messages that names an
address has its `user:password@` masked as `***@`.

**CFG-14.** A plugin's `skills` item is a folder, never a glob. Loading the config refuses an item
holding `*`, `?` or `[` with `skills item '<item>' is a folder, not a glob` (PLG-9).

## Credentials

**CFG-9.** A source's `auth` is `{username, password}`. `password` MUST be an `{env: NAME}`
reference; `username` is a literal or an `{env: NAME}` reference.

```yaml
auth:
  username: x-access-token
  password: {env: GITHUB_TOKEN}
```

**CFG-10.** A reference is resolved from the process environment when a backend connects, never at
load time.

**CFG-11.** An unset variable fails only the fetch that needs it
(`environment variable NAME is not set`); the server keeps running.

**CFG-12.** Logs of a failed refresh or reindex mask every resolved credential and URL userinfo.

**CFG-13.** No credential is written under the cache directory, a clone's remote URL included.

## Telemetry

**CFG-15.** The optional `telemetry` mapping is kubed-mcp's built-in `telemetry` section, its items
set by their `TELEMETRY_*` variables and `--telemetry-*` flags (CFG-1), which the server kubed-mcp
builds reads off the config: `profiles` (a Pyroscope address; setting it turns profiles on),
`profile_cpu` and `profile_memory` (both `true` by default), `otel` (`false` by default;
OpenTelemetry traces and call metrics, configured by the standard `OTEL_*` variables) and `tags` (a
string map of labels). Absent, every signal is off. An unknown key in it is a config error (CFG-5).
kb adds only the `profiles` guard: an address carrying userinfo is a config error, as a source URL
is (SRC-3), and the error does not quote it. Profiles, traces and
metrics carry the service name `OTEL_SERVICE_NAME`, else `mcp-kb`. Metrics leave as
`OTEL_METRICS_EXPORTER` says: pushed over OTLP, or scraped from the exporter's own port with
`prometheus`. The server adds no metrics route.

```yaml
telemetry:
  profiles: http://pyroscope.example.com:4040
  otel: true
  tags: {team: platform}
```

**CFG-21.** A `resources/read` that kb itself answers is labelled in the call metrics by its
kind's pattern, never by its address: `skill://{library}/_index.md`,
`skill://{library}/{folder}/_index.md`, `skill://{library}/_index.json`,
`skill://{library}/{folder}/_index.json`, `skill://{library}/_files.md`, and
`skill://{library}/{+path}`. `{folder}` is the address's second segment, and
`skill://{library}/{+path}` is any other address kb answers: a library file, a plugin-root
fallback (SKL-30, SKL-31), or a deeper folder's `_index.json`. The pattern is read from the
address with its dot segments resolved. A read through the `read_resource` tool is labelled the
same. A read kb misses carries no label, as before, and an out-of-scope read is labelled as an
absent one is. These patterns are labels only: `resources/templates/list` still lists the one row
`skill://{library}/{+path}`, and a miss is never read through a template. A skill's own files are
labelled by kubed-mcp.

## Delivery

**CFG-19.** The optional `delivery` mapping is kubed-mcp's defaults for the delivery inputs:
`resources`, `listed` and `via`, each set by its `DELIVERY_*` variable and `--delivery-*` flag
(CFG-1), and none of them set by default. A request's own header or query parameter wins over it.

```yaml
delivery:
  via: extension
```

## Sources

**SRC-1.** A source is `name`, `url`, and optionally `auth`, `cache` (`snapshot`, the default, or
`live`) and `refresh` (matching `^[1-9]\d*[smh]$`, as in `30s`, `5m`, `1h`).

**SRC-2.** The `url` scheme alone picks the backend:

| `url` scheme | Backend |
|---|---|
| `git+https://`, `git+http://`, `git+file://` | git |
| `webdav+https://`, `webdav+http://` | webdav |
| `file://` | file |

**SRC-3.** Each of these sources is a config error:

| Source | Why |
|---|---|
| any other `url` scheme | the error lists the schemes above |
| a `url` carrying userinfo, `https://user:token@host` | a credential belongs in `auth` |
| a `file://` url with a host part, `file://relative/path` | it MUST be absolute, `file:///path` |
| named `file` | `file://` is built in and could never address it |
| webdav with no `auth` | |
| `cache: live` on git or file | |

## Addresses and fetches

**SRC-4.** A plugin's or a marketplace library's `source` is an address; its grammar is in
[plugins-and-libraries.md](plugins-and-libraries.md).

**SRC-5.** An address scheme is a declared source's name or `file`, which needs no source entry.
Any other is a config error that lists the declared sources.

**SRC-6.** `?ref=` is accepted only when the address's source is git.

**SRC-7.** The backend URL is the source `url` less its `git+` or `webdav+` prefix, then `/`, then
the address path: `github://example/repo` under `git+https://github.com` reads
`https://github.com/example/repo`. A source with `url: file:///srv/kb` makes `local://team` read
`/srv/kb/team`.

**SRC-8.** A fetch is one materialised tree, keyed `<scheme>://<path>[?ref=<ref>]`: the address
without its subdir. Everything whose address has one key shares one fetch, one clone, one export
and one `/health` entry.

**SRC-9.** A fetch takes `auth`, `cache` and `refresh` from its source. A built-in `file://`
address has no auth, `cache: snapshot` and no `refresh`.

**SRC-10.** A failure to materialise or fingerprint a fetch is recorded on that fetch alone, and
its error names the fetch key, never a cache path.

**SRC-53.** Each declared source, and `file`, has one fetcher: a loader whose scheme is the
source's name, made with the source (its URL and `auth`) and the cache directory, which kb
materialises and fingerprints its fetches through. kubed-mcp is never handed one. It reads every
plugin through one loader of kb's, the **served-tree loader**, registered for `file` and for every
declared source's name, in place of kubed-mcp's own `LocalLoader`. The served-tree loader is never
a fetcher: it clones, exports and copies nothing. `materialise(address)` is the tree kb serves for
the address's fetch now, the last good one included, with the subdir inside it
([SRC-8](#addresses-and-fetches)). A fetch kb serves no tree for fails with
`<key> is not materialised`, and a subdir that is not a directory in the tree fails with
`<subdir> is not a directory in <key>`. kubed-mcp is handed kb's own address, never a cache path.

## git

**SRC-11.** A git fetch is cloned bare, with no working copy, into `<cache>/git/<slug>`. A remote
clone has depth 1; a `git+file://` clone is full, because libgit2's local transport refuses a
shallow fetch.

**SRC-12.** A clone that cannot be opened, or whose `origin` is not the fetch's URL, is deleted and
cloned again.

**SRC-13.** The ref resolves to one commit:

| `?ref=` | Resolves to | Fails with |
|---|---|---|
| absent | the remote's default branch | |
| 40 hex characters | that commit, fetched by sha if not in the clone | `commit <sha> is not in <url>` |
| anything else | a branch of that name, else a tag | `ref '<ref>' not found` |

**SRC-14.** The commit's tree is exported to `<cache>/src/<slug>/<commit>`. A symlink in it is
exported as a regular file whose text is the link target.

**SRC-15.** A git error reporting an authentication replay or an authentication requirement is an
access refusal ([SRC-41](#startup)).

## webdav

**SRC-16.** A webdav fetch's URL is the folder. Its whole content is copied to
`<cache>/src/<slug>/<version>`, the version being the SHA-256 of its sorted `path → ETag` map. A
file with no ETag stands in `<modified>:<size>`.

**SRC-17.** A folder whose ETag map has not moved resolves to the export on disk and is not
downloaded.

**SRC-18.** A failure reports the status and folder path, never the host, URL or credentials:

| Cause | Error | Access refusal |
|---|---|---|
| no such folder | `the folder <path> does not exist` | no |
| HTTP 401 | `HTTP 401: the credentials were refused` | yes |
| HTTP 403 | `HTTP 403: the account may not read this folder` | yes |
| other HTTP | `HTTP <status>` | no |

**SRC-19.** A file name holding `#`, `?` or anything else that needs encoding is copied and
revalidated like any other.

## file

**SRC-20.** A file fetch is served in place; nothing is copied. A path that is not a directory
fails the fetch with `<path> is not a directory`. A skill's files are read once per generation,
so an edit to one in place is served from the next refresh (or `POST /reindex`); a prompt file is
read when its plugin is added to the plugin layer, once per generation, like a skill's files; a
library file is read off disk each time.

## `cache: live`

**SRC-21.** On a live fetch, each read of one of its library files, and each request that reads
skills, agents or prompts under a scope admitting one of its plugins, starts the fetch's
revalidation in the background if one is due (SKL-37). It is served from the local copy as it
is. A revalidation lists the fetch's folder once, one PROPFIND per directory, and downloads each
file the local copy holds whose ETag differs from the local copy's. An edit is served from the
first request after the revalidation that found it.

**SRC-22.** A download is staged in `<cache>/src/<slug>/.work/` and renamed over the local copy in
one step, so a reader sees one whole version of the file.

| Bound | Value |
|---|---|
| a fetch revalidated this recently is not revalidated again | 2 s |
| one revalidation request times out after | 1 s |
| after a failure, the fetch is not revalidated for | 30 s |
| revalidations running at once for the generation served | 1 |

**SRC-23.** A failed revalidation logs one warning, `<fetch>: revalidating the listing failed:
<reason>` or `<fetch>: revalidating <path> failed: <reason>`, with no URL or credential. The local
copy goes on serving, and no read fails or waits for it. While the fetch is cooling, `/health`
shows `cooling: true`.

**SRC-24.** A file deleted upstream is served from the local copy until the fetch is rebuilt. A
file added or renamed upstream, and an edited description in a listing, wait for a rebuild.

**SRC-25.** A live fetch's `/health` entry carries `live: true` and two counts: `revalidated`,
the files a revalidation compared against the server's listing, and `fetched`, the ones
downloaded again.

**SRC-54.** A live fetch's revalidation belongs to the generation it serves. Once a refresh swaps
in a new generation, the previous one's revalidation starts nothing, and one it is running stops
before its next file and logs nothing more.

## The cache directory

**SRC-26.** A slug is the fetch key lower-cased, each run of other characters made `-`, cut to 60
characters, then `-` and 8 hex characters of the key's SHA-256.

**SRC-27.** An export is built under a `.tmp-` sibling and published by a rename onto a free name.
A tree being served is never written over or deleted in place.

**SRC-28.** An export's hidden stamp file holds its version and file count and is written last. An
export is complete only while its stamp matches its contents. An incomplete one is rebuilt beside
it, at `<version>.1`, then `.2`, and so on.

**SRC-29.** Each time an export is ensured, the newest other export of that fetch is kept and the
rest are deleted once their mtime is 15 minutes old. Leftover `.tmp-` and `.discard-` directories
go too, and `.work/` files 15 minutes old.

**SRC-30.** `<cache>/index.json` holds the fetch records of the served snapshot: each fetch's
key, status, root, fingerprint, `built` and error. It holds no plugin: a plugin is harvested from
its tree on disk (SRC-37). It is written atomically at boot and after every rebuild. When it
cannot be written, the server logs a warning and serves on.

## Fingerprints

**SRC-31.** A fetch is fingerprinted when it is built, before any plugin is harvested from it. It
has moved when a later fingerprint differs, or cannot be taken.

| Backend | Keys | Network per check |
|---|---|---|
| git | `commit`, `files`, `ref`, `remote` (the ref's commit upstream) | one ref listing; none for a 40-hex ref |
| webdav | `exported`, `files`, `remote` (upstream ETag digest), `remote_files` | one folder listing |
| file | `files`, `bytes`, `newest` (newest mtime in ns) | none |

**SRC-32.** `files` counts the export on disk, so an export that lost files has moved.

**SRC-33.** A file fingerprint skips hidden directories except `.github`, `.claude`, `.agents` and
`.claude-plugin`.

**SRC-34.** A file fingerprint follows a symlink, to a file or a directory, only when it resolves
inside the fetch root, and walks each resolved directory once. A ConfigMap mount, all symlinks,
fingerprints like a plain tree.

## Startup

**SRC-35.** The catalogue is built before the server binds its port.

**SRC-36.** Boot reuses `index.json` only when the server reads its format version and its config
hash equals that of the parsed config, so formatting and comments do not count. The hash covers
`sources`, `plugins` and `libraries` alone, so editing `serving`, `cache_dir`, `telemetry` or
`delivery` costs no refetch. The server writes version 12. It also
reads version 11, for its `fetches` alone, ignoring its `plugins`, until every deployment has
written 12.

**SRC-37.** From a reused index, boot keeps each `ok` or `stale` fetch record whose tree is on
disk, and builds the rest. Every plugin is harvested again from its fetch's tree, which touches no
network.

**SRC-38.** Boot takes no fingerprints. The first background pass, started with the server,
fingerprints every fetch.

**SRC-39.** A fetch that fails at boot is recorded `failed` and everything else is served, except
as SRC-41 says.

**SRC-40.** Deleting the cache costs one full fetch of everything at the next boot, and nothing
else.

**SRC-41.** A fetch built at boot whose server refuses its credentials exits the process with code
3 and the error on stderr. A fetch kept from the index is not built and cannot.

| Exit code | Cause |
|---|---|
| 0 | `mcp-kb schema`, or a normal stop |
| 2 | the config is unreadable, not YAML or invalid; or a bad command-line argument, or `CONFIG` is set |
| 3 | a fetch built at boot had its credentials refused |

## Refresh

**SRC-42.** After the first pass the server wakes every 5 seconds, or every shortest `refresh` if
that is shorter. A config with no `refresh` anywhere stops after the first pass.

**SRC-43.** A fetch is due once its `refresh` has elapsed since its last examination, rebuilt or
not. A fetch with no `refresh` is never due.

**SRC-44.** Examining a fetch rebuilds it when its record is not `ok`, its tree is gone, or its
fingerprint moved.

**SRC-45.** A rebuild that fails while the fetch's last tree is on disk makes it `stale`: that tree
is served, `built` and `fingerprint` still describe it, and `error` says why. A credential refusal
outside boot is handled the same way. With no tree on disk, the fetch is `failed`.

**SRC-46.** A stale fetch is `ok` again at its first successful rebuild.

**SRC-47.** A rebuild that ends in the status and error the record already holds is not a change,
and a pass with no change leaves the generation where it is.

**SRC-48.** On a change, every plugin is harvested again from its tree on disk, every marketplace
is re-read from disk, any fetch a marketplace starts needing is built, and a snapshot with the
next generation replaces the served one in one assignment. So a marketplace entry on another
repository serves its edited `skills`, `commands`, `agents` or `git-subdir` `path` though its own
fetch did not move. A request in flight finishes on the snapshot it started with.

**SRC-49.** Refreshes are serialised. A background pass that raises is logged and the loop goes on.

**SRC-50.** A fetch's change of state is logged once: `failed` as an error, `stale` as a warning,
back to `ok` as info.

**SRC-51.** `POST /reindex` examines every fetch with the fingerprint check skipped, so each is
rebuilt.

**SRC-52.** The shortest `refresh` in the config is the cache lifetime a client is given for a
listing; see [http-and-tools.md](http-and-tools.md).
