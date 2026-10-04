# tests/test_downloader.py
from pathlib import Path
from core import downloader

def test_models_ready_false_then_true(tmp_path, monkeypatch):
    assert downloader.models_ready(tmp_path) is False
    for sub in ("SenseVoiceSmall", "fsmn-vad", "ct-punc", "bge-small-zh-v1.5"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    assert downloader.models_ready(tmp_path) is True

def test_ensure_models_downloads_all(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(downloader, "_download_modelscope",
                        lambda repo, dest, log: calls.append(("ms", repo, dest)) or dest.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(downloader, "_download_hf",
                        lambda repo, dest, log: calls.append(("hf", repo, dest)) or dest.mkdir(parents=True, exist_ok=True))
    logs = []
    downloader.ensure_models(tmp_path, logs.append)
    repos = {c[1] for c in calls}
    assert any("SenseVoiceSmall" in r for r in repos)
    assert any("bge-small-zh-v1.5" in r for r in repos)
    assert any("开始下载" in l for l in logs)

def test_ensure_models_skips_existing(tmp_path, monkeypatch):
    (tmp_path / "SenseVoiceSmall").mkdir()
    n = []
    monkeypatch.setattr(downloader, "_download_modelscope",
                        lambda repo, dest, log: n.append(1) or dest.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(downloader, "_download_hf",
                        lambda repo, dest, log: n.append(1) or dest.mkdir(parents=True, exist_ok=True))
    downloader.ensure_models(tmp_path, lambda *_: None)
    assert len(n) == 3  # 只下载缺失的 3 个
