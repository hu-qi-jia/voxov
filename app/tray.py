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
    wizard = QAction("下载模型", win)
    wizard.triggered.connect(win._open_wizard)
    quit_ = QAction("退出", win)
    quit_.triggered.connect(win.close)
    menu.addAction(show)
    menu.addAction(wizard)
    menu.addAction(quit_)
    tray.setContextMenu(menu)
    tray.setToolTip("Notes")   # 对外中性 tooltip（spec §6.5）
    tray.show()
    return tray
