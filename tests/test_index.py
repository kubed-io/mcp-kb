"""Unit tests for the on-disk index: round trip, corruption, atomicity."""

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, fields
from pathlib import Path

import pytest

from kubed.mcp_kb.catalogue.index import (
    INDEX_VERSION,
    PREVIOUS_VERSION,
    FetchRecord,
    Index,
    config_hash,
    now,
)
from kubed.mcp_kb.config import load_config
from kubed.mcp_kb.sources import SourceLoader
from tests.conftest import V11_PLUGIN_ROW, key_of, make_config

FETCH = "file:///skills/flatsource"
# A fetch record's fields, in the order v11 wrote them and v12 still does.
FIELDS = ["key", "status", "root", "fingerprint", "built", "error"]


def _fetch_record(**overrides):
    fields = {
        "key": FETCH,
        "status": "ok",
        "root": "/skills/flatsource",
        "fingerprint": {"mtime": 123.0},
        "built": now(),
        "error": None,
    }
    fields.update(overrides)
    return FetchRecord(**fields)


def _index(**overrides):
    fields = {
        "version": INDEX_VERSION,
        "built": now(),
        "config_hash": "deadbeef",
        "fetches": {FETCH: _fetch_record()},
    }
    fields.update(overrides)
    return Index(**fields)


def _v11(tmp_path, **raw):
    """The file as v11 wrote it: these fetches, and one plugin row of its shape."""
    body = {
        "version": 11,
        "built": now(),
        "config_hash": "deadbeef",
        "fetches": {FETCH: asdict(_fetch_record())},
        "plugins": {"flatsource": V11_PLUGIN_ROW},
        **raw,
    }
    path = tmp_path / "index.json"
    path.write_text(json.dumps(body))
    return path


@pytest.mark.unit
def test_an_index_round_trips_through_json(tmp_path):
    path = tmp_path / "index.json"
    written = _index()
    written.write(path)
    assert Index.read(path) == written


@pytest.mark.unit
def test_a_v12_index_holds_no_plugin_rows(tmp_path):
    """D1: what a boot writes is its fetches, and nothing harvested."""
    path = tmp_path / "index.json"
    _index().write(path)
    raw = json.loads(path.read_text())
    assert set(raw) == {"version", "built", "config_hash", "fetches"}
    assert raw["version"] == INDEX_VERSION == 12


@pytest.mark.unit
def test_a_v11_index_keeps_its_fetches_and_ignores_its_plugins(tmp_path):
    """The version on disk at the upgrade: its trees are still good (SRC-37)."""
    read = Index.read(_v11(tmp_path))
    assert read.version == PREVIOUS_VERSION == 11
    assert read.fetches == {FETCH: _fetch_record(built=read.fetches[FETCH].built)}
    assert not hasattr(read, "plugins")


@pytest.mark.unit
@pytest.mark.parametrize("plugins", [[], "x", {"p": {"id": "p"}}, None])
def test_a_v11_plugins_value_of_any_shape_is_ignored(tmp_path, plugins):
    """Never looked at, so no shape of it can fail a boot."""
    assert Index.read(_v11(tmp_path, plugins=plugins)).fetches.keys() == {FETCH}


@pytest.mark.unit
def test_the_fetch_record_shape_is_the_one_v11_wrote(tmp_path):
    """A v11 file is read for its fetches, so a change to them must fail here."""
    assert [f.name for f in fields(FetchRecord)] == FIELDS
    raw = json.loads(_v11(tmp_path).read_text())
    assert list(raw["fetches"][FETCH]) == FIELDS


@pytest.mark.unit
def test_a_missing_or_corrupt_index_reads_as_none(tmp_path):
    missing = tmp_path / "missing.json"
    assert Index.read(missing) is None

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{", encoding="utf-8")
    assert Index.read(corrupt) is None


@pytest.mark.unit
@pytest.mark.parametrize("version", [13, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1])
def test_a_different_version_reads_as_none(tmp_path, version):
    """Older as well as newer, by literal and not only by offset.

    An index written by an earlier release is the one a real upgrade meets, and
    the literals are the shapes before this one (1 on main, 2 part-way through
    the address-space work, 3 before a record carried `skipped`, 4 the
    per-source shape before plugins, 5 before a prompt row carried its name, 6
    before a plugin record carried the globs it was harvested with, 7 while a
    plugin's skills were globs rather than the folders kubed-mcp reads, 8 and 9
    while a prompt was a row of its path, dialect and name, 10 while an agent
    was a row of its path and name, and 11 while the index held plugin rows,
    read for its `fetches` alone, D1):
    lowering `INDEX_VERSION` back to any of them but 11 must fail here, which an
    offset from the current value alone never would.
    """
    path = tmp_path / "index.json"
    _index(version=version).write(path)
    assert Index.read(path) is None


@pytest.mark.unit
def test_a_v4_index_on_disk_is_discarded_whole(tmp_path):
    """The shape a running deployment upgrades from: one `sources` mapping.

    Not a version literal alone -- the file as v4 actually wrote it, so a
    reader that grew lenient about the mapping names would still be caught.
    """
    path = tmp_path / "index.json"
    path.write_text(
        json.dumps(
            {
                "version": 4,
                "built": now(),
                "config_hash": "x",
                "sources": {
                    "flatsource": {
                        "name": "flatsource",
                        "status": "ok",
                        "library": "flatsource",
                        "root": "/skills/flatsource",
                        "fingerprint": {},
                        "built": now(),
                        "error": None,
                        "skills": [],
                        "prompts": [],
                        "files": [],
                        "skill_dirs": [],
                        "skipped": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert Index.read(path) is None


@pytest.mark.unit
@pytest.mark.parametrize("version", [11, 12])
def test_a_wrong_shaped_fetches_mapping_reads_as_none(tmp_path, version):
    path = tmp_path / "index.json"
    raw = {"version": version, "built": now(), "config_hash": "x", "fetches": []}
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert Index.read(path) is None


@pytest.mark.unit
def test_a_previous_version_index_meets_the_hash_check(
    skills_dir, tmp_path_factory, monkeypatch
):
    """Review Focus 2: a v11 file from another config is discarded whole (SRC-36)."""
    from kubed.mcp_kb import KnowledgeBase

    cache = tmp_path_factory.mktemp("cache")
    KnowledgeBase(make_config(skills_dir, libraries=["flatsource"]), cache)
    raw = json.loads((cache / "index.json").read_text())
    raw |= {"version": 11, "plugins": {"flatsource": V11_PLUGIN_ROW}}
    (cache / "index.json").write_text(json.dumps(raw))

    real = SourceLoader.materialise
    seen = []

    def spy(loader, address):
        seen.append(address)
        return real(loader, address)

    monkeypatch.setattr(SourceLoader, "materialise", spy)
    config = make_config(skills_dir)
    KnowledgeBase(config, cache)

    assert sorted(seen) == sorted(key_of(config, n) for n in ("deepsource", "flatsource"))


@pytest.mark.unit
def test_the_write_is_atomic(tmp_path, monkeypatch):
    path = tmp_path / "index.json"
    calls = []
    real_replace = os.replace

    def recording_replace(src, dst):
        calls.append((src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr("kubed.mcp_kb.catalogue.index.os.replace", recording_replace)

    _index().write(path)

    assert len(calls) == 1
    src, dst = calls[0]
    assert Path(src).parent == tmp_path
    assert Path(dst) == path
    assert not Path(src).exists()  # renamed away by os.replace
    assert path.exists()


@pytest.mark.unit
def test_two_writers_in_the_same_directory_do_not_share_a_temp_name(
    tmp_path, monkeypatch
):
    """M4: a fixed `.tmp` sibling races across processes; `mkstemp` cannot."""
    path = tmp_path / "index.json"
    names = []
    real_mkstemp = tempfile.mkstemp

    def recording_mkstemp(*args, **kwargs):
        fd, name = real_mkstemp(*args, **kwargs)
        names.append(name)
        return fd, name

    monkeypatch.setattr("kubed.mcp_kb.catalogue.index.tempfile.mkstemp", recording_mkstemp)

    _index().write(path)
    _index().write(path)

    assert len(names) == 2
    assert names[0] != names[1]


@pytest.mark.unit
def test_config_hash_ignores_key_order_and_changes_with_content(tmp_path):
    forward = tmp_path / "forward.yaml"
    forward.write_text(
        "plugins:\n- name: lib\n  source: file:///skills/lib\n  tags: [x, y]\n"
        "libraries:\n- name: lib\n  plugins: [lib]\n"
    )
    # Same content, top-level keys and per-plugin fields in the opposite order.
    reordered = tmp_path / "reordered.yaml"
    reordered.write_text(
        "libraries:\n- plugins: [lib]\n  name: lib\n"
        "plugins:\n- tags: [x, y]\n  source: file:///skills/lib\n  name: lib\n"
    )
    a = load_config(forward)
    b = load_config(reordered)
    assert config_hash(a) == config_hash(b)

    changed = tmp_path / "changed.yaml"
    changed.write_text(
        "plugins:\n- name: lib\n  source: file:///skills/lib\n  tags: [x, y, z]\n"
        "libraries:\n- name: lib\n  plugins: [lib]\n"
    )
    c = load_config(changed)
    assert config_hash(a) != config_hash(c)


@pytest.mark.unit
def test_config_hash_leaves_the_telemetry_section_out(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("")
    watched = tmp_path / "watched.yaml"
    watched.write_text("telemetry:\n  profiles: http://pyroscope.example.com:4040\n")
    before = json.dumps({"libraries": [], "plugins": [], "sources": []}, sort_keys=True)
    assert config_hash(load_config(empty)) == hashlib.sha256(before.encode()).hexdigest()
    assert config_hash(load_config(watched)) == config_hash(load_config(empty))
