# tests/test_theme.py —— Codex 浅色设计系统：令牌齐全、QSS 覆盖核心控件
from app.theme import TOKENS, build_qss


def test_tokens_complete():
    need = {"bg", "field", "hover", "active", "pill", "border", "text",
            "text_dim", "ok", "danger", "radius", "font"}
    assert need <= set(TOKENS)


def test_light_theme_pill_is_near_black():
    # Codex 参考图：黑胶囊选中态 + 浅色场
    assert TOKENS["pill"] == "#1a1a1a"
    assert TOKENS["field"] == "#f7f7f8"


def test_qss_covers_core_widgets_and_states():
    qss = build_qss()
    for sel in ("QMainWindow", "QDialog", "QLabel#subtitle", "QLabel#question",
                "QLabel#status", "QTextBrowser#answer", "QWidget#overlay",
                "QWidget#sidebar", "QPushButton#nav", "QToolButton#overlay_close",
                "QLabel#model_status[state=\"ok\"]"):
        assert sel in qss, f"QSS 缺少 {sel}"
