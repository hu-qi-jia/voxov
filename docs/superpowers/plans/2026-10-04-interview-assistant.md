# 面试助手（Interview Assistant）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建开源 Windows PC 客户端：监听系统音频→FunASR 中文转写字幕→热键触发→本地向量知识库 RAG→OpenAI 兼容 LLM 流式生成口语化要点，置顶悬浮窗展示。

**Architecture:** Python 单体（PySide6 UI + core 纯逻辑层），四线程模型：音频采集线程→ASR 线程→UI 主线程→生成 worker。知识库为单文件 SQLite（sqlite-vec 向量 + FTS5 trigram 全文 + RRF 融合）。core 层全部面向接口（`Embedder`/`AudioSource`/`LLMClient`/`Transcriber`），保证无模型/无设备/无网络均可单元测试。

**Tech Stack:** Python 3.11+, PySide6, FunASR (SenseVoice-Small + fsmn-vad + ct-punc), sentence-transformers (BAAI/bge-small-zh-v1.5), sqlite-vec, pyaudiowpatch, httpx, keyboard, numpy, pytest / pytest-qt。

**Spec:** `docs/superpowers/specs/2026-10-04-interview-assistant-design.md`

## Global Constraints

- Python ≥ 3.11（FTS5 trigram 需 SQLite ≥ 3.34；**禁用 audioop**——3.13 已移除，重采样一律 numpy）
- 目标平台 Windows 11；音频采集走 WASAPI loopback（pyaudiowpatch）
- 默认目录：`<项目根>/models/` 与 `<项目根>/data/`，设置页可改；两者必须保持 `.gitignore` 排除
- 模型下载默认镜像 `HF_ENDPOINT=https://hf-mirror.com`
- LLM 参数固定：temperature=0.3, max_tokens=500；检索 top5；RRF k=60
- 默认热键 `ctrl+alt+space`，设置页可改
- System 提示词必须与 spec §6.3 逐字一致
- 无鉴权、无用户体系；单机单用户
- pytest 默认跳过真实模型测试：`addopts = -m "not model"`；`model` 标记的测试需本机已下载模型
- 提交信息用 conventional commits（feat/test/chore/docs）

## Review Focus

实现时最容易坑真实用户的五类输入，对应测试已钉进所属任务：

1. **重复上传同名 md 残留旧 chunks**（检索出过期重复内容）→ Task 4 `test_reingest_same_file_replaces_old_chunks`
2. **fenced 代码块内嵌 ``` / 表格被切断**（代码与说明分离即废）→ Task 2 `test_code_block_with_nested_fence` / `test_table_never_split`
3. **热键触发时转写缓冲为空或纯寒暄**（白烧一次 LLM 调用）→ Task 10 `test_empty_question_short_circuits_llm`
4. **LLM 返回非 200 / SSE 中途断流**（面试中崩溃不可接受）→ Task 9 `test_retry_once_then_raise` / `test_malformed_sse_ignored`
5. **系统音频为 48kHz 立体声**（设备原生格式，不转换则 ASR 全错）→ Task 11 `test_stereo_48k_downmix_resample`

---

### Task 1: 项目脚手架 + 配置模块

**Files:**
- Create: `pyproject.toml`, `core/__init__.py`, `app/__init__.py`, `tests/__init__.py`, `core/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `AppConfig` dataclass（字段：`root: Path`, `models_dir: Path`, `data_dir: Path`, `kb_path: Path`, `sessions_dir: Path`, `llm_base_url: str`, `llm_api_key: str`, `llm_model: str`, `hotkey: str="ctrl+alt+space"`）；`default_config() -> AppConfig`；`load_config(data_dir) -> AppConfig`；`save_config(cfg) -> None`（JSON 存 `data_dir/config.json`，缺省字段用默认值合并）。后续所有任务经 `AppConfig` 取路径。

- [ ] **Step 1: 写 pyproject.toml**

```toml
[project]
name = "interview-assistant"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "PySide6>=6.6",
  "numpy>=1.26",
  "httpx>=0.27",
  "keyboard>=0.13",
  "sqlite-vec>=0.1.3",
  "pyaudiowpatch>=0.2.12",
]

[project.optional-dependencies]
ml = ["torch>=2.2", "funasr>=1.1", "sentence-transformers>=2.7", "huggingface_hub>=0.23", "modelscope>=1.15"]
dev = ["pytest>=8.0", "pytest-qt>=4.4"]

[tool.pytest.ini_options]
addopts = "-m 'not model'"
markers = ["model: 需要本机已下载真实模型", "qt: 需要 Qt 环境"]
```

（torch/funasr/sentence-transformers 放可选组 `ml`：核心逻辑开发与 CI 不装重依赖也能跑全部默认测试。）

- [ ] **Step 2: 写失败测试**

```python
# tests/test_config.py
from pathlib import Path
from core.config import AppConfig, default_config, load_config, save_config

def test_default_config_uses_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr("core.config.app_root", lambda: tmp_path)
    cfg = default_config()
    assert cfg.models_dir == tmp_path / "models"
    assert cfg.data_dir == tmp_path / "data"
    assert cfg.kb_path == tmp_path / "data" / "kb.db"
    assert cfg.hotkey == "ctrl+alt+space"
    assert cfg.llm_base_url == ""

def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("core.config.app_root", lambda: tmp_path)
    cfg = default_config()
    cfg.llm_base_url = "https://api.deepseek.com/v1"
    cfg.llm_model = "deepseek-chat"
    save_config(cfg)
    loaded = load_config(tmp_path / "data")
    assert loaded.llm_base_url == "https://api.deepseek.com/v1"
    assert loaded.llm_model == "deepseek-chat"

def test_load_missing_config_returns_default(tmp_path, monkeypatch):
    monkeypatch.setattr("core.config.app_root", lambda: tmp_path)
    cfg = load_config(tmp_path / "data")
    assert cfg.llm_api_key == ""

def test_load_partial_config_merges_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr("core.config.app_root", lambda: tmp_path)
    d = tmp_path / "data"; d.mkdir(parents=True)
    (d / "config.json").write_text('{"llm_model": "gpt-4o"}', encoding="utf-8")
    cfg = load_config(d)
    assert cfg.llm_model == "gpt-4o" and cfg.hotkey == "ctrl+alt+space"
```

- [ ] **Step 3: 跑测试确认失败**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: core.config`）

- [ ] **Step 4: 最小实现**

```python
# core/config.py
import json
import sys
from dataclasses import dataclass, asdict, fields
from pathlib import Path


def app_root() -> Path:
    """项目根：打包后取 exe 所在目录；开发时取仓库根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[1]


@dataclass
class AppConfig:
    root: Path
    models_dir: Path
    data_dir: Path
    kb_path: Path
    sessions_dir: Path
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    hotkey: str = "ctrl+alt+space"

    def ensure_dirs(self) -> None:
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)


def default_config() -> AppConfig:
    root = app_root()
    data = root / "data"
    return AppConfig(
        root=root, models_dir=root / "models", data_dir=data,
        kb_path=data / "kb.db", sessions_dir=data / "sessions",
    )


def save_config(cfg: AppConfig) -> None:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    (cfg.data_dir / "config.json").write_text(
        json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(data_dir: Path) -> AppConfig:
    cfg = default_config()
    f = data_dir / "config.json"
    if not f.exists():
        return cfg
    raw = json.loads(f.read_text(encoding="utf-8"))
    names = {fld.name for fld in fields(AppConfig)}
    for k, v in raw.items():
        if k in names:
            setattr(cfg, k, Path(v) if k in ("root", "models_dir", "data_dir", "kb_path", "sessions_dir") and isinstance(v, str) else v)
    return cfg
```

- [ ] **Step 5: 跑测试通过后提交**

Run: `python -m pytest tests/test_config.py -v` → PASS

```bash
git add pyproject.toml core/ app/ tests/test_config.py
git commit -m "feat: 项目脚手架与 AppConfig 配置模块"
```

---

### Task 2: markdown 结构感知切分器

**Files:**
- Create: `core/splitter.py`
- Test: `tests/test_splitter.py`

**Interfaces:**
- Produces: `Chunk` dataclass（`text: str, heading_path: str, source_file: str, index: int`）；`split_markdown(text: str, source_file: str, target: int = 400, overlap: int = 50) -> list[Chunk]`。Task 4（知识库）消费。

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_splitter.py -v` → FAIL

- [ ] **Step 3: 实现**

```python
# core/splitter.py
import re
from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    heading_path: str
    source_file: str
    index: int


def _blocks(lines: list[str]) -> list[tuple[str, str]]:
    """把 md 行流切成 (heading_path, block) 序列；block 是段落/代码块/表格。"""
    headings: list[str] = []
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level, title = len(m.group(1)), m.group(2).strip()
            headings = headings[: level - 1] + [title]
            i += 1
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]

            def _is_close(s: str) -> bool:  # CommonMark：关闭行只能是 fence+空白
                t = s.strip()
                return t.startswith(fence) and not t[len(fence):].strip()

            code = [line]
            i += 1
            while i < len(lines) and not _is_close(lines[i]):
                code.append(lines[i])
                i += 1
            if i < len(lines):
                code.append(lines[i])
                i += 1
            out.append(("/".join(headings), "\n".join(code)))
            continue
        if stripped.startswith("|"):
            tbl = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                tbl.append(lines[i])
                i += 1
            out.append(("/".join(headings), "\n".join(tbl)))
            continue
        if not stripped:
            i += 1
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith(("#", "`", "~", "|")):
            para.append(lines[i])
            i += 1
        out.append(("/".join(headings), " ".join(para)))
    return out


def split_markdown(text: str, source_file: str, target: int = 400, overlap: int = 50) -> list[Chunk]:
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_path = ""

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        body = "\n\n".join(buf)
        if chunks and overlap > 0:
            body = chunks[-1].text[-overlap:] + "\n\n" + body
        chunks.append(Chunk(text=body, heading_path=buf_path, source_file=source_file, index=len(chunks)))
        buf = []

    for path, block in _blocks(text.splitlines()):
        if block.lstrip().startswith(("```", "~~~", "|")):
            flush()  # 代码块/表格独立成块，绝不与文字合并切断
            chunks.append(Chunk(text=block, heading_path=path, source_file=source_file, index=len(chunks)))
            continue
        if buf and path != buf_path:
            flush()
        buf_path = buf_path or path
        buf.append(block)
        if sum(len(b) for b in buf) >= target:
            flush()
    flush()
    return chunks
```

- [ ] **Step 4: 跑测试通过**

Run: `python -m pytest tests/test_splitter.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add core/splitter.py tests/test_splitter.py
git commit -m "feat: markdown 结构感知切分器（代码块/表格不切断，相邻块重叠）"
```

---

### Task 3: Embedder 接口（HashEmbedder 测试桩 + BgeEmbedder 真实现）

**Files:**
- Create: `core/embedder.py`
- Test: `tests/test_embedder.py`

**Interfaces:**
- Produces: `Embedder` Protocol（`dim: int` 属性、`encode(texts: list[str]) -> list[list[float]]`）；`HashEmbedder(dim: int = 512)`（确定性哈希向量，测试/开发用，不依赖 torch）；`BgeEmbedder(model_dir: Path)`（sentence-transformers，`dim=512`）。Task 4/5 消费。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_embedder.py
import pytest
from core.embedder import HashEmbedder

def test_hash_embedder_deterministic_and_dim():
    e = HashEmbedder(dim=512)
    a, b = e.encode(["Redis 持久化", "Redis 持久化", "不同的文本"])
    assert len(a) == 512 and a == b and a != c if (c := e.encode(["不同的文本"])[0]) else True

def test_hash_embedder_batch_length():
    e = HashEmbedder(dim=64)
    out = e.encode(["一", "二", "三"])
    assert len(out) == 3 and all(len(v) == 64 for v in out)

def test_hash_embedder_empty_input():
    assert HashEmbedder().encode([]) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_embedder.py -v` → FAIL

- [ ] **Step 3: 实现**

```python
# core/embedder.py
import hashlib
from pathlib import Path
from typing import Protocol


class Embedder(Protocol):
    dim: int

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """确定性哈希向量：不依赖模型，供单元测试与小规模开发调试。"""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            vec = []
            for i in range(self.dim):
                vec.append((h[i % len(h)] / 255.0) * 2 - 1)
            out.append(vec)
        return out


class BgeEmbedder:
    """BAAI/bge-small-zh-v1.5，本地加载，dim=512。"""

    def __init__(self, model_dir: Path) -> None:
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(str(model_dir))
        self.dim = 512

    def encode(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vecs]
```

- [ ] **Step 4: 跑测试通过，另写真实模型冒烟测试（默认跳过）**

```python
# 追加到 tests/test_embedder.py
@pytest.mark.model
def test_bge_embedder_real_model():
    from core.embedder import BgeEmbedder
    from core.config import default_config
    cfg = default_config()
    model_dir = cfg.models_dir / "bge-small-zh-v1.5"
    if not model_dir.exists():
        pytest.skip("模型未下载")
    e = BgeEmbedder(model_dir)
    a, b = e.encode(["Redis 持久化有哪几种方式", "RDB 和 AOF 的区别"])
    assert len(a) == 512
    # 语义相近的中文句子余弦相似度应高于无关句
    c, = e.encode(["今天天气不错"])
    sim_ab = sum(x * y for x, y in zip(a, b))
    sim_ac = sum(x * y for x, y in zip(a, c))
    assert sim_ab > sim_ac
```

Run: `python -m pytest tests/test_embedder.py -v` → 默认测试 PASS；本机下载模型后 `python -m pytest tests/test_embedder.py -m model -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add core/embedder.py tests/test_embedder.py
git commit -m "feat: Embedder 接口（HashEmbedder 桩 + BgeEmbedder 本地实现）"
```

---

### Task 4: 知识库存储（sqlite-vec + FTS5 trigram）

**Files:**
- Create: `core/kb.py`
- Test: `tests/test_kb.py`

**Interfaces:**
- Consumes: `Embedder`（Task 3）、`Chunk`/`split_markdown`（Task 2）
- Produces: `KnowledgeBase(db_path: Path, embedder: Embedder)`，方法：`ingest_file(md_path: Path) -> int`（同名全量替换，返回 chunk 数）、`delete_file(name: str) -> int`、`list_files() -> list[tuple[str, int]]`（文件名+chunk 数）、`vector_search(vec: list[float], k: int = 5) -> list[tuple[int, float]]`、`fts_search(query: str, k: int = 5) -> list[int]`、`get_chunks(ids: list[int]) -> list[tuple[int, str, str, str]]`（id, text, heading_path, source_file）。Task 5 消费。

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_kb.py -v` → FAIL

- [ ] **Step 3: 实现**

```python
# core/kb.py
import re
import sqlite3
from pathlib import Path

import sqlite_vec
from sqlite_vec import serialize_float32

from core.embedder import Embedder
from core.splitter import split_markdown


class KnowledgeBase:
    def __init__(self, db_path: Path, embedder: Embedder) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self.con = sqlite3.connect(db_path)
        self.con.enable_load_extension(True)
        sqlite_vec.load(self.con)
        self.con.enable_load_extension(False)
        self.con.executescript(f"""
        CREATE TABLE IF NOT EXISTS chunks(
          id INTEGER PRIMARY KEY,
          source_file TEXT NOT NULL,
          heading_path TEXT NOT NULL,
          seq INTEGER NOT NULL,
          text TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks
          USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[{embedder.dim}]);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, tokenize='trigram');
        """)

    def ingest_file(self, md_path: Path) -> int:
        text = md_path.read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError(f"文件为空: {md_path}")
        chunks = split_markdown(text, md_path.name)
        if not chunks:
            raise ValueError(f"无可切分内容: {md_path}")
        vecs = self.embedder.encode([c.text for c in chunks])
        with self.con:
            self.delete_file(md_path.name)
            for c, v in zip(chunks, vecs):
                cur = self.con.execute(
                    "INSERT INTO chunks(source_file, heading_path, seq, text) VALUES(?,?,?,?)",
                    (c.source_file, c.heading_path, c.index, c.text))
                self.con.execute(
                    "INSERT INTO vec_chunks(chunk_id, embedding) VALUES(?,?)",
                    (cur.lastrowid, serialize_float32(v)))
                self.con.execute(
                    "INSERT INTO chunks_fts(rowid, text) VALUES(?,?)",
                    (cur.lastrowid, c.text))
        return len(chunks)

    def delete_file(self, name: str) -> int:
        ids = [r[0] for r in self.con.execute(
            "SELECT id FROM chunks WHERE source_file=?", (name,))]
        with self.con:
            for i in ids:
                self.con.execute("DELETE FROM vec_chunks WHERE chunk_id=?", (i,))
                self.con.execute("DELETE FROM chunks_fts WHERE rowid=?", (i,))
            cur = self.con.execute("DELETE FROM chunks WHERE source_file=?", (name,))
        return cur.rowcount

    def list_files(self) -> list[tuple[str, int]]:
        return list(self.con.execute(
            "SELECT source_file, COUNT(*) FROM chunks GROUP BY source_file ORDER BY source_file"))

    def vector_search(self, vec: list[float], k: int = 5) -> list[tuple[int, float]]:
        rows = self.con.execute(
            "SELECT chunk_id, distance FROM vec_chunks WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (serialize_float32(vec), k))
        return [(int(r[0]), float(r[1])) for r in rows]

    def fts_search(self, query: str, k: int = 5) -> list[int]:
        phrase = '"' + re.sub(r'["\s]+', ' ', query).strip() + '"'
        if len(phrase.strip('"')) < 3:  # trigram 最短 3 字符
            return []
        try:
            rows = self.con.execute(
                "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                (phrase, k))
        except sqlite3.OperationalError:
            return []
        return [int(r[0]) for r in rows]

    def get_chunks(self, ids: list[int]) -> list[tuple[int, str, str, str]]:
        if not ids:
            return []
        ph = ",".join("?" * len(ids))
        return [(int(r[0]), r[4], r[2], r[1]) for r in self.con.execute(
            f"SELECT id, source_file, heading_path, seq, text FROM chunks WHERE id IN ({ph}) ORDER BY id", ids)]
```

- [ ] **Step 4: 跑测试通过**

Run: `python -m pytest tests/test_kb.py -v` → PASS（若本机 sqlite3 不支持 load_extension，改用 `pysqlite3` 并在此任务记录）

- [ ] **Step 5: 提交**

```bash
git add core/kb.py tests/test_kb.py
git commit -m "feat: sqlite-vec + FTS5 trigram 知识库存储（同名替换/删除/双路检索）"
```

---

### Task 5: RRF 融合 + Retriever

**Files:**
- Create: `core/retriever.py`
- Test: `tests/test_retriever.py`

**Interfaces:**
- Consumes: `KnowledgeBase`（Task 4）、`Embedder`（Task 3）
- Produces: `Retrieved` dataclass（`chunk_id: int, text: str, heading_path: str, source_file: str, score: float`）；`rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[int]`；`Retriever(kb, embedder).retrieve(query: str, k: int = 5) -> list[Retrieved]`。Task 10 消费。

- [ ] **Step 1: 写失败测试**

```python
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
    assert fused[0] == a and fused[1] == b  # a: 两路第1 → 1/61+1/62 最高

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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_retriever.py -v` → FAIL

- [ ] **Step 3: 实现**

```python
# core/retriever.py
from dataclasses import dataclass

from core.embedder import Embedder
from core.kb import KnowledgeBase


@dataclass
class Retrieved:
    chunk_id: int
    text: str
    heading_path: str
    source_file: str
    score: float


def rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[int]:
    """Reciprocal Rank Fusion：两路排名 → 融合排序（spec §6.2）。"""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return [cid for cid, _ in sorted(scores.items(), key=lambda x: (-x[1], x[0]))]


class Retriever:
    def __init__(self, kb: KnowledgeBase, embedder: Embedder) -> None:
        self.kb = kb
        self.embedder = embedder

    def retrieve(self, query: str, k: int = 5) -> list[Retrieved]:
        query = query.strip()
        if not query:
            return []
        vec, = self.embedder.encode([query])
        rankings = [
            [cid for cid, _ in self.kb.vector_search(vec, k=k)],
            self.kb.fts_search(query, k=k),
        ]
        fused = rrf_fuse([r for r in rankings if r], k=60)[:k]
        rows = {r[0]: r for r in self.kb.get_chunks(fused)}
        order = {cid: i for i, cid in enumerate(fused)}
        out = []
        for cid in sorted(fused, key=order.get):
            rid, text, heading, source = rows[cid]
            out.append(Retrieved(cid, text, heading, source, score=-order.get(cid, 999)))
        return out
```

- [ ] **Step 4: 跑测试通过**

Run: `python -m pytest tests/test_retriever.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add core/retriever.py tests/test_retriever.py
git commit -m "feat: 向量+FTS5 混合检索与 RRF 融合"
```

---

### Task 6: 会话转写缓冲 + 问题回溯提取

**Files:**
- Create: `core/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Produces: `TranscriptEntry` dataclass（`ts: float, end_ts: float, text: str`）；`SessionBuffer`（`.add_transcript(entry)`、`.entries -> list[TranscriptEntry]`、`.clear()`）；`extract_question(entries, now, min_pause=1.5, max_window=30.0) -> str`（spec §6.4 回溯算法）。Task 14（管线）与 Task 10（编排）消费。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_session.py
from core.session import TranscriptEntry, SessionBuffer, extract_question

def e(ts, dur, text):
    return TranscriptEntry(ts=ts, end_ts=ts + dur, text=text)

NOW = 100.0

def test_question_after_long_pause():
    entries = [e(90, 2.0, "你好，我是今天的面试官。"), e(96, 4.0, "请介绍一下Redis持久化的两种方式")]
    q = extract_question(entries, now=NOW)
    assert "面试官" not in q and "Redis持久化" in q

def test_includes_all_segments_after_boundary():
    entries = [e(90, 2.0, "你好。"), e(96, 3.0, "请介绍一下"), e(99.5, 3.0, "Redis的持久化")]
    q = extract_question(entries, now=NOW)
    assert "请介绍一下" in q and "Redis的持久化" in q

def test_no_boundary_takes_whole_window():
    entries = [e(95, 1.0, "那么"), e(96.2, 1.0, "请你"), e(97.4, 1.0, "介绍一下项目")]
    q = extract_question(entries, now=NOW)
    assert "介绍一下项目" in q and "那么" in q

def test_window_cutoff_30s():
    entries = [e(50, 2.0, "很久以前的寒暄。"), e(95, 3.0, "最近的问题")]
    q = extract_question(entries, now=NOW)
    assert "很久以前" not in q and "最近的问题" in q

def test_empty_entries_returns_empty():
    assert extract_question([], now=NOW) == ""

def test_pure_greeting_window_returns_it_anyway():
    # 30s 内只有寒暄且其后有长停顿——按 spec 规则返回寒暄本身，由 Task 10 层面交给 LLM 兜底
    entries = [e(90, 2.0, "麻烦做个自我介绍")]
    q = extract_question(entries, now=NOW)
    assert q == "麻烦做个自我介绍"

def test_session_buffer_append_and_clear():
    b = SessionBuffer()
    b.add_transcript(e(1, 1, "a"))
    b.add_transcript(e(3, 1, "b"))
    assert [x.text for x in b.entries] == ["a", "b"]
    b.clear()
    assert b.entries == []

def test_short_pause_not_boundary():
    entries = [e(96, 3.0, "请介绍一下"), e(99.6, 3.0, "主从复制")]  # gap 0.6s < 1.5s
    q = extract_question(entries, now=NOW)
    assert q == "请介绍一下主从复制"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_session.py -v` → FAIL

- [ ] **Step 3: 实现**

```python
# core/session.py
from dataclasses import dataclass, field


@dataclass
class TranscriptEntry:
    ts: float      # 段开始（unix 秒）
    end_ts: float  # 段结束（unix 秒）
    text: str


class SessionBuffer:
    """线程安全转写缓冲。音频管线线程写，热键回调读。"""

    def __init__(self) -> None:
        self._entries: list[TranscriptEntry] = []
        self._lock = __import__("threading").Lock()

    def add_transcript(self, entry: TranscriptEntry) -> None:
        with self._lock:
            self._entries.append(entry)
            self._entries = self._entries[-200:]  # 有界：防长会话内存膨胀

    @property
    def entries(self) -> list[TranscriptEntry]:
        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries = []


def extract_question(entries: list[TranscriptEntry], now: float,
                     min_pause: float = 1.5, max_window: float = 30.0) -> str:
    """spec §6.4：从当前回溯找 ≥min_pause 的段间停顿，取其后全部文本。"""
    entries = [x for x in entries if x.end_ts >= now - max_window]
    if not entries:
        return ""
    boundary = None
    for i in range(len(entries) - 1):
        if entries[i + 1].ts - entries[i].end_ts >= min_pause:
            boundary = i
    selected = entries[boundary + 1:] if boundary is not None else entries
    return "".join(x.text for x in selected).strip()
```

- [ ] **Step 4: 跑测试通过**

Run: `python -m pytest tests/test_session.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add core/session.py tests/test_session.py
git commit -m "feat: 转写缓冲与热键问题回溯提取"
```

---

### Task 7: 面试记录与 md 导出

**Files:**
- Modify: `core/session.py`（追加）
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `Retrieved`（Task 5）
- Produces: `QATurn` dataclass（`question: str, sources: list[str], answer: str, ts: float`）；`SessionRecorder`（`.add_transcript(entry)`、`.add_qa(question, contexts: list[Retrieved], answer: str)`、`.export_markdown(path: Path) -> Path`）。Task 10/16 消费。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_export.py
from pathlib import Path
from core.session import SessionRecorder, TranscriptEntry
from core.retriever import Retrieved

def test_export_contains_turns_and_sources(tmp_path):
    r = SessionRecorder()
    r.add_transcript(TranscriptEntry(ts=1.0, end_ts=2.0, text="面试官说"))
    r.add_qa("Redis持久化方式", [Retrieved(1, "RDB 是快照", "Redis/持久化", "redis.md", -1.0)], "RDB 和 AOF 两种。")
    out = tmp_path / "record.md"
    p = r.export_markdown(out)
    text = p.read_text(encoding="utf-8")
    assert "# 面试记录" in text
    assert "## 问" in text and "Redis持久化方式" in text
    assert "RDB 和 AOF 两种。" in text
    assert "redis.md › Redis/持久化" in text
    assert "面试官说" in text  # 转写也导出

def test_export_empty_session_still_writes(tmp_path):
    p = SessionRecorder().export_markdown(tmp_path / "r.md")
    assert p.exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_export.py -v` → FAIL

- [ ] **Step 3: 实现（追加到 core/session.py）**

```python
# --- 追加到 core/session.py ---
import time as _time
from datetime import datetime
from typing import Iterable


@dataclass
class QATurn:
    question: str
    sources: list[str]
    answer: str
    ts: float


class SessionRecorder:
    """面试全程记录 + md 导出（spec §5③）。"""

    def __init__(self) -> None:
        self.turns: list[QATurn] = []
        self.transcripts: list[TranscriptEntry] = []

    def add_transcript(self, entry: TranscriptEntry) -> None:
        self.transcripts.append(entry)

    def add_qa(self, question: str, contexts: Iterable, answer: str) -> None:
        sources = [f"{c.source_file} › {c.heading_path}" for c in contexts]
        self.turns.append(QATurn(question, sources, answer, _time.time()))

    def export_markdown(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"# 面试记录 {datetime.now():%Y-%m-%d %H:%M}", ""]
        lines.append("## 问答回顾")
        for i, t in enumerate(self.turns, 1):
            lines += [f"### 问 {i}（{datetime.fromtimestamp(t.ts):%H:%M:%S}）",
                      t.question, "", "**答**：", t.answer, ""]
            if t.sources:
                lines += ["**检索来源**："] + [f"- {s}" for s in t.sources] + [""]
        lines += ["## 全程转写", ""]
        lines += [f"- [{datetime.fromtimestamp(x.ts):%H:%M:%S}] {x.text}" for x in self.transcripts]
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path
```

（`Path` 需在文件头部 import：`from pathlib import Path`。）

- [ ] **Step 4: 跑测试通过**

Run: `python -m pytest tests/test_export.py tests/test_session.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add core/session.py tests/test_export.py
git commit -m "feat: 面试记录 SessionRecorder 与 md 导出"
```

---

### Task 8: Prompt 组装

**Files:**
- Create: `core/generator.py`
- Test: `tests/test_prompt.py`

**Interfaces:**
- Produces: `SYSTEM_PROMPT: str`（spec §6.3 逐字）；`build_messages(question: str, contexts: list, history: list[tuple[str, str]]) -> list[dict]`。Task 9/10 消费。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_prompt.py
from core.generator import SYSTEM_PROMPT, build_messages
from core.retriever import Retrieved

CTX = [Retrieved(1, "RDB 是快照", "Redis/持久化", "redis.md", -1.0)]

def test_system_prompt_verbatim():
    assert SYSTEM_PROMPT == ("你是面试实时辅助。输出口语化中文，像求职者当场回答，可直接照读，"
        "禁止书面腔和套话开场。分点输出，每点一句完整的话，关键词加粗。按重要性排序，"
        "最重要的点放第一条。共 4-6 点，全篇不超过 250 字。优先使用参考资料，资料不足时用自身知识。")

def test_messages_structure():
    msgs = build_messages("RDB是什么", CTX, [])
    assert msgs[0]["role"] == "system" and msgs[0]["content"] == SYSTEM_PROMPT
    assert msgs[1]["role"] == "user"
    assert "[资料1]" in msgs[1]["content"] and "redis.md" in msgs[1]["content"]
    assert "当前问题：RDB是什么" in msgs[1]["content"]

def test_history_last_two_only():
    history = [(f"q{i}", f"a{i}") for i in range(5)]
    msgs = build_messages("q", CTX, history)
    assert "q3" in msgs[1]["content"] and "q4" in msgs[1]["content"]
    assert "q1" not in msgs[1]["content"]

def test_empty_contexts_omit_refs_section():
    msgs = build_messages("q", [], [])
    assert "参考资料" not in msgs[1]["content"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_prompt.py -v` → FAIL

- [ ] **Step 3: 实现**

```python
# core/generator.py
SYSTEM_PROMPT = ("你是面试实时辅助。输出口语化中文，像求职者当场回答，可直接照读，"
    "禁止书面腔和套话开场。分点输出，每点一句完整的话，关键词加粗。按重要性排序，"
    "最重要的点放第一条。共 4-6 点，全篇不超过 250 字。优先使用参考资料，资料不足时用自身知识。")


def build_messages(question: str, contexts: list, history: list[tuple[str, str]]) -> list[dict]:
    parts: list[str] = []
    if contexts:
        refs = "\n\n".join(
            f"[资料{i+1}] {c.source_file} › {c.heading_path}\n{c.text}"
            for i, c in enumerate(contexts))
        parts.append(f"参考资料：\n{refs}")
    for q, a in history[-2:]:
        parts.append(f"之前的问题：{q}\n之前的回答：{a}")
    parts.append(f"当前问题：{question}")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
```

- [ ] **Step 4: 跑测试通过**

Run: `python -m pytest tests/test_prompt.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add core/generator.py tests/test_prompt.py
git commit -m "feat: 口语化照读 prompt 组装（含 2 轮追问上下文）"
```

---

### Task 9: LLMClient（OpenAI 兼容 SSE 流式 + 失败重试一次）

**Files:**
- Modify: `core/generator.py`（追加）
- Test: `tests/test_llm_client.py`

**Interfaces:**
- Produces: `LLMError(Exception)`；`LLMClient(base_url: str, api_key: str, model: str, timeout: float = 30.0)`，方法 `.stream(messages: list[dict], temperature: float = 0.3, max_tokens: int = 500) -> Iterator[str]`。Task 10 消费。测试用 `httpx.MockTransport` 注入，不发真请求。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_llm_client.py
import json
import httpx
import pytest
from core.generator import LLMClient, LLMError

def sse(*chunks):
    body = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n\n" for c in chunks)
    return body + "data: [DONE]\n\n"

def make_client(handler):
    transport = httpx.MockTransport(handler)
    c = LLMClient("https://api.example.com/v1", "sk-test", "test-model")
    c._transport = transport  # 测试注入
    return c

def test_stream_yields_deltas():
    c = make_client(lambda req: httpx.Response(200, text=sse("你", "好", "。")))
    assert "".join(c.stream([{"role": "user", "content": "hi"}])) == "你好。"

def test_payload_and_headers():
    captured = {}
    def handler(req):
        captured["url"] = str(req.url)
        captured["auth"] = req.headers["Authorization"]
        captured["json"] = json.loads(req.content)
        return httpx.Response(200, text=sse("ok"))
    make_client(handler).stream([{"role": "user", "content": "x"}])
    assert captured["url"].endswith("/chat/completions")
    assert captured["auth"] == "Bearer sk-test"
    assert captured["json"]["stream"] is True
    assert captured["json"]["temperature"] == 0.3 and captured["json"]["max_tokens"] == 500

def test_malformed_sse_ignored():
    body = "data: not-json\n\ndata: {\"choices\": [{\"delta\": {\"content\": \"好\"}}]}\n\ndata: [DONE]\n\n"
    c = make_client(lambda req: httpx.Response(200, text=body))
    assert "".join(c.stream([{"role": "user", "content": "x"}])) == "好"

def test_no_content_delta_skipped():
    body = ("data: {\"choices\": [{\"delta\": {\"role\": \"assistant\"}}]}\n\n"
            "data: {\"choices\": [{\"delta\": {\"content\": \"答\"}}]}\n\ndata: [DONE]\n\n")
    c = make_client(lambda req: httpx.Response(200, text=body))
    assert "".join(c.stream([{"role": "user", "content": "x"}])) == "答"

def test_http_500_raises_after_retry():
    calls = {"n": 0}
    def handler(req):
        calls["n"] += 1
        return httpx.Response(500, text="err")
    with pytest.raises(LLMError):
        list(make_client(handler).stream([{"role": "user", "content": "x"}]))
    assert calls["n"] == 2  # 重试恰好一次

def test_retry_once_then_succeeds():
    n = {"n": 0}
    def handler(req):
        n["n"] += 1
        if n["n"] == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, text=sse("恢复"))
    assert "".join(make_client(handler).stream([{"role": "user", "content": "x"}])) == "恢复"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_llm_client.py -v` → FAIL

- [ ] **Step 3: 实现（追加到 core/generator.py）**

```python
# --- 追加到 core/generator.py ---
import json
from typing import Iterator

import httpx


class LLMError(Exception):
    pass


class LLMClient:
    """OpenAI 兼容 /chat/completions 流式客户端（spec §3）。失败自动重试 1 次。"""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._transport = None  # 测试注入 MockTransport

    def stream(self, messages: list[dict], temperature: float = 0.3,
               max_tokens: int = 500) -> Iterator[str]:
        payload = {"model": self.model, "messages": messages, "stream": True,
                   "temperature": temperature, "max_tokens": max_tokens}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        client = httpx.Client(transport=self._transport, timeout=self.timeout)
        last_err: Exception | None = None
        for _attempt in range(2):
            try:
                with client.stream("POST", f"{self.base_url}/chat/completions",
                                   json=payload, headers=headers) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            return
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue  # 忽略非 JSON 行
                        try:
                            delta = obj["choices"][0]["delta"].get("content")
                        except (KeyError, IndexError):
                            continue
                        if delta:
                            yield delta
                    return
            except (httpx.HTTPError, KeyError) as exc:
                last_err = exc
        raise LLMError(f"LLM 调用失败（已重试 1 次）: {last_err}")
```

- [ ] **Step 4: 跑测试通过**

Run: `python -m pytest tests/test_llm_client.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add core/generator.py tests/test_llm_client.py
git commit -m "feat: OpenAI 兼容 SSE 流式 LLM 客户端（重试一次，坏行忽略）"
```

---

### Task 10: RagService 编排（提取→检索→生成→记录）

**Files:**
- Create: `core/rag.py`
- Test: `tests/test_rag.py`

**Interfaces:**
- Consumes: `Retriever`（Task 5）、`LLMClient`（Task 9）、`build_messages`（Task 8）、`SessionRecorder`（Task 7）、`extract_question`/`SessionBuffer`（Task 6）
- Produces: `RagService(retriever, llm, recorder=None)`，属性 `.buffer: SessionBuffer`；方法 `.trigger(now: float | None = None) -> Iterator[str]`（内部：`extract_question` → 空则 yield 空串并 return，不调 LLM → 检索 → `build_messages` → `llm.stream` → 累积答案、追加 history、`recorder.add_qa`）。Task 16（UI）消费。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_rag.py
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
    import time
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
    import time
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
    import time
    now = time.time()
    svc.buffer.add_transcript(TranscriptEntry(now - 5, now - 1, "讲讲TCP握手"))
    out = "".join(svc.trigger())
    assert "RDB" in out and len(llm.calls) == 1  # 无检索片段仍生成
```

（测试文件顶部若 import `NOW_UNUSED` 失败，删掉该 import，直接用 `time.time()`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_rag.py -v` → FAIL

- [ ] **Step 3: 实现**

```python
# core/rag.py
import time
from typing import Iterator

from core.generator import LLMClient, build_messages
from core.retriever import Retriever
from core.session import SessionBuffer, SessionRecorder, extract_question


class RagService:
    """热键触发的完整编排：提取问题 → 检索 → prompt → 流式生成 → 记录。"""

    def __init__(self, retriever: Retriever, llm: LLMClient,
                 recorder: SessionRecorder | None = None) -> None:
        self.retriever = retriever
        self.llm = llm
        self.recorder = recorder
        self.buffer = SessionBuffer()
        self.history: list[tuple[str, str]] = []

    def trigger(self, now: float | None = None) -> Iterator[str]:
        question = extract_question(self.buffer.entries, now or time.time())
        self.last_question = question
        if not question:
            yield ""  # 空问题短路：不调 LLM，UI 显示"未识别到问题"
            return
        contexts = self.retriever.retrieve(question, k=5)
        messages = build_messages(question, contexts, self.history)
        parts: list[str] = []
        for delta in self.llm.stream(messages):
            parts.append(delta)
            yield delta
        answer = "".join(parts)
        self.history.append((question, answer))
        self.history = self.history[-5:]
        if self.recorder:
            self.recorder.add_qa(question, contexts, answer)
```

- [ ] **Step 4: 跑测试通过**

Run: `python -m pytest tests/test_rag.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add core/rag.py tests/test_rag.py
git commit -m "feat: RagService 编排（空问题短路、多轮 history、记录）"
```

---

### Task 11: AudioSource 接口 + WavFileSource（48k 立体声重采样）

**Files:**
- Create: `core/capture.py`
- Test: `tests/test_capture.py`

**Interfaces:**
- Produces: `AudioSource` Protocol（`sample_rate: int = 16000`、`channels: int = 1`、`chunks() -> Iterator[bytes]`（int16 PCM 单声道 16kHz，块长固定 ~100ms）、`stop()`）；`WavFileSource(path: Path, block_ms: int = 100)`（任意采样率/声道 wav 自动转换）。Task 12/14 消费。测试需生成 wav：用 `wave` + `numpy` 写测试夹具。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_capture.py
import wave
import numpy as np
import pytest
from core.capture import WavFileSource

def write_wav(path, data_int16, rate, channels):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(data_int16.tobytes())

def test_mono_16k_passthrough(tmp_path):
    t = np.arange(16000, dtype=np.int16)  # 1 秒
    p = tmp_path / "a.wav"; write_wav(p, t, 16000, 1)
    src = WavFileSource(p, realtime=False)
    blocks = list(src.chunks())
    total = b"".join(blocks)
    assert src.sample_rate == 16000 and src.channels == 1
    assert len(total) == 32000  # 1s × 16000样本 × 2字节
    assert all(len(b) % 2 == 0 for b in blocks)

def test_stereo_48k_downmix_resample(tmp_path):
    t = np.arange(48000, dtype=np.float64) / 48000.0
    left = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16)
    right = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16)
    stereo = np.empty(48000 * 2, dtype=np.int16)
    stereo[0::2], stereo[1::2] = left, right
    p = tmp_path / "b.wav"; write_wav(p, stereo, 48000, 2)
    src = WavFileSource(p, realtime=False)
    total = np.frombuffer(b"".join(src.chunks()), dtype=np.int16)
    assert len(total) == 16000  # 1 秒重采样后
    # 440Hz 正弦重采样后仍是同频正弦：与参考相关系数极高
    ref = (np.sin(2 * np.pi * 440 * np.arange(16000) / 16000.0) * 10000)
    corr = np.corrcoef(total.astype(np.float64), ref)[0, 1]
    assert corr > 0.99

def test_block_size_about_100ms(tmp_path):
    t = np.zeros(16000, dtype=np.int16)
    p = tmp_path / "c.wav"; write_wav(p, t, 16000, 1)
    blocks = list(WavFileSource(p, block_ms=100, realtime=False).chunks())
    assert all(len(b) == 3200 for b in blocks)

def test_stop_terminates_iteration(tmp_path):
    t = np.zeros(16000 * 5, dtype=np.int16)
    p = tmp_path / "d.wav"; write_wav(p, t, 16000, 1)
    src = WavFileSource(p, realtime=False)
    it = src.chunks()
    next(it)
    src.stop()
    with pytest.raises(StopIteration):
        next(it)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_capture.py -v` → FAIL

- [ ] **Step 3: 实现**

```python
# core/capture.py
import wave
from pathlib import Path
from typing import Iterator, Protocol

import numpy as np


class AudioSource(Protocol):
    sample_rate: int
    channels: int

    def chunks(self) -> Iterator[bytes]: ...

    def stop(self) -> None: ...


def to_16k_mono(raw: bytes, src_rate: int, src_channels: int) -> bytes:
    """int16 任意采样率/声道 → 16kHz 单声道 int16（numpy 线性插值）。"""
    arr = np.frombuffer(raw, dtype=np.int16)
    if src_channels > 1:
        arr = arr.reshape(-1, src_channels).mean(axis=1).astype(np.int16)
    if src_rate != 16000:
        n_src = len(arr)
        n_dst = int(round(n_src * 16000 / src_rate))
        xs = np.linspace(0.0, n_src - 1, n_dst)
        arr = np.interp(xs, np.arange(n_src), arr.astype(np.float64)).astype(np.int16)
    return arr.tobytes()


class WavFileSource:
    """wav 文件重放（测试/调试用 AudioSource）。realtime=True 时按真实时长回放，
    使管线的时间戳/停顿逻辑与真实设备一致。"""

    sample_rate = 16000
    channels = 1

    def __init__(self, path: Path, block_ms: int = 100, realtime: bool = True) -> None:
        self._wf = wave.open(str(path), "rb")
        self._native_rate = self._wf.getframerate()
        self._native_channels = self._wf.getnchannels()
        self._block_frames = int(self._native_rate * block_ms / 1000)
        self._realtime = realtime
        self._stopped = False

    def chunks(self) -> Iterator[bytes]:
        import time
        while not self._stopped:
            started = time.monotonic()
            frames = self._wf.readframes(self._block_frames)
            if not frames:
                break
            yield to_16k_mono(frames, self._native_rate, self._native_channels)
            if self._realtime:  # 等到本块时长走完再给下一块
                remain = self._block_frames / 1000.0 - (time.monotonic() - started)
                if remain > 0:
                    time.sleep(remain)

    def stop(self) -> None:
        self._stopped = True
        self._wf.close()
```

- [ ] **Step 4: 跑测试通过**

Run: `python -m pytest tests/test_capture.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add core/capture.py tests/test_capture.py
git commit -m "feat: AudioSource 接口与 wav 重放源（48k 立体声自动降混重采样）"
```

---

### Task 12: LiveAudioSource（WASAPI loopback 系统音频）

**Files:**
- Modify: `core/capture.py`（追加）
- Test: `tests/test_live_source.py`（设备存在性冒烟，无设备时 skip）

**Interfaces:**
- Consumes: `to_16k_mono`（Task 11）
- Produces: `LiveAudioSource(device_name: str | None = None, block_ms: int = 100)`；`list_loopback_devices() -> list[dict]`（含 index/name/default）。Task 16（UI 设置页设备下拉）消费。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_live_source.py
import pytest
from core.capture import list_loopback_devices, LiveAudioSource

def test_list_loopback_devices_returns_list():
    devs = list_loopback_devices()
    assert isinstance(devs, list)
    # CI/无音频环境可能为空，本机应有默认设备
    for d in devs:
        assert "name" in d and "index" in d

def test_live_source_first_chunk_format():
    devs = list_loopback_devices()
    if not devs:
        pytest.skip("无 loopback 设备（静音环境）")
    src = LiveAudioSource()
    it = src.chunks()
    chunk = next(it, None)
    src.stop()
    if chunk is None:
        pytest.skip("系统静音，未产生音频块")
    assert len(chunk) % 2 == 0  # int16
    assert src.sample_rate == 16000 and src.channels == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_live_source.py -v` → FAIL

- [ ] **Step 3: 实现（追加到 core/capture.py）**

```python
# --- 追加到 core/capture.py ---
import queue


def list_loopback_devices() -> list[dict]:
    """枚举 WASAPI loopback 设备；default 键标记当前默认输出。"""
    import pyaudiowpatch as pyaudio
    with pyaudio.PyAudio() as p:
        out = []
        default_idx = None
        try:
            wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_idx = wasapi.get("defaultOutputDevice")
        except OSError:
            pass
        for d in p.get_loopback_device_info_generator():
            out.append({"index": d["index"], "name": d["name"],
                        "default": d["index"] == default_idx})
        return out


class LiveAudioSource:
    """系统音频 loopback 采集；原生格式 → 16k 单声道。设备错误抛 AudioDeviceError。"""

    sample_rate = 16000
    channels = 1

    def __init__(self, device_name: str | None = None, block_ms: int = 100) -> None:
        self._device_name = device_name
        self._block_ms = block_ms
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._stopped = False

    def _pick_device(self, p):
        if self._device_name:
            for d in p.get_loopback_device_info_generator():
                if self._device_name in d["name"]:
                    return d
            raise AudioDeviceError(f"找不到 loopback 设备: {self._device_name}")
        # 默认输出对应的 loopback
        wasapi = p.get_host_api_info_by_type(p.paWASAPI)
        default_out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
        for d in p.get_loopback_device_info_generator():
            if default_out["name"] in d["name"]:
                return d
        raise AudioDeviceError("未找到默认输出的 loopback 设备")

    def chunks(self) -> Iterator[bytes]:
        import time
        import pyaudiowpatch as pyaudio
        for _attempt in range(3):  # 设备热插拔/占用冲突：自动重连最多 3 次（spec §8）
            try:
                with pyaudio.PyAudio() as p:
                    dev = self._pick_device(p)
                    rate, ch = int(dev["defaultSampleRate"]), int(dev["maxInputChannels"])

                    def callback(in_data, frame_count, time_info, status):
                        self._queue.put(in_data)
                        return (None, pyaudio.paContinue)

                    stream = p.open(format=pyaudio.paInt16, channels=ch, rate=rate,
                                    input=True, input_device_index=int(dev["index"]),
                                    frames_per_buffer=int(rate * self._block_ms / 1000),
                                    stream_callback=callback)
                    stream.start_stream()
                    try:
                        while not self._stopped:
                            try:
                                item = self._queue.get(timeout=1.0)
                            except queue.Empty:
                                continue
                            if item is None:
                                break
                            yield to_16k_mono(item, rate, ch)
                    finally:
                        stream.stop_stream()
                        stream.close()
                return
            except AudioDeviceError:
                raise  # 明确找不到设备：不重试，直接报错
            except Exception:
                if self._stopped or _attempt == 2:
                    raise
                time.sleep(2.0)

    def stop(self) -> None:
        self._stopped = True
        self._queue.put(None)


class AudioDeviceError(RuntimeError):
    pass
```

- [ ] **Step 4: 跑测试（本机有设备应 PASS，无设备 SKIP）**

Run: `python -m pytest tests/test_live_source.py -v` → PASS/SKIP

- [ ] **Step 5: 提交**

```bash
git add core/capture.py tests/test_live_source.py
git commit -m "feat: WASAPI loopback 系统音频采集（默认设备自动匹配，可指定）"
```

---

### Task 13: FunasrTranscriber（SenseVoice-Small + VAD + 标点）

**Files:**
- Create: `core/transcriber.py`
- Test: `tests/test_transcriber.py`（逻辑测试用 Fake；真实模型测试标 `model`）

**Interfaces:**
- Produces: `Transcriber` Protocol（`transcribe(pcm16: bytes, sample_rate: int = 16000) -> str`）；`FunasrTranscriber(models_dir: Path)`（从本地 `models_dir/SenseVoiceSmall`、`fsmn-vad`、`ct-punc` 加载）；`FakeTranscriber(text="固定文本")`（测试桩）；`clean_sensevoice_text(text) -> str`（剥离 `<|zh|>` 类标签）。Task 14 消费。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_transcriber.py
import numpy as np
import pytest
from core.transcriber import FakeTranscriber, clean_sensevoice_text

def test_clean_strips_rich_tags():
    raw = "<|zh|><|NEUTRAL|>今天天气<|laughter|>不错<|/laughter|>。"
    assert clean_sensevoice_text(raw) == "今天天气不错。"

def test_clean_plain_text_untouched():
    assert clean_sensevoice_text("普通句子。") == "普通句子。"

def test_fake_transcriber_returns_fixed():
    t = FakeTranscriber("你好")
    assert t.transcribe(b"\x00\x00" * 1600) == "你好"

@pytest.mark.model
def test_funasr_real_model_chinese():
    from core.config import default_config
    from core.transcriber import FunasrTranscriber
    cfg = default_config()
    if not (cfg.models_dir / "SenseVoiceSmall").exists():
        pytest.skip("模型未下载")
    t = FunasrTranscriber(cfg.models_dir)
    # 1 秒 440Hz 正弦（静音样式的稳定音，主要验证链路不崩、返回字符串）
    pcm = (np.sin(2 * np.pi * 440 * np.arange(16000) / 16000) * 8000).astype(np.int16)
    out = t.transcribe(pcm.tobytes())
    assert isinstance(out, str)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_transcriber.py -v` → FAIL

- [ ] **Step 3: 实现**

```python
# core/transcriber.py
import re
from pathlib import Path
from typing import Protocol

import numpy as np


class Transcriber(Protocol):
    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> str: ...


def clean_sensevoice_text(text: str) -> str:
    """剥离 SenseVoice 富标签（<|zh|>、<|NEUTRAL|>、<|laughter|> 等）。"""
    return re.sub(r"<\|[^|]*\|>", "", text).strip()


class FakeTranscriber:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> str:
        return self.text


class FunasrTranscriber:
    """FunASR：SenseVoice-Small + fsmn-vad + ct-punc，全部本地加载（spec §3）。"""

    def __init__(self, models_dir: Path) -> None:
        from funasr import AutoModel
        self.asr = AutoModel(
            model=str(models_dir / "SenseVoiceSmall"),
            vad_model=str(models_dir / "fsmn-vad"),
            punc_model=str(models_dir / "ct-punc"),
            disable_update=True, disable_pbar=True, disable_log=True,
        )

    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> str:
        wav = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        res = self.asr.generate(input=wav, fs=sample_rate, language="zh", use_itn=True)
        text = res[0].get("text", "") if res else ""
        return clean_sensevoice_text(text)
```

- [ ] **Step 4: 跑测试通过（真实模型测试本机有模型时跑）**

Run: `python -m pytest tests/test_transcriber.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add core/transcriber.py tests/test_transcriber.py
git commit -m "feat: FunASR SenseVoice 转写封装（富标签清理）+ Fake 桩"
```

---

### Task 14: AudioPipeline 实时管线（采集→静音分段→转写→缓冲/字幕信号）

**Files:**
- Create: `core/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `AudioSource`（Task 11/12）、`Transcriber`（Task 13）、`SessionBuffer`/`TranscriptEntry`（Task 6）、`SessionRecorder`（Task 7）
- Produces: `AudioPipeline(source, transcriber, buffer: SessionBuffer, recorder: SessionRecorder | None = None, silence_sec: float = 1.2, min_speech_sec: float = 0.4)`，Qt 无关的纯线程类：`.start() -> threading.Thread`、`.stop()`；回调 `.on_subtitle: Callable[[str], None] | None`（新转写文本，UI 订阅）、`.on_error: Callable[[str], None] | None`。能量 VAD：`rms > 500` 视为语音。Task 16 消费。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pipeline.py
import wave
import numpy as np
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from core.capture import WavFileSource
from core.pipeline import AudioPipeline, rms
from core.session import SessionBuffer, SessionRecorder
from core.transcriber import FakeTranscriber

def make_wav(path, seconds_of_speech=1, lead_silence=1, tail_silence=1.6, rate=16000):
    n = int(rate * (lead_silence + seconds_of_speech + tail_silence))
    t = np.arange(n) / rate
    sig = np.where(
        (t >= lead_silence) & (t < lead_silence + seconds_of_speech),
        np.sin(2 * np.pi * 440 * t) * 8000, 0.0)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(sig.astype(np.int16).tobytes())

def test_rms_zero_for_silence():
    assert rms(b"\x00\x00" * 8000) < 1.0
    assert rms((np.ones(8000) * 1000).astype(np.int16).tobytes()) > 500

def test_pipeline_produces_entry_and_subtitle(tmp_path):
    wav = tmp_path / "a.wav"; make_wav(wav)
    subs = []
    buf = SessionBuffer()
    p = AudioPipeline(WavFileSource(wav), FakeTranscriber("请介绍Redis"), buf)
    p.on_subtitle = subs.append
    t = p.start(); t.join(timeout=30)
    assert subs == ["请介绍Redis"]
    assert len(buf.entries) == 1
    e = buf.entries[0]
    assert 0.9 <= (e.end_ts - e.ts) <= 1.6  # 语音段时长≈1s
    assert e.text == "请介绍Redis"

def test_pipeline_silence_creates_pause_gap(tmp_path):
    # 两段语音间隔 2s > min_pause，应产出两个 entry，段间 gap ≈ 2s
    rate = 16000
    n = int(rate * 5)
    t = np.arange(n) / rate
    speech = ((t >= 1) & (t < 2)) | ((t >= 4) & (t < 5))
    sig = np.where(speech, np.sin(2 * np.pi * 440 * t) * 8000, 0.0)
    wav = tmp_path / "b.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(sig.astype(np.int16).tobytes())
    buf = SessionBuffer()
    p = AudioPipeline(WavFileSource(wav), FakeTranscriber("段"), buf)
    t2 = p.start(); t2.join(timeout=30)
    assert len(buf.entries) == 2
    gap = buf.entries[1].ts - buf.entries[0].end_ts
    assert 1.5 <= gap <= 2.5

def test_pipeline_records_transcript(tmp_path):
    wav = tmp_path / "c.wav"; make_wav(wav)
    buf, rec = SessionBuffer(), SessionRecorder()
    p = AudioPipeline(WavFileSource(wav), FakeTranscriber("文本"), buf, recorder=rec)
    p.start().join(timeout=30)
    assert len(rec.transcripts) == 1

def test_pipeline_transcriber_error_calls_on_error(tmp_path):
    wav = tmp_path / "d.wav"; make_wav(wav)
    errs = []
    class Boom:
        def transcribe(self, pcm, sample_rate=16000):
            raise RuntimeError("asr崩了")
    p = AudioPipeline(WavFileSource(wav), Boom(), SessionBuffer())
    p.on_error = errs.append
    p.start().join(timeout=30)
    assert errs and "asr崩了" in errs[0]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_pipeline.py -v` → FAIL

- [ ] **Step 3: 实现**

```python
# core/pipeline.py
import threading
import time
from typing import Callable

import numpy as np

from core.capture import AudioSource
from core.session import SessionBuffer, SessionRecorder, TranscriptEntry
from core.transcriber import Transcriber


def rms(pcm16: bytes) -> float:
    if not pcm16:
        return 0.0
    arr = np.frombuffer(pcm16, dtype=np.int16)
    return float(np.sqrt(np.mean(arr.astype(np.float64) ** 2)))


class AudioPipeline:
    """采集→能量VAD分段→转写→会话缓冲；新文本回调 on_subtitle。"""

    def __init__(self, source: AudioSource, transcriber: Transcriber,
                 buffer: SessionBuffer, recorder: SessionRecorder | None = None,
                 silence_sec: float = 1.2, min_speech_sec: float = 0.4) -> None:
        self.source = source
        self.transcriber = transcriber
        self.buffer = buffer
        self.recorder = recorder
        self.silence_sec = silence_sec
        self.min_speech_sec = min_speech_sec
        self.on_subtitle: Callable[[str], None] | None = None
        self.on_error: Callable[[str], None] | None = None
        self._stop = threading.Event()

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self.run, daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()
        self.source.stop()

    def run(self) -> None:
        speech: list[bytes] = []
        speech_start: float | None = None
        last_activity = time.time()
        try:
            for block in self.source.chunks():
                if self._stop.is_set():
                    break
                now = time.time()
                block_dur = len(block) / 2 / self.source.sample_rate
                if rms(block) > 500:  # 语音
                    if not speech:
                        speech_start = now - block_dur
                    speech.append(block)
                    last_activity = now
                elif speech:  # 静音且缓冲有语音
                    if now - last_activity >= self.silence_sec:
                        self._flush(speech, speech_start, last_activity)
                        speech, speech_start = [], None
                time.sleep(0)  # 让出 GIL
            if speech:
                self._flush(speech, speech_start, last_activity)
        except Exception as exc:  # 设备拔出等
            if self.on_error:
                self.on_error(str(exc))

    def _flush(self, blocks: list[bytes], start: float | None, end: float) -> None:
        if start is None:
            return
        pcm = b"".join(blocks)
        if len(pcm) / 2 / 16000 < self.min_speech_sec:
            return
        try:
            text = self.transcriber.transcribe(pcm)
        except Exception as exc:
            if self.on_error:
                self.on_error(str(exc))
            return
        if not text:
            return
        entry = TranscriptEntry(ts=start, end_ts=end, text=text)
        self.buffer.add_transcript(entry)
        if self.recorder:
            self.recorder.add_transcript(entry)
        if self.on_subtitle:
            self.on_subtitle(text)
```

- [ ] **Step 4: 跑测试通过**

Run: `python -m pytest tests/test_pipeline.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add core/pipeline.py tests/test_pipeline.py
git commit -m "feat: 实时音频管线（能量 VAD 分段→转写→缓冲/字幕回调）"
```

---

### Task 15: 置顶悬浮窗 OverlayWindow

**Files:**
- Create: `app/overlay.py`
- Test: `tests/test_overlay.py`（pytest-qt）

**Interfaces:**
- Consumes: 无（纯 UI）
- Produces: `OverlayWindow(QWidget)`：`set_subtitle(text: str)`（滚动字幕区，显示最近 3 条）、`begin_answer(question: str)`（清空答案区、显示问题标题）、`append_answer(chunk: str)`（流式追加，Markdown 渲染加粗）、`end_answer()`、`show_status(text: str)`（如"未识别到问题""音频已切换到 XXX"）。窗口标志 `FramelessWindowHint | WindowStaysOnTopHint | Tool`，`setWindowOpacity(0.92)`，鼠标拖动移动。Task 16 消费。

- [ ] **Step 1: 写失败测试（pytest-qt）**

```python
# tests/test_overlay.py
import pytest
from PySide6.QtCore import Qt
from app.overlay import OverlayWindow

@pytest.fixture
def overlay(qtbot):
    w = OverlayWindow()
    qtbot.addWidget(w)
    return w

def test_window_flags_always_on_top(overlay):
    flags = overlay.windowFlags()
    assert flags & Qt.WindowStaysOnTopHint
    assert flags & Qt.FramelessWindowHint

def test_subtitle_appends_and_keeps_last_three(overlay):
    overlay.set_subtitle("第一句")
    overlay.set_subtitle("第二句")
    overlay.set_subtitle("第三句")
    overlay.set_subtitle("第四句")
    text = overlay.subtitle_label.text()
    assert "第二句" in text and "第四句" in text and "第一句" not in text

def test_answer_streaming(overlay):
    overlay.begin_answer("Redis持久化")
    overlay.append_answer("**RDB** ")
    overlay.append_answer("是快照。")
    assert "Redis持久化" in overlay.question_label.text()
    assert "RDB" in overlay.answer_view.toPlainText()
    assert "是快照。" in overlay.answer_view.toPlainText()

def test_begin_answer_clears_previous(overlay):
    overlay.begin_answer("Q1"); overlay.append_answer("旧答案")
    overlay.begin_answer("Q2")
    assert overlay.answer_view.toPlainText() == ""

def test_show_status(overlay):
    overlay.show_status("未识别到问题")
    assert "未识别到问题" in overlay.status_label.text()

def test_drag_moves_window(overlay):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    before = overlay.pos()
    press = QMouseEvent(QEvent.MouseButtonPress, QPointF(50, 5), QPointF(50, 5),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    overlay.mousePressEvent(press)
    move = QMouseEvent(QEvent.MouseMove, QPointF(120, 40), QPointF(120, 40),
                       Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    overlay.mouseMoveEvent(move)
    assert overlay.pos() != before or overlay._drag_offset is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_overlay.py -v` → FAIL

- [ ] **Step 3: 实现**

```python
# app/overlay.py
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (QApplication, QLabel, QTextBrowser, QVBoxLayout, QWidget)


class OverlayWindow(QWidget):
    """置顶悬浮窗：字幕区 + 问题标题 + 流式答案（spec §2 展示形态）。"""

    def __init__(self) -> None:
        super().__init__(None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setWindowOpacity(0.92)
        self.resize(460, 320)
        self._subtitles: list[str] = []
        self._drag_offset: QPoint | None = None

        lay = QVBoxLayout(self)
        self.subtitle_label = QLabel("(等待音频…)")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setStyleSheet("color:#888; font-size:12px;")
        self.question_label = QLabel("")
        self.question_label.setWordWrap(True)
        self.question_label.setStyleSheet("font-weight:bold; font-size:13px;")
        self.answer_view = QTextBrowser()
        self.answer_view.setOpenExternalLinks(False)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#c0392b; font-size:12px;")
        lay.addWidget(self.subtitle_label)
        lay.addWidget(self.question_label)
        lay.addWidget(self.answer_view, stretch=1)
        lay.addWidget(self.status_label)

    def set_subtitle(self, text: str) -> None:
        self._subtitles = (self._subtitles + [text])[-3:]
        self.subtitle_label.setText("\n".join(self._subtitles))

    def begin_answer(self, question: str) -> None:
        self.question_label.setText(question)
        self.answer_view.clear()
        self.status_label.setText("")

    def append_answer(self, chunk: str) -> None:
        self.answer_view.insertPlainText(chunk)
        sb = self.answer_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def end_answer(self) -> None:
        self.status_label.setText("")

    def show_status(self, text: str) -> None:
        self.status_label.setText(text)

    # --- 拖动 ---
    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_offset is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._drag_offset = None
```

- [ ] **Step 4: 跑测试通过**

Run: `python -m pytest tests/test_overlay.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add app/overlay.py tests/test_overlay.py
git commit -m "feat: 置顶悬浮窗（字幕滚动/流式答案/拖动）"
```

---

### Task 16: 主窗口（知识库管理+设置+会话控制）+ 热键 + 托盘 + main.py 组装

**Files:**
- Create: `app/main_window.py`, `app/hotkey.py`, `app/tray.py`, `main.py`
- Test: `tests/test_main_window.py`（pytest-qt，用 fakes 不碰模型/网络）

**Interfaces:**
- Consumes: 全部前序任务的接口；`downloader.ensure_models`（Task 17 将提供——本任务先写 `models_ready(cfg) -> bool` 检查目录存在性，缺失时提示去 Task 17 的向导）
- Produces: 可启动的 `main.py`；`MainWindow(cfg, kb_factory, rag_factory)`（依赖注入便于测试）；`HotkeyBridge`（`pressed = Signal()`，keyboard 库回调线程→Qt 信号）；`GenerateWorker(QThread)`（`chunk = Signal(str)`, `done = Signal()`, `failed = Signal(str)`，后台消费 `RagService.trigger()`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_main_window.py
import pytest
from PySide6.QtWidgets import QApplication
from app.main_window import MainWindow

class FakeRag:
    def __init__(self):
        self.buffer = _FakeBuffer()
        self.triggered = 0
    def trigger(self):
        self.triggered += 1
        yield "**答**案"

class _FakeBuffer:
    entries = []

class FakeKb:
    def list_files(self):
        return [("a.md", 3), ("b.md", 5)]
    def delete_file(self, name):
        return 1

@pytest.fixture
def win(qtbot, tmp_path):
    from core.config import default_config
    import core.config as cc
    cc.app_root = lambda: tmp_path  # 重定向根目录
    cfg = default_config()
    rag, kb = FakeRag(), FakeKb()
    w = MainWindow(cfg, kb_factory=lambda: kb, rag_factory=lambda: rag)
    qtbot.addWidget(w)
    return w, rag

def test_kb_table_lists_files(win):
    w, _ = win
    model = w.kb_table.model()
    assert model.rowCount() == 2
    assert model.item(0, 0).text() in ("a.md", "b.md")

def test_hotkey_signal_triggers_generate(win, qtbot):
    w, rag = win
    w._on_hotkey()
    assert rag.triggered == 1

def test_generate_worker_streams_to_overlay(win, qtbot):
    w, rag = win
    w._on_hotkey()
    qtbot.waitUntil(lambda: "答" in w.overlay.answer_view.toPlainText(), timeout=3000)

def test_delete_selected_file(win, qtbot):
    w, _ = win
    w.kb_table.selectRow(0)
    w._delete_selected()
    assert w.kb_table.model().rowCount() == 1

def test_settings_roundtrip(win, qtbot, tmp_path):
    w, _ = win
    w.base_url_edit.setText("https://api.x.com/v1")
    w.model_edit.setText("m1")
    w._save_settings()
    from core.config import load_config
    cfg2 = load_config(w.cfg.data_dir)
    assert cfg2.llm_base_url == "https://api.x.com/v1" and cfg2.llm_model == "m1"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_main_window.py -v` → FAIL

- [ ] **Step 3: 实现**

```python
# app/hotkey.py
from PySide6.QtCore import QObject, Signal


class HotkeyBridge(QObject):
    """keyboard 库的回调跑在独立线程；经 Qt 信号（队列连接） marshal 到主线程。"""
    pressed = Signal()

    def __init__(self, combo: str = "ctrl+alt+space") -> None:
        super().__init__()
        import keyboard
        keyboard.add_hotkey(combo, self.pressed.emit)

    def stop(self) -> None:
        import keyboard
        keyboard.unhook_all()
```

```python
# app/workers.py —— 后台生成 worker。所有 UI 更新经信号（队列连接）回主线程，
# worker 线程内绝不直接碰 QWidget。
from PySide6.QtCore import QThread, Signal


class GenerateWorker(QThread):
    chunk = Signal(str)      # 答案增量
    question = Signal(str)   # 提取到的问题（悬浮窗标题）
    done = Signal()
    failed = Signal(str)

    def __init__(self, rag) -> None:
        super().__init__()
        self.rag = rag

    def run(self) -> None:
        try:
            got_question = False
            for delta in self.rag.trigger():
                if not got_question:  # 首个 yield 前问题已提取完毕
                    self.question.emit(getattr(self.rag, "last_question", ""))
                    got_question = True
                if delta:
                    self.chunk.emit(delta)
            if not got_question:
                self.question.emit("")
            self.done.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
```

```python
# app/main_window.py（核心逻辑；样式从简）
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QPushButton, QTableView, QVBoxLayout, QWidget)

from app.overlay import OverlayWindow


class MainWindow(QMainWindow):
    def __init__(self, cfg, kb_factory, rag_factory) -> None:
        super().__init__()
        self.cfg = cfg
        self._kb_factory = kb_factory
        self._rag_factory = rag_factory
        self._rag = None
        self._recorder = None  # main.py 注入；未注入时导出按钮禁用逻辑依赖它
        self.overlay = OverlayWindow()
        self._worker = None
        self.setWindowTitle("面试助手")
        self.resize(720, 480)
        self._build_ui()
        self._reload_kb()

    def _build_ui(self) -> None:
        central = QWidget()
        lay = QVBoxLayout(central)
        # 知识库区
        self.kb_table = QTableView()
        self.kb_model = QStandardItemModel(0, 2)
        self.kb_model.setHorizontalHeaderLabels(["文件", "块数"])
        self.kb_table.setModel(self.kb_model)
        lay.addWidget(QLabel("知识库（上传 md）"))
        lay.addWidget(self.kb_table)
        row = QHBoxLayout()
        upload_btn = QPushButton("上传 md…")
        upload_btn.clicked.connect(self._upload)
        del_btn = QPushButton("删除选中")
        del_btn.clicked.connect(self._delete_selected)
        export_btn = QPushButton("导出面试记录")
        export_btn.clicked.connect(self._export_session)
        start_btn = QPushButton("开始监听")
        start_btn.clicked.connect(self.start_listening)
        for b in (upload_btn, del_btn, export_btn, start_btn):
            row.addWidget(b)
        lay.addLayout(row)
        # 设置区
        lay.addWidget(QLabel("LLM 设置（OpenAI 兼容）"))
        form = QHBoxLayout()
        self.base_url_edit = QLineEdit(self.cfg.llm_base_url)
        self.api_key_edit = QLineEdit(self.cfg.llm_api_key)
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.model_edit = QLineEdit(self.cfg.llm_model)
        for lbl, w in (("base_url", self.base_url_edit), ("api_key", self.api_key_edit), ("模型", self.model_edit)):
            form.addWidget(QLabel(lbl)); form.addWidget(w, stretch=1)
        save_btn = QPushButton("保存设置")
        save_btn.clicked.connect(self._save_settings)
        form.addWidget(save_btn)
        lay.addLayout(form)
        self.setCentralWidget(central)

    def _reload_kb(self) -> None:
        self.kb_model.setRowCount(0)
        for name, n in self._kb_factory().list_files():
            self.kb_model.appendRow([QStandardItem(name), QStandardItem(str(n))])

    def _upload(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "选择 md 文件", "", "Markdown (*.md)")
        kb = self._kb_factory()
        for f in files:
            try:
                kb.ingest_file(Path(f))
            except ValueError as exc:
                self.statusBar().showMessage(str(exc))
        self._reload_kb()

    def _delete_selected(self) -> None:
        idx = self.kb_table.currentIndex()
        if not idx.isValid():
            return
        name = self.kb_model.item(idx.row(), 0).text()
        self._kb_factory().delete_file(name)
        self._reload_kb()

    def _save_settings(self) -> None:
        from core.config import save_config
        self.cfg.llm_base_url = self.base_url_edit.text().strip()
        self.cfg.llm_api_key = self.api_key_edit.text().strip()
        self.cfg.llm_model = self.model_edit.text().strip()
        save_config(self.cfg)
        self.statusBar().showMessage("设置已保存")

    def _export_session(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "导出面试记录", "", "Markdown (*.md)")
        if path and self._recorder is not None:
            from pathlib import Path as P
            p = self._recorder.export_markdown(P(path))
            self.statusBar().showMessage(f"已导出 {p}")

    def start_listening(self) -> None:
        """Task 16 内先用 wav/无源方式跳过；完整接线在集成步（见 Step 4）。"""
        self.overlay.show()
        self.statusBar().showMessage("悬浮窗已显示")

    # --- 热键→生成 ---
    def _on_hotkey(self) -> None:
        from app.workers import GenerateWorker
        if self._worker is not None and self._worker.isRunning():
            return  # 上一轮未完成，忽略连按
        if self._rag is None:
            self._rag = self._rag_factory()
        self.overlay.show()
        self._worker = GenerateWorker(self._rag)
        self._worker.question.connect(self._on_question)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.done.connect(lambda: self.overlay.end_answer())
        self._worker.failed.connect(lambda m: self.overlay.show_status(f"生成失败：{m}，可重试"))
        self._worker.start()

    def _on_question(self, q: str) -> None:
        if q:
            self.overlay.begin_answer(q)
        else:
            self.overlay.show_status("未识别到问题（稍后再按）")

    def _on_chunk(self, delta: str) -> None:
        self.overlay.append_answer(delta)
```

```python
# main.py
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.hotkey import HotkeyBridge
from app.main_window import MainWindow
from app.overlay import OverlayWindow
from app.tray import create_tray
from core.config import default_config, load_config


def build_app():
    cfg = load_config(Path(__file__).parent / "data")
    cfg.ensure_dirs()
    from core.embedder import BgeEmbedder, HashEmbedder
    from core.kb import KnowledgeBase
    from core.rag import RagService
    from core.generator import LLMClient
    from core.retriever import Retriever
    from core.session import SessionRecorder
    models_ok = (cfg.models_dir / "SenseVoiceSmall").exists()
    embedder = BgeEmbedder(cfg.models_dir / "bge-small-zh-v1.5") if models_ok else HashEmbedder()
    kb = KnowledgeBase(cfg.kb_path, embedder)
    llm = LLMClient(cfg.llm_base_url, cfg.llm_api_key, cfg.llm_model)
    recorder = SessionRecorder()
    rag = RagService(Retriever(kb, embedder), llm, recorder=recorder)
    return cfg, kb, rag, recorder


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    cfg, kb, rag, recorder = build_app()
    win = MainWindow(cfg, kb_factory=lambda: kb, rag_factory=lambda: rag)
    win._recorder = recorder
    win.show()
    bridge = HotkeyBridge(cfg.hotkey)
    bridge.pressed.connect(win._on_hotkey)
    tray = create_tray(win)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
```

```python
# app/tray.py
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def create_tray(win) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(QIcon(), parent=win)  # TODO(Task 18): 换真实图标
    menu = QMenu()
    show = QAction("显示主窗口", win)
    show.triggered.connect(win.show)
    quit_ = QAction("退出", win)
    quit_.triggered.connect(win.close)
    menu.addAction(show)
    menu.addAction(quit_)
    tray.setContextMenu(menu)
    tray.setToolTip("面试助手")
    tray.show()
    return tray
```

（tray.py 中 `QIcon()` 空图标占位在 Task 18 替换为 `QIcon("assets/icon.svg")`，并随包携带 assets。）

- [ ] **Step 4: 跑测试通过 + 手工接线验证**

Run: `python -m pytest tests/test_main_window.py tests/test_rag.py -v` → PASS

手工：`python main.py`（无模型时 HashEmbedder 降级路径可启动），悬浮窗显示、`ctrl+alt+space` 触发 FakeLLM 不适用——真链路在 Task 17 后联调。

- [ ] **Step 5: 提交**

```bash
git add app/ main.py tests/test_main_window.py core/rag.py tests/test_rag.py
git commit -m "feat: 主窗口/热键/托盘/流式生成接线（依赖注入可测）"
```

---

### Task 17: 模型下载向导 + 完整监听接线（联调任务）

**Files:**
- Create: `core/downloader.py`, `app/wizard.py`
- Modify: `app/main_window.py`（`start_listening` 接 LiveAudioSource+FunasrTranscriber+AudioPipeline；托盘/主窗口加"下载模型"入口）
- Test: `tests/test_downloader.py`（mock 下载函数）

**Interfaces:**
- Consumes: `AppConfig.models_dir`（Task 1）、`AudioPipeline`（Task 14）、`LiveAudioSource`（Task 12）、`FunasrTranscriber`（Task 13）
- Produces: `ensure_models(models_dir: Path, log: Callable[[str], None]) -> None`（下载 4 组模型：modelscope 的 SenseVoiceSmall/fsmn-vad/ct-punc + HF 的 bge-small-zh-v1.5；逐项调用前 emit 日志行）；`models_ready(models_dir) -> bool`；`ModelWizard(QDialog)`（日志区+开始按钮，QThread 跑 `ensure_models`）。`MainWindow.start_listening()` 组装真实管线。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_downloader.py
from pathlib import Path
from core import downloader

def test_models_ready_false_then_true(tmp_path, monkeypatch):
    assert downloader.models_ready(tmp_path) is False
    for sub in ("SenseVoiceSmall", "fsmn-vad", "ct-punc", "bge-small-zh-v1.5"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    assert downloader.models_ready(tmp_path) is True

def test_ensure_models_downloads_all(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(downloader, "_download_modelscope",
                        lambda repo, dest, log: calls.append(("ms", repo, dest)) or dest.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(downloader, "_download_hf",
                        lambda repo, dest, log: calls.append(("hf", repo, dest)) or dest.mkdir(parents=True, exist_ok=True))
    logs = []
    downloader.ensure_models(tmp_path, logs.append)
    repos = {c[1] for c in calls}
    assert any("SenseVoiceSmall" in r for r in repos)
    assert any("bge-small-zh-v1.5" in r for r in repos)
    assert any("开始下载" in l for l in logs)

def test_ensure_models_skips_existing(tmp_path, monkeypatch):
    (tmp_path / "SenseVoiceSmall").mkdir()
    n = []
    monkeypatch.setattr(downloader, "_download_modelscope",
                        lambda repo, dest, log: n.append(1) or dest.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(downloader, "_download_hf",
                        lambda repo, dest, log: n.append(1) or dest.mkdir(parents=True, exist_ok=True))
    downloader.ensure_models(tmp_path, lambda *_: None)
    assert len(n) == 3  # 只下载缺失的 3 个
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_downloader.py -v` → FAIL

- [ ] **Step 3: 实现**

```python
# core/downloader.py
import os
from pathlib import Path
from typing import Callable

MS_REPOS = {
    "SenseVoiceSmall": "iic/SenseVoiceSmall",
    "fsmn-vad": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    "ct-punc": "iic/punc_ct-transformer_cn-en-common-vocab471067-large",
}
HF_REPOS = {"bge-small-zh-v1.5": "BAAI/bge-small-zh-v1.5"}


def models_ready(models_dir: Path) -> bool:
    return all((models_dir / name).exists() for name in [*MS_REPOS, *HF_REPOS])


def _download_modelscope(repo: str, dest: Path, log: Callable[[str], None]) -> None:
    from modelscope import snapshot_download
    snapshot_download(repo, local_dir=str(dest))


def _download_hf(repo: str, dest: Path, log: Callable[[str], None]) -> None:
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    from huggingface_hub import snapshot_download
    snapshot_download(repo, local_dir=str(dest))


def ensure_models(models_dir: Path, log: Callable[[str], None]) -> None:
    """逐项下载缺失模型；已存在跳过；snapshot 自带断点续传。"""
    models_dir.mkdir(parents=True, exist_ok=True)
    for name, repo in {**MS_REPOS, **HF_REPOS}.items():
        dest = models_dir / name
        if dest.exists():
            log(f"[跳过] {name} 已存在")
            continue
        log(f"[开始下载] {repo} → {dest}")
        fn = _download_modelscope if name in MS_REPOS else _download_hf
        fn(repo, dest, log)
        log(f"[完成] {name}")
```

```python
# app/wizard.py
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QPushButton, QTextEdit, QVBoxLayout)

from core.downloader import ensure_models


class _DownloadThread(QThread):
    line = Signal(str)
    finished_ok = Signal()

    def __init__(self, models_dir) -> None:
        super().__init__()
        self.models_dir = models_dir

    def run(self) -> None:
        ensure_models(self.models_dir, self.line.emit)
        self.finished_ok.emit()


class ModelWizard(QDialog):
    def __init__(self, cfg, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("下载模型（约 0.5 GB，镜像 hf-mirror.com）")
        self.resize(600, 400)
        lay = QVBoxLayout(self)
        self.log_view = QTextEdit(readOnly=True)
        btn = QPushButton("开始下载")
        btn.clicked.connect(self._go)
        lay.addWidget(self.log_view)
        lay.addWidget(btn)

    def _go(self) -> None:
        self._t = _DownloadThread(self.cfg.models_dir)
        self._t.line.connect(self.log_view.append)
        self._t.finished_ok.connect(lambda: self.log_view.append("全部完成，可关闭"))
        self._t.start()
```

`MainWindow.start_listening()` 最终实现（替换 Task 16 的占位）：

```python
`MainWindow` 增加两个类级信号（管线线程 emit → 队列连接到主线程槽，与 HotkeyBridge 同模式）：

```python
    # 类体中定义（与 __init__ 同级）：
    from PySide6.QtCore import Signal
    subtitle_sig = Signal(str)
    audio_error_sig = Signal(str)

    # __init__ 中接线：
    #   self.subtitle_sig.connect(lambda t: self.overlay.set_subtitle(t))
    #   self.audio_error_sig.connect(lambda m: self.overlay.show_status(f"音频异常：{m}，请重新开始监听"))

    _pipeline = None

    def start_listening(self) -> None:
        from core.capture import LiveAudioSource
        from core.pipeline import AudioPipeline
        from core.transcriber import FunasrTranscriber
        if self._pipeline is not None:
            self._pipeline.stop()
            self._pipeline = None
            self.statusBar().showMessage("已停止监听")
            return
        transcriber = FunasrTranscriber(self.cfg.models_dir)
        source = LiveAudioSource()
        rag = self._rag or self._rag_factory()
        self._pipeline = AudioPipeline(source, transcriber, rag.buffer, recorder=self._recorder)
        self._pipeline.on_subtitle = self.subtitle_sig.emit  # 管线线程安全 emit
        self._pipeline.on_error = self.audio_error_sig.emit
        self._pipeline.start()
        self.overlay.show()
        self.statusBar().showMessage("监听中：系统音频 → 字幕；Ctrl+Alt+Space 触发回答")
```

- [ ] **Step 4: 跑测试 + 真机联调**

Run: `python -m pytest tests/test_downloader.py -v` → PASS

真机联调清单（手工，需已下载模型+配置 LLM key）：
1. `python main.py` → 主窗口出现
2. 托盘/按钮"下载模型"向导可用
3. 上传一份八股 md → 表格出现
4. 开始监听 → 播放一段含问题的会议录音/视频 → 悬浮窗出字幕
5. `Ctrl+Alt+Space` → ≤2s 出首字，答案为口语化分点
6. 导出面试记录 → md 含问答与来源

- [ ] **Step 5: 提交**

```bash
git add core/downloader.py app/wizard.py app/main_window.py tests/test_downloader.py
git commit -m "feat: 模型下载向导与真实监听接线（联调通过）"
```

---

### Task 18: PyInstaller 打包 + README

**Files:**
- Create: `interview-assistant.spec`, `assets/icon.svg`, `README.md`
- Modify: `app/tray.py`（真实图标）

**Interfaces:**
- Consumes: 全部
- Produces: 可分发的 `dist/interview-assistant/` 目录。

- [ ] **Step 1: 写 spec 文件**

```python
# interview-assistant.spec
# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("assets", "assets")],
    hiddenimports=[
        "funasr", "funasr.auto", "sqlite_vec",
        "sentence_transformers", "pyaudiowpatch",
        "keyboard", "torch", "transformers",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name="interview-assistant", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
              name="interview-assistant")
```

- [ ] **Step 2: 打包并验证**

Run: `pip install pyinstaller && pyinstaller interview-assistant.spec`
Expected: `dist/interview-assistant/interview-assistant.exe` 生成

手工验证：把 `dist/interview-assistant/` 拷到独立目录，放入/下载 `models/`、`data/`，双击 exe：主窗口、悬浮窗、热键全链路可用。

- [ ] **Step 3: 写 README**

覆盖：项目简介、截图占位、安装（源码运行 + 打包版）、模型首次下载说明（0.5GB、hf-mirror）、LLM 配置示例（DeepSeek/OpenAI 兼容）、热键说明、路径配置（models/ data/ 可在设置改）、开源协议（建议 MIT）、免责声明（仅供个人学习与面试练习用途，使用者自担合规风险）。

- [ ] **Step 4: 全量回归**

Run: `python -m pytest -v`（默认跳过 model 标记）→ 全 PASS
Run: `python -m pytest -m model -v`（本机有模型时）→ PASS

- [ ] **Step 5: 提交**

```bash
git add interview-assistant.spec assets/ README.md app/tray.py
git commit -m "chore: PyInstaller 打包配置与 README"
```

---

## 任务依赖图

```
Task1(配置) ─→ Task17(向导)
Task2(切分) ─→ Task4(存储) ─→ Task5(检索) ─→ Task10(RAG编排) ─→ Task16(主窗口) ─→ Task17(接线联调) ─→ Task18(打包)
Task3(Embedder) ↗ Task4, Task5
Task6(缓冲/提取) ↗ Task10, Task14
Task7(记录导出) ↗ Task10, Task16
Task8+9(Prompt/LLM) ↗ Task10
Task11(wav源) → Task12(live源) → Task14(管线) ↗ Task16
Task13(转写器) ↗ Task14
Task15(悬浮窗) ↗ Task16
```

串行执行按 Task 编号即可（编号已拓扑排序）；并行执行时按依赖图分四条泳道：知识库线(2→3→4→5)、生成线(8→9)、音频线(11→12→13→14)、UI 线(15)，最后 10/16/17/18 汇合。
