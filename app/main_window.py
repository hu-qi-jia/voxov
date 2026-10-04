# app/main_window.py（核心逻辑；样式从简）
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel,
                               QMainWindow, QPushButton, QTableView, QVBoxLayout, QWidget)

from app.overlay import OverlayWindow


class MainWindow(QMainWindow):
    # 管线线程 emit → 队列连接回主线程（与 HotkeyBridge 同模式）
    subtitle_sig = Signal(str)
    audio_error_sig = Signal(str)

    def __init__(self, cfg, kb_factory, rag_factory) -> None:
        super().__init__()
        self.cfg = cfg
        self._kb_factory = kb_factory
        self._rag_factory = rag_factory
        self._rag = None
        self._recorder = None  # main.py 注入；未注入时导出按钮禁用逻辑依赖它
        self.overlay = OverlayWindow()
        self.subtitle_sig.connect(lambda t: self.overlay.set_subtitle(t))
        self.audio_error_sig.connect(
            lambda m: self.overlay.show_status(f"音频异常：{m}，请重新开始监听"))
        self._worker = None
        self._pipeline = None
        self.tray = None      # main.py 注入（急隐藏需要同时藏托盘）
        self._hidden = False
        self.setWindowTitle("Notes")   # 对外中性标题（spec §6.5）
        self.resize(720, 480)
        self._build_ui()
        self._reload_kb()

    def _build_ui(self) -> None:
        central = QWidget()
        lay = QVBoxLayout(central)
        # 知识库区（文案极简：spec §6.8 只留操作标签与状态词）
        self.kb_table = QTableView()
        self.kb_model = QStandardItemModel(0, 2)
        self.kb_model.setHorizontalHeaderLabels(["文件", "块数"])
        self.kb_table.setModel(self.kb_model)
        lay.addWidget(QLabel("知识库"))
        lay.addWidget(self.kb_table)
        row = QHBoxLayout()
        upload_btn = QPushButton("上传")
        upload_btn.clicked.connect(self._upload)
        del_btn = QPushButton("删除")
        del_btn.clicked.connect(self._delete_selected)
        export_btn = QPushButton("导出")
        export_btn.clicked.connect(self._export_session)
        start_btn = QPushButton("监听")
        start_btn.setProperty("accent", True)
        start_btn.clicked.connect(self.start_listening)
        self.rehearse_btn = QPushButton("彩排")
        self.rehearse_btn.clicked.connect(self._rehearse_clicked)
        wizard_btn = QPushButton("下载模型")
        wizard_btn.clicked.connect(self._open_wizard)
        settings_btn = QPushButton("设置")
        settings_btn.clicked.connect(self._open_settings)
        for b in (upload_btn, del_btn, export_btn, start_btn,
                  self.rehearse_btn, wizard_btn, settings_btn):
            row.addWidget(b)
        lay.addLayout(row)
        self.setCentralWidget(central)

    def _reload_kb(self) -> None:
        self.kb_model.setRowCount(0)
        for name, n in self._kb_factory().list_files():
            self.kb_model.appendRow([QStandardItem(name), QStandardItem(str(n))])

    def _upload(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "选择 md 文件", "", "Markdown (*.md)")
        kb = self._kb_factory()
        for f in files:
            try:
                kb.ingest_file(Path(f))
            except ValueError as exc:
                self.statusBar().showMessage(str(exc))
        self._reload_kb()

    def _delete_selected(self) -> None:
        idx = self.kb_table.currentIndex()
        if not idx.isValid():
            return
        name = self.kb_model.item(idx.row(), 0).text()
        self._kb_factory().delete_file(name)
        self._reload_kb()

    def _open_settings(self) -> None:
        from app.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.cfg, parent=self)
        if dlg.exec():
            self.statusBar().showMessage("已保存")

    def _open_wizard(self) -> None:
        from app.wizard import ModelWizard
        ModelWizard(self.cfg, parent=self).exec()

    def _on_hide(self) -> None:
        """急隐藏（spec §6.5）：悬浮窗+托盘同时隐/显，再按一次恢复。"""
        self._hidden = not self._hidden
        self.overlay.setVisible(not self._hidden)
        if self.tray is not None:
            self.tray.setVisible(not self._hidden)

    def _export_session(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "导出面试记录", "", "Markdown (*.md)")
        if path and self._recorder is not None:
            from pathlib import Path as P
            p = self._recorder.export_markdown(P(path))
            self.statusBar().showMessage(f"已导出 {p}")

    def start_listening(self) -> None:
        from core.capture import LiveAudioSource
        from core.pipeline import AudioPipeline
        from core.transcriber import FunasrTranscriber
        if self._pipeline is not None:
            self._pipeline.stop()
            self._pipeline = None
            self.statusBar().showMessage("已停止监听")
            return
        transcriber = FunasrTranscriber(self.cfg.models_dir)
        source = LiveAudioSource()
        self._rag = self._rag or self._rag_factory()
        self._pipeline = AudioPipeline(source, transcriber, self._rag.buffer, recorder=self._recorder)
        self._pipeline.on_subtitle = self.subtitle_sig.emit  # 管线线程安全 emit
        self._pipeline.on_error = self.audio_error_sig.emit
        self._pipeline.start()
        self.overlay.show()
        self.statusBar().showMessage("监听中：系统音频 → 字幕；Ctrl+Alt+Space 触发回答")

    def _rehearse_clicked(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        from pathlib import Path as P
        path, _ = QFileDialog.getOpenFileName(self, "选择录音", "", "Wave (*.wav)")
        if path:
            self.start_rehearsal(P(path))

    def start_rehearsal(self, wav_path) -> None:
        """彩排模式（spec §5④）：wav 按真实时长回放，链路与监听完全一致，
        不接真实设备——首次真实面试前用它全链路验证。"""
        from core.capture import WavFileSource
        from core.pipeline import AudioPipeline
        from core.transcriber import FunasrTranscriber
        if self._pipeline is not None:
            self._pipeline.stop()
        transcriber = FunasrTranscriber(self.cfg.models_dir)
        self._rag = self._rag or self._rag_factory()
        self._pipeline = AudioPipeline(WavFileSource(wav_path), transcriber,
                                       self._rag.buffer, recorder=self._recorder)
        self._pipeline.on_subtitle = self.subtitle_sig.emit
        self._pipeline.on_error = self.audio_error_sig.emit
        self._pipeline.start()
        self.overlay.show()
        self.statusBar().showMessage("彩排中")

    # --- 热键→生成 ---
    def _on_hotkey(self) -> None:
        from app.workers import GenerateWorker
        if self._worker is not None and self._worker.isRunning():
            return  # 上一轮未完成，忽略连按
        if self._pipeline is not None:
            self._pipeline.flush_pending()  # spec §6.6：先强刷 pending 语音再提取问题
        if self._rag is None:
            self._rag = self._rag_factory()
        self.overlay.show()
        self._worker = GenerateWorker(self._rag)
        self._worker.question.connect(self._on_question)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.done.connect(lambda: self.overlay.end_answer())
        self._worker.failed.connect(lambda m: self.overlay.show_status(f"生成失败：{m}，可重试"))
        self._worker.start()

    def _on_question(self, q: str) -> None:
        if q:
            self.overlay.begin_answer(q)
        else:
            self.overlay.show_status("未识别到问题（稍后再按）")

    def _on_chunk(self, delta: str) -> None:
        self.overlay.append_answer(delta)
