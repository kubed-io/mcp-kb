"""Turning a source's include globs into skill dirs, prompt files and pack files."""

from pathlib import Path

import pytest

from mcp_school.config import Include
from mcp_school.harvest import group_of, pack_files, patterns, prompt_files, skill_dirs


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for rel, body in {
        "skills/grafana-lgtm/loki/SKILL.md": "---\nname: loki\ndescription: d\n---\n",
        "skills/flat/SKILL.md": "---\nname: flat\ndescription: d\n---\n",
        "template/SKILL.md": "---\nname: template\ndescription: d\n---\n",
        ".github/skills/gh/SKILL.md": "---\nname: gh\ndescription: d\n---\n",
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


def rel(root: Path, paths) -> set[str]:
    return {Path(p).relative_to(root).as_posix() for p in paths}


def test_conventions_find_nested_skills_and_never_a_root_template(tree):
    assert rel(tree, skill_dirs(tree, Include())) == {
        "skills/grafana-lgtm/loki",
        "skills/flat",
        ".github/skills/gh",
    }


def test_a_dot_directory_is_skipped_unless_it_is_a_convention(tree):
    found = rel(tree, skill_dirs(tree, Include(skills=["**/SKILL.md"])))
    assert ".github/skills/gh" in found
    assert ".git" not in found


def test_setting_a_kind_replaces_its_defaults(tree):
    assert rel(tree, skill_dirs(tree, Include(skills=["template/SKILL.md"]))) == {
        "template"
    }


def test_an_empty_list_turns_a_kind_off(tree):
    assert prompt_files(tree, Include(prompts=[])) == []


def test_conventions_find_both_prompt_layouts(tree):
    assert rel(tree, prompt_files(tree, Include())) == {
        ".github/prompts/review.prompt.md",
        "prompts/grafana/debug-logs.md",
    }


def test_files_are_served_only_when_asked_for(tree):
    dirs = skill_dirs(tree, Include())
    assert pack_files(tree, Include(), dirs) == []
    assert pack_files(tree, Include(files=["shared/**"]), dirs) == ["shared/tokens.md"]


def test_a_file_inside_a_skill_is_never_a_pack_file(tree):
    # pack_files only excludes files inside a skill dir (per its docstring); a
    # broad "**/*.md" also legitimately matches the fixture's prompt files,
    # which live outside every skill dir returned by skill_dirs().
    dirs = skill_dirs(tree, Include())
    assert pack_files(tree, Include(files=["**/*.md"]), dirs) == [
        ".github/prompts/review.prompt.md",
        "prompts/grafana/debug-logs.md",
        "shared/tokens.md",
        "template/SKILL.md",
    ]


def test_a_glob_cannot_escape_the_source(tree, tmp_path):
    # config.py's Include validator already refuses "../**" at construction;
    # model_construct bypasses it so this test exercises harvest.files()'s own
    # defence-in-depth guard directly, independent of that outer validation.
    (tmp_path.parent / "outside.md").write_text("no\n")
    include = Include.model_construct(files=["../**"])
    assert pack_files(tree, include, []) == []


def test_the_group_is_the_containing_directory_unless_that_is_a_skill_root(tree):
    assert group_of(tree / "skills/grafana-lgtm/loki", tree) == "grafana-lgtm"
    assert group_of(tree / "skills/flat", tree) is None
    assert group_of(tree / ".github/skills/gh", tree) is None
    assert group_of(tree / "template", tree) is None


@pytest.mark.unit
def test_a_trailing_globstar_means_everything_underneath(tmp_path):
    """`dir/**` and `dir/**/*` must find the same files on every version.

    Before Python 3.13 a trailing `**` matches directories only, so this test
    reads as a tautology on 3.13+ and as the real thing on 3.11 and 3.12 --
    where, before `patterns` normalised it, the first form found nothing.
    """
    tree = tmp_path / "pack"
    (tree / "shared" / "deep").mkdir(parents=True)
    (tree / "shared" / "tokens.md").write_text("t")
    (tree / "shared" / "deep" / "more.md").write_text("m")

    assert pack_files(tree, Include(files=["shared/**"]), []) == pack_files(
        tree, Include(files=["shared/**/*"]), []
    )
    assert pack_files(tree, Include(files=["shared/**"]), []) == [
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
    assert patterns("files", Include(files=["shared/**"])) == ("shared/**/*",)
    assert patterns("files", Include(files=["shared/**/*"])) == ("shared/**/*",)
    assert patterns("files", Include(files=["shared/*"])) == ("shared/*",)
    assert patterns("skills", Include(skills=["skills/*/SKILL.md"])) == (
        "skills/*/SKILL.md",
    )


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

    found = prompt_files(root, Include(skills=[], prompts=["*.md"]))

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

    assert prompt_files(root, Include(skills=[], prompts=["*.md"])) == []
