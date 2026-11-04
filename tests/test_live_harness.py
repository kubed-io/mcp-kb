"""The live checks are opt-in: CI must skip them, never run or drop them."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.mark.unit
def test_the_live_checks_skip_without_a_url():
    run = subprocess.run(
        [
            sys.executable, "-m", "pytest", "tests/live", "-q", "-rs",
            "-p", "no:cacheprovider",
        ],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    assert run.returncode == 0, run.stdout
    assert "a live check: needs --kb-url" in run.stdout
    summary = run.stdout.strip().splitlines()[-1]
    assert " skipped" in summary
    assert "passed" not in summary and "failed" not in summary
