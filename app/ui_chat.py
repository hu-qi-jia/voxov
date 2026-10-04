# app/ui_chat.py —— 监听页：对话流（面试官气泡 + 回答气泡），qfluentwidgets 组件。
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout,
                               QWidget, QSizePolicy)

from qfluentwidgets import (FluentIcon as FIF, ScrollArea, PushButton,
                            SwitchButton, SubtitleLabel, StrongBodyLabel,
                            CaptionLabel, CardWidget, BodyLabel)


class Bubble(CardWidget):
    """对话气泡基类：垂直排列的卡片。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(14, 10, 14, 12)
        self._lay.setSpacing(4)


class InterviewerBubble(Bubble):
    """面试官：左对齐浅灰卡片。"""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setMaximumWidth(640)
        tag = CaptionLabel("面试官", self)
        tag.setStyleSheet("color: #8e8e93;")
        self._lay.addWidget(tag)
        body = BodyLabel(text, self)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._lay.addWidget(body)


class AnswerBubble(Bubble):
    """回答：标题（问题）+ markdown 流式正文。"""

    def __init__(self, question: str, parent=None):
        super().__init__(parent)
        self.setMaximumWidth(720)
        tag = StrongBodyLabel(question, self)
        tag.setWordWrap(True)
        self._lay.addWidget(tag)
        self.view = QTextBrowser(self)
        self.view.setObjectName("answer")
        self.view.setOpenExternalLinks(False)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.view.setMinimumHeight(40)
        self._lay.addWidget(self.view)
        self.note = CaptionLabel("", self)
        self.note.setStyleSheet("color: #b54708;")
        self._lay.addWidget(self.note)
        self._buf = ""

    def append(self, delta: str) -> None:
        if not delta:
            return
        self._buf += delta
        self.view.setMarkdown(self._buf)


class ChatPage(QWidget):
    """监听页：头部操作 + 对话流。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chat-page")
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(12)
        self.start_btn = PushButton(FIF.MICROPHONE, "开始监听")
        self.start_btn.setProperty("accent", True)
        head.addWidget(self.start_btn)
        self.auto_switch = SwitchButton("自动作答", self)
        self.auto_switch.setChecked(True)
        head.addWidget(self.auto_switch)
        self.model_status_label = CaptionLabel("未下载", self)
        self.model_status_label.setObjectName("model_status")
        head.addWidget(self.model_status_label)
        head.addStretch(1)
        root.addLayout(head)

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.enableTransparentBackground()
        self.feed = QWidget()
        self.feed.setStyleSheet("background: #ffffff;")
        self.feed_lay = QVBoxLayout(self.feed)
        self.feed_lay.setContentsMargins(0, 0, 16, 8)
        self.feed_lay.setSpacing(10)
        self.feed_lay.addStretch(1)
        self.scroll.setWidget(self.feed)
        root.addWidget(self.scroll, 1)

    # ---- 对话流 API ----
    def add_interviewer(self, text: str) -> InterviewerBubble:
        b = InterviewerBubble(text)
        self._insert(b)
        return b

    def begin_answer(self, question: str) -> AnswerBubble:
        b = AnswerBubble(question)
        self._insert(b)
        return b

    def _insert(self, w: QWidget) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(w, 0, Qt.AlignLeft)
        self.feed_lay.insertWidget(self.feed_lay.count() - 1, w)
        sb = self.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._tail_rows = getattr(self, "_tail_rows", []) + [row]

    def scroll_to_bottom(self) -> None:
        sb = self.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
