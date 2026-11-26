"""The server ``instructions``, built for each connection.

What a client is told on connecting depends on its scope, whether it reads
resources and whether it declared the Skills extension, so there is no one text
to hand FastMCP at construction. kubed-mcp calls ``ScopedInstructions`` with
each ``initialize`` and ``server/discover`` request's resolution, so the
footer follows its resolved ``resources`` setting and the Skills extension is
the one it resolved. The prefix is kubed-mcp's to write over the text returned.

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
from typing import TYPE_CHECKING

from ..catalogue.instructions import build_instructions
from ..catalogue.snapshot import Snapshot
from .request import EXTENSION_ID, requested_scope

if TYPE_CHECKING:
    from kubed.mcp.delivery import Resolved


class ScopedInstructions:
    """The ``instructions`` hook: the text for one resolved request, unprefixed."""

    def __init__(self, snapshot: Callable[[], Snapshot]):
        self._snapshot = snapshot

    def __call__(self, delivery: Resolved) -> str:
        snapshot = self._snapshot()
        scope = requested_scope()
        return build_instructions(
            snapshot.catalogue,
            scope,
            resources=delivery.resources == "on",
            skills_extension=EXTENSION_ID in (delivery.extensions or ()),
            folders=snapshot.folders(scope),
        )
