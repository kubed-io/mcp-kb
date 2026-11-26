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

The text follows the request's Via mode (INS-20): ``mcp``, ``extension`` or
``local``, handed to the builder as the plain string kubed-mcp resolved.

Building the text never fails a handshake (INS-23). Everything, from reading the
snapshot to the build, sits in one ``try``; a failure is logged at ERROR with
its traceback masked of credentials, and the answer is the mode's footer, or
nothing under ``local``, never kubed-mcp's own failure path.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from typing import TYPE_CHECKING

from ..catalogue.instructions import build_instructions, footer
from ..catalogue.snapshot import Snapshot
from ..config import redact
from .request import EXTENSION_ID, requested_scope

if TYPE_CHECKING:
    from kubed.mcp.delivery import Resolved


log = logging.getLogger(__name__)


class ScopedInstructions:
    """The ``instructions`` hook: the text for one resolved request, unprefixed.

    It never raises (INS-23): a failed build is logged and answered with the
    footer of the request's mode.
    """

    def __init__(
        self, snapshot: Callable[[], Snapshot], secrets: Callable[[], list[str]]
    ):
        self._snapshot = snapshot
        self._secrets = secrets

    def __call__(self, delivery: Resolved) -> str:
        try:
            snapshot = self._snapshot()
            scope = requested_scope()
            return build_instructions(
                snapshot.catalogue,
                scope,
                resources=delivery.resources == "on",
                skills_extension=EXTENSION_ID in (delivery.extensions or ()),
                folders=snapshot.folders(scope),
                via=delivery.via,
            )
        except Exception as exc:  # noqa: BLE001 - a handshake never fails (INS-23)
            trace = "".join(traceback.format_exception(exc))
            log.error(
                "instructions failed; the footer stands in\n%s",
                redact(trace, self._secrets()),
            )
            return footer(resources=delivery.resources == "on", via=delivery.via)
