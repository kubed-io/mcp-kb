"""``cache: live``: bringing a fetch up to date with its server in the background.

A mirrored source is copied into the cache and read from disk, which is why a
request touches no network at all. That is the right trade for a git repository
and the wrong one for a folder somebody is editing: a note changed in Nextcloud
should be readable now, not after the next refresh.

So a source may say ``cache: live``, and then the read path tells the
revalidator what it is about to serve. Given that path, the revalidator finds
the live fetch that owns it and, if that fetch is due, starts a pass on a
thread of its own and returns. The pass lists each due fetch once, one
``Depth: 1`` PROPFIND per directory, and downloads each file whose ETag moved.
The read serves what is on disk now; the first request after the pass lands
serves the edit (SKL-37).

Four properties this has to keep, and they are why it is this module rather
than a cache library:

- **No request waits for the server.** A read runs on the event loop, so a
  Nextcloud that accepts connections and never answers would otherwise stall
  every request the server is handling, ``/health`` included. Nothing here
  touches the network on its caller's thread: ``revalidate`` only decides
  whether a pass is due and starts one. One pass runs at a time, and a kick
  while one runs starts nothing and waits for nothing.
- **It degrades to the copy on disk.** Every failure is logged once and
  swallowed. A server that is down, a password that was rotated, a proxy that
  is confused: none of them may turn a read that a complete local copy could
  have answered into a read that fails. The client timeout and the cooldown
  below keep a wedged server from costing a pass more than once.
- **It prices the files the export holds, so it cannot see a new one.** A file
  that did not exist when the folder was indexed has no URI, and nothing asks
  to read it. A file deleted upstream goes on serving from the local copy. New
  and deleted files are a ``refresh:`` interval's job, or ``POST /reindex``.
- **It belongs to its snapshot.** A refresh exports the folder to a *new*
  directory, so the roots in here are the previous generation's the moment one
  finishes. ``build_snapshot`` builds a revalidator alongside the snapshot that
  uses it, and ``retire`` stops it: a retired revalidator starts no pass, and a
  pass under way stops before its next fetch or file.

fsspec ships ``filecache``, which is the obvious alternative and does not fit:
it stores files under hashed names in a directory of its own, and everything
downstream of a fetch here is a real directory tree of ``Path``s.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..plugins import Fetch
from .webdav import client, download, recorded_etags, remote_etags

if TYPE_CHECKING:
    from webdav4.fsspec import WebdavFileSystem

log = logging.getLogger(__name__)

# How long a fetch is taken on trust once a pass has priced it, counted from
# when that pass ended. A client that lists and then reads asks for the same
# plugin twice within the same second; without a floor every request would
# start a listing of the whole folder. Under steady traffic an edit is served
# about this long, plus one pass, after it was saved.
TTL_SECONDS = 2.0

# What one revalidation request may take. httpx defaults to 5 seconds. Per HTTP
# operation, so a large file downloading steadily is unaffected; what this
# bounds is a server that has gone quiet, which would otherwise hold the pass,
# and every fetch behind it, for that long per request.
REVALIDATE_TIMEOUT = 1.0

# How long a fetch is left unrevalidated after a pass failed on it. The timeout
# above bounds a single request; this is what stops a wedged server costing a
# pass anything at all after the first. Short, because the cost of being wrong
# is one revalidation's delay and the gain is that a folder comes back to life
# by itself.
COOLDOWN_SECONDS = 30.0


def is_live(fetch: Fetch) -> bool:
    """Whether reads of ``fetch`` revalidate. Only a WebDAV source can say so."""
    return fetch.backend == "webdav" and fetch.live


@dataclass
class _Live:
    """One live fetch: what it is, where its copy is, what its files were.

    ``etags`` starts as the map written into the export at index time and is
    updated in place as files are downloaded again, so it always says what the
    tree on disk holds. ``fs`` is built by the first pass and kept: a client per
    pass is a TCP connection and a TLS handshake per pass.

    Only the pass writes any of it. A kick and ``stats`` read the floats and
    ints, which is all they need.
    """

    fetch: Fetch
    root: Path
    etags: dict[str, str]
    fs: WebdavFileSystem | None = None
    revalidated: int = 0
    fetched: int = 0
    # The monotonic clock reading this fetch may be revalidated again at. Set
    # when a pass fails on it, cleared when one succeeds.
    cooling_until: float = 0.0
    # The monotonic clock reading the last pass over this fetch ended at.
    passed_at: float = float("-inf")


class Revalidator:
    """The live fetches of one snapshot, and the one pass that prices them.

    Built from the records a snapshot is assembled from, and retired with it.
    ``_running`` is the single-flight flag, and the one primitive the kicker
    and the pass both touch. Nobody ever blocks on it: a kick that finds it
    held returns, and the pass releases it however it ends.
    """

    def __init__(
        self,
        fetches: Sequence[tuple[Fetch, Path]],
        *,
        ttl: float | None = None,
        cooldown: float | None = None,
    ):
        self._fetches = [
            _Live(fetch=fetch, root=root.resolve(), etags=recorded_etags(root))
            for fetch, root in fetches
        ]
        # Read from the module rather than defaulted in the signature, so the
        # value a test sets is the value a snapshot built afterwards uses.
        self._ttl = TTL_SECONDS if ttl is None else ttl
        self._cooldown = COOLDOWN_SECONDS if cooldown is None else cooldown
        self._running = threading.Lock()
        # Held only while a kick starts its thread and records it, so ``wait``
        # never reads a pass older than the one running.
        self._starting = threading.Lock()
        self._thread: threading.Thread | None = None
        self._retired = False

    def revalidate(self, path: Path) -> None:
        """Start a pass if the fetch owning ``path`` is due, and return at once.

        No network here: the listing, the client and every download happen on
        the pass's thread. A kick while a pass runs starts nothing.
        """
        owned = self._owner(path)
        if owned is None or self._retired:
            return
        live, _ = owned
        if not self._due(live, time.monotonic()):
            return
        if not self._running.acquire(blocking=False):
            return
        with self._starting:
            thread = threading.Thread(
                target=self._pass, name="kb-revalidate", daemon=True
            )
            try:
                thread.start()
            except BaseException:
                self._running.release()
                raise
            self._thread = thread

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the pass running now, if any; whether none runs after it."""
        with self._starting:
            thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def retire(self) -> None:
        """Start no pass from now on, and stop the one running at its next step.

        A download already under way finishes its one atomic replace into this
        snapshot's export, which nothing reads once the snapshot is retired.
        """
        self._retired = True

    @property
    def retired(self) -> bool:
        """Whether ``retire`` was called."""
        return self._retired

    def stats(self, key: str) -> dict:
        """What passes over the fetch ``key`` have asked of its server, for ``/health``.

        ``revalidated`` counts the files compared against the server's listing,
        and ``fetched`` the ones that had moved and were downloaded again --
        which together say whether edits are actually flowing. ``cooling``
        appears while a failure has this fetch's revalidation suspended, which
        is the one state where those two counters stop moving for a reason that
        is not "nothing changed".
        """
        for live in self._fetches:
            if live.fetch.key == key:
                return {
                    "revalidated": live.revalidated,
                    "fetched": live.fetched,
                    **(
                        {"cooling": True}
                        if time.monotonic() < live.cooling_until
                        else {}
                    ),
                }
        return {}

    # -- the pass ----------------------------------------------------------------

    def _due(self, live: _Live, now: float) -> bool:
        """Whether ``live`` is neither cooling nor priced within the TTL."""
        return now >= live.cooling_until and now - live.passed_at >= self._ttl

    def _pass(self) -> None:
        """Price every due live fetch, in order; on the pass's own thread."""
        try:
            for live in self._fetches:
                if self._retired:
                    return
                if self._due(live, time.monotonic()):
                    self._price(live)
        finally:
            self._running.release()

    def _price(self, live: _Live) -> None:
        """List ``live`` once and download each of its files whose ETag moved.

        A file the listing lacks is gone upstream: its local copy goes on
        serving, and nothing is counted for it (SRC-24). A file the listing has
        and the export lacks is new, and a refresh's job. The TTL runs from the
        answer, not the question (SKL-38).
        """
        key = live.fetch.key
        rel: str | None = None
        try:
            fs = self._client(live)
            listed = remote_etags(live.fetch, fs)
            for rel in sorted(live.etags):
                if self._retired:
                    return
                etag = listed.get(rel)
                if etag is None:
                    continue
                live.revalidated += 1
                if etag != live.etags[rel] or not (live.root / rel).is_file():
                    download(live.fetch, live.root, rel, fs)
                    live.etags[rel] = etag
                    live.fetched += 1
        except Exception as exc:  # noqa: BLE001 - a flaky server is not a failed read
            if self._retired:
                return
            live.cooling_until = time.monotonic() + self._cooldown
            # The error names the fetch, and what failed, already; saying
            # either twice reads as two of them.
            if rel is None:
                reason = _reason(exc, f"{key}: listing failed: ", key)
                log.warning("%s: revalidating the listing failed: %s", key, reason)
            else:
                reason = _reason(exc, f"{key}: fetch of {rel} failed: ", key)
                log.warning("%s: revalidating %s failed: %s", key, rel, reason)
        else:
            live.cooling_until = 0.0
        finally:
            live.passed_at = time.monotonic()

    def _owner(self, path: Path) -> tuple[_Live, str] | None:
        """The live fetch ``path`` sits under, and its path within it."""
        resolved = path.resolve()
        for live in self._fetches:
            if resolved.is_relative_to(live.root):
                return live, resolved.relative_to(live.root).as_posix()
        return None

    def _client(self, live: _Live) -> WebdavFileSystem:
        """This fetch's client, built by the first pass that needs it.

        Not at construction: building one resolves a credential, and a snapshot
        must be assemblable without one -- a live fetch whose password is
        missing fails its passes and logs, it does not fail the whole rebuild.
        """
        if live.fs is None:
            live.fs = client(live.fetch, timeout=REVALIDATE_TIMEOUT)
        return live.fs


def _reason(exc: Exception, said: str, key: str) -> str:
    """What ``exc`` says once the log line's own words are taken off its front.

    An ``OSError`` raised outside the transport's reporting -- the replace onto
    the export, or a ``mkdir`` -- says its errno's words and not its filename,
    which is a path under the cache.
    """
    if isinstance(exc, OSError) and exc.strerror:
        return f"{type(exc).__name__}: {exc.strerror}"
    return str(exc).removeprefix(said).removeprefix(f"{key}: ")
