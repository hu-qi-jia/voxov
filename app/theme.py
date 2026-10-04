# app/theme.py —— 设计系统 v4：retro terminal 暗色。
# 近黑底 / 磷光绿强调 / 1px 直线 / 等宽字栈；禁圆角、阴影、渐变。
TOKENS = {
    "bg":        "#0a0a0a",
    "bg_raise":  "#111111",
    "bg_hover":  "#151515",
    "fg":        "#e6e6e6",
    "fg_dim":    "#9a9a9a",
    "fg_faint":  "#5c5c5c",
    "line":      "#2a2a2a",
    "line_soft": "#1e1e1e",
    "accent":    "#5af78e",
    "warn":      "#e3b341",
    "danger":    "#f85149",
    "font":      "'Cascadia Mono', 'Consolas', 'Microsoft YaHei UI', monospace",
}


def build_qss() -> str:
    t = TOKENS
    return f"""
    QMainWindow, QDialog {{ background: {t['bg']}; }}
    QWidget {{ color: {t['fg']}; font-family: {t['font']}; font-size: 13px; }}
    QLabel {{ background: transparent; }}
    QLabel#hint, QLabel#turn_note, QLabel#dl_log {{ color: {t['fg_faint']};
        font-size: 12px; }}
    QLabel#turn_q {{ color: {t['fg_dim']}; }}
    QLabel#sec_title {{ color: {t['fg_dim']}; }}
    QLabel#status_info {{ color: {t['fg_faint']}; font-size: 12px; }}
    QLabel#status_msg {{ font-size: 12px; }}

    /* ---- 按钮：方角 1px 边框；accent=磷光绿描边 ---- */
    QPushButton {{ background: transparent; border: 1px solid {t['line']};
        padding: 6px 16px; color: {t['fg']}; }}
    QPushButton:hover {{ background: {t['bg_hover']}; border-color: {t['fg_dim']}; }}
    QPushButton:pressed {{ background: {t['bg_raise']}; }}
    QPushButton:disabled {{ color: {t['fg_faint']}; border-color: {t['line_soft']}; }}
    QPushButton[accent="true"] {{ border-color: {t['accent']}; color: {t['accent']}; }}
    QPushButton[accent="true"]:hover {{ background: rgba(90, 247, 142, 0.06); }}
    QPushButton[accent="true"]:disabled {{ color: {t['fg_faint']};
        border-color: {t['line_soft']}; }}
    QPushButton#nav_tab {{ border: none; border-bottom: 2px solid transparent;
        color: {t['fg_dim']}; padding: 12px 2px 10px; border-radius: 0; }}
    QPushButton#nav_tab:hover {{ background: transparent; color: {t['fg']}; }}
    QPushButton#nav_tab:checked {{ color: {t['fg']};
        border-bottom: 2px solid {t['accent']}; }}

    /* ---- 输入：方角、bg_raise 底、focus 绿框 ---- */
    QLineEdit, QComboBox {{ background: {t['bg_raise']}; border: 1px solid {t['line']};
        padding: 6px 10px; color: {t['fg']}; selection-background-color: {t['accent']}; }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {t['accent']}; }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {t['fg_faint']}; }}
    QComboBox QAbstractItemView {{ background: {t['bg_raise']};
        border: 1px solid {t['line']}; selection-background-color: {t['bg_hover']}; }}

    /* ---- 复选：方框 + 内实心方块（checked） ---- */
    QCheckBox {{ spacing: 8px; color: {t['fg']}; }}
    QCheckBox::indicator {{ width: 13px; height: 13px;
        border: 1px solid {t['fg_dim']}; background: transparent; }}
    QCheckBox::indicator:hover {{ border-color: {t['fg']}; }}
    QCheckBox::indicator:checked {{ background: {t['accent']};
        border: 1px solid {t['fg_dim']}; }}

    /* ---- 表格：无竖线、行间 1px、整行反白选中 ---- */
    QTableView {{ background: transparent; border: none; gridline-color: transparent;
        selection-background-color: {t['fg']}; selection-color: {t['bg']}; }}
    QTableView::item {{ padding: 10px 12px; border-bottom: 1px solid {t['line_soft']}; }}
    QTableView::item:selected {{ background: {t['fg']}; color: {t['bg']}; }}
    QHeaderView::section {{ background: transparent; border: none;
        border-bottom: 1px solid {t['line']}; padding: 8px 12px;
        color: {t['fg_faint']}; font-size: 12px; }}

    /* ---- 进度条：平面 ---- */
    QProgressBar {{ background: {t['bg_raise']}; border: 1px solid {t['line']};
        height: 10px; text-align: center; color: transparent; }}
    QProgressBar::chunk {{ background: {t['accent']}; }}

    /* ---- 对话流 / 状态行 ---- */
    QWidget#feed {{ background: {t['bg']}; }}
    QTextBrowser#answer {{ background: transparent; border: none; color: {t['fg']}; }}
    QWidget#statusline {{ border-top: 1px solid {t['line']}; background: {t['bg']}; }}
    QWidget#nav {{ border-bottom: 1px solid {t['line']}; background: {t['bg']}; }}
    QFrame#hline {{ background: {t['line_soft']}; max-height: 1px; border: none; }}

    QMenu {{ background: {t['bg_raise']}; border: 1px solid {t['line']}; }}
    QMenu::item {{ padding: 6px 20px; }}
    QMenu::item:selected {{ background: {t['bg_hover']}; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; }}
    QScrollBar::handle:vertical {{ background: {t['line']}; }}
    QScrollBar::handle:vertical:hover {{ background: {t['fg_faint']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """


def apply(app) -> None:
    from PySide6.QtGui import QFont
    f = QFont()
    f.setFamilies(["Cascadia Mono", "Consolas", "Microsoft YaHei UI"])
    f.setStyleHint(QFont.Monospace)
    f.setLetterSpacing(QFont.AbsoluteSpacing, 0.5)
    app.setFont(f)
    app.setStyleSheet(build_qss())
