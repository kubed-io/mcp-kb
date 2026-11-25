"""Prompts: the files, how they render, and who may see them."""

import logging

import pytest
from fastmcp import Client

from kubed.mcp_kb import KnowledgeBase
from kubed.mcp_kb.catalogue import harvest
from kubed.mcp_kb.catalogue.prompts import prompt_name
from kubed.mcp_kb.config import Config
from kubed.mcp_kb.mcp.scope import Scope
from kubed.mcp_kb.plugins import Globs
from tests.conftest import make_config, read_prompt, server_of

pytestmark = pytest.mark.unit


def text(result):
    return result.messages[0].content.text


def _served(config: Config, cache) -> KnowledgeBase:
    """A knowledge base with its plugin set published, which reads the prompts."""
    knowledge_base = KnowledgeBase(config, cache)
    server_of(knowledge_base)
    return knowledge_base


def _kit(tmp_path, files: dict[str, str]) -> KnowledgeBase:
    """One declared plugin ``kit`` in library ``kit``, over ``files``, served."""
    root = tmp_path / "plugin"
    for rel, body in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body)
    config = Config.model_validate(
        {
            "plugins": [{"name": "kit", "source": f"file://{root}"}],
            "libraries": [{"name": "kit", "plugins": ["kit"]}],
        }
    )
    return _served(config, tmp_path / "cache")


# -- loading -------------------------------------------------------------------


def test_the_name_is_library_qualified(prompts_dir, tmp_path):
    """A file outside a library folder is not a prompt at all."""
    kb = _served(make_config(prompts_dir=prompts_dir), tmp_path / "cache")
    assert {p.name for p in kb.prompts} == {"flatsource_hello", "deepsource_check"}


def test_libraries_hard_scope_the_prompts(prompts_dir, tmp_path):
    config = make_config(prompts_dir=prompts_dir, libraries=["flatsource"])
    kb = _served(config, tmp_path / "cache")
    assert {p.name for p in kb.prompts} == {"flatsource_hello"}


def test_an_undeclared_placeholder_is_skipped_loudly(tmp_path, caplog):
    """Rendered blank, a typo reads fine and asks the model for the wrong thing."""
    typo = "---\ndescription: typo\narguments:\n- name: name\n---\nHi {{ nmae }}\n"
    with caplog.at_level(logging.WARNING):
        kb = _kit(tmp_path, {"prompts/typo.md": typo})
    assert kb.prompts == ()
    [row] = kb.status["plugins"]["kit"]["skipped"]
    assert row["path"] == "prompts/typo.md" and "nmae" in row["reason"]
    assert "nmae" in caplog.text


def test_a_required_argument_cannot_have_a_default(tmp_path):
    path = tmp_path / "bad.md"
    path.write_text(
        "---\narguments:\n- name: who\n  required: true\n  default: x\n---\n{{ who }}\n"
    )
    with pytest.raises(ValueError, match="cannot have a default"):
        read_prompt(path, "flatsource")


def test_a_prompt_carries_its_plugins_labels_and_nothing_implicit(tmp_path):
    """No library name, plugin name or "prompt" smuggled in as a tag."""
    path = tmp_path / "hello.md"
    path.write_text("---\ndescription: hi\n---\nHi.\n")
    bare = read_prompt(path, "flatsource")
    assert bare.tags == set()
    labelled = read_prompt(
        path, "flatsource", plugin="p", tags=["ops", "lgtm"], category="obs"
    )
    assert labelled.tags == {"ops", "lgtm"}
    assert labelled.category == "obs"
    assert labelled.plugin == "p"


@pytest.mark.parametrize(
    ("rel", "dirs", "name"),
    [
        ("commands/db/migrate.md", (), "db_migrate"),
        ("commands/top.md", (), "top"),
        (".claude/commands/a/b.md", (), "a_b"),
        ("cmds/a/b.md", ("cmds",), "a_b"),
        ("cmds/a/b.md", ("./cmds/",), "a_b"),
        ("cmds/deep/a/b.md", ("cmds", "cmds/deep"), "a_b"),
        ("a/b.md", (".",), "a_b"),
        ("prompts/sub/debug.md", (), "debug"),
        ("prompts/sub/x.prompt.md", (), "x"),
        ("commandsx/a.md", (), "a"),
    ],
)
def test_a_prompts_name_is_decided_where_it_was_found(tmp_path, rel, dirs, name):
    assert prompt_name(tmp_path / rel, tmp_path, dirs) == name


def test_a_resolved_path_under_an_unresolved_root_is_still_below_it(tmp_path):
    real = tmp_path / "real"
    (real / "commands" / "db").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real)
    path = (link / "commands" / "db" / "x.md").resolve()
    assert prompt_name(path, link, ()) == "db_x"


def test_a_missing_directory_is_no_prompts(tmp_path):
    """Harvest yields no files for a missing source, so the layer reads none."""
    files = harvest.prompt_files(tmp_path / "nope", Globs())
    assert files == []
    assert harvest.command_entries([], ()) == ()


# -- splitting frontmatter from the body ---------------------------------------


def test_a_body_that_recurs_in_the_frontmatter_is_sliced_by_position(tmp_path):
    """``str.index`` finds the body's first occurrence anywhere, including inside
    the frontmatter block when the description happens to repeat the body text."""
    path = tmp_path / "echo.md"
    path.write_text("---\ndescription: body\n---\nbody\n")
    prompt = read_prompt(path, "flatsource")
    assert prompt.template == "body\n"


def test_an_unterminated_frontmatter_block_is_refused(tmp_path):
    path = tmp_path / "broken.md"
    path.write_text("---\ndescription: d\nbody never closed\n")
    with pytest.raises(ValueError, match="no YAML frontmatter"):
        read_prompt(path, "flatsource")


def test_a_body_starting_with_a_dashed_rule_still_parses(tmp_path):
    """A real frontmatter block, followed by a body that itself starts with
    ``---``, must not be mistaken for "no frontmatter at all"."""
    path = tmp_path / "rule.md"
    path.write_text("---\ndescription: d\n---\n---\nnot frontmatter, just text\n")
    prompt = read_prompt(path, "flatsource")
    assert prompt.template == "---\nnot frontmatter, just text\n"


# -- over MCP ------------------------------------------------------------------


async def test_a_client_sees_the_prompt_and_its_arguments(skills_dir, prompts_dir):
    server = KnowledgeBase(make_config(skills_dir, prompts_dir), skills_dir / "_cache")
    async with Client(server_of(server)) as client:
        listed = {p.name: p for p in await client.list_prompts()}
    hello = listed["flatsource_hello"]
    assert hello.description == "Say hello."
    assert [(a.name, a.required) for a in hello.arguments] == [
        ("who", True),
        ("greeting", False),
    ]


async def test_rendering_fills_arguments_and_defaults(skills_dir, prompts_dir):
    server = KnowledgeBase(make_config(skills_dir, prompts_dir), skills_dir / "_cache")
    async with Client(server_of(server)) as client:
        given = await client.get_prompt(
            "flatsource_hello", {"who": "Dr K", "greeting": "Hi"}
        )
        defaulted = await client.get_prompt("flatsource_hello", {"who": "Dr K"})
        blank = await client.get_prompt(
            "flatsource_hello", {"who": "Dr K", "greeting": ""}
        )
    assert text(given) == "Hi, Dr K.\n"
    assert text(defaulted) == "Hello, Dr K.\n"
    # A picker sends a field left empty as "", which must not beat the default.
    assert text(blank) == "Hello, Dr K.\n"


async def test_a_missing_required_argument_is_refused(skills_dir, prompts_dir, caplog):
    """Invalid params naming the argument -- the caller's mistake -- and not the
    internal error and ERROR traceback FastMCP gives any other render failure."""
    from kubed.mcp.protocol import INVALID_PARAMS, MCPError

    server = KnowledgeBase(make_config(skills_dir, prompts_dir), skills_dir / "_cache")
    server_of(server)  # publishing logs what the plugin layer notes; not a call
    caplog.clear()
    with caplog.at_level(logging.INFO):
        async with Client(server_of(server)) as client:
            with pytest.raises(MCPError) as caught:
                await client.get_prompt("flatsource_hello", {})
    assert caught.value.error.code == INVALID_PARAMS
    assert caught.value.error.message == "Prompt 'flatsource_hello' needs the argument who."
    assert not [r for r in caplog.records if r.levelno >= logging.INFO]


async def test_logql_braces_survive_rendering(skills_dir, prompts_dir):
    server = KnowledgeBase(make_config(skills_dir, prompts_dir), skills_dir / "_cache")
    async with Client(server_of(server)) as client:
        result = await client.get_prompt("deepsource_check", {"service": "api"})
    assert text(result) == '{app="api"} |= "error"\n'


async def test_a_claude_command_and_a_copilot_prompt_serve_as_one_kind_of_prompt(
    tmp_path,
):
    """The dialect seam, end to end over a real client: a Claude Code command
    under ``commands/`` and a VS Code ``.prompt.md`` list beside this server's
    own dialect and render with their own placeholders filled. A Copilot
    ``${input:…}`` name is also an MCP argument name, so it has to survive the
    client's argument schema on the way round.
    """
    root = tmp_path / "plugin"
    (root / "commands").mkdir(parents=True)
    (root / "commands" / "deploy.md").write_text(
        "---\ndescription: Deploy an app.\narguments: [app, env]\n---\n"
        "Deploy $app to $env.\n"
    )
    (root / ".github" / "prompts").mkdir(parents=True)
    (root / ".github" / "prompts" / "review.prompt.md").write_text(
        "---\ndescription: Review a file.\n---\n"
        "Review ${input:target:Which file?} for ${input:concern}.\n"
    )
    config = Config.model_validate(
        {
            "plugins": [{"name": "kit", "source": f"file://{root}"}],
            "libraries": [{"name": "kit", "plugins": ["kit"]}],
        }
    )
    server = KnowledgeBase(config, tmp_path / "cache")
    async with Client(server_of(server)) as client:
        listed = {p.name: p for p in await client.list_prompts()}
        deployed = await client.get_prompt("kit_deploy", {"app": "api", "env": "prod"})
        reviewed = await client.get_prompt(
            "kit_review", {"target": "main.py", "concern": "races"}
        )
    assert [a.name for a in listed["kit_deploy"].arguments] == ["app", "env"]
    assert listed["kit_review"].arguments[0].description == "Which file?"
    assert [a.name for a in listed["kit_review"].arguments] == ["target", "concern"]
    assert text(deployed) == "Deploy api to prod.\n"
    assert text(reviewed) == "Review main.py for races.\n"
    assert {p.dialect for p in server.prompts} == {"claude", "copilot"}


async def test_a_prompts_dialect_is_decided_at_every_read(tmp_path):
    """No dialect is recorded: each read of the plugin decides it, by PRM-14.
    A command under ``commands/`` is Claude's, ``${input:app}`` and all, on the
    first start and on a cold start from the index alike."""
    deploy = (
        "---\ndescription: Deploy.\narguments: [env]\n---\n"
        "Deploy ${input:app} to $env.\n"
    )
    harvested = _kit(tmp_path, {"commands/deploy.md": deploy})
    assert [(p.dialect, [a.name for a in p.arguments]) for p in harvested.prompts] == [
        ("claude", ["env"])
    ]
    assert harvested.snapshot.commands["kit"].selected == ("commands/deploy.md",)

    restarted = _served(harvested.config, tmp_path / "cache")
    (prompt,) = restarted.prompts
    assert prompt.dialect == "claude"
    async with Client(server_of(restarted)) as client:
        rendered = await client.get_prompt("kit_deploy", {"env": "prod"})
    assert text(rendered) == "Deploy ${input:app} to prod.\n"


async def test_a_prompts_title_is_published(tmp_path):
    """FastMCP's ``Prompt`` has a title, and a file that declares one gets it."""
    root = tmp_path / "plugin"
    (root / "prompts").mkdir(parents=True)
    (root / "prompts" / "hello.md").write_text(
        "---\ntitle: Say Hello\ndescription: Greets.\n---\nHi.\n"
    )
    config = Config.model_validate(
        {
            "plugins": [{"name": "kit", "source": f"file://{root}"}],
            "libraries": [{"name": "kit", "plugins": ["kit"]}],
        }
    )
    server = KnowledgeBase(config, tmp_path / "cache")
    async with Client(server_of(server)) as client:
        listed = {p.name: p for p in await client.list_prompts()}
    assert listed["kit_hello"].title == "Say Hello"


async def test_skill_libraries_scopes_prompts(skills_dir, prompts_dir):
    """A prompt from an unconfigured library is neither listed nor renderable."""
    config = make_config(skills_dir, prompts_dir, libraries=["flatsource"])
    server = KnowledgeBase(config, skills_dir / "_cache")
    async with Client(server_of(server)) as client:
        assert [p.name for p in await client.list_prompts()] == ["flatsource_hello"]
        with pytest.raises(Exception, match="deepsource_check"):
            await client.get_prompt("deepsource_check", {"service": "api"})


# -- reading the snapshot -------------------------------------------------------


def test_visible_prompts_hold_to_the_scope(skills_dir, prompts_dir):
    """What ``RefuseEmptyScope`` counts: the prompts served, by their plugin's
    library, category and tags."""
    server = _served(make_config(skills_dir, prompts_dir), skills_dir / "_cache")
    snapshot = server.snapshot
    names = [p.name for p in snapshot.visible_prompts(Scope("flatsource"))]
    assert names == ["flatsource_hello"]
    assert not snapshot.visible_prompts(Scope("nowhere"))
    assert len(snapshot.visible_prompts()) == 2
