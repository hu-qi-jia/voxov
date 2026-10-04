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

# --- 审查修复轮 ---
def test_answer_renders_markdown_not_literal_asterisks(overlay):
    # 审查 I9：LLM 输出 **加粗** 不得以字面星号展示（"可直接照读"承诺）
    overlay.begin_answer("Q")
    overlay.append_answer("**RDB** 是快照，")
    overlay.append_answer("**AOF** 是日志。")
    plain = overlay.answer_view.toPlainText()
    assert "**" not in plain
    assert "RDB 是快照" in plain

def test_adjust_opacity_clamped(overlay):
    # 审查 I11：spec §2 可调透明度，范围夹取
    overlay.adjust_opacity(0.5)
    assert overlay.windowOpacity() == 1.0
    overlay.adjust_opacity(-5.0)
    # Windows 平台层把窗口不透明度量化为 8bit（0.3 → 76/255），容差放宽到一级量化
    assert abs(overlay.windowOpacity() - 0.3) <= 1 / 255

def test_ctrl_wheel_adjusts_opacity(overlay):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    before = overlay.windowOpacity()
    up = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
                     Qt.NoButton, Qt.ControlModifier, Qt.ScrollUpdate, False)
    overlay.wheelEvent(up)
    assert overlay.windowOpacity() > before
    plain_ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
                           Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
    mid = overlay.windowOpacity()
    overlay.wheelEvent(plain_ev)
    assert overlay.windowOpacity() == mid
