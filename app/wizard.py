# app/wizard.py —— 下载向导（开箱即用）：打开即自动下载，异常可见、可重试。
# worker 由 starter 提供（主窗口持有），关闭对话框不中断后台下载。
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QDialog, QLabel, QPushButton, QTextEdit, QVBoxLayout)


class ModelWizard(QDialog):
    def __init__(self, starter, parent=None) -> None:
        super().__init__(parent)
        self._starter = starter
        self.setWindowTitle("下载模型（约 1 GB，支持断点续传）")
        self.resize(600, 400)
        lay = QVBoxLayout(self)
        self.heart_label = QLabel("准备下载…")
        lay.addWidget(self.heart_label)
        self.log_view = QTextEdit(readOnly=True)
        lay.addWidget(self.log_view)
        self.retry_btn = QPushButton("重试")
        self.retry_btn.clicked.connect(self._retry)
        lay.addWidget(self.retry_btn)
        self._heart = QTimer(self, interval=5000)
        self._heart.timeout.connect(self._tick_heartbeat)
        self._attach(self._starter())

    def _attach(self, worker) -> None:
        """挂到当前下载 worker：日志/错误/完成全部可见。"""
        self._worker = worker
        worker.line.connect(self.log_view.append)
        worker.failed.connect(self._on_fail)
        worker.finished_ok.connect(self._on_ok)
        self.retry_btn.setEnabled(False)
        self.heart_label.setText("下载中…（约 1 GB，可能需要数分钟）")
        self._heart.start()
        self._tick_heartbeat()

    def _retry(self) -> None:
        self.log_view.append("[重试] 已下载部分会续传")
        self._attach(self._starter())

    def _on_fail(self, msg: str) -> None:
        self._heart.stop()
        self.heart_label.setText("下载失败")
        self.log_view.append(f"下载失败：{msg}")
        self.log_view.append("可点击下方“重试”（已下载部分会续传）。")
        self.retry_btn.setEnabled(True)

    def _on_ok(self) -> None:
        self._heart.stop()
        self.heart_label.setText("全部完成")
        self.log_view.append("全部完成，可关闭")

    def _tick_heartbeat(self) -> None:
        secs = int(self._worker.elapsed())
        self.heart_label.setText(f"下载中… 已 {secs}s（约 1 GB，可能需要数分钟）")
