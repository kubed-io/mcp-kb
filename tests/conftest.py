"""Shared fixtures: a synthetic skills tree covering both nesting depths."""

import weakref
from pathlib import Path

import frontmatter
import pytest

from kubed.mcp_kb.app import create_app
from kubed.mcp_kb.catalogue import harvest
from kubed.mcp_kb.catalogue.prompts import load_prompts
from kubed.mcp_kb.catalogue.skills import LibraryFiles, load_skills
from kubed.mcp_kb.config import Config
from kubed.mcp_kb.plugins import Fetch, Globs, Plugin

# The WebDAV server fixture lives in its own module -- it is a server, not a
# tree -- and is registered here so a test can ask for `webdav` by name.
from tests.webdav_server import webdav  # noqa: F401 - a fixture, used by name

FLAT = {"alpha": "First skill.", "beta": "Second skill."}
NESTED = {"plugin-a": {"gamma": "Third skill."}, "plugin-b": {"delta": "Fourth skill."}}

# Each synthetic library is its directory's plugins, every one rooted at that
# directory, so their skill folders are relative to it rather than to the tree
# root. flatsource is one plugin, named like its library and so its main one,
# which lays its skills directly under itself and declares that folder (".").
# deepsource is three: its own -- the main plugin, serving the library's files
# and prompts and no skill -- and one per folder below skills/, named like the
# folder, which is what puts their skills at deepsource/<plugin>/<name>.
FLAT_FOLDERS = (".",)
DEEP_FILES = ("README.md", "shared/**/*")


def library_plugins(library: str, nested=tuple(NESTED)) -> dict[str, Globs]:
    """The plugins a synthetic library's directory is declared as, by name.

    ``nested`` is deepsource's plugins below its own: one per folder below
    ``skills/``, declared whether or not the folder is there yet.
    """
    if library != "deepsource":
        return {library: Globs(skills=FLAT_FOLDERS, files=("**/*",))}
    return {
        library: Globs(skills=(), files=DEEP_FILES),
        **{
            name: Globs(skills=(f"./skills/{name}",), prompts=(), files=())
            for name in nested
        },
    }


PROMPT_GLOBS = Globs(skills=(), prompts=("*.md",))

# What each synthetic library's plugins declare about themselves. A tag per
# library, so a tag scope can tell the two apart the way a library scope can.
PLUGIN_TAGS = {"flatsource": ("flat",), "deepsource": ("deep",)}

# One app per knowledge base, so a test that reaches the server twice -- a route
# added, then the ASGI app built -- reaches the same one.
_APPS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def server_of(knowledge_base):
    """The FastMCP server ``create_app`` builds over ``knowledge_base``.

    What a ``fastmcp.Client`` connects to in memory, and what ``http_app()`` is
    called on.
    """
    if knowledge_base not in _APPS:
        _APPS[knowledge_base] = create_app(knowledge_base)
    return _APPS[knowledge_base].server


def served(catalogue, uri: str, scope=None) -> str | None:
    """``uri`` as the server serves it from ``catalogue``, under ``scope``.

    A skill's file comes from the skills provider's build, as production serves
    it; anything else from ``Catalogue.read``. For a test below MCP.
    """
    from kubed.mcp_kb.mcp.scope import EVERYTHING
    from kubed.mcp_kb.mcp.skill_catalogue import SkillCatalogue

    scope = EVERYTHING if scope is None else scope
    for address, skill in SkillCatalogue(lambda: catalogue).skills(scope).items():
        root = f"skill://{address}/"
        if uri.startswith(root):
            data = skill.files.get(uri[len(root) :])
            return None if data is None else data.decode("utf-8")
    return catalogue.read(uri, scope)


def read_served(knowledge_base, uri: str) -> str | None:
    """``uri`` read as a client reads it: ``resources/read`` over an MCP client.

    None when the server answers that it has nothing there. Synchronous, for a
    test that is not a coroutine; it runs the client on a loop of its own, so a
    coroutine test may call it too. Off HTTP, so unscoped.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    from fastmcp import Client
    from kubed.mcp.protocol import MCPError

    async def read() -> str | None:
        async with Client(server_of(knowledge_base)) as client:
            try:
                return (await client.read_resource(uri))[0].text
            except MCPError:
                return None

    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, read()).result()


# Frontmatter nested deeper than the YAML parser's stack, as far as
# ``frontmatter_out_of_stack`` is concerned; the real parser may well read it.
DEEP_YAML = "[" * 1000 + "]" * 1000


@pytest.fixture
def frontmatter_out_of_stack(monkeypatch):
    """``frontmatter.loads`` as a runner with a small stack has it.

    Since 3.14 how deep a parser goes depends on the thread's stack size, not
    on the recursion limit, so real nesting raises ``RecursionError`` on one
    runner and parses to the end on another. Text holding ``DEEP_YAML`` raises
    here every time; every other text still goes to the real parser.
    """
    real = frontmatter.loads

    def loads(text, *args, **kwargs):
        if isinstance(text, str) and DEEP_YAML in text:
            raise RecursionError("maximum recursion depth exceeded")
        return real(text, *args, **kwargs)

    monkeypatch.setattr(frontmatter, "loads", loads)


def fetch_key(path: Path) -> str:
    """The fetch key a ``file://`` plugin at ``path`` gets: what ``refresh`` returns."""
    return f"file://{path}"


def key_of(config: Config, plugin: str) -> str:
    """The fetch key of the named plugin in ``config``, whatever scheme it uses."""
    return next(p.address.key for p in config.plugins if p.name == plugin)


def fake_plugin(name: str, root: Path, **overrides) -> Plugin:
    """A resolved plugin over a local directory, for tests below the server.

    The id is the name and the fetch is the directory itself, which is what
    ``make_config`` below produces once it has been through the config.
    """
    fields = {
        "id": name,
        "name": name,
        "description": "",
        "category": None,
        "tags": PLUGIN_TAGS.get(name, ()),
        "keywords": (),
        "version": None,
        "fetch": Fetch(key=fetch_key(root), backend="file", url=str(root)),
        "subdir": "",
        "globs": Globs(),
    }
    fields.update(overrides)
    return Plugin(**fields)


def _synthetic_plugins(root):
    """Each synthetic plugin under ``root``: library, name, root and globs."""
    for library in PLUGIN_TAGS:
        library_root = root / library
        if library_root.is_dir():
            for name, globs in library_plugins(library).items():
                yield library, name, library_root, globs


def load_all_skills(root):
    """Harvest and load every synthetic library under ``root``, as one catalogue.

    A plugin named like its library is its main one, as ``assemble_libraries``
    decides it for these libraries; every other sits in a folder of its name.
    """
    skills = []
    for library, name, library_root, globs in _synthetic_plugins(root):
        dirs = harvest.skill_dirs(library_root, globs.skills)
        skills += load_skills(
            dirs,
            library=library,
            plugin=fake_plugin(name, library_root, tags=PLUGIN_TAGS[library]),
            root=library_root,
            folder="" if name == library else name,
        )
    return skills


def build_library_files(root):
    """A ``LibraryFiles`` fed from every synthetic library under ``root``."""
    resources = LibraryFiles()
    for library, name, library_root, globs in _synthetic_plugins(root):
        dirs = harvest.skill_dirs(library_root, globs.skills)
        files = harvest.library_files(library_root, globs, dirs)
        resources.add(
            library,
            library_root,
            files,
            dirs,
            plugin=fake_plugin(name, library_root, tags=PLUGIN_TAGS[library]),
        )
    return resources


def load_library_prompts(root, library):
    """The prompts harvested from one library's own prompt root under ``root``."""
    library_root = root / library
    if not library_root.is_dir():
        return []
    files = harvest.prompt_files(library_root, PROMPT_GLOBS)
    return load_prompts(files, library=library, plugin=f"{library}-prompts")


def load_all_prompts(root):
    """Every library's prompts under ``root``, combined."""
    prompts = []
    for library in PLUGIN_TAGS:
        prompts += load_library_prompts(root, library)
    return prompts


def make_config(
    skills_dir=None, prompts_dir=None, libraries=None, refresh=None, nested=None
):
    """A ``Config`` whose ``file://`` plugins mirror the fixture trees above.

    One plugin per top-level directory under ``skills_dir`` and one
    ``<name>-prompts`` plugin per top-level directory under ``prompts_dir``,
    and one library per name listing both -- the two trees are separate roots
    and a plugin is exactly one root. ``libraries`` narrows to the named
    libraries: a deployment that should serve less gets a config that lists
    less.

    ``refresh`` puts the plugins behind a declared ``local`` source carrying
    that interval instead of the built-in ``file://`` scheme, which carries
    none -- the shape a test of the refresh loop needs.

    ``nested`` is deepsource's plugins below its own, in place of one per
    folder of ``NESTED``: a plugin declared before its folder exists is how a
    refresh picks up a new one.
    """
    nested = tuple(NESTED) if nested is None else tuple(nested)
    plugins = []
    members: dict[str, list[str]] = {}
    for base, is_prompts in ((skills_dir, False), (prompts_dir, True)):
        if base is None:
            continue
        for name in sorted(p.name for p in base.iterdir() if p.is_dir()):
            if libraries is not None and name not in libraries:
                continue
            path = base / name
            source = f"file://{path}" if refresh is None else f"local://{path.relative_to('/')}"
            if is_prompts:
                declared = [
                    {
                        "name": f"{name}-prompts",
                        "source": source,
                        "skills": [],
                        "prompts": ["*.md"],
                    }
                ]
            else:
                declared = [
                    {
                        "name": plugin,
                        "source": source,
                        "tags": list(PLUGIN_TAGS.get(name, ())),
                        "skills": list(globs.skills),
                        **({} if globs.prompts is None else {"prompts": []}),
                        "files": list(globs.files),
                    }
                    for plugin, globs in library_plugins(name, nested).items()
                ]
            plugins += declared
            members.setdefault(name, []).extend(p["name"] for p in declared)
    sources = [] if refresh is None else [
        {"name": "local", "url": "file:///", "refresh": refresh}
    ]
    return Config.model_validate(
        {
            "sources": sources,
            "plugins": plugins,
            "libraries": [
                {"name": name, "plugins": names} for name, names in members.items()
            ],
        }
    )


def _build_tree(root):
    """Write the synthetic skills tree into ``root`` and return it."""
    for name, desc in FLAT.items():
        _write(root / "flatsource" / name, name, desc)
    for plugin, skills in NESTED.items():
        for name, desc in skills.items():
            _write(root / "deepsource" / "skills" / plugin / name, name, desc)
    # Library-level files: outside every skill directory, so not skills themselves.
    (root / "deepsource" / "README.md").write_text("not a skill\n")
    shared = root / "deepsource" / "shared"
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "guide.md").write_text("shared guidance\n")
    (shared / "nested").mkdir(exist_ok=True)
    (shared / "nested" / "schema.json").write_text("{}\n")
    # A dotfile, which is the only library-level "file" grafana actually ships.
    # It must not earn the library an index row pointing at nothing readable.
    (root / "flatsource" / ".gitkeep").write_text("")
    return root


def _write(path, name, description):
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\nBody.\n"
    )


def _build_prompts(root):
    """One prompt per library, plus a file that is not in a library folder at all."""
    _prompt(
        root / "flatsource" / "hello.md",
        "description: Say hello.\n"
        "arguments:\n"
        "- name: who\n"
        "  required: true\n"
        "- name: greeting\n"
        "  default: Hello\n",
        "{{ greeting }}, {{ who }}.\n",
    )
    # LogQL uses single braces, which is why placeholders are double ones.
    _prompt(
        root / "deepsource" / "check.md",
        "description: Check a service.\narguments:\n- name: service\n",
        '{app="{{ service }}"} |= "error"\n',
    )
    (root / "loose.md").write_text("---\ndescription: not in a library\n---\nnope\n")
    return root


def _prompt(path, frontmatter, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}---\n{body}")


@pytest.fixture
def prompts_dir(tmp_path_factory):
    """A prompts root: ``<library>/<name>.md``, for the libraries in ``skills_dir``."""
    return _build_prompts(tmp_path_factory.mktemp("prompts"))


@pytest.fixture(scope="module")
def prompts_dir_module(tmp_path_factory):
    """Module-scoped twin of ``prompts_dir``, for the HTTP server fixture."""
    return _build_prompts(tmp_path_factory.mktemp("prompts"))


@pytest.fixture
def skills_dir(tmp_path):
    """A skills root holding one flat plugin and one two-level plugin.

    Mirrors the real libraries: n8n is ``<root>/<skill>/`` while grafana is
    ``<root>/skills/<folder>/<skill>/``.
    """
    return _build_tree(tmp_path)


@pytest.fixture(scope="module")
def skills_dir_module(tmp_path_factory):
    """Module-scoped twin of ``skills_dir``.

    The HTTP tests start one uvicorn server per module, so the tree it serves
    has to outlive a single test.
    """
    return _build_tree(tmp_path_factory.mktemp("skills"))


def pytest_addoption(parser):
    parser.addoption(
        "--kb-url", default=None, help="a running kb's base URL, for tests/live"
    )
    parser.addoption(
        "--kb-dav-dir",
        default=None,
        help="the folder the running kb's dav source serves; AGT-16 edits it",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--kb-url"):
        return
    skip = pytest.mark.skip(reason="a live check: needs --kb-url")
    for item in items:
        if item.get_closest_marker("live"):
            item.add_marker(skip)
