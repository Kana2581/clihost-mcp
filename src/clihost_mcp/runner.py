"""Subprocess execution core.

All CLI invocations go through `run_subprocess`. Never use shell=True — argv is
always a list, so command-injection is structurally impossible.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Sequence


# Absolute backstop in the runner. The real per-deployment ceiling is
# DefaultsConfig.max_timeout_sec, enforced by server.py before the value
# reaches here. This constant just prevents asyncio.wait_for from being
# called with a wildly large value (e.g. agent passes float('inf')).
HARD_TIMEOUT_CEILING_SEC = 86400  # 24h


@dataclass
class RunResult:
    argv: list[str]
    cwd: Optional[str]
    exit_code: Optional[int]
    duration_ms: int
    stdout: str
    stderr: str
    truncated: bool
    timed_out: bool
    run_id: str
    full_output_path: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _decode(buf: bytes) -> str:
    # CLIs may emit non-UTF8 on Windows. Replace errors rather than raise.
    return buf.decode("utf-8", errors="replace")


async def run_subprocess(
    argv: Sequence[str],
    *,
    cwd: Optional[str] = None,
    timeout_sec: float = 120.0,
    max_output_bytes: int = 100 * 1024,
    env: Optional[dict[str, str]] = None,
    stdin_input: Optional[str] = None,
    runs_dir: Optional[Path] = None,
) -> RunResult:
    """Run a command and return a structured result.

    - argv: command + args, no shell interpolation
    - timeout_sec: clamped to HARD_TIMEOUT_CEILING_SEC
    - max_output_bytes: stdout and stderr each capped to this many bytes;
      excess is dropped from the returned string but full output is persisted
      to disk under runs_dir if provided.
    """
    if not argv:
        raise ValueError("argv must be non-empty")

    timeout = min(max(0.1, float(timeout_sec)), HARD_TIMEOUT_CEILING_SEC)
    argv_list = list(argv)
    run_id = uuid.uuid4().hex[:12]
    started = time.monotonic()

    # On Windows, asyncio.create_subprocess_exec does not respect PATHEXT, so
    # bare names like "codex" (whose actual file is `codex.cmd`) fail to launch.
    # Resolve the executable via shutil.which when the first token has no path
    # separator — this preserves the safety property (no shell interpolation)
    # while making `.cmd`/`.bat` shims work.
    head = argv_list[0]
    if os.sep not in head and (os.altsep is None or os.altsep not in head):
        resolved = shutil.which(head)
        if resolved is not None:
            argv_list[0] = resolved

    # Build env: caller passes the already-filtered env, or None to inherit.
    proc_env = env if env is not None else None

    # When no stdin payload is supplied, hand the child DEVNULL rather than
    # inheriting the parent's stdin. Under stdio MCP transport the parent's
    # stdin is the JSON-RPC pipe — a CLI that reads from it (e.g. `codex exec`
    # which slurps stdin for extra context) would hang forever and corrupt the
    # MCP channel.
    stdin_target = asyncio.subprocess.PIPE if stdin_input is not None else asyncio.subprocess.DEVNULL

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv_list,
            stdin=stdin_target,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=proc_env,
        )
    except FileNotFoundError as e:
        return RunResult(
            argv=argv_list,
            cwd=cwd,
            exit_code=None,
            duration_ms=0,
            stdout="",
            stderr="",
            truncated=False,
            timed_out=False,
            run_id=run_id,
            error=f"binary not found: {e}",
        )
    except PermissionError as e:
        return RunResult(
            argv=argv_list,
            cwd=cwd,
            exit_code=None,
            duration_ms=0,
            stdout="",
            stderr="",
            truncated=False,
            timed_out=False,
            run_id=run_id,
            error=f"permission denied: {e}",
        )

    timed_out = False
    stdout_bytes = b""
    stderr_bytes = b""
    try:
        stdin_payload = stdin_input.encode("utf-8") if stdin_input else None
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=stdin_payload), timeout=timeout
        )
    except asyncio.TimeoutError:
        timed_out = True
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=5.0
            )
        except asyncio.TimeoutError:
            stdout_bytes, stderr_bytes = b"", b""

    duration_ms = int((time.monotonic() - started) * 1000)
    exit_code = proc.returncode

    truncated = False
    if len(stdout_bytes) > max_output_bytes:
        truncated = True
    if len(stderr_bytes) > max_output_bytes:
        truncated = True

    stdout_str = _decode(stdout_bytes[:max_output_bytes])
    stderr_str = _decode(stderr_bytes[:max_output_bytes])

    full_output_path: Optional[str] = None
    if truncated and runs_dir is not None:
        try:
            run_dir = Path(runs_dir) / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "stdout").write_bytes(stdout_bytes)
            (run_dir / "stderr").write_bytes(stderr_bytes)
            full_output_path = str(run_dir)
        except OSError:
            full_output_path = None

    return RunResult(
        argv=argv_list,
        cwd=cwd,
        exit_code=exit_code,
        duration_ms=duration_ms,
        stdout=stdout_str,
        stderr=stderr_str,
        truncated=truncated,
        timed_out=timed_out,
        run_id=run_id,
        full_output_path=full_output_path,
        error=("timed out" if timed_out else None),
    )


def filter_env(passthrough: Sequence[str]) -> dict[str, str]:
    """Build an env dict containing only the named keys from the current env.

    The base whitelist must keep enough Windows essentials that a Node-based
    CLI (codex, claude-code) can initialise. Node's CSPRNG init on Windows
    aborts if it can't reach bcrypt primitives, which in turn depends on
    PATH/SystemRoot plus the standard process-info vars (PROCESSOR_*,
    COMPUTERNAME, etc.). Trimming those out caused codex to die with
    `Assertion failed: ncrypto::CSPRNG(...)` before it could read its prompt.
    """
    base_keys = {
        # cross-platform basics
        "PATH", "HOME", "LANG", "LC_ALL", "TZ",
        # Windows: filesystem / user
        "SystemRoot", "SYSTEMROOT", "WINDIR", "ComSpec", "PATHEXT",
        "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
        "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
        "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432",
        "TEMP", "TMP",
        # Windows: process/system identity (Node loader + crypto init need these)
        "USERNAME", "USERDOMAIN", "COMPUTERNAME", "OS",
        "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER",
        "PROCESSOR_LEVEL", "PROCESSOR_REVISION", "NUMBER_OF_PROCESSORS",
    }
    allow = set(passthrough) | base_keys
    return {k: v for k, v in os.environ.items() if k in allow}
