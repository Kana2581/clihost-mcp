# clihost-mcp

**English** | [中文](README.zh-CN.md)

An MCP server that exposes local CLIs — Claude Code, Codex CLI, shell
commands, and any custom CLI you declare in YAML — as MCP tools.

Built for the case where one agent (e.g. Claude Desktop, Cursor, Claude
Code itself) wants to delegate work to another local AI CLI, or to a remote
one via HTTP.

Requires Python 3.10+.

> ### ⚠ Security notice — please read before installing
>
> `config.example.yaml` ships with `--dangerously-skip-permissions` (Claude
> Code) and `--dangerously-bypass-approvals-and-sandbox` (Codex CLI) in the
> default args. These flags **disable the spawned CLI's per-action approval
> prompts** — they're necessary for unattended MCP usage (interactive
> prompts would otherwise deadlock the call), but they mean the spawned CLI
> can read, write, delete and execute anything inside its working directory
> with your full user privileges. clihost-mcp becomes the entire trust boundary.
>
> Before running this in production: set `defaults.cwd_allowlist`, gate the
> HTTP transport with `auth_token`, and only point clihost-mcp at directories
> you'd be OK letting an LLM rewrite. See [Security model](#security-model)
> below for the full threat model and how to opt out of the dangerous
> defaults.

---

## Install

Pick **one** of the following.

### Option A — uv (recommended)

```powershell
# install uv once: https://docs.astral.sh/uv/
uv tool install --from "/path/to/clihost_mcp" clihost-mcp
```

This puts `clihost-mcp` on PATH (under `~/.local/bin`) in its own isolated
environment. To upgrade after editing the code, re-run with `--force`.

If you'd rather not install at all and just run from the source tree, uv
can do that too:

```powershell
uv run --directory "/path/to/clihost_mcp" clihost-mcp
```

### Option B — pip

```powershell
pip install -e "/path/to/clihost_mcp"
```

Either way, `clihost-mcp --print-config` should now print the resolved config.

---

## Wiring it into MCP clients

All popular MCP clients accept the same shape of JSON config — only the
file location differs.

| Client | Config file |
| --- | --- |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` |
| Cursor | `%USERPROFILE%\.cursor\mcp.json` |
| Claude Code (CLI) | use `claude mcp add` (see below) or `~/.claude/settings.json` |
| Cline / Continue / others | their own JSON, same `mcpServers` shape |

### Config — when `clihost-mcp` is already on PATH

After Option A or B above:

```json
{
  "mcpServers": {
    "clihost-mcp": {
      "command": "clihost-mcp"
    }
  }
}
```

### Config — uv, no install

Skips the install step entirely; uv will sync deps on first run and reuse
the cached `.venv` after that:

```json
{
  "mcpServers": {
    "clihost-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/clihost_mcp",
        "run",
        "clihost-mcp"
      ]
    }
  }
}
```

### Config — with a custom config file or env vars

```json
{
  "mcpServers": {
    "clihost-mcp": {
      "command": "clihost-mcp",
      "args": ["--config", "C:\\Users\\you\\my_clihost_mcp.yaml"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

`env` here is forwarded to the `clihost-mcp` process, which in turn passes
through whatever `defaults.env_passthrough` whitelists to the spawned CLI
subprocesses.

### Claude Code CLI shortcut

Instead of hand-editing JSON, register from the terminal:

```powershell
# if clihost-mcp is on PATH
claude mcp add clihost-mcp -- clihost-mcp

# or via uv, no install
claude mcp add clihost-mcp -- uv --directory "/path/to/clihost_mcp" run clihost-mcp
```

After restart, in any Claude Code session, `/mcp` will list `clihost-mcp` and
you can call any of its tools.

---

## Tools exposed

| Tool | Purpose |
| --- | --- |
| `claude_run(prompt, cwd?, timeout_sec?, adapter_kwargs?)` | Invoke `claude -p ...` |
| `codex_run(prompt, cwd?, timeout_sec?, adapter_kwargs?)` | Invoke `codex exec ...` |
| `shell_run(prompt, cwd?, timeout_sec?)` | Run a whitelisted shell command (disabled by default) |
| `<custom>_run(...)` | Any adapter you declare under `custom_adapters` in the YAML |
| `list_adapters()` | Discover all enabled adapters and their accepted params |

Every `*_run` tool returns a uniform dict: `{stdout, stderr, exit_code,
duration_ms, truncated, timed_out, run_id, full_output_path, error}`.
`claude_run` additionally returns a `parsed` field when Claude Code's JSON
output is parseable.

---

## HTTP mode (for remote agents)

```powershell
clihost-mcp --transport http --host 127.0.0.1 --port 8765 --auth-token YOUR_TOKEN
```

Clients call the MCP endpoint with `Authorization: Bearer YOUR_TOKEN`.
Binding to a non-localhost host without an auth token is refused at
startup.

---

## Configuration

Copy `config.example.yaml` to `~/.clihost_mcp/config.yaml` (or pass
`--config <path>`, or set `$CLIHOST_MCP_CONFIG`). Resolution order is:
`--config` > env var > `~/.clihost_mcp/config.yaml` > built-in defaults.

Highlights:

- `defaults.default_cwd` — directory the spawned CLI runs in when the
  caller does not pass `cwd`. **Validated at server startup**: must exist,
  must be a directory, and (if `cwd_allowlist` is non-empty) must fall
  inside it — typos / missing dirs / contradictory configs fail fast at
  load time, not on first tool call. See "Working directory" below.
- `defaults.cwd_allowlist` — restricts which working directories tool
  calls may target. Empty list = no restriction.
- `defaults.env_passthrough` — whitelists env vars forwarded to
  subprocesses. Leave empty to inherit the full parent env.
- `defaults.proxy` — outbound HTTP proxy spliced into every spawned CLI's
  env (bypasses `env_passthrough`). Needed when Anthropic / OpenAI APIs are
  geo-blocked. See "Outbound proxy" below for the full shape and gotchas.
- `adapters.shell.command_allowlist` — required when `shell.enabled: true`.
  Compared by basename, case-insensitive; `.exe`/`.bat`/`.cmd`/`.ps1`
  stripped before matching.
- `custom_adapters` — declare additional CLIs without writing Python.
  The token `{prompt}` in `argv_template` is substituted at call time.

### Working directory

cwd resolution order, per call:

1. The `cwd` argument the caller (e.g. Claude) passed to the tool.
   Validated against `cwd_allowlist`. Rejected with a structured error if
   outside.
2. Otherwise `defaults.default_cwd` from the config (already validated at
   startup).
3. Otherwise inherit `clihost-mcp`'s own cwd — which under MCP stdio spawn is
   whatever directory the MCP client launched clihost-mcp from (usually the
   client's current project dir). This last fallback is often **not** what
   you want — surprise behaviour like "codex ended up in my Claude Code
   project dir" comes from skipping steps 1 & 2.

Recommended setup: set `default_cwd` to a fixed sandbox/scratch dir and
let `cwd_allowlist` cover that plus any project dirs you'd let callers
explicitly target.

```yaml
defaults:
  default_cwd: "C:\\Users\\you\\scratch"
  cwd_allowlist:
    - "C:\\Users\\you\\scratch"
    - "C:\\Users\\you\\projects"
```

### Outbound proxy

Anthropic and OpenAI geo-block a few regions (mainland China among them).
The symptom from inside `clihost-mcp` looks like this:

```json
{
  "exit_code": 1,
  "stdout": "{... \"is_error\": true, \"api_error_status\": 403,
              \"result\": \"Failed to authenticate. API Error: 403 Request not allowed\" ...}"
}
```

A 403 — not a network timeout — means the request **did** reach the
upstream, but the source IP wasn't allowed. Pointing the spawned CLI at a
local proxy that exits in an allowed region fixes it.

Configure once in `~/.clihost_mcp/config.yaml`:

```yaml
defaults:
  # shorthand: same URL used for both HTTP and HTTPS
  proxy: "http://127.0.0.1:7890"
```

Or the full mapping form when you need per-scheme control or a bypass list:

```yaml
defaults:
  proxy:
    url: "http://127.0.0.1:7890"      # fallback for any scheme not overridden
    https: "http://127.0.0.1:7891"    # override https only
    no_proxy: "localhost,127.0.0.1,.internal"
```

What gets injected into every spawned CLI's environment:

| Variable | Source |
| --- | --- |
| `HTTP_PROXY` / `http_proxy` | `http` if set, else `url` |
| `HTTPS_PROXY` / `https_proxy` | `https` if set, else `url` |
| `ALL_PROXY` / `all_proxy` | `https` if set, else `http` |
| `NO_PROXY` / `no_proxy` | `no_proxy` if set |

Important details:

- **Bypasses `env_passthrough`.** Even with a strict passthrough list like
  `[ANTHROPIC_API_KEY, OPENAI_API_KEY]`, the proxy variables are still
  spliced in. The passthrough filter exists to gate secrets, not plumbing.
- **Pick a port that matches your proxy client.** Clash defaults to `7890`,
  v2rayN's HTTP port is usually `10809`, Shadowsocks's local HTTP bridge
  varies. Use whatever `netstat -ano | findstr LISTEN` shows.
- **Restart your MCP client after editing.** `clihost-mcp` is launched once
  per MCP-client session; Python does not hot-reload, so an edit to
  `config.yaml` only takes effect after restarting Claude Desktop / Cursor /
  Claude Code / etc.
- **`clihost-mcp --print-config` shows the resolved proxy block** — use it to
  confirm YAML parsed the way you expected before restarting the client.
- The setting only affects subprocesses `clihost-mcp` spawns. `clihost-mcp` itself
  doesn't make outbound calls, so its own env is unaffected.

If you'd rather not maintain a per-project YAML at all, pass overrides
directly on the clihost-mcp command line. All three are validated at startup.

| Flag | Overrides | Notes |
| --- | --- | --- |
| `--default-cwd PATH` | `defaults.default_cwd` | Auto-extends `cwd_allowlist` to cover PATH when the allowlist is non-empty. |
| `--default-timeout-sec N` | `defaults.timeout_sec` | Per-call default when the caller does not pass `timeout_sec`. |
| `--max-timeout-sec N` | `defaults.max_timeout_sec` | Hard ceiling for any single tool call. Raise this for long-running agentic CLIs (codex agent mode routinely needs more than the 600s default). |

Typical MCP-client wiring for a project that needs longer codex runs:

```json
{
  "mcpServers": {
    "clihost-mcp": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/clihost_mcp",
        "run", "clihost-mcp",
        "--default-cwd", "/path/to/your/project",
        "--default-timeout-sec", "600",
        "--max-timeout-sec", "1800"
      ]
    }
  }
}
```

### Adding a custom CLI without code

```yaml
custom_adapters:
  - name: gemini
    description: "Google Gemini CLI"
    argv_template: ["gemini", "-p", "{prompt}"]
```

Registers a `gemini_run` MCP tool — no code changes; restart only the
`clihost-mcp` process (your MCP client will reconnect automatically).

---

## Security model

### ⚠ The dangerous defaults, in plain English

`config.example.yaml` ships with two flags enabled by default that turn off
the spawned CLI's own safety prompts:

| CLI | Flag | What it does |
| --- | --- | --- |
| Claude Code | `--dangerously-skip-permissions` | Auto-approves every tool use (Read, Write, Edit, Bash, …). Claude never pauses to ask. |
| Codex CLI | `--dangerously-bypass-approvals-and-sandbox` | Disables Codex's per-action approval **and** its filesystem/network sandbox. Codex runs shell commands directly with your user privileges. |

These are not paranoid warnings — they're literally how the CLIs describe
themselves. With either flag set, the spawned CLI can:

- Read any file the OS user can read.
- Write or delete any file the OS user can write — anywhere on disk if
  `cwd_allowlist` is empty.
- Execute arbitrary shell commands.
- Hit the network (proxy-routed if `defaults.proxy` is set).

**Why ship them on?** Without them, the CLI will block on stdin waiting for
human approval — but clihost-mcp gives the child `DEVNULL` for stdin (the
parent's stdin is the MCP JSON-RPC pipe, which the child must not touch).
So the call hangs until it hits the timeout. There's no middle ground in a
non-interactive wrapper: either the child has full power or it deadlocks
on its first non-trivial action.

**Threat model.** With dangerous flags on, **clihost-mcp is the entire trust
boundary** — there is nothing safer downstream of it. That puts the
responsibility on you to:

1. **Set `cwd_allowlist`.** Without it, a caller can target any directory.
   With it, the spawned CLI is confined to those prefixes. This is the
   single most important defence — please don't leave it empty.
2. **Gate the HTTP transport.** Non-localhost bind without
   `transport.http.auth_token` is rejected at startup. Even on localhost,
   set a token if anything else on the machine could call it.
3. **Mind the prompt source.** Prompts are passed straight to a CLI that
   can execute code. Treat any caller of `claude_run` / `codex_run` as
   equivalent to giving them a shell in `default_cwd`. Untrusted prompt
   text + dangerous defaults = remote code execution.
4. **Don't point `default_cwd` at sensitive directories.** Source repos
   you're OK with the LLM rewriting are fine. `~`, `/etc`, anything with
   credentials, secrets, or production config — not fine.

**How to opt out.** Delete the offending flag from
`adapters.claude.default_args` (and/or `adapters.codex.default_args`) in
your config. Calls that need approval will then hang until they time out
— that's the cost of the safe choice in a non-interactive wrapper. You'll
probably want to combine this with a smaller `defaults.timeout_sec` (say
30s) so hangs fail fast.

### Other guarantees (independent of the dangerous flags)

- No `shell=True` anywhere; argv is always a list — command injection is
  structurally impossible.
- `cwd` parameters are validated against `cwd_allowlist`.
- The `shell` adapter is disabled by default; enabling it requires an
  explicit `command_allowlist`. Commands are matched by basename (case
  insensitive, `.exe`/`.bat`/`.cmd`/`.ps1` stripped).
- Per-call timeout, capped server-side by `defaults.max_timeout_sec`
  regardless of caller input.
- HTTP transport: localhost-only without an auth token; with one, every
  request must carry `Authorization: Bearer <token>`.
- `env_passthrough` filters which env vars reach the spawned CLI — useful
  for keeping unrelated secrets out of the child process. `defaults.proxy`
  is the one exception: it's injected unconditionally because it's network
  plumbing, not a secret.
- Output truncation at 100 KiB/stream (configurable). Truncated runs
  persist full output under `~/.clihost_mcp/runs/<run_id>/` and the path is
  returned to the caller.

---

## CLI-specific notes

- **Codex CLI** refuses to run outside a git repository unless invoked
  with `--skip-git-repo-check`. The example config sets that as a default
  arg — remove it if you only ever invoke from inside a repo.
- **Claude Code** authentication: `claude -p` reuses the OAuth/credential
  state from your interactive login. If you get `403 Request not
  allowed`, the issue is on the `claude` CLI side (account/region/auth)
  not in clihost_mcp — verify with a direct `claude -p "test"` in your shell.
- **Windows + `.cmd` shims** (npm-installed CLIs like `codex.cmd`):
  handled automatically — the runner resolves bare names via
  `shutil.which`, which respects PATHEXT.

---

## Layout

```
src/clihost_mcp/
├── server.py       # FastMCP wiring; dynamic tool registration
├── runner.py       # subprocess execution (timeout, truncation, PATHEXT)
├── config.py       # YAML + Pydantic
├── registry.py     # built-in + custom adapter assembly
├── cli.py          # `clihost-mcp` entry point
└── adapters/
    ├── base.py
    ├── claude_code.py
    ├── codex.py
    └── shell.py
```

---

## Development

```powershell
# with uv
uv sync --extra dev
uv run pytest

# with pip
pip install -e ".[dev]"
pytest
```

`smoke_test.py` at the repo root spins up the server in-process and drives
it through the FastMCP `Client` — useful for verifying end-to-end without
a real MCP client attached.
