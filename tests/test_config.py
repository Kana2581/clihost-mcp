"""Tests for config loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from clihost_mcp.config import Config, load_config


def test_defaults_when_no_file(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CLIHOST_MCP_CONFIG", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = load_config(None)
    assert isinstance(cfg, Config)
    assert cfg.defaults.timeout_sec == 120.0
    assert cfg.adapters.shell.enabled is False
    assert cfg.transport.default == "stdio"


def test_loads_yaml_file(tmp_path: Path):
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(
        """
defaults:
  timeout_sec: 30
adapters:
  shell:
    enabled: true
    command_allowlist: [git, ls]
custom_adapters:
  - name: gemini
    argv_template: ["gemini", "-p", "{prompt}"]
""",
        encoding="utf-8",
    )
    cfg = load_config(str(cfg_path))
    assert cfg.defaults.timeout_sec == 30
    assert cfg.adapters.shell.enabled is True
    assert "git" in cfg.adapters.shell.command_allowlist
    assert cfg.custom_adapters[0].name == "gemini"


def test_custom_adapter_requires_prompt_placeholder():
    with pytest.raises(Exception):  # Pydantic ValidationError
        Config.model_validate(
            {"custom_adapters": [{"name": "bad", "argv_template": ["foo", "bar"]}]}
        )


def test_custom_adapter_name_must_be_identifier():
    with pytest.raises(Exception):
        Config.model_validate(
            {
                "custom_adapters": [
                    {"name": "bad-name", "argv_template": ["foo", "{prompt}"]}
                ]
            }
        )


def test_default_cwd_must_exist():
    with pytest.raises(Exception, match="default_cwd"):
        Config.model_validate(
            {"defaults": {"default_cwd": "Z:\\definitely\\does\\not\\exist\\xyz"}}
        )


def test_default_cwd_must_be_directory(tmp_path: Path):
    f = tmp_path / "afile.txt"
    f.write_text("hi", encoding="utf-8")
    with pytest.raises(Exception, match="not a directory"):
        Config.model_validate({"defaults": {"default_cwd": str(f)}})


def test_default_cwd_must_be_inside_allowlist(tmp_path: Path):
    inside = tmp_path / "allowed"
    inside.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(Exception, match="not inside"):
        Config.model_validate(
            {
                "defaults": {
                    "default_cwd": str(outside),
                    "cwd_allowlist": [str(inside)],
                }
            }
        )


def test_max_timeout_must_be_positive():
    with pytest.raises(Exception, match="> 0"):
        Config.model_validate({"defaults": {"max_timeout_sec": 0}})


def test_default_timeout_cannot_exceed_max():
    with pytest.raises(Exception, match="cannot exceed"):
        Config.model_validate(
            {"defaults": {"timeout_sec": 1000, "max_timeout_sec": 500}}
        )


def test_timeout_within_ceiling_accepted():
    cfg = Config.model_validate(
        {"defaults": {"timeout_sec": 300, "max_timeout_sec": 1800}}
    )
    assert cfg.defaults.timeout_sec == 300
    assert cfg.defaults.max_timeout_sec == 1800


def test_proxy_string_shorthand_is_coerced():
    cfg = Config.model_validate(
        {"defaults": {"proxy": "http://127.0.0.1:7890"}}
    )
    assert cfg.defaults.proxy is not None
    assert cfg.defaults.proxy.url == "http://127.0.0.1:7890"
    env = cfg.defaults.proxy.to_env()
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:7890"
    assert env["HTTP_PROXY"] == "http://127.0.0.1:7890"
    assert env["ALL_PROXY"] == "http://127.0.0.1:7890"
    assert env["https_proxy"] == env["HTTPS_PROXY"]


def test_proxy_mapping_form_with_overrides():
    cfg = Config.model_validate(
        {
            "defaults": {
                "proxy": {
                    "url": "http://127.0.0.1:7890",
                    "https": "http://127.0.0.1:7891",
                    "no_proxy": "localhost,127.0.0.1",
                }
            }
        }
    )
    env = cfg.defaults.proxy.to_env()
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:7891"  # https override wins
    assert env["HTTP_PROXY"] == "http://127.0.0.1:7890"   # falls back to url
    assert env["NO_PROXY"] == "localhost,127.0.0.1"


def test_proxy_empty_object_rejected():
    with pytest.raises(Exception, match="at least one"):
        Config.model_validate({"defaults": {"proxy": {}}})


def test_proxy_absent_by_default():
    cfg = Config()
    assert cfg.defaults.proxy is None


def test_default_cwd_accepted_when_inside_allowlist(tmp_path: Path):
    inside = tmp_path / "allowed"
    inside.mkdir()
    sub = inside / "sub"
    sub.mkdir()
    cfg = Config.model_validate(
        {
            "defaults": {
                "default_cwd": str(sub),
                "cwd_allowlist": [str(inside)],
            }
        }
    )
    assert cfg.defaults.default_cwd == str(sub)
