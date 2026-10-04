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

# --- 三模式（路由 spec §6） ---
from core.generator import GENERIC_PROMPT, STATEMENT_PROMPT

def test_generic_mode_swaps_system_and_drops_refs():
    msgs = build_messages("介绍一下你的项目", CTX, [], mode="generic")
    assert msgs[0]["content"] == GENERIC_PROMPT
    assert "参考资料" not in msgs[1]["content"]
    assert "当前问题：介绍一下你的项目" in msgs[1]["content"]

def test_generic_prompt_forbids_fabricated_refs():
    assert "禁止" in GENERIC_PROMPT and "资料" in GENERIC_PROMPT

def test_statement_mode_uses_speaker_label():
    msgs = build_messages("我们团队主要做 ToB 业务", [], [], mode="statement")
    assert msgs[0]["content"] == STATEMENT_PROMPT
    assert "当前面试官发言：我们团队主要做 ToB 业务" in msgs[1]["content"]
    assert "参考资料" not in msgs[1]["content"]

def test_refs_mode_is_default_and_unchanged():
    msgs = build_messages("RDB是什么", CTX, [])
    assert msgs[0]["content"] == SYSTEM_PROMPT
    assert "[资料1]" in msgs[1]["content"]
