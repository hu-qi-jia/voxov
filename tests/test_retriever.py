# tests/test_retriever.py
from core.embedder import HashEmbedder
from core.kb import KnowledgeBase
from core.retriever import Retriever, rrf_fuse

DOC = """# Redis

## 持久化

RDB 是定时快照。BGSAVE fork 子进程执行，SAVE 阻塞主线程。

## 主从复制

replication 异步，主写从读。

# MySQL

## 事务

MVCC 多版本并发控制，InnoDB 默认可重复读。
"""

def _kb(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb.db", HashEmbedder(dim=512))
    p = tmp_path / "doc.md"
    p.write_text(DOC, encoding="utf-8")
    kb.ingest_file(p)
    return kb

def test_rrf_prefers_item_in_both_rankings():
    a, b, c = 1, 2, 3
    fused = rrf_fuse([[a, b, c], [b, c, a]], k=60)
    # b: 1/62+1/61 ≈ 0.03252 > a: 1/61+1/63 ≈ 0.03227 > c —— 双路均靠前者胜
    assert fused[0] == b and fused[1] == a

def test_rrf_single_ranking_preserved():
    assert rrf_fuse([[5, 9, 7]]) == [5, 9, 7]

def test_rrf_empty():
    assert rrf_fuse([]) == []

def test_retrieve_hits_fts_for_exact_term(tmp_path):
    r = Retriever(_kb(tmp_path), HashEmbedder(dim=512))
    out = r.retrieve("MVCC 是什么", k=3)
    assert any("MVCC" in x.text for x in out)

def test_retrieve_returns_metadata(tmp_path):
    r = Retriever(_kb(tmp_path), HashEmbedder(dim=512))
    out = r.retrieve("Redis 主从复制", k=3)
    assert all(x.source_file == "doc.md" and x.heading_path for x in out)
    assert all(hasattr(x, "score") for x in out)

def test_retrieve_empty_kb(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb.db", HashEmbedder(dim=512))
    r = Retriever(kb, HashEmbedder(dim=512))
    assert r.retrieve("任何问题", k=5) == []

def test_retrieve_english_term(tmp_path):
    r = Retriever(_kb(tmp_path), HashEmbedder(dim=512))
    out = r.retrieve("BGSAVE 命令", k=3)
    assert any("BGSAVE" in x.text for x in out)

# --- 路由信号：真距离 + 可靠性 ---
def test_distances_unreliable_with_hash_embedder(tmp_path):
    r = Retriever(_kb(tmp_path), HashEmbedder(dim=512))
    assert r.distances_reliable is False

def test_distances_reliable_with_onnx_embedder(tmp_path):
    from core.embedder import OnnxEmbedder
    r = Retriever(_kb(tmp_path), OnnxEmbedder.__new__(OnnxEmbedder))  # 仅测 isinstance
    assert r.distances_reliable is True

def test_last_top_distance_populated_and_reset(tmp_path):
    r = Retriever(_kb(tmp_path), HashEmbedder(dim=512))
    r.retrieve("MVCC 是什么", k=3)
    assert isinstance(r.last_top_distance, float)
    assert r.last_top_distance >= 0.0
    r.retrieve("这是一个完全无关的查询单独", k=3)   # 有结果
    # 有结果的查询不抛错即可
    r.retrieve("", k=3)                              # 空查询必须重置
    assert r.last_top_distance is None

def test_last_top_distance_none_on_empty_kb(tmp_path):
    from core.kb import KnowledgeBase
    r = Retriever(KnowledgeBase(tmp_path / "e.db", HashEmbedder(dim=512)),
                  HashEmbedder(dim=512))
    r.retrieve("任何问题", k=5)
    assert r.last_top_distance is None


# ---- 检索主路：只检索问题（标题直配 + 问题向量）+ 命中扩节 ----
def test_match_sections_title_window(tmp_path):
    r = Retriever(_kb(tmp_path), HashEmbedder(dim=512))
    # 标题=「事务」（2字）短于 4 字滑窗，匹配不到；「MySQL」是根标题但无正文块
    assert r.match_sections("MySQL 的事务隔离级别是什么") == []
    assert r.match_sections("讲讲主从复制的机制") == [("doc.md", "Redis/主从复制", 1.0)]

def test_match_sections_ancestor_covers_descendant(tmp_path):
    doc = "# Redis\n\nRedis 是内存数据库。\n\n## 持久化\n\nRDB 是定时快照。\n"
    kb = KnowledgeBase(tmp_path / "kb.db", HashEmbedder(dim=512))
    p = tmp_path / "doc.md"
    p.write_text(doc, encoding="utf-8")
    kb.ingest_file(p)
    r = Retriever(kb, HashEmbedder(dim=512))
    assert r.match_sections("讲讲 Redis") == [("doc.md", "Redis", 1.0)]  # 根节命中，子树随扩节带入

def test_match_sections_no_hit(tmp_path):
    r = Retriever(_kb(tmp_path), HashEmbedder(dim=512))
    assert r.match_sections("量子计算是什么") == []

def test_section_materials_merges_whole_section(tmp_path):
    kb = _kb(tmp_path)
    r = Retriever(kb, HashEmbedder(dim=512))
    mats = r.section_materials([("doc.md", "Redis/持久化", 0.9)])
    assert len(mats) == 1
    assert "RDB 是定时快照" in mats[0].text
    assert "主写从读" not in mats[0].text               # 平级节不串
    assert "MVCC" not in mats[0].text                  # 其它文件节不串

def test_expand_to_sections_dedups_and_expands(tmp_path):
    r = Retriever(_kb(tmp_path), HashEmbedder(dim=512))
    from core.retriever import Retrieved
    ctxs = [
        Retrieved(1, "RDB 片段", "Redis/持久化", "doc.md", -1),
        Retrieved(1, "RDB 另一片段", "Redis/持久化", "doc.md", -2),   # 同节（同块）：去重
        Retrieved(3, "事务片段", "MySQL/事务", "doc.md", -3),
    ]
    mats = r.expand_to_sections(ctxs)
    assert [m.heading_path for m in mats] == ["Redis/持久化", "MySQL/事务"]
    assert "主写从读" not in mats[0].text                            # 扁平节：只带本节
