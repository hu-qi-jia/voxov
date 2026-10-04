# tests/test_main_window.py —— voxov 壳：tab 导航、状态行、自动作答路由、知识库表
import pytest
from PySide6.QtWidgets import QTableView

from app.main_window import MainWindow


class FakeRag:
    def __init__(self):
        from core.session import SessionBuffer
        self.buffer = SessionBuffer()
        self.triggered = 0
        self.last_notice = ""
    def trigger(self):
        self.triggered += 1
        yield "**答**案"


class FakeKb:
    def __init__(self):
        self.files = [("a.md", 3), ("b.md", 5)]
    def list_files(self):
        return list(self.files)
    def delete_file(self, name):
        self.files = [(f, n) for f, n in self.files if f != name]
        return 1


@pytest.fixture
def win(qtbot, tmp_path, monkeypatch):
    import core.config as cc
    monkeypatch.setattr(cc, "app_root", lambda: tmp_path)
    from core.config import default_config
    rag, kb = FakeRag(), FakeKb()
    w = MainWindow(default_config(), kb_factory=lambda: kb, rag_factory=lambda: rag)
    qtbot.addWidget(w)
    return w, rag


def test_window_title_and_nav_tabs(win):
    w, _ = win
    assert w.windowTitle() == "voxov"
    for key in ("listen", "kb", "settings"):
        assert key in w._pages


def test_switch_page_moves_stack(win):
    w, _ = win
    w.switch_page("settings")
    assert w._stack.currentWidget() is w.settings_page
    w.switch_page("listen")
    assert w._stack.currentWidget() is w.chat_page


def test_kb_table_lists_files_and_row_selection(win):
    w, _ = win
    model = w.kb_table.model()
    assert model.rowCount() == 2
    assert w.kb_table.selectionBehavior() == QTableView.SelectRows
    assert not w.kb_table.editTriggers()


def test_kb_empty_state_hint(win):
    w, _ = win
    w.show(); w.switch_page("kb"); w._reload_kb()
    kb = w._kb_factory()
    kb.files.clear()
    w._reload_kb()
    assert not w.kb_empty.isHidden()


def test_delete_selected_file(win):
    w, _ = win
    w.kb_table.selectRow(0)
    w._delete_selected()
    assert w.kb_table.model().rowCount() == 1


def test_set_status_message_and_auto_clear(win, qtbot):
    w, _ = win
    w.set_status("设置已保存", "ok")
    assert "设置已保存" in w.status_msg.text()
    w._status_timer.start(50)
    qtbot.wait(120)
    assert w.status_msg.text() == ""


def test_hotkey_triggers_generate(win, qtbot):
    w, rag = win
    w._on_hotkey()
    qtbot.waitUntil(lambda: rag.triggered == 1, timeout=3000)
    assert w._chat_answer is not None


def test_hotkey_flushes_pending_pipeline(win):
    w, rag = win
    flushed = []
    class FakePipeline:
        def flush_pending(self):
            flushed.append(1)
    w._pipeline = FakePipeline()
    w._on_hotkey()
    assert flushed == [1]


def test_subtitle_question_auto_triggers(win, monkeypatch):
    w, _ = win
    fired = []
    monkeypatch.setattr(w, "_on_hotkey", lambda: fired.append(1))
    w.subtitle_sig.emit("说说 MySQL 索引")
    assert fired == [1]


def test_subtitle_statement_auto_triggers_when_auto_on(win, monkeypatch):
    w, _ = win
    fired = []
    monkeypatch.setattr(w, "_on_hotkey", lambda: fired.append(1))
    w.subtitle_sig.emit("我们团队主要做 ToB 业务")
    assert fired == [1]                     # 陈述也是实质话轮（路由 spec）


def test_subtitle_chatter_never_triggers(win, monkeypatch):
    w, _ = win
    fired = []
    monkeypatch.setattr(w, "_on_hotkey", lambda: fired.append(1))
    w.subtitle_sig.emit("嗯好的")
    assert fired == []
    w.chat_page.auto_switch.setChecked(False)
    w.subtitle_sig.emit("说说 MySQL 索引")
    assert fired == []


def test_notice_passthrough_to_answer_note(win, qtbot):
    w, rag = win
    rag.last_notice = "开放题 · 未用资料"
    w._on_hotkey()
    qtbot.waitUntil(lambda: w._chat_answer is not None
                    and "开放题" in w._chat_answer.note.text(), timeout=3000)


def test_hide_hotkey_toggles_window(win):
    w, _ = win
    w.show()
    w._on_hide()
    assert not w.isVisible()
    w._on_hide()
    assert w.isVisible()


def test_no_rehearsal_leftovers(win):
    w, _ = win
    assert not hasattr(w, "start_rehearsal")
    assert not hasattr(w, "_rehearsal_rag_factory")
    assert not hasattr(w, "_info")


def test_apply_settings_rebuilds_llm(win, monkeypatch):
    from core.generator import LLMClient
    import app.hotkey as hk
    made = []
    monkeypatch.setattr("core.generator.LLMClient",
                        lambda *a, **k: made.append(a) or object())

    class _Sig:
        def connect(self, *a): pass

    class _NB:                       # 不注册真实全局热键钩（C4）
        def __init__(self):
            self.pressed = _Sig()
            self.hidden = _Sig()
    monkeypatch.setattr(hk, "HotkeyBridge", lambda *a, **k: _NB())
    w, rag = win
    w._rag = rag
    w._apply_settings()
    assert made[0][0] == w.cfg.llm_base_url and made[0][2] == w.cfg.llm_model
    assert len(made) == 1 and rag.llm is not None


def test_rebind_hotkeys_replaces_bridge(win, monkeypatch):
    import app.hotkey as hk
    made = []

    class _Sig:
        def connect(self, *a): pass

    class _FB:
        def __init__(self, a, b):
            if a == "bad!!":           # 旧 I3c 锁定的库契约：非法组合注册即抛
                raise ValueError("bad combo")
            made.append((a, b))
            self.pressed = _Sig()      # rebind_hotkeys 会连接这两个信号
            self.hidden = _Sig()
        def stop(self): made.append("stop")
    monkeypatch.setattr(hk, "HotkeyBridge", _FB)
    w, _ = win
    w.bridge = None
    w.cfg.hotkey = "ctrl+alt+q"
    w.rebind_hotkeys()
    assert ("ctrl+alt+q", "ctrl+alt+h") in made and w.bridge is not None
    w.cfg.hotkey = "bad!!"
    w.rebind_hotkeys()
    assert made[-1] == ("ctrl+alt+space", "ctrl+alt+h")   # 回退默认不崩
    assert "stop" in made                                  # 旧桥被停
