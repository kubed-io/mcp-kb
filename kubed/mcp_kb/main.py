"""Entry point: the ``mcp-kb`` console script, from argv and the environment.

Three things here are kb's own: the ``serve`` or ``schema`` word in front,
``--help``, and the guard that stops a boot whose environment still sets the
``CONFIG`` kb no longer reads. Every other token goes to kubed-mcp's config
loader with the environment, which reads the file ``CONFIG_FILE`` or
``--config-file`` names, then each item's env var, then each item's flag. The
names are written in ``config.py``'s sections, never here, so ``--help`` and the
wiki read them off the schema. The one other reader of the environment is
``EnvRef.resolve`` in ``config.py``, which resolves a source's credential where
it is declared rather than passing it through a plain ``str`` on the way.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections.abc import Sequence

from .app import create_app
from .config import ConfigError, load, schema
from .server import KnowledgeBase
from .sources import AccessRefused

COMMANDS = ("serve", "schema")
"""The words ``mcp-kb`` takes in front: anything else is served, every token
passed on, so ``mcp-kb --port 9000`` serves on 9000."""

LEFTOVER = "mcp-kb: CONFIG is no longer read: name the config file with CONFIG_FILE"

# The loggers that arrive with a handler or a level of their own. Each is
# emptied, reset and made to propagate, so one line format and one level reach
# the collector whoever wrote it.
THIRD_PARTY_LOGGERS = (
    "fastmcp",
    "mcp",
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "httpx",
)

# The loggers whose INFO is traffic, not what the server did: a line per MCP
# call and per probe from uvicorn, a line per WebDAV request from httpx. Held
# at WARNING below DEBUG.
TRAFFIC_LOGGERS = ("uvicorn.access", "httpx")


def configure_logging(level: str) -> None:
    """One handler on stderr, one line format, one level, for the whole process.

    FastMCP installs a Rich handler of its own on import and uvicorn installs
    its own on start, each with its own format and level, so ``LOG_LEVEL`` set
    only on this package would leave most of what the process writes untouched.
    Each is emptied and sent to the root handler instead.

    The traffic loggers are the exception: a line per MCP call and per probe,
    or per WebDAV request, is traffic, not what the server did, so those are
    written only at ``DEBUG``. Each one's own level is what holds it back -- a
    record that propagates is not measured against the root's level again --
    so it is never set below the level asked for.
    """
    handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%SZ"
    )
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in THIRD_PARTY_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(logging.NOTSET)
    if level != "DEBUG":
        for name in TRAFFIC_LOGGERS:
            logging.getLogger(name).setLevel(
                max(logging.WARNING, logging.getLevelName(level))
            )


def named_items(published: dict) -> list[tuple[str, str, str]]:
    """``(arg, env, description)`` for each item of ``published`` with a flag.

    In schema order: the root's properties first, then the properties of each
    section a root property ``$ref``s into ``$defs``, one level down.
    """
    defs = published.get("$defs", {})
    root = published.get("properties", {})
    levels = [root]
    for prop in root.values():
        ref = prop.get("$ref")
        if ref:
            levels.append(defs[ref.rsplit("/", 1)[-1]].get("properties", {}))
    return [
        (prop["arg"], prop.get("env", ""), prop.get("description", ""))
        for props in levels
        for prop in props.values()
        if "arg" in prop
    ]


def split_command(argv: Sequence[str]) -> tuple[str, list[str]]:
    """The command and the tokens after it: a first token in ``COMMANDS`` is the
    command, and anything else is ``serve`` with every token kept."""
    tokens = list(argv)
    if tokens and tokens[0] in COMMANDS:
        return tokens[0], tokens[1:]
    return "serve", tokens


def help_text() -> str:
    """The usage, the config file's flag and one line per item, from the schema."""
    lines = [
        "usage: mcp-kb [serve|schema] [--config-file PATH] [--<item> VALUE ...]",
        "  --config-file PATH  (env CONFIG_FILE)  "
        "The YAML config file; none is read unless named.",
    ]
    lines += [
        f"  {arg}  (env {env})  {description}"
        for arg, env, description in named_items(schema())
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """Entry point for the ``mcp-kb`` console script."""
    tokens = sys.argv[1:] if argv is None else list(argv)
    ahead = tokens[: tokens.index("--")] if "--" in tokens else tokens
    if "-h" in ahead or "--help" in ahead:
        print(help_text())
        return
    command, rest = split_command(tokens)
    if command == "schema":
        print(json.dumps(schema(), indent=2))
        return
    if os.environ.get("CONFIG", "").strip():
        # A deployment written for the old name would otherwise serve the
        # image's own example config through its CONFIG_FILE, and say nothing.
        print(LEFTOVER, file=sys.stderr)
        raise SystemExit(2)
    try:
        loaded = load(rest)
    except ConfigError as exc:
        # A bad config must fail loudly at boot, not silently serve nothing.
        print(f"mcp-kb: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    config = loaded.config
    configure_logging(config.serving.log_level)
    try:
        knowledge_base = KnowledgeBase(config, config.cache_dir)
    except AccessRefused as exc:
        # Exit rather than serve without it: see KnowledgeBase._cold_start.
        print(f"mcp-kb: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
    # run() reads the loaded config's serving section: transport, host, port
    # and the log level. uvicorn is given no log config of its own, so its
    # lines go through the handler configure_logging installed and read like
    # the rest.
    create_app(knowledge_base, loaded=loaded).run(uvicorn_config={"log_config": None})


if __name__ == "__main__":
    main()
