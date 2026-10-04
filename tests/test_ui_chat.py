# tests/test_ui_chat.py —— 监听页终端转写流
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QTextBrowser

from app.ui_chat import AnswerTurn, ChatPage, InterviewerTurn


@pytest.fixture
def page(qtbot):
    p = ChatPage()
    qtbot.addWidget(p)
    return p


def test_header_has_only_button_and_checkbox(page):
    assert page.start_btn.text().strip() == "开始监听"
    assert page.auto_switch.text() == "自动作答"
    assert page.auto_switch.isChecked()


def test_interviewer_turn_has_prefix(page):
    t = page.add_interviewer("请讲讲 Redis 持久化")
    assert isinstance(t, InterviewerTurn)
    lb = t.layout().itemAt(0).widget()
    assert lb.text().startswith("›")


def test_answer_streams_and_mark_interrupted(page):
    b = page.begin_answer()
    b.append("**RDB** 是快照，")
    b.append("**AOF** 是日志。")
    assert "RDB" in b.view.toPlainText() and "**" not in b.view.toPlainText()
    b.mark_interrupted()
    assert "生成中断" in b.note.text()


def test_answer_view_frameless_and_no_scrollbars(page):
    b = page.begin_answer()
    assert b.view.frameShape() == QFrame.NoFrame
    assert b.view.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert b.view.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff


def test_answer_bold_renders_accent(page):
    b = page.begin_answer()
    b.append("**重点**内容")
    assert "#5af78e" in b.view.document().defaultStyleSheet().lower()


def test_turns_are_separated_by_hline(page):
    page.add_interviewer("第一句")
    page.begin_answer().append("答")
    page.add_interviewer("第二句")
    from PySide6.QtWidgets import QFrame
    frames = page.feed.findChildren(QFrame)
    assert any(f.frameShape() == QFrame.HLine or f.objectName() == "hline" for f in frames)
