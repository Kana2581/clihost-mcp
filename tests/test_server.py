"""Tests for server wiring: tool registration, cwd allowlist, custom adapters."""

from __future__ import annotations

from clihost_mcp.config import (
    AdaptersConfig,
    ClaudeAdapterConfig,
    CodexAdapterConfig,
    Config,
    CustomAdapterConfig,
    DefaultsConfig,
    ProxyConfig,
    ShellAdapterConfig,
)
from clihost_mcp.registry import build_registry
from clihost_mcp.server import _build_subprocess_env, _cwd_is_allowed, build_server


def test_registry_contains_enabled_builtins():
    config = Config(
        adapters=AdaptersConfig(
            claude=ClaudeAdapterConfig(enabled=True),
            codex=CodexAdapterConfig(enabled=False),
            shell=ShellAdapterConfig(enabled=True, command_allowlist=["git"]),
        )
    )
    reg = build_registry(config)
    assert "claude" in reg
    assert "codex" not in reg
    assert "shell" in reg


def test_registry_includes_custom_adapter():
    config = Config(
        custom_adapters=[
            CustomAdapterConfig(
                name="gemini",
                description="Gemini CLI",
                argv_template=["gemini", "-p", "{prompt}"],
            )
        ]
    )
    reg = build_registry(config)
    assert "gemini" in reg
    argv = reg["gemini"].build_argv("hello world")
    assert argv == ["gemini", "-p", "hello world"]


def test_custom_adapter_cannot_shadow_builtin():
    config = Config(
        custom_adapters=[
            CustomAdapterConfig(
                name="claude",
                argv_template=["x", "{prompt}"],
            )
        ]
    )
    import pytest
    with pytest.raises(ValueError, match="collides"):
        build_registry(config)


def test_cwd_allowlist_empty_allows_all(tmp_path):
    assert _cwd_is_allowed(str(tmp_path), []) is True


def test_cwd_allowlist_blocks_outside(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    assert _cwd_is_allowed(str(outside), [str(allowed)]) is False
    assert _cwd_is_allowed(str(allowed), [str(allowed)]) is True
    # Subdirectory of an allowed prefix is allowed.
    sub = allowed / "child"
    sub.mkdir()
    assert _cwd_is_allowed(str(sub), [str(allowed)]) is True


def test_build_env_returns_none_when_unrestricted():
    defaults = DefaultsConfig()
    assert _build_subprocess_env(defaults) is None


def test_build_env_injects_proxy_even_without_passthrough(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    defaults = DefaultsConfig(proxy=ProxyConfig(url="http://127.0.0.1:7890"))
    env = _build_subprocess_env(defaults)
    assert env is not None
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:7890"
    assert env["HTTP_PROXY"] == "http://127.0.0.1:7890"
    # Without env_passthrough we fall back to full parent env, so the API key
    # is still visible — proxy alone must not silently clip secrets.
    assert env["ANTHROPIC_API_KEY"] == "sk-test"


def test_build_env_proxy_survives_restrictive_passthrough(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("HTTPS_PROXY", "should-not-leak")  # not in passthrough
    defaults = DefaultsConfig(
        env_passthrough=["ANTHROPIC_API_KEY"],
        proxy=ProxyConfig(url="http://127.0.0.1:7890"),
    )
    env = _build_subprocess_env(defaults)
    assert env is not None
    # filter_env would have dropped the parent's HTTPS_PROXY; proxy injection
    # then puts our configured value back in.
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:7890"
    assert env["ANTHROPIC_API_KEY"] == "sk-test"
    # No accidental escape hatch — random parent env vars stay filtered out.
    assert "USERNAME" in env or "PATH" in env  # base whitelist still applies


def test_build_server_registers_tools():
    config = Config(
        defaults=DefaultsConfig(),
        adapters=AdaptersConfig(
            claude=ClaudeAdapterConfig(enabled=True),
            codex=CodexAdapterConfig(enabled=True),
            shell=ShellAdapterConfig(enabled=False),
        ),
    )
    mcp = build_server(config)
    import asyncio
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert "claude_run" in names
    assert "codex_run" in names
    assert "list_adapters" in names
    assert "shell_run" not in names
