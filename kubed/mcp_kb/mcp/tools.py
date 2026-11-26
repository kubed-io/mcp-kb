"""The tools: kubed-mcp's resource pair, and nothing else.

``list_resources`` returns the rows ``resources/list`` returns and
``read_resource`` takes the URI ``resources/read`` takes, over every resource
this server has -- the plugin layer's ``SKILL.md`` rows, kb's ``_files.md`` and
every file read, alike. Both are kubed-mcp's (DLV-6): it lists the pair only for
a client that turned resources off (``?resources=off``, ``Kb-Resources: off`` or
``X-MCP-Resources: off``), and refuses a server tool of either name (DLV-7), so
kb defines neither and registers no tool. A client with no resources reads a
prompt's file the same way, once ``Kb-Listed: prompts`` lists it.

An agent that knows how to drive MCP resources already knows how to drive these,
because the vocabulary is the same one -- list addresses, read an address -- and
progressive disclosure lives in the address space rather than in the tool list::

    list_resources()
        -> a SKILL.md row per skill, and each library's _files.md
    read_resource("skill://grafana/grafana-lgtm/_index.md")
        -> that folder's skills, as URIs (an index reads and is not listed)
    read_resource("skill://grafana/grafana-lgtm/loki/SKILL.md")
        -> the instructions to follow
"""

from __future__ import annotations

# kubed-mcp's resource pair (DLV-6): named here for the wiki's tool page, and
# never defined here.
RESOURCE_TOOLS = ("list_resources", "read_resource")

# The names kubed-mcp reads its delivery inputs under with kb's ``Kb`` prefix
# (DLV-16): for the wiki's generator and its test, never to read a request.
RESOURCES_PARAM = "resources"
RESOURCES_HEADER = "kb-resources"
LISTED_PARAM = "listed"
LISTED_HEADER = "kb-listed"
