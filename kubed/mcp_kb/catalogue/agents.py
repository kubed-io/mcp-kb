"""What kubed-mcp's plugin layer serves of one Claude Code subagent file.

An agent is a markdown file: YAML frontmatter naming it and saying when to use
it, then the system prompt as the body. kubed-mcp's plugin layer is the one
reader of an agent file (AGT-6, AGT-8): kb's harvest records each agent file's
path and nothing else, and kb's ``_meta`` key reads the frontmatter through the
layer's own parser (``mcp/skills.py``, AGT-9).

``ServedAgent`` is what the plugin layer serves of one agent file, as kb
records it: its name and file as the layer reports them, admitted by a
``Scope`` exactly as a skill or a prompt of the same plugin is (AGT-15). No
FastMCP here.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..mcp.scope import Scope


@dataclass(frozen=True)
class ServedAgent:
    """One agent the plugin layer serves: the name and the file it reports.

    ``name`` is the layer's (``AgentFile.name``), a rename included, and
    ``path`` its file, relative to the plugin root (``AgentFile.path``).
    ``plugin`` is kb's plugin id, and ``category``, ``tags`` and
    ``library_categories`` are that plugin's, in ``library``: what a scope
    admits it on.
    """

    name: str
    library: str
    plugin: str
    path: str
    category: str | None
    tags: frozenset[str]
    library_categories: frozenset[str] = frozenset()

    def admitted(self, scope: Scope) -> bool:
        return scope.admits(
            self.library,
            self.category,
            self.tags,
            library_categories=self.library_categories,
        )
