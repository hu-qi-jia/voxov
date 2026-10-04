# app/wizard.py
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QPushButton, QTextEdit, QVBoxLayout)

from core.downloader import ensure_models


class _DownloadThread(QThread):
    line = Signal(str)
    finished_ok = Signal()

    def __init__(self, models_dir) -> None:
        super().__init__()
        self.models_dir = models_dir

    def run(self) -> None:
        ensure_models(self.models_dir, self.line.emit)
        self.finished_ok.emit()


class ModelWizard(QDialog):
    def __init__(self, cfg, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("下载模型（约 0.5 GB，镜像 hf-mirror.com）")
        self.resize(600, 400)
        lay = QVBoxLayout(self)
        self.log_view = QTextEdit(readOnly=True)
        btn = QPushButton("开始下载")
        btn.clicked.connect(self._go)
        lay.addWidget(self.log_view)
        lay.addWidget(btn)

    def _go(self) -> None:
        self._t = _DownloadThread(self.cfg.models_dir)
        self._t.line.connect(self.log_view.append)
        self._t.finished_ok.connect(lambda: self.log_view.append("全部完成，可关闭"))
        self._t.start()
