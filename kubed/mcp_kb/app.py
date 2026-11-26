"""The MCP server over a knowledge base, built by ``QuickMCP``.

``create_app`` is the wiring and nothing else: the plugin set, the address
space, the resources, the middleware and the routes, around one
``KnowledgeBase`` that ``main`` has already cold-started.

The skills, agents and prompts are kubed-mcp's to serve, from the plugin set
``SkillServing`` publishes each generation, with kb's scope as its view, kb's
text rewriting as its rewriter and kb's dialect reader as its command reader.
kb serves the rest of the ``skill://`` space: the indexes, ``_files.md``,
library files and the fallbacks. The
resource tools are kubed-mcp's too (DLV-6), shown to a client that says it
cannot read resources, and they are the server's only tools.
"""

from __future__ import annotations

from kubed.mcp import QuickMCP
from kubed.mcp.protocol import AdvertiseLegacyExtensions
from kubed.mcp.skills import SkillsExtension

from . import routes
from .catalogue.uris import Catalogue
from .config import BUILTIN_SCHEMES, SERVER_NAME
from .mcp import resources
from .mcp.announce import AnnounceChanges
from .mcp.instructions import ScopedInstructions
from .mcp.pins import RefuseEmptyScope, what_is_wrong
from .mcp.skills import QuietSelection, SkillServing
from .server import KnowledgeBase
from .sources import ServedTrees
from .spec import package_version


def create_app(knowledge_base: KnowledgeBase) -> QuickMCP:
    """The ``mcp-kb`` server over ``knowledge_base``, ready to ``run()``."""
    config = knowledge_base.config
    ttl = config.min_refresh_seconds
    mcp = QuickMCP(
        SERVER_NAME,
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
    # The plugin layer's line for a file kb's selection leaves out, kept out
    # of the log; once per process, however many apps it builds (P8).
    QuietSelection.install()
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
    # The snapshot the plugin layer serves, not kb's: the handshake pins no
    # build, so its pointers name what is served (INS-19).
    mcp.add_middleware(ScopedInstructions(serving.served_snapshot))
    mcp.add_middleware(
        RefuseEmptyScope(
            lambda scope: what_is_wrong(scope, config, knowledge_base.snapshot)
        )
    )
    mcp.add_middleware(AnnounceChanges(knowledge_base))
    routes.register(mcp, knowledge_base)
    return mcp
