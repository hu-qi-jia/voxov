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
