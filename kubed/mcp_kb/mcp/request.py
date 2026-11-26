"""What the current request says about itself.

Two kinds of question, both answered from the HTTP request and both meaningless off it:
*what slice of the catalogue may this client see*, and *which MCP features
can it use natively*. They
are read here rather than in the handlers because both halves of the server --
the resources and kubed-mcp's tools that mirror them -- have to agree on the answers,
and a second reader is how the two halves drift apart.

Every helper degrades to the permissive default outside an HTTP request, which
is what stdio is: no headers, no query string, nothing to narrow by.
"""

from __future__ import annotations

from kubed.mcp.protocol import client_supports_extension
from kubed.mcp.request import request_values

from .scope import Scope

# The client capability a host declares when it builds its own skill list.
EXTENSION_ID = "io.modelcontextprotocol/skills"
# The draft Agent Discovery Extension, beside it: agents/list and agents/get.
AGENTS_EXTENSION_ID = "io.modelcontextprotocol/agents"

# Per-request scope, set once in a client's connection config -- which is how
# one deployment serves several narrowly-scoped agents. Each setting is a
# header and a query parameter, plus the older names, still accepted.
LIBRARY_PARAM = "library"
LIBRARY_HEADER = "kb-library"
LIBRARY_ALIAS = "x-skill-library"
CATEGORY_PARAM = "category"
CATEGORY_HEADER = "kb-category"
CATEGORY_ALIAS = "x-skill-categories"
CATEGORY_PARAM_ALIAS = "categories"
TAG_PARAM = "tag"
TAG_HEADER = "kb-tag"
TAG_ALIAS = "x-skill-tags"
TAG_PARAM_ALIAS = "tags"

# How a client declares it cannot read resources: what kubed-mcp lists its
# resource mirror by (DLV-6), and what the instructions are worded for.
RESOURCES_PARAM = "resources"
RESOURCES_HEADER = "x-mcp-resources"
RESOURCES_KB_HEADER = "kb-resources"
_OFF = ("off", "false", "0", "no", "none")

def _read(
    header: str,
    param: str,
    alias: str | None = None,
    param_alias: str | None = None,
) -> list[str]:
    """What this request says for one setting: every value, or none at all.

    Precedence: the header, its older name, the query parameter, its older
    name. A header is set in a credential, by an admin, where a parameter rides
    on a URL somebody may paste without it. Off HTTP there is neither, and an
    empty list is what every caller reads as "not narrowed, not declared".
    """
    http = request_values()
    if http is None:
        return []
    params, headers = http
    for source, name in (
        (headers, header),
        (headers, alias),
        (params, param),
        (params, param_alias),
    ):
        found = [value for value in source.get(name or "", []) if value]
        if found:
            return found
    return []


def requested_scope() -> Scope:
    """The slice of the catalogue this request is restricted to.

    Read from the MCP URL (``?library=grafana&category=observability``) or
    headers (``Kb-Library``, ``Kb-Category``, ``Kb-Tag``); the older
    ``X-Skill-Library``, ``X-Skill-Categories`` and ``X-Skill-Tags`` (and
    ``?categories=``, ``?tags=``) still work. It is a ceiling set by whoever
    configured the client, not a suggestion the model can widen. One library:
    it is the URI's first segment, so several would be a different request.
    """
    library = _read(LIBRARY_HEADER, LIBRARY_PARAM, LIBRARY_ALIAS)
    return Scope.parse(
        library[0] if library else "",
        _read(
            CATEGORY_HEADER, CATEGORY_PARAM, CATEGORY_ALIAS, CATEGORY_PARAM_ALIAS
        ),
        _read(TAG_HEADER, TAG_PARAM, TAG_ALIAS, TAG_PARAM_ALIAS),
    )


def _declared_on(header: str, param: str, kb_header: str) -> bool:
    """True unless the client said ``off`` for this capability.

    ``Kb-<Name>`` wins over ``X-MCP-<Name>``, then the query parameter.
    """
    declared = _read(kb_header, param, header)
    return not declared or declared[0].strip().lower() not in _OFF


def client_reads_resources() -> bool:
    """Whether this caller can be expected to read MCP resources.

    Defaults to true -- the assumption is that a client is spec-complete, and a
    client that is not says so, with ``?resources=off`` on the MCP URL or an
    ``X-MCP-Resources: off`` header.
    """
    return _declared_on(RESOURCES_HEADER, RESOURCES_PARAM, RESOURCES_KB_HEADER)


def declared_on_initialize(context) -> bool:
    """Whether the ``initialize`` request declared the Skills extension."""
    params = getattr(getattr(context, "message", None), "params", None)
    extensions = getattr(getattr(params, "capabilities", None), "extensions", None)
    return bool(extensions) and EXTENSION_ID in extensions


def declared_on_discover(context) -> bool:
    """Whether a 2026-07-28 request's ``_meta`` declared it; no session, no."""
    try:
        session = context.fastmcp_context.session
        return client_supports_extension(session, EXTENSION_ID)
    except (RuntimeError, AttributeError):  # no context or session: not declared
        return False
