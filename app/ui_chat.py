# app/ui_chat.py —— 监听页：对话流（DSH 风格，扁平单层面板，无嵌套盒子）。
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QTextBrowser,
                               QVBoxLayout, QWidget)

from qfluentwidgets import (FluentIcon as FIF, ScrollArea, PushButton,
                            SwitchButton, SubtitleLabel, StrongBodyLabel,
                            CaptionLabel, BodyLabel)


def _flat_panel(bg: str, border: str) -> QFrame:
    """单层扁平面板：只留一层 1px 描边，杜绝盒子套盒子。"""
    f = QFrame()
    f.setStyleSheet(f"QFrame {{ background: {bg}; border: 1px solid {border};"
                    f"border-radius: 10px; }}")
    return f


def _avatar(text: str, bg: str, fg: str, bd: str) -> QLabel:
    a = QLabel(text)
    a.setObjectName("bubble_avatar")
    a.setFixedSize(30, 30)
    a.setAlignment(Qt.AlignCenter)
    a.setStyleSheet(f"background: {bg}; color: {fg}; border: 1px solid {bd};")
    return a


class InterviewerBubble(QWidget):
    """面试官：右对齐，头像在右，layer-3 单层面板。"""

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
        panel = _flat_panel("#353638", "#3d3d40")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 10, 14, 10)
        body = BodyLabel(text, panel)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pl.addWidget(body)
        col.addWidget(panel)
        row.addStretch(1)
        row.addLayout(col)
        row.addWidget(_avatar("面", "#2c2c2e", "#adb2b8", "#3d3d40"), 0, Qt.AlignTop)


class _AutoHeightBrowser(QTextBrowser):
    """无边框、无滚动条的流式正文。
    QTextBrowser 默认自带 StyledPanel 内框（QSS border:none 清不掉），
    加上高度按旧宽度误算导致裁字+滚动条——三者叠加读起来像"文字被框住"。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setOpenExternalLinks(False)

    def refit(self) -> None:
        """按当前视口宽度实排正文，高度兜住全部内容。"""
        doc = self.document()
        doc.setTextWidth(self.viewport().width() or doc.textWidth())
        self.setFixedHeight(max(28, int(doc.size().height()) + 10))

    def resizeEvent(self, ev) -> None:  # 宽度变了必须重排，否则按旧宽度算高会裁字
        super().resizeEvent(ev)
        if ev.oldSize().width() != self.width():
            self.refit()


class AnswerBubble(QWidget):
    """回答：左对齐，头像在左，layer-1 单层面板 + markdown 流式正文。
    正文区高度随内容自适应（不留大空白）；空态显示「正在生成…」；
    生成中断时 note 显示已截断提示。"""

    def __init__(self, question: str, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 48, 0)
        row.setSpacing(10)
        row.addWidget(_avatar("答", "#1f2740", "#7aaaff", "#34415b"), 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        role = CaptionLabel("助手", self)
        role.setObjectName("bubble_role")
        col.addWidget(role)
        panel = _flat_panel("#232324", "#2c2c2e")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 10, 14, 10)
        pl.setSpacing(6)
        title = StrongBodyLabel(question, panel)
        title.setWordWrap(True)
        pl.addWidget(title)
        self.view = _AutoHeightBrowser(panel)
        self.view.setObjectName("answer")
        self.view.setPlaceholderText("正在生成…")
        self.view.setFixedHeight(36)      # 空态占位高度；首个分块后自适应
        pl.addWidget(self.view)
        self.note = CaptionLabel("", panel)
        self.note.setObjectName("bubble_note")
        self.note.setWordWrap(True)
        pl.addWidget(self.note)
        col.addWidget(panel)
        row.addLayout(col, 1)
        self._buf = ""

    def append(self, delta: str) -> None:
        if not delta:
            return
        self._buf += delta
        self.view.setMarkdown(self._buf)
        self.view.refit()
        self._parent_scroll_to_bottom()

    def mark_interrupted(self) -> None:
        if self._buf:
            self.note.setText("生成中断——以上为已收到的部分，可稍后重试")

    def _parent_scroll_to_bottom(self) -> None:
        p = self.parent()
        while p is not None:
            if hasattr(p, "scroll_to_bottom"):
                p.scroll_to_bottom()
                return
            p = p.parent()


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
