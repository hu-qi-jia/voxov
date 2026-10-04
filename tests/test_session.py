# tests/test_session.py
from core.session import TranscriptEntry, SessionBuffer, extract_question

def e(ts, dur, text):
    return TranscriptEntry(ts=ts, end_ts=ts + dur, text=text)

NOW = 100.0

def test_question_after_long_pause():
    entries = [e(90, 2.0, "你好，我是今天的面试官。"), e(96, 4.0, "请介绍一下Redis持久化的两种方式")]
    q = extract_question(entries, now=NOW)
    assert "面试官" not in q and "Redis持久化" in q

def test_includes_all_segments_after_boundary():
    entries = [e(90, 2.0, "你好。"), e(96, 3.0, "请介绍一下"), e(99.5, 3.0, "Redis的持久化")]
    q = extract_question(entries, now=NOW)
    assert "请介绍一下" in q and "Redis的持久化" in q

def test_no_boundary_takes_whole_window():
    entries = [e(95, 1.0, "那么"), e(96.2, 1.0, "请你"), e(97.4, 1.0, "介绍一下项目")]
    q = extract_question(entries, now=NOW)
    assert "介绍一下项目" in q and "那么" in q

def test_window_cutoff_30s():
    entries = [e(50, 2.0, "很久以前的寒暄。"), e(95, 3.0, "最近的问题")]
    q = extract_question(entries, now=NOW)
    assert "很久以前" not in q and "最近的问题" in q

def test_empty_entries_returns_empty():
    assert extract_question([], now=NOW) == ""

def test_pure_greeting_window_returns_it_anyway():
    # 30s 内只有寒暄且其后有长停顿——按 spec 规则返回寒暄本身，由 Task 10 层面交给 LLM 兜底
    entries = [e(90, 2.0, "麻烦做个自我介绍")]
    q = extract_question(entries, now=NOW)
    assert q == "麻烦做个自我介绍"

def test_session_buffer_append_and_clear():
    b = SessionBuffer()
    b.add_transcript(e(1, 1, "a"))
    b.add_transcript(e(3, 1, "b"))
    assert [x.text for x in b.entries] == ["a", "b"]
    b.clear()
    assert b.entries == []

def test_short_pause_not_boundary():
    entries = [e(96, 3.0, "请介绍一下"), e(99.6, 3.0, "主从复制")]  # gap 0.6s < 1.5s
    q = extract_question(entries, now=NOW)
    assert q == "请介绍一下主从复制"
