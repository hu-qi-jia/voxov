# app/theme.py —— 设计系统 v2：Codex 风格浅色（极简扁平、黑胶囊选中态、留白呼吸感）。
# 参考视觉：浅灰场 #f7f7f8 + 近黑文字 + 黑色胶囊主按钮/选中态 + 无描边侧栏。
TOKENS = {
    "bg":         "#ffffff",   # 内容场
    "field":      "#f7f7f8",   # 侧栏 / 应用底色
    "hover":      "#ececee",   # 悬停
    "active":     "#e9e9eb",   # 次级选中（列表行）
    "pill":       "#1a1a1a",   # 黑胶囊：主按钮 / 导航选中
    "pill_hover": "#333333",
    "border":     "#e5e5e7",   # 仅输入框/分隔用，侧栏无描边
    "text":       "#1a1a1a",
    "text_dim":   "#8e8e93",
    "ok":         "#0d8a5f",   # 功能色：仅状态（就绪/监听中）
    "warn":       "#b54708",   # 功能色：进行中
    "danger":     "#d92d20",
    "radius":     "10px",
    "radius_sm":  "8px",
    "font":       "'Segoe UI', 'Microsoft YaHei UI', 13px",
    "font_sm":    "'Segoe UI', 'Microsoft YaHei UI', 12px",
}


def build_qss() -> str:
    t = TOKENS
    return f"""
    QMainWindow, QDialog {{ background: {t['bg']}; font: {t['font']}; }}
    QWidget {{ color: {t['text']}; font: {t['font']}; }}

    /* ---- 侧栏：无描边，浅灰场 ---- */
    QWidget#sidebar {{ background: {t['field']}; border: none; }}
    QLabel#side_title {{ font-size: 17px; font-weight: 600; padding: 4px 8px 10px; }}
    QPushButton#nav {{ background: transparent; border: none; border-radius: 999px;
        padding: 9px 14px; text-align: left; color: {t['text']}; }}
    QPushButton#nav:hover {{ background: {t['hover']}; }}
    QPushButton#nav:checked {{ background: {t['pill']}; color: #ffffff; }}
    QPushButton#side_small {{ background: transparent; border: none; color: {t['text_dim']};
        padding: 7px 14px; text-align: left; border-radius: 999px; }}
    QPushButton#side_small:hover {{ color: {t['text']}; background: {t['hover']}; }}
    QLabel#model_status {{ color: {t['text_dim']}; font: {t['font_sm']}; padding: 6px 14px; }}
    QLabel#model_status[state="ok"] {{ color: {t['ok']}; }}
    QLabel#model_status[state="dl"] {{ color: {t['warn']}; }}
    QLabel#model_status[state="err"] {{ color: {t['danger']}; }}

    /* ---- 内容页 ---- */
    QWidget#page {{ background: {t['bg']}; }}
    QLabel#hint {{ color: {t['text_dim']}; font: {t['font_sm']}; }}
    QLabel#subtitle {{ color: {t['text_dim']}; font: {t['font_sm']}; }}
    QLabel#question {{ color: {t['text']}; font-weight: 600; }}
    QLabel#status {{ color: {t['danger']}; font: {t['font_sm']}; }}

    /* ---- 按钮：黑胶囊主 CTA，次级幽灵 ---- */
    QPushButton {{ background: transparent; border: 1px solid {t['border']};
        border-radius: 999px; padding: 7px 16px; color: {t['text']}; }}
    QPushButton:hover {{ background: {t['hover']}; }}
    QPushButton:pressed {{ background: {t['active']}; }}
    QPushButton:disabled {{ color: {t['text_dim']}; border-color: {t['border']};
        background: transparent; }}
    QPushButton[accent="true"] {{ background: {t['pill']}; border: none; color: #ffffff;
        padding: 8px 20px; font-weight: 600; }}
    QPushButton[accent="true"]:hover {{ background: {t['pill_hover']}; }}
    QPushButton[accent="true"]:disabled {{ background: {t['hover']}; color: {t['text_dim']}; }}

    /* ---- 输入/表格 ---- */
    QLineEdit, QComboBox {{ background: {t['bg']}; border: 1px solid {t['border']};
        border-radius: {t['radius_sm']}; padding: 7px 10px;
        selection-background-color: {t['pill']}; selection-color: #ffffff; }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {t['text']}; }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {t['text_dim']}; }}
    QTableView {{ background: {t['bg']}; border: none; gridline-color: transparent; }}
    QTableView::item {{ padding: 8px; border-bottom: 1px solid {t['border']}; }}
    QTableView::item:selected {{ background: {t['active']}; color: {t['text']}; }}
    QHeaderView::section {{ background: transparent; border: none;
        border-bottom: 1px solid {t['border']}; padding: 8px; color: {t['text_dim']};
        font: {t['font_sm']}; }}

    /* ---- 悬浮窗：浅色圆角卡片 ---- */
    QWidget#overlay {{ background: {t['field']}; border: 1px solid {t['border']};
        border-radius: 12px; }}
    QTextBrowser#answer, QTextEdit#subtitle_view {{ background: {t['bg']};
        border: 1px solid {t['border']}; border-radius: {t['radius']}; padding: 8px; }}
    QToolButton#overlay_close {{ background: transparent; border: none;
        color: {t['text_dim']}; font-size: 14px; border-radius: 999px; padding: 2px 8px; }}
    QToolButton#overlay_close:hover {{ background: {t['hover']}; color: {t['text']}; }}

    QMenu {{ background: {t['bg']}; border: 1px solid {t['border']};
        border-radius: {t['radius_sm']}; }}
    QMenu::item {{ padding: 6px 20px; }}
    QMenu::item:selected {{ background: {t['hover']}; }}
    QStatusBar {{ background: {t['field']}; color: {t['text_dim']}; font: {t['font_sm']}; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """


def apply(app) -> None:
    app.setStyleSheet(build_qss())
