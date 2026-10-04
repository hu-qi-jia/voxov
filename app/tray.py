# app/tray.py
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from core.config import app_root


def create_tray(win) -> QSystemTrayIcon:
    icon_path = app_root() / "assets" / "icon.svg"  # 相对应用根解析，不依赖 CWD
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
