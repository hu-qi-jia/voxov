# app/theme.py —— 设计系统（spec §6.8）：唯一暗色主题，令牌集中，QSS 统一生成。
TOKENS = {
    "bg":             "#0d0f12",   # 窗体背景
    "surface":        "#16181d",   # 面板/输入框
    "elevated":       "#1e2127",   # 悬浮层/hover
    "border":         "#2a2d34",
    "text":           "#ececf1",
    "text_dim":       "#9aa0aa",
    "accent":         "#10a37f",   # 单一强调色
    "accent_hover":   "#0e8f6f",
    "accent_pressed": "#0c7f62",
    "danger":         "#ef4444",
    "radius":         "10px",
    "radius_sm":      "6px",
    "font":           "'Segoe UI', 'Microsoft YaHei UI', 13px",
    "font_sm":        "'Segoe UI', 'Microsoft YaHei UI', 12px",
}


def build_qss() -> str:
    t = TOKENS
    return f"""
    QMainWindow, QDialog {{ background: {t['bg']}; font: {t['font']}; }}
    QWidget {{ color: {t['text']}; font: {t['font']}; }}
    QLabel#subtitle {{ color: {t['text_dim']}; font: {t['font_sm']}; }}
    QLabel#question {{ color: {t['text']}; font-weight: 600; }}
    QLabel#status {{ color: {t['danger']}; font: {t['font_sm']}; }}
    QWidget#overlay {{ background: {t['surface']}; border: 1px solid {t['border']};
        border-radius: {t['radius']}; }}
    QTextBrowser#answer {{ background: {t['elevated']}; border: none;
        border-radius: {t['radius_sm']}; padding: 8px; }}
    QLineEdit, QComboBox {{ background: {t['surface']}; border: 1px solid {t['border']};
        border-radius: {t['radius_sm']}; padding: 6px 8px;
        selection-background-color: {t['accent']}; }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {t['accent']}; }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {t['text_dim']}; }}
    QPushButton {{ background: {t['surface']}; border: 1px solid {t['border']};
        border-radius: {t['radius_sm']}; padding: 7px 14px; color: {t['text']}; }}
    QPushButton:hover {{ background: {t['elevated']}; }}
    QPushButton:pressed {{ background: {t['border']}; }}
    QPushButton:disabled {{ color: {t['text_dim']}; background: {t['bg']}; }}
    QPushButton[accent="true"] {{ background: {t['accent']}; border: none; color: #ffffff; }}
    QPushButton[accent="true"]:hover {{ background: {t['accent_hover']}; }}
    QPushButton[accent="true"]:pressed {{ background: {t['accent_pressed']}; }}
    QTableView {{ background: {t['surface']}; border: 1px solid {t['border']};
        border-radius: {t['radius']}; gridline-color: {t['border']}; }}
    QTableView::item {{ padding: 6px; }}
    QTableView::item:selected {{ background: {t['accent']}; color: #ffffff; }}
    QHeaderView::section {{ background: {t['elevated']}; border: none;
        border-bottom: 1px solid {t['border']}; padding: 6px; color: {t['text_dim']}; }}
    QMenu {{ background: {t['surface']}; border: 1px solid {t['border']};
        border-radius: {t['radius_sm']}; }}
    QMenu::item {{ padding: 6px 20px; }}
    QMenu::item:selected {{ background: {t['elevated']}; }}
    QWidget#sidebar {{ background: {t['surface']}; border-right: 1px solid {t['border']}; }}
    QLabel#side_title {{ font-size: 16px; font-weight: 600; padding: 2px 6px 8px; }}
    QPushButton#nav {{ background: transparent; border: none; border-radius: {t['radius_sm']};
        padding: 9px 12px; text-align: left; color: {t['text_dim']}; }}
    QPushButton#nav:hover {{ background: {t['elevated']}; color: {t['text']}; }}
    QPushButton#nav:checked {{ background: {t['elevated']}; color: {t['accent']};
        font-weight: 600; }}
    QPushButton#side_small {{ background: transparent; border: none; color: {t['text_dim']};
        padding: 6px 8px; text-align: left; }}
    QPushButton#side_small:hover {{ color: {t['text']}; background: {t['elevated']};
        border-radius: {t['radius_sm']}; }}
    QLabel#model_status {{ color: {t['text_dim']}; font: {t['font_sm']}; padding: 4px 8px; }}
    QLabel#model_status[state="ok"] {{ color: {t['accent']}; }}
    QLabel#model_status[state="dl"] {{ color: {t['text']}; }}
    QLabel#model_status[state="err"] {{ color: {t['danger']}; }}
    QLabel#hint {{ color: {t['text_dim']}; font: {t['font_sm']}; }}
    QWidget#page {{ background: {t['bg']}; }}
    QTextEdit#subtitle_view {{ background: {t['surface']}; border: 1px solid {t['border']};
        border-radius: {t['radius']}; padding: 8px; color: {t['text_dim']}; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; }}
    """


def apply(app) -> None:
    app.setStyleSheet(build_qss())
