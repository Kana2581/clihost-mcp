"""Adapter for OpenAI's Codex CLI (`codex`)."""

from __future__ import annotations

from typing import Any

from cli_mcp.adapters.base import CLIAdapter


class CodexAdapter(CLIAdapter):
    name = "codex"
    description = "Invoke Codex CLI in non-interactive mode (`codex exec <prompt>`)."
    extra_params = {
        "model": {"type": "string", "description": "Override the model passed to Codex."},
    }

    def __init__(self, binary: str = "codex", default_args: list[str] | None = None) -> None:
        self.binary = binary
        self.default_args = list(default_args) if default_args is not None else []

    def build_argv(self, prompt: str, **kwargs: Any) -> list[str]:
        argv: list[str] = [self.binary, "exec", *self.default_args]
        model = kwargs.get("model")
        if model:
            argv += ["--model", str(model)]
        argv.append(prompt)
        return argv
