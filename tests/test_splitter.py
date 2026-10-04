# tests/test_splitter.py
from core.splitter import split_markdown

MD = """# Redis
Redis 是内存数据库。

## 持久化
两种方式如下。

### RDB
定时快照，`SAVE` 阻塞。

### AOF
追加日志，更安全。
"""

def test_heading_path_recorded():
    chunks = split_markdown(MD, "redis.md")
    paths = {c.heading_path for c in chunks}
    assert "Redis/持久化/RDB" in paths
    assert "Redis/持久化/AOF" in paths

def test_heading_change_flushes_chunk():
    chunks = split_markdown(MD, "redis.md")
    assert all("RDB" not in c.text or "AOF" not in c.text for c in chunks)

def test_chunks_have_index_and_source():
    chunks = split_markdown(MD, "redis.md")
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert all(c.source_file == "redis.md" for c in chunks)

def test_code_block_never_split():
    doc = "# C\n\n" + "段落一。" * 100 + "\n\n```python\nfor i in range(10):\n    print(i)\n```\n" + "段落二。" * 100
    chunks = split_markdown(doc, "c.md")
    code_chunks = [c for c in chunks if "for i in range(10):" in c.text]
    assert len(code_chunks) == 1
    assert "print(i)" in code_chunks[0].text  # 代码块完整

def test_code_block_with_nested_fence():
    fence_md = "# T\n\n```\nouter start\n```inner\n```\nouter end\n```\n"
    chunks = split_markdown(fence_md, "t.md")
    assert any("outer start" in c.text and "outer end" in c.text for c in chunks)

def test_table_never_split():
    tbl = "# TB\n\n" + "前文。" * 200 + "\n\n| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n" + "后文。" * 200
    chunks = split_markdown(tbl, "tb.md")
    t = [c for c in chunks if "| 1 | 2 |" in c.text]
    assert len(t) == 1 and "| 3 | 4 |" in t[0].text

def test_long_paragraph_produces_multiple_chunks_with_overlap():
    doc = "# L\n\n" + "这是一段很长的中文内容需要被切分。" * 60
    chunks = split_markdown(doc, "l.md")
    assert len(chunks) >= 2
    # 相邻块重叠：后一块开头是前一块结尾的尾部
    assert chunks[1].text[:10] in chunks[0].text

def test_empty_input_returns_empty():
    assert split_markdown("", "x.md") == []
