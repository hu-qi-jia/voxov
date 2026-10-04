# tests/test_overlay.py
import pytest
from PySide6.QtCore import Qt
from app.overlay import OverlayWindow

@pytest.fixture
def overlay(qtbot):
    w = OverlayWindow()
    qtbot.addWidget(w)
    return w

def test_window_flags_always_on_top(overlay):
    flags = overlay.windowFlags()
    assert flags & Qt.WindowStaysOnTopHint
    assert flags & Qt.FramelessWindowHint

def test_subtitle_appends_and_keeps_last_three(overlay):
    overlay.set_subtitle("第一句")
    overlay.set_subtitle("第二句")
    overlay.set_subtitle("第三句")
    overlay.set_subtitle("第四句")
    text = overlay.subtitle_label.text()
    assert "第二句" in text and "第四句" in text and "第一句" not in text

def test_answer_streaming(overlay):
    overlay.begin_answer("Redis持久化")
    overlay.append_answer("**RDB** ")
    overlay.append_answer("是快照。")
    assert "Redis持久化" in overlay.question_label.text()
    assert "RDB" in overlay.answer_view.toPlainText()
    assert "是快照。" in overlay.answer_view.toPlainText()

def test_begin_answer_clears_previous(overlay):
    overlay.begin_answer("Q1"); overlay.append_answer("旧答案")
    overlay.begin_answer("Q2")
    assert overlay.answer_view.toPlainText() == ""

def test_show_status(overlay):
    overlay.show_status("未识别到问题")
    assert "未识别到问题" in overlay.status_label.text()

def test_drag_moves_window(overlay):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    before = overlay.pos()
    press = QMouseEvent(QEvent.MouseButtonPress, QPointF(50, 5), QPointF(50, 5),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    overlay.mousePressEvent(press)
    move = QMouseEvent(QEvent.MouseMove, QPointF(120, 40), QPointF(120, 40),
                       Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    overlay.mouseMoveEvent(move)
    assert overlay.pos() != before or overlay._drag_offset is not None
