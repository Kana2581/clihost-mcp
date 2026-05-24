"""Configuration loading and validation.

Resolution order:
1. explicit path passed to load_config
2. $CLIHOST_MCP_CONFIG
3. ~/.clihost_mcp/config.yaml
4. built-in defaults
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class ProxyConfig(BaseModel):
    """Outbound HTTP proxy injected into every subprocess env.

    `url` is a shorthand: when set, it populates both HTTP_PROXY and HTTPS_PROXY.
    `http`/`https` override per-scheme. `no_proxy` is a comma-separated bypass
    list. Proxy env vars are always injected, regardless of `env_passthrough` —
    that filter exists to restrict secrets, not network plumbing.
    """

    url: Optional[str] = None
    http: Optional[str] = None
    https: Optional[str] = None
    no_proxy: Optional[str] = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "ProxyConfig":
        if not (self.url or self.http or self.https):
            raise ValueError(
                "proxy must set at least one of 'url', 'http', or 'https'"
            )
        return self

    def to_env(self) -> dict[str, str]:
        """Build the env var dict to splice into subprocess env."""
        http = self.http or self.url
        https = self.https or self.url
        out: dict[str, str] = {}
        if http:
            out["HTTP_PROXY"] = http
            out["http_proxy"] = http
        if https:
            out["HTTPS_PROXY"] = https
            out["https_proxy"] = https
        all_proxy = https or http
        if all_proxy:
            out["ALL_PROXY"] = all_proxy
            out["all_proxy"] = all_proxy
        if self.no_proxy:
            out["NO_PROXY"] = self.no_proxy
            out["no_proxy"] = self.no_proxy
        return out


class DefaultsConfig(BaseModel):
    timeout_sec: float = 120.0
    # Hard ceiling for caller-supplied timeout_sec. Tools cannot run longer
    # than this regardless of what the agent asks for. Bump it when wrapping
    # long-running agentic CLIs (codex agentic mode can routinely take 10+ min).
    max_timeout_sec: float = 600.0
    max_output_bytes: int = 100 * 1024
    cwd_allowlist: list[str] = Field(default_factory=list)
    env_passthrough: list[str] = Field(default_factory=list)
    runs_dir: Optional[str] = None  # None => ~/.clihost_mcp/runs
    # When a tool call does not supply `cwd`, the subprocess is spawned here.
    # If unset, the subprocess inherits clihost-mcp's own cwd (which under MCP
    # stdio spawn is whatever the MCP client launched clihost-mcp from — usually
    # the client's current project dir, which may not be what you want).
    default_cwd: Optional[str] = None
    # Outbound proxy applied to every spawned subprocess. Either a bare URL
    # string (`proxy: "http://127.0.0.1:7890"`) or a mapping with per-scheme
    # entries (`proxy: { https: ..., no_proxy: ... }`). Bypasses env_passthrough
    # so a restrictive passthrough list does not silently disable the proxy.
    proxy: Optional[ProxyConfig] = None

    @field_validator("timeout_sec", "max_timeout_sec")
    @classmethod
    def _positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("must be > 0")
        return v

    @field_validator("proxy", mode="before")
    @classmethod
    def _coerce_proxy(cls, v):
        # Allow the user to write `proxy: "http://127.0.0.1:7890"` in YAML
        # instead of `proxy: { url: "..." }`.
        if isinstance(v, str):
            return {"url": v}
        return v

    @model_validator(mode="after")
    def _timeout_within_ceiling(self) -> "DefaultsConfig":
        if self.timeout_sec > self.max_timeout_sec:
            raise ValueError(
                f"defaults.timeout_sec ({self.timeout_sec}) cannot exceed "
                f"defaults.max_timeout_sec ({self.max_timeout_sec})"
            )
        return self


class ClaudeAdapterConfig(BaseModel):
    enabled: bool = True
    binary: str = "claude"
    # --dangerously-skip-permissions: suppress the interactive per-tool approval
    #   prompt that would otherwise hang an MCP call forever. claude-code runs
    #   with the user's full privileges inside default_cwd — only safe because
    #   clihost-mcp itself is the trust boundary (cwd_allowlist + you control who
    #   can call claude_run). Drop this flag if you want claude-code to refuse
    #   anything beyond read-only.
    default_args: list[str] = Field(
        default_factory=lambda: [
            "--output-format",
            "json",
            "--dangerously-skip-permissions",
        ]
    )


class CodexAdapterConfig(BaseModel):
    enabled: bool = True
    binary: str = "codex"
    default_args: list[str] = Field(default_factory=list)


class ShellAdapterConfig(BaseModel):
    enabled: bool = False  # opt-in for safety
    command_allowlist: list[str] = Field(default_factory=list)


class AdaptersConfig(BaseModel):
    claude: ClaudeAdapterConfig = Field(default_factory=ClaudeAdapterConfig)
    codex: CodexAdapterConfig = Field(default_factory=CodexAdapterConfig)
    shell: ShellAdapterConfig = Field(default_factory=ShellAdapterConfig)


class CustomAdapterConfig(BaseModel):
    name: str
    description: str = ""
    argv_template: list[str]  # supports {prompt} placeholder in any token
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not v.isidentifier():
            raise ValueError(f"adapter name {v!r} must be a valid Python identifier")
        return v

    @field_validator("argv_template")
    @classmethod
    def _nonempty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("argv_template must be non-empty")
        joined = " ".join(v)
        if "{prompt}" not in joined:
            raise ValueError("argv_template must contain {prompt} placeholder in at least one token")
        return v


class HttpConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765
    auth_token: Optional[str] = None


class TransportConfig(BaseModel):
    default: str = "stdio"  # "stdio" | "http"
    http: HttpConfig = Field(default_factory=HttpConfig)


class Config(BaseModel):
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    adapters: AdaptersConfig = Field(default_factory=AdaptersConfig)
    custom_adapters: list[CustomAdapterConfig] = Field(default_factory=list)
    transport: TransportConfig = Field(default_factory=TransportConfig)

    def resolved_runs_dir(self) -> Path:
        if self.defaults.runs_dir:
            return Path(self.defaults.runs_dir).expanduser()
        return Path.home() / ".clihost_mcp" / "runs"

    @model_validator(mode="after")
    def _validate_default_cwd(self) -> "Config":
        # Catches typos and missing dirs at server startup rather than at first
        # tool call. Also enforces that default_cwd is inside cwd_allowlist when
        # the allowlist is non-empty (otherwise the allowlist would silently
        # block every default-cwd call).
        d = self.defaults
        if not d.default_cwd:
            return self
        path = Path(d.default_cwd).expanduser()
        try:
            resolved = path.resolve(strict=True)
        except (OSError, FileNotFoundError):
            raise ValueError(
                f"defaults.default_cwd {d.default_cwd!r} does not exist or is inaccessible"
            )
        if not resolved.is_dir():
            raise ValueError(
                f"defaults.default_cwd {d.default_cwd!r} is not a directory"
            )
        if d.cwd_allowlist:
            inside = False
            for prefix in d.cwd_allowlist:
                try:
                    prefix_resolved = Path(prefix).expanduser().resolve()
                except OSError:
                    continue
                try:
                    resolved.relative_to(prefix_resolved)
                    inside = True
                    break
                except ValueError:
                    continue
            if not inside:
                raise ValueError(
                    f"defaults.default_cwd {d.default_cwd!r} is not inside "
                    f"any cwd_allowlist entry {d.cwd_allowlist}"
                )
        return self


def _candidate_paths(explicit: Optional[str]) -> list[Path]:
    if explicit:
        return [Path(explicit).expanduser()]
    env = os.environ.get("CLIHOST_MCP_CONFIG")
    if env:
        return [Path(env).expanduser()]
    return [Path.home() / ".clihost_mcp" / "config.yaml"]


def load_config(path: Optional[str] = None) -> Config:
    """Load config from disk if present, otherwise return defaults."""
    for candidate in _candidate_paths(path):
        if candidate.is_file():
            with candidate.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return Config.model_validate(data)
    return Config()
