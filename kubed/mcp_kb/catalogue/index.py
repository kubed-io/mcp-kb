"""The on-disk index: what each fetch and each plugin yielded, without re-harvesting.

Cold start reads this file and reconstructs every ``Skill`` straight from it,
with no filesystem walk and no frontmatter parse -- that is the whole point of
writing one. A prompt is recorded as the path of its file and nothing more: the
plugin layer reads and parses it, through kb's command reader, as the plugin
is added. So is an agent file: the plugin layer is its one reader (AGT-6). A
row is therefore self-contained: absolute paths as strings, and no reference
back to a live object.

Two kinds of record, because two things are expensive: a ``FetchRecord`` is
one materialised tree (a clone, a copy, a directory) and its fingerprint, and
a ``PluginRecord`` is one plugin's harvest out of such a tree. A skill row
carries no library: which libraries a plugin serves in is assembled from the
config at snapshot time, and a plugin in two libraries is one harvest served
twice.

``Index`` is a frozen dataclass whose two mapping fields are plain ``dict``s.
Python does not stop a caller from mutating a dict reached through a frozen
instance; nothing here needs it to. The type is immutable by convention,
matching every other snapshot in this codebase, and callers that build a new
``Index`` build new mappings rather than mutating one in place.

``config_hash`` and the ``version`` field are cold start's two questions before
it trusts anything in the file: "was this built from the config I have now",
and "do I still know how to read this shape". Either mismatch means rebuild
from scratch, so ``Index.read`` folds every way of failing those questions --
missing file, unparsable JSON, a wrong or absent version, a shape that does
not match the dataclasses below -- into a single ``None``.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from ..config import Config
from ..plugins import Globs
from .skills import Skill

INDEX_VERSION = 11


@dataclass(frozen=True)
class SkillRow:
    """A harvested skill, flattened to JSON-safe fields.

    No library, folder, plugin, category or tags: those are the library's and
    the plugin's, put back on by ``to_skill`` when a snapshot assigns the plugin
    to a library. The folder is the library's decision too -- empty for its
    main plugin, the plugin's name otherwise -- so one plugin in two libraries
    is one row served at two addresses.
    """

    name: str
    description: str
    path: str

    @classmethod
    def from_skill(cls, skill: Skill) -> SkillRow:
        return cls(
            name=skill.name,
            description=skill.description,
            path=str(skill.path),
        )

    def to_skill(
        self,
        *,
        library: str,
        folder: str,
        plugin: str,
        root: Path,
        category: str | None,
        tags: frozenset[str],
        library_categories: frozenset[str] = frozenset(),
        live: bool = False,
    ) -> Skill:
        return Skill(
            name=self.name,
            library=library,
            folder=folder,
            description=self.description,
            path=Path(self.path),
            plugin=plugin,
            root=root,
            category=category,
            tags=tags,
            library_categories=library_categories,
            live=live,
        )


@dataclass(frozen=True)
class FetchRecord:
    """One materialised tree: where it is on disk, and the fingerprint it had.

    ``status``/``error`` carry a failed fetch the way ``sources.materialise``
    already does elsewhere -- a bad fetch is a value on the record, not an
    exception that would keep the other fetches out of the index.

    ``"stale"`` is the third state and the useful one: everything an ``"ok"``
    record has -- a root, a fingerprint -- plus the error from the refresh that
    failed. It is served exactly like ``"ok"``, because the last good tree is
    still on disk and still the best answer available.
    """

    key: str
    status: Literal["ok", "failed", "stale"]
    root: str | None
    fingerprint: dict
    built: str
    error: str | None


@dataclass(frozen=True)
class PluginRecord:
    """One plugin's harvest out of its fetch's tree: every row built from it.

    ``root`` is the plugin root -- the fetch root joined with the plugin's
    subdirectory -- and ``fetch`` the key of the record it was harvested from,
    which is what decides whether this record can be reused when that one is.
    ``globs`` are what chose the files out of that tree, and with ``root``
    decide it too: a marketplace entry's lists and subdirectory are the
    marketplace's, which may be another fetch, so the tree can stand still
    while what it serves changes (SRC-48).
    ``None`` is a record with no harvest behind it, which nothing reuses.
    A plugin fails on its own when its root is not a directory, its manifest
    does not parse, or its fetch failed; the error says which.
    """

    id: str
    fetch: str
    root: str | None
    status: Literal["ok", "failed"]
    error: str | None
    built: str
    skills: tuple[SkillRow, ...]
    # The prompt files the harvest selected, root-relative and in path order.
    # Nothing is parsed here: the plugin layer reads them, through kb's command
    # reader, when the plugin is added (PRM-18).
    prompts: tuple[str, ...]
    files: tuple[str, ...]
    skill_dirs: tuple[str, ...]
    # What the harvest found and could not load, as ``{"path", "reason"}``
    # rows. None is written now: an agent file is the plugin layer's to read,
    # and the plugin layer says what it skips (AGT-6).
    skipped: tuple[dict[str, str], ...] = ()
    # The agent files the harvest found, root-relative and in its order, read
    # by nothing here; and the paths a fallback must refuse (AGT-3).
    agents: tuple[str, ...] = ()
    agent_paths: tuple[str, ...] = ()
    globs: Globs | None = None
    # Those of ``prompts`` a ``commands`` declaration selects, which are read in
    # Claude's dialect wherever they sit (PRM-14).
    claude_prompts: tuple[str, ...] = ()


def _fetch_record_from_dict(raw: dict) -> FetchRecord:
    return FetchRecord(
        key=raw["key"],
        status=raw["status"],
        root=raw["root"],
        fingerprint=raw["fingerprint"],
        built=raw["built"],
        error=raw["error"],
    )


def _plugin_record_from_dict(raw: dict) -> PluginRecord:
    return PluginRecord(
        id=raw["id"],
        fetch=raw["fetch"],
        root=raw["root"],
        status=raw["status"],
        error=raw["error"],
        built=raw["built"],
        skills=tuple(SkillRow(**s) for s in raw["skills"]),
        prompts=_paths(raw["prompts"]),
        files=tuple(raw["files"]),
        skill_dirs=tuple(raw["skill_dirs"]),
        skipped=tuple(_skipped_row(row) for row in raw["skipped"]),
        agents=_paths(raw["agents"]),
        agent_paths=tuple(raw["agent_paths"]),
        globs=_globs_from_dict(raw["globs"]),
        claude_prompts=_paths(raw["claude_prompts"]),
    )


def _globs_from_dict(raw: dict | None) -> Globs | None:
    """A ``Globs`` back from JSON, tuples and all, so it compares equal.

    A kind's null stays ``None`` and its empty list becomes ``()``: the two are
    the conventions and none of that kind, and blurring them would re-harvest
    every plugin on every cold start, or worse, reuse the wrong harvest.
    """
    if raw is None:
        return None

    def kind(key: str) -> tuple[str, ...] | None:
        value = raw[key]
        return None if value is None else tuple(value)

    return Globs(
        skills=kind("skills"),
        prompts=kind("prompts"),
        files=kind("files"),
        commands=tuple(raw["commands"]),
        agents=kind("agents"),
        command_dirs=tuple(raw["command_dirs"]),
        command_files=tuple(raw["command_files"]),
    )


def _paths(raw: object) -> tuple[str, ...]:
    """A list of root-relative paths, refused when it is anything else."""
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
        raise ValueError(f"not a list of paths: {raw!r}")
    return tuple(raw)


def _skipped_row(row: object) -> dict[str, str]:
    """One ``{"path", "reason"}`` row, exactly -- anything else is a bad index.

    Every other field is shaped by constructing a dataclass, which refuses a
    wrong one; this one is a plain dict, so it is checked by hand, and a row
    the log and ``/health`` would index into must not reach them half-formed.
    """
    if (
        not isinstance(row, dict)
        or set(row) != {"path", "reason"}
        or not all(isinstance(v, str) for v in row.values())
    ):
        raise ValueError(f"not a skipped row: {row!r}")
    return {"path": row["path"], "reason": row["reason"]}


@dataclass(frozen=True)
class Index:
    """The whole on-disk record: one JSON file, one atomic write."""

    version: int
    built: str
    config_hash: str
    fetches: dict[str, FetchRecord]
    plugins: dict[str, PluginRecord]

    def write(self, path: Path) -> None:
        """Write to a unique temp file beside ``path``, then ``os.replace`` it.

        A reader never sees a half-written file: ``os.replace`` is a single
        filesystem rename, so the index at ``path`` is either the previous
        complete one or this complete one, never a partial write. The temp
        file comes from ``tempfile.mkstemp`` rather than a fixed sibling name,
        so two writers in the same directory can never race for it.
        """
        fd, name = tempfile.mkstemp(
            dir=path.parent, prefix=f"{path.name}.", suffix=".tmp"
        )
        tmp = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(self), sort_keys=True))
        os.replace(tmp, path)  # noqa: PTH105 - the atomic rename tests monkeypatch

    @classmethod
    def read(cls, path: Path) -> Index | None:
        """The index at ``path``, or ``None`` when it cannot be trusted.

        Missing, unparsable, the wrong version, or a shape that does not match
        the dataclasses above all collapse to the same ``None`` -- every case
        means "rebuild from scratch", so the cause does not need to travel any
        further than a log line at the call site.
        """
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict) or raw.get("version") != INDEX_VERSION:
            return None
        if not isinstance(raw.get("fetches"), dict) or not isinstance(
            raw.get("plugins"), dict
        ):
            return None
        try:
            return cls(
                version=raw["version"],
                built=raw["built"],
                config_hash=raw["config_hash"],
                fetches={
                    key: _fetch_record_from_dict(rec)
                    for key, rec in raw["fetches"].items()
                },
                plugins={
                    pid: _plugin_record_from_dict(rec)
                    for pid, rec in raw["plugins"].items()
                },
            )
        except (KeyError, TypeError, AttributeError, ValueError):
            return None


def config_hash(config: Config) -> str:
    """A stable fingerprint of the config, independent of key order.

    The telemetry section is left out (D3): it says what the process reports,
    not what it serves, so changing it must not discard a warm index.
    """
    payload = json.dumps(
        config.model_dump(mode="json", exclude={"telemetry"}), sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def now() -> str:
    """The current time, ISO-8601 UTC at seconds precision."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
