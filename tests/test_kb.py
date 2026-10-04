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
