"""The skills, served by FastMCP's skills provider from kb's ``Catalogue`` (MD-55).

A catalogue, in FastMCP's sense, is the set of skills a server serves, keyed by
a path whose last segment is the skill's name. kb's is every skill of every
library in the caller's scope, keyed by its address, so
``grafana/grafana-lgtm/loki`` serves ``skill://grafana/grafana-lgtm/loki/SKILL.md``.
``SkillCatalogue.load_skills()`` builds it per request from kb's own
``Catalogue``, and FastMCP and kubed-mcp serve the rest: every file, the
``_manifest``, the Skills extension's entries and digests, and the folders a
skill's files sit in (``_index.json``, ``_index.md``, ``resources/directory/read``).

A ``SKILL.md`` reads differently under each scope and each gateway prefix:
plugin-root placeholders and qualified names resolve through what the scope
admits, and the prefix is written into every file's text. So the text is
rewritten when the catalogue is built, never on read (MD-59), and the digests
an entry carries are digests of the bytes a read returns. A built catalogue is
kept per (generation, scope, prefix), and rebuilt when a live skill in it moves.

A skill FastMCP refuses (MD-56: its frontmatter, its paths, its size, or it sits
inside another skill) is not served at all. It is taken out of the catalogue
every other surface reads (``catalogue()``), so no index, listing, hint or
rewritten pointer names a skill that does not read.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from collections.abc import Callable
from urllib.parse import unquote

from kubed.mcp import Resource, ResourceContent, ResourceResult, TextResource
from kubed.mcp.protocol import VersionSpec
from kubed.mcp.skills import EntryOnlySkillProvider, Skill, SkillFileResource

from ..catalogue.addressing import Addressing
from ..catalogue.uris import (
    INDEX,
    MANIFEST,
    MEMO_LIMIT,
    SCHEME,
    Catalogue,
    mime_for,
)
from .request import requested_addressing, requested_scope
from .scope import EVERYTHING, Scope

log = logging.getLogger(__name__)

# One skill's files as they read, keyed by path.
Texts = dict[str, str]


class ServedFile(SkillFileResource):
    """A skill's file with kb's media type, and always as text.

    Every file kb serves is text: it is read as UTF-8 with bad bytes replaced
    (SKL-22), so the bytes always decode. FastMCP would send a ``.sh`` or a
    ``.json`` as a blob and guess ``application/octet-stream`` for an extension
    it does not know; kb's rule is a guess, else ``text/markdown`` (SKL-23).
    Still a ``SkillFileResource`` with the same ``file``, so the Skills
    extension offers the entry.
    """

    async def read(self) -> ResourceResult:
        content = await self.provider.read_file(self)
        return ResourceResult(
            [ResourceContent(content.decode("utf-8"), mime_type=self.mime_type)]
        )


class _Generation:
    """What one snapshot's catalogue serves as skills, built as requests ask."""

    def __init__(self, source: Catalogue):
        self.source = source
        # The skills FastMCP refuses, by address, with why.
        self.refused: dict[str, str] = {}
        # Each skill as it reads with no scope and no prefix, to build from.
        self.built: dict[str, tuple[Texts, Skill]] = {}
        self.memo: OrderedDict[tuple[Scope, str], tuple[tuple, dict[str, Skill]]] = (
            OrderedDict()
        )
        self.catalogue = source


def _reason(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        return "; ".join(e["msg"].removeprefix("Value error, ") for e in errors())
    return str(exc) or type(exc).__name__


def _skill(texts: Texts, like: tuple[Texts, Skill] | None = None) -> Skill:
    """The skill ``texts`` make, sharing the bytes of each file ``like`` has too."""
    files: dict[str, bytes] = {}
    for path, text in texts.items():
        if like is not None and like[0].get(path) == text:
            files[path] = like[1].files[path]
        else:
            files[path] = text.encode("utf-8")
    return Skill.from_files(files)


class SkillCatalogue(EntryOnlySkillProvider):
    """kb's skills, for the request's scope and prefix, from the current snapshot.

    ``catalogue`` is a getter, as everywhere in kb: a refresh swaps the
    snapshot, and the first request after it builds the new generation.
    """

    def __init__(self, catalogue: Callable[[], Catalogue]) -> None:
        super().__init__()
        self._source = catalogue
        self._generation: _Generation | None = None

    def catalogue(self) -> Catalogue:
        """The catalogue serving now, less the skills FastMCP refuses."""
        return self._current().catalogue

    def refused(self) -> dict[str, str]:
        """The skills this generation does not serve, by address, with why."""
        return dict(self._current().refused)

    def _current(self) -> _Generation:
        source = self._source()
        generation = self._generation
        if generation is None or generation.source is not source:
            generation = _Generation(source)
            self._check(generation)
            self._generation = generation
        return generation

    @staticmethod
    def _check(generation: _Generation) -> None:
        """Build every skill as it reads unscoped, and set aside what FastMCP refuses.

        A skill inside another is refused: FastMCP's catalogue has no room for
        one, and the outer skill's files already hold it.
        """
        source = generation.source
        skills = source.visible_skills()
        addresses = {s.address for s in skills}
        for skill in skills:
            parts = skill.address.split("/")
            outer = next(
                (
                    "/".join(parts[:cut])
                    for cut in range(1, len(parts))
                    if "/".join(parts[:cut]) in addresses
                ),
                None,
            )
            if outer is not None:
                generation.refused[skill.address] = (
                    f"it sits inside the skill at {outer}"
                )
                continue
            texts = source.skill_files(skill)
            try:
                generation.built[skill.address] = (texts, _skill(texts))
            except ValueError as exc:
                generation.refused[skill.address] = _reason(exc)
        for address, reason in sorted(generation.refused.items()):
            log.error(
                "skill %s is not a valid Agent Skill, so it is not served: %s",
                address,
                reason,
            )
        generation.catalogue = source.without(sorted(generation.refused))

    async def load_skills(self) -> dict[str, Skill]:
        return self.skills(requested_scope(), requested_addressing())

    def skills(self, scope: Scope = EVERYTHING, a: Addressing | None = None) -> dict:
        """The catalogue for ``scope`` and the prefix ``a``, built once per key.

        Kept until the generation goes, the oldest dropped past ``MEMO_LIMIT``
        keys, and built again when a live skill in scope has moved since.
        """
        a = a or Addressing()
        generation = self._current()
        catalogue = generation.catalogue
        stamp = catalogue.live_stamp(scope)
        key = (scope, a.prefix)
        kept = generation.memo.get(key)
        if kept is not None and kept[0] == stamp:
            generation.memo.move_to_end(key)
            return kept[1]
        skills: dict[str, Skill] = {}
        for skill in catalogue.visible_skills(scope):
            texts = {
                path: a.text(text)
                for path, text in catalogue.skill_files(skill, scope).items()
            }
            like = generation.built.get(skill.address)
            if like is not None and like[0] == texts:
                skills[skill.address] = like[1]
                continue
            try:
                skills[skill.address] = _skill(texts, like)
            except ValueError as exc:
                # Only a rewrite can get here, the skill having passed unscoped:
                # a prefix that takes a description past 1024 characters.
                log.warning(
                    "skill %s is not served under this scope: %s",
                    skill.address,
                    _reason(exc),
                )
        generation.memo[key] = (stamp, skills)
        while len(generation.memo) > MEMO_LIMIT:
            generation.memo.popitem(last=False)
        return skills

    async def _list_resources(self) -> list[Resource]:
        # kb's listing is indexes (SKL-14), and its full listing names each
        # SKILL.md (SKL-16): both are CatalogueProvider's rows.
        return []

    async def _get_resource(
        self, uri: str, version: VersionSpec | None = None
    ) -> Resource | None:
        resource = await super()._get_resource(uri, version)
        if isinstance(resource, SkillFileResource):
            fields = {
                name: getattr(resource, name) for name in type(resource).model_fields
            }
            fields["mime_type"] = mime_for(resource.file_path)
            return ServedFile(**fields)
        manifest = getattr(resource, "manifest", None)
        if manifest is not None:
            # FastMCP's, but naming the skill by its address as kb always has
            # (SKL-24): its name alone is not unique across libraries.
            path = unquote(uri)[len(SCHEME) : -len(MANIFEST) - 1]
            files = [
                {"path": p, "size": f.size, "hash": f.digest}
                for p, f in manifest.files.items()
            ]
            return TextResource(
                uri=uri,
                name=resource.name,
                description=resource.description,
                mime_type="application/json",
                text=json.dumps({"skill": path, "files": files}, indent=2),
            )
        if isinstance(resource, TextResource) and uri.endswith(f"/{INDEX}"):
            # A folder's index is text a client reads, so it carries the prefix.
            text = requested_addressing().text(resource.text)
            return resource.model_copy(update={"text": text})
        return resource
