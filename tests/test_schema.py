"""The committed config.schema.json, and main's CLI: schema, serve, and exit codes."""

import json
from pathlib import Path

import pytest

from kubed.mcp_kb.config import schema
from kubed.mcp_kb.main import main, split_command

ROOT = Path(__file__).resolve().parents[1]


def test_the_committed_schema_is_the_model():
    committed = json.loads((ROOT / "config.schema.json").read_text())
    assert committed == schema(), (
        "config.schema.json is stale: run `mcp-kb schema > config.schema.json`"
    )


def test_the_schema_subcommand_prints_the_model(capsys):
    main(["schema"])
    assert json.loads(capsys.readouterr().out) == schema()


def test_serve_with_a_missing_config_exits_2_with_a_message_on_stderr(
    monkeypatch, capsys
):
    monkeypatch.delenv("CONFIG", raising=False)
    """A bad config must fail loudly at boot, not silently serve nothing."""
    with pytest.raises(SystemExit) as raised:
        main(["serve", "--config-file", "/nope"])
    assert raised.value.code == 2
    err = capsys.readouterr().err
    assert "mcp-kb:" in err and "/nope" in err


def test_one_level_and_one_handler_reach_fastmcp_and_uvicorn_too():
    """Loggers that arrived with handlers of their own write through the root's."""
    import logging

    import fastmcp  # noqa: F401 - importing it is what installs its handler

    from kubed.mcp_kb.main import THIRD_PARTY_LOGGERS, configure_logging

    root = logging.getLogger()
    saved = (root.handlers[:], root.level)
    third = {
        name: (lg.handlers[:], lg.propagate, lg.level)
        for name in THIRD_PARTY_LOGGERS
        for lg in [logging.getLogger(name)]
    }
    try:
        configure_logging("WARNING")
        assert root.level == logging.WARNING
        for name in THIRD_PARTY_LOGGERS:
            logger = logging.getLogger(name)
            assert logger.handlers == [] and logger.propagate
        assert not logging.getLogger("fastmcp.server").isEnabledFor(logging.INFO)
        assert logging.getLogger("fastmcp.server").isEnabledFor(logging.WARNING)
        assert not logging.getLogger("uvicorn.access").isEnabledFor(logging.INFO)

        configure_logging("ERROR")
        assert not logging.getLogger("uvicorn.access").isEnabledFor(logging.WARNING)

        configure_logging("DEBUG")
        assert logging.getLogger("uvicorn.access").isEnabledFor(logging.INFO)
    finally:
        root.handlers[:], _ = saved
        root.setLevel(saved[1])
        for name, (handlers, propagate, level) in third.items():
            logger = logging.getLogger(name)
            logger.handlers[:], logger.propagate = handlers, propagate
            logger.setLevel(level)


def test_the_httpx_logger_is_held_at_warning_below_debug():
    """httpx logs one INFO line per WebDAV request: traffic, held like uvicorn's."""
    import logging

    from kubed.mcp_kb.main import configure_logging

    root = logging.getLogger()
    httpx_logger = logging.getLogger("httpx")
    saved = (root.handlers[:], root.level, httpx_logger.level)
    try:
        configure_logging("INFO")
        assert not httpx_logger.isEnabledFor(logging.INFO)
        assert httpx_logger.isEnabledFor(logging.WARNING)

        # Back to DEBUG in the same process: the hold must come off again.
        configure_logging("DEBUG")
        assert httpx_logger.isEnabledFor(logging.INFO)
    finally:
        root.handlers[:] = saved[0]
        root.setLevel(saved[1])
        httpx_logger.setLevel(saved[2])


def test_a_typod_telemetry_key_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CONFIG", raising=False)
    path = tmp_path / "config.yaml"
    path.write_text("telemetry:\n  profile: http://pyroscope.example.com:4040\n")
    with pytest.raises(SystemExit) as raised:
        main(["serve", "--config-file", str(path)])
    assert raised.value.code == 2
    err = capsys.readouterr().err
    assert "mcp-kb:" in err and "profile" in err


def test_split_command():
    assert split_command([]) == ("serve", [])
    assert split_command(["schema"]) == ("schema", [])
    assert split_command(["serve", "--port", "9000"]) == ("serve", ["--port", "9000"])
    assert split_command(["--port", "9000"]) == ("serve", ["--port", "9000"])


def test_schema_reads_no_config(monkeypatch, capsys):
    monkeypatch.setenv("CONFIG_FILE", "/nope")
    main(["schema", "--port", "not-a-port"])
    assert json.loads(capsys.readouterr().out) == schema()


def test_help_names_every_item_and_exits_0(capsys):
    main(["--help"])
    out = capsys.readouterr().out
    assert out.startswith("usage: mcp-kb")
    for flag, env in [
        ("--config-file", "CONFIG_FILE"),
        ("--sources", "KB_SOURCES"),
        ("--cache-dir", "CACHE_DIR"),
        ("--port", "PORT"),
        ("--telemetry-profiles", "TELEMETRY_PROFILES"),
        ("--delivery-via", "DELIVERY_VIA"),
    ]:
        assert flag in out and env in out


def test_an_unknown_flag_or_a_positional_exits_2(monkeypatch, capsys):
    monkeypatch.delenv("CONFIG", raising=False)
    for argv in (["serve", "--config", "x.yaml"], ["serve", "extra"]):
        with pytest.raises(SystemExit) as raised:
            main(argv)
        assert raised.value.code == 2
        assert "mcp-kb: the config did not load" in capsys.readouterr().err


def test_a_leftover_config_variable_exits_2(tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.yaml"
    path.write_text("")
    monkeypatch.setenv("CONFIG", str(path))
    with pytest.raises(SystemExit) as raised:
        main(["serve", "--config-file", str(path)])
    assert raised.value.code == 2
    assert "CONFIG is no longer read" in capsys.readouterr().err
