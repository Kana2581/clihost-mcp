"""Adapter for Anthropic's Claude Code CLI (`claude`)."""

from __future__ import annotations

import json
from typing import Any

from cli_mcp.adapters.base import CLIAdapter
from cli_mcp.runner import RunResult


class ClaudeCodeAdapter(CLIAdapter):
    name = "claude"
    description = "Invoke Claude Code in non-interactive mode (`claude -p <prompt>`)."
    extra_params = {
        "model": {"type": "string", "description": "Override the model, e.g. 'claude-opus-4-7'."},
        "system_prompt": {"type": "string", "description": "Inject a system prompt via --system-prompt."},
        "allowed_tools": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Restrict Claude Code's tool use via --allowedTools.",
        },
        "session_id": {"type": "string", "description": "Resume a session via --resume."},
    }

    def __init__(self, binary: str = "claude", default_args: list[str] | None = None) -> None:
        self.binary = binary
        # JSON output so parse_output can extract structured fields, plus the
        # skip-permissions flag so an MCP call doesn't deadlock on an
        # interactive approval prompt. The ClaudeAdapterConfig default carries
        # the same values; this list is the fallback for direct instantiation
        # in tests or callers that bypass the config layer.
        self.default_args = (
            list(default_args)
            if default_args is not None
            else ["--output-format", "json", "--dangerously-skip-permissions"]
        )

    def build_argv(self, prompt: str, **kwargs: Any) -> list[str]:
        argv: list[str] = [self.binary, "-p", prompt, *self.default_args]
        model = kwargs.get("model")
        if model:
            argv += ["--model", str(model)]
        system_prompt = kwargs.get("system_prompt")
        if system_prompt:
            argv += ["--system-prompt", str(system_prompt)]
        allowed_tools = kwargs.get("allowed_tools")
        if allowed_tools:
            argv += ["--allowedTools", ",".join(str(t) for t in allowed_tools)]
        session_id = kwargs.get("session_id")
        if session_id:
            argv += ["--resume", str(session_id)]
        return argv

    def parse_output(self, result: RunResult) -> dict[str, Any]:
        out = result.to_dict()
        # Only attempt to parse JSON when the run succeeded and output looks
        # like JSON. Failure to parse is non-fatal — we still return raw stdout.
        if result.exit_code == 0 and result.stdout.strip().startswith("{"):
            try:
                parsed = json.loads(result.stdout)
                if isinstance(parsed, dict):
                    out["parsed"] = {
                        "result": parsed.get("result"),
                        "session_id": parsed.get("session_id"),
                        "total_cost_usd": parsed.get("total_cost_usd"),
                        "num_turns": parsed.get("num_turns"),
                        "is_error": parsed.get("is_error"),
                    }
            except json.JSONDecodeError:
                pass
        return out
