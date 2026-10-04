# app/settings_dialog.py —— 全部配置集中于此（spec §6.7）；主窗口仅"设置"入口。
from pathlib import Path

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from core.config import AppConfig, save_config


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("设置")
        self.setMinimumWidth(520)
        form = QFormLayout()

        # LLM
        self.base_url_edit = QLineEdit(cfg.llm_base_url)
        self.api_key_edit = QLineEdit(cfg.llm_api_key)
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.model_edit = QLineEdit(cfg.llm_model)
        form.addRow("Base URL", self.base_url_edit)
        form.addRow("API Key", self.api_key_edit)
        form.addRow("模型", self.model_edit)

        # 目录
        self.models_dir_edit = QLineEdit(str(cfg.models_dir))
        self.data_dir_edit = QLineEdit(str(cfg.data_dir))
        for edit, title in ((self.models_dir_edit, "模型目录"), (self.data_dir_edit, "数据目录")):
            row = QHBoxLayout()
            row.addWidget(edit)
            pick = QPushButton("…")
            pick.setFixedWidth(32)
            pick.clicked.connect(lambda _=False, e=edit, t=title: self._pick_dir(e, t))
            row.addWidget(pick)
            wrap = QWidget()
            wrap.setLayout(row)
            form.addRow(title, wrap)

        # 热键
        self.hotkey_edit = QLineEdit(cfg.hotkey)
        self.hide_hotkey_edit = QLineEdit(cfg.hide_hotkey)
        form.addRow("触发热键", self.hotkey_edit)
        form.addRow("急隐藏热键", self.hide_hotkey_edit)

        # 音频设备
        self.device_combo = QComboBox()
        self._load_devices()
        form.addRow("音频设备", self.device_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

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

    def _pick_dir(self, edit: QLineEdit, title: str) -> None:
        d = QFileDialog.getExistingDirectory(self, title, edit.text() or str(Path.home()))
        if d:
            edit.setText(d)

    def _save(self) -> None:
        hotkey = self.hotkey_edit.text().strip() or "ctrl+alt+space"
        hide_hotkey = self.hide_hotkey_edit.text().strip() or "ctrl+alt+h"
        # 审查 I4：非法热键一旦落盘，下次启动即崩——保存前校验并拒绝
        for label, text in (("触发热键", hotkey), ("急隐藏热键", hide_hotkey)):
            try:
                import keyboard
                keyboard.parse_hotkey(text)
            except Exception:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "热键无效", f"无法识别的{label}：{text}")
                return
        self.cfg.llm_base_url = self.base_url_edit.text().strip()
        self.cfg.llm_api_key = self.api_key_edit.text().strip()
        self.cfg.llm_model = self.model_edit.text().strip()
        self.cfg.models_dir = Path(self.models_dir_edit.text())
        self.cfg.data_dir = Path(self.data_dir_edit.text())
        self.cfg.hotkey = hotkey
        self.cfg.hide_hotkey = hide_hotkey
        self.cfg.audio_device = self.device_combo.currentData() or ""
        save_config(self.cfg)
        self.accept()
