# app/main_window.py —— 主窗口 v4：retro terminal 壳。
# 顶栏文本 tab + 底部状态行；设置/下载并入设置页；彩排已移除。
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QStackedWidget, QTableView, QVBoxLayout, QWidget)

from app.icons import icon
from app.settings_page import SettingsPage
from app.ui_chat import ChatPage

STATUS_COLOR = {"info": "#e6e6e6", "ok": "#5af78e", "warn": "#e3b341", "error": "#f85149"}


class MainWindow(QMainWindow):
    subtitle_sig = Signal(str)
    audio_error_sig = Signal(str)

    def __init__(self, cfg, kb_factory, rag_factory) -> None:
        super().__init__()
        self.cfg = cfg
        self._kb_factory = kb_factory
        self._rag_factory = rag_factory
        self._rag = None
        self._recorder = None
        self._chat_answer = None
        self._last_utterance = ""
        self._workers: set = set()          # 并行生成：每个话轮独立 worker
        self._last_history: list = []       # 最近完成的问答上下文（供后续生成继承）
        self._listen_buffer = None          # 监听转写缓冲（启动监听时创建）
        self.subtitle_sig.connect(self._on_subtitle)
        self.audio_error_sig.connect(self._on_audio_error)
        self._worker = None
        self._pipeline = None
        self._load_worker = None
        self._pending_build = None
        self.bridge = None
        self.tray = None
        self._hidden = False
        self._dl_worker = None
        self._started_without_models = False
        self._model_text = "model: 未下载"
        self.setWindowTitle("voxov")
        self.resize(1120, 760)
        self._build_ui()
        self._reload_kb()

    # ---- UI ----
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        nav = QWidget()
        nav.setObjectName("nav")
        nav_lay = QHBoxLayout(nav)
        nav_lay.setContentsMargins(28, 0, 28, 0)
        nav_lay.setSpacing(24)
        self._stack = QStackedWidget()
        self.chat_page = ChatPage(self)
        self._page_kb = self._build_kb_page()
        self.settings_page = SettingsPage(self.cfg, set_status=self.set_status)
        self._pages: dict[str, tuple[QPushButton, QWidget]] = {}
        for key, label, widget in (("listen", "监听", self.chat_page),
                                   ("kb", "知识库", self._page_kb),
                                   ("settings", "设置", self.settings_page)):
            btn = QPushButton(label)
            btn.setObjectName("nav_tab")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.switch_page(k))
            nav_lay.addWidget(btn)
            self._pages[key] = (btn, widget)
            self._stack.addWidget(widget)
        root.addWidget(nav)
        root.addWidget(self._stack, 1)

        footer = QWidget()
        footer.setObjectName("statusline")
        f_lay = QHBoxLayout(footer)
        f_lay.setContentsMargins(14, 4, 14, 4)
        self.status_info = QLabel("")
        self.status_info.setObjectName("status_info")
        self.status_msg = QLabel("")
        self.status_msg.setObjectName("status_msg")
        f_lay.addWidget(self.status_info)
        f_lay.addStretch(1)
        f_lay.addWidget(self.status_msg)
        root.addWidget(footer)
        self._status_timer = QTimer(self, singleShot=True, interval=4000)
        self._status_timer.timeout.connect(lambda: self.status_msg.setText(""))

        self.start_btn = self.chat_page.start_btn
        self.model_status_label = self.settings_page.model_state   # 既有引用别名
        self.start_btn.clicked.connect(self.start_listening)
        self.settings_page.download_requested.connect(self._start_download)
        self.settings_page.saved.connect(self._apply_settings)
        self.switch_page("listen")
        self._refresh_status_info()

    def switch_page(self, key: str) -> None:
        for k, (btn, _) in self._pages.items():
            btn.setChecked(k == key)
        self._stack.setCurrentWidget(self._pages[key][1])
        if key == "settings":
            self.settings_page.refresh_models_state(
                downloading=self._dl_worker is not None and self._dl_worker.isRunning())

    def open_settings(self) -> None:
        self.show()
        self.switch_page("settings")

    def _apply_settings(self) -> None:
        """审查 I3：设置保存后立即生效。并行架构下每次生成都按当前 cfg 新建
        LLMClient（工厂闭包读 cfg），此处只需重绑热键 + 刷新状态行。"""
        self.rebind_hotkeys()
        self._refresh_status_info()

    def rebind_hotkeys(self) -> None:
        """审查 I3c/I4：按当前配置重建全局热键；非法组合回退默认，绝不崩溃。
        注册成败必须可见（dist 里热键静默失效曾无从排查）。"""
        from app.hotkey import HotkeyBridge
        if self.bridge is not None:
            self.bridge.stop()
        try:
            nb = HotkeyBridge(self.cfg.hotkey, self.cfg.hide_hotkey)
        except Exception as exc:
            self.set_status(f"热键注册失败（{exc}），已回退默认组合", "error")
            nb = HotkeyBridge("ctrl+alt+space", "ctrl+alt+h")
        nb.pressed.connect(self._on_hotkey)
        nb.hidden.connect(self._on_hide)
        self.bridge = nb
        if nb.errors:
            self.set_status(f"热键部分注册失败：{'；'.join(nb.errors)}", "warn", hold=8000)
        else:
            self.set_status(f"热键已注册：{self.cfg.hotkey}（触发） / "
                            f"{self.cfg.hide_hotkey}（急隐藏）", "info", hold=6000)

    def reveal(self) -> None:
        """第二次启动唤起 / 从急隐藏找回：窗口+托盘一并恢复并前置。"""
        self._hidden = False
        self.setVisible(True)
        if self.tray is not None:
            self.tray.setVisible(True)
        self.raise_()
        self.activateWindow()

    def set_status(self, text: str, kind: str = "info", hold: int = 4000) -> None:
        self.status_msg.setStyleSheet(f"color: {STATUS_COLOR.get(kind, STATUS_COLOR['info'])};")
        self.status_msg.setText(text)
        self._status_timer.start(hold)

    def _refresh_status_info(self) -> None:
        n = len(self._kb_factory().list_files())
        build = ""
        if getattr(sys, "frozen", False):
            import datetime
            mt = datetime.datetime.fromtimestamp(os.path.getmtime(sys.executable))
            build = f" · build {mt:%m-%d %H:%M}"
        self.status_info.setText(
            f"{self._model_text} · kb: {n} 文件 · hotkey: {self.cfg.hotkey}{build}")

    def _build_kb_page(self) -> QWidget:
        from PySide6.QtWidgets import QFrame
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 20, 28, 20)
        lay.setSpacing(12)
        head = QHBoxLayout()
        for text, icon_name, handler in (("上传", "upload", self._upload),
                                         ("删除", "trash", self._delete_selected),
                                         ("导出", "download", self._export_session)):
            b = QPushButton(" " + text)
            b.setIcon(icon(icon_name))
            b.clicked.connect(handler)
            head.addWidget(b)
        head.addStretch(1)
        self.kb_count = QLabel("")
        self.kb_count.setObjectName("hint")
        head.addWidget(self.kb_count)
        lay.addLayout(head)
        line = QFrame()
        line.setObjectName("hline")
        line.setFixedHeight(1)
        lay.addWidget(line)
        self.kb_empty = QLabel("暂无文件 —— 上传 markdown 开始构建知识库")
        self.kb_empty.setObjectName("hint")
        lay.addWidget(self.kb_empty)
        self.kb_table = QTableView()
        self.kb_model = QStandardItemModel(0, 2)
        self.kb_model.setHorizontalHeaderLabels(["文件", "块数"])
        self.kb_table.setModel(self.kb_model)
        self.kb_table.horizontalHeader().setStretchLastSection(True)
        self.kb_table.setEditTriggers(QTableView.NoEditTriggers)
        self.kb_table.setSelectionBehavior(QTableView.SelectRows)
        self.kb_table.setSelectionMode(QTableView.SingleSelection)
        self.kb_table.setShowGrid(False)
        self.kb_table.verticalHeader().hide()
        lay.addWidget(self.kb_table, 1)
        return page

    def _reload_kb(self) -> None:
        self.kb_model.setRowCount(0)
        files = self._kb_factory().list_files()
        for name, n in files:
            name_item = QStandardItem(name)
            name_item.setIcon(icon("file-text"))
            self.kb_model.appendRow([name_item, QStandardItem(str(n))])
        if hasattr(self, "kb_count"):
            blocks = sum(n for _, n in files)
            self.kb_count.setText(f"{len(files)} 文件 · {blocks} 块")
        self.kb_empty.setVisible(not files)   # 空态提示；表格保持（不隐藏）
        self._refresh_status_info()

    def _upload(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "选择 md 文件", "", "Markdown (*.md)")
        kb = self._kb_factory()
        bad = []
        for f in files:
            try:
                kb.ingest_file(Path(f))
            except ValueError as exc:
                bad.append(str(exc))
        self._reload_kb()
        if bad:
            self.set_status(f"导入失败：{bad[0]}", "error")
        elif files:
            self.set_status(f"已导入 {len(files)} 个文件", "ok")

    def _delete_selected(self) -> None:
        idx = self.kb_table.currentIndex()
        if not idx.isValid():
            return
        name = self.kb_model.item(idx.row(), 0).text()
        self._kb_factory().delete_file(name)
        self._reload_kb()
        self.set_status(f"已删除 {name}", "ok")

    def _export_session(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出面试记录", "", "Markdown (*.md)")
        if path and self._recorder is not None:
            p = self._recorder.export_markdown(Path(path))
            self.set_status(f"已导出 {p}", "ok")

    # ---- 下载（worker 持有在主窗；页面只展示） ----
    def maybe_auto_download(self) -> None:
        from core.downloader import models_ready
        if models_ready(self.cfg.models_dir):
            self._set_model_state("ok")
            return
        self._start_download()

    def _start_download(self) -> None:
        from app.workers import DownloadWorker
        if self._dl_worker is not None and self._dl_worker.isRunning():
            return
        w = DownloadWorker(self.cfg.models_dir)
        w.failed.connect(self._on_dl_failed)
        w.finished_ok.connect(self._on_dl_ok)
        w.progress.connect(self.settings_page.on_dl_progress)
        w.line.connect(self.settings_page.on_dl_line)
        self._dl_worker = w
        self._set_model_state("dl")
        w.start()

    def _on_dl_failed(self, msg: str) -> None:
        self._set_model_state("err")
        self.settings_page.on_dl_failed(msg)
        self.set_status(f"模型下载失败：{msg}", "error")

    def _on_dl_ok(self) -> None:
        self._set_model_state("ok")
        if self._started_without_models:
            self.set_status("模型已就绪 · 重启应用后启用语义检索", "ok")
        else:
            self.set_status("模型已就绪 · 语音识别可用", "ok")

    def _set_model_state(self, state: str) -> None:
        from core.downloader import models_ready
        if state == "dl":
            self._model_text = "model: 下载中"
            self.settings_page.on_dl_started()
        elif state == "err":
            self._model_text = "model: 下载失败"
            self.model_status_label.setText("下载失败")
        else:
            ok = state == "ok" and models_ready(self.cfg.models_dir)
            self._model_text = "model: 就绪" if ok else "model: 未下载"
            self.settings_page.refresh_models_state()
        self._refresh_status_info()

    def _on_hide(self) -> None:
        self._hidden = not self._hidden
        self.setVisible(not self._hidden)
        if self.tray is not None:
            self.tray.setVisible(not self._hidden)

    def shutdown(self) -> None:
        if self._pipeline is not None:
            self._pipeline.stop()
        if self.bridge is not None:
            self.bridge.stop()
        for wk in list(self._workers):
            if wk.isRunning():
                wk.wait(2000)
        if self._load_worker is not None and self._load_worker.isRunning():
            self._load_worker.wait(2000)
        if self._dl_worker is not None and self._dl_worker.isRunning():
            self._dl_worker.wait(2000)

    def quit_app(self) -> None:
        self.shutdown()
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # ---- 监听 ----
    def start_listening(self) -> None:
        if self._pipeline is not None:
            self._pipeline.stop()
            self._pipeline = None
            self.start_btn.setText(" 开始监听")
            self.start_btn.setIcon(icon("mic", "#5af78e"))
            self.set_status("已停止监听", "ok")
            return
        if self._load_worker is not None and self._load_worker.isRunning():
            return
        from core.downloader import models_ready
        if not models_ready(self.cfg.models_dir):
            self.set_status("模型未就绪 · 已切到设置页", "warn")
            self.open_settings()
            self._start_download()
            return
        from core.session import SessionBuffer
        self._listen_buffer = SessionBuffer()   # 转写缓冲归窗口：并行生成共享读取

        def build(tr):
            from core.capture import LiveAudioSource
            from core.pipeline import AudioPipeline
            from core.vad import make_silero_vad
            return AudioPipeline(LiveAudioSource(device_name=self.cfg.audio_device or None),
                                 tr, self._listen_buffer,
                                 recorder=self._recorder,
                                 vad=make_silero_vad(self.cfg.models_dir))

        self._load_and_start(build)

    def _load_and_start(self, build) -> None:
        from app.workers import LoadWorker
        self._pending_build = build
        self.start_btn.setText(" 加载模型中…")
        self.start_btn.setEnabled(False)
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
            self.start_btn.setText(" 停止监听")
            self.start_btn.setIcon(icon("square", "#f85149"))
            self.start_btn.setEnabled(True)
            self.switch_page("listen")
        except Exception as exc:
            self.set_status(f"启动失败：{exc}", "error")
            self.start_btn.setText(" 开始监听")
            self.start_btn.setEnabled(True)

    def _on_load_failed(self, msg: str) -> None:
        self.set_status(f"启动失败：{msg}", "error")
        self.start_btn.setText(" 开始监听")
        self.start_btn.setEnabled(True)

    def _on_audio_error(self, m: str) -> None:
        self._pipeline = None
        self.start_btn.setText(" 开始监听")
        self.start_btn.setIcon(icon("mic", "#5af78e"))
        self.start_btn.setEnabled(True)
        self.set_status(f"音频异常，已停止监听：{m}", "error")

    # ---- 热键 → 生成（并行）：每次触发独立 RagService + 独立回答气泡 ----
    def _on_hotkey(self) -> None:
        import time as _time
        from app.workers import GenerateWorker
        from core.session import extract_turn
        if self._pipeline is not None:
            self._pipeline.flush_pending()
        # 话轮先在主线程提取：空话轮不建气泡、不启 worker——杜绝「正在生成…」僵尸
        turn = ""
        if self._listen_buffer is not None:
            turn = extract_turn(self._listen_buffer.entries, _time.time())
        if not turn:
            self.set_status("未识别到问题——请先开始监听，等对方说完再触发", "warn")
            return
        rag = self._rag_factory()
        rag.buffer = self._listen_buffer        # 与监听管线共用转写缓冲
        rag.history = list(self._last_history)  # 继承已完成问答的上下文
        rag.pending_turn = turn                 # 主线程提取的话轮直达 trigger
        self._chat_answer = self.chat_page.begin_answer()
        worker = GenerateWorker(rag)
        worker.question.connect(self._on_question)
        worker.chunk.connect(self._on_chunk)
        worker.notice.connect(self._on_notice)
        worker.missed.connect(self._on_missed)
        worker.failed.connect(self._on_generate_failed)
        worker.done.connect(lambda r=rag: self._remember_history(r))
        worker.finished.connect(lambda w=worker: self._workers.discard(w))
        self._workers.add(worker)
        self._worker = worker                   # 兼容别名：指向最新一个
        worker.start()

    def _remember_history(self, rag) -> None:
        self._last_history = list(getattr(rag, "history", []))

    def _on_subtitle(self, t: str) -> None:
        self.chat_page.add_interviewer(t)
        self._last_utterance = t
        if self.chat_page.auto_switch.isChecked():
            self._on_hotkey()          # 不过滤：全部话轮走知识库检索（用户指示）

    def _on_question(self, q: str) -> None:
        if not q and self._chat_answer is not None:
            self._chat_answer.note.setText("未识别到问题（稍后再按）")

    def _on_chunk(self, delta: str) -> None:
        if self._chat_answer is not None:
            self._chat_answer.append(delta)
            self.chat_page.scroll_to_bottom()

    def _on_missed(self, m: str) -> None:
        """未命中：气泡占位与标注替换为「知识库无对应内容」，不调 LLM。"""
        if self._chat_answer is not None:
            self._chat_answer.miss(m)

    def _on_generate_failed(self, m: str) -> None:
        self.set_status(f"生成失败：{m}", "error")
        if self._chat_answer is not None:
            self._chat_answer.fail(m)

    def _on_notice(self, m: str) -> None:
        if self._chat_answer is not None:
            self._chat_answer.note.setText(m)
