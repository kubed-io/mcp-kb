"""The Agents extension: agents/list and agents/get, beside the Skills one.

The draft Agent Discovery Extension (``io.modelcontextprotocol/agents``) is a
discovery surface of its own. It adds no listing row, no tool, no prompt and no
line of instructions, so a client that never declared it sees exactly the server
it saw before (AGT-2). Catalogue is the authority for names, scope and content;
this module adds the envelope, the gateway prefix and the errors, and reads the
catalogue through a getter so it follows every snapshot replacement.

Neither method takes a scope (SCP-9): the connection's own is the only filter,
and an agent outside it is answered exactly as an absent one is (AGT-13).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from fastmcp.server.extensions import MethodBinding, ServerExtension
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_PARAMS, PaginatedRequestParams, RequestParams
from pydantic import Field

from ..catalogue.uris import Catalogue
from .request import AGENTS_EXTENSION_ID, requested_addressing
from .scope import Scope
from .skills import checked_scope, complete

# kb sends no notifications/agents/list_changed (AGT-1).
SETTINGS = {"listChanged": False}

AGENT_NOT_FOUND = {"reason": "agent_not_found"}


class GetAgentParams(RequestParams):
    name: str = Field(min_length=1)


class AgentsExtension(ServerExtension):
    """Publish scoped agent cards and definitions, and nothing else."""

    identifier = AGENTS_EXTENSION_ID

    def __init__(
        self,
        catalogue: Callable[[], Catalogue],
        scope_problem: Callable[[Scope], str | None],
    ):
        self._catalogue = catalogue
        self._scope_problem = scope_problem

    def settings(self) -> dict[str, Any]:
        # A fresh dict each time: it is spliced into a capabilities answer.
        return dict(SETTINGS)

    def methods(self) -> Sequence[MethodBinding]:
        return (
            MethodBinding("agents/list", PaginatedRequestParams, self.list_agents),
            MethodBinding("agents/get", GetAgentParams, self.get_agent),
        )

    async def list_agents(self, ctx, params: PaginatedRequestParams) -> dict:
        scope = checked_scope(self._scope_problem)
        if params.cursor is not None:
            # One page holds every card, so no cursor was ever issued (AGT-7).
            raise MCPError(code=INVALID_PARAMS, message="Invalid agents cursor")
        return complete(agents=self._catalogue().agent_cards(scope))

    async def get_agent(self, ctx, params: GetAgentParams) -> dict:
        scope = checked_scope(self._scope_problem)
        definition = self._catalogue().agent_definition(params.name, scope)
        if definition is None:
            # Out-of-scope and absent agents have exactly the same error.
            raise MCPError(
                code=INVALID_PARAMS,
                message="Agent not found",
                data=dict(AGENT_NOT_FOUND),
            )
        # A new dict: the definition's values are the snapshot's own, and only
        # instructions -- a fresh string -- differs. _meta goes out verbatim.
        served = dict(definition)
        if "instructions" in served:
            served["instructions"] = requested_addressing().text(
                served["instructions"]
            )
        return complete(**served)
