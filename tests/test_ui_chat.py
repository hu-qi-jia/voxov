# tests/test_ui_chat.py —— 滚动跟随：新问题必跟最新一条；流式增长钉底；上翻不拽回。
import pytest
from PySide6.QtCore import Qt

from app.ui_chat import AnswerTurn, ChatPage


@pytest.fixture
def page(qtbot):
    w = ChatPage()
    qtbot.addWidget(w)
    w.resize(420, 260)   # 视口小：几条就溢出
    w.show()
    return w


def _drain(qtbot):
    qtbot.wait(30)       # singleShot(0) 的补滚与布局实排都要事件循环


def _settle_bottom(page, qtbot):
    """等布局实排完且已钉底（word-wrap 高度是惰性计算的，一轮事件未必够）。"""
    sb = page.scroll.verticalScrollBar()
    qtbot.waitUntil(lambda: sb.maximum() > 300 and sb.value() == sb.maximum(),
                    timeout=5000)


def test_new_question_follows_latest(page, qtbot):
    """新问题到达：无论之前滚到哪里，视图必须跟到最新一条。"""
    for i in range(20):
        page.add_interviewer(f"问题{i}，" + "内容足够长需要换行换行换行换行换行。" * 3)
    _settle_bottom(page, qtbot)
    sb = page.scroll.verticalScrollBar()
    assert sb.value() == sb.maximum()          # 旧实现：插入时高度未实排，滚不到底


def test_streaming_growth_stays_pinned(page, qtbot):
    """钉底状态下流式增高（refit）：视图持续跟随，不飘走。"""
    for i in range(15):
        page.add_interviewer(f"填充{i}，" + "占位占位占位占位占位占位。" * 4)
    page.begin_answer()
    _settle_bottom(page, qtbot)
    b = page.feed_lay.itemAt(page.feed_lay.count() - 2).widget()
    assert isinstance(b, AnswerTurn)
    for _ in range(5):
        b.append("更多内容" * 60)               # 触发 refit 增高
        _drain(qtbot)
    sb = page.scroll.verticalScrollBar()
    assert sb.value() == sb.maximum()


def test_scroll_up_unpins_until_new_question(page, qtbot):
    """用户上翻阅读：流式增长不得拽回底部；新问题到达才重新跟随。"""
    for i in range(15):
        page.add_interviewer(f"填充{i}，" + "占位占位占位占位占位占位。" * 4)
    b = page.begin_answer()
    _settle_bottom(page, qtbot)
    sb = page.scroll.verticalScrollBar()
    sb.setValue(sb.maximum() - 500)            # 模拟上翻
    _drain(qtbot)
    assert page._pinned is False
    for _ in range(3):
        b.append("增长" * 80)
        _drain(qtbot)
        assert sb.value() < sb.maximum()       # 未被拽回
    page.add_interviewer("下一个新问题")
    _drain(qtbot)
    assert sb.value() == sb.maximum()          # 新问题重新跟随
    assert page._pinned is True
