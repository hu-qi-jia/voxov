# tests/test_theme.py —— DSH 暗色设计系统（VoxRecall 同源）：令牌齐全、QSS 覆盖核心控件
from app.theme import TOKENS, build_qss


def test_tokens_complete():
    need = {"bg", "layer1", "layer2", "layer3", "border", "text", "text_dim",
            "accent", "ok", "warn", "danger", "radius", "font"}
    assert need <= set(TOKENS)


def test_dsh_dark_palette():
    # VoxRecall/DSH：950 底 + 分层面板 + 蓝强调
    assert TOKENS["bg"] == "#151517"
    assert TOKENS["layer1"] == "#232324"
    assert TOKENS["layer3"] == "#353638"
    assert TOKENS["accent"] == "#7aaaff"


def test_qss_covers_core_widgets_and_states():
    qss = build_qss()
    for sel in ("QMainWindow", "QDialog", "QLabel#bubble_role", "QLabel#bubble_avatar",
                "QLabel#bubble_note", "QTextBrowser#answer", "QWidget#feed",
                "QPushButton[accent=\"true\"]"):
        assert sel in qss, f"QSS 缺少 {sel}"
