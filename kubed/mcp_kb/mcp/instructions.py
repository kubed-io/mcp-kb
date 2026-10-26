"""The server ``instructions``, built for each connection.

What a client is told on connecting depends on its scope, whether it reads
resources and whether it declared the Skills extension, so there is no one text
to hand FastMCP at construction. Both handshakes carry it: ``initialize`` for
handshake-era clients and ``server/discover`` for the rest.
"""

from __future__ import annotations

from collections.abc import Callable

from fastmcp.server.middleware import Middleware

from ..catalogue.instructions import build_instructions
from ..catalogue.uris import Catalogue
from .request import (
    client_reads_resources,
    declared_on_discover,
    declared_on_initialize,
    requested_scope,
)


class ScopedInstructions(Middleware):
    """Set ``instructions`` on every initialize and discover answer."""

    def __init__(self, catalogue: Callable[[], Catalogue]):
        self._catalogue = catalogue

    def _text(self, declared: bool) -> str:
        return build_instructions(
            self._catalogue(),
            requested_scope(),
            resources=client_reads_resources(),
            skills_extension=declared,
        )

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
