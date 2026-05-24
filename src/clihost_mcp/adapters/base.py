"""CLI adapter abstraction.

An adapter knows how to build the argv for a particular CLI given a prompt
plus optional adapter-specific kwargs. The runner executes that argv; the
adapter then gets a chance to post-process the raw output (e.g. parse JSON).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from clihost_mcp.runner import RunResult


class AdapterError(Exception):
    """Raised when an adapter rejects an invocation (validation, allowlist, etc.)."""


class CLIAdapter(ABC):
    name: str = ""
    description: str = ""
    # JSON-schema-like dict describing extra kwargs the adapter accepts (for
    # tool schema generation). prompt/cwd/timeout are common and handled
    # uniformly by the server layer.
    extra_params: dict[str, dict[str, Any]] = {}

    @abstractmethod
    def build_argv(self, prompt: str, **kwargs: Any) -> list[str]:
        """Return the full argv list to execute."""

    def parse_output(self, result: RunResult) -> dict[str, Any]:
        """Default: pass through the raw RunResult dict.

        Adapters can override to enrich the response (e.g. parse JSON stdout
        into structured fields).
        """
        return result.to_dict()
