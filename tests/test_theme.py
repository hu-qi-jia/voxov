# tests/test_theme.py —— retro terminal 设计系统：tokens 齐全、暗色取值、QSS 覆盖核心控件
from app.theme import TOKENS, build_qss


def test_tokens_complete():
    need = {"bg", "bg_raise", "bg_hover", "fg", "fg_dim", "fg_faint",
            "line", "line_soft", "accent", "warn", "danger", "font"}
    assert need <= set(TOKENS)


def test_terminal_dark_values():
    assert TOKENS["bg"] == "#0a0a0a"
    assert TOKENS["fg"] == "#e6e6e6"
    assert TOKENS["accent"] == "#5af78e"
    assert TOKENS["line"] == "#2a2a2a"
    assert TOKENS["danger"] == "#f85149"


def test_font_stack_is_mono():
    assert "Cascadia Mono" in TOKENS["font"]
    assert "Microsoft YaHei UI" in TOKENS["font"]


def test_qss_covers_core_widgets_and_states():
    qss = build_qss()
    for sel in ("QMainWindow", "QPushButton", "QPushButton[accent=\"true\"]",
                "QLineEdit", "QComboBox", "QCheckBox::indicator:checked",
                "QProgressBar::chunk", "QTableView::item:selected",
                "QTextBrowser#answer", "QWidget#statusline", "QPushButton#nav_tab:checked"):
        assert sel in qss, f"QSS 缺少 {sel}"
