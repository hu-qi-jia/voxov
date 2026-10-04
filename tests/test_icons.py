# tests/test_icons.py —— Lucide 图标加载与着色
# 注：icon() 内构造 QPixmap，Qt 规定须先有 QGuiApplication（否则进程直接 abort），
# 故借用 pytest-qt 的 qapp fixture（项目 dev 依赖）。
def test_icon_known_name_renders_non_null(qapp):
    from app.icons import icon
    assert not icon("mic").isNull()

def test_icon_unknown_name_returns_null_without_raise(qapp):
    from app.icons import icon
    assert icon("no-such-icon").isNull()

def test_icon_color_applied():
    from app.icons import _svg_for
    assert "#5af78e" in _svg_for("mic", "#5af78e")
    assert "currentColor" not in _svg_for("mic", "#5af78e")
