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


# --- 全话轮分类（路由 spec §4 矩阵） ---
from core.heuristics import classify_turn

def test_spec_matrix():
    cases = {
        "嗯好的": "chatter",
        "那我们继续下一题": "chatter",
        "好的我们了解一下": "chatter",
        "你了解 Redis 吗": "question",
        "介绍一下你的项目经历": "open",
        "讲讲你的职业规划": "open",
        "Redis 持久化怎么做的": "question",
        "我们团队主要做 ToB 业务": "statement",
    }
    for text, want in cases.items():
        assert classify_turn(text) == want, (text, classify_turn(text))

def test_empty_and_punctuation_are_chatter():
    assert classify_turn("") == "chatter"
    assert classify_turn("。。。！？") == "chatter"
    assert classify_turn(None) == "chatter"

def test_chatter_words_do_not_kill_short_tech_sentence():
    assert classify_turn("我们继续看看Redis持久化") == "question"

def test_long_statement_falls_through():
    assert classify_turn("我们这个团队这两年一直在做云端协同方向的产品落地") == "statement"

def test_leading_chatter_does_not_swallow_real_question():
    assert classify_turn("好的那你讲讲Redis持久化") == "question"
    assert classify_turn("行，那你介绍一下TCP") == "question"

def test_single_char_chatter_words_do_not_substring_shave():
    assert classify_turn("我们继续运行下去") == "question"
