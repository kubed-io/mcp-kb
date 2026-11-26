"""The ``skill://`` address space, and the catalogue that answers it.

Everything this server serves has one address. A library index, a skill's
instructions, a file a skill references, a file the *library* references --
each is a ``skill://`` URI, and reading one is the only operation there is.

That is not a stylistic choice. MCP already has a read-a-thing primitive, and a
model already knows how to drive it: list the resources, read a URI. A server
that invents ``read_skill(skill, file)`` alongside it is asking the model to
learn a second vocabulary for the same act. So the catalogue below is written
once, in URIs, and both halves of the protocol are thin projections of it --
``resources.py`` serves it as resources, and kubed-mcp's ``list_resources`` and
``read_resource`` read those same resources for clients that have none.

The grammar follows the MCP Skills extension (SEP-2640), which is the whole
API::

    skill://<library>/<folder>/<name>/SKILL.md    a skill's instructions
    skill://<library>/<folder>/<name>/_manifest   what else that skill ships
    skill://<library>/<folder>/<name>/<file>      one of those files
    skill://<library>/_index.md                   the folders and skills in a library
    skill://<library>/<folder>/_index.md          the folders and skills in a folder
    skill://<library>/_files.md                   files outside every skill
    skill://<library>/<file>                      one of those

``<folder>`` is the skill's plugin's place in the library: empty for the
library's main plugin, the plugin's name for any other
(``snapshot.folder_for``). It never comes from where the skill sits inside its
plugin. The last segment before the file is always the skill's name. A skill is
found by the longest prefix of the path that names one, so a nested skill wins
over the skill whose directory holds it.

An index lists what is *directly* under it: a library's, each folder as its own
``_index.md`` with how many skills are in it, then each of the main plugin's
skills as its ``SKILL.md``; a folder's, its plugin's skills. A library of fifty
skills in seven folders is then seven lines, and the reader chooses which one to
open, rather than paying for every skill's description to find the folder it
wanted.

Every other address is a directory -- a library, a folder, a skill's root --
and serves nothing, as on any other skill server. ``hint`` says which file to
read instead, for the error a caller sees, and ``directory`` lists a library's
or a folder's direct children, for ``resources/directory/read`` and
``_index.json``.

A skill's own files, its ``_manifest`` and the folders inside it are served by
kubed-mcp's plugin layer, which reads each plugin itself; kb's rewriter
renders a ``SKILL.md`` through ``instructions`` and an agent's body through
``agent_instructions``, and ``agent_meta`` is kb's key in an agent's ``_meta``.

Nothing here imports FastMCP. Absent content is ``None``, never an exception, so
a caller in the resource half can raise and a caller in the tool half can
explain -- and the scoping rule stays in one place either way.
"""

from __future__ import annotations

import logging
import mimetypes
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..mcp.scope import EVERYTHING, Scope
from . import placeholders
from .harvest import hidden, readable
from .names import QualifiedNames, split_frontmatter
from .skills import LibraryFiles, Skill, SkillIndex

log = logging.getLogger(__name__)

SCHEME = "skill://"
MAIN_FILE = "SKILL.md"
MANIFEST = "_manifest"
INDEX = "_index.md"
INDEX_JSON = "_index.json"
LIBRARY_FILES = "_files.md"
# Names the server generates at any folder. A file called one of these is
# skipped by the harvest and never served by the plugin-root fallback: where
# there is a generated body it answers first, and ``/health`` says as much.
RESERVED_NAMES = frozenset({INDEX, INDEX_JSON, LIBRARY_FILES})
# What a folder is, as a directory resource (SEP-2640).
DIRECTORY = "inode/directory"
# Distinct scopes a catalogue remembers listings for before starting over.
MEMO_LIMIT = 64
# Where an agent definition says what kb knows of it (AGT-9).
AGENT_META = "io.kubed.mcp-kb/agent"


def _count(n: int, noun: str = "skill") -> str:
    """``3 skills`` / ``1 skill`` -- an index row is prose, so it reads as prose."""
    return f"{n} {noun}" + ("" if n == 1 else "s")


mimetypes.add_type("text/markdown", ".md")


@dataclass(frozen=True)
class Entry:
    """One row of a resource listing -- the shape both halves publish.

    ``uri``, ``name``, ``description`` and ``mime_type`` are the four fields
    ``resources/list`` returns, so the resource tools are the same rows and not a
    translation of them. ``tags`` rides alongside for ``resources.py`` to carry
    onto the ``TextResource`` it builds; it is not one of the four and never
    appears in ``as_dict``. A ``_files.md`` row is tagged with its library and
    ``"index"``.
    """

    uri: str
    name: str
    description: str
    mime_type: str
    tags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, str]:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mime_type,
        }


def parse(uri: str) -> tuple[str, str] | None:
    """Split a ``skill://`` URI into its library and the path below it.

    Returns ``(library, "")`` for a bare library and ``(library, path)`` for
    anything under one, or None when the string is not a ``skill://`` URI at
    all. Percent-decoding is not done here: the segments this server mints are
    already path-safe, and decoding would be one more way for ``%2e%2e`` to
    become ``..``.

    The path's dot segments are resolved here, once, for every read, hint and
    media type: a skill links its sibling as ``../other/SKILL.md``, and a
    client that resolves that without normalising sends the ``..`` as written.
    Every check downstream -- scope, containment, hidden files -- then runs on
    the address the URI names rather than on its spelling.
    """
    if not uri.startswith(SCHEME):
        return None
    rest = uri[len(SCHEME) :].strip("/")
    if not rest:
        return None
    head, _, tail = rest.partition("/")
    return head, _remove_dot_segments(tail)


def resolved(uri: str) -> str | None:
    """The address ``parse`` reads: ``skill://<library>/<path>``, dots resolved.

    A bare library is ``skill://<library>``. None when ``parse`` gives None.
    """
    parsed = parse(uri)
    if parsed is None:
        return None
    library, path = parsed
    return f"{SCHEME}{library}/{path}" if path else f"{SCHEME}{library}"


def climbs(uri: str) -> bool:
    """Whether the dot segments of ``uri``, resolved over the whole path, leave
    an address other than the one ``resolved`` names.

    ``resolved`` clamps a ``..`` at the library; a resolver that counts the
    library as a segment does not, so a ``..`` that reaches it names another
    address there. False for anything ``resolved`` cannot read.
    """
    address = resolved(uri)
    if address is None:
        return False
    whole = _remove_dot_segments(uri[len(SCHEME) :].strip("/"))
    return whole != address[len(SCHEME) :]


def _remove_dot_segments(path: str) -> str:
    """RFC 3986 ``remove_dot_segments`` on the path below the library.

    ``.`` goes, ``..`` takes the segment before it, and a ``..`` with nothing
    before it is dropped -- clamped at the root exactly as a normalising client
    clamps it. The library is the URI's authority, not a path segment, so no
    number of ``..`` can reach a different one.
    """
    kept: list[str] = []
    for segment in path.split("/"):
        if segment == "..":
            if kept:
                kept.pop()
        elif segment != ".":
            kept.append(segment)
    return "/".join(kept).strip("/")


def uri_for(skill: Skill, file: str = MAIN_FILE) -> str:
    """The address of one file of a skill, its instructions by default."""
    return f"{SCHEME}{skill.address}/{file}"


def index_uri(library: str, folder: str = "") -> str:
    """The index of a library, or of one folder in it."""
    return f"{SCHEME}{'/'.join(p for p in (library, folder) if p)}/{INDEX}"


def _in(skill: Skill, folder: str) -> bool:
    """Whether ``skill`` sits in ``folder`` or anywhere below it; ``""`` is all."""
    return not folder or skill.folder == folder or skill.folder.startswith(f"{folder}/")


def _children(skills: list[Skill], folder: str) -> dict[str, int]:
    """The folders directly in ``folder``, each with how many skills are below it.

    One definition for the folders the indexes name.
    """
    prefix = f"{folder}/" if folder else ""
    found: dict[str, int] = {}
    for skill in skills:
        if skill.folder != folder and _in(skill, folder):
            child = prefix + skill.folder[len(prefix) :].split("/")[0]
            found[child] = found.get(child, 0) + 1
    return dict(sorted(found.items()))


def mime_for(path: str) -> str:
    """The media type of a path, defaulting to markdown rather than octets.

    Everything here is prose unless it says otherwise, and a client told
    ``application/octet-stream`` may decline to show a file it could read.
    """
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "text/markdown"


def tidy(text: str) -> str:
    """Text with no blank line in it and no trailing space on any line.

    Blank lines separate the sections of the instructions, and a description
    quotes upstream text, so one must not be able to open a section.
    """
    lines = (line.rstrip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


@dataclass(frozen=True)
class LibraryText:
    """What a library says about itself, apart from its skills."""

    name: str
    description: str = ""
    notes: str = ""
    list_skills: bool = True
    # (plugin id, plugin name) in library order: what a qualified name matches.
    plugins: tuple[tuple[str, str], ...] = ()


class Catalogue:
    """The address space: what is listed, and what each URI resolves to.

    Wraps ``SkillIndex`` and ``LibraryFiles`` rather than replacing them --
    they still own what a skill is and who may see one. This adds the one thing
    a URI space needs on top: a total function from address to content, with the
    request scope applied on every single call.

    ``scope`` is threaded through every method for that reason. It is the slice
    a scoped client is restricted to, and a method that forgot it would hand
    that client somebody else's skills -- so there is no method here that can be
    called without deciding about it.
    """

    def __init__(
        self,
        index: SkillIndex,
        resources: LibraryFiles,
        revalidate: Callable[[Path], None] | None = None,
        libraries: Sequence[LibraryText] = (),
    ):
        self._libraries = list(libraries)
        self._index = index
        self._resources = resources
        self._revalidate = revalidate
        self._memo: dict[Scope, list[Entry]] = {}
        # A skill's files and their text, unless it is live: an export never
        # changes under a generation, so each is read once however many ask.
        self._files: dict[Path, dict[str, Path]] = {}
        self._texts: dict[Path, str] = {}

    # -- listing ------------------------------------------------------------

    def entries(self, scope: Scope = EVERYTHING) -> list[Entry]:
        """What kb lists itself: each library's ``_files.md``, where one has files.

        The skills' own rows are the plugin layer's (SKL-14), so none is listed
        here and none twice. ``_files.md`` is kb's alone: a library with a
        library file in scope gets one row.

        Memoised per scope. A ``Catalogue`` is built per snapshot and thrown
        away with it, so the memo cannot outlive the data it summarises -- which
        is the only reason caching a listing is safe here at all. The list is
        shared with every other caller of the same scope: read it, never edit it.
        """
        memo = self._memo.get(scope)
        if memo is not None:
            return memo
        entries = self._entries(scope)
        if not entries and scope:
            # An unknown scope yields nothing and cost nothing to find out.
            # Memoising it would let a client grow this dict one bogus header
            # at a time.
            return entries
        if len(self._memo) >= MEMO_LIMIT:
            # Tag combinations are the client's choice, so the set of real
            # scopes is not bounded by the catalogue. Dropping the lot is
            # cheaper than an LRU and a listing is quick to rebuild.
            self._memo.clear()
        self._memo[scope] = entries
        return entries

    def _entries(self, scope: Scope) -> list[Entry]:
        return [
            Entry(
                f"{SCHEME}{library}/{LIBRARY_FILES}",
                f"{library}/{LIBRARY_FILES}",
                f"Files the {library} library ships outside any skill,"
                " which its skills reference.",
                "text/markdown",
                tuple(sorted({library, "index"})),
            )
            for library in sorted(self._resources.libraries)
            if self._library_files(library, scope)
        ]

    # -- what a scope may see -----------------------------------------------

    def without(self, addresses: Sequence[str]) -> Catalogue:
        """The same catalogue less the skills at ``addresses``.

        For a server that refuses to serve some skills: everything that lists,
        hints at or rewrites a pointer to one is answered from what is left,
        so nothing names a skill the server will not read.
        """
        if not addresses:
            return self
        narrowed = Catalogue(
            self._index.without(addresses),
            self._resources,
            self._revalidate,
            self._libraries,
        )
        # The same trees, so what one has read the other need not read again.
        narrowed._files = self._files
        narrowed._texts = self._texts
        return narrowed

    def visible_skills(self, scope: Scope = EVERYTHING) -> list[Skill]:
        """Every skill ``scope`` admits, by address."""
        return sorted(self._index.visible(scope), key=lambda s: s.address)

    def skill_files(self, skill: Skill) -> dict[str, str]:
        """Every file of ``skill`` as it reads on disk, keyed by path, sorted.

        The files are the regular ones under the skill's directory that are not
        hidden and resolve inside it, nested skills' files included. A file
        that cannot be read is left out. Raw text: kb's rewriter renders a
        ``SKILL.md`` when the plugin layer builds it (``instructions``).
        """
        return {
            file: self._text(skill, target)
            for file, target in self._files_of(skill).items()
        }

    def _files_of(self, skill: Skill) -> dict[str, Path]:
        """``skill``'s files and where each reads from, walked once unless live."""
        files = None if skill.live else self._files.get(skill.path)
        if files is None:
            files = {}
            for path in sorted(skill.path.rglob("*")):
                relative = path.relative_to(skill.path)
                if not path.is_file() or hidden(relative):
                    continue
                target = readable(skill.path, relative.as_posix())
                if target is not None:
                    files[relative.as_posix()] = target
            if not skill.live:
                self._files[skill.path] = files
        return files

    def live_stamp(self, skill: Skill) -> tuple:
        """What ``skill``'s files hold on disk now, revalidated if it is live.

        Empty for a skill that is not live: an export never moves under a
        generation. A server that keeps what it read of a live skill reads it
        again when this changes (SKL-37).
        """
        if not skill.live:
            return ()
        stamp = []
        for path in sorted(skill.path.rglob("*")):
            if not path.is_file() or hidden(path.relative_to(skill.path)):
                continue
            if self._revalidate is not None:
                self._revalidate(path)
            try:
                stat = path.stat()
            except OSError:
                continue
            stamp.append((str(path), stat.st_mtime_ns, stat.st_size))
        return tuple(stamp)

    def selected(self, scope: Scope = EVERYTHING) -> list[LibraryText]:
        """Libraries with a skill visible in ``scope``: constructor order, then
        any the constructor never heard of, by name."""
        present = {s.library for s in self._index.visible(scope)}
        known = {t.name for t in self._libraries}
        return [t for t in self._libraries if t.name in present] + [
            LibraryText(name) for name in sorted(present - known)
        ]

    def skill_paths(self, library: str, scope: Scope = EVERYTHING) -> list[str]:
        """Each visible skill's address below its library, sorted."""
        prefix = f"{library}/"
        found = self._in_library(library, scope)
        return sorted(s.address.removeprefix(prefix) for s in found)

    def plugin_skill_dirs(
        self, library: str, plugin: str, scope: Scope = EVERYTHING
    ) -> dict[str, str]:
        """One plugin's skills in one library: directory below the root, to address.

        What ``${CLAUDE_PLUGIN_ROOT}/<dir>`` renders as in that plugin's text.
        Own plugin and own library only, as in Claude Code. Every skill of one
        plugin in one library shares its category, labels and library
        categories, so ``scope`` admits all of them or none and the map reveals
        nothing the caller could not list. A skipped skill is not in the index,
        so it is not here, and a citation of it dangles.

        The key is the directory as the plugin names it, ``""`` for a plugin
        root that is itself a skill. A harvest resolves the root it walks, so
        either spelling may be the prefix; a skill under neither is left out.
        """
        dirs: dict[str, str] = {}
        for skill in self._index.visible(scope):
            if skill.library != library or skill.plugin != plugin:
                continue
            base = skill.root
            if not skill.path.is_relative_to(base):
                base = skill.root.resolve()
                if not skill.path.is_relative_to(base):
                    continue
            rel = skill.path.relative_to(base).as_posix()
            dirs["" if rel == "." else rel] = f"{SCHEME}{skill.address}"
        return dirs

    def qualified_names(
        self, library: str, plugin: str, scope: Scope = EVERYTHING
    ) -> QualifiedNames:
        """The names a text of ``plugin`` in ``library`` may cite (SKL-55).

        ``plugin`` is an id. Its own name comes first, then the library's
        plugins in library order, then any others by id; each maps a skill name
        to its ``SKILL.md`` addresses, from what ``scope`` admits and nothing
        else, so an out-of-scope skill is as absent as a missing one.
        """
        mine = next((t for t in self._libraries if t.name == library), None)
        pairs = dict(mine.plugins) if mine is not None else {}
        found: dict[str, dict[str, list[str]]] = {plugin: {}}
        for skill in sorted(self._in_library(library, scope), key=lambda s: s.address):
            found.setdefault(skill.plugin, {}).setdefault(skill.name, []).append(
                uri_for(skill)
            )
        order = [plugin] + [pid for pid in pairs if pid != plugin]
        order += sorted(pid for pid in found if pid not in order)
        return QualifiedNames(
            tuple(
                (
                    pairs.get(pid, pid),
                    {name: tuple(uris) for name, uris in found.get(pid, {}).items()},
                )
                for pid in order
            )
        )

    # -- agents -------------------------------------------------------------

    def agent_instructions(
        self, library: str, plugin: str, body: str, scope: Scope = EVERYTHING
    ) -> str:
        """An agent's body as ``scope`` reads it: AGT-17, then PRM-48.

        Plugin-qualified skill names become addresses first (SKL-54), from
        what ``scope`` admits; then ``${CLAUDE_PLUGIN_ROOT}`` renders as a
        prompt body's does, through the plugin's own skills in this library.
        Every other placeholder -- ``${CLAUDE_SKILL_DIR}`` included, an agent
        being no skill -- is left as written. The gateway prefix is the plugin
        layer's to write, after this.
        """
        names = self.qualified_names(library, plugin, scope)
        return placeholders.substitute(
            names.rewrite(body),
            plugin_root=f"{SCHEME}{library}",
            skills=self.plugin_skill_dirs(library, plugin, scope),
        )

    def agent_meta(
        self,
        library: str,
        plugin: str,
        path: str,
        frontmatter: Mapping[str, object],
        servers: Sequence[str],
    ) -> dict:
        """kb's ``io.kubed.mcp-kb/agent`` value for one agent (AGT-9).

        ``plugin`` is kb's plugin id, ``path`` the agent's file under its root,
        ``frontmatter`` what that file's frontmatter reads as and ``servers``
        the plugin's MCP server names. ``skills`` maps each ``skills:`` entry of
        the frontmatter to the ``SKILL.md`` address it resolves to among the
        agent's own plugin's skills alone (N9): this is computed once per
        generation and never sees a scope, and every scope that admits the
        agent admits its plugin, so it never names a skill a caller cannot see
        (SCP-24).
        """
        names = self.qualified_names(library, plugin)
        own = QualifiedNames(names.plugins[:1])
        return {
            "plugin": plugin,
            "library": library,
            "path": path,
            "frontmatter": frontmatter,
            "servers": list(servers),
            "skills": own.preload(frontmatter.get("skills")),
        }

    def _library_files(self, library: str, scope: Scope) -> list[str]:
        """The library-level files this caller may see, empty when none are.

        Both halves of the library-files rule in one place: the listing offers
        a ``_files.md`` row exactly when reading one would return a body, and a
        library out of scope entirely has neither. ``LibraryFiles`` checks each
        root's plugin against the scope's categories and tags; whether the
        library itself is in scope is decided here.
        """
        if scope.library and scope.library != library:
            return []
        return self._resources.files(library, scope)

    def _in_library(self, library: str, scope: Scope) -> list[Skill]:
        return [s for s in self._index.visible(scope) if s.library == library]

    def _skill_at(
        self, library: str, path: str, scope: Scope
    ) -> tuple[Skill, str] | None:
        """The skill whose address is the longest prefix of ``path``, and the rest.

        The rest is empty when ``path`` is the skill's own root.
        """
        segments = path.split("/")
        for cut in range(len(segments), 0, -1):
            address = "/".join([library, *segments[:cut]])
            skill = self._index.get(address, scope)
            if skill is not None:
                return skill, "/".join(segments[cut:])
        return None

    def _unclaimed(self, library: str, path: str) -> bool:
        """Whether the library-wide fallback may answer ``path`` at all.

        Two addresses it may not, and they are the two the harvest already
        refuses to serve a library file at (``snapshot._admit``), so that
        ``/health``'s ``skipped`` stays true and one URI keeps one answer:

        - one inside a skill's address, *whoever* may see that skill -- the
          skill branch above owns it, and a scope that hides the skill must not
          uncover something else at the same URI;
        - one named like an index the server generates, which answers first
          wherever there is one.
        """
        if PurePosixPath(path).name in RESERVED_NAMES:
            return False
        return self._skill_at(library, path, EVERYTHING) is None

    # -- reading ------------------------------------------------------------

    def read(self, uri: str, scope: Scope = EVERYTHING) -> str | None:
        """The content at ``uri``, or None when there is none to give.

        None covers absent, malformed, out-of-scope and directory addresses
        alike, and that conflation is deliberate: knowing a skill's exact
        address must not be enough to confirm it exists in a library the caller
        was not given.

        A skill is tried first, then the indexes, then the library's own files.
        The order never arbitrates between two things at one address, because
        the snapshot serves no such pair: a library file inside a skill of its
        own plugin, or named like an index, is skipped, and one inside another
        plugin's skill fails that plugin.

        Either kind of miss falls back to the plugin root -- the skill's own,
        then every one the library has -- because that is where a kit's shared
        material actually sits and what its citations and
        ``${CLAUDE_PLUGIN_ROOT}`` point at. The fallback reads what it is asked
        for and lists nothing.

        A skill's own files and its ``_manifest`` read as nothing here: the
        plugin layer serves them, from each plugin as it reads it. A path under
        a skill reads here only through the plugin-root fallback.
        """
        parsed = parse(uri)
        if parsed is None:
            return None
        library, path = parsed
        if not path:
            return None
        found = self._skill_at(library, path, scope)
        if found is not None and found[1]:
            skill, file = found
            if file == MANIFEST or self._has(skill, file):
                return None
            body = self._root_file(skill, file)
            if body is not None:
                return body
        if path == INDEX:
            return self._index_body(library, None, scope)
        if path == LIBRARY_FILES:
            return self._library_files_body(library, scope)
        folder, _, last = path.rpartition("/")
        if last == INDEX and folder:
            body = self._index_body(library, folder, scope)
            if body is not None:
                return body
        if scope.library and scope.library != library:
            return None
        body = self._resources.read(library, path, scope)
        if body is None and self._unclaimed(library, path):
            body = self._resources.read_any(library, path, scope)
        return body

    def hint(self, uri: str, scope: Scope = EVERYTHING) -> str | None:
        """What to read instead of an address that serves nothing, or None.

        One kind of miss gets one: a directory -- a library, a folder, a skill's
        root -- which names the file to read in its place. A path under a skill
        that is really the library's own material needs no hint any more; the
        plugin-root fallback in ``read`` serves it where it was asked for.

        Answered from what ``scope`` can see, so a hint never confirms an
        address the caller could not list.
        """
        parsed = parse(uri)
        if parsed is None:
            return None
        library, path = parsed
        skills = self._in_library(library, scope)
        files = self._library_files(library, scope)
        files_hint = f"read {SCHEME}{library}/{LIBRARY_FILES} for the files in it."
        if not path:
            if skills:
                return (
                    "It is a library, not a file:"
                    f" read {index_uri(library)} for its skills."
                )
            if files:
                return f"It is a library, not a file: {files_hint}"
            return None
        found = self._skill_at(library, path, scope)
        if found is not None and not found[1]:
            skill = found[0]
            return (
                "It is a skill's directory, not a file:"
                f" read {uri_for(skill)} for its instructions, or"
                f" {uri_for(skill, MANIFEST)} for the files it ships."
            )
        folder = path.strip("/")
        if any(s.folder == folder or s.folder.startswith(f"{folder}/") for s in skills):
            return (
                "It is a folder, not a file:"
                f" read {index_uri(library, folder)} for what is in it."
            )
        if any(f.startswith(f"{folder}/") for f in files):
            return f"It is a folder, not a file: {files_hint}"
        return None

    def directory(self, uri: str, scope: Scope = EVERYTHING) -> list[Entry] | None:
        """The direct children of a library or a folder, or None for anything else.

        A folder of skills, a skill, a folder of library files and a library
        file, each as ``scope`` admits it, by URI: what
        ``resources/directory/read`` and ``_index.json`` list (MD-57). A folder
        or a skill is a directory resource, with no trailing ``/``. A skill's
        own directory and what is inside it are the skill provider's, so they
        are None here, as an absent or out-of-scope address is. An index or
        ``_files.md`` sits beside a folder, not in it, so neither is listed.
        """
        parsed = parse(uri)
        if parsed is None:
            return None
        library, folder = parsed
        if self._skill_at(library, folder, EVERYTHING) is not None:
            return None
        skills = [s for s in self._in_library(library, scope) if _in(s, folder)]
        prefix = f"{folder}/" if folder else ""
        files = [
            f for f in self._library_files(library, scope) if f.startswith(prefix)
        ]
        if not skills and not files:
            return None

        def entry(rel: str, description: str, mime_type: str = DIRECTORY) -> Entry:
            return Entry(
                f"{SCHEME}{library}/{rel}", f"{library}/{rel}", description, mime_type
            )

        found: dict[str, Entry] = {}
        for child, count in _children(skills, folder).items():
            found.setdefault(child, entry(child, _count(count)))
        for skill in skills:
            if skill.folder == folder:
                rel = skill.address.removeprefix(f"{library}/")
                found.setdefault(rel, entry(rel, skill.description))
        for file in files:
            head, slash, _ = file[len(prefix) :].partition("/")
            rel = prefix + head
            if slash:
                text = f"Files the {library} library ships outside any skill."
                found.setdefault(rel, entry(rel, text))
            else:
                text = f"A file the {library} library ships outside any skill."
                found.setdefault(rel, entry(rel, text, mime_for(rel)))
        return sorted(found.values(), key=lambda e: e.uri)

    def _index_body(
        self, library: str, folder: str | None, scope: Scope
    ) -> str | None:
        """One index: what sits directly in a library, or in one folder of it.

        A folder below this one is one line, its own ``_index.md`` with a count
        of the skills anywhere under it; a skill in no deeper folder is its
        ``SKILL.md`` and description; and a library index ends with its
        ``_files.md`` when it has library files. So an index is as long as the
        level it describes is wide, not as long as the catalogue is deep.

        Lines are ``<uri>: <description>`` rather than ``<name>: ...`` so that
        reading an index teaches the grammar for the next call. A name would
        have to be translated back into an address anyway, and it is not even
        unique.
        """
        here = folder or ""
        under = [s for s in self._in_library(library, scope) if _in(s, here)]
        if not under:
            return None

        below = _children(under, here)
        lines = [
            f"{index_uri(library, child)}: {_count(count)}"
            for child, count in sorted(below.items())
        ]
        direct = sorted(
            (s for s in under if s.folder == here), key=lambda s: s.address
        )
        lines += [f"{uri_for(skill)}: {skill.description}" for skill in direct]
        files = [] if here else self._library_files(library, scope)
        if files:
            lines.append(
                f"{SCHEME}{library}/{LIBRARY_FILES}:"
                f" {_count(len(files), 'library-level file')}"
            )

        advice = []
        if below:
            advice.append(f"Read a folder's {INDEX} for what is in it.")
        if direct:
            advice.append(
                f"Read a skill's {MAIN_FILE} for its instructions, or {MANIFEST}"
                " in its place to see what else it ships, then read one of those"
                " paths under the same skill."
            )
        title = f"{library}/{here}" if here else library
        text = ""
        if not here:
            mine = next((t for t in self._libraries if t.name == library), None)
            if mine is not None:
                parts = (tidy(mine.description), tidy(mine.notes))
                text = "".join(f"{x}\n" for x in parts if x)
                text = f"{text}\n" if text else ""
        return (
            f"# {title} — {_count(len(under))}\n\n"
            + text
            + "\n".join(lines)
            + "\n\n"
            + " ".join(advice)
            + "\n"
        )

    def _has(self, skill: Skill, file: str) -> bool:
        """Whether ``file`` is one of ``skill``'s own, as ``skill_files`` names them."""
        return file in self._files_of(skill)

    def instructions(self, address: str, text: str, scope: Scope = EVERYTHING) -> str:
        """The ``SKILL.md`` ``text`` of the skill at ``address`` as ``scope``
        reads it: SKL-55, then SKL-25 and SKL-52. ``text`` as written for an
        address that is no skill here."""
        skill = self._index.get(address)
        if skill is None:
            return text
        return self._instructions(skill, text, scope)

    def _instructions(self, skill: Skill, text: str, scope: Scope) -> str:
        """A ``SKILL.md`` as ``scope`` reads it: names and placeholders resolved."""
        # A citation through the plugin root into one of its own skills renders
        # as that skill's address: the literal path would be refused, because
        # the library-level read keeps out of a skill's own directory and a
        # skill's files have one address, which is the skill's.
        head, body = split_frontmatter(text)
        names = self.qualified_names(skill.library, skill.plugin, scope)
        return placeholders.substitute(
            head + names.rewrite(body),
            plugin_root=f"{SCHEME}{skill.library}",
            skill_dir=f"{SCHEME}{skill.address}",
            skills=self.plugin_skill_dirs(skill.library, skill.plugin, scope),
        )

    def _text(self, skill: Skill, target: Path) -> str:
        """One file of ``skill`` as text, read once unless the skill is live.

        A live skill's file is read off disk each time, and revalidated by
        ``live_stamp``, which its reader asks first.
        """
        if skill.live:
            return target.read_text(encoding="utf-8", errors="replace")
        text = self._texts.get(target)
        if text is None:
            text = target.read_text(encoding="utf-8", errors="replace")
            self._texts[target] = text
        return text

    def _root_file(self, skill: Skill, file: str) -> str | None:
        """One file of the skill's plugin root, addressed below the skill.

        A skill that factors material up out of itself cites it from the
        repository root (``shared/tokens.md``), and resolved against the skill's
        own directory that is an address with nothing at it. The plugin root is
        the ceiling -- what ``${CLAUDE_PLUGIN_ROOT}`` reaches in Claude Code --
        so the citation reads, at the address the skill's text produced.

        ``LibraryFiles`` owns the rest of the rule, because it is the one that
        knows the plugin's skill directories: a sibling skill's file is not
        readable through this skill's address, however the two are spelled. A
        legitimate sibling citation is ``../other/reference.md``, which the
        dot-segment removal in ``parse`` turns into the sibling's own address
        before any of this runs.
        """
        if hidden(Path(file)) or PurePosixPath(file).name in RESERVED_NAMES:
            return None
        return self._resources.read_under(skill.library, skill.root, file)

    def _library_files_body(self, library: str, scope: Scope) -> str | None:
        files = self._library_files(library, scope)
        if not files:
            return None
        lines = [f"{SCHEME}{library}/{f}" for f in files]
        return (
            f"# {library} — {_count(len(files), 'library-level file')}\n\n"
            "These sit outside every skill in this library, and its skills"
            " reference them.\n\n" + "\n".join(lines) + "\n"
        )

    def mime(self, uri: str) -> str:
        """The media type a read of ``uri`` will return, from its extension.

        A skill's ``_manifest`` is its provider's to type, so a library file of
        that name is not JSON here.
        """
        parsed = parse(uri)
        if parsed is None or not parsed[1]:
            return "text/markdown"
        return mime_for(parsed[1])
