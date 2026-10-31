"""Tests for config: env vars > keyring > file, KEYS_DIR override,
importing config does not crash when keys are missing."""
import importlib
import sys
from pathlib import Path

import pytest

import config as cfg


def test_optional_key_reads_from_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "KEYS_DIR", tmp_path)
    (tmp_path / "test_key.txt").write_text("secret123\n", encoding="utf-8")
    monkeypatch.delenv("TEST_KEY_API_KEY", raising=False)
    assert cfg._optional_key("test_key.txt") == "secret123"


def test_optional_key_env_var_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "KEYS_DIR", tmp_path)
    (tmp_path / "test_key.txt").write_text("fromfile\n", encoding="utf-8")
    monkeypatch.setenv("TEST_KEY_API_KEY", "fromenv")
    assert cfg._optional_key("test_key.txt") == "fromenv"


def test_optional_key_with_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "KEYS_DIR", tmp_path)
    (tmp_path / "test_key.txt").write_text("api_key: secret_with_prefix\n", encoding="utf-8")
    monkeypatch.delenv("TEST_KEY_API_KEY", raising=False)
    assert cfg._optional_key("test_key.txt", prefix="api_key") == "secret_with_prefix"


def test_optional_key_returns_empty_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "KEYS_DIR", tmp_path)
    assert cfg._optional_key("nonexistent.txt") == ""


def test_optional_key_first_line_wins(tmp_path, monkeypatch):
    """First non-empty line is the key (current behaviour). Comments are
    not skipped — users should keep key files to a single value."""
    monkeypatch.setattr(cfg, "KEYS_DIR", tmp_path)
    (tmp_path / "test_key.txt").write_text("actual_key_value\n", encoding="utf-8")
    monkeypatch.delenv("TEST_KEY_API_KEY", raising=False)
    assert cfg._optional_key("test_key.txt") == "actual_key_value"


def test_keys_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("KEYS_DIR", str(tmp_path))
    (tmp_path / "openalex_api.txt").write_text("openalex_test\n", encoding="utf-8")
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    importlib.reload(cfg)
    assert cfg.KEYS_DIR == Path(tmp_path)
    assert cfg.OPENALEX_API_KEY == "openalex_test"


def test_import_config_without_deepseek_key(monkeypatch, tmp_path):
    """Importing config with no DEEPSEEK key file must NOT raise (P1 fix)."""
    monkeypatch.setenv("KEYS_DIR", str(tmp_path))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    importlib.reload(cfg)
    assert cfg.DEEPSEEK_API_KEY == "", "missing deepseek key should be empty, not raise"


def test_optional_key_keyring_wins_even_with_prefix(tmp_path, monkeypatch):
    """Minimax (prefix='api_key') must still consult keyring — regression for
    the bug where a prefix skipped the keyring lookup and lost the stored key."""
    import keyring
    monkeypatch.setattr(cfg, "KEYS_DIR", tmp_path)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.setattr(keyring, "get_password", lambda service, account: "from_keyring")
    assert cfg._optional_key("minimax.txt", prefix="api_key") == "from_keyring"
