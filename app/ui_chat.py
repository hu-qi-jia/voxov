# app/ui_chat.py —— 监听页：终端转写流（无气泡容器，1px 分割线）。
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QTextBrowser, QVBoxLayout, QWidget)

from app.icons import icon

ACCENT = "#5af78e"


class _AutoHeightBrowser(QTextBrowser):
    """无边框、无滚动条的流式正文；高度按当前视口宽实排。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setOpenExternalLinks(False)

    def refit(self) -> None:
        doc = self.document()
        doc.setTextWidth(self.viewport().width() or doc.textWidth())
        self.setFixedHeight(max(28, int(doc.size().height()) + 10))

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        if ev.oldSize().width() != self.width():
            self.refit()


def _hline() -> QFrame:
    f = QFrame()
    f.setObjectName("hline")
    f.setFrameShape(QFrame.HLine)
    f.setFixedHeight(1)
    return f


class InterviewerTurn(QWidget):
    """面试官话轮：fg_dim 文本 + “›” 前缀。"""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lb = QLabel("› " + text, self)
        lb.setObjectName("turn_q")
        lb.setWordWrap(True)
        lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(lb)


class AnswerTurn(QWidget):
    """回答话轮：markdown 正文（加粗渲染为 accent）+ 弱色标注行。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 6, 0, 10)
        col.setSpacing(6)
        self.view = _AutoHeightBrowser(self)
        self.view.setObjectName("answer")
        self.view.document().setDefaultStyleSheet(f"strong {{ color: {ACCENT}; }}")
        self.view.setPlaceholderText("正在生成…")
        self.view.setFixedHeight(36)
        col.addWidget(self.view)
        self.note = QLabel("", self)
        self.note.setObjectName("turn_note")
        self.note.setWordWrap(True)
        col.addWidget(self.note)
        self._buf = ""

    def append(self, delta: str) -> None:
        if not delta:
            return
        self._buf += delta
        self.view.setMarkdown(self._buf)
        self._recolor_bold()
        self.view.refit()
        self._parent_scroll_to_bottom()

    def _recolor_bold(self) -> None:
        """setMarkdown 不经过 defaultStyleSheet：直接遍历片段把加粗涂成 accent。"""
        from PySide6.QtGui import QBrush, QColor, QTextCursor
        doc = self.view.document()
        block = doc.firstBlock()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid() and frag.charFormat().fontWeight() > 400:
                    c = QTextCursor(doc)
                    c.setPosition(frag.position())
                    c.setPosition(frag.position() + frag.length(), QTextCursor.KeepAnchor)
                    fmt = frag.charFormat()
                    fmt.setForeground(QBrush(QColor(ACCENT)))
                    c.mergeCharFormat(fmt)
                it += 1
            block = block.next()

    def mark_interrupted(self) -> None:
        if self._buf:
            self.note.setText("生成中断——以上为已收到的部分，可稍后重试")

    def fail(self, msg: str) -> None:
        """失败可见化：有内容标注截断；空内容换掉「正在生成…」占位并说明原因。"""
        if self._buf:
            self.mark_interrupted()
        else:
            self.view.setPlaceholderText("生成失败——可重新提问")
            self.note.setText(msg)

    def _parent_scroll_to_bottom(self) -> None:
        p = self.parent()
        while p is not None:
            if hasattr(p, "scroll_to_bottom"):
                p.scroll_to_bottom()
                return
            p = p.parent()


class ChatPage(QWidget):
    """监听页：头行（开始监听 + 自动作答）+ 转写流。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chat-page")
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 12)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(18)
        self.start_btn = QPushButton(" 开始监听")
        self.start_btn.setIcon(icon("mic", ACCENT))
        self.start_btn.setProperty("accent", True)
        head.addWidget(self.start_btn)
        self.auto_switch = QCheckBox("自动作答")
        self.auto_switch.setChecked(True)
        head.addWidget(self.auto_switch)
        head.addStretch(1)
        root.addLayout(head)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.feed = QWidget()
        self.feed.setObjectName("feed")
        self.feed_lay = QVBoxLayout(self.feed)
        self.feed_lay.setContentsMargins(0, 0, 16, 8)
        self.feed_lay.setSpacing(0)
        self.feed_lay.addStretch(1)
        self.scroll.setWidget(self.feed)
        root.addWidget(self.scroll, 1)

    def add_interviewer(self, text: str) -> InterviewerTurn:
        t = InterviewerTurn(text)
        self.feed_lay.insertWidget(self.feed_lay.count() - 1, t)
        self.feed_lay.insertWidget(self.feed_lay.count() - 1, _hline())
        self.scroll_to_bottom()
        return t

    def begin_answer(self) -> AnswerTurn:
        b = AnswerTurn()
        self.feed_lay.insertWidget(self.feed_lay.count() - 1, b)
        self.scroll_to_bottom()
        return b

    def scroll_to_bottom(self) -> None:
        sb = self.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
