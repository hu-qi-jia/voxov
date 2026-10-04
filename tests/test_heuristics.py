# tests/test_heuristics.py —— 自动作答触发启发式
from core.heuristics import looks_like_question


def test_question_mark_always_triggers():
    assert looks_like_question("讲讲 Redis 持久化？")
    assert looks_like_question("what is RDB?")


def test_chinese_question_words_trigger():
    for t in ("说说 MySQL 索引", "介绍一下你的项目", "Redis 和 Memcached 的区别",
              "为什么要用消息队列"):
        assert looks_like_question(t), t


def test_smalltalk_does_not_trigger():
    assert not looks_like_question("好的")
    assert not looks_like_question("嗯嗯，明白")
    assert not looks_like_question("")


def test_too_long_monologue_does_not_trigger():
    assert not looks_like_question("长" * 300)
