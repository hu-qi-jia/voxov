# tests/test_main_window_ui.py —— Fluent 壳 + 对话流监听页（qfluentwidgets 重构后）
import pytest

from app.main_window import MainWindow
from app.ui_chat import AnswerBubble, InterviewerBubble


class _Rag:
    def __init__(self):
        from core.session import SessionBuffer, SessionRecorder
        self.buffer = SessionBuffer()
        self.recorder = SessionRecorder()

    def trigger(self):
        yield "答"


class _Kb:
    def list_files(self):
        return []


@pytest.fixture
def win(qtbot, tmp_path, monkeypatch):
    import core.config as cc
    monkeypatch.setattr(cc, "app_root", lambda: tmp_path)
    from core.config import default_config
    rag = _Rag()
    w = MainWindow(default_config(), kb_factory=lambda: _Kb(), rag_factory=lambda: rag)
    qtbot.addWidget(w)
    qtbot.addWidget(w.overlay)
    return w, rag


def test_fluent_pages_exist(win):
    w, _ = win
    assert w.chat_page is not None and w.page_kb is not None and w.page_rehearse is not None
    assert w.start_btn.text() == "开始监听"
    assert w.model_status_label is not None
    assert hasattr(w.chat_page, "auto_switch")


def test_chat_bubbles_flow(win):
    w, _ = win
    b1 = w.chat_page.add_interviewer("请讲讲 Redis 持久化")
    assert isinstance(b1, InterviewerBubble)
    b2 = w.chat_page.begin_answer("Redis 持久化")
    assert isinstance(b2, AnswerBubble)
    b2.append("**RDB** 是快照，")
    b2.append("**AOF** 是日志。")
    assert "RDB" in b2.view.toPlainText() and "**" not in b2.view.toPlainText()


# --- 字幕双写：对话流新增气泡 + 悬浮窗只留最近 3 条 ---
def test_subtitle_dual_write(win):
    w, _ = win
    for t in ("第一句", "第二句", "第三句", "第四句"):
        w.subtitle_sig.emit(t)
    assert "第一句" not in w.overlay.subtitle_label.text()   # 悬浮窗只留 3 条
    from qfluentwidgets import BodyLabel
    labels = [lb.text() for lb in w.chat_page.feed.findChildren(BodyLabel)]
    assert "第一句" in labels and "第四句" in labels          # 主窗全量留档


# --- 问答流：块流入当前回答气泡 + 悬浮窗同步 ---
def test_answer_streams_into_chat_bubble(win):
    w, _ = win
    w._last_utterance = "讲讲 Redis 持久化"
    w._on_hotkey()
    assert w._chat_answer is not None
    w._on_question("Redis 持久化")
    w._on_chunk("**RDB** 是快照。")
    assert "RDB" in w._chat_answer.view.toPlainText()
    assert "Redis 持久化" in w.overlay.question_label.text()


# --- 自动作答：像问题才触发，开关可关 ---
def test_auto_answer_triggers_on_question(win, monkeypatch):
    w, _ = win
    fired = []
    monkeypatch.setattr(w, "_on_hotkey", lambda: fired.append(1))
    w.subtitle_sig.emit("说说 MySQL 索引")
    assert fired == [1]


def test_auto_answer_skips_smalltalk_and_can_be_disabled(win, monkeypatch):
    w, _ = win
    fired = []
    monkeypatch.setattr(w, "_on_hotkey", lambda: fired.append(1))
    w.subtitle_sig.emit("好的")
    assert fired == []
    w.chat_page.auto_switch.setChecked(False)
    w.subtitle_sig.emit("说说 MySQL 索引")
    assert fired == []


# --- 悬浮窗必须可关闭（✕ / Esc） ---
def test_overlay_close_button_and_esc(win):
    w, _ = win
    w.overlay.show()
    assert w.overlay.isVisible()
    w.overlay.close_btn.click()
    assert not w.overlay.isVisible()
    w.overlay.show()
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    w.overlay.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert not w.overlay.isVisible()


# --- 音频异常：管线复位 + InfoBar 浮出 ---
def test_audio_error_resets_pipeline(win, monkeypatch):
    w, _ = win
    infos = []
    monkeypatch.setattr(w, "_info", lambda *a, **k: infos.append(a))
    monkeypatch.setattr(w, "_set_listen_btn", lambda *a, **k: None)

    class _P:
        def stop(self):
            pass

    w._pipeline = _P()
    w.audio_error_sig.emit("设备被占用")
    assert w._pipeline is None
    assert any(a and a[0] == "error" and "设备被占用" in a[2] for a in infos)
