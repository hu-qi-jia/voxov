# tests/test_theme.py
from app.theme import TOKENS, build_qss

def test_tokens_complete():
    need = {"bg", "surface", "elevated", "border", "text", "text_dim",
            "accent", "danger", "radius", "font"}
    assert need <= set(TOKENS)

def test_qss_covers_core_widgets_and_states():
    qss = build_qss()
    for sel in ("QMainWindow", "QDialog", "QLabel#subtitle", "QLabel#question",
                "QLabel#status", "QTextBrowser#answer", "QWidget#overlay",
                "QPushButton", "QLineEdit", "QComboBox", "QTableView", "QMenu"):
        assert sel in qss
    for state in (":hover", ":pressed", ":disabled", ":focus"):
        assert state in qss
