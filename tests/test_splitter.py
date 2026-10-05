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

def test_overlap_is_about_50_chars():
    """用户口径：块间重叠 ≈50 字，保证跨块的句子连贯可读。"""
    norm = lambda s: "".join(s.split())
    doc = "# L\n\n" + "这是一段很长的中文内容需要被切分。" * 60
    chunks = split_markdown(doc, "l.md")
    tail = norm(chunks[0].text)
    head = norm(chunks[1].text)
    # 后块以「前块去掉尾部后的剩余内容的结尾」+重叠衔接：直接量度共享长度
    shared = 0
    for n in range(50, 0, -1):
        if tail[-n:] == head[:n]:
            shared = n
            break
    assert 30 <= shared <= 60        # 标称 50，允许标点/换行归一化误差

def test_overlap_stays_within_same_section():
    """重叠不得跨标题节：B 节块不得携带 A 节尾巴（污染标题锚定嵌入与 FTS）。"""
    norm = lambda s: "".join(s.split())
    doc = ("# A\n\n" + "甲节内容。" * 80 + "\n\n# B\n\n" + "乙节内容。" * 80)
    chunks = split_markdown(doc, "s.md")
    a_chunks = [c for c in chunks if c.heading_path == "A"]
    b_chunks = [c for c in chunks if c.heading_path == "B"]
    assert a_chunks and b_chunks
    assert not norm(b_chunks[0].text).startswith(norm(a_chunks[-1].text)[-20:])
    assert norm(b_chunks[0].text).startswith("乙节内容。")

def test_empty_input_returns_empty():
    assert split_markdown("", "x.md") == []


# --- 问题节规则：### 三级标题为问题，三级以下（含 ####）全部归入回答 ---
def test_section_is_level3_heading():
    doc = "# 简历\n\n## 个人经历\n\n### 自我介绍\n\n正文A。\n\n#### 跳槽原因\n\n正文B。\n\n## 未来计划\n\n正文C。\n"
    chunks = split_markdown(doc, "r.md")
    sec = {c.heading_path: c.section for c in chunks}
    assert sec["简历/个人经历/自我介绍"] == "简历/个人经历/自我介绍"
    assert (sec["简历/个人经历/自我介绍/跳槽原因"]
            == "简历/个人经历/自我介绍")            # #### 归入 ### 回答
    assert sec["简历/未来计划"] == "简历/未来计划"

def test_section_breaks_at_next_level3():
    """下一个 ### 开启新问题节：前一节的回答不会越界。"""
    doc = "### 甲问题\n\n甲回答。\n\n#### 甲细节\n\n细节。\n\n### 乙问题\n\n乙回答。\n"
    chunks = split_markdown(doc, "s.md")
    assert [c.section for c in chunks] == ["甲问题", "甲问题", "乙问题"]
