# Config and sources

The config file and the backends it names: how the file is read and validated, how a credential
is referenced, how a source turns an address into a directory on this machine, and how that
directory is kept current. What a plugin or a library selects out of a source is
[plugins-and-libraries.md](plugins-and-libraries.md); the wire shape of `/health` and `/reindex`
is [http-and-tools.md](http-and-tools.md).

## Running it

**CFG-1.** A flag wins over its variable, which wins over the default.

| Flag | Env | Default |
|---|---|---|
| `--config` | `CONFIG` | `/etc/mcp-kb/config.yaml` |
| `--cache-dir` | `CACHE_DIR` | `/var/cache/mcp-kb` |

**CFG-2.** The config file says what to serve; flags and environment say how to run. No setting
exists in both. Transport, host and port are in [http-and-tools.md](http-and-tools.md).

**CFG-3.** `mcp-kb schema` prints the config's JSON Schema and exits 0 without reading a config.
`config.schema.json` in the repository is the same document.

## The config file

**CFG-4.** The file is YAML with three optional top-level lists, `sources`, `plugins` and
`libraries`. An empty file is a valid config with all three empty.

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
is not YAML or fails validation exits with code 2 and `mcp-kb: <reason>` on stderr.

**CFG-8.** A validation error that quotes a URL has its `user:password@` masked as `***@`.

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
fails the fetch with `<path> is not a directory`.

## `cache: live`

**SRC-21.** On a live fetch, each read of one of its files (skill file, library file, `_manifest`,
prompt) first revalidates that file: one request for its ETag, and a download only if the ETag
differs from the local copy's.

**SRC-22.** A download is staged in `<cache>/src/<slug>/.work/` and renamed over the local copy in
one step, so a reader sees one whole version of the file.

| Bound | Value |
|---|---|
| a file revalidated this recently is served without asking | 2 s |
| one revalidation request times out after | 1 s |
| after a failure, the fetch is not revalidated for | 30 s |

**SRC-23.** A failed revalidation logs a warning and serves the local copy; the read never fails
for it. While the fetch is cooling, `/health` shows `cooling: true`.

**SRC-24.** A file deleted upstream is served from the local copy until the fetch is rebuilt. A
file added or renamed upstream, and an edited description in a listing, wait for a rebuild.

**SRC-25.** A live fetch's `/health` entry carries `live: true` and the counts `revalidated` and
`fetched`.

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

**SRC-30.** `<cache>/index.json` holds every fetch and plugin record of the served snapshot. It is
written atomically at boot and after every rebuild. When it cannot be written, the server logs a
warning and serves on.

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
hash equals that of the parsed config, so formatting and comments do not count.

**SRC-37.** From a reused index, boot keeps each `ok` or `stale` fetch record whose tree is on
disk, and the plugin records of those fetches while their lists and root still match (SRC-48). It
builds the rest.

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
| 2 | the config is unreadable, not YAML or invalid; or a bad command-line argument |
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

**SRC-48.** On a change, the plugins of every rebuilt fetch are harvested again, every marketplace
is re-read from disk, any fetch a marketplace starts needing is built, and a snapshot with the
next generation replaces the served one in one assignment. A plugin whose effective lists or root
changed is harvested again too, though its own fetch did not move: a marketplace entry on another
repository takes its `skills`, `commands` and `agents` from the marketplace's fetch, and a
`git-subdir` entry's `path` is its root and no part of the fetch key. Each plugin record keeps the
lists and root it was harvested with, and is reused only while they match. A request in flight
finishes on the snapshot it started with.

**SRC-49.** Refreshes are serialised. A background pass that raises is logged and the loop goes on.

**SRC-50.** A fetch's change of state is logged once: `failed` as an error, `stale` as a warning,
back to `ok` as info.

**SRC-51.** `POST /reindex` examines every fetch with the fingerprint check skipped, so each is
rebuilt.

**SRC-52.** The shortest `refresh` in the config is the cache lifetime a client is given for a
listing; see [http-and-tools.md](http-and-tools.md).
