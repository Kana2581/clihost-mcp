"""Adapter registry: assembles built-in + YAML-defined adapters."""

from __future__ import annotations

from typing import Any

from clihost_mcp.adapters import (
    CLIAdapter,
    ClaudeCodeAdapter,
    CodexAdapter,
    ShellAdapter,
)
from clihost_mcp.config import Config, CustomAdapterConfig


class _TemplateAdapter(CLIAdapter):
    """Generic adapter built from a YAML argv_template.

    Each token in argv_template may contain the literal substring `{prompt}`,
    which is substituted with the user-supplied prompt string. No other
    interpolation is performed — this is intentionally limited.
    """

    extra_params: dict[str, dict[str, Any]] = {}

    def __init__(self, name: str, description: str, argv_template: list[str]) -> None:
        self.name = name
        self.description = description
        self._template = list(argv_template)

    def build_argv(self, prompt: str, **kwargs: Any) -> list[str]:
        # Replace {prompt} as substring (not format()) — avoids accidental
        # interpolation of other braces in the template or prompt.
        return [tok.replace("{prompt}", prompt) for tok in self._template]


def build_registry(config: Config) -> dict[str, CLIAdapter]:
    registry: dict[str, CLIAdapter] = {}

    if config.adapters.claude.enabled:
        registry["claude"] = ClaudeCodeAdapter(
            binary=config.adapters.claude.binary,
            default_args=config.adapters.claude.default_args,
        )
    if config.adapters.codex.enabled:
        registry["codex"] = CodexAdapter(
            binary=config.adapters.codex.binary,
            default_args=config.adapters.codex.default_args,
        )
    if config.adapters.shell.enabled:
        registry["shell"] = ShellAdapter(
            command_allowlist=config.adapters.shell.command_allowlist,
        )

    for custom in config.custom_adapters:
        if not custom.enabled:
            continue
        if custom.name in registry:
            # Custom adapters cannot shadow built-ins — fail loud at startup.
            raise ValueError(
                f"custom adapter name {custom.name!r} collides with a built-in adapter"
            )
        registry[custom.name] = _TemplateAdapter(
            name=custom.name,
            description=custom.description or f"Custom adapter {custom.name}",
            argv_template=custom.argv_template,
        )

    return registry
