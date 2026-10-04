# tests/test_prompt.py
from core.generator import SYSTEM_PROMPT, build_messages
from core.retriever import Retrieved

CTX = [Retrieved(1, "RDB 是快照", "Redis/持久化", "redis.md", -1.0)]

def test_system_prompt_verbatim():
    assert SYSTEM_PROMPT == ("你是面试实时辅助。输出口语化中文，像求职者当场回答，可直接照读，"
        "禁止书面腔和套话开场。分点输出，每点一句完整的话，关键词加粗。按重要性排序，"
        "最重要的点放第一条。共 4-6 点，全篇不超过 250 字。优先使用参考资料，资料不足时用自身知识。")

def test_messages_structure():
    msgs = build_messages("RDB是什么", CTX, [])
    assert msgs[0]["role"] == "system" and msgs[0]["content"] == SYSTEM_PROMPT
    assert msgs[1]["role"] == "user"
    assert "[资料1]" in msgs[1]["content"] and "redis.md" in msgs[1]["content"]
    assert "当前问题：RDB是什么" in msgs[1]["content"]

def test_history_last_two_only():
    history = [(f"q{i}", f"a{i}") for i in range(5)]
    msgs = build_messages("q", CTX, history)
    assert "q3" in msgs[1]["content"] and "q4" in msgs[1]["content"]
    assert "q1" not in msgs[1]["content"]

def test_empty_contexts_omit_refs_section():
    msgs = build_messages("q", [], [])
    assert "参考资料" not in msgs[1]["content"]
