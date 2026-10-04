# app/theme.py —— 设计系统 v3：DSH 暗色（与 VoxRecall web 端同源的 DeepSeek Harness 令牌）。
# 分层面板（950 底 / 875·850 层）、白透明描边、蓝强调、绿=成功 橙=进行 红=错误。
TOKENS = {
    "bg":       "#151517",   # bg-base
    "layer1":   "#232324",   # AI 气泡 / 输入场
    "layer2":   "#2c2c2e",   # 卡片
    "layer3":   "#353638",   # 用户气泡 / 悬停
    "chrome":   "#1b1b1c",   # 侧栏
    "border":   "#2e2e30",   # 白 12% 的等效实色
    "text":     "#f9fafb",
    "text_dim": "#adb2b8",
    "text_faint": "#979da6",
    "accent":   "#7aaaff",   # 业务蓝
    "accent_deep": "#4176e6",
    "ok":       "#22c55e",
    "warn":     "#f59e0b",
    "danger":   "#f25a5a",
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

    QLabel#hint, QLabel#subtitle {{ color: {t['text_dim']}; font: {t['font_sm']}; }}
    QLabel#question {{ color: {t['text']}; font-weight: 600; }}

    /* ---- 按钮：DSH 主按钮白底黑字，次级描边 ---- */
    QPushButton {{ background: transparent; border: 1px solid {t['border']};
        border-radius: {t['radius']}; padding: 7px 16px; color: {t['text']}; }}
    QPushButton:hover {{ background: {t['layer2']}; }}
    QPushButton:pressed {{ background: {t['layer3']}; }}
    QPushButton:disabled {{ color: {t['text_faint']}; }}
    QPushButton[accent="true"] {{ background: {t['text']}; border: none; color: {t['bg']};
        padding: 8px 20px; font-weight: 600; }}
    QPushButton[accent="true"]:hover {{ background: #ffffff; }}
    QPushButton[accent="true"]:disabled {{ background: {t['layer2']};
        color: {t['text_faint']}; }}

    /* ---- 输入/表格 ---- */
    QLineEdit, QComboBox {{ background: {t['layer1']}; border: 1px solid {t['border']};
        border-radius: {t['radius_sm']}; padding: 7px 10px;
        selection-background-color: {t['accent_deep']}; }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {t['accent']}; }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {t['text_faint']}; }}
    QTableView {{ background: transparent; border: none; gridline-color: transparent; }}
    QTableView::item {{ padding: 8px; border-bottom: 1px solid {t['border']}; }}
    QTableView::item:selected {{ background: {t['layer3']}; }}
    QHeaderView::section {{ background: transparent; border: none;
        border-bottom: 1px solid {t['border']}; padding: 8px; color: {t['text_dim']};
        font: {t['font_sm']}; }}

    /* ---- 对话流 ---- */
    QWidget#feed {{ background: {t['bg']}; }}
    QTextBrowser#answer {{ background: transparent; border: none; color: {t['text']}; }}
    QLabel#bubble_role {{ color: {t['text_faint']}; font: {t['font_sm']};
        letter-spacing: 0.02em; }}
    QLabel#bubble_avatar {{ border-radius: 15px; font-size: 12px; font-weight: 600; }}
    QLabel#bubble_note {{ color: {t['warn']}; font: {t['font_sm']}; }}

    QMenu {{ background: {t['layer2']}; border: 1px solid {t['border']};
        border-radius: {t['radius_sm']}; }}
    QMenu::item {{ padding: 6px 20px; }}
    QMenu::item:selected {{ background: {t['layer3']}; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; }}
    QScrollBar::handle:vertical {{ background: {t['layer3']}; border-radius: 4px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """


def apply(app) -> None:
    app.setStyleSheet(build_qss())
