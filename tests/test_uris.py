"""The address space, with no MCP layer involved.

``Catalogue`` is where the grammar and the scoping rules meet, and both halves
of the server are thin projections of it -- so they are tested here directly
rather than only through whichever half happens to be convenient.
"""

from pathlib import Path

import pytest

from kubed.mcp_kb.catalogue.skills import LibraryFiles, SkillIndex
from kubed.mcp_kb.catalogue.uris import (
    Catalogue,
    LibraryText,
    parse,
    resolved,
    uri_for,
)
from kubed.mcp_kb.mcp.scope import Scope
from tests.conftest import build_library_files, load_all_skills, served


def _tags(*groups):
    return Scope(tags=frozenset(frozenset(group) for group in groups))


@pytest.fixture
def catalogue(skills_dir):
    skills = load_all_skills(skills_dir)
    return Catalogue(SkillIndex(skills), build_library_files(skills_dir))


# -- grammar ------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("skill://n8n", ("n8n", "")),
        ("skill://n8n/", ("n8n", "")),
        ("skill://grafana/lgtm/loki/SKILL.md", ("grafana", "lgtm/loki/SKILL.md")),
        ("skill://grafana/lgtm/loki/_manifest", ("grafana", "lgtm/loki/_manifest")),
        ("skill://penpot/shared/a/b.md", ("penpot", "shared/a/b.md")),
    ],
)
def test_parse_splits_head_from_the_rest(uri, expected):
    assert parse(uri) == expected


@pytest.mark.unit
@pytest.mark.parametrize("uri", ["", "skill://", "file://x/y", "grafana/loki", "://x"])
def test_parse_rejects_anything_that_is_not_an_address(uri):
    assert parse(uri) is None


@pytest.mark.unit
def test_parse_does_not_decode_percent_escapes(catalogue):
    """Decoding here would be one more way for %2e%2e to become ``..``."""
    assert parse("skill://p/%2e%2e/x")[1] == "%2e%2e/x"
    assert catalogue.read("skill://deepsource/%2e%2e/README.md") is None


# -- listing ------------------------------------------------------------------


@pytest.mark.unit
def test_entries_are_files_md_rows_not_indexes_or_skills(catalogue):
    """kb lists its own ``_files.md`` alone: the skills' rows are the plugin
    layer's, and the indexes read without being listed."""
    uris = [e.uri for e in catalogue.entries()]
    assert uris == ["skill://deepsource/_files.md"]


@pytest.mark.unit
def test_entries_carry_the_four_resource_fields(catalogue):
    """The tool mirror publishes these rows verbatim, so the shape is the API."""
    row = catalogue.entries()[0].as_dict()
    assert set(row) == {"uri", "name", "description", "mimeType"}


@pytest.mark.unit
def test_a_library_with_shared_material_advertises_it(catalogue):
    uris = [e.uri for e in catalogue.entries()]
    assert "skill://deepsource/_files.md" in uris
    # flatsource ships only a dotfile, which is not readable material.
    assert "skill://flatsource/_files.md" not in uris


@pytest.mark.unit
def test_entries_honour_the_pin(catalogue):
    assert [e.uri for e in catalogue.entries(Scope("deepsource"))] == [
        "skill://deepsource/_files.md"
    ]
    assert catalogue.entries(Scope("flatsource")) == []


@pytest.mark.unit
def test_a_tag_scope_lists_the_files_of_the_libraries_carrying_it(catalogue):
    """A tag narrows which plugins count, so a library's ``_files.md`` is listed
    when a plugin carrying the tag has a library file in scope."""
    uris = [e.uri for e in catalogue.entries(_tags({"deep"}))]
    assert uris == ["skill://deepsource/_files.md"]
    assert catalogue.entries(_tags({"nope"})) == []


@pytest.mark.unit
def test_a_folder_name_selects_nothing(catalogue):
    """A scope names a library and nothing below it: neither a bare folder
    name nor a library/folder path is one."""
    assert catalogue.entries(Scope("plugin-a")) == []
    assert catalogue.entries(Scope("deepsource/plugin-a")) == []


# -- reading ------------------------------------------------------------------


@pytest.mark.unit
def test_reading_an_index_lists_skills_as_uris(catalogue):
    """An index teaches the grammar for the next call, so it emits addresses."""
    body = catalogue.read("skill://flatsource/_index.md")
    assert "skill://flatsource/alpha/SKILL.md: First skill." in body
    assert "skill://flatsource/beta/SKILL.md: Second skill." in body


@pytest.mark.unit
def test_reading_a_folder_index_excludes_the_sibling_folder(catalogue):
    body = catalogue.read("skill://deepsource/plugin-a/_index.md")
    assert "gamma" in body and "delta" not in body


@pytest.mark.unit
def test_a_skill_root_is_a_directory_not_its_instructions(catalogue):
    """Only `.../SKILL.md` is the instructions; the bare skill path serves nothing."""
    assert catalogue.read("skill://flatsource/alpha") is None
    assert "First skill." in served(catalogue, "skill://flatsource/alpha/SKILL.md")


def _skill_at(catalogue, address):
    return next(s for s in catalogue.visible_skills() if s.address == address)


@pytest.mark.unit
def test_a_skills_files_are_what_a_read_serves(catalogue):
    """What the skill provider builds a skill, and its ``_manifest``, from."""
    files = catalogue.skill_files(_skill_at(catalogue, "flatsource/alpha"))
    assert list(files) == ["SKILL.md"]
    assert files["SKILL.md"] == served(catalogue, "skill://flatsource/alpha/SKILL.md")


@pytest.mark.unit
def test_a_skills_files_leave_out_a_symlink_out_of_it(catalogue, skills_dir, tmp_path):
    """A symlink out of the skill root must not leak the target's path or bytes."""
    secret = tmp_path / "secret.txt"
    secret.write_text("shh\n")
    (skills_dir / "flatsource" / "alpha" / "leak.md").symlink_to(secret)

    files = catalogue.skill_files(_skill_at(catalogue, "flatsource/alpha"))
    assert "leak.md" not in files


@pytest.mark.unit
def test_a_skills_files_are_only_those_the_harvest_would_keep(catalogue, skills_dir):
    """A client syncing a skill to disk goes shopping from them, so they name
    what the skill ships and not an editor's swap file."""
    (skills_dir / "flatsource" / "alpha" / ".tmp-half").write_text("not a file\n")

    files = catalogue.skill_files(_skill_at(catalogue, "flatsource/alpha"))

    assert ".tmp-half" not in files


@pytest.mark.unit
def test_a_skills_own_files_are_not_read_beside_its_provider(catalogue):
    """``read`` is the provider registered after the skills one (SKL-58)."""
    assert catalogue.read("skill://flatsource/alpha/SKILL.md") is None
    assert catalogue.read("skill://flatsource/alpha/_manifest") is None
    assert catalogue.read("skill://flatsource/_index.md")


@pytest.mark.unit
def test_a_directory_is_its_direct_children_under_the_scope(catalogue):
    """MD-57 G1: what ``resources/directory/read`` and ``_index.json`` list."""
    rows = [e.as_dict() for e in catalogue.directory("skill://deepsource")]
    assert [(r["uri"], r["mimeType"]) for r in rows] == [
        ("skill://deepsource/README.md", "text/markdown"),
        ("skill://deepsource/plugin-a", "inode/directory"),
        ("skill://deepsource/plugin-b", "inode/directory"),
        ("skill://deepsource/shared", "inode/directory"),
    ]
    folder = catalogue.directory("skill://deepsource/plugin-a")
    assert [(e.uri, e.description) for e in folder] == [
        ("skill://deepsource/plugin-a/gamma", "Third skill.")
    ]
    shared = catalogue.directory("skill://deepsource/shared")
    assert [e.uri for e in shared] == [
        "skill://deepsource/shared/guide.md",
        "skill://deepsource/shared/nested",
    ]
    # A skill's own directory is its provider's; out of scope is absent.
    assert catalogue.directory("skill://deepsource/plugin-a/gamma") is None
    assert catalogue.directory("skill://deepsource", Scope("flatsource")) is None
    assert catalogue.directory("skill://nope") is None


@pytest.mark.unit
def test_library_files_index_and_one_of_its_files(catalogue):
    index = catalogue.read("skill://deepsource/_files.md")
    assert "skill://deepsource/shared/guide.md" in index
    assert catalogue.read("skill://deepsource/shared/guide.md") == "shared guidance\n"
    assert catalogue.read("skill://deepsource/shared/nested/schema.json") == "{}\n"


@pytest.mark.unit
def test_skill_names_collide_across_libraries_and_both_survive(skills_dir):
    """The library in the URI is what makes this reachable at all.

    SkillsDirectoryProvider keys on the folder name and drops the loser
    entirely; qualifying the address is the fix, so it is pinned by a test.
    """
    for library in ("flatsource", "deepsource"):
        _write_skill(skills_dir, library, "twin", f"from {library}")
    skills = load_all_skills(skills_dir)
    cat = Catalogue(SkillIndex(skills), build_library_files(skills_dir))
    assert "from flatsource" in served(cat, "skill://flatsource/twin/SKILL.md")
    assert "from deepsource" in served(cat, "skill://deepsource/twin/SKILL.md")


def _write_skill(root, library, name, description):
    path = root / library / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nBody.\n"
    )


# -- absence and scope --------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "uri",
    [
        "skill://nope",
        "skill://nope/_index.md",
        "skill://flatsource/nope",
        "skill://flatsource/nope/SKILL.md",
        "skill://flatsource/_files.md",
        "skill://deepsource/plugin-c/_index.md",
        "skill://flatsource/alpha/nope.md",
        "skill://deepsource/shared/nope.md",
        "not-a-uri",
    ],
)
def test_absent_reads_are_none_not_errors(catalogue, uri):
    assert catalogue.read(uri) is None


@pytest.mark.unit
def test_traversal_cannot_walk_out_of_a_skill(catalogue):
    """`..` resolves to another address in the library, never to the disk.

    `gamma/../../README.md` is the address `skill://deepsource/README.md`, a
    library file this source serves anyway; what it can never be is a path
    walked out of the skill directory, and past the library it clamps.
    """
    assert catalogue.read(
        "skill://deepsource/plugin-a/gamma/../../README.md"
    ) == catalogue.read("skill://deepsource/README.md")
    assert (
        catalogue.read("skill://deepsource/plugin-a/gamma/../../../etc/passwd")
        is None
    )


@pytest.mark.unit
def test_a_skill_file_is_not_reachable_as_a_library_file(catalogue):
    """The two spaces must not overlap, or skill scoping could be bypassed."""
    assert served(catalogue, "skill://deepsource/plugin-a/gamma/SKILL.md") is not None
    pinned = Scope("deepsource", categories=frozenset({"nope"}))
    assert served(catalogue, "skill://deepsource/plugin-a/gamma/SKILL.md", pinned) is None


@pytest.mark.unit
def test_the_pin_hides_another_library_entirely(catalogue):
    """Out of scope is indistinguishable from absent, on purpose."""
    gamma = "skill://deepsource/plugin-a/gamma/SKILL.md"
    flat = Scope("flatsource")
    assert served(catalogue, gamma) is not None
    assert served(catalogue, gamma, scope=flat) is None
    assert catalogue.read("skill://deepsource/_index.md", scope=flat) is None
    assert catalogue.read("skill://deepsource/plugin-a/_index.md", scope=flat) is None


@pytest.mark.unit
def test_a_tag_scope_reaches_the_shared_material_of_the_plugin_carrying_it(catalogue):
    """Shared files come from the plugin whose skills cite them, and are in
    scope exactly when that plugin is."""
    guide = "skill://deepsource/shared/guide.md"
    assert catalogue.read(guide, scope=_tags({"deep"})) == "shared guidance\n"
    assert catalogue.read(guide, scope=_tags({"flat"})) is None
    assert catalogue.read("skill://deepsource/_files.md", scope=_tags({"flat"})) is None


@pytest.mark.unit
def test_the_pin_blocks_shared_material_of_another_library(catalogue):
    assert (
        catalogue.read("skill://deepsource/shared/guide.md", scope=Scope("flatsource"))
        is None
    )
    assert (
        catalogue.read("skill://deepsource/_files.md", scope=Scope("flatsource"))
        is None
    )


@pytest.mark.unit
def test_uri_for_is_the_address_the_catalogue_answers(catalogue, skills_dir):
    skill = next(s for s in load_all_skills(skills_dir) if s.name == "gamma")
    assert uri_for(skill) == "skill://deepsource/plugin-a/gamma/SKILL.md"
    assert served(catalogue, uri_for(skill)) is not None


@pytest.mark.unit
def test_mime_types_follow_the_content(catalogue):
    assert catalogue.mime("skill://deepsource/_index.md") == "text/markdown"
    assert (
        catalogue.mime("skill://deepsource/shared/nested/schema.json")
        == "application/json"
    )


# -- tags -----------------------------------------------------------------------


@pytest.mark.unit
def test_a_files_row_is_tagged_with_its_library(catalogue):
    """A ``_files.md`` row is tagged with its own library and "index", sorted."""
    assert catalogue.entries()[0].tags == ("deepsource", "index")


# -- library text -------------------------------------------------------------


def _skill(library, folder, name, tags=()):
    from kubed.mcp_kb.catalogue.skills import Skill

    return Skill(
        name=name,
        library=library,
        folder=folder,
        description=f"{name}.",
        path=Path("/nowhere") / name,
        plugin=library,
        root=Path("/nowhere"),
        tags=frozenset(tags),
    )


@pytest.mark.unit
def test_plugin_skill_dirs_maps_one_plugin_in_one_library():
    """What ``${CLAUDE_PLUGIN_ROOT}/<dir>`` renders as: the plugin's own skills,
    in this library, keyed by their directory below the plugin root."""
    from kubed.mcp_kb.catalogue.skills import Skill

    def skill(library, plugin, rel, name, folder="", root=Path("/r")):
        return Skill(
            name=name,
            library=library,
            folder=folder,
            description=f"{name}.",
            path=root / rel,
            plugin=plugin,
            root=root,
            tags=frozenset({"t"}),
        )

    skills = [
        skill("a", "p", "skills/writing", "writing"),
        skill("a", "p", "skills/writing/drafts", "drafts", folder="writing"),
        skill("a", "q", "skills/ops", "ops"),
        skill("b", "p", "skills/writing", "writing"),
        skill("c", "solo", "", "solo", root=Path("/s")),
    ]
    cat = Catalogue(SkillIndex(skills), LibraryFiles())
    assert cat.plugin_skill_dirs("a", "p") == {
        "skills/writing": "skill://a/writing",
        "skills/writing/drafts": "skill://a/writing/drafts",
    }
    assert cat.plugin_skill_dirs("b", "p") == {"skills/writing": "skill://b/writing"}
    assert cat.plugin_skill_dirs("c", "solo") == {"": "skill://c/solo"}
    assert cat.plugin_skill_dirs("a", "nobody") == {}
    assert cat.plugin_skill_dirs("a", "p", _tags({"other"})) == {}


@pytest.mark.unit
def test_plugin_skill_dirs_accepts_a_symlinked_root_and_drops_a_stray_skill(
    tmp_path,
):
    """A harvest resolves the root it walks, so a skill's path may sit under the
    resolved spelling of a root that is a symlink; one under neither is left out."""
    from kubed.mcp_kb.catalogue.skills import Skill

    real = tmp_path / "real"
    (real / "skills" / "writing").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    def skill(name, path):
        return Skill(
            name=name,
            library="a",
            folder="",
            description=f"{name}.",
            path=path,
            plugin="p",
            root=link,
            tags=frozenset({"t"}),
        )

    cat = Catalogue(
        SkillIndex(
            [
                skill("writing", real.resolve() / "skills" / "writing"),
                skill("whole", real.resolve()),
                skill("stray", tmp_path / "elsewhere" / "stray"),
            ]
        ),
        LibraryFiles(),
    )
    assert cat.plugin_skill_dirs("a", "p") == {
        "skills/writing": "skill://a/writing",
        "": "skill://a/whole",
    }


@pytest.mark.unit
def test_selected_follows_scope_and_constructor_order():
    skills = [_skill("a", "", "one", {"x"}), _skill("b", "", "two", {"y"})]
    cat = Catalogue(
        SkillIndex(skills),
        LibraryFiles(),
        libraries=[LibraryText("b"), LibraryText("a"), LibraryText("empty")],
    )
    assert [t.name for t in cat.selected()] == ["b", "a"]
    assert [t.name for t in cat.selected(_tags({"x"}))] == ["a"]


@pytest.mark.unit
def test_selected_gives_an_untexted_library_a_bare_text_in_name_order():
    skills = [_skill("z", "", "one"), _skill("m", "", "two"), _skill("k", "", "3")]
    cat = Catalogue(
        SkillIndex(skills), LibraryFiles(), libraries=[LibraryText("k", "D.")]
    )
    assert cat.selected() == [LibraryText("k", "D."), LibraryText("m"), LibraryText("z")]


@pytest.mark.unit
def test_skill_paths_are_paths_under_the_library():
    skills = [_skill("lib", "x", "loki", {"t"}), _skill("lib", "y", "loki")]
    cat = Catalogue(SkillIndex(skills), LibraryFiles())
    assert cat.skill_paths("lib") == ["x/loki", "y/loki"]
    assert cat.skill_paths("lib", _tags({"t"})) == ["x/loki"]


@pytest.mark.unit
def test_library_index_opens_with_its_text():
    skills = [_skill("lib", "", "a"), _skill("lib", "f", "b")]
    plain = Catalogue(SkillIndex(skills), LibraryFiles())
    texted = Catalogue(
        SkillIndex(skills),
        LibraryFiles(),
        libraries=[LibraryText("lib", "D.", "N.")],
    )
    before = plain.read("skill://lib/_index.md")
    after = texted.read("skill://lib/_index.md")
    head, rest = before.split("\n\n", 1)
    assert after == f"{head}\n\nD.\nN.\n\n{rest}"
    assert after.startswith("# lib — 2 skills\n\nD.\nN.\n\n")
    assert texted.read("skill://lib/f/_index.md") == plain.read("skill://lib/f/_index.md")
    bare = Catalogue(SkillIndex(skills), LibraryFiles(), libraries=[LibraryText("lib")])
    assert bare.read("skill://lib/_index.md") == before


def test_resolved_names_the_address_parse_reads():
    assert resolved("skill://grafana/a/../b/SKILL.md") == "skill://grafana/b/SKILL.md"
    assert resolved("skill://grafana/") == "skill://grafana"
    assert resolved("skill://grafana/../../x") == "skill://grafana/x"
    assert resolved("kb+skill://grafana/x") is None
    assert resolved("skill://") is None
