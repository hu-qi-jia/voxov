# app/tray.py
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def create_tray(win) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(QIcon(), parent=win)  # TODO(Task 18): 换真实图标
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
