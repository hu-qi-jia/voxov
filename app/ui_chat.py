# app/ui_chat.py —— 监听页：对话流（VoxRecall/DSH 风格——头像+角色标签+分向气泡）。
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout,
                               QWidget)

from qfluentwidgets import (FluentIcon as FIF, ScrollArea, PushButton,
                            SwitchButton, SubtitleLabel, StrongBodyLabel,
                            CaptionLabel, BodyLabel, CardWidget)


class InterviewerBubble(QWidget):
    """面试官：右对齐，圆形头像在右，layer-3 圆角卡（DSH user 气泡）。"""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(48, 0, 0, 0)
        row.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(4)
        role = CaptionLabel("面试官", self)
        role.setObjectName("bubble_role")
        role.setAlignment(Qt.AlignRight)
        col.addWidget(role)
        card = CardWidget(self)
        card.setStyleSheet("background: #353638; border: 1px solid #3d3d40;"
                           "border-radius: 10px;")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 10, 14, 10)
        body = BodyLabel(text, card)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cl.addWidget(body)
        col.addWidget(card)
        row.addStretch(1)
        row.addLayout(col)
        avatar = QLabel("面", self)
        avatar.setObjectName("bubble_avatar")
        avatar.setFixedSize(30, 30)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet("background: #2c2c2e; color: #adb2b8;"
                             "border: 1px solid #3d3d40;")
        row.addWidget(avatar, 0, Qt.AlignTop)


class AnswerBubble(QWidget):
    """回答：左对齐，蓝圈头像在左，layer-1 卡（DSH ai 气泡）+ markdown 流式正文。
    正文为空时显示「正在生成…」占位，首个分块到达即清除。"""

    def __init__(self, question: str, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 48, 0)
        row.setSpacing(10)
        avatar = QLabel("答", self)
        avatar.setObjectName("bubble_avatar")
        avatar.setFixedSize(30, 30)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet("background: #1f2740; color: #7aaaff;"
                             "border: 1px solid #34415b;")
        row.addWidget(avatar, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        role = CaptionLabel("助手", self)
        role.setObjectName("bubble_role")
        col.addWidget(role)
        card = CardWidget(self)
        card.setStyleSheet("background: #232324; border: 1px solid #2c2c2e;"
                           "border-radius: 10px;")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 10, 14, 10)
        cl.setSpacing(6)
        title = StrongBodyLabel(question, card)
        title.setWordWrap(True)
        cl.addWidget(title)
        self.view = QTextBrowser(card)
        self.view.setObjectName("answer")
        self.view.setOpenExternalLinks(False)
        self.view.setMinimumHeight(24)
        self.view.setPlaceholderText("正在生成…")
        cl.addWidget(self.view)
        self.note = CaptionLabel("", card)
        self.note.setObjectName("bubble_note")
        self.note.setWordWrap(True)
        cl.addWidget(self.note)
        col.addWidget(card)
        row.addLayout(col, 1)
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
        self.feed.setObjectName("feed")
        self.feed_lay = QVBoxLayout(self.feed)
        self.feed_lay.setContentsMargins(0, 0, 16, 8)
        self.feed_lay.setSpacing(12)
        self.feed_lay.addStretch(1)
        self.scroll.setWidget(self.feed)
        root.addWidget(self.scroll, 1)

    # ---- 对话流 API ----
    def add_interviewer(self, text: str) -> InterviewerBubble:
        b = InterviewerBubble(text)
        self.feed_lay.insertWidget(self.feed_lay.count() - 1, b)
        self.scroll_to_bottom()
        return b

    def begin_answer(self, question: str) -> AnswerBubble:
        b = AnswerBubble(question)
        self.feed_lay.insertWidget(self.feed_lay.count() - 1, b)
        self.scroll_to_bottom()
        return b

    def scroll_to_bottom(self) -> None:
        sb = self.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
