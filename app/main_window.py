# app/main_window.py —— 主窗口 v3：FluentWindow 壳 + 对话流监听页（qfluentwidgets）。
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel,
                               QPushButton, QTableView, QVBoxLayout, QWidget)

from qfluentwidgets import (FluentWindow, FluentIcon as FIF, PushButton,
                            CardWidget, SubtitleLabel, CaptionLabel, InfoBar,
                            InfoBarPosition)

from app.ui_chat import ChatPage


def _card_page(title: str) -> tuple[QWidget, CardWidget]:
    page = QWidget()
    page.setObjectName(title)
    lay = QVBoxLayout(page)
    lay.setContentsMargins(28, 24, 28, 20)
    lay.setSpacing(14)
    lay.addWidget(SubtitleLabel(title))
    card = CardWidget(page)
    lay.addWidget(card)
    return page, card


class MainWindow(FluentWindow):
    # 管线线程 emit → 队列连接回主线程（与 HotkeyBridge 同模式）
    subtitle_sig = Signal(str)
    audio_error_sig = Signal(str)

    def __init__(self, cfg, kb_factory, rag_factory,
                 rehearsal_rag_factory=None) -> None:
        super().__init__()
        self.cfg = cfg
        self._kb_factory = kb_factory
        self._rag_factory = rag_factory
        self._rehearsal_rag_factory = rehearsal_rag_factory  # 审查 I7：彩排独立会话
        self._rag = None
        self._rehearsal_rag = None
        self._recorder = None
        self._chat_answer = None        # 当前对话流回答气泡
        self._last_utterance = ""       # 最近一句面试官语音（自动作答用）
        self.subtitle_sig.connect(self._on_subtitle)
        self.audio_error_sig.connect(self._on_audio_error)
        self._worker = None
        self._pipeline = None
        self._load_worker = None
        self._pending_build = None
        self._pending_rehearse = False
        self.bridge = None
        self.tray = None
        self._hidden = False
        self._dl_worker = None
        self._dl_heart = None
        self._started_without_models = False
        self.setWindowTitle("Notes")   # 对外中性标题（spec §6.5）
        self.resize(1120, 760)
        self._build_ui()
        self._reload_kb()

    # ---- UI：Fluent 导航壳 + 三页 ----
    def _build_ui(self) -> None:
        self.chat_page = ChatPage(self)
        self.addSubInterface(self.chat_page, FIF.MICROPHONE, "监听")
        self.page_kb = self._build_kb_page()
        self.addSubInterface(self.page_kb, FIF.FOLDER, "知识库")
        self.page_rehearse = self._build_rehearse_page()
        self.addSubInterface(self.page_rehearse, FIF.PLAY, "彩排")

        # 别名：既有测试与逻辑引用
        self.start_btn = self.chat_page.start_btn
        self.model_status_label = self.chat_page.model_status_label
        self.start_btn.clicked.connect(self.start_listening)

        self.navigationInterface.addItem(
            "nav_settings", FIF.SETTING, "设置", selectable=False,
            onClick=lambda: self._open_settings())
        self.navigationInterface.addItem(
            "nav_dl", FIF.DOWNLOAD, "下载模型", selectable=False,
            onClick=lambda: self._open_wizard())
        self.switchTo(self.chat_page)

    def _build_kb_page(self) -> QWidget:
        page, card = _card_page("知识库")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 16)
        self.kb_table = QTableView()
        self.kb_model = QStandardItemModel(0, 2)
        self.kb_model.setHorizontalHeaderLabels(["文件", "块数"])
        self.kb_table.setModel(self.kb_model)
        self.kb_table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.kb_table)
        row = QHBoxLayout()
        upload_btn = PushButton(FIF.ADD, "上传")
        upload_btn.clicked.connect(self._upload)
        del_btn = PushButton(FIF.DELETE, "删除")
        del_btn.clicked.connect(self._delete_selected)
        export_btn = PushButton(FIF.SHARE, "导出")
        export_btn.clicked.connect(self._export_session)
        for b in (upload_btn, del_btn, export_btn):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        return page

    def _build_rehearse_page(self) -> QWidget:
        page, card = _card_page("彩排")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 16)
        lay.setSpacing(10)
        self.rehearse_btn = PushButton(FIF.PLAY, "选择录音开始彩排")
        self.rehearse_btn.clicked.connect(self._rehearse_clicked)
        lay.addWidget(self.rehearse_btn)
        tip = CaptionLabel("彩排把一段 wav 按真实时长回放，走与监听完全一致的链路，"
                           "不接真实设备——首次真实面试前用它做全链路验证。")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        lay.addStretch(1)
        return page

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
                self._info("error", "导入失败", str(exc))
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
            self._apply_settings()
            self._info("ok", "已保存", "设置已保存并立即生效")

    def _apply_settings(self) -> None:
        """审查 I3：设置保存后立即生效——重建 LLM 客户端、重绑热键。"""
        from core.generator import LLMClient
        for rag in (self._rag, self._rehearsal_rag):
            if rag is not None:
                rag.llm = LLMClient(self.cfg.llm_base_url, self.cfg.llm_api_key,
                                    self.cfg.llm_model)
        self.rebind_hotkeys()

    def rebind_hotkeys(self) -> None:
        """审查 I3c/I4：按当前配置重建全局热键；非法组合回退默认，绝不崩溃。"""
        from app.hotkey import HotkeyBridge
        if self.bridge is not None:
            self.bridge.stop()
        try:
            nb = HotkeyBridge(self.cfg.hotkey, self.cfg.hide_hotkey)
        except Exception:
            self._info("error", "热键无效", "已回退默认组合")
            nb = HotkeyBridge("ctrl+alt+space", "ctrl+alt+h")
        nb.pressed.connect(self._on_hotkey)
        nb.hidden.connect(self._on_hide)
        self.bridge = nb

    def _open_wizard(self) -> None:
        from app.wizard import ModelWizard
        ModelWizard(self._dl_worker_or_start, parent=self).exec()

    def _info(self, kind: str, title: str, content: str) -> None:
        f = {"ok": InfoBar.success, "error": InfoBar.error,
             "warn": InfoBar.warning}[kind]
        f(title=title, content=content, orient=Qt.Horizontal, isClosable=True,
          position=InfoBarPosition.TOP, duration=5000, parent=self)

    # ---- 首启自动下载（开箱即用） ----
    def maybe_auto_download(self) -> None:
        from core.downloader import models_ready
        if models_ready(self.cfg.models_dir):
            self._set_model_state("ok")
            return
        self._dl_worker_or_start()

    def _dl_worker_or_start(self):
        from app.workers import DownloadWorker
        if self._dl_worker is not None and self._dl_worker.isRunning():
            return self._dl_worker
        w = DownloadWorker(self.cfg.models_dir)
        w.failed.connect(self._on_dl_failed)
        w.finished_ok.connect(self._on_dl_ok)
        w.progress.connect(self._on_dl_progress)
        self._dl_worker = w
        self._set_model_state("dl")
        self._dl_heart = QTimer(self, interval=5000)
        self._dl_heart.timeout.connect(self._tick_dl_heartbeat)
        self._dl_heart.start()
        w.start()
        self._tick_dl_heartbeat()
        return w

    def _on_dl_failed(self, msg: str) -> None:
        self._stop_dl_heart()
        self._set_model_state("err")
        self._info("error", "模型下载失败", f"{msg}（点左侧“下载模型”重试）")

    def _on_dl_ok(self) -> None:
        self._stop_dl_heart()
        self._set_model_state("ok")
        if self._started_without_models:
            self._info("ok", "模型已就绪", "重启应用后知识库启用语义检索")
        else:
            self._info("ok", "模型已就绪", "语音识别可用")

    def _stop_dl_heart(self) -> None:
        if self._dl_heart is not None:
            self._dl_heart.stop()

    def _tick_dl_heartbeat(self) -> None:
        if self._dl_worker is None:
            return
        secs = int(self._dl_worker.elapsed())
        self.model_status_label.setText(f"下载中… 已 {secs}s")

    def _on_dl_progress(self, p: float) -> None:
        self.model_status_label.setText(f"下载中… {int(p * 100)}%")

    def _set_model_state(self, state: str) -> None:
        text = {"missing": "未下载", "dl": "下载中…", "ok": "模型就绪",
                "err": "下载失败"}.get(state, "")
        self.model_status_label.setProperty("state", state)
        self.model_status_label.setText(text)
        self.model_status_label.style().unpolish(self.model_status_label)
        self.model_status_label.style().polish(self.model_status_label)

    def _on_hide(self) -> None:
        """急隐藏（spec §6.5/§1）：一切可见痕迹消失。"""
        self._hidden = not self._hidden
        self.setVisible(not self._hidden)
        if self.tray is not None:
            self.tray.setVisible(not self._hidden)

    def shutdown(self) -> None:
        """审查 I2：退出前清理全局热钩与线程，避免进程残留。"""
        if self._pipeline is not None:
            self._pipeline.stop()
        if self.bridge is not None:
            self.bridge.stop()
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(2000)
        if self._load_worker is not None and self._load_worker.isRunning():
            self._load_worker.wait(2000)
        self._stop_dl_heart()
        if self._dl_worker is not None and self._dl_worker.isRunning():
            self._dl_worker.wait(2000)

    def quit_app(self) -> None:
        self.shutdown()
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _export_session(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出面试记录", "", "Markdown (*.md)")
        if path and self._recorder is not None:
            from pathlib import Path as P
            p = self._recorder.export_markdown(P(path))
            self._info("ok", "已导出", str(p))

    # ---- 监听 ----
    def start_listening(self) -> None:
        if self._pipeline is not None:
            self._pipeline.stop()
            self._pipeline = None
            self._set_listen_btn("开始监听")
            self._info("ok", "已停止监听", "")
            return
        if self._load_worker is not None and self._load_worker.isRunning():
            return
        from core.downloader import models_ready
        if not models_ready(self.cfg.models_dir):
            self._info("warn", "模型未就绪", "正在下载或未开始，点左侧“下载模型”查看")
            self._open_wizard()
            return
        self._rehearsal_rag = None
        self._rag = self._rag or self._rag_factory()
        rag = self._rag

        def build(tr):
            from core.capture import LiveAudioSource
            from core.pipeline import AudioPipeline
            from core.vad import make_silero_vad
            return AudioPipeline(LiveAudioSource(device_name=self.cfg.audio_device or None),
                                 tr, rag.buffer,
                                 recorder=getattr(rag, "recorder", self._recorder),
                                 vad=make_silero_vad(self.cfg.models_dir))

        self._load_and_start(build)

    def _set_listen_btn(self, text: str, enabled: bool = True) -> None:
        self.start_btn.setText(text)
        self.start_btn.setEnabled(enabled)

    def _rehearse_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择录音", "", "Wave (*.wav)")
        if path:
            self.start_rehearsal(Path(path))

    def start_rehearsal(self, wav_path) -> None:
        """彩排模式（spec §5④）：wav 按真实时长回放，链路与监听一致。"""
        if self._pipeline is not None:
            self._pipeline.stop()
            self._pipeline = None
        if self._load_worker is not None and self._load_worker.isRunning():
            return
        from core.downloader import models_ready
        if not models_ready(self.cfg.models_dir):
            self._info("warn", "模型未就绪", "点左侧“下载模型”查看")
            self._open_wizard()
            return
        if self._rehearsal_rag_factory is not None:
            self._rehearsal_rag = self._rehearsal_rag_factory()
        if self._active_rag() is None:
            self._rag = self._rag_factory()
        rag = self._active_rag()

        def build(tr):
            from core.capture import WavFileSource
            from core.pipeline import AudioPipeline
            from core.vad import make_silero_vad
            return AudioPipeline(WavFileSource(wav_path), tr, rag.buffer,
                                 recorder=getattr(rag, "recorder", self._recorder),
                                 vad=make_silero_vad(self.cfg.models_dir))

        self._load_and_start(build, rehearse=True)

    # ---- Bug 2 / M7：转写器后台加载 ----
    def _load_and_start(self, build, rehearse: bool = False) -> None:
        """连接必须用绑定方法：窗口销毁时 Qt 自动断连。"""
        from app.workers import LoadWorker
        self._pending_build = build
        self._pending_rehearse = rehearse
        self._set_listen_btn("加载模型中…", enabled=False)
        w = LoadWorker(self.cfg.models_dir)
        self._load_worker = w
        w.loaded.connect(self._on_loaded)
        w.failed.connect(self._on_load_failed)
        w.start()

    def _on_loaded(self, tr) -> None:
        try:
            self._pipeline = self._pending_build(tr)
            self._pipeline.on_subtitle = self.subtitle_sig.emit
            self._pipeline.on_error = self.audio_error_sig.emit
            self._pipeline.start()
            self._set_listen_btn("停止监听" if not self._pending_rehearse else "开始监听")
            self.switchTo(self.chat_page)
        except Exception as exc:
            self._info("error", "启动失败", str(exc))
            self._set_listen_btn("开始监听")

    def _on_load_failed(self, msg: str) -> None:
        self._info("error", "启动失败", msg)
        self._set_listen_btn("开始监听")

    def _on_audio_error(self, m: str) -> None:
        self._pipeline = None
        self._set_listen_btn("开始监听")
        self._info("error", "音频异常，已停止监听", f"{m}（可重新点“开始监听”）")

    def _active_rag(self):
        """审查 I7：热键作用于当前活跃会话（彩排中 → 彩排会话）。"""
        return self._rehearsal_rag if self._rehearsal_rag is not None else self._rag

    # ---- 热键→生成 ----
    def _on_hotkey(self) -> None:
        from app.workers import GenerateWorker
        if self._worker is not None and self._worker.isRunning():
            return
        if self._pipeline is not None:
            self._pipeline.flush_pending()
        if self._active_rag() is None:
            self._rag = self._rag_factory()
        self._chat_answer = self.chat_page.begin_answer(
            self._last_utterance or "（手动触发生成）")
        self._worker = GenerateWorker(self._active_rag())
        self._worker.question.connect(self._on_question)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.notice.connect(self._on_notice)
        self._worker.failed.connect(self._on_generate_failed)
        self._worker.start()

    # ---- 字幕/问答双写：对话流留档 + 悬浮窗实时 ----
    def _on_subtitle(self, t: str) -> None:
        self.chat_page.add_interviewer(t)
        self._last_utterance = t
        from core.heuristics import looks_like_question
        worker_busy = self._worker is not None and self._worker.isRunning()
        if self.chat_page.auto_switch.isChecked() and not worker_busy:
            if looks_like_question(t):
                self._on_hotkey()

    def _on_question(self, q: str) -> None:
        if not q:
            if self._chat_answer is not None:
                self._chat_answer.note.setText("未识别到问题（稍后再按）")

    def _on_chunk(self, delta: str) -> None:
        if self._chat_answer is not None:
            self._chat_answer.append(delta)
            self.chat_page.scroll_to_bottom()

    def _on_generate_failed(self, m: str) -> None:
        self._info("error", "生成失败", f"{m}，可重试")
        if self._chat_answer is not None:
            self._chat_answer.mark_interrupted()

    def _on_notice(self, m: str) -> None:
        if self._chat_answer is not None:
            self._chat_answer.note.setText(m)
