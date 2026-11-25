"""The catalogue, served as MCP resources.

MCP already has a primitive for "material an agent reads", and it is the
resource, not the tool. So this is the real interface and ``tools.py`` is a
mirror of it, kept for the clients -- n8n above all -- to which a resource-only
server looks empty.

One provider serves the whole address space rather than one provider per skill.
FastMCP's ``SkillsDirectoryProvider`` is the obvious alternative, and it is
wrong here for two reasons that only show up at scale:

- It names a skill after its folder, so two libraries shipping a ``testing/``
  become one, and the loser is not merely shadowed but absent from the
  server. With four libraries and ninety skills that is a matter of time,
  not luck.
- It lists every skill and every manifest on every ``resources/list`` -- 77KB
  for this catalogue, paid by every client on every listing. That is the same
  expense this server rejects ``ResourcesAsTools`` for.

``Catalogue`` fixes both by listing *indexes* and resolving content on demand,
which is the resource half of progressive disclosure. A library and a folder
are directories too: ``CatalogueProvider.children`` lists one for
``resources/directory/read`` and ``_index.json``, from the same scoped
``Catalogue.directory``.

A skill's own files are not this provider's. kubed-mcp's plugin layer serves
them, from the plugin set ``skills.SkillServing`` publishes, and this provider
answers only what it misses: the indexes, ``_files.md``, the library files and
the plugin-root fallbacks (SKL-30, SKL-31), so it never shadows a skill file.

``resources/templates/list`` carries one fixed row, ``skill://{library}/{+path}``.
It is how a client learns the space exists, and it is never matched: a read
that misses stays a miss, whatever the template would have expanded to.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from kubed.mcp import (
    Middleware,
    NotFoundError,
    QuickMCP,
    Resource,
    ResourceTemplate,
    TextResource,
)
from kubed.mcp.protocol import INVALID_PARAMS, MCPError, Provider, VersionSpec, types
from kubed.mcp.skills import FolderNotFound, NameTheIndex

from ..catalogue.addressing import Addressing
from ..catalogue.uris import INDEX_JSON, Catalogue, parse
from .request import full_listing, requested_addressing, requested_scope

TEMPLATE_URI = "skill://{library}/{+path}"
# An escaped "/" in an address, and the address nothing answers.
_ENCODED_SLASH = re.compile(r"%2f", re.IGNORECASE)
NOWHERE = "skill://%2F"

TEMPLATE_DESCRIPTION = (
    "A skill, index or file this server serves: {library} is a library's name"
    " and {path} a path below it. Start at skill://{library}/_index.md;"
    " resources/list names the libraries."
)


class SkillTemplate(ResourceTemplate):
    """The template row, without a ``mimeType``.

    MCP says to give one only when every match shares a type, and these do not
    (markdown, a JSON ``_manifest``, a library file's guessed type). FastMCP
    defaults an empty one to ``text/plain``, so the wire row drops it.
    """

    def to_mcp_template(self, **overrides: Any) -> types.ResourceTemplate:
        return super().to_mcp_template(**{"mimeType": None, **overrides})


class CatalogueProvider(Provider):
    """Every ``skill://`` URI, scoped to whoever is asking.

    The scope is applied here rather than in middleware because it is applied on
    *every* call anyway -- ``Catalogue`` has no method that does not take
    the scope. Middleware would be a second place for it to be forgotten.

    An out-of-scope URI resolves to None, which FastMCP reports as an unknown
    resource. That conflation is deliberate and matches ``SkillIndex``: a scoped
    client must not be able to confirm another library's contents from the shape
    of an error.

    The catalogue arrives as a getter, not a value. A refresh builds a new one
    and swaps the server's snapshot; a provider holding the old object would
    serve the generation it was registered in for the life of the process.
    """

    def __init__(self, catalogue: Callable[[], Catalogue]):
        super().__init__()
        self._catalogue = catalogue

    async def _list_resources(self) -> Sequence[Resource]:
        entries = self._catalogue().entries(requested_scope(), full=full_listing())
        a = requested_addressing()
        return [
            TextResource(
                uri=entry.uri,
                name=entry.name,
                description=a.text(entry.description),
                mime_type=entry.mime_type,
                tags=set(entry.tags),
                # Listing rows are addresses, not content. The body is fetched
                # when the URI is actually read; putting it here would read the
                # whole catalogue off disk to answer "what is there?".
                text="",
            )
            for entry in entries
        ]

    async def _get_resource(
        self, uri: str, version: VersionSpec | None = None
    ) -> Resource | None:
        catalogue = self._catalogue()
        a = requested_addressing()
        canonical = a.canonical(uri)
        name = uri.removeprefix(a.prefix).removeprefix("skill://")
        parent, _, last = canonical.rpartition("/")
        if last == INDEX_JSON:
            children = await self.children(parent)
            if children is not None:
                return TextResource(
                    uri=uri,
                    name=name,
                    description=f"What is in {parent}",
                    mime_type="application/json",
                    # Text a client reads, so it carries the prefix, as this
                    # provider's _index.md and the plugin layer's own
                    # _index.json do (GW-5): one writer.
                    text=a.text(json.dumps(children, indent=2)),
                )
        body = catalogue.read(canonical, requested_scope())
        if body is None:
            return None
        return TextResource(
            uri=uri,
            name=name,
            mime_type=catalogue.mime(canonical),
            text=a.text(body),
        )

    async def children(self, uri: str) -> list[dict] | None:
        """A library's or a folder's direct children, as wire ``Resource`` rows.

        What ``resources/directory/read`` and ``_index.json`` list there, from
        ``Catalogue.directory`` under the caller's scope; None for anything
        else, a skill's own folders included, which are the skill provider's.
        """
        a = requested_addressing()
        entries = self._catalogue().directory(a.canonical(uri), requested_scope())
        if entries is None:
            return None
        return [
            {**entry.as_dict(), "description": a.text(entry.description)}
            for entry in entries
        ]

    async def _list_resource_templates(self) -> Sequence[ResourceTemplate]:
        return [
            SkillTemplate(
                uri_template=TEMPLATE_URI,
                name="skill",
                description=requested_addressing().text(TEMPLATE_DESCRIPTION),
                # ResourceTemplate requires it; never matched against, because
                # _get_resource_template below returns None.
                parameters={
                    "type": "object",
                    "properties": {
                        "library": {"type": "string"},
                        "path": {"type": "string"},
                    },
                    "required": ["library", "path"],
                },
            )
        ]

    async def _get_resource_template(
        self, uri: str, version: VersionSpec | None = None
    ) -> ResourceTemplate | None:
        """Never match: the template is for discovery, not for reading.

        FastMCP's ``read_resource`` falls back to this when ``_get_resource``
        misses, and the default would match any listed template, turning every
        miss into a template read and breaking ``NameTheFileToRead`` and the
        rule that out-of-scope reads exactly as absent.
        """
        return None


class NameTheFileToRead(Middleware):
    """Turn a read of a directory address into an error that says what to read.

    A library, a folder and a skill's root are directories, and a directory
    serves nothing. The provider answers None for them like any other missing
    URI, and FastMCP reports ``Resource not found`` -- true, and no help to an
    agent that learned the shorthand elsewhere. This rewrites that one error to
    name the ``_index.md``, ``SKILL.md`` or ``_manifest`` to read instead.

    The hint is answered from the caller's own scope, so it never confirms a
    directory the caller could not have listed: out of scope, the error is the
    same bare one a missing URI gets. The code is unchanged, -32602.
    """

    def __init__(self, catalogue: Callable[[], Catalogue]):
        self._catalogue = catalogue

    async def on_read_resource(self, context, call_next):
        try:
            return await call_next(context)
        except (NotFoundError, FolderNotFound) as miss:
            uri = str(context.message.uri)
            catalogue, scope, a = (
                self._catalogue(),
                requested_scope(),
                requested_addressing(),
            )
            hint = catalogue.hint(a.canonical(uri), scope)
            if hint is None and isinstance(miss, FolderNotFound):
                # A folder inside a skill, which kubed-mcp named: its index.
                hint = miss.hint
            if hint is None:
                raise
            hint = a.text(hint)
            raise MCPError(
                code=INVALID_PARAMS,
                message=f"Resource not found: {uri!r}. {hint}",
                data={"uri": uri},
            ) from None


def canonical(uri: str, a: Addressing) -> str:
    """The address a sent URI names: the request's prefix off, dot segments resolved.

    What every provider is asked for, so a skill's file is found through
    ``../sibling/SKILL.md`` and through ``kb+skill://`` (SKL-13, SKL-42) by a
    provider that matches addresses exactly. Anything not ``skill://`` is left
    as it was sent.
    """
    if _ENCODED_SLASH.search(uri):
        # kb never decodes an escape (SKL-13), so ``%2F`` is no separator and
        # names nothing kb serves; FastMCP's skills provider would decode it.
        return NOWHERE
    uri = a.canonical(uri)
    parsed = parse(uri)
    if parsed is None:
        return uri
    library, path = parsed
    return f"skill://{library}/{path}" if path else f"skill://{library}"


class ReadTheAddress(Middleware):
    """Hand every provider the canonical address of what the client sent.

    A read's result still carries the URI the client sent (SKL-36): FastMCP
    answers with the request's own. ``resources/directory/read`` resolves as a
    read does. ``skills/get`` only loses the prefix: a skill is got by its
    exact ``SKILL.md`` address (SKL-49).
    """

    async def on_read_resource(self, context, call_next):
        uri = str(context.message.uri)
        address = canonical(uri, requested_addressing())
        if address != uri:
            message = context.message.model_copy(update={"uri": address})
            context = context.copy(message=message)
        return await call_next(context)

    async def on_request(self, context, call_next):
        message = context.message
        if context.method in ("skills/get", "resources/directory/read") and (
            isinstance(message, Mapping) and isinstance(message.get("uri"), str)
        ):
            a = requested_addressing()
            uri = message["uri"]
            if context.method == "skills/get":
                # It matches the exact URI already, escapes and all.
                uri = a.canonical(uri)
            else:
                uri = canonical(uri, a)
            if uri != message["uri"]:
                context = context.copy(message={**message, "uri": uri})
        return await call_next(context)


class HideMirrorTools(Middleware):
    """Drop the mirroring tools from ``tools/list`` for clients that have the
    native feature each one mirrors.

    Every tool this server has is a mirror: ``list_prompts``/``get_prompt``
    stand in for MCP prompts, and kubed-mcp's ``list_resources``/
    ``read_resource`` for MCP resources, which kubed-mcp hides itself (DLV-6).
    Advertising both shapes to a client that has the real one is noise -- two
    ways to ask one question, and the model has to pick one.

    Filtering the listing rather than registering conditionally is what keeps
    one server object correct for every client at once. The decision depends on
    who is asking, so it can only be made per request; registration happens once
    at boot, when there is no asker.

    They stay *callable* either way. Hiding a tool from a listing is a
    presentation choice; refusing to run one a client already knows about would
    be a different and worse contract.
    """

    def __init__(self, mirrors: dict[str, Callable[[], bool]]):
        # tool name -> "does this client have the native feature it mirrors?"
        self.mirrors = dict(mirrors)

    async def on_list_tools(self, context, call_next):
        tools = await call_next(context)
        return [
            tool
            for tool in tools
            if tool.name not in self.mirrors or not self.mirrors[tool.name]()
        ]


def register(mcp: QuickMCP, catalogue: Callable[[], Catalogue]) -> None:
    """Publish the catalogue as ``skill://`` resources, read per request.

    After the plugin layer's skills provider, so a skill's file is always its.
    The hints run outside the address, so an error names the URI the client
    sent: kb's own first, then kubed-mcp's for a folder inside a skill.
    """
    mcp.add_provider(CatalogueProvider(catalogue))
    mcp.add_middleware(NameTheFileToRead(catalogue))
    mcp.add_middleware(ReadTheAddress())
    mcp.add_middleware(NameTheIndex())
