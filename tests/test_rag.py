# tests/test_rag.py —— 二元路由：检索命中→LLM 整理展示；未命中→知识库无对应内容
import time

import pytest
from core.embedder import HashEmbedder
from core.kb import KnowledgeBase
from core.rag import RagService
from core.retriever import Retriever, Retrieved
from core.session import SessionRecorder, TranscriptEntry

DOC = "# Redis\n\n## 持久化\n\nRDB 定时快照，AOF 追加日志。\n"

_REF = Retrieved(chunk_id=1, text="RDB 定时快照 AOF 追加日志", heading_path="Redis",
                 source_file="redis.md", score=-1)


class FakeLLM:
    def __init__(self):
        self.calls = []

    def stream(self, messages, temperature=0.3, max_tokens=None):
        self.calls.append(messages)
        yield "**RDB** 是快照。"
        yield "**AOF** 是日志。"


class FakeRetriever:
    def __init__(self, contexts, reliable=True, top=0.9):
        self._c = contexts
        self.distances_reliable = reliable
        self.last_top_distance = top
        self.last_distances = {c.chunk_id: top for c in contexts}
        self.space_mismatch = False

    def retrieve(self, q, k=5):
        return self._c


def _mk_service(tmp_path, retriever, llm):
    kb = KnowledgeBase(tmp_path / "kb.db", HashEmbedder(dim=512))
    p = tmp_path / "redis.md"
    p.write_text(DOC, encoding="utf-8")
    kb.ingest_file(p)
    rec = SessionRecorder()
    return RagService(retriever, llm, recorder=rec), llm, rec


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


def _feed(svc, text, sec_ago=6):
    now = time.time()
    svc.buffer.add_transcript(TranscriptEntry(now - sec_ago - 2, now - sec_ago, text))


def _feed_question(svc):
    _feed(svc, "请介绍Redis持久化")


# --- 基本链路 ---
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
    _feed(svc, "那数据量大了怎么办", sec_ago=3)
    list(svc.trigger())
    assert len(llm.calls) == 2
    assert "之前的问题" in llm.calls[1][1]["content"]


def test_empty_turn_short_circuits(service):
    svc, llm, rec = service                      # 缓冲为空
    out = list(svc.trigger())
    assert out == [""]
    assert llm.calls == [] and rec.turns == []
    assert svc.last_missed is True


def test_kb_empty_misses_without_llm(tmp_path):
    """未命中（空库）：显示「知识库无对应内容」，不调 LLM。"""
    kb = KnowledgeBase(tmp_path / "kb.db", HashEmbedder(dim=512))
    llm = FakeLLM()
    svc = RagService(Retriever(kb, HashEmbedder(dim=512)), llm)
    _feed(svc, "讲讲TCP握手")
    out = "".join(svc.trigger())
    assert out == ""
    assert llm.calls == []
    assert svc.last_notice == "知识库无对应内容"
    assert svc.last_missed is True


# --- 二元路由：距离闸 / FTS 越过 / 降级 / 空间错配 ---
def test_unreliable_retriever_nonempty_hits(service):
    """Hash/降级（距离不可信）：有结果即命中（旧行为）。"""
    svc, llm, _ = service
    _feed_question(svc)
    "".join(svc.trigger())
    assert "已整理" in svc.last_notice
    assert svc.last_missed is False


def test_reliable_distance_over_gate_misses():
    llm = FakeLLM()
    svc = RagService(FakeRetriever([_REF], reliable=True, top=1.3), llm)
    _feed(svc, "TCP三次握手详细过程是怎样的")
    "".join(svc.trigger())
    assert svc.last_notice == "知识库无对应内容"
    assert svc.last_missed is True
    assert llm.calls == []                       # 未命中不调 LLM


def test_fts_four_char_hit_overrides_gate():
    ctx = Retrieved(chunk_id=2, text="项目经历应当用 STAR 法则组织", heading_path="h",
                    source_file="s.md", score=-1)
    llm = FakeLLM()
    svc = RagService(FakeRetriever([ctx], reliable=True, top=1.3), llm)
    _feed(svc, "介绍一下你的项目经历")
    "".join(svc.trigger())
    assert svc.last_notice == "基于知识库 · 已整理 1 段资料"   # ≥4 字词项「项目经历」越过阈值
    assert len(llm.calls) == 1


def test_space_mismatch_falls_back_to_fts():
    ctx = Retrieved(chunk_id=2, text="项目经历应当用 STAR 法则组织", heading_path="h",
                    source_file="s.md", score=-1)
    r = FakeRetriever([ctx], reliable=True, top=1.3)
    r.space_mismatch = True                      # 距离不可信：向量路弃用
    llm = FakeLLM()
    svc = RagService(r, llm)
    _feed(svc, "介绍一下你的项目经历")
    "".join(svc.trigger())
    assert svc.last_notice == "基于知识库 · 已整理 1 段资料"   # FTS 越过仍可用
    assert len(llm.calls) == 1


# --- 素材整理：命中带内全部 chunk 进 prompt，LLM 只做整理合并（禁编造） ---
def test_synthesis_collects_all_materials():
    c1 = Retrieved(chunk_id=3, text="答：主导过日千万级缓存重构", heading_path="项目",
                   source_file="qa.md", score=-1)
    c2 = Retrieved(chunk_id=4, text="答：本地协议签约 9w+", heading_path="企业客户",
                   source_file="qa.md", score=-1)
    llm = FakeLLM()
    r = FakeRetriever([c1, c2], reliable=True, top=0.6)
    r.last_distances = {3: 0.6, 4: 0.65}
    svc = RagService(r, llm)
    _feed(svc, "介绍一下你的项目经历")
    out = "".join(svc.trigger())
    assert len(llm.calls) == 1
    sys_msg = llm.calls[0][0]["content"]
    user_msg = llm.calls[0][1]["content"]
    assert "真实资料" in sys_msg and "禁止编造" in sys_msg
    assert "缓存重构" in user_msg and "9w+" in user_msg   # 带内素材全部入 prompt
    assert "已整理 2 段" in svc.last_notice
    assert "RDB" in out
