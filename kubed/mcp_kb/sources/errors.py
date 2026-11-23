"""``SourceError`` lives on its own so ``file.py`` need not import the package
``__init__`` that imports ``file.py`` -- a straight import, not a circular one
resolved by deferring it to call time.
"""

from __future__ import annotations


class SourceError(ValueError):
    """A source could not be materialised.

    A ``ValueError`` because that is a failure kubed-mcp's ``add_plugin`` reports
    for a loader. Its ``PluginError`` is one too, but importing it would bring
    FastMCP into ``catalogue/`` (``tests/test_boundaries.py``).
    """


class AccessRefused(SourceError):
    """The server answered, and refused this source's credentials.

    Told apart from every other failure because it is the one a wait does not
    fix and a person does: an unreachable remote comes back by itself, a
    rejected password or an account not yet let in does not.
    """
