"""`cli-mcp` command-line entry point."""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from pathlib import Path

from cli_mcp.config import Config, load_config
from cli_mcp.server import run_server


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cli-mcp",
        description="MCP server that exposes local CLIs (Claude Code, Codex, shell) as tools.",
    )
    p.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default=None,
        help="Transport to use. Defaults to the value in config (transport.default), else 'stdio'.",
    )
    p.add_argument(
        "--host",
        default=None,
        help="HTTP bind host (overrides config). Only used with --transport http.",
    )
    p.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP bind port (overrides config). Only used with --transport http.",
    )
    p.add_argument(
        "--auth-token",
        default=None,
        help="HTTP Bearer auth token (overrides config). Only used with --transport http.",
    )
    p.add_argument(
        "--config",
        default=None,
        help="Path to config YAML. Defaults to $CLI_MCP_CONFIG or ~/.cli_mcp/config.yaml.",
    )
    p.add_argument(
        "--default-cwd",
        default=None,
        help=(
            "Override defaults.default_cwd from the command line — handy when "
            "you don't want to maintain a per-project YAML. The path is also "
            "auto-added to cwd_allowlist (if the allowlist is non-empty) so "
            "the override doesn't get rejected by its own guard. Validated at "
            "startup: must exist and be a directory."
        ),
    )
    p.add_argument(
        "--default-timeout-sec",
        type=float,
        default=None,
        help="Override defaults.timeout_sec (per-call default when the caller does not pass timeout_sec).",
    )
    p.add_argument(
        "--max-timeout-sec",
        type=float,
        default=None,
        help="Override defaults.max_timeout_sec (hard ceiling for any single tool call).",
    )
    p.add_argument(
        "--print-config",
        action="store_true",
        help="Print the resolved config as JSON and exit.",
    )
    return p


def _apply_default_cwd_override(config: Config, path: str) -> Config:
    """Apply --default-cwd to a loaded Config, re-running Pydantic validation.

    Auto-extends cwd_allowlist to cover the override (when the allowlist is
    non-empty), so passing the flag is equivalent to "trust this path for the
    duration of this process" without forcing the user to also edit the YAML.
    """
    data = config.model_dump()
    data["defaults"]["default_cwd"] = path
    allowlist = data["defaults"].get("cwd_allowlist") or []
    if allowlist:
        try:
            target = Path(path).expanduser().resolve()
            covered = False
            for prefix in allowlist:
                try:
                    p = Path(prefix).expanduser().resolve()
                    target.relative_to(p)
                    covered = True
                    break
                except (ValueError, OSError):
                    continue
            if not covered:
                allowlist.append(path)
                data["defaults"]["cwd_allowlist"] = allowlist
        except OSError:
            pass  # let the validator raise the real error
    return Config.model_validate(data)


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)

    if args.default_cwd is not None:
        config = _apply_default_cwd_override(config, args.default_cwd)

    if args.max_timeout_sec is not None or args.default_timeout_sec is not None:
        data = config.model_dump()
        if args.max_timeout_sec is not None:
            data["defaults"]["max_timeout_sec"] = args.max_timeout_sec
        if args.default_timeout_sec is not None:
            data["defaults"]["timeout_sec"] = args.default_timeout_sec
        config = Config.model_validate(data)

    if args.host is not None:
        config.transport.http.host = args.host
    if args.port is not None:
        config.transport.http.port = args.port
    if args.auth_token is not None:
        config.transport.http.auth_token = args.auth_token

    transport = args.transport or config.transport.default

    if args.print_config:
        import json
        print(json.dumps(config.model_dump(), indent=2, default=str))
        return

    try:
        run_server(config, transport=transport)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
