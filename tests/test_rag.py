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

# --- 路由（spec §5）：statement 不检索；距离阈值；FTS 越过；Hash 降级 ---
from core.retriever import Retrieved

def _feed(svc, text, sec_ago=6):
    now = time.time()
    svc.buffer.add_transcript(TranscriptEntry(now - sec_ago - 2, now - sec_ago, text))

def test_statement_turn_skips_retrieval():
    calls = {"retrieve": 0}
    class R:
        distances_reliable = False
        last_top_distance = None
        def retrieve(self, q, k=5):
            calls["retrieve"] += 1
            return []
    llm = FakeLLM()
    svc = RagService(R(), llm)
    _feed(svc, "我们团队主要做 ToB 业务")
    out = "".join(svc.trigger())
    assert calls["retrieve"] == 0 and len(llm.calls) == 1
    assert svc.last_notice == "接话 · 未用资料"
    assert "RDB" in out

def test_open_turn_without_refs_notices_open(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb.db", HashEmbedder(dim=512))
    svc = RagService(Retriever(kb, HashEmbedder(dim=512)), FakeLLM())
    _feed(svc, "介绍一下你的项目经历")
    "".join(svc.trigger())
    assert svc.last_notice == "开放题 · 未用资料"

class FakeRetriever:
    def __init__(self, contexts, reliable=True, top=0.9):
        self._c = contexts
        self.distances_reliable = reliable
        self.last_top_distance = top
    def retrieve(self, q, k=5):
        return self._c

_REF = Retrieved(chunk_id=1, text="RDB 定时快照 AOF 追加日志", heading_path="Redis",
                 source_file="redis.md", score=-1)

def test_reliable_distance_within_threshold_uses_refs():
    # 0.92 < d ≤ 0.95：预设带之外、refs 带之内 → 正常走 LLM
    svc = RagService(FakeRetriever([_REF], reliable=True, top=0.93), FakeLLM())
    _feed(svc, "RDB持久化怎么做的")
    "".join(svc.trigger())
    assert svc.last_notice == "基于知识库 · 1 条资料"
    assert svc.last_had_refs is True

def test_reliable_distance_over_threshold_falls_to_generic():
    # 原计划喂「…是啥样的」：经实测 classify_turn 判为 statement（不检索），
    # 距离阈值分支根本不会执行——改一个字（啥→怎）使其为 question 类，意图不变。
    svc = RagService(FakeRetriever([_REF], reliable=True, top=1.3), FakeLLM())
    _feed(svc, "TCP三次握手详细过程是怎样的")
    "".join(svc.trigger())
    assert svc.last_notice == "通用回答（知识库无命中）"
    assert svc.last_had_refs is False

def test_fts_four_char_hit_overrides_distance():
    ctx = Retrieved(chunk_id=2, text="项目经历应当用 STAR 法则组织", heading_path="h",
                    source_file="s.md", score=-1)
    svc = RagService(FakeRetriever([ctx], reliable=True, top=1.3), FakeLLM())
    _feed(svc, "介绍一下你的项目经历")
    "".join(svc.trigger())
    assert svc.last_notice == "基于知识库 · 1 条资料"   # ≥4 字词项「项目经历」子串命中

def test_hash_embedder_keeps_legacy_behavior():
    svc = RagService(FakeRetriever([_REF], reliable=False, top=None), FakeLLM())
    _feed(svc, "RDB持久化怎么做的")
    "".join(svc.trigger())
    assert svc.last_had_refs is True                    # 有结果即注入（降级旧行为）

def test_question_no_hits_keeps_legacy_notice(tmp_path):
    # 裁决 1：空 KB 的提问话轮不注入资料仍生成，标注沿用旧文案；
    # 分类在 question/chatter 间漂移均为合法（双合法值断言），不设死变量。
    kb = KnowledgeBase(tmp_path / "kb.db", HashEmbedder(dim=512))
    svc = RagService(Retriever(kb, HashEmbedder(dim=512)), FakeLLM())
    _feed(svc, "讲讲TCP握手")
    "".join(svc.trigger())
    assert svc.last_notice in ("通用回答（知识库无命中）", "接话 · 未用资料")
    assert len(svc.llm.calls) == 1


def test_space_mismatch_disables_vector_distance():
    """空间错配（库由其他嵌入模型构建）：距离信号不可信，走 FTS 兜底。"""
    ctx = Retrieved(chunk_id=2, text="项目经历应当用 STAR 法则组织", heading_path="h",
                    source_file="s.md", score=-1)
    r = FakeRetriever([ctx], reliable=True, top=1.3)
    r.space_mismatch = True
    svc = RagService(r, FakeLLM())
    _feed(svc, "介绍一下你的项目经历")
    "".join(svc.trigger())
    assert svc.last_notice == "基于知识库 · 1 条资料"    # FTS 越过兜底仍可用


# --- 预设问答直出：余弦≥0.7（L2≤0.775）→ 跳过 LLM 直接展示库内答案 ---
def test_preset_qa_direct_hit_skips_llm():
    ctx = Retrieved(chunk_id=3, text="问：介绍下你的项目经历\n答：主导过日千万级缓存重构",
                    heading_path="预设问答", source_file="qa.md", score=-1)
    llm = FakeLLM()
    svc = RagService(FakeRetriever([ctx], reliable=True, top=0.6), llm)
    _feed(svc, "介绍一下你的项目经历")
    out = "".join(svc.trigger())
    assert out == "问：介绍下你的项目经历\n答：主导过日千万级缓存重构"
    assert llm.calls == []                              # LLM 完全不介入
    assert svc.last_notice.startswith("命中预设问答 · 相似度 0.")

def test_above_refs_band_falls_to_generic():
    svc = RagService(FakeRetriever([_REF], reliable=True, top=1.05), FakeLLM())
    _feed(svc, "RDB持久化怎么做的")
    "".join(svc.trigger())
    assert svc.last_notice == "通用回答（知识库无命中）"
    assert svc.last_had_refs is False

def test_preset_direct_hit_disabled_when_space_mismatch():
    ctx = Retrieved(chunk_id=3, text="问：项目经历\n答：略", heading_path="h",
                    source_file="s.md", score=-1)
    llm = FakeLLM()
    r = FakeRetriever([ctx], reliable=True, top=0.5)
    r.space_mismatch = True                             # 距离不可信：不允许直出
    svc = RagService(r, llm)
    _feed(svc, "介绍一下你的项目经历")
    "".join(svc.trigger())
    assert len(llm.calls) == 1                          # 回落正常生成
