"""Tests for runner.py — uses `python -c ...` as the subject so the tests are
cross-platform and don't depend on `claude` or `codex` being installed."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cli_mcp.runner import run_subprocess


PYTHON = sys.executable


async def test_basic_stdout():
    result = await run_subprocess([PYTHON, "-c", "print('hello')"])
    assert result.exit_code == 0
    assert "hello" in result.stdout
    assert not result.timed_out
    assert not result.truncated


async def test_nonzero_exit_returned_not_raised():
    result = await run_subprocess([PYTHON, "-c", "import sys; sys.exit(7)"])
    assert result.exit_code == 7
    assert result.error is None


async def test_stderr_captured():
    result = await run_subprocess([PYTHON, "-c", "import sys; sys.stderr.write('boom')"])
    assert "boom" in result.stderr


async def test_timeout_kills_process():
    result = await run_subprocess(
        [PYTHON, "-c", "import time; time.sleep(5)"],
        timeout_sec=0.5,
    )
    assert result.timed_out is True
    assert result.error == "timed out"


async def test_truncation_persists_full_output(tmp_path: Path):
    # Print 200 KiB; cap at 4 KiB so truncation kicks in.
    result = await run_subprocess(
        [PYTHON, "-c", "import sys; sys.stdout.write('x' * 200_000)"],
        max_output_bytes=4096,
        runs_dir=tmp_path,
    )
    assert result.exit_code == 0
    assert result.truncated is True
    assert len(result.stdout) <= 4096
    assert result.full_output_path is not None
    stdout_file = Path(result.full_output_path) / "stdout"
    assert stdout_file.exists()
    assert stdout_file.stat().st_size == 200_000


async def test_missing_binary_returns_error():
    result = await run_subprocess(["definitely-not-a-real-binary-xyz123"])
    assert result.exit_code is None
    assert result.error is not None
    assert "not found" in result.error.lower()


async def test_empty_argv_raises():
    with pytest.raises(ValueError):
        await run_subprocess([])
