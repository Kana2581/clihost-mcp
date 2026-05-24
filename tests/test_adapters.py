"""Tests for adapter argv construction. No subprocesses are spawned."""

from __future__ import annotations

import pytest

from clihost_mcp.adapters import ClaudeCodeAdapter, CodexAdapter, ShellAdapter
from clihost_mcp.adapters.base import AdapterError


def test_claude_basic_argv():
    a = ClaudeCodeAdapter()
    argv = a.build_argv("do thing")
    assert argv[0] == "claude"
    assert "-p" in argv
    assert "do thing" in argv
    assert "--output-format" in argv
    assert "json" in argv
    # Permission prompts would deadlock a non-interactive MCP call; the default
    # must skip them. If you intentionally tighten this, also tighten the
    # corresponding default in ClaudeAdapterConfig.
    assert "--dangerously-skip-permissions" in argv


def test_claude_config_default_args_match_adapter():
    # Guard against drift between the Pydantic default and the adapter's
    # constructor fallback — they're separately maintained.
    from clihost_mcp.config import ClaudeAdapterConfig

    cfg = ClaudeAdapterConfig()
    a = ClaudeCodeAdapter(default_args=cfg.default_args)
    argv = a.build_argv("x")
    assert "--output-format" in argv
    assert "--dangerously-skip-permissions" in argv


def test_claude_with_model_and_system():
    a = ClaudeCodeAdapter()
    argv = a.build_argv(
        "x",
        model="claude-opus-4-7",
        system_prompt="you are concise",
        allowed_tools=["Read", "Grep"],
        session_id="abc",
    )
    assert "--model" in argv
    assert "claude-opus-4-7" in argv
    assert "--system-prompt" in argv
    assert "you are concise" in argv
    assert "--allowedTools" in argv
    assert "Read,Grep" in argv
    assert "--resume" in argv
    assert "abc" in argv


def test_claude_custom_binary():
    a = ClaudeCodeAdapter(binary="C:\\custom\\claude.exe", default_args=[])
    argv = a.build_argv("hi")
    assert argv[0] == "C:\\custom\\claude.exe"
    assert "--output-format" not in argv


def test_codex_basic_argv():
    a = CodexAdapter()
    argv = a.build_argv("refactor this")
    assert argv == ["codex", "exec", "refactor this"]


def test_codex_with_model():
    a = CodexAdapter()
    argv = a.build_argv("x", model="gpt-5")
    assert "--model" in argv
    assert "gpt-5" in argv
    # prompt comes last
    assert argv[-1] == "x"


def test_shell_blocks_non_allowlisted():
    a = ShellAdapter(command_allowlist=["git"])
    with pytest.raises(AdapterError):
        a.build_argv("rm -rf /")


def test_shell_allows_listed():
    a = ShellAdapter(command_allowlist=["git"])
    argv = a.build_argv("git status")
    assert argv == ["git", "status"]


def test_shell_basename_match_with_extension():
    # Windows: `git.exe` should match an allowlist entry of `git`.
    a = ShellAdapter(command_allowlist=["git"])
    argv = a.build_argv("git.exe log")
    assert argv[0] == "git.exe"


def test_shell_argv_override():
    a = ShellAdapter(command_allowlist=["python"])
    argv = a.build_argv("ignored", argv=["python", "-c", "print(1)"])
    assert argv == ["python", "-c", "print(1)"]


def test_shell_empty_rejected():
    a = ShellAdapter(command_allowlist=["git"])
    with pytest.raises(AdapterError):
        a.build_argv("")
