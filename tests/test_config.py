# tests/test_config.py
from pathlib import Path
from core.config import AppConfig, default_config, load_config, save_config

def test_default_config_uses_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr("core.config.app_root", lambda: tmp_path)
    cfg = default_config()
    assert cfg.models_dir == tmp_path / "models"
    assert cfg.data_dir == tmp_path / "data"
    assert cfg.kb_path == tmp_path / "data" / "kb.db"
    assert cfg.hotkey == "ctrl+alt+space"
    assert cfg.hide_hotkey == "ctrl+alt+h"
    assert cfg.audio_device == ""
    assert cfg.llm_base_url == ""

def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("core.config.app_root", lambda: tmp_path)
    cfg = default_config()
    cfg.llm_base_url = "https://api.deepseek.com/v1"
    cfg.llm_model = "deepseek-chat"
    save_config(cfg)
    loaded = load_config(tmp_path / "data")
    assert loaded.llm_base_url == "https://api.deepseek.com/v1"
    assert loaded.llm_model == "deepseek-chat"

def test_load_missing_config_returns_default(tmp_path, monkeypatch):
    monkeypatch.setattr("core.config.app_root", lambda: tmp_path)
    cfg = load_config(tmp_path / "data")
    assert cfg.llm_api_key == ""

def test_load_partial_config_merges_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr("core.config.app_root", lambda: tmp_path)
    d = tmp_path / "data"; d.mkdir(parents=True)
    (d / "config.json").write_text('{"llm_model": "gpt-4o"}', encoding="utf-8")
    cfg = load_config(d)
    assert cfg.llm_model == "gpt-4o" and cfg.hotkey == "ctrl+alt+space"
