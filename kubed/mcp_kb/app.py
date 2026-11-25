"""The MCP server over a knowledge base, built by ``QuickMCP``.

``create_app`` is the wiring and nothing else: the plugin set, the address
space, the resources, the prompts, the middleware and the routes, around one
``KnowledgeBase`` that ``main`` has already cold-started.

The skills and agents are kubed-mcp's to serve, from the plugin set
``SkillServing`` publishes each generation, with kb's scope as its view and
kb's text rewriting as its rewriter. kb serves the rest of the ``skill://``
space: the indexes, ``_files.md``, library files and the fallbacks. The
resource mirror tools are kubed-mcp's too (DLV-6), shown to a client that says
it cannot read resources; the prompt mirror is kb's.
"""

from __future__ import annotations

from kubed.mcp import QuickMCP
from kubed.mcp.protocol import AdvertiseLegacyExtensions
from kubed.mcp.skills import SkillsExtension

from . import routes
from .catalogue.uris import Catalogue
from .config import BUILTIN_SCHEMES
from .mcp import prompts, resources
from .mcp.announce import AnnounceChanges
from .mcp.instructions import ScopedInstructions
from .mcp.pins import RefuseEmptyScope, what_is_wrong
from .mcp.request import client_uses_prompts
from .mcp.skills import SkillServing
from .server import KnowledgeBase
from .sources import ServedTrees
from .spec import package_version


def create_app(knowledge_base: KnowledgeBase) -> QuickMCP:
    """The ``mcp-kb`` server over ``knowledge_base``, ready to ``run()``."""
    config = knowledge_base.config
    ttl = config.min_refresh_seconds
    mcp = QuickMCP(
        "mcp-kb",
        config=config,
        header_prefix="Kb",
        version=package_version(),
        lifespan=knowledge_base.lifespan,
        # A client may hold a listing for as long as the shortest refresh
        # interval, which is the soonest it could possibly be wrong. That is the
        # whole staleness bound for a sessionless client, which AnnounceChanges
        # cannot reach. Private, because a listing is scoped by the caller's own
        # headers.
        cache_ttl=ttl,
        cache_scope=None if ttl is None else "private",
    )

    # kubed-mcp is handed kb's own address, never a cache path: the trees it
    # reads are the ones kb serves, the last good one included.
    mcp.add_loader(
        ServedTrees(
            (*BUILTIN_SCHEMES, *(source.name for source in config.sources)),
            knowledge_base.served_tree,
        )
    )

    # Built at boot, not on first use: a refused credential has to stop the
    # process before it serves (see KnowledgeBase._cold_start), so the
    # container is handed the one main built, and main owns it.
    mcp.singleton(KnowledgeBase, instance=knowledge_base)

    def catalogue() -> Catalogue:
        return knowledge_base.snapshot.catalogue

    # A transient, so a call reads one generation from start to end, and the
    # next call reads whatever a refresh has swapped in since.
    mcp.transient(Catalogue, catalogue)

    # The plugin set, published now and on every refresh. First, so the plugin
    # layer's skills provider comes before kb's whenever the boot generation
    # has a skill, and before any tool, so no tool kb registers can take a
    # name the plugin layer serves (DLV-7).
    serving = SkillServing(mcp, knowledge_base)
    serving.attach()
    mcp.singleton(SkillServing, instance=serving)

    resources.register(mcp, catalogue)
    # initialize carries what server/discover does: the skills id with
    # directoryRead. The agents id is kubed-mcp's to advertise.
    mcp.add_middleware(
        AdvertiseLegacyExtensions(
            {SkillsExtension.identifier: SkillsExtension().settings()}
        )
    )
    mcp.add_middleware(ScopedInstructions(catalogue))
    prompt_tools = prompts.register(mcp, lambda: knowledge_base.snapshot, catalogue)
    mcp.add_middleware(
        RefuseEmptyScope(
            lambda scope: what_is_wrong(scope, config, knowledge_base.snapshot)
        )
    )
    mcp.add_middleware(
        resources.HideMirrorTools(dict.fromkeys(prompt_tools, client_uses_prompts))
    )
    mcp.add_middleware(AnnounceChanges(knowledge_base))
    routes.register(mcp, knowledge_base)
    return mcp
