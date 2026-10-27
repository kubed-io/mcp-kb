"""How one request addresses the catalogue: the gateway prefix.

Pure on purpose: it only rewrites strings, so every MCP surface can share it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")

_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*\+$")
_SCHEME = "skill://"
# Not the tail of a longer scheme, or of an address already prefixed.
_LEFT = r"(?<![A-Za-z0-9+.-])"
_ANY = re.compile(_LEFT + re.escape(_SCHEME))


@dataclass(frozen=True)
class Addressing:
    prefix: str = ""

    @classmethod
    def parse(cls, prefix: str = "") -> Addressing:
        prefix = (prefix or "").strip()
        return cls(prefix if _PREFIX.match(prefix) else "")

    def text(self, body: str) -> str:
        """Addresses inside prose, which a gateway does not rewrite for us."""
        return _ANY.sub(f"{self.prefix}{_SCHEME}", body) if self.prefix else body

    def incoming(self, uri: str) -> list[str]:
        """Canonical candidates for an address a client sent, best first."""
        if self.prefix and uri.startswith(self.prefix + _SCHEME):
            return [uri[len(self.prefix) :]]
        return [uri]

    def first(self, uri: str, look: Callable[[str], T | None]) -> T | None:
        for candidate in self.incoming(uri):
            hit = look(candidate)
            if hit is not None:
                return hit
        return None


DEFAULT = Addressing()
