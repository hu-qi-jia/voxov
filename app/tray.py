# app/tray.py
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from core.config import app_root
from core.paths import assets_dir


def create_tray(win) -> QSystemTrayIcon:
    icon_path = assets_dir() / "icon.png"          # PNG：Qt 核心支持，无插件依赖
    if not icon_path.exists():                     # 开发环境兜底（SVG 可用）
        icon_path = assets_dir() / "icon.svg"
    tray = QSystemTrayIcon(QIcon(str(icon_path)) if icon_path.exists() else QIcon(),
                           parent=win)
    menu = QMenu()
    show = QAction("显示主窗口", win)
    show.triggered.connect(win.show)
    settings_act = QAction("设置", win)
    settings_act.triggered.connect(win.open_settings)
    quit_ = QAction("退出", win)
    quit_.triggered.connect(win.quit_app)  # 审查 I2：真正退出（清理热钩/管线），非仅关窗
    menu.addAction(show)
    menu.addAction(settings_act)
    menu.addAction(quit_)
    tray.setContextMenu(menu)
    tray.setToolTip("Notes")   # 对外中性 tooltip（spec §6.5）
    tray.show()
    return tray
