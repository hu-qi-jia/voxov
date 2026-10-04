# tests/test_rag.py
import time
import pytest
from core.embedder import HashEmbedder
from core.kb import KnowledgeBase
from core.rag import RagService
from core.retriever import Retriever
from core.session import SessionRecorder, TranscriptEntry

DOC = "# Redis\n\n## 持久化\n\nRDB 定时快照，AOF 追加日志。\n"

class FakeLLM:
    def __init__(self):
        self.calls = []
    def stream(self, messages, temperature=0.3, max_tokens=500):
        self.calls.append(messages)
        yield "**RDB** 是快照。"
        yield "**AOF** 是日志。"

@pytest.fixture
def service(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb.db", HashEmbedder(dim=512))
    p = tmp_path / "redis.md"
    p.write_text(DOC, encoding="utf-8")
    kb.ingest_file(p)
    llm = FakeLLM()
    rec = SessionRecorder()
    svc = RagService(Retriever(kb, HashEmbedder(dim=512)), llm, recorder=rec)
    return svc, llm, rec

def _feed_question(svc):
    now = time.time()
    svc.buffer.add_transcript(TranscriptEntry(now - 10, now - 6, "请介绍Redis持久化"))

def test_trigger_streams_answer_and_records(service):
    svc, llm, rec = service
    _feed_question(svc)
    out = "".join(svc.trigger())
    assert "RDB" in out
    assert svc.last_question.startswith("请介绍Redis")
    assert len(llm.calls) == 1
    assert len(rec.turns) == 1
    assert rec.turns[0].answer == out

def test_history_grows_for_followup(service):
    svc, llm, _ = service
    _feed_question(svc)
    list(svc.trigger())
    now = time.time()
    svc.buffer.add_transcript(TranscriptEntry(now - 8, now - 4, "那数据量大了怎么办"))
    list(svc.trigger())
    assert len(llm.calls) == 2
    assert "之前的问题" in llm.calls[1][1]["content"]

def test_empty_question_short_circuits_llm(service):
    svc, llm, rec = service  # 缓冲为空
    out = list(svc.trigger())
    assert out == [""]  # 空问题 → 单个空串信号，UI 层显示提示
    assert llm.calls == [] and rec.turns == []

def test_kb_empty_still_calls_llm(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb.db", HashEmbedder(dim=512))
    llm = FakeLLM()
    svc = RagService(Retriever(kb, HashEmbedder(dim=512)), llm)
    now = time.time()
    svc.buffer.add_transcript(TranscriptEntry(now - 5, now - 1, "讲讲TCP握手"))
    out = "".join(svc.trigger())
    assert "RDB" in out and len(llm.calls) == 1  # 无检索片段仍生成
