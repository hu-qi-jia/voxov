# tests/test_prompt.py —— 整理式 prompt（二元路由 v3：命中即整理，禁编造）
from core.generator import SYNTH_PROMPT, build_messages
from core.retriever import Retrieved

CTX = [Retrieved(1, "RDB 是快照", "Redis/持久化", "redis.md", -1.0)]

def test_synth_prompt_locks_key_constraints():
    assert "真实资料" in SYNTH_PROMPT
    assert "整理合并" in SYNTH_PROMPT
    assert "禁止编造" in SYNTH_PROMPT          # 零幻觉约束必须在提示词里

def test_messages_structure():
    msgs = build_messages("RDB是什么", CTX, [])
    assert msgs[0]["role"] == "system" and msgs[0]["content"] == SYNTH_PROMPT
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
    assert "资料" not in msgs[1]["content"]
    assert msgs[0]["content"] == SYNTH_PROMPT
