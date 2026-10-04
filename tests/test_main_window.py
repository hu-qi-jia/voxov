# tests/test_main_window.py
import pytest
from PySide6.QtWidgets import QApplication
from app.main_window import MainWindow

class FakeRag:
    def __init__(self):
        self.buffer = _FakeBuffer()
        self.triggered = 0
    def trigger(self):
        self.triggered += 1
        yield "**答**案"

class _FakeBuffer:
    entries = []

class FakeKb:
    def __init__(self):
        self.files = [("a.md", 3), ("b.md", 5)]
    def list_files(self):
        return list(self.files)
    def delete_file(self, name):
        self.files = [(f, n) for f, n in self.files if f != name]
        return 1

@pytest.fixture
def win(qtbot, tmp_path):
    from core.config import default_config
    import core.config as cc
    cc.app_root = lambda: tmp_path  # 重定向根目录
    cfg = default_config()
    rag, kb = FakeRag(), FakeKb()
    w = MainWindow(cfg, kb_factory=lambda: kb, rag_factory=lambda: rag)
    qtbot.addWidget(w)
    return w, rag

def test_kb_table_lists_files(win):
    w, _ = win
    model = w.kb_table.model()
    assert model.rowCount() == 2
    assert model.item(0, 0).text() in ("a.md", "b.md")

def test_hotkey_signal_triggers_generate(win, qtbot):
    w, rag = win
    w._on_hotkey()
    qtbot.waitUntil(lambda: rag.triggered == 1, timeout=3000)

def test_generate_worker_streams_to_chat_bubble(win, qtbot):
    w, rag = win
    w._on_hotkey()
    qtbot.waitUntil(lambda: w._chat_answer is not None
                    and "答" in w._chat_answer.view.toPlainText(), timeout=3000)

def test_delete_selected_file(win, qtbot):
    w, _ = win
    w.kb_table.selectRow(0)
    w._delete_selected()
    assert w.kb_table.model().rowCount() == 1

def test_settings_dialog_roundtrip(win, qtbot, tmp_path):
    from app.settings_dialog import SettingsDialog
    w, _ = win
    dlg = SettingsDialog(w.cfg, parent=w)
    dlg.base_url_edit.setText("https://api.x.com/v1")
    dlg.model_edit.setText("m1")
    dlg.hide_hotkey_edit.setText("ctrl+alt+h")
    dlg._save()
    from core.config import load_config
    cfg2 = load_config(w.cfg.data_dir)
    assert cfg2.llm_base_url == "https://api.x.com/v1" and cfg2.llm_model == "m1"

def test_hide_hotkey_toggles_main_window(win, qtbot):
    w, _ = win
    w.show()
    w._on_hide()
    assert not w.isVisible()
    w._on_hide()
    assert w.isVisible()

def test_hotkey_flushes_pending_pipeline(win, qtbot):
    # spec §6.6：热键路径必须先强刷管线 pending 语音再提取问题
    w, rag = win
    flushed = []
    class FakePipeline:
        def flush_pending(self):
            flushed.append(1)
    w._pipeline = FakePipeline()
    w._on_hotkey()
    assert flushed == [1]  # 同步调用，触发前必须完成
    qtbot.waitUntil(lambda: rag.triggered == 1, timeout=3000)

def test_main_window_has_no_inline_config_controls(win, qtbot):
    # spec §6.7：主窗口不放散落配置控件，设置集中在 SettingsDialog
    w, _ = win
    assert not hasattr(w, "base_url_edit") and not hasattr(w, "_save_settings")
    assert hasattr(w, "_open_settings")
