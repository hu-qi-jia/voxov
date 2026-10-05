# app/tray.py
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from core.config import app_root
from core.paths import assets_dir


def create_tray(win) -> QSystemTrayIcon:
    icon_path = assets_dir() / "voxov_logo.png"    # voxov 反白字形（透明底，暗色托盘可读）
    if not icon_path.exists():                     # 兜底：旧资源 → SVG
        icon_path = assets_dir() / "icon.png"
    if not icon_path.exists():
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
    tray.setToolTip("voxov")   # 托盘提示（对外名）
    tray.show()
    return tray
