"""A prompt file as FastMCP's ``Prompt``, the seam to kubed-mcp's plugin layer.

A skill is read by the model when it decides to. A prompt is picked by a person
-- Claude Code lists them as slash commands -- who fills in a few arguments
before the model sees anything. Different primitive, so a different module,
scoped by the same library, category and tag rules as skills.

The parsing -- frontmatter, dialects, placeholders -- lives in
``catalogue/prompts/`` and has no FastMCP in it at all: ``catalogue/`` is the
layer ``AGENTS.md`` promises stays free of it. kubed-mcp's plugin layer serves
the prompts, scoped by kb's view, and reads each file through kb's command
reader (``SkillServing.read_command``). This module is the seam between the
two: ``adapt`` wraps a catalogue ``FilePrompt`` in FastMCP's own ``Prompt``
base class as ``MCPFilePrompt``, which is what the reader hands the layer.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from kubed.mcp import Prompt, PromptArgument, ValidationError
from kubed.mcp.protocol import (
    MODERN_PROTOCOL_VERSIONS,
    InputRequiredPromptResult,
    types,
)
from kubed.mcp.request import get_context
from pydantic import ConfigDict

from ..catalogue.prompts import FilePrompt, MissingArguments

if TYPE_CHECKING:
    from kubed.mcp import Context

# The key the one form elicitation is minted and read back under. A prompt asks
# for its arguments and nothing else, so there is exactly one.
ARGUMENTS = "arguments"

class MCPFilePrompt(Prompt):
    """FastMCP's ``Prompt``, backed by a catalogue ``FilePrompt``.

    Everything a client-facing prompt needs -- the substitution and the
    missing-argument check -- is ``file``'s to do; this class exists only to
    satisfy FastMCP's ``Prompt`` contract and hand the result back. ``file``'s
    body was rendered when the plugin layer's build was made: qualified names
    and ``${CLAUDE_PLUGIN_ROOT}`` are addresses already (PRM-47), and the
    gateway prefix is the layer's to write into what this renders (GW-7).

    A missing argument is the one failure translated here. FastMCP treats any
    other exception out of a render as its own fault: -32603 on the wire and a
    traceback at ERROR in the log. Its ``ValidationError`` is the caller's
    fault instead -- -32602 -- and logged at the level it carries.

    On a connection that can be asked, it is not a failure at all: the render
    returns an ``InputRequiredResult`` (SEP-2322) asking for the argument, and
    the round that answers renders (§C1.37). Everything older keeps the error.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    file: FilePrompt

    async def render(
        self, arguments: dict[str, object] | None = None
    ) -> str | InputRequiredPromptResult:
        try:
            return self._filled(arguments)
        except MissingArguments as exc:
            answered = _answered()
            if answered is None:
                asked = self._ask(exc)
                if asked is not None:
                    return asked
                raise _refused(exc) from exc
            if answered.action != "accept" or not answered.content:
                # Declined or dismissed: the caller's own answer is that the
                # prompt is not to be rendered, which is where it started.
                raise _refused(exc) from exc
            try:
                return self._filled({**(arguments or {}), **answered.content})
            except MissingArguments as again:
                raise _refused(again) from again

    def _filled(self, arguments: dict[str, object] | None) -> str:
        return self.file.render(arguments)

    def _ask(self, exc: MissingArguments) -> InputRequiredPromptResult | None:
        """The missing arguments as one form, or None when nobody can fill it.

        One elicitation rather than one per argument: a person filling in a
        slash command fills in the command, and a client that showed three
        dialogs for three blanks would be reporting our data model at them.
        """
        if not _can_ask():
            return None
        described = {a.name: a.description or "" for a in self.file.arguments}
        form = types.ElicitRequestFormParams(
            message=f"The {self.name} prompt needs {', '.join(exc.names)}.",
            requested_schema={
                "type": "object",
                "properties": {
                    name: {"type": "string", "description": described.get(name, "")}
                    for name in exc.names
                },
                "required": list(exc.names),
            },
        )
        return InputRequiredPromptResult(
            types.InputRequiredResult(
                input_requests={ARGUMENTS: types.ElicitRequest(params=form)}
            )
        )


def _refused(exc: MissingArguments) -> ValidationError:
    return ValidationError(str(exc), log_level=logging.DEBUG)


def _context() -> Context | None:
    """The active FastMCP context, or None when there is no request."""
    try:
        return get_context()
    except RuntimeError:
        return None


def _can_ask() -> bool:
    """Whether this request can carry a question back to a client that answers.

    Two things have to hold. The multi-round-trip result type exists only at
    MCP 2026-07-28, so an older connection would be handed a result it has no
    schema for; and the client has to have declared *form* elicitation, since
    a form is what a prompt's arguments are asked for with -- a client that
    declared URL mode alone could not fill one in.
    """
    ctx = _context()
    if ctx is None:
        return False
    try:
        session = ctx.session
    except RuntimeError:
        return False
    if session.protocol_version not in MODERN_PROTOCOL_VERSIONS:
        return False
    capabilities = session.client_capabilities
    elicitation = None if capabilities is None else capabilities.elicitation
    return elicitation is not None and elicitation.form is not None


def _answered() -> types.ElicitResult | None:
    """This round's answer to the form asked for on the last one, if any."""
    ctx = _context()
    if ctx is None:
        return None
    answered = (ctx.input_responses or {}).get(ARGUMENTS)
    return answered if isinstance(answered, types.ElicitResult) else None


def adapt(file: FilePrompt) -> MCPFilePrompt:
    """``file`` as the ``Prompt`` kb's command reader hands the plugin layer."""
    return MCPFilePrompt(
        name=file.name,
        title=file.title,
        description=file.description,
        # The plugin's labels plus the library, so FastMCP's own tag filters
        # can tell one library's prompts from another's.
        tags={file.library, *file.tags},
        arguments=[
            PromptArgument(name=a.name, description=a.description, required=a.required)
            for a in file.arguments
        ],
        file=file,
    )
