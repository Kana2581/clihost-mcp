# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`clihost-mcp` is a FastMCP server (Python 3.10+) that exposes local CLIs — Claude Code (`claude`), Codex CLI (`codex`), an opt-in `shell` adapter, and any CLI declared under `custom_adapters:` in YAML — as MCP tools. One agent uses it to delegate work to another local AI CLI (or to a remote one over HTTP).

A more detailed contributor guide lives in `AGENTS.md` (bilingual EN/中文); the user-facing reference is `README.md`. Both should stay consistent with code behaviour — if they drift, fix the doc or the code, don't paper over it.

## Commands

```powershell
# install dev deps
uv sync --extra dev          # or: pip install -e ".[dev]"

# run from source (no install)
uv run --directory "/path/to/clihost_mcp" clihost-mcp

# install as a global tool (puts `clihost-mcp` on PATH)
uv tool install --force --from "/path/to/clihost_mcp" clihost-mcp

# inspect resolved config (after YAML + env + CLI overrides)
clihost-mcp --print-config

# tests
uv run pytest                # or: pytest
uv run pytest tests/test_runner.py::test_name -q   # single test
```

`smoke_test.py` at the repo root drives the in-process server via a FastMCP `Client` and makes a real `claude_run` call — handy for end-to-end verification without wiring an MCP client. It needs a working `claude` binary on PATH.

## Architecture

Request flow for a single tool call (e.g. `claude_run`):

```
MCP client
   │  JSON-RPC over stdio (or HTTP)
   ▼
cli.py        parses argv, applies --default-cwd / --max-timeout-sec overrides
   │
config.py     loads & validates YAML; ProxyConfig coerces "url-string" shorthand;
   │          Config validator checks default_cwd exists and is inside cwd_allowlist
   ▼
server.py     build_server() iterates the registry, registers `<name>_run` per
   │          adapter + `list_adapters()`. _make_tool wraps the call: validates
   │          caller `cwd` against allowlist, clamps timeout to max_timeout_sec,
   │          builds env (filter_env + proxy overlay), calls runner.
   ▼
registry.py   merges built-in adapters with YAML `custom_adapters`. Custom names
   │          cannot shadow built-ins (raises at startup). `{prompt}` token
   │          substitution is plain string-replace, not str.format.
   ▼
adapters/     each adapter only turns (prompt, kwargs) into argv (+ optional
   │          parse_output). No subprocess work here.
   ▼
runner.py     run_subprocess: shutil.which() resolves bare names so Windows
              `.cmd`/`.bat` shims work (asyncio doesn't honour PATHEXT). stdin is
              DEVNULL unless a payload is given (parent stdin is the MCP pipe).
              Output is capped at max_output_bytes/stream; truncated runs are
              persisted to runs_dir and the path is returned.
```

Module boundary is load-bearing — keep it: **config in `config.py`, execution in `runner.py`, tool/server wiring in `server.py`, argv assembly in `adapters/`.** All subprocesses must go through `runner.run_subprocess`.

## Invariants you must not break

- **No `shell=True`, ever.** argv is always a list. Command injection is structurally impossible by construction; that property is the project's reason to exist.
- **`cwd` resolution order is: caller arg (allowlist-checked) → `defaults.default_cwd` → clihost-mcp's own cwd.** That last fallback is usually wrong under MCP stdio (cwd = whatever directory the client launched clihost-mcp from). Don't paper over a missing `default_cwd` by changing the fallback.
- **`defaults.proxy` bypasses `env_passthrough`.** Proxy is plumbing, not a secret. Both lowercase and UPPERCASE variants are injected (`HTTP_PROXY`/`http_proxy`, etc.).
- **`filter_env`'s base whitelist must keep Windows essentials.** Node-based CLIs (`claude`, `codex`) abort on CSPRNG init if `PATH`, `SystemRoot`, `PROCESSOR_*`, `COMPUTERNAME`, etc. are stripped. Don't trim that list without checking codex still boots.
- **Caller timeouts are clamped by `defaults.max_timeout_sec` before reaching the runner**, and the runner additionally caps at `HARD_TIMEOUT_CEILING_SEC` (24h) as a backstop against `float('inf')`.
- **HTTP transport refuses non-localhost bind without `auth_token`.** With a token, every request needs `Authorization: Bearer <token>` (enforced by `BearerAuthMiddleware`).
- **Custom adapters require `{prompt}` somewhere in `argv_template`** (validated in `CustomAdapterConfig`) and their `name` must be a valid Python identifier.

## Config resolution

`--config` > `$CLIHOST_MCP_CONFIG` > `~/.clihost_mcp/config.yaml` > built-in defaults (in `DefaultsConfig`). Built-in defaults: `timeout_sec=120`, `max_timeout_sec=600`, `max_output_bytes=102_400`, `shell.enabled=False`. `config.example.yaml` is a sample, not loaded automatically.

`clihost-mcp --print-config` shows the post-merge view (after CLI overrides) — always confirm with this before debugging a "config didn't take effect" issue. MCP clients spawn `clihost-mcp` once per session; YAML edits only land after restarting the client (Claude Desktop / Cursor / Claude Code).

## Tests

- `pyproject.toml` sets `asyncio_mode = "auto"` and `testpaths = ["tests"]`.
- Unit tests should not require real `claude` / `codex` / `gemini` binaries — use `sys.executable`, `python -c ...`, temp dirs, and direct config-object construction instead.
- Update tests when changing: subprocess execution, security checks (cwd/allowlist/auth), config parsing/validation, adapter argv, or tool registration.

## Things not to do

- Don't commit `__pycache__/`, `.pytest_cache/`, `.venv/`, user configs, API keys, OAuth/credential state, or anything under `~/.clihost_mcp/runs/`.
- Don't hard-code local absolute paths (the Windows ones in `README.md` / `config.example.yaml` are examples for this machine, not defaults).
- No new ruff/black/mypy/etc. step — the project hasn't adopted one and tests don't run it. Don't claim "lint" or "format" as a required command.
