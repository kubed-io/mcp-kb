"""The knowledge base: the lifecycle of what the server serves.

Builds the catalogue a config file describes and keeps it current; the MCP
server over it -- the address space, the resources, the resource tools, the
routes -- is ``app.create_app``'s. Turning a fetch into a directory is
``sources``'s job; resolving
the config's plugins and reading a marketplace is ``plugins``'s; deciding what
in a plugin counts as a skill, a prompt or a library-level file is
``catalogue/harvest.py``'s; building one immutable view of all of it is
``catalogue/snapshot.py``'s; the catalogue itself lives in
``catalogue/skills.py``, ``catalogue/prompts/`` and ``catalogue/uris.py``; and
deciding when a fetch is looked at again is ``catalogue/refresh.py``'s. This
module runs the resolution phases in order, connects the pieces, and owns the
one mutable thing in the process: which ``Snapshot`` is current.

Three rules follow from that, and every change here has to keep them:

- **Start from the fetches on disk, not from the sources.** ``<cache>/index.json``
  holds each fetch's tree and fingerprint. A boot over the same config keeps
  every tree still on disk and harvests every plugin from it, which touches no
  network. The question "has anything changed?" is deferred to the background
  pass that runs a moment later.
- **Swap, never mutate.** A rebuild constructs a whole new ``Snapshot`` beside
  the live one and replaces it with a single assignment. The old snapshot keeps
  serving until that instant, so there is no window in which the server has a
  partial catalogue, and a request already in flight finishes against the
  consistent one it started with.
- **Read through the getter.** Every provider, tool and route is handed a
  ``lambda: self.snapshot...`` or has the current ``Catalogue`` injected per
  call, never a stored one. A stored one would pin that component to the
  generation it was registered in, which is a bug that looks exactly like "the
  refresh does not work".
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterable
from pathlib import Path
from typing import Any

from .catalogue.index import INDEX_VERSION, FetchRecord, Index, config_hash, now
from .catalogue.prompts import FilePrompt
from .catalogue.refresh import Schedule, keep_last_good, loop, moved, same_failure
from .catalogue.skills import LibraryFiles, SkillIndex
from .catalogue.snapshot import (
    SERVABLE,
    Harvest,
    Library,
    Snapshot,
    assemble_libraries,
    build_fetch,
    build_plugin,
    build_snapshot,
    failed_plugin,
    log_changes,
    unrooted,
    with_manifest,
)
from .catalogue.uris import Catalogue
from .config import Config
from .plugins import Fetch, Plugin, declared_plugins, marketplace_fetches
from .plugins.marketplace import find_marketplace, read_marketplace
from .sources import SourceLoader, loaders, not_in, plugin_root

log = logging.getLogger(__name__)

INDEX_FILE = "index.json"


class KnowledgeBase:
    """The libraries a config file names: built at boot, then kept current.

    Building one is the cold start, so a config whose credentials are refused
    fails here, before anything serves. ``app.create_app`` serves it.
    """

    def __init__(self, config: Config, cache: Path):
        self.config = config
        self.cache = cache
        self.index_path = cache / INDEX_FILE
        self.loaders = loaders(config, cache)
        # Every write of the records, the harvests and self.snapshot happens
        # under this, so two refreshes triggered at once still swap in a single
        # order.
        self._lock = threading.Lock()
        # When each fetch was last examined; see catalogue/refresh.py, which
        # decides what that means and when one comes due again.
        self.schedule = Schedule()

        self._fetches: dict[str, FetchRecord] = {}
        self._harvests: dict[str, Harvest] = {}
        self._plugins: list[Plugin] = []
        self._libraries: list[Library] = []
        # What serves each snapshot before it is swapped in: the plugin layer's
        # publisher, once ``serve_through`` is called. It returns the snapshot
        # to swap in, narrowed to what it serves.
        self._publish: Callable[[Snapshot], Snapshot] | None = None
        self._cold_start()
        self.snapshot: Snapshot = self._build(generation=0)
        log_changes({}, self.snapshot.status)
        self._write_index()

    # -- what the snapshot currently holds -----------------------------------

    @property
    def generation(self) -> int:
        return self.snapshot.generation

    @property
    def index(self) -> SkillIndex:
        return self.snapshot.index

    @property
    def resources(self) -> LibraryFiles:
        return self.snapshot.resources

    @property
    def catalogue(self) -> Catalogue:
        return self.snapshot.catalogue

    @property
    def prompts(self) -> tuple[FilePrompt, ...]:
        return self.snapshot.prompts

    @property
    def status(self) -> dict[str, dict]:
        return self.snapshot.status

    @property
    def fetches(self) -> list[Fetch]:
        """This generation's fetches: the marketplaces', then every plugin's.

        Derived from the plugins rather than stored, so a marketplace that
        gained an entry on another repository brings that repository's fetch
        into the next pass by itself.
        """
        found: dict[str, Fetch] = {}
        for _, fetch, _ in marketplace_fetches(self.config).values():
            found.setdefault(fetch.key, fetch)
        for plugin in self._plugins:
            found.setdefault(plugin.fetch.key, plugin.fetch)
        return list(found.values())

    # -- building it ---------------------------------------------------------

    def _cold_start(self) -> None:
        """Resolve everything, keeping every fetch the on-disk index still holds.

        A fetch built here whose server refuses its credentials stops the
        process: ``AccessRefused`` escapes, and ``main`` exits naming it. A
        refusal is the one failure a wait does not fix -- a wrong password, an
        account not yet let in -- and a pod that exits is restarted, visibly,
        until it is fixed, where one that serves on looks healthy with a
        library missing. Every other failure stays a failed fetch, so an
        unreachable remote at boot never takes the libraries that did load down
        with it; and a refusal on a later refresh, of a fetch already serving,
        makes it stale and is logged.

        No fingerprint is taken here. Checking one means walking every tree,
        which is the cost this whole file exists to move off the boot path;
        the verification pass the lifespan runs immediately afterwards does it
        instead, and until it finishes the server serves last boot's trees --
        which are almost always still the right ones. Every plugin is harvested
        from them again: a local walk, and nothing about a harvest is stored.
        """
        stored = Index.read(self.index_path)
        fetches: dict[str, FetchRecord] = {}
        if stored is not None and stored.config_hash == config_hash(self.config):
            fetches = {
                key: record
                for key, record in stored.fetches.items()
                if _serving(record)
            }
        elif stored is not None:
            log.info("config changed since %s was written; rebuilding", self.index_path)
        self._fetches = fetches
        self._plugins, self._libraries, self._harvests = self._assemble(
            fetches, refusal_is_fatal=True
        )

    def _assemble(
        self,
        fetches: dict[str, FetchRecord],
        *,
        refusal_is_fatal: bool = False,
    ) -> tuple[list[Plugin], list[Library], dict[str, Harvest]]:
        """The resolution phases: marketplaces, fetches, plugins, then libraries.

        ``fetches`` is the records already in hand -- reused from the index or
        left alone by a refresh -- and is *added to*: every fetch a marketplace
        or a plugin needs that is not in it is built here, and every record
        nothing needs any more is dropped, so on return it holds exactly this
        generation's fetches. Every plugin whose fetch serves is harvested
        again off its tree, which is cheap and touches no network, so no
        harvest outlives the lists or the root that chose it (SRC-48).

        A marketplace's plugins are re-derived by re-reading its
        ``marketplace.json`` off the tree on disk every time: cheap, and the
        only way a refresh of that fetch can serve an entry it gained. A stale
        fetch is read off its last good tree, so its entry count -- what decides
        a lone entry is its library's main plugin -- is still known; only a
        marketplace that could not be read at all leaves it out.
        """
        declared = declared_plugins(self.config)
        markets = marketplace_fetches(self.config)

        derived: list[Plugin] = []
        errors: dict[str, str] = {}
        skipped: dict[str, tuple[dict[str, str], ...]] = {}
        descriptions: dict[str, str] = {}
        entries: dict[str, int] = {}
        for name, (library, fetch, address) in markets.items():
            record = self._fetch_record(fetches, fetch, refusal_is_fatal)
            if not _serving(record):
                errors[name] = record.error or "the marketplace could not be fetched"
                continue
            root = plugin_root(Path(record.root or ""), address.subdir)
            if root is None:
                errors[name] = not_in(address.subdir, fetch.key)
                continue
            if find_marketplace(root) is None:
                errors[name] = f"no marketplace.json under {address.subdir or '/'}"
                continue
            try:
                market = read_marketplace(
                    root,
                    library=library,
                    fetch=fetch,
                    address=address,
                    config=self.config,
                )
            except ValueError as exc:
                # An unreadable file's error quotes its absolute path, which
                # is a cache path: stripped, as every harvest string is.
                errors[name] = unrooted(str(exc), root)
                continue
            derived += market.plugins
            descriptions[name] = market.description
            entries[name] = market.entries
            if market.skipped:
                skipped[name] = market.skipped

        plugins = [*declared, *derived]
        for plugin in plugins:
            self._fetch_record(fetches, plugin.fetch, refusal_is_fatal)
        needed = {p.fetch.key for p in plugins}
        needed |= {fetch.key for _, fetch, _ in markets.values()}
        for key in [key for key in fetches if key not in needed]:
            del fetches[key]

        # Each plugin comes back completed by its manifest, so the selectors,
        # the scopes and /health all see the labels the publisher declared.
        completed: list[Plugin] = []
        harvests: dict[str, Harvest] = {}
        for plugin in plugins:
            plugin, harvests[plugin.id] = self._harvest(
                plugin, fetches[plugin.fetch.key]
            )
            completed.append(plugin)
        libraries = assemble_libraries(
            self.config,
            completed,
            errors=errors,
            skipped=skipped,
            descriptions=descriptions,
            entries=entries,
        )
        return completed, libraries, harvests

    def _fetch_record(
        self, fetches: dict[str, FetchRecord], fetch: Fetch, refusal_is_fatal: bool
    ) -> FetchRecord:
        """The record for ``fetch``, built now if there is none in hand."""
        record = fetches.get(fetch.key)
        if record is None:
            record = build_fetch(
                fetch, self._loader(fetch), refusal_is_fatal=refusal_is_fatal
            )
            fetches[fetch.key] = record
        return record

    def _loader(self, fetch: Fetch) -> SourceLoader:
        return self.loaders[fetch.scheme]

    def _harvest(self, plugin: Plugin, fetch: FetchRecord) -> tuple[Plugin, Harvest]:
        """The plugin completed by its manifest, and its harvest, made now.

        The manifest is read whenever the root is there: it is one small file,
        and it decides what the harvest reads.
        """
        if not _serving(fetch):
            return plugin, failed_plugin(plugin, fetch.error or "the fetch failed")
        root = plugin_root(Path(fetch.root or ""), plugin.subdir)
        if root is None:
            refusal = not_in(plugin.subdir, plugin.fetch.key)
            return plugin, failed_plugin(plugin, refusal)
        try:
            plugin, globs = with_manifest(plugin, root)
        except ValueError as exc:
            # An OSError behind the read quotes the cache path; /health is
            # published, so the root comes back out of it here as everywhere.
            return plugin, failed_plugin(plugin, unrooted(str(exc), root))
        return plugin, build_plugin(plugin, root, globs=globs)

    def _build(self, generation: int) -> Snapshot:
        return build_snapshot(
            self.config,
            self._plugins,
            self._libraries,
            self._fetches,
            self._harvests,
            generation,
        )

    def _write_index(self) -> None:
        """Persist the current fetch records, or log why the next boot will be slow.

        A cache directory that cannot be written is not fatal: the catalogue is
        already built and serving. It only means the next cold start fetches
        everything again, which is the cost the index exists to save.
        """
        record = Index(
            version=INDEX_VERSION,
            built=now(),
            config_hash=config_hash(self.config),
            fetches=self._fetches,
        )
        try:
            self.cache.mkdir(parents=True, exist_ok=True)
            record.write(self.index_path)
        except OSError as exc:
            log.warning("could not write %s: %s", self.index_path, exc)

    def refresh(
        self, *, force: bool = False, only: Iterable[str] | None = None
    ) -> list[str]:
        """Rebuild whatever has changed and swap in a new snapshot. Blocking.

        Returns the fetch keys actually rebuilt, in this generation's order --
        empty when nothing moved, which is the common case and the reason the
        generation does not advance on every pass. ``only`` narrows the sweep
        to the fetches the caller already knows are due; ``force`` skips the
        fingerprint check and rebuilds them regardless.

        Every marketplace on a rebuilt fetch is re-read, so an entry it gained
        is served, and every plugin is harvested again, whichever fetch it
        reads: an entry on another repository's can change its lists or its
        root while its own fetch stands still.

        Synchronous and serialised: this walks trees, hashes files and writes
        ``index.json``, and two of them at once would race for the index's
        temporary file. Call it from the event loop through ``refresh_async``.
        """
        keys = None if only is None else set(only)
        checked_at = time.monotonic()
        with self._lock:
            fetches = dict(self._fetches)
            rebuilt: list[str] = []
            for fetch in self.fetches:
                if keys is not None and fetch.key not in keys:
                    continue
                current = fetches.get(fetch.key)
                # Examined, whether or not it turns out stale -- the schedule
                # runs off this, so it must move on every check and not only
                # on a rebuild.
                self.schedule.examined(fetch.key, checked_at)
                if (
                    not force
                    and current is not None
                    and not moved(fetch, self._loader(fetch), current)
                ):
                    continue
                built = build_fetch(fetch, self._loader(fetch))
                fresh = keep_last_good(current, built)
                if same_failure(current, fresh):
                    continue
                fetches[fetch.key] = fresh
                rebuilt.append(fetch.key)

            if not rebuilt:
                return []
            known = set(fetches)
            plugins, libraries, harvests = self._assemble(fetches)
            # A marketplace re-read above may have gained an entry on another
            # repository, which `_assemble` materialises -- after the loop,
            # which only ever sees the fetches this generation already had. It
            # was built, so it belongs in what was rebuilt; otherwise
            # `/reindex` and the log both omit a clone that really happened.
            rebuilt += [key for key in fetches if key not in known]
            # Assigned before the build and the publish, which read them: the
            # publisher finds the new trees through ``served_tree``. A raise in
            # either puts back the four it replaced, so nothing points at a
            # generation that was never swapped in.
            was = self._fetches, self._plugins, self._libraries, self._harvests
            self._fetches, self._plugins = fetches, plugins
            self._libraries, self._harvests = libraries, harvests
            try:
                snapshot = self._build(generation=self.snapshot.generation + 1)
                if self._publish is not None:
                    snapshot = self._publish(snapshot)
            except BaseException:
                self._fetches, self._plugins, self._libraries, self._harvests = was
                raise
            log_changes(self.snapshot.status, snapshot.status)
            self.snapshot = snapshot
            # Best-effort and therefore last, after the swap: a raise here
            # leaves the harvests and the snapshot one generation, the new one.
            self._write_index()
            return rebuilt

    def serve_through(self, publish: Callable[[Snapshot], Snapshot]) -> None:
        """Hand every snapshot to ``publish`` before it is swapped in.

        The current one at once, then every rebuilt one, under the lock, so a
        snapshot is served by the plugin layer before any request reads it and
        two refreshes publish in the order they swap. ``publish`` returns the
        snapshot to swap in: the one it was given, narrowed to what it serves.
        """
        with self._lock:
            self._publish = publish
            published = publish(self.snapshot)
            log_changes(self.snapshot.status, published.status)
            self.snapshot = published

    def renarrowed(self, was: Snapshot, now: Snapshot) -> None:
        """Swap in ``now``, the same generation as ``was`` narrowed again by the
        publisher after a live re-read (D9), when ``was`` is still the one served.

        Takes no lock, as ``served_tree`` does not: the publisher calls this
        holding its own lock, which a refresh needs to publish before it swaps,
        so no swap can land between the check and the assignment.
        """
        if self.snapshot is was:
            self.snapshot = now

    def served_tree(self, key: str) -> Path | None:
        """The tree being served for fetch ``key``, or None.

        The last good one counts: a fetch that went ``stale`` on a refresh still
        answers its old root.

        Takes no lock, and must not: ``refresh`` publishes while holding
        ``_lock`` (a plain ``Lock``), and that publisher reaches this through the
        plugin layer. Reading is safe because ``_fetches`` is replaced whole under
        ``_lock`` and never changed once published; the one in-place mutation is
        ``_cold_start`` inside ``__init__``, before any reader exists.
        """
        record = self._fetches.get(key)
        if record is None or not _serving(record):
            return None
        return Path(record.root or "")

    async def refresh_async(self, **kwargs) -> list[str]:
        """``refresh`` off the event loop, because all of it blocks."""
        return await asyncio.to_thread(self.refresh, **kwargs)

    # -- keeping it current --------------------------------------------------

    @contextlib.asynccontextmanager
    async def lifespan(self, server: Any) -> AsyncIterator[dict]:
        """Run the refresh loop for as long as the server is up."""
        del server
        task = asyncio.create_task(loop(self))
        try:
            yield {}
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def _serving(record: FetchRecord) -> bool:
    """Whether a fetch record still names a tree on disk worth serving from.

    ``stale`` counts -- its tree is the last good one.
    """
    return (
        record.status in SERVABLE
        and record.root is not None
        and Path(record.root).is_dir()
    )
