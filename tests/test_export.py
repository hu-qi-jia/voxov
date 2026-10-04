# tests/test_export.py
from pathlib import Path
from core.session import SessionRecorder, TranscriptEntry
from core.retriever import Retrieved

def test_export_contains_turns_and_sources(tmp_path):
    r = SessionRecorder()
    r.add_transcript(TranscriptEntry(ts=1.0, end_ts=2.0, text="面试官说"))
    r.add_qa("Redis持久化方式", [Retrieved(1, "RDB 是快照", "Redis/持久化", "redis.md", -1.0)], "RDB 和 AOF 两种。")
    out = tmp_path / "record.md"
    p = r.export_markdown(out)
    text = p.read_text(encoding="utf-8")
    assert "# 面试记录" in text
    assert "## 问" in text and "Redis持久化方式" in text
    assert "RDB 和 AOF 两种。" in text
    assert "redis.md › Redis/持久化" in text
    assert "面试官说" in text  # 转写也导出

def test_export_empty_session_still_writes(tmp_path):
    p = SessionRecorder().export_markdown(tmp_path / "r.md")
    assert p.exists()
