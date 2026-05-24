"""Adapter for arbitrary shell commands, gated by an allowlist."""

from __future__ import annotations

import shlex
from typing import Any

from clihost_mcp.adapters.base import CLIAdapter, AdapterError


class ShellAdapter(CLIAdapter):
    name = "shell"
    description = (
        "Execute a whitelisted shell command. The first token must be present "
        "in the configured command_allowlist. No shell interpolation — the "
        "command is split with shlex and executed as argv."
    )
    extra_params = {}  # `prompt` is the command; no extras

    def __init__(self, command_allowlist: list[str] | None = None) -> None:
        self.command_allowlist = set(command_allowlist or [])

    def build_argv(self, prompt: str, **kwargs: Any) -> list[str]:
        # `prompt` here is the command string. Accept either a string (split
        # via shlex) or a pre-split argv list passed through kwargs["argv"].
        argv_override = kwargs.get("argv")
        if argv_override is not None:
            if not isinstance(argv_override, list) or not all(isinstance(x, str) for x in argv_override):
                raise AdapterError("argv must be a list of strings")
            argv = list(argv_override)
        else:
            try:
                argv = shlex.split(prompt, posix=False)
            except ValueError as e:
                raise AdapterError(f"failed to parse command: {e}") from e
        if not argv:
            raise AdapterError("empty command")
        head = argv[0]
        # Allow matching on basename only — users typically allowlist `git`,
        # not `C:\Program Files\Git\bin\git.exe`.
        import os
        basename = os.path.basename(head).lower()
        # Strip common Windows extensions for the comparison.
        for ext in (".exe", ".bat", ".cmd", ".ps1"):
            if basename.endswith(ext):
                basename = basename[: -len(ext)]
                break
        allowed = {c.lower() for c in self.command_allowlist}
        if basename not in allowed:
            raise AdapterError(
                f"command {head!r} (resolved to {basename!r}) is not in shell.command_allowlist"
            )
        return argv
