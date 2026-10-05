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
    import time

    import core.config as cc
    monkeypatch.setattr(cc, "app_root", lambda: tmp_path)
    from core.config import default_config
    from core.session import SessionBuffer, TranscriptEntry
    rag, kb = FakeRag(), FakeKb()
    w = MainWindow(default_config(), kb_factory=lambda: kb, rag_factory=lambda: rag)
    qtbot.addWidget(w)
    w._listen_buffer = SessionBuffer()          # 预置监听缓冲：热键可提取话轮
    now = time.time()
    w._listen_buffer.add_transcript(
        TranscriptEntry(now - 6, now - 4, "介绍一下你自己"))
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


def test_subtitle_no_filtering_all_turns_trigger(win, monkeypatch):
    """用户指示：不过滤招呼语——全部话轮走知识库检索。"""
    w, _ = win
    fired = []
    monkeypatch.setattr(w, "_on_hotkey", lambda: fired.append(1))
    w.subtitle_sig.emit("嗯好的")
    assert fired == [1]
    w.chat_page.auto_switch.setChecked(False)
    w.subtitle_sig.emit("说说 MySQL 索引")
    assert fired == [1]                          # 开关关：一律不触发


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


def test_apply_settings_rebinds_and_refreshes(win, monkeypatch):
    """并行架构下 LLMClient 由工厂按当前 cfg 在每次生成时新建；
    _apply_settings 的职责收敛为重绑热键 + 刷新状态行。"""
    import app.hotkey as hk
    made = []

    class _Sig:
        def connect(self, *a): pass

    class _NB:
        errors = []
        def __init__(self, a, b):
            made.append((a, b))
            self.pressed = _Sig()
            self.hidden = _Sig()
        def stop(self): pass

    monkeypatch.setattr(hk, "HotkeyBridge", _NB)
    w, _ = win
    w.cfg.hotkey = "ctrl+alt+q"
    w._apply_settings()
    assert made == [("ctrl+alt+q", "ctrl+alt+h")]
    assert w.status_info.text()       # 已刷新


def test_parallel_hotkey_spawns_independent_workers(win):
    """连续提问并行处理：每次触发独立 rag + 独立气泡，互不丢弃。"""
    made = []

    def factory():
        r = FakeRag()
        made.append(r)
        return r

    w, _ = win
    w._rag_factory = factory
    w._on_hotkey()
    w._on_hotkey()
    assert len(made) == 2 and made[0] is not made[1]   # 独立 RagService（无共享竞态）
    assert len(w._workers) == 2
    assert w._chat_answer is not None


def test_rebind_hotkeys_replaces_bridge(win, monkeypatch):
    import app.hotkey as hk
    made = []

    class _Sig:
        def connect(self, *a): pass

    class _FB:
        errors = []
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


def test_reveal_restores_hidden_window(win):
    w, _ = win
    w.show()
    w._on_hide()
    assert not w.isVisible()
    w.reveal()
    assert w.isVisible()
    assert w._hidden is False


def test_rebind_reports_registered_status(win, monkeypatch):
    """热键注册成败必须可见（dist 里静默失效曾无从排查）。"""
    import app.hotkey as hk

    class _Sig:
        def connect(self, *a): pass

    class _FB:
        errors = []
        def __init__(self, a, b):
            self.pressed = _Sig()
            self.hidden = _Sig()
        def stop(self): pass

    class _FBPartial:
        errors = ["急隐藏 ctrl+alt+h：denied"]
        def __init__(self, a, b):
            self.pressed = _Sig()
            self.hidden = _Sig()
        def stop(self): pass

    stubs = {"ok": _FB, "partial": _FBPartial}
    monkeypatch.setattr(hk, "HotkeyBridge", stubs["ok"])
    w, _ = win
    w.rebind_hotkeys()
    assert "热键已注册" in w.status_msg.text()
    monkeypatch.setattr(hk, "HotkeyBridge", stubs["partial"])
    w.rebind_hotkeys()
    assert "部分注册失败" in w.status_msg.text()


def test_hotkey_with_no_listen_buffer_spawns_nothing(win):
    """监听没开/无转写：不建气泡、不启 worker，状态行说明原因。"""
    w, rag = win
    w._listen_buffer = None
    before = len(w._workers)
    w._on_hotkey()
    assert len(w._workers) == before
    assert w._chat_answer is None
    assert "未识别到问题" in w.status_msg.text()


def test_hotkey_uses_fresh_turn_and_passes_to_rag(win, qtbot):
    """有转写时：主线程提取话轮，经 pending_turn 直达 trigger。"""
    import time
    from core.session import TranscriptEntry
    w, rag = win
    w.show()
    from core.session import SessionBuffer
    w._listen_buffer = SessionBuffer()
    now = time.time()
    w._listen_buffer.add_transcript(TranscriptEntry(now - 6, now - 4, "介绍一下你自己"))
    w._on_hotkey()
    qtbot.waitUntil(lambda: rag.triggered == 1, timeout=3000)
    assert getattr(rag, "pending_turn", "") == "介绍一下你自己"
    assert w._chat_answer is not None
