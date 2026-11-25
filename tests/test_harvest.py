"""Finding a plugin's skill folders, prompt files and library files."""

import json
from pathlib import Path

import pytest

from kubed.mcp_kb.catalogue.harvest import (
    library_files,
    patterns,
    prompt_files,
    skill_dirs,
)
from kubed.mcp_kb.config import Config, LibraryConfig
from kubed.mcp_kb.plugins import Globs, fetch_for
from kubed.mcp_kb.plugins.address import parse_address
from kubed.mcp_kb.plugins.marketplace import MARKETPLACE_FILES, read_marketplace


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for rel, body in {
        "skills/grafana-lgtm/loki/SKILL.md": "---\nname: loki\ndescription: d\n---\n",
        "skills/flat/SKILL.md": "---\nname: flat\ndescription: d\n---\n",
        "template/SKILL.md": "---\nname: template\ndescription: d\n---\n",
        ".github/prompts/review.prompt.md": "---\ndescription: r\n---\nbody\n",
        "prompts/grafana/debug-logs.md": "---\ndescription: p\n---\nbody\n",
        "shared/tokens.md": "shared\n",
        "skills/flat/reference.md": "inside a skill\n",
        ".git/SKILL.md": "---\nname: git\ndescription: never\n---\n",
    }.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return tmp_path


def rel(root: Path, paths) -> list[str]:
    return [Path(p).relative_to(root).as_posix() for p in paths]


def _skill(root: Path, where: str) -> None:
    path = root / where
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(f"---\nname: {path.name}\ndescription: d\n---\n")


# -- the rule: skills/<name>/, plus what is declared ---------------------------


@pytest.mark.unit
def test_a_skill_is_a_direct_child_of_skills(tmp_path):
    _skill(tmp_path, "skills/a")
    _skill(tmp_path, "skills/g/b")
    _skill(tmp_path, ".claude/skills/c")
    (tmp_path / "SKILL.md").write_text("---\nname: root\ndescription: d\n---\n")

    assert rel(tmp_path, skill_dirs(tmp_path)) == ["skills/a"]


@pytest.mark.unit
def test_a_declared_folder_is_a_skill_or_holds_skills(tmp_path):
    _skill(tmp_path, "skills/g/b")
    _skill(tmp_path, "skills/g/c")
    _skill(tmp_path, "skills/g/b/deep")

    assert rel(tmp_path, skill_dirs(tmp_path, ["./skills/g/b"])) == ["skills/g/b"]
    assert rel(tmp_path, skill_dirs(tmp_path, ["./skills/g"])) == [
        "skills/g/b",
        "skills/g/c",
    ]
    assert skill_dirs(tmp_path, ["./missing"]) == []


@pytest.mark.unit
def test_the_first_claim_wins(tmp_path):
    _skill(tmp_path, "skills/a")
    _skill(tmp_path, "skills/z")
    _skill(tmp_path, "extra/b")

    found = skill_dirs(tmp_path, ["./extra", "./skills/a", "./skills"])

    assert rel(tmp_path, found) == ["skills/a", "skills/z", "extra/b"]


@pytest.mark.unit
def test_dot_folders_are_skipped(tmp_path):
    _skill(tmp_path, "skills/.hidden")
    _skill(tmp_path, "skills/shown")
    _skill(tmp_path, "extra/.hidden")

    assert rel(tmp_path, skill_dirs(tmp_path, ["./extra"])) == ["skills/shown"]


@pytest.mark.unit
def test_a_declared_folder_under_a_dot_directory_is_read(tmp_path):
    """As kubed-mcp reads it: only a dot *child* is skipped, never a declaration."""
    _skill(tmp_path, ".hid/skills/h")
    _skill(tmp_path, "skills/.x")

    assert rel(tmp_path, skill_dirs(tmp_path, ["./.hid/skills"])) == [".hid/skills/h"]
    assert rel(tmp_path, skill_dirs(tmp_path, ["./skills/.x"])) == ["skills/.x"]


@pytest.mark.unit
def test_a_skills_folder_holding_a_skill_md_is_one_skill(tmp_path):
    """``skills/`` is read like any declared folder: a skill itself, or its parent."""
    _skill(tmp_path, "skills")
    _skill(tmp_path, "skills/a")

    assert rel(tmp_path, skill_dirs(tmp_path)) == ["skills"]


@pytest.mark.unit
def test_a_child_folder_that_is_a_symlink_is_not_a_skill(tmp_path):
    """``os.walk`` does not descend into a linked folder, so kubed-mcp skips it."""
    _skill(tmp_path, "real/target")
    _skill(tmp_path, "skills/plain")
    (tmp_path / "skills" / "linked").symlink_to(tmp_path / "real" / "target")

    assert rel(tmp_path, skill_dirs(tmp_path)) == ["skills/plain"]


@pytest.mark.unit
def test_a_symlinked_folder_read_is_followed_as_a_configmap_mounts_it(tmp_path):
    """``skills -> ..data/skills``: the folder read is ``os.walk``'s top, followed."""
    data = tmp_path / "..2026_09_16_13_15_49.612400444"
    _skill(data, "skills/cm")
    (tmp_path / "..data").symlink_to(data)
    (tmp_path / "skills").symlink_to(tmp_path / "..data" / "skills")

    assert rel(tmp_path, skill_dirs(tmp_path)) == ["skills/cm"]


@pytest.mark.unit
def test_grafana_entries_serve_their_declared_skills(tmp_path):
    """A root entry naming one skill serves that one, and none beside it.

    grafana/skills keeps every skill a folder below ``skills/``, so the scan of
    ``skills/`` finds nothing of its own and each entry is what it declares.
    """
    from kubed.mcp_kb.catalogue.snapshot import build_plugin, with_manifest

    _skill(tmp_path, "skills/grafana-lgtm/loki")
    _skill(tmp_path, "skills/grafana-lgtm/tempo")
    _skill(tmp_path, "template")
    catalog = {
        "name": "grafana-skills",
        "plugins": [
            {
                "name": "grafana-lgtm",
                "source": "./",
                "skills": ["./skills/grafana-lgtm/loki"],
            }
        ],
    }
    where = tmp_path / MARKETPLACE_FILES[0]
    where.parent.mkdir(parents=True, exist_ok=True)
    where.write_text(json.dumps(catalog))
    config = Config.model_validate(
        {"sources": [{"name": "github", "url": "git+https://github.com"}]}
    )
    address = parse_address("github://grafana/skills?ref=abc")
    [plugin] = read_marketplace(
        tmp_path,
        library=LibraryConfig(name="grafana", source="github://grafana/skills"),
        fetch=fetch_for(config, address),
        address=address,
        config=config,
    ).plugins

    completed, globs = with_manifest(plugin, tmp_path)
    record = build_plugin(completed, tmp_path, globs=globs)

    assert record.status == "ok"
    assert [(s.name, s.path) for s in record.skills] == [
        ("loki", tmp_path / "skills/grafana-lgtm/loki")
    ]


@pytest.mark.unit
def test_no_declared_skills_at_all_serves_none(tmp_path):
    """``Globs.skills == ()`` is a plugin's ``skills: []``: the scan is off too."""
    from kubed.mcp_kb.catalogue.snapshot import build_plugin
    from tests.conftest import fake_plugin

    _skill(tmp_path, "skills/a")

    record = build_plugin(fake_plugin("p", tmp_path), tmp_path, globs=Globs(skills=()))

    assert record.skills == ()


# -- containment ---------------------------------------------------------------


@pytest.mark.unit
def test_a_skill_folder_linked_out_of_the_root_is_not_a_skill(tmp_path):
    outside = tmp_path / "elsewhere" / "secret"
    outside.mkdir(parents=True)
    (outside / "SKILL.md").write_text("---\nname: secret\n---\nno")
    root = tmp_path / "src"
    (root / "skills").mkdir(parents=True)
    (root / "skills" / "linked").symlink_to(outside)

    assert skill_dirs(root) == []
    assert skill_dirs(root, ["./skills/linked"]) == []


@pytest.mark.unit
def test_a_symlink_loop_fails_that_link_not_the_harvest(tmp_path, monkeypatch):
    """Before 3.13 `resolve()` raises RuntimeError on a loop, not OSError.

    Forced here so the test means the same thing on every interpreter.
    """
    root = tmp_path / "src"
    good = root / "skills" / "good"
    good.mkdir(parents=True)
    (good / "SKILL.md").write_text("---\nname: good\n---\nbody")
    (root / "skills" / "loop").symlink_to(root / "skills" / "loop")

    real = Path.resolve

    def resolve(self, strict=False):
        if self.name == "loop":
            raise RuntimeError(f"Symlink loop from {self}")
        return real(self, strict)

    monkeypatch.setattr(Path, "resolve", resolve)

    assert [p.name for p in skill_dirs(root)] == ["good"]


@pytest.mark.unit
def test_a_skill_md_symlinked_out_of_the_root_does_not_register(tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "SKILL.md").write_text("---\nname: leak\n---\nno")
    root = tmp_path / "src"
    leak = root / "skills" / "leak"
    leak.mkdir(parents=True)
    (leak / "SKILL.md").symlink_to(outside / "SKILL.md")

    assert skill_dirs(root) == []
    assert skill_dirs(root, ["./skills/leak"]) == []


# -- prompts and library files -------------------------------------------------


def test_an_empty_list_turns_a_kind_off(tree):
    assert prompt_files(tree, Globs(prompts=[])) == []


def test_conventions_find_both_prompt_layouts(tree):
    assert set(rel(tree, prompt_files(tree, Globs()))) == {
        ".github/prompts/review.prompt.md",
        "prompts/grafana/debug-logs.md",
    }


def test_files_are_served_only_when_asked_for(tree):
    dirs = skill_dirs(tree)
    assert library_files(tree, Globs(), dirs) == []
    assert library_files(tree, Globs(files=["shared/**"]), dirs) == ["shared/tokens.md"]


def test_a_file_inside_a_skill_is_never_a_library_file(tree):
    # library_files only excludes files inside a skill dir (per its docstring); a
    # broad "**/*.md" also legitimately matches the fixture's prompt files, and
    # a SKILL.md that is no skill (too deep, or at a folder never scanned).
    dirs = skill_dirs(tree)
    assert library_files(tree, Globs(files=["**/*.md"]), dirs) == [
        ".github/prompts/review.prompt.md",
        "prompts/grafana/debug-logs.md",
        "shared/tokens.md",
        "skills/grafana-lgtm/loki/SKILL.md",
        "template/SKILL.md",
    ]


def test_a_glob_cannot_escape_the_plugin_root(tree, tmp_path):
    # PluginConfig's glob validator already refuses "../**" at construction; a
    # Globs built by hand carries no validation, so this exercises
    # harvest.files()'s own defence-in-depth guard directly.
    (tmp_path.parent / "outside.md").write_text("no\n")
    assert library_files(tree, Globs(files=("../**",)), []) == []


@pytest.mark.unit
def test_a_trailing_globstar_means_everything_underneath(tmp_path):
    """`dir/**` and `dir/**/*` must find the same files on every version.

    Before Python 3.13 a trailing `**` matches directories only, so this test
    reads as a tautology on 3.13+ and as the real thing on 3.11 and 3.12 --
    where, before `patterns` normalised it, the first form found nothing.
    """
    tree = tmp_path / "library"
    (tree / "shared" / "deep").mkdir(parents=True)
    (tree / "shared" / "tokens.md").write_text("t")
    (tree / "shared" / "deep" / "more.md").write_text("m")

    assert library_files(tree, Globs(files=["shared/**"]), []) == library_files(
        tree, Globs(files=["shared/**/*"]), []
    )
    assert library_files(tree, Globs(files=["shared/**"]), []) == [
        "shared/deep/more.md",
        "shared/tokens.md",
    ]


@pytest.mark.unit
def test_a_trailing_globstar_is_normalised_before_it_reaches_glob():
    """The version-independent half of the rule above.

    `pathlib.glob` is what changed in 3.13, so a test that calls it can only
    assert the old behaviour on an old interpreter. This one pins the
    normalisation itself, and fails everywhere if it is dropped.
    """
    assert patterns("files", Globs(files=["shared/**"])) == ("shared/**/*",)
    assert patterns("files", Globs(files=["shared/**/*"])) == ("shared/**/*",)
    assert patterns("files", Globs(files=["shared/*"])) == ("shared/*",)


@pytest.mark.unit
def test_a_configmap_style_symlink_farm_is_harvested(tmp_path):
    """A Kubernetes ConfigMap mount is entirely symlinks through a dot-directory.

    Every key is `key -> ..data/key` and `..data -> ..<timestamp>/`, so judging
    hidden-ness by the RESOLVED path throws the whole mount away — which made
    `file://`, the backend that exists to serve mounted prompts, serve nothing
    at all. Containment is the security property; the target's name is not.
    """
    root = tmp_path / "prompts"
    data = root / "..2026_09_16_13_15_49.612400444"
    data.mkdir(parents=True)
    (data / "debug-logs.md").write_text("---\ndescription: x\n---\nbody")
    (root / "..data").symlink_to(data)
    (root / "debug-logs.md").symlink_to(root / "..data" / "debug-logs.md")

    found = prompt_files(root, Globs(skills=(), prompts=["*.md"]))

    assert [p.name for p in found] == ["debug-logs.md"]
    assert found[0].read_text().endswith("body")


@pytest.mark.unit
def test_a_symlink_out_of_the_root_is_still_refused(tmp_path):
    """The other half: judging the requested path must not weaken containment."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "secret.md").write_text("---\ndescription: x\n---\nno")
    root = tmp_path / "prompts"
    root.mkdir()
    (root / "secret.md").symlink_to(outside / "secret.md")

    assert prompt_files(root, Globs(skills=(), prompts=["*.md"])) == []


@pytest.mark.unit
def test_only_a_whole_trailing_component_is_a_globstar():
    """`logs**` is not a globstar: it matches names beginning with "logs".

    Rewriting it to `logs**/*` would silently change it to mean the descendants
    of those names instead — a different set, and empty for a plain file.
    """
    assert patterns("files", Globs(files=["logs**"])) == ("logs**",)
    assert patterns("files", Globs(files=["a/logs**"])) == ("a/logs**",)
    assert patterns("files", Globs(files=["**"])) == ("**/*",)
    assert patterns("files", Globs(files=["a/**"])) == ("a/**/*",)
