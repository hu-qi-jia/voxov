# tests/test_settings_page.py —— 设置页：保存/热键校验/下载状态
def _page(qtbot, tmp_path, monkeypatch):
    import core.config as cc
    monkeypatch.setattr(cc, "app_root", lambda: tmp_path)
    from core.config import default_config
    from app.settings_page import SettingsPage
    cfg = default_config()
    statuses = []
    p = SettingsPage(cfg, set_status=lambda t, kind="info": statuses.append((t, kind)))
    qtbot.addWidget(p)
    return p, cfg, statuses

def test_save_writes_config(qtbot, tmp_path, monkeypatch):
    p, cfg, _ = _page(qtbot, tmp_path, monkeypatch)
    p.base_url_edit.setText("https://api.x.com/v1")
    p.model_edit.setText("m1")
    assert p.save() is True
    from core.config import load_config
    cfg2 = load_config(cfg.data_dir)
    assert cfg2.llm_base_url == "https://api.x.com/v1" and cfg2.llm_model == "m1"

def test_save_rejects_invalid_hotkey(qtbot, tmp_path, monkeypatch):
    p, cfg, statuses = _page(qtbot, tmp_path, monkeypatch)
    before = cfg.hotkey
    p.hotkey_edit.setText("bad!!")
    assert p.save() is False
    assert cfg.hotkey == before
    assert any("热键无效" in t for t, _ in statuses)

def test_device_combo_has_default(qtbot, tmp_path, monkeypatch):
    p, _, _ = _page(qtbot, tmp_path, monkeypatch)
    assert p.device_combo.currentData() == ""

def test_refresh_models_state_ready(qtbot, tmp_path, monkeypatch):
    import core.downloader as dl
    p, cfg, _ = _page(qtbot, tmp_path, monkeypatch)
    for rel in dl.REQUIRED:
        f = cfg.models_dir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    p.refresh_models_state()
    assert "已就绪" in p.model_state.text()

def test_download_request_signal(qtbot, tmp_path, monkeypatch):
    p, _, _ = _page(qtbot, tmp_path, monkeypatch)
    got = []
    p.download_requested.connect(lambda: got.append(1))
    p.dl_btn.click()
    assert got == [1]

def test_dl_progress_and_ok_flow(qtbot, tmp_path, monkeypatch):
    import core.downloader as dl
    p, cfg, _ = _page(qtbot, tmp_path, monkeypatch)
    for rel in dl.REQUIRED:  # app_root 已重定向，须在沙箱 models_dir 预置齐全文件
        f = cfg.models_dir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    p.on_dl_started()
    assert not p.progress.isHidden()
    assert not p.dl_btn.isEnabled()
    p.on_dl_progress(0.62)
    assert p.progress.value() == 62
    p.on_dl_ok()
    assert "已就绪" in p.model_state.text()
    assert p.progress.isHidden()

def test_refresh_preserves_downloading_state(qtbot, tmp_path, monkeypatch):
    p, _, _ = _page(qtbot, tmp_path, monkeypatch)
    p.on_dl_started()
    p.refresh_models_state(downloading=True)
    assert not p.dl_btn.isEnabled()
    assert not p.progress.isHidden()


def test_shortcut_button_reports_created(qtbot, tmp_path, monkeypatch):
    p, _, statuses = _page(qtbot, tmp_path, monkeypatch)
    called = []
    import app.shortcuts as sc
    monkeypatch.setattr(sc, "create_desktop_shortcut", lambda: called.append(1) or "D:/voxov.lnk")
    p.shortcut_btn.click()
    assert called == [1]
    assert any("已创建" in t for t, _ in statuses)


def test_shortcut_button_reports_failure(qtbot, tmp_path, monkeypatch):
    p, _, statuses = _page(qtbot, tmp_path, monkeypatch)
    import app.shortcuts as sc
    def boom():
        raise RuntimeError("boom")
    monkeypatch.setattr(sc, "create_desktop_shortcut", boom)
    p.shortcut_btn.click()
    assert any("失败" in t for t, _ in statuses)
