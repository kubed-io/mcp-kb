"""The MCP server over a knowledge base, built by ``QuickMCP``.

``create_app`` is the wiring and nothing else: the address space, the
resources, the mirror tools, the extensions, the middleware and the routes,
around one ``KnowledgeBase`` that ``main`` has already cold-started.

The catalogue is served twice, because MCP clients are not all alike. As
``skill://`` **resources**, which is what it is; and as two **tools** that
mirror those resources exactly, for the many clients that only implement tools
-- n8n among them, to which a resource-only server looks empty. The mirror is
hidden from clients that read resources, so each client sees one way to ask,
not two. A client declares it cannot read resources with ``?resources=off`` on
the MCP URL or an ``X-MCP-Resources: off`` header.
"""

from __future__ import annotations

from kubed.mcp import QuickMCP

from . import routes
from .catalogue.uris import Catalogue
from .mcp import prompts, resources, tools
from .mcp.agents import AgentsExtension
from .mcp.announce import AnnounceChanges
from .mcp.instructions import ScopedInstructions
from .mcp.pins import RefuseEmptyScope, what_is_wrong
from .mcp.request import client_reads_resources, client_uses_prompts
from .mcp.skills import AdvertiseLegacyExtensions, SkillsExtension
from .server import KnowledgeBase
from .spec import package_version


def current_catalogue(knowledge_base: KnowledgeBase) -> Catalogue:
    """The catalogue of the snapshot serving now, built once per call.

    A transient, so a call reads one generation from start to end, and the next
    call reads whatever a refresh has swapped in since.
    """
    return knowledge_base.snapshot.catalogue


def create_app(knowledge_base: KnowledgeBase) -> QuickMCP:
    """The ``mcp-kb`` server over ``knowledge_base``, ready to ``run()``."""
    config = knowledge_base.config
    ttl = config.min_refresh_seconds
    mcp = QuickMCP(
        "mcp-kb",
        config=config,
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

    # Built at boot, not on first use: a refused credential has to stop the
    # process before it serves (see KnowledgeBase._cold_start), so the
    # container is handed the one main built, and main owns it.
    mcp.singleton(KnowledgeBase, instance=knowledge_base)
    mcp.transient(Catalogue, current_catalogue)

    def catalogue() -> Catalogue:
        return knowledge_base.snapshot.catalogue

    resources.register(mcp, catalogue)
    extensions = [
        extension(
            catalogue,
            lambda scope: what_is_wrong(scope, config, knowledge_base.snapshot),
        )
        for extension in (SkillsExtension, AgentsExtension)
    ]
    for extension in extensions:
        mcp.add_extension(extension)
    # initialize carries what server/discover does: the skills id with {}, the
    # agents id with {"listChanged": False}.
    mcp.add_middleware(
        AdvertiseLegacyExtensions({e.identifier: e.settings() for e in extensions})
    )
    mcp.add_middleware(ScopedInstructions(catalogue))
    resource_tools = tools.register(mcp)
    prompt_tools = prompts.register(mcp, lambda: knowledge_base.snapshot)
    mirrors = dict.fromkeys(resource_tools, client_reads_resources)
    mirrors.update(dict.fromkeys(prompt_tools, client_uses_prompts))
    mcp.add_middleware(
        RefuseEmptyScope(
            lambda scope: what_is_wrong(scope, config, knowledge_base.snapshot)
        )
    )
    mcp.add_middleware(resources.HideMirrorTools(mirrors))
    mcp.add_middleware(AnnounceChanges(knowledge_base))
    routes.register(mcp, knowledge_base)
    return mcp
