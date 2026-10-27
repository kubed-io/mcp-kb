"""How one request addresses the catalogue: a gateway prefix and a pinned library.

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


@dataclass(frozen=True)
class Addressing:
    prefix: str = ""
    library: str = ""

    @classmethod
    def parse(cls, prefix: str = "", library: str = "") -> Addressing:
        prefix = (prefix or "").strip()
        if not _PREFIX.match(prefix):
            prefix = ""
        return cls(prefix, (library or "").strip())

    def structured(self, uri: str) -> str:
        """A URI in a structured field: shortened by the pin, never prefixed."""
        head = f"{_SCHEME}{self.library}/"
        if self.library and uri.startswith(head):
            return _SCHEME + uri[len(head) :]
        return uri

    def text(self, body: str) -> str:
        """Addresses inside prose, which a gateway does not rewrite for us."""
        if self.library:
            lib = re.escape(self.library)
            # Library names are [a-z0-9-], so that is the boundary of a bare one.
            body = re.sub(
                rf"{re.escape(_SCHEME)}{lib}(?:/|(?![a-z0-9-]))",
                f"{self.prefix}{_SCHEME}",
                body,
            )
        elif self.prefix:
            body = body.replace(_SCHEME, f"{self.prefix}{_SCHEME}")
        return body

    def incoming(self, uri: str) -> list[str]:
        """Canonical candidates for an address a client sent, best first."""
        if self.prefix and uri.startswith(self.prefix + _SCHEME):
            uri = uri[len(self.prefix) :]
        if not self.library or not uri.startswith(_SCHEME):
            return [uri]
        rest = uri[len(_SCHEME) :]
        found = [f"{_SCHEME}{self.library}/{rest}"]
        if rest.split("/", 1)[0] == self.library:
            found.append(uri)
        return found

    def first(self, uri: str, look: Callable[[str], T | None]) -> T | None:
        for candidate in self.incoming(uri):
            hit = look(candidate)
            if hit is not None:
                return hit
        return None


DEFAULT = Addressing()
