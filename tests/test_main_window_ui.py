# tests/test_main_window_ui.py —— 主窗口重构：左导航（知识库置顶）+ 右侧页面 + 字幕/问答双写
import pytest

from app.main_window import MainWindow


class _Rag:
    def __init__(self):
        from core.session import SessionBuffer, SessionRecorder
        self.buffer = SessionBuffer()
        self.recorder = SessionRecorder()
    def trigger(self):
        yield "a"


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


# --- 导航结构：左栏三页，知识库置顶 ---
def test_nav_buttons_exist_kb_first(win):
    w, _ = win
    for name in ("nav_kb", "nav_listen", "nav_rehearse"):
        assert getattr(w, name) is not None
    side_order = [w.side_layout.itemAt(i).widget() for i in range(w.side_layout.count())]
    widgets = [x for x in side_order if x is not None]
    texts = [x.text() for x in widgets if hasattr(x, "text")]
    assert texts.index("知识库") < texts.index("监听") < texts.index("彩排")


def test_nav_click_switches_pages(win):
    w, _ = win
    w.nav_listen.click()
    assert w.stack.currentWidget() is w.page_listen
    w.nav_kb.click()
    assert w.stack.currentWidget() is w.page_kb
    w.nav_rehearse.click()
    assert w.stack.currentWidget() is w.page_rehearse


def test_listen_page_holds_start_button_and_streams(win):
    w, _ = win
    assert w.page_listen is not None
    assert w.start_btn.parent() is w.page_listen or w.start_btn in w.page_listen.findChildren(type(w.start_btn))


# --- 字幕/问答双写：主窗口记录全量，悬浮窗只留最近 3 条 ---
def test_subtitle_dual_write_full_history_in_main(win):
    w, _ = win
    for t in ("第一句", "第二句", "第三句", "第四句"):
        w.subtitle_sig.emit(t)
    main_text = w.subtitle_view.toPlainText()
    assert "第一句" in main_text and "第四句" in main_text      # 主窗口全量保留
    assert "第一句" not in w.overlay.subtitle_label.text()       # 悬浮窗只留 3 条


def test_question_and_answer_dual_write(win):
    w, _ = win
    w._on_question("Redis 持久化")
    w._on_chunk("**RDB** 是快照。")
    main_md = w.answer_view.toPlainText()
    assert "Redis 持久化" in main_md
    assert "RDB" in main_md and "**" not in main_md              # markdown 渲染
    assert "Redis 持久化" in w.overlay.question_label.text()


def test_new_question_starts_new_answer_block(win):
    w, _ = win
    w._on_question("Q1")
    w._on_chunk("答案一")
    w._on_question("Q2")
    w._on_chunk("答案二")
    md = w.answer_view.toPlainText()
    assert "Q1" in md and "Q2" in md and "答案一" in md and "答案二" in md


# --- 左栏底部：模型状态灯 + 设置/下载模型入口 ---
def test_sidebar_bottom_controls(win):
    w, _ = win
    assert w.model_status_label.parent() is not w.statusBar()
    assert hasattr(w, "settings_btn") and hasattr(w, "wizard_btn")
