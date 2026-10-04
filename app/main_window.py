# app/main_window.py（核心逻辑；样式从简）
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QHBoxLayout, QLabel,
                               QMainWindow, QPushButton, QStackedWidget, QTableView,
                               QTextBrowser, QTextEdit, QVBoxLayout, QWidget)

from app.overlay import OverlayWindow


class MainWindow(QMainWindow):
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
        self._recorder = None  # main.py 注入；未注入时导出按钮禁用逻辑依赖它
        self.overlay = OverlayWindow()
        self._main_answer_buf = ""      # 主窗口问答流缓冲（与悬浮窗同源双写）
        self.subtitle_sig.connect(self._on_subtitle)
        self.audio_error_sig.connect(
            lambda m: self.overlay.show_status(f"音频异常：{m}，请重新开始监听"))
        self._worker = None
        self._pipeline = None
        self._load_worker = None     # Bug 2/M7：转写器后台加载
        self._pending_build = None
        self._pending_rehearse = False
        self.bridge = None      # rebind_hotkeys() 创建/重建（审查 I3c）
        self.tray = None        # main.py 注入（急隐藏需要同时藏托盘）
        self._hidden = False
        self._dl_worker = None          # 首启自动下载（开箱即用）
        self._dl_heart = None
        self._started_without_models = False   # main.py 注入：成功后提示重启升级检索
        self.setWindowTitle("Notes")   # 对外中性标题（spec §6.5）
        self.resize(720, 480)
        self._build_ui()
        self._reload_kb()

    # --- UI：左导航（知识库置顶）+ 右侧页面栈（spec §6.8 暗色令牌） ---
    def _build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        self.side_layout = QVBoxLayout(side)
        self.side_layout.setContentsMargins(12, 16, 12, 12)
        self.side_layout.setSpacing(4)
        title = QLabel("Notes")          # 对外中性名（spec §6.5）
        title.setObjectName("side_title")
        self.side_layout.addWidget(title)
        self.side_layout.addSpacing(8)

        self.stack = QStackedWidget()
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.page_kb = self._build_kb_page()
        self.page_listen = self._build_listen_page()
        self.page_rehearse = self._build_rehearse_page()
        self.nav_kb = self._nav_btn("知识库", self.page_kb)
        self.nav_listen = self._nav_btn("监听", self.page_listen)
        self.nav_rehearse = self._nav_btn("彩排", self.page_rehearse)
        for p in (self.page_kb, self.page_listen, self.page_rehearse):
            self.stack.addWidget(p)
        for b in (self.nav_kb, self.nav_listen, self.nav_rehearse):
            self.nav_group.addButton(b)
            self.side_layout.addWidget(b)
        self.side_layout.addStretch(1)

        self.model_status_label = QLabel("未下载")
        self.model_status_label.setObjectName("model_status")
        self.side_layout.addWidget(self.model_status_label)
        self.wizard_btn = QPushButton("下载模型")
        self.wizard_btn.setObjectName("side_small")
        self.wizard_btn.clicked.connect(self._open_wizard)
        self.settings_btn = QPushButton("设置")
        self.settings_btn.setObjectName("side_small")
        self.settings_btn.clicked.connect(self._open_settings)
        self.side_layout.addWidget(self.wizard_btn)
        self.side_layout.addWidget(self.settings_btn)

        root.addWidget(side)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.nav_kb.setChecked(True)
        self.stack.setCurrentWidget(self.page_kb)

    def _nav_btn(self, text: str, page) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("nav")
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda: self.stack.setCurrentWidget(page))
        return b

    def _build_kb_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)
        self.kb_table = QTableView()
        self.kb_model = QStandardItemModel(0, 2)
        self.kb_model.setHorizontalHeaderLabels(["文件", "块数"])
        self.kb_table.setModel(self.kb_model)
        lay.addWidget(self.kb_table)
        row = QHBoxLayout()
        upload_btn = QPushButton("上传")
        upload_btn.clicked.connect(self._upload)
        del_btn = QPushButton("删除")
        del_btn.clicked.connect(self._delete_selected)
        export_btn = QPushButton("导出")
        export_btn.clicked.connect(self._export_session)
        for b in (upload_btn, del_btn, export_btn):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        return page

    def _build_listen_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)
        row = QHBoxLayout()
        self.start_btn = QPushButton("开始监听")
        self.start_btn.setProperty("accent", True)
        self.start_btn.clicked.connect(self.start_listening)
        row.addWidget(self.start_btn)
        hint = QLabel("系统音频 → 字幕；Ctrl+Alt+Space 触发回答，急隐藏 Ctrl+Alt+H")
        hint.setObjectName("hint")
        row.addWidget(hint, 1)
        lay.addLayout(row)
        cap = QLabel("监听内容")
        cap.setObjectName("hint")
        lay.addWidget(cap)
        self.subtitle_view = QTextEdit(readOnly=True)
        self.subtitle_view.setObjectName("subtitle_view")
        self.subtitle_view.setPlaceholderText("开始监听后，识别到的语音逐句显示在这里")
        lay.addWidget(self.subtitle_view, 1)
        cap2 = QLabel("问题与回答")
        cap2.setObjectName("hint")
        lay.addWidget(cap2)
        self.answer_view = QTextBrowser()
        self.answer_view.setObjectName("answer")
        self.answer_view.setOpenExternalLinks(False)
        lay.addWidget(self.answer_view, 2)
        return page

    def _build_rehearse_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)
        self.rehearse_btn = QPushButton("选择录音开始彩排")
        self.rehearse_btn.clicked.connect(self._rehearse_clicked)
        lay.addWidget(self.rehearse_btn)
        tip = QLabel("彩排把一段 wav 按真实时长回放，走与监听完全一致的链路，"
                     "不接真实设备——首次真实面试前用它做全链路验证。")
        tip.setObjectName("hint")
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
            self._apply_settings()
            self.statusBar().showMessage("已保存")

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
            self.statusBar().showMessage("热键无效，已回退默认组合")
            nb = HotkeyBridge("ctrl+alt+space", "ctrl+alt+h")
        nb.pressed.connect(self._on_hotkey)
        nb.hidden.connect(self._on_hide)
        self.bridge = nb

    def _open_wizard(self) -> None:
        from app.wizard import ModelWizard
        ModelWizard(self._dl_worker_or_start, parent=self).exec()

    # --- 首启自动下载（开箱即用，spec §3/§8） ---
    def maybe_auto_download(self) -> None:
        """模型缺失时后台自动下载，不弹窗；状态灯反映进度。"""
        from core.downloader import models_ready
        if models_ready(self.cfg.models_dir):
            self._set_model_state("ok")
            return
        self._dl_worker_or_start()

    def _dl_worker_or_start(self):
        """当前下载 worker；无/已结束则新建并启动（重试=断点续传）。"""
        from app.workers import DownloadWorker
        if self._dl_worker is not None and self._dl_worker.isRunning():
            return self._dl_worker
        w = DownloadWorker(self.cfg.models_dir,
                           log_file=self.cfg.data_dir / "download.log")
        w.failed.connect(self._on_dl_failed)
        w.finished_ok.connect(self._on_dl_ok)
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
        self.statusBar().showMessage(f"模型下载失败：{msg}（点“下载模型”重试）", 10000)

    def _on_dl_ok(self) -> None:
        self._stop_dl_heart()
        self._set_model_state("ok")
        if self._started_without_models:
            self.statusBar().showMessage("模型已就绪；重启应用后知识库启用语义检索", 10000)
        else:
            self.statusBar().showMessage("模型已就绪", 5000)

    def _stop_dl_heart(self) -> None:
        if self._dl_heart is not None:
            self._dl_heart.stop()

    def _tick_dl_heartbeat(self) -> None:
        if self._dl_worker is None:
            return
        secs = int(self._dl_worker.elapsed())
        self.model_status_label.setText(f"下载中… 已 {secs}s")

    def _set_model_state(self, state: str) -> None:
        text = {"missing": "未下载", "dl": "下载中…", "ok": "模型就绪",
                "err": "下载失败"}.get(state, "")
        self.model_status_label.setProperty("state", state)
        self.model_status_label.setText(text)
        self.model_status_label.style().unpolish(self.model_status_label)
        self.model_status_label.style().polish(self.model_status_label)

    def _on_hide(self) -> None:
        """急隐藏（spec §6.5/§1）：一切可见痕迹消失——主窗口+悬浮窗+托盘。"""
        self._hidden = not self._hidden
        self.setVisible(not self._hidden)
        self.overlay.setVisible(not self._hidden)
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
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "导出面试记录", "", "Markdown (*.md)")
        if path and self._recorder is not None:
            from pathlib import Path as P
            p = self._recorder.export_markdown(P(path))
            self.statusBar().showMessage(f"已导出 {p}")

    def start_listening(self) -> None:
        if self._pipeline is not None:
            self._pipeline.stop()
            self._pipeline = None
            self._set_listen_btn("开始监听")
            self.statusBar().showMessage("已停止监听")
            return
        if self._load_worker is not None and self._load_worker.isRunning():
            return  # 加载中，忽略连点
        from core.downloader import models_ready
        if not models_ready(self.cfg.models_dir):   # Bug 2 门禁：缺模型不盲启
            self.statusBar().showMessage("模型未就绪：正在下载或未开始，点“下载模型”查看")
            self.overlay.show_status("模型未就绪，暂不能监听")
            self._open_wizard()
            return
        self._rehearsal_rag = None  # 回到正式会话
        self._rag = self._rag or self._rag_factory()
        rag = self._rag

        def build(tr):
            from core.capture import LiveAudioSource
            from core.pipeline import AudioPipeline
            return AudioPipeline(LiveAudioSource(device_name=self.cfg.audio_device or None),  # 审查 I3b
                                 tr, rag.buffer,
                                 recorder=getattr(rag, "recorder", self._recorder))

        self._load_and_start(build)

    def _rehearse_clicked(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        from pathlib import Path as P
        path, _ = QFileDialog.getOpenFileName(self, "选择录音", "", "Wave (*.wav)")
        if path:
            self.start_rehearsal(P(path))

    def start_rehearsal(self, wav_path) -> None:
        """彩排模式（spec §5④）：wav 按真实时长回放，链路与监听完全一致，
        不接真实设备——首次真实面试前用它全链路验证。审查 I7：独立会话与记录。"""
        if self._pipeline is not None:
            self._pipeline.stop()
            self._pipeline = None
        if self._load_worker is not None and self._load_worker.isRunning():
            return
        from core.downloader import models_ready
        if not models_ready(self.cfg.models_dir):
            self.statusBar().showMessage("模型未就绪：正在下载或未开始，点“下载模型”查看")
            self.overlay.show_status("模型未就绪，暂不能彩排")
            self._open_wizard()
            return
        if self._rehearsal_rag_factory is not None:
            self._rehearsal_rag = self._rehearsal_rag_factory()
        if self._active_rag() is None:  # 无工厂且尚未建过会话
            self._rag = self._rag_factory()
        rag = self._active_rag()

        def build(tr):
            from core.capture import WavFileSource
            from core.pipeline import AudioPipeline
            return AudioPipeline(WavFileSource(wav_path), tr, rag.buffer,
                                 recorder=getattr(rag, "recorder", self._recorder))

        self._load_and_start(build, rehearse=True)

    # --- Bug 2 / M7：转写器后台加载，绝不冻结 GUI 线程 ---
    def _set_listen_btn(self, text: str, enabled: bool = True) -> None:
        self.start_btn.setText(text)
        self.start_btn.setEnabled(enabled)

    def _load_and_start(self, build, rehearse: bool = False) -> None:
        """连接必须用绑定方法（receiver=self）：窗口销毁时 Qt 自动断连，
        否则队列信号投递到已死控件的闭包 → 访问违例。"""
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
            self._pipeline.on_subtitle = self.subtitle_sig.emit  # 管线线程安全 emit
            self._pipeline.on_error = self.audio_error_sig.emit
            self._pipeline.start()
            self.overlay.show()
            self._set_listen_btn("停止监听" if not self._pending_rehearse else "开始监听")
            self.statusBar().showMessage(
                "彩排中" if self._pending_rehearse
                else "监听中：系统音频 → 字幕；Ctrl+Alt+Space 触发回答")
        except Exception as exc:
            self.statusBar().showMessage(f"启动失败：{exc}")
            self.overlay.show_status(f"启动失败：{exc}")
            self._set_listen_btn("开始监听")

    def _on_load_failed(self, msg: str) -> None:
        self.statusBar().showMessage(f"启动失败：{msg}")
        self.overlay.show_status(f"启动失败：{msg}")
        self._set_listen_btn("开始监听")

    def _active_rag(self):
        """审查 I7：热键作用于当前活跃会话（彩排中 → 彩排会话）。"""
        return self._rehearsal_rag if self._rehearsal_rag is not None else self._rag

    # --- 热键→生成 ---
    def _on_hotkey(self) -> None:
        from app.workers import GenerateWorker
        if self._worker is not None and self._worker.isRunning():
            return  # 上一轮未完成，忽略连按
        if self._pipeline is not None:
            self._pipeline.flush_pending()  # spec §6.6：先强刷 pending 语音再提取问题
        if self._active_rag() is None:
            self._rag = self._rag_factory()
        if not self._hidden:  # 审查 I1：急隐藏态不弹悬浮窗
            self.overlay.show()
        self._worker = GenerateWorker(self._active_rag())
        self._worker.question.connect(self._on_question)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.notice.connect(
            lambda m: self.overlay.show_status(m))  # 审查 I12：通用回答标记
        self._worker.done.connect(lambda: self.overlay.end_answer())
        self._worker.failed.connect(lambda m: self.overlay.show_status(f"生成失败：{m}，可重试"))
        self._worker.start()

    # --- 字幕/问答双写：主窗口全量留档，悬浮窗只保最新观感 ---
    def _on_subtitle(self, t: str) -> None:
        self.overlay.set_subtitle(t)
        self.subtitle_view.append(t)

    def _on_question(self, q: str) -> None:
        if q:
            self.overlay.begin_answer(q)
            # 主窗口是全量会话留档：新问题追加成新块，不抹历史
            self._main_answer_buf += f"\n**问：** {q}\n\n"
            self.answer_view.setMarkdown(self._main_answer_buf)
        else:
            self.overlay.show_status("未识别到问题（稍后再按）")

    def _on_chunk(self, delta: str) -> None:
        self.overlay.append_answer(delta)
        if delta:
            self._main_answer_buf += delta
            self.answer_view.setMarkdown(self._main_answer_buf)
