"""Sources: turning a fetch into a local directory.

Every filesystem-shaped fetch is *materialised* -- made into a directory on
this machine -- before anything reads it. That is what keeps the catalogue,
the URI grammar, the scoping and the traversal guard unchanged whatever the
backend: they only ever see a ``Path``. A ``file://`` fetch is served in
place; a ``git+…`` one is cloned bare and exported under the cache directory;
a ``webdav+…`` folder is copied into it. The two that copy share one export
mechanism (``export.py``): a tree is written to a new path per version and
never over the one a snapshot is serving.

A ``Fetch`` is one URL at one ref, however many plugins read it: seven
marketplace entries in one repository are one clone. Its ``key`` is what every
error names and its ``slug`` is where the cache puts it -- never a plugin, a
library or a credential.

Each declared source, and the built-in ``file``, is read through a loader: a
kubed-mcp ``PluginLoader`` answering the addresses whose scheme is the source's
name. ``materialise(address)`` is the fetch's tree with the subdir inside it.
Deciding when a fetch has moved and rebuilding it stays kb's: it fingerprints
through the loader too.

A fetch that cannot be materialised is an error *value*, not an exception
that escapes: one bad fetch must not take the others down, and ``/health``
reports it instead.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from ..catalogue.harvest import inside
from ..config import BUILTIN_SCHEMES
from ..plugins import Fetch, source_fetch
from ..plugins.address import parse_address
from .errors import AccessRefused, SourceError
from .file import fingerprint_file, materialise_file
from .git import fingerprint_git, materialise_git
from .webdav import fingerprint_webdav, materialise_webdav

if TYPE_CHECKING:
    from ..config import Config, SourceConfig

__all__ = [
    "AccessRefused",
    "FileLoader",
    "GitLoader",
    "ServedTrees",
    "SourceError",
    "SourceLoader",
    "WebdavLoader",
    "loaders",
    "not_in",
    "plugin_root",
]


class SourceLoader(ABC):
    """One source's fetches, as a ``PluginLoader`` for the source's name.

    The source, with the credentials it declares, and the cache directory are
    given here; None is the built-in ``file://``. ``materialise(address)`` is
    the folder the address names: its fetch's tree, then the subdir inside it.
    A subclass names its backend's ``build`` and ``stamp``.
    """

    def __init__(self, source: SourceConfig | None, cache: Path) -> None:
        self.source = source
        self.cache = cache
        self.schemes = BUILTIN_SCHEMES if source is None else (source.name,)

    @staticmethod
    @abstractmethod
    def build(fetch: Fetch, cache: Path) -> Path: ...

    @staticmethod
    @abstractmethod
    def stamp(fetch: Fetch, cache: Path, root: Path) -> dict: ...

    def materialise(self, address: str) -> Path:
        parsed = parse_address(address)
        fetch = source_fetch(self.source, parsed)
        root = plugin_root(self.build(fetch, self.cache), parsed.subdir)
        if root is None:
            raise SourceError(not_in(parsed.subdir, fetch.key))
        return root

    def fingerprint(self, fetch: Fetch, root: Path) -> dict:
        """What the tree at ``root`` is, and what its remote is now."""
        return self.stamp(fetch, self.cache, root)


class FileLoader(SourceLoader):
    build = staticmethod(materialise_file)
    stamp = staticmethod(fingerprint_file)


class GitLoader(SourceLoader):
    build = staticmethod(materialise_git)
    stamp = staticmethod(fingerprint_git)


class WebdavLoader(SourceLoader):
    build = staticmethod(materialise_webdav)
    stamp = staticmethod(fingerprint_webdav)


LOADERS: dict[str, type[SourceLoader]] = {
    "file": FileLoader,
    "git": GitLoader,
    "webdav": WebdavLoader,
}


def loaders(config: Config, cache: Path) -> dict[str, SourceLoader]:
    """A loader for each declared source and for ``file://``, by its scheme."""
    found: dict[str, SourceLoader] = {"file": FileLoader(None, cache)}
    for source in config.sources:
        found[source.name] = LOADERS[source.backend](source, cache)
    return found


class ServedTrees:
    """The trees kb serves, as a kubed-mcp ``PluginLoader``.

    The fetch memo and never a fetcher: it clones, exports and copies nothing.
    ``served`` answers a fetch key with the tree the knowledge base is serving
    for it now (the last good one included), or None. kubed-mcp is handed kb's
    own address and gets back that tree, never a cache path of its own making.
    """

    def __init__(
        self, schemes: tuple[str, ...], served: Callable[[str], Path | None]
    ) -> None:
        self.schemes = schemes
        self.served = served

    def materialise(self, address: str) -> Path:
        parsed = parse_address(address)
        tree = self.served(parsed.key)
        if tree is None:
            raise SourceError(f"{parsed.key} is not materialised")
        root = plugin_root(tree, parsed.subdir)
        if root is None:
            raise SourceError(not_in(parsed.subdir, parsed.key))
        return root


def plugin_root(fetch_root: Path, subdir: str) -> Path | None:
    """The plugin or marketplace root inside a materialised fetch, or None.

    ``inside`` is the guard the harvest and every read use, and it belongs
    here too: a subdir that is a *symlink* out of the fetch makes ``is_dir()``
    true for an arbitrary directory, which then becomes the harvest's base --
    so everything under it is "contained" relative to the escaped root and is
    served. ``..`` never gets this far (``parse_address`` refuses it), and a
    link inside the fetch still resolves, which is what makes a ConfigMap
    mount -- every path of which is a symlink -- servable.

    The path handed back is the one that was asked for rather than its
    target, because that is what a ``skill://`` address and an index row are
    built from; containment is decided on the resolved one and nothing else.
    """
    root = fetch_root / subdir
    if inside(root, fetch_root.resolve()) is None or not root.is_dir():
        return None
    return root


def not_in(subdir: str, key: str) -> str:
    """Why a root was refused: the subdir and the fetch, and no cache path.

    One message for both refusals, because from outside they are one thing --
    the fetch holds no directory this plugin or marketplace can be served
    from, whether because there is nothing there or because what is there
    leads out of the tree.
    """
    return f"{subdir or '/'} is not a directory in {key}"
