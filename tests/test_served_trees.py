"""``ServedTrees``: kubed-mcp's loader over the trees kb is serving.

It is a memo of what ``KnowledgeBase`` holds and never a fetcher, so these
tests count the clones a read makes (none) and break the remote to show the
last good tree still answers.
"""

import shutil
import threading
from pathlib import Path

import pytest
from kubed.mcp import QuickMCP

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.app import create_app
from kubed.mcp_kb.config import Config
from kubed.mcp_kb.sources import GitLoader, ServedTrees, SourceError, plugin_root
from tests.test_git_source import _config, origin  # noqa: F401 - a fixture


def _loader(knowledge_base):
    return ServedTrees(("file", "lab"), knowledge_base.served_tree)


def _file_config(tree):
    return Config.model_validate(
        {
            "plugins": [
                {
                    "name": "library",
                    "source": f"file://{tree}",
                    "skills": ["skills/*/SKILL.md"],
                }
            ],
            "libraries": [{"name": "library", "plugins": ["library"]}],
        }
    )


def _skill_tree(tmp_path):
    tree = tmp_path / "plugin"
    (tree / "skills" / "x").mkdir(parents=True)
    (tree / "skills" / "x" / "SKILL.md").write_text(
        "---\nname: x\ndescription: A skill.\n---\n\nbody\n"
    )
    return tree


@pytest.mark.unit
def test_it_answers_the_tree_kb_serves(origin, tmp_path, monkeypatch):  # noqa: F811
    git = KnowledgeBase(_config(origin, ref="main", subdir="docs"), tmp_path / "c")
    plain = _skill_tree(tmp_path)
    local = KnowledgeBase(_file_config(plain), tmp_path / "d")
    calls = []
    real = GitLoader.build
    monkeypatch.setattr(
        GitLoader, "build", staticmethod(lambda *a: calls.append(a) or real(*a))
    )

    key = f"lab://{origin.path.name}?ref=main"
    record = git._fetches[key]
    assert _loader(git).materialise(f"{key.split('?')[0]}//docs?ref=main") == (
        plugin_root(Path(record.root), "docs")
    )
    file_record = local._fetches[f"file://{plain}"]
    assert _loader(local).materialise(f"file://{plain}") == plugin_root(
        Path(file_record.root), ""
    )
    assert calls == []


@pytest.mark.unit
def test_it_serves_the_last_good_tree(origin, tmp_path):  # noqa: F811
    knowledge_base = KnowledgeBase(_config(origin, ref="main"), tmp_path / "c")
    key = f"lab://{origin.path.name}?ref=main"
    old = knowledge_base._fetches[key].root

    shutil.move(origin.path, tmp_path / "gone")
    knowledge_base.refresh(force=True)

    assert knowledge_base._fetches[key].status == "stale"
    assert str(_loader(knowledge_base).materialise(key)) == old


@pytest.mark.unit
def test_an_unknown_fetch_is_not_materialised(tmp_path):
    knowledge_base = KnowledgeBase(_file_config(_skill_tree(tmp_path)), tmp_path / "c")

    with pytest.raises(SourceError, match="is not materialised") as raised:
        _loader(knowledge_base).materialise("file:///nowhere")
    assert "file:///nowhere" in str(raised.value)
    assert str(tmp_path) not in str(raised.value)


@pytest.mark.unit
def test_a_subdir_link_out_of_the_tree_is_refused(tmp_path):
    plain = _skill_tree(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (plain / "link").symlink_to(outside)
    knowledge_base = KnowledgeBase(_file_config(plain), tmp_path / "c")

    with pytest.raises(SourceError, match="link is not a directory in") as raised:
        _loader(knowledge_base).materialise(f"file://{plain}//link")
    assert str(outside) not in str(raised.value)


@pytest.mark.unit
def test_it_replaces_local_loader(tmp_path):
    """``create_app`` registers it for ``file`` and every declared source.

    ``add_plugin`` itself is refused while kb has tools of its own that rc2
    serves (DLV-7), so this asks the plugin layer which loader answers.
    """
    plain = _skill_tree(tmp_path)
    knowledge_base = KnowledgeBase(_file_config(plain), tmp_path / "c")
    mcp = create_app(knowledge_base)

    loader = mcp._plugins._loader_for(f"file://{plain}")

    assert isinstance(loader, ServedTrees)
    record = knowledge_base._fetches[f"file://{plain}"]
    assert loader.materialise(f"file://{plain}") == plugin_root(Path(record.root), "")
    with pytest.raises(ValueError, match="file"):
        mcp.add_loader(ServedTrees(("file",), knowledge_base.served_tree))


@pytest.mark.unit
def test_a_fetch_that_is_not_serving_is_not_materialised(tmp_path):
    plain = _skill_tree(tmp_path)
    knowledge_base = KnowledgeBase(_file_config(plain), tmp_path / "c")
    key = f"file://{plain}"
    shutil.rmtree(knowledge_base._fetches[key].root)

    with pytest.raises(SourceError, match="is not materialised"):
        _loader(knowledge_base).materialise(key)


@pytest.mark.unit
def test_it_answers_while_the_publisher_holds_the_lock(tmp_path):
    """``refresh`` publishes under ``_lock``, and the plugin layer asks from there."""
    plain = _skill_tree(tmp_path)
    knowledge_base = KnowledgeBase(_file_config(plain), tmp_path / "c")
    got = []
    worker = threading.Thread(
        target=lambda: got.append(
            _loader(knowledge_base).materialise(f"file://{plain}")
        ),
        daemon=True,
    )
    with knowledge_base._lock:
        worker.start()
        worker.join(5)

    assert not worker.is_alive(), "served_tree waited on the lock"
    record = knowledge_base._fetches[f"file://{plain}"]
    assert got == [plugin_root(Path(record.root), "")]


@pytest.mark.unit
def test_kubed_mcp_drives_it_end_to_end(tmp_path):
    plain = _skill_tree(tmp_path)
    knowledge_base = KnowledgeBase(_file_config(plain), tmp_path / "c")
    mcp = QuickMCP("t")
    mcp.add_loader(ServedTrees(("file",), knowledge_base.served_tree))

    plugin = mcp.add_plugin(f"file://{plain}")

    record = knowledge_base._fetches[f"file://{plain}"]
    assert plugin.root == plugin_root(Path(record.root), "")
