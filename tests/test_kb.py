# tests/test_kb.py
from pathlib import Path
import pytest
from core.embedder import HashEmbedder
from core.kb import KnowledgeBase

DOC = """# Redis

## 持久化

RDB 是定时快照，SAVE 命令阻塞主线程，BGSAVEfork 子进程执行。

## 主从复制

主节点写，从节点读，replication 是异步的。
"""

@pytest.fixture
def kb(tmp_path):
    return KnowledgeBase(tmp_path / "kb.db", HashEmbedder(dim=512))

def _write(tmp_path, name, text=DOC):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p

def test_ingest_returns_chunk_count(kb, tmp_path):
    n = kb.ingest_file(_write(tmp_path, "redis.md"))
    assert n >= 2

def test_reingest_same_file_replaces_old_chunks(kb, tmp_path):
    kb.ingest_file(_write(tmp_path, "redis.md"))
    kb.ingest_file(_write(tmp_path, "redis.md", "# New\n\n完全不同的内容。\n"))
    files = dict(kb.list_files())
    assert files["redis.md"] == 1

def test_delete_file(kb, tmp_path):
    kb.ingest_file(_write(tmp_path, "redis.md"))
    assert kb.delete_file("redis.md") >= 1
    assert kb.list_files() == []

def test_empty_file_raises(kb, tmp_path):
    with pytest.raises(ValueError):
        kb.ingest_file(_write(tmp_path, "empty.md", ""))

def test_vector_search_returns_ids(kb, tmp_path):
    kb.ingest_file(_write(tmp_path, "redis.md"))
    q, = HashEmbedder(dim=512).encode(["主从复制"])
    hits = kb.vector_search(q, k=2)
    assert 1 <= len(hits) <= 2 and all(isinstance(i, int) for i, _ in hits)

def test_fts_search_chinese_substring(kb, tmp_path):
    kb.ingest_file(_write(tmp_path, "redis.md"))
    hits = kb.fts_search("定时快照", k=5)
    assert len(hits) >= 1
    rows = kb.get_chunks(hits)
    assert any("RDB" in r[1] for r in rows)

def test_fts_search_english_term(kb, tmp_path):
    kb.ingest_file(_write(tmp_path, "redis.md"))
    hits = kb.fts_search("SAVE", k=5)
    assert len(hits) >= 1

def test_fts_search_no_match_returns_empty(kb, tmp_path):
    kb.ingest_file(_write(tmp_path, "redis.md"))
    assert kb.fts_search("量子纠缠", k=5) == []

def test_get_chunks_returns_metadata(kb, tmp_path):
    kb.ingest_file(_write(tmp_path, "redis.md"))
    hits = kb.fts_search("定时快照", k=5)
    rows = kb.get_chunks(hits)
    rid, text, heading, source = rows[0]
    assert source == "redis.md" and heading.startswith("Redis")

# --- 审查修复轮 ---
import threading

def test_kb_usable_from_worker_thread(kb, tmp_path):
    # 审查 C1：连接在主线程建、GenerateWorker 线程检索 → 不得抛 ProgrammingError
    kb.ingest_file(_write(tmp_path, "redis.md"))
    errs: list[Exception] = []
    def work():
        try:
            q, = HashEmbedder(dim=512).encode(["主从复制"])
            kb.vector_search(q, k=2)
            kb.fts_search("定时快照", k=2)
            kb.list_files()
        except Exception as e:
            errs.append(e)
    t = threading.Thread(target=work)
    t.start(); t.join()
    assert errs == []

def test_fts_search_matches_terms_not_whole_phrase(kb, tmp_path):
    # 审查 I5：整句短语匹配对真实问题失效，应按词项 OR 命中
    kb.ingest_file(_write(tmp_path, "mvcc.md",
        "# MVCC\n\nInnoDB 通过 MVCC 实现快照读，undo log 支持回滚。\n"))
    hits = kb.fts_search("MVCC 是什么", k=5)
    assert len(hits) >= 1
    rows = kb.get_chunks(hits)
    assert any("MVCC" in r[1] for r in rows)


# --- 嵌入空间指纹：跨空间污染防护 + 自愈重嵌 ---
def test_space_mismatch_detected_after_embedder_change(tmp_path):
    from core.embedder import OnnxEmbedder
    kb = KnowledgeBase(tmp_path / "kb.db", HashEmbedder(dim=512))
    p = tmp_path / "doc.md"
    p.write_text(DOC, encoding="utf-8")
    kb.ingest_file(p)
    assert kb.embedder_id() == "hash-sha256:512"
    onnx = OnnxEmbedder.__new__(OnnxEmbedder)      # 只为指纹/重嵌测试，不触模型
    onnx.dim = 512
    onnx.id = "onnx:bge-small-zh-v1.5:512"
    def fake_encode(texts):
        import numpy as np
        out = []
        for t in texts:
            rng = np.random.default_rng(len(t))
            v = rng.normal(size=512)
            out.append((v / np.linalg.norm(v)).tolist())
        return out
    onnx.encode = fake_encode
    assert kb.space_mismatch(onnx) is True          # 空间不匹配被识别
    n = kb.reembed(onnx)                            # 文本在库：无需原始文件即可自愈
    assert n > 0
    assert kb.embedder_id() == "onnx:bge-small-zh-v1.5:512"
    assert kb.space_mismatch(onnx) is False

def test_hash_ingest_into_onnx_space_refuses(tmp_path):
    """onnx 空间的库在降级（Hash）模式下拒入库：防止污染语义空间。"""
    kb = KnowledgeBase(tmp_path / "kb.db", HashEmbedder(dim=512))
    p = tmp_path / "doc.md"
    p.write_text(DOC, encoding="utf-8")
    kb.ingest_file(p)                                # hash 空间建库
    kb.set_embedder_id("onnx:bge-small-zh-v1.5:512")  # 模拟库实为 onnx 空间
    # 以降级（hash）embedder 入库 onnx 空间的库：_ensure_space 必须拒绝（防污染）
    import pytest
    with pytest.raises(ValueError, match="嵌入模型未就绪"):
        kb.ingest_file(p)


# ---- 标题直配 + 命中扩节（检索为主：简历/文档按问答结构组织，节标题≈面试问题） ----
RESUME = """# 个人经历

### 自我介绍

面试官您好，我叫测试用户，今年三十岁，本科就读于某大学。

工作经历的话，是从零到一做过多个产品。

#### 跳槽原因

很多方面的原因，未来两年组内规划聚焦在核心项目上。

## 未来计划

短期希望快速融入团队，长期希望负责整条产品线。

# 项目经历

### 促销中心

负责促销活动的配置与数据看板，支撑大促场景。
"""

@pytest.fixture
def resume_kb(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb.db", HashEmbedder(dim=512))
    kb.ingest_file(_write(tmp_path, "简历.md", RESUME))
    return kb

def test_match_sections_hits_section_title(resume_kb):
    """「请你做一个自我介绍」→ 4字滑窗「自我介绍」命中节标题。"""
    hits = resume_kb.match_sections("请你做一个自我介绍")
    assert hits == [("简历.md", "个人经历/自我介绍")]

def test_match_sections_prefers_exact_title_and_skips_descendants(resume_kb):
    """嵌套命中只留最浅节：整节扩出时子树自然带上，不重复计数。"""
    hits = resume_kb.match_sections("自我介绍，包括跳槽原因")
    assert ("简历.md", "个人经历/自我介绍") in hits
    assert ("简历.md", "个人经历/自我介绍/跳槽原因") not in hits

def test_match_sections_latin_token(tmp_path):
    """西文词项 ≥4 字符也要能直配（大小写不敏感）。"""
    kb = KnowledgeBase(tmp_path / "kb2.db", HashEmbedder(dim=512))
    nlp = "# NLP\n\n### Transformer是什么，简单解释一下原理\n\n自注意力机制让每个词都能看到全句。\n"
    kb.ingest_file(_write(tmp_path, "nlp.md", nlp))
    assert kb.match_sections("transformer是什么") == [("nlp.md", "NLP/Transformer是什么，简单解释一下原理")]
    assert kb.match_sections("TRANSFORMER 介绍一下") == [("nlp.md", "NLP/Transformer是什么，简单解释一下原理")]

def test_match_sections_future_plan(resume_kb):
    hits = resume_kb.match_sections("未来计划是什么")
    assert hits == [("简历.md", "个人经历/未来计划")]

def test_match_sections_no_match(resume_kb):
    assert resume_kb.match_sections("今天天气怎么样") == []

def test_section_chunks_includes_subtree_in_order(resume_kb):
    rows = resume_kb.section_chunks("简历.md", "个人经历/自我介绍")
    texts = [t for _, _, t in rows]
    assert any("面试官您好" in t for t in texts)
    assert any("跳槽原因" in t or "很多方面的原因" in t for t in texts)
    assert not any("未来计划" in t for t in texts)      # 平级节不带
    assert not any("促销" in t for t in texts)          # 其它文件节不带

def test_merge_section_texts_dedups_overlap_seam():
    from core.kb import merge_section_texts
    prev = "".join(f"第{i}句内容。" for i in range(80))   # 递增编号：尾部串全文唯一
    nxt = prev[-50:] + "\n\n" + "后续内容" * 20
    merged = merge_section_texts([("r/a", prev), ("r/a", nxt)])   # 同节：拼缝去重叠
    assert merged.startswith(prev)
    assert "后续内容" in merged
    assert merged.count(prev[-50:]) == 1             # 拼缝只出现一次

def test_merge_section_texts_keeps_disjoint_texts():
    from core.kb import merge_section_texts
    merged = merge_section_texts([("r/a", "第一段"), ("r/a", "第二段")])
    assert merged == "第一段\n\n第二段"

def test_merge_section_texts_restores_subheadings():
    """跨 #### 子标题补回四级标题行：回答里层级不丢。"""
    from core.kb import merge_section_texts
    rows = [("r/自我介绍", "开头介绍。"), ("r/自我介绍/跳槽原因", "很多方面的原因。")]
    merged = merge_section_texts(rows)
    assert merged.startswith("开头介绍。")
    assert "#### 跳槽原因" in merged
    assert "很多方面的原因。" in merged

def test_merge_section_texts_collapses_aligned_spaces():
    """源文档用连续空格对齐 → 直出折叠为单空格，行尾空白去除。"""
    rows = [("r/a", "指标一：TTFT      指标二：成本　　指标三：质量  \n\n下一段。")]
    from core.kb import merge_section_texts
    merged = merge_section_texts(rows)
    assert "      " not in merged and "　　" not in merged
    assert "指标一：TTFT 指标二：成本 指标三：质量" in merged


def test_question_vec_match_threshold_and_descendant_dedup(tmp_path):
    """问题向量主路：阈值过滤 + 嵌套命中被祖先覆盖；降级模式恒不命中。"""
    import numpy as np
    from core.embedder import OnnxEmbedder
    kb = KnowledgeBase(tmp_path / "kb.db", HashEmbedder(dim=512))
    doc = ("# QA\n\n### 自我介绍\n\n正文A。\n\n#### 跳槽原因\n\n正文B。\n")
    kb.ingest_file(_write(tmp_path, "qa.md", doc))
    # 降级（Hash）模式：问题向量无语义，恒不命中
    assert kb.match_sections_by_vec("请你做一个自我介绍") == []

    onnx = OnnxEmbedder.__new__(OnnxEmbedder)      # 不触真模型的受控桩
    onnx.dim = 512
    onnx.id = "onnx:stub"
    e0 = np.zeros(512, dtype=np.float32); e0[0] = 1.0    # 自我介绍
    e1 = np.zeros(512, dtype=np.float32); e1[1] = 1.0    # 跳槽原因
    def enc(texts):
        return [e0 if "自我介绍" in t else e1 for t in texts]
    onnx.encode = enc
    onnx.encode_query = lambda q: (e0 + e1) / np.linalg.norm(e0 + e1)   # 两节都过阈
    kb.embedder = onnx
    kb.rebuild_question_vectors()
    hits = kb.match_sections_by_vec("请你做一个自我介绍，顺便讲讲跳槽原因")
    assert [hp for _, hp, _ in hits] == ["QA/自我介绍"]   # 后代节被祖先覆盖

    onnx.encode_query = lambda q: [0.0] * 512                          # 正交：全不过阈
    assert kb.match_sections_by_vec("请你做一个自我介绍") == []
