# app/icons.py —— Lucide（ISC）图标：QSvgRenderer 渲染、按 token 着色。
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from core.paths import assets_dir

ICON_DIR = assets_dir() / "icons"


@lru_cache(maxsize=None)
def _svg_for(name: str, color: str) -> str:
    path = ICON_DIR / f"{name}.svg"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").replace("currentColor", color)


@lru_cache(maxsize=None)
def icon(name: str, color: str = "#e6e6e6") -> QIcon:
    svg = _svg_for(name, color)
    if not svg:
        return QIcon()
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    renderer.render(p)
    p.end()
    return QIcon(pm)
