# app/ui_chat.py —— 监听页：终端转写流（无气泡容器，1px 分割线）。
from PySide6.QtCore import QEvent, Qt, QTimer
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

    def sizeHint(self):                        # 宽度解耦：长行/宽表格不得撑开主窗
        from PySide6.QtCore import QSize
        return QSize(self.width(), max(28, int(self.document().size().height()) + 10))

    def minimumSizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(0, 28)

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
        doc = self.view.document()
        doc.setDocumentMargin(0)          # 默认 4px 内边距去掉：贴齐正文流
        doc.setDefaultStyleSheet(
            f"strong {{ color: {ACCENT}; }}"
            "p { margin: 3px 0; }"                    # 段落紧凑，像 md 渲染而非双倍空行
            "h1,h2,h3,h4 { margin: 6px 0 3px; }"
            "ul,ol { margin: 2px 0 2px 22px; }"
            "li { margin: 1px 0; }"
            "table { margin: 3px 0; }"
        )
        self.view.setPlaceholderText("正在生成…")
        self.view.setFixedHeight(36)
        col.addWidget(self.view)
        self.note = QLabel("", self)
        self.note.setObjectName("turn_note")
        self.note.setWordWrap(True)
        col.addWidget(self.note)
        self._buf = ""
        self._t0 = None               # 生成计时：等 8s+ 的 LLM 缝合要有时间预期

    def start_progress(self) -> None:
        import time
        self._t0 = time.monotonic()

    def tick_progress(self) -> None:
        if self._t0 is not None and not self._buf:
            self.view.setPlaceholderText(f"正在生成… {int(time.monotonic() - self._t0)}s")

    def stop_progress(self) -> None:
        self._t0 = None

    def append(self, delta: str) -> None:
        if not delta:
            return
        self.stop_progress()
        self._buf += delta
        self.view.setMarkdown(self._buf)
        self._recolor_bold()
        self.view.refit()       # 增高后的跟随由 ChatPage 的钉底事件过滤器统一负责

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

    def miss(self, msg: str) -> None:
        """未命中：占位与标注替换为原因（无 LLM 输出）。"""
        self.stop_progress()
        self.view.setPlaceholderText(msg)
        self.note.setText(msg)

    def fail(self, msg: str) -> None:
        """失败可见化：有内容标注截断；空内容换掉「正在生成…」占位并说明原因。"""
        self.stop_progress()
        if self._buf:
            self.mark_interrupted()
        else:
            self.view.setPlaceholderText("生成失败——可重新提问")
            self.note.setText(msg)


class ChatPage(QWidget):
    """监听页：头行（开始监听 + 自动作答）+ 转写流。"""

    PIN_TOLERANCE = 48   # 距底部 ≤48px 视为「钉在底部」

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

        # 滚动跟随：插入的词条要经布局实排出真实高度（word-wrap / refit），
        # 插入瞬间滚到底是滚不到的——feed 高度一变（Resize）就补滚，才贴得住最新一条。
        self._pinned = True
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self.feed.installEventFilter(self)

        # 生成计时：LLM 缝合要等 8-60s，「正在生成… Ns」让等待有预期
        from PySide6.QtCore import QTimer
        self._progress_timer = QTimer(self, interval=1000)
        self._progress_timer.timeout.connect(self._tick_progress)
        self._progress_timer.start()

    def _tick_progress(self) -> None:
        for i in range(self.feed_lay.count()):
            w = self.feed_lay.itemAt(i).widget()
            if isinstance(w, AnswerTurn):
                w.tick_progress()

    def _on_scrolled(self, value: int) -> None:
        sb = self.scroll.verticalScrollBar()
        self._pinned = value >= sb.maximum() - self.PIN_TOLERANCE

    def eventFilter(self, obj, ev) -> bool:
        if obj is self.feed and ev.type() == QEvent.Resize and self._pinned:
            QTimer.singleShot(0, self.scroll_to_bottom)   # 布局落定后再滚
        return super().eventFilter(obj, ev)

    def add_interviewer(self, text: str) -> InterviewerTurn:
        t = InterviewerTurn(text)
        self.feed_lay.insertWidget(self.feed_lay.count() - 1, t)
        self.feed_lay.insertWidget(self.feed_lay.count() - 1, _hline())
        self.follow_latest()          # 新问题：无条件跟随最新一条
        return t

    def begin_answer(self) -> AnswerTurn:
        b = AnswerTurn()
        b.start_progress()
        self.feed_lay.insertWidget(self.feed_lay.count() - 1, b)
        self.follow_latest()
        return b

    def follow_latest(self) -> None:
        """钉底 + 立即滚 + 布局实排后补滚一次（立即滚时 maximum 还是旧值）。"""
        self._pinned = True
        self.scroll_to_bottom()
        QTimer.singleShot(0, self.scroll_to_bottom)

    def scroll_to_bottom(self) -> None:
        sb = self.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
