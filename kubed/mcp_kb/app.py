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
from kubed.mcp.protocol import AdvertiseLegacyExtensions
from kubed.mcp.skills import SkillsExtension

from . import routes
from .catalogue.uris import Catalogue
from .config import BUILTIN_SCHEMES
from .mcp import prompts, resources, tools
from .mcp.agents import AgentsExtension
from .mcp.announce import AnnounceChanges
from .mcp.instructions import ScopedInstructions
from .mcp.pins import RefuseEmptyScope, what_is_wrong
from .mcp.request import client_reads_resources, client_uses_prompts
from .mcp.skill_catalogue import SkillCatalogue
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

    # The skills FastMCP serves, from the snapshot serving now. The catalogue a
    # request reads is the snapshot's less every skill that request's skills
    # catalogue lacks, and every other surface reads it.
    skills = SkillCatalogue(lambda: knowledge_base.snapshot.catalogue)

    def catalogue() -> Catalogue:
        return skills.catalogue()

    # A transient, so a call reads one generation from start to end, and the
    # next call reads whatever a refresh has swapped in since.
    mcp.transient(Catalogue, catalogue)

    # First, so a skill's file is always the skill provider's (MD-57).
    mcp.add_provider(skills)
    resources.register(mcp, catalogue)
    agents = AgentsExtension(
        catalogue,
        lambda scope: what_is_wrong(
            scope, config, knowledge_base.snapshot, skills.catalogue
        ),
    )
    mcp.add_extension(agents)
    # initialize carries what server/discover does: the skills id with
    # directoryRead, the agents id with {"listChanged": False}.
    declared = {SkillsExtension.identifier: SkillsExtension().settings()}
    mcp.add_middleware(
        AdvertiseLegacyExtensions({**declared, agents.identifier: agents.settings()})
    )
    mcp.add_middleware(ScopedInstructions(catalogue))
    resource_tools = tools.register(mcp)
    prompt_tools = prompts.register(mcp, lambda: knowledge_base.snapshot, catalogue)
    mirrors = dict.fromkeys(resource_tools, client_reads_resources)
    mirrors.update(dict.fromkeys(prompt_tools, client_uses_prompts))
    mcp.add_middleware(
        RefuseEmptyScope(
            lambda scope: what_is_wrong(
                scope, config, knowledge_base.snapshot, skills.catalogue
            )
        )
    )
    mcp.add_middleware(resources.HideMirrorTools(mirrors))
    mcp.add_middleware(AnnounceChanges(knowledge_base))
    routes.register(mcp, knowledge_base)
    return mcp
