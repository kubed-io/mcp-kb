"""The on-disk index: each fetch's tree and fingerprint, so a boot fetches nothing.

A ``FetchRecord`` is one materialised tree -- a clone, a copy, a directory --
and the fingerprint it had, which is the expensive thing: building one is a
network round trip. Nothing harvested out of a tree is written. A boot and a
refresh harvest every plugin again from the trees on disk, which is a local
walk and the one way a harvest cannot outlive the lists that chose it (SRC-48).

``Index`` is a frozen dataclass whose one mapping field is a plain ``dict``.
Python does not stop a caller from mutating a dict reached through a frozen
instance; nothing here needs it to. The type is immutable by convention,
matching every other snapshot in this codebase, and callers that build a new
``Index`` build a new mapping rather than mutating one in place.

``config_hash`` and the ``version`` field are cold start's two questions before
it trusts anything in the file: "was this built from the config I have now",
and "do I still know how to read this shape". Either mismatch means rebuild
from scratch, so ``Index.read`` folds every way of failing those questions --
missing file, unparsable JSON, a wrong or absent version, a shape that does
not match ``FetchRecord`` -- into a single ``None``. A file of the previous
version is read for its ``fetches`` alone: the plugin rows it also holds are
never looked at, so no shape of them can fail a boot.
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

INDEX_VERSION = 12
# The version before this one, whose fetches are the same records: read for
# them alone, and written over as INDEX_VERSION. It goes once every deployment
# has written 12 (#84's follow-up).
PREVIOUS_VERSION = 11


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


def _fetch_record_from_dict(raw: dict) -> FetchRecord:
    return FetchRecord(
        key=raw["key"],
        status=raw["status"],
        root=raw["root"],
        fingerprint=raw["fingerprint"],
        built=raw["built"],
        error=raw["error"],
    )


@dataclass(frozen=True)
class Index:
    """The whole on-disk record: one JSON file, one atomic write."""

    version: int
    built: str
    config_hash: str
    fetches: dict[str, FetchRecord]

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

        Missing, unparsable, a version other than this one or the previous,
        or a shape that does not match ``FetchRecord`` all collapse to the same
        ``None`` -- every case means "rebuild from scratch", so the cause does
        not need to travel any further than a log line at the call site.
        ``version`` is the file's own; a previous version's ``plugins`` is
        never read.
        """
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict) or raw.get("version") not in (
            PREVIOUS_VERSION,
            INDEX_VERSION,
        ):
            return None
        if not isinstance(raw.get("fetches"), dict):
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
            )
        except (KeyError, TypeError, AttributeError, ValueError):
            return None


def config_hash(config: Config) -> str:
    """A stable fingerprint of the config, independent of key order.

    The telemetry section is left out (SRC-36): it says what the process reports,
    not what it serves, so changing it must not discard a warm index.
    """
    payload = json.dumps(
        config.model_dump(mode="json", exclude={"telemetry"}), sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def now() -> str:
    """The current time, ISO-8601 UTC at seconds precision."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
