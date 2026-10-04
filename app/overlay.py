# app/overlay.py
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel, QTextBrowser, QVBoxLayout, QWidget


class OverlayWindow(QWidget):
    """置顶悬浮窗：字幕区 + 问题标题 + 流式答案（spec §2/§6.5/§6.8）。"""

    def __init__(self) -> None:
        super().__init__(None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setWindowTitle("Notes")           # 对外中性标题（spec §6.5）
        self.setObjectName("overlay")
        self.setAttribute(Qt.WA_StyledBackground, True)  # 让 QSS 背景生效
        self.setWindowOpacity(0.92)
        self.resize(460, 320)
        self._subtitles: list[str] = []
        self._drag_offset: QPoint | None = None

        lay = QVBoxLayout(self)
        self.subtitle_label = QLabel("(等待音频…)")
        self.subtitle_label.setObjectName("subtitle")
        self.subtitle_label.setWordWrap(True)
        self.question_label = QLabel("")
        self.question_label.setObjectName("question")
        self.question_label.setWordWrap(True)
        self.answer_view = QTextBrowser()
        self.answer_view.setObjectName("answer")
        self.answer_view.setOpenExternalLinks(False)
        self.status_label = QLabel("")
        self.status_label.setObjectName("status")
        lay.addWidget(self.subtitle_label)
        lay.addWidget(self.question_label)
        lay.addWidget(self.answer_view, stretch=1)
        lay.addWidget(self.status_label)

    def set_subtitle(self, text: str) -> None:
        self._subtitles = (self._subtitles + [text])[-3:]
        self.subtitle_label.setText("\n".join(self._subtitles))

    def begin_answer(self, question: str) -> None:
        self.question_label.setText(question)
        self.answer_view.clear()
        self.status_label.setText("")

    def append_answer(self, chunk: str) -> None:
        self.answer_view.insertPlainText(chunk)
        sb = self.answer_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def end_answer(self) -> None:
        self.status_label.setText("")

    def show_status(self, text: str) -> None:
        self.status_label.setText(text)

    # --- 拖动 ---
    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_offset is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._drag_offset = None
