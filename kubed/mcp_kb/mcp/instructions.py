"""The server ``instructions``, built for each connection.

What a client is told on connecting depends on its scope, whether it reads
resources and whether it declared the Skills extension, so there is no one text
to hand FastMCP at construction. Both handshakes carry it: ``initialize`` for
handshake-era clients and ``server/discover`` for the rest.

The text is built from one snapshot, read once per answer: its catalogue for
the skills, and its ``folders`` for where the prompts and agents are served
(INS-19). That snapshot is ``SkillServing.served_snapshot``, not
``KnowledgeBase.snapshot``. The handshake pins nothing (no view is asked for on
connect), so the instructions read the generation the plugin layer is serving,
and the pinned one inside a request that pinned: a pointer never names a folder
of a generation the layer is not serving to that request.
"""

from __future__ import annotations

from collections.abc import Callable

from kubed.mcp import Middleware
from kubed.mcp.gateway import prefix, prefixed

from ..catalogue.instructions import build_instructions
from ..catalogue.snapshot import Snapshot
from .request import (
    client_reads_resources,
    declared_on_discover,
    declared_on_initialize,
    requested_scope,
)


class ScopedInstructions(Middleware):
    """Set ``instructions`` on every initialize and discover answer."""

    def __init__(self, snapshot: Callable[[], Snapshot]):
        self._snapshot = snapshot

    def _text(self, declared: bool) -> str:
        snapshot = self._snapshot()
        scope = requested_scope()
        text = build_instructions(
            snapshot.catalogue,
            scope,
            resources=client_reads_resources(),
            skills_extension=declared,
            folders=snapshot.folders(scope),
        )
        return prefixed(text, prefix())

    async def on_initialize(self, context, call_next):
        result = await call_next(context)
        if result is not None:
            result.instructions = self._text(declared_on_initialize(context))
        return result

    async def on_discover(self, context, call_next):
        result = await call_next(context)
        if result is None:
            return result
        text = self._text(declared_on_discover(context))
        if isinstance(result, dict):
            result["instructions"] = text
        else:
            result.instructions = text
        return result
