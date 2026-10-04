# app/settings_page.py —— 设置页（窗口内，替代设置弹窗+下载向导）。
# 直线分节：语音模型（下载）/ 大模型 / 热键 / 音频与目录；保存统一落盘。
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from core.config import AppConfig, save_config
from core.downloader import models_ready

from app.icons import icon


def _sep() -> QFrame:
    f = QFrame()
    f.setObjectName("hline")
    f.setFixedHeight(1)
    return f


class SettingsPage(QWidget):
    download_requested = Signal()

    def __init__(self, cfg: AppConfig, set_status, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._set_status = set_status
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)

        # -- 语音模型 --
        root.addWidget(QLabel("# 语音模型"))
        row = QHBoxLayout()
        self.model_state = QLabel("")
        self.model_state.setObjectName("model_status")
        row.addWidget(self.model_state)
        row.addStretch(1)
        self.dl_btn = QPushButton(" 下载模型")
        self.dl_btn.setIcon(icon("download", "#5af78e"))
        self.dl_btn.clicked.connect(self.download_requested.emit)
        row.addWidget(self.dl_btn)
        root.addLayout(row)
        self.progress = QProgressBar()
        self.progress.hide()
        root.addWidget(self.progress)
        self.dl_log = QLabel("")
        self.dl_log.setObjectName("dl_log")
        self.dl_log.hide()
        root.addWidget(self.dl_log)
        root.addWidget(_sep())

        # -- 大模型 --
        root.addWidget(QLabel("# 大模型"))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        self.base_url_edit = QLineEdit(cfg.llm_base_url)
        self.api_key_edit = QLineEdit(cfg.llm_api_key)
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.model_edit = QLineEdit(cfg.llm_model)
        form.addRow("base url", self.base_url_edit)
        form.addRow("api key", self.api_key_edit)
        form.addRow("模型", self.model_edit)
        root.addLayout(form)
        root.addWidget(_sep())

        # -- 热键 --
        root.addWidget(QLabel("# 热键"))
        form2 = QFormLayout()
        self.hotkey_edit = QLineEdit(cfg.hotkey)
        self.hide_hotkey_edit = QLineEdit(cfg.hide_hotkey)
        form2.addRow("触发", self.hotkey_edit)
        form2.addRow("急隐藏", self.hide_hotkey_edit)
        root.addLayout(form2)
        root.addWidget(_sep())

        # -- 音频与目录 --
        root.addWidget(QLabel("# 音频与目录"))
        form3 = QFormLayout()
        self.device_combo = QComboBox()
        self._load_devices()
        form3.addRow("音频设备", self.device_combo)
        self.models_dir_edit = QLineEdit(str(cfg.models_dir))
        self.data_dir_edit = QLineEdit(str(cfg.data_dir))
        form3.addRow("模型目录", self.models_dir_edit)
        hint = QLabel("语音识别与向量检索模型统一存放于此")
        hint.setObjectName("hint")
        form3.addRow("", hint)
        form3.addRow("数据目录", self.data_dir_edit)
        root.addLayout(form3)

        root.addStretch(1)
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.save_btn = QPushButton(" 保存")
        self.save_btn.setIcon(icon("save", "#5af78e"))
        self.save_btn.setProperty("accent", True)
        self.save_btn.clicked.connect(self._on_save_clicked)
        save_row.addWidget(self.save_btn)
        root.addLayout(save_row)

        self.refresh_models_state()

    # ---- 保存 ----
    def _on_save_clicked(self) -> None:
        if self.save():
            self._set_status("设置已保存", "ok")

    def save(self) -> bool:
        hotkey = self.hotkey_edit.text().strip() or "ctrl+alt+space"
        hide = self.hide_hotkey_edit.text().strip() or "ctrl+alt+h"
        import keyboard
        for label, text in (("触发热键", hotkey), ("急隐藏热键", hide)):
            try:
                keyboard.parse_hotkey(text)
            except Exception:
                self._set_status(f"热键无效：{label} {text}", "error")
                return False
        self.cfg.llm_base_url = self.base_url_edit.text().strip()
        self.cfg.llm_api_key = self.api_key_edit.text().strip()
        self.cfg.llm_model = self.model_edit.text().strip()
        self.cfg.models_dir = Path(self.models_dir_edit.text())
        self.cfg.data_dir = Path(self.data_dir_edit.text())
        self.cfg.hotkey = hotkey
        self.cfg.hide_hotkey = hide
        self.cfg.audio_device = self.device_combo.currentData() or ""
        save_config(self.cfg)
        return True

    # ---- 下载状态（worker 由主窗持有，页面只展示） ----
    def refresh_models_state(self) -> None:
        ok = models_ready(self.cfg.models_dir)
        self.model_state.setText("已就绪 · sherpa-onnx + bge" if ok else "未下载")
        self.dl_btn.setText(" 重新下载" if ok else " 下载模型")
        self.dl_btn.setEnabled(True)
        self.progress.hide()
        self.dl_log.hide()

    def on_dl_started(self) -> None:
        self.dl_btn.setText(" 下载中…")
        self.dl_btn.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.dl_log.show()

    def on_dl_progress(self, p: float) -> None:
        self.progress.setValue(int(p * 100))

    def on_dl_line(self, m: str) -> None:
        self.dl_log.setText(m)

    def on_dl_failed(self, msg: str) -> None:
        self.dl_log.setText(f"下载失败：{msg}（点重新下载续传）")
        self.dl_btn.setText(" 重新下载")
        self.dl_btn.setEnabled(True)

    def on_dl_ok(self) -> None:
        self.refresh_models_state()

    def _load_devices(self) -> None:
        self.device_combo.addItem("系统默认", "")
        try:
            from core.capture import list_loopback_devices
            for d in list_loopback_devices():
                label = d["name"] + ("（默认）" if d.get("default") else "")
                self.device_combo.addItem(label, d["name"])
        except Exception:
            pass  # 无音频环境仅保留"系统默认"
        idx = self.device_combo.findData(self.cfg.audio_device)
        self.device_combo.setCurrentIndex(idx if idx >= 0 else 0)
