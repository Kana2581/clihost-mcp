"""FastMCP server: registers one `<name>_run` tool per enabled adapter."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from fastmcp import FastMCP

from clihost_mcp.adapters.base import AdapterError, CLIAdapter
from clihost_mcp.config import Config, DefaultsConfig
from clihost_mcp.registry import build_registry
from clihost_mcp.runner import filter_env, run_subprocess


def _build_subprocess_env(defaults: DefaultsConfig) -> Optional[dict[str, str]]:
    """Compose the env dict handed to spawned CLIs.

    Returns None to mean "inherit the full parent env" — only possible when
    neither env_passthrough nor proxy is configured. Otherwise builds an
    explicit dict: env_passthrough filters parent env, then proxy keys are
    overlaid unconditionally (proxy is plumbing, not a secret, so it always
    propagates).
    """
    if not defaults.env_passthrough and defaults.proxy is None:
        return None
    env = filter_env(defaults.env_passthrough) if defaults.env_passthrough else dict(os.environ)
    if defaults.proxy is not None:
        env.update(defaults.proxy.to_env())
    return env


def _cwd_is_allowed(cwd: str, allowlist: list[str]) -> bool:
    if not allowlist:
        return True
    try:
        target = Path(cwd).resolve()
    except OSError:
        return False
    for prefix in allowlist:
        try:
            prefix_path = Path(prefix).expanduser().resolve()
        except OSError:
            continue
        try:
            target.relative_to(prefix_path)
            return True
        except ValueError:
            continue
    return False


def _make_tool(
    adapter: CLIAdapter,
    config: Config,
):
    """Build the async tool function for an adapter.

    Returns an awaitable that takes (prompt, cwd, timeout_sec, **adapter_kwargs)
    and returns a dict. Dynamically named so FastMCP can register it under
    `<adapter.name>_run`.
    """

    runs_dir = config.resolved_runs_dir()
    defaults = config.defaults

    async def _tool(
        prompt: str,
        cwd: Optional[str] = None,
        adapter_kwargs: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        # Caller-supplied cwd is validated against the allowlist; otherwise
        # fall back to defaults.default_cwd (already validated at config load).
        effective_cwd = cwd if cwd is not None else defaults.default_cwd
        if cwd is not None and not _cwd_is_allowed(cwd, defaults.cwd_allowlist):
            return {
                "error": f"cwd {cwd!r} is not within configured cwd_allowlist",
                "exit_code": None,
            }
        timeout = min(defaults.timeout_sec, defaults.max_timeout_sec)

        kwargs = adapter_kwargs or {}
        try:
            argv = adapter.build_argv(prompt, **kwargs)
        except AdapterError as e:
            return {"error": str(e), "exit_code": None}
        except TypeError as e:
            return {"error": f"invalid adapter_kwargs: {e}", "exit_code": None}

        env = _build_subprocess_env(defaults)

        result = await run_subprocess(
            argv,
            cwd=effective_cwd,
            timeout_sec=timeout,
            max_output_bytes=defaults.max_output_bytes,
            env=env,
            runs_dir=runs_dir,
        )
        return adapter.parse_output(result)

    _tool.__name__ = f"{adapter.name}_run"
    _tool.__doc__ = (
        f"{adapter.description}\n\n"
        "Args:\n"
        "  prompt: the prompt/command to send to the CLI.\n"
        "  cwd: optional working directory (must be inside cwd_allowlist if configured).\n"
        "  adapter_kwargs: optional adapter-specific parameters; "
        f"accepted keys: {sorted(adapter.extra_params.keys()) or 'none'}.\n"
    )
    return _tool


def build_server(config: Config) -> FastMCP:
    mcp = FastMCP(name="clihost-mcp")
    registry = build_registry(config)

    for adapter in registry.values():
        tool_fn = _make_tool(adapter, config)
        mcp.tool(
            name=f"{adapter.name}_run",
            description=adapter.description,
        )(tool_fn)

    @mcp.tool(
        name="list_adapters",
        description="List all enabled CLI adapters with their descriptions and accepted parameters.",
    )
    def list_adapters() -> dict[str, Any]:
        return {
            "adapters": [
                {
                    "name": adapter.name,
                    "tool_name": f"{adapter.name}_run",
                    "description": adapter.description,
                    "extra_params": adapter.extra_params,
                }
                for adapter in registry.values()
            ]
        }

    return mcp


def run_server(config: Config, transport: str) -> None:
    mcp = build_server(config)
    if transport == "stdio":
        mcp.run()
        return
    if transport == "http":
        http = config.transport.http
        if http.host not in ("127.0.0.1", "localhost") and not http.auth_token:
            raise SystemExit(
                f"refusing to bind {http.host!r} without an auth_token — "
                "set transport.http.auth_token in the config."
            )
        if http.auth_token:
            _run_http_with_auth(mcp, http.host, http.port, http.auth_token)
        else:
            mcp.run(transport="streamable-http", host=http.host, port=http.port)
        return
    raise ValueError(f"unknown transport: {transport!r}")


def _run_http_with_auth(mcp: FastMCP, host: str, port: int, token: str) -> None:
    """Wrap the FastMCP ASGI app with a Bearer-token check, then serve it."""
    import uvicorn
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class BearerAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            header = request.headers.get("authorization", "")
            expected = f"Bearer {token}"
            if header != expected:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    inner = mcp.http_app(transport="streamable-http")
    app = Starlette(
        routes=inner.routes,
        middleware=[Middleware(BearerAuthMiddleware)],
        lifespan=inner.lifespan,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")
