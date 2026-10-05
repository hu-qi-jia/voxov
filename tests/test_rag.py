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


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _feed_question(svc):
    _feed(svc, "请介绍Redis持久化")


# --- 基本链路 ---
def test_title_hit_single_section_direct_output(service):
    """标题直配单节命中：答案原文直出，不调 LLM（检索为主）。"""
    svc, llm, rec = service
    _feed_question(svc)
    out = "".join(svc.trigger())
    assert "RDB" in out                             # 整节原文（含持久化子树）
    assert svc.last_question.startswith("请介绍Redis")
    assert llm.calls == []                          # 直出：零 LLM
    assert svc.last_notice.startswith("知识库原文")
    assert svc.last_missed is False
    assert len(rec.turns) == 1
    assert rec.turns[0].answer == out


def test_history_grows_for_followup(tmp_path):
    """跨节命中走 LLM：历史上下文随问随传。"""
    kb = KnowledgeBase(tmp_path / "kb.db", HashEmbedder(dim=512))
    doc = "# 项目\n\n### Alpha\n\nA 部分内容。\n\n### Beta\n\nB 部分内容。\n"
    kb.ingest_file(_write(tmp_path, "ab.md", doc))
    llm = FakeLLM()
    svc = RagService(Retriever(kb, HashEmbedder(dim=512)), llm)
    _feed(svc, "Alpha 和 Beta 都讲讲")
    list(svc.trigger())
    _feed(svc, "Alpha 和 Beta 再展开讲讲", sec_ago=3)
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


# --- 兜底路：距离闸 / FTS 越过 / 降级 / 空间错配（经正文向量，命中扩节后同样直出） ---
def test_unreliable_retriever_nonempty_hits(service):
    """Hash/降级（距离不可信）：有结果即命中。"""
    svc, llm, _ = service
    _feed_question(svc)
    "".join(svc.trigger())
    assert "知识库原文" in svc.last_notice
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
    out = "".join(svc.trigger())
    assert svc.last_missed is False              # ≥4 字词项「项目经历」越过阈值
    assert "STAR" in out                         # 单材料直出：不再强制走 LLM
    assert llm.calls == []


def test_space_mismatch_falls_back_to_fts():
    ctx = Retrieved(chunk_id=2, text="项目经历应当用 STAR 法则组织", heading_path="h",
                    source_file="s.md", score=-1)
    r = FakeRetriever([ctx], reliable=True, top=1.3)
    r.space_mismatch = True                      # 距离不可信：向量路弃用
    llm = FakeLLM()
    svc = RagService(r, llm)
    _feed(svc, "介绍一下你的项目经历")
    out = "".join(svc.trigger())
    assert svc.last_missed is False              # FTS 越过仍可用
    assert "STAR" in out


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
    assert "已整理 2 节" in svc.last_notice
    assert "RDB" in out


# --- 哨兵：命中但资料不足以回答，模型明说「[无法回答]」→ 等同未命中 ---
class PieceLLM:
    """按给定分片流式输出（哨兵/普通回答两用）。"""
    def __init__(self, pieces):
        self.pieces = pieces
        self.calls = []
    def stream(self, messages, temperature=0.3, max_tokens=None):
        self.calls.append(messages)
        yield from self.pieces


def _svc_with_llm(tmp_path, llm):
    """强制走 LLM 缝合路：双材料（跨节）。"""
    c1 = _REF
    c2 = Retrieved(chunk_id=2, text="AOF 是追加日志", heading_path="Redis/AOF",
                   source_file="redis.md", score=-2)
    rec = SessionRecorder()
    svc = RagService(FakeRetriever([c1, c2], reliable=False, top=0.8), llm, recorder=rec)
    _feed_question(svc)
    return svc, rec


def test_no_answer_sentinel_treated_as_miss(tmp_path):
    """哨兵被流式扣留，零内容外流；等同未命中：不入历史、不记 QA。"""
    llm = PieceLLM(["[无法", "回答]"])
    svc, rec = _svc_with_llm(tmp_path, llm)
    outs = list(svc.trigger())
    assert outs == [""]                      # 哨兵没有外流
    assert svc.last_missed is True
    assert svc.last_notice == "知识库无对应内容"
    assert svc.history == [] and rec.turns == []

def test_no_answer_sentinel_with_punctuation(tmp_path):
    """哨兵后跟标点（模型不听话）：仍是「明说答不了」。"""
    llm = PieceLLM(["[无法回答]，"])
    svc, rec = _svc_with_llm(tmp_path, llm)
    # 标点破坏了扣留，哨兵本体放行过；随后的 "" 是 no-answer 收尾信号（worker 跳过）
    assert list(svc.trigger()) == ["[无法回答]，", ""]
    assert svc.last_missed is True and rec.turns == []

def test_sentinel_prefix_in_real_answer_passes_through(tmp_path):
    """回答正文以哨兵开头但后面有实质内容：正常展示，不当未命中。"""
    llm = PieceLLM(["[无法回答]，", "但资料里有：RDB 是快照。"])
    svc, rec = _svc_with_llm(tmp_path, llm)
    outs = list(svc.trigger())
    assert "".join(outs) == "[无法回答]，但资料里有：RDB 是快照。"
    assert svc.last_missed is False
    assert len(rec.turns) == 1

def test_normal_answer_not_delayed_by_holdback(tmp_path):
    """普通回答首片即与哨兵不匹配：立即放行，无扣留时延。"""
    llm = PieceLLM(["**RDB** 是快照。"])
    svc, _ = _svc_with_llm(tmp_path, llm)
    assert list(svc.trigger()) == ["**RDB** 是快照。"]
    assert svc.last_missed is False

# --- 材料封顶：尾部整块丢弃，不切半截 ---
def test_cap_materials_drops_tail_whole():
    from core.generator import cap_materials
    ctxs = [Retrieved(i, "x" * 3000, "h", "f.md", -i) for i in (1, 2, 3)]
    capped = cap_materials(ctxs)
    assert [c.chunk_id for c in capped] == [1]      # 第二块放不下：整块丢弃

def test_cap_materials_keeps_oversized_first_block():
    from core.generator import cap_materials
    ctxs = [Retrieved(1, "y" * 9999, "h", "f.md", -1),
            Retrieved(2, "z", "h", "f.md", -2)]
    assert [c.chunk_id for c in cap_materials(ctxs)] == [1]
