"""Fixtures for the checks against a running kb."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def kb_url(pytestconfig) -> str:
    return pytestconfig.getoption("--kb-url").rstrip("/")


@pytest.fixture
def dav_dir(pytestconfig) -> Path:
    value = pytestconfig.getoption("--kb-dav-dir")
    if not value:
        pytest.skip("needs --kb-dav-dir: the folder the running kb's dav source serves")
    return Path(value)
