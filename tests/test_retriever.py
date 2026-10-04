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
