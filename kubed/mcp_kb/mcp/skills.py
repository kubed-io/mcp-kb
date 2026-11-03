"""The Skills extension, alongside the existing resource and tool surfaces.

A skill:// resource is not itself an extension declaration. Skills-aware
clients discover complete entries through skills/list and skills/get, then
verify each file against that entry before loading it. Catalogue remains the
authority for scope and content; a getter follows every snapshot replacement.

The envelope, the scope check and the legacy declaration are shared with the
Agents extension in ``agents.py``, so the two answer alike.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
from collections.abc import Callable, Mapping, Sequence

import frontmatter
import yaml
from fastmcp.server.extensions import MethodBinding, ServerExtension
from fastmcp.server.middleware import Middleware
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_PARAMS, PaginatedRequestParams, RequestParams
from pydantic import Field

from ..catalogue.addressing import DEFAULT, Addressing
from ..catalogue.uris import Catalogue
from .request import EXTENSION_ID, requested_addressing, requested_scope
from .scope import Scope


class GetSkillParams(RequestParams):
    uri: str = Field(min_length=1)


def addressed(
    catalogue: Catalogue, scope: Scope, a: Addressing, entry: dict | None
) -> dict | None:
    """A canonical entry as this request addresses it.

    The catalogue stays canonical; the edge re-digests the
    bytes ``a.text`` makes of each body, which is what resources/read serves.
    """
    if entry is None or a == DEFAULT:
        return entry
    files = []
    for file in entry["resources"]:
        body = catalogue.read(file["uri"], scope)
        if body is None:
            continue
        served = a.text(body)
        content = served.encode("utf-8")
        files.append(
            {
                **file,
                "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
                "size": len(content),
            }
        )
        if file["uri"] == entry["uri"] and served != body:
            # An unparsable served body keeps the canonical frontmatter.
            with contextlib.suppress(yaml.YAMLError, ValueError):
                meta = frontmatter.loads(served).metadata
                entry = {**entry, "frontmatter": meta}
    return {**entry, "resources": files}


def checked_scope(problem: Callable[[Scope], str | None]) -> Scope:
    """This request's scope, or the refusal its scope earns (SCP-29).

    Extension methods keep the same invalid-scope contract as resources and
    prompts, including when a handler is invoked directly.
    """
    scope = requested_scope()
    refusal = problem(scope)
    if refusal:
        raise MCPError(code=INVALID_PARAMS, message=refusal)
    return scope


def complete(**fields: object) -> dict:
    """An extension result in the envelope every one of ours carries.

    Local/live sources can change between calls. Clients may retain an
    entry for verification, but must not reuse it as a fresh listing.
    """
    return {
        "resultType": "complete",
        "ttlMs": 0,
        "cacheScope": "private",
        **fields,
    }


class AdvertiseLegacyExtensions(Middleware):
    """Keep the declarations in initialize for handshake-era clients.

    FastMCP 4 advertises registered extensions through server/discover, but
    its SDK's legacy serializer removes that capability from initialize.
    This public middleware hook restores ours after serialization, each with
    the value server/discover gives it; otherwise existing Skills and Agents
    clients see a server that supports neither.
    """

    def __init__(self, declared: Mapping[str, dict]):
        self._declared = dict(declared)

    async def on_initialize(self, context, call_next):
        result = await call_next(context)
        if result is not None:
            result.capabilities.extensions = {
                **(result.capabilities.extensions or {}),
                **copy.deepcopy(self._declared),
            }
        return result


class SkillsExtension(ServerExtension):
    """Publish complete scoped entries without expanding resources/list."""

    identifier = EXTENSION_ID

    def __init__(
        self,
        catalogue: Callable[[], Catalogue],
        scope_problem: Callable[[Scope], str | None],
    ):
        self._catalogue = catalogue
        self._scope_problem = scope_problem

    def methods(self) -> Sequence[MethodBinding]:
        return (
            MethodBinding("skills/list", PaginatedRequestParams, self.list_skills),
            MethodBinding("skills/get", GetSkillParams, self.get_skill),
        )

    async def list_skills(self, ctx, params: PaginatedRequestParams) -> dict:
        scope = checked_scope(self._scope_problem)
        if params.cursor is not None:
            raise MCPError(code=INVALID_PARAMS, message="Invalid skills cursor")
        catalogue, a = self._catalogue(), requested_addressing()
        entries = []
        for uri in catalogue.skill_uris(scope):
            entry = addressed(catalogue, scope, a, catalogue.skill_entry(uri, scope))
            if entry is not None:
                entries.append(entry)
        return complete(skills=entries)

    async def get_skill(self, ctx, params: GetSkillParams) -> dict:
        scope = checked_scope(self._scope_problem)
        catalogue, a = self._catalogue(), requested_addressing()
        entry = catalogue.skill_entry(a.canonical(params.uri), scope)
        entry = addressed(catalogue, scope, a, entry)
        if entry is None:
            # Out-of-scope and absent skills have exactly the same error.
            raise MCPError(code=INVALID_PARAMS, message="Skill not found")
        return complete(skill=entry)
