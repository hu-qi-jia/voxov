# 全话轮路由 + Retro Terminal UI 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ① 实质话轮全部触发生成、按距离阈值路由检索（refs/generic/statement 三模式）；② 整壳重构为 retro terminal 暗色风（原生 Qt + QSS，删除 qfluentwidgets/彩排/向导/设置弹窗）。

**Architecture:** core 层先落路由（纯函数分类 → 检索真距离 → prompt 三模式 → rag 路由），app 层后换壳（icons → theme → settings 页 → 对话流 → 主窗 → 清理打包）。core 测试先行锁行为，UI 每任务以测试+截图验收。

**Tech Stack:** PySide6（原生 Widgets + QtSvg）、sqlite-vec、httpx；测试 pytest + pytest-qt。

**Spec:**
- `docs/superpowers/specs/2026-10-04-turn-trigger-routing-design.md`（路由）
- `docs/superpowers/specs/2026-10-05-retro-terminal-ui-design.md`（UI）
- 视觉基准：`docs/design/2026-10-04-retro-terminal-preview.html`

## Global Constraints

- 禁止再引入 qfluentwidgets；UI 一律原生 Widgets + `app/theme.py` 的 QSS。
- Tokens 逐字采用 UI spec §2：bg `#0a0a0a`、bg_raise `#111111`、bg_hover `#151515`、fg `#e6e6e6`、fg_dim `#9a9a9a`、fg_faint `#5c5c5c`、line `#2a2a2a`、line_soft `#1e1e1e`、accent `#5af78e`、warn `#e3b341`、danger `#f85149`。
- 零圆角、零阴影、零渐变。
- 全中文 UI 文案；窗标题 `voxov`；打包 exe 名保持 `notes-viewer`（对外中性）。
- 检索 k=5（用户复核维持原值）；`REF_DIST_MAX = 1.05`。
- 每个任务结束全量相关测试绿并独立提交；提交信息用 `feat:`/`refactor:`/`chore:`/`test:` 前缀。
- 运行测试统一用 `./.venv/Scripts/python.exe -m pytest`。

## Review Focus

1. **空/纯标点话轮进 classify_turn** → 必须 chatter 且不抛错（Task 1 测试 pin）。
2. **热键非法保存** → 拒绝落盘、不崩、状态行提示（Task 7 测试 pin）。
3. **HashEmbedder 降级（距离不可信）** → 有检索结果即注入，与旧行为一致（Task 4 测试 pin）。
4. **chatter 词误杀短技术句**（如「我们继续看看Redis持久化」）→ 去除 chatter 词后残余 ≥4 字不判 chatter（Task 1 测试 pin）。
5. **下载中断后重试** → 设置页按钮重新可用、再次点击重发请求（Task 7 测试 pin）。

---

### Task 1: 话轮分类引擎 `classify_turn`

**Files:**
- Modify: `core/heuristics.py`
- Test: `tests/test_heuristics.py`

**Interfaces:**
- Produces: `classify_turn(text: str) -> str`，返回 `'chatter' | 'open' | 'question' | 'statement'`；`looks_like_question` 原样保留。

- [ ] **Step 1: 追加失败测试到 `tests/test_heuristics.py`**

```python
# --- 全话轮分类（路由 spec §4 矩阵） ---
from core.heuristics import classify_turn

def test_spec_matrix():
    cases = {
        "嗯好的": "chatter",
        "那我们继续下一题": "chatter",
        "好的我们了解一下": "chatter",
        "你了解 Redis 吗": "question",
        "介绍一下你的项目经历": "open",
        "讲讲你的职业规划": "open",
        "Redis 持久化怎么做的": "question",
        "我们团队主要做 ToB 业务": "statement",
    }
    for text, want in cases.items():
        assert classify_turn(text) == want, (text, classify_turn(text))

def test_empty_and_punctuation_are_chatter():
    assert classify_turn("") == "chatter"
    assert classify_turn("。。。！？") == "chatter"
    assert classify_turn(None) == "chatter"

def test_chatter_words_do_not_kill_short_tech_sentence():
    assert classify_turn("我们继续看看Redis持久化") == "question"

def test_long_statement_falls_through():
    assert classify_turn("我们这个团队这两年一直在做云端协同方向的产品落地") == "statement"
```

- [ ] **Step 2: 跑测试确认红**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_heuristics.py -q`
Expected: FAIL，`ImportError: cannot import name 'classify_turn'`

- [ ] **Step 3: 实现 `core/heuristics.py`（文件末尾追加）**

```python
# --- 全话轮分类（路由 spec §4）：先到先得 chatter → open → question → statement ---
CHATTER_WORDS = ("嗯", "好的", "好的啊", "行", "谢谢", "辛苦", "下一题", "继续",
                 "明白", "清楚", "不错", "可以", "没问题", "开始吧", "等一下", "稍等")
STRONG_Q_WORDS = ("什么", "怎么", "怎样", "如何", "为什么", "为何", "哪些", "哪个")
OPEN_ENDED_WORDS = ("自我介绍", "项目经历", "项目亮点", "职业规划", "离职原因",
                    "优缺点", "你的优势", "性格", "团队协作", "加班", "期望薪资",
                    "聊聊你", "说说你", "谈谈你", "遇到的困难", "失败经历", "成就感")
_WORD_RE = re.compile(r"[\w一-鿿]")


def classify_turn(text: str | None) -> str:
    t = (text or "").strip()
    if not _WORD_RE.search(t):
        return "chatter"                      # 空/纯标点兜底
    if len(t) < 8:
        return "chatter"                      # 寒暄/短反馈几乎低于此线
    open_hit = any(k in t for k in OPEN_ENDED_WORDS)
    strong_q = t.endswith(("？", "?")) or any(k in t for k in STRONG_Q_WORDS)
    if len(t) < 16 and not open_hit and not strong_q:
        residual = t
        for w in sorted(CHATTER_WORDS, key=len, reverse=True):
            residual = residual.replace(w, "")
        if len(residual.strip()) < 4 or t.startswith(CHATTER_WORDS):
            return "chatter"
    if open_hit:
        return "open"
    if strong_q or looks_like_question(t):
        return "question"
    return "statement"
```

注意：文件顶部需有 `import re`（当前没有）。

- [ ] **Step 4: 跑测试确认绿**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_heuristics.py -q`
Expected: 全 PASS（含既有 looks_like_question 用例）

- [ ] **Step 5: Commit**

```bash
git add core/heuristics.py tests/test_heuristics.py
git commit -m "feat: 话轮四分类引擎 classify_turn（chatter/open/question/statement）"
```

---

### Task 2: 检索器透传真距离

**Files:**
- Modify: `core/retriever.py`
- Test: `tests/test_retriever.py`

**Interfaces:**
- Produces: `Retriever.last_top_distance: float | None`（向量路最优 L2 距离，无向量结果为 None，每次 retrieve 前重置）；`Retriever.distances_reliable: bool`（embedder 是 OnnxEmbedder 才 True）。

- [ ] **Step 1: 追加失败测试到 `tests/test_retriever.py`**

```python
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
    assert r.last_top_distance is not None or r.last_top_distance is None  # 不抛错即可
    r.retrieve("", k=3)                              # 空查询必须重置
    assert r.last_top_distance is None

def test_last_top_distance_none_on_empty_kb(tmp_path):
    from core.kb import KnowledgeBase
    r = Retriever(KnowledgeBase(tmp_path / "e.db", HashEmbedder(dim=512)),
                  HashEmbedder(dim=512))
    r.retrieve("任何问题", k=5)
    assert r.last_top_distance is None
```

- [ ] **Step 2: 跑测试确认红**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_retriever.py -q`
Expected: FAIL，`AttributeError: 'Retriever' object has no attribute 'distances_reliable'`

- [ ] **Step 3: 实现 `core/retriever.py`**

`Retriever` 类整体替换为：

```python
class Retriever:
    def __init__(self, kb: KnowledgeBase, embedder: Embedder) -> None:
        self.kb = kb
        self.embedder = embedder
        self.last_top_distance: float | None = None

    @property
    def distances_reliable(self) -> bool:
        from core.embedder import OnnxEmbedder
        return isinstance(self.embedder, OnnxEmbedder)

    def retrieve(self, query: str, k: int = 5) -> list[Retrieved]:
        query = query.strip()
        self.last_top_distance = None
        if not query:
            return []
        vec = self.embedder.encode_query(query)
        vec_hits = self.kb.vector_search(vec, k=k)          # [(cid, L2 dist)]
        if vec_hits:
            self.last_top_distance = min(d for _, d in vec_hits)
        rankings = [
            [cid for cid, _ in vec_hits],
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

（`rrf_fuse`、`Retrieved`、文件头 import 不变。）

- [ ] **Step 4: 跑测试确认绿**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_retriever.py -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add core/retriever.py tests/test_retriever.py
git commit -m "feat: 检索器透传向量最优 L2 距离与距离可靠性标记"
```

---

### Task 3: 生成三模式 prompt

**Files:**
- Modify: `core/generator.py`
- Test: `tests/test_prompt.py`

**Interfaces:**
- Produces: `build_messages(question, contexts, history, mode="refs")`；mode ∈ `refs | generic | statement`；常量 `GENERIC_PROMPT`、`STATEMENT_PROMPT`。`SYSTEM_PROMPT` 逐字不变。

- [ ] **Step 1: 追加失败测试到 `tests/test_prompt.py`**

```python
# --- 三模式（路由 spec §6） ---
from core.generator import GENERIC_PROMPT, STATEMENT_PROMPT

def test_generic_mode_swaps_system_and_drops_refs():
    msgs = build_messages("介绍一下你的项目", CTX, [], mode="generic")
    assert msgs[0]["content"] == GENERIC_PROMPT
    assert "参考资料" not in msgs[1]["content"]
    assert "当前问题：介绍一下你的项目" in msgs[1]["content"]

def test_generic_prompt_forbids_fabricated_refs():
    assert "禁止" in GENERIC_PROMPT and "资料" in GENERIC_PROMPT

def test_statement_mode_uses_speaker_label():
    msgs = build_messages("我们团队主要做 ToB 业务", [], [], mode="statement")
    assert msgs[0]["content"] == STATEMENT_PROMPT
    assert "当前面试官发言：我们团队主要做 ToB 业务" in msgs[1]["content"]
    assert "参考资料" not in msgs[1]["content"]

def test_refs_mode_is_default_and_unchanged():
    msgs = build_messages("RDB是什么", CTX, [])
    assert msgs[0]["content"] == SYSTEM_PROMPT
    assert "[资料1]" in msgs[1]["content"]
```

- [ ] **Step 2: 跑测试确认红**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_prompt.py -q`
Expected: FAIL，`ImportError: cannot import name 'GENERIC_PROMPT'`

- [ ] **Step 3: 实现 `core/generator.py`**

`SYSTEM_PROMPT` 之后追加两个常量，`build_messages` 整体替换：

```python
GENERIC_PROMPT = ("你是面试实时辅助。知识库中没有相关资料，凭你自己的知识与经历回答。"
    "输出口语化中文，像求职者当场回答，可直接照读，禁止书面腔和套话开场。"
    "分点输出，每点一句完整的话，关键词加粗。按重要性排序，最重要的点放第一条。"
    "共 4-6 点，全篇不超过 250 字。禁止虚构或引用任何资料。")

STATEMENT_PROMPT = ("你是面试实时辅助。面试官正在做陈述或铺垫，不是提问。"
    "给出求职者此刻最该说的自然回应：一两句话即可，口语化、可直接照读，"
    "顺势带出自己的相关经验或优势。不要分点，不要超过 80 字。")


def build_messages(question: str, contexts: list, history: list[tuple[str, str]],
                   mode: str = "refs") -> list[dict]:
    if mode == "statement":
        system = STATEMENT_PROMPT
    elif mode == "generic":
        system = GENERIC_PROMPT
    else:
        system = SYSTEM_PROMPT
    parts: list[str] = []
    if mode == "refs" and contexts:
        refs = "\n\n".join(
            f"[资料{i+1}] {c.source_file} › {c.heading_path}\n{c.text}"
            for i, c in enumerate(contexts))
        parts.append(f"参考资料：\n{refs}")
    for q, a in history[-2:]:
        parts.append(f"之前的问题：{q}\n之前的回答：{a}")
    label = "当前面试官发言" if mode == "statement" else "当前问题"
    parts.append(f"{label}：{question}")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
```

- [ ] **Step 4: 跑测试确认绿**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_prompt.py -q`
Expected: 全 PASS（既有 verbatim 用例不动）

- [ ] **Step 5: Commit**

```bash
git add core/generator.py tests/test_prompt.py
git commit -m "feat: 生成三模式 prompt（refs/generic/statement）"
```

---

### Task 4: rag 路由 + `extract_turn` 改名 + worker 通知透传

**Files:**
- Modify: `core/session.py:39`（函数改名）、`core/rag.py`（重写）、`app/workers.py`（notice 透传）
- Test: `tests/test_session.py`、`tests/test_rag.py`、`tests/test_review_fixes.py`

**Interfaces:**
- Consumes: Task 1 `classify_turn`、Task 2 `last_top_distance`/`distances_reliable`、Task 3 `build_messages(mode=)`。
- Produces: `extract_turn(entries, now)`（原 `extract_question` 改名，行为不变）；`RagService.last_notice: str`、`RagService.last_turn_class: str`、`RagService.last_had_refs: bool`（=use_refs）；类常量 `RagService.REF_DIST_MAX = 1.05`。

- [ ] **Step 1: 改名 + 失败测试**

`core/session.py`：`def extract_question(` 改名 `def extract_turn(`，docstring 中「问题」改「话轮文本」。`tests/test_session.py` 中 4 处 `extract_question` 同步改 `extract_turn`（含 import 行）。

追加到 `tests/test_rag.py`：

```python
# --- 路由（spec §5）：statement 不检索；距离阈值；FTS 越过；Hash 降级 ---
from core.retriever import Retrieved

def _feed(svc, text, sec_ago=6):
    now = time.time()
    svc.buffer.add_transcript(TranscriptEntry(now - sec_ago - 2, now - sec_ago, text))

def test_statement_turn_skips_retrieval():
    calls = {"retrieve": 0}
    class R:
        distances_reliable = False
        last_top_distance = None
        def retrieve(self, q, k=5):
            calls["retrieve"] += 1
            return []
    llm = FakeLLM()
    svc = RagService(R(), llm)
    _feed(svc, "我们团队主要做 ToB 业务")
    out = "".join(svc.trigger())
    assert calls["retrieve"] == 0 and llm.calls == 1
    assert svc.last_notice == "接话 · 未用资料"
    assert "RDB" in out

def test_open_turn_without_refs_notices_open(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb.db", HashEmbedder(dim=512))
    svc = RagService(Retriever(kb, HashEmbedder(dim=512)), FakeLLM())
    _feed(svc, "介绍一下你的项目经历")
    "".join(svc.trigger())
    assert svc.last_notice == "开放题 · 未用资料"

class FakeRetriever:
    def __init__(self, contexts, reliable=True, top=0.9):
        self._c = contexts
        self.distances_reliable = reliable
        self.last_top_distance = top
    def retrieve(self, q, k=5):
        return self._c

_REF = Retrieved(chunk_id=1, text="RDB 定时快照 AOF 追加日志", heading_path="Redis",
                 source_file="redis.md", score=-1)

def test_reliable_distance_within_threshold_uses_refs():
    svc = RagService(FakeRetriever([_REF], reliable=True, top=0.9), FakeLLM())
    _feed(svc, "RDB持久化怎么做的")
    "".join(svc.trigger())
    assert svc.last_notice == "基于知识库 · 1 条资料"
    assert svc.last_had_refs is True

def test_reliable_distance_over_threshold_falls_to_generic():
    svc = RagService(FakeRetriever([_REF], reliable=True, top=1.3), FakeLLM())
    _feed(svc, "TCP三次握手详细过程是啥样的")
    "".join(svc.trigger())
    assert svc.last_notice == "通用回答（知识库无命中）"
    assert svc.last_had_refs is False

def test_fts_four_char_hit_overrides_distance():
    ctx = Retrieved(chunk_id=2, text="项目经历应当用 STAR 法则组织", heading_path="h",
                    source_file="s.md", score=-1)
    svc = RagService(FakeRetriever([ctx], reliable=True, top=1.3), FakeLLM())
    _feed(svc, "介绍一下你的项目经历")
    "".join(svc.trigger())
    assert svc.last_notice == "基于知识库 · 1 条资料"   # ≥4 字词项「项目经历」子串命中

def test_hash_embedder_keeps_legacy_behavior():
    svc = RagService(FakeRetriever([_REF], reliable=False, top=None), FakeLLM())
    _feed(svc, "RDB持久化怎么做的")
    "".join(svc.trigger())
    assert svc.last_had_refs is True                    # 有结果即注入（降级旧行为）
```

`tests/test_review_fixes.py` 两个用例改为透传语义（原 `test_worker_notice_when_no_refs`、`test_generic_answer_notice_shown_in_overlay` 删除）：

```python
def test_worker_notice_passthrough(qtbot):
    from app.workers import GenerateWorker
    class _R:
        last_question = "q"
        last_notice = "通用回答（知识库无命中）"
        def trigger(self):
            yield "a"
    wk = GenerateWorker(_R())
    got = []
    wk.notice.connect(got.append)
    wk.start()
    assert wk.wait(3000)
    qtbot.waitUntil(lambda: got == ["通用回答（知识库无命中）"], timeout=3000)

def test_generic_answer_notice_shown_in_chat(win, qtbot):
    w, rag = win
    rag.last_notice = "开放题 · 未用资料"
    w._on_hotkey()
    qtbot.waitUntil(lambda: w._chat_answer is not None
                    and "开放题" in w._chat_answer.note.text(), timeout=3000)
```

- [ ] **Step 2: 跑测试确认红**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_rag.py tests/test_session.py tests/test_review_fixes.py -q`
Expected: FAIL（`extract_turn` 不存在 / `last_notice` 属性缺失）

- [ ] **Step 3: 实现**

`core/rag.py` 全文替换：

```python
# core/rag.py —— 触发编排 v2：话轮分类 → 检索路由（距离阈值+FTS 越过）→ 三模式生成。
import re
import time
from typing import Iterator

from core.generator import LLMClient, build_messages
from core.heuristics import classify_turn
from core.retriever import Retriever
from core.session import SessionBuffer, SessionRecorder, extract_turn


def _fts_exact_hit(query: str, contexts: list) -> bool:
    """查询中 ≥4 字词项在任一检出 chunk 子串命中 → 越过距离阈值（防误杀）。"""
    toks = re.findall(r"[0-9A-Za-z_]{4,}|[一-鿿]{4,}", query)
    return any(tok in c.text for c in contexts for tok in toks)


class RagService:
    """热键/自动触发的完整编排：提取话轮 → 分类 → 检索路由 → 流式生成 → 记录。"""

    REF_DIST_MAX = 1.05   # sqlite-vec L2（单位向量）⇔ cos≥约0.45；实测后可调

    def __init__(self, retriever: Retriever, llm: LLMClient,
                 recorder: SessionRecorder | None = None) -> None:
        self.retriever = retriever
        self.llm = llm
        self.recorder = recorder
        self.buffer = SessionBuffer()
        self.history: list[tuple[str, str]] = []
        self.last_question: str = ""
        self.last_had_refs = True
        self.last_notice = ""
        self.last_turn_class = "statement"

    def trigger(self, now: float | None = None) -> Iterator[str]:
        self.last_notice = ""
        turn = extract_turn(self.buffer.entries, now or time.time())
        self.last_question = turn
        if not turn:
            self.last_had_refs = True
            yield ""          # 空话轮短路：不调 LLM
            return
        self.last_turn_class = classify_turn(turn)
        contexts: list = []
        if self.last_turn_class == "statement":
            use_refs = False                      # 陈述不检索（spec §5.2）
        else:
            contexts = self.retriever.retrieve(turn, k=5)
            reliable = getattr(self.retriever, "distances_reliable", False)
            if reliable:
                top = getattr(self.retriever, "last_top_distance", None)
                use_refs = bool(contexts) and (
                    (top is not None and top <= self.REF_DIST_MAX)
                    or _fts_exact_hit(turn, contexts))
            else:
                use_refs = bool(contexts)         # Hash 降级：维持旧行为
        self.last_had_refs = use_refs
        mode = ("statement" if self.last_turn_class == "statement"
                else "refs" if use_refs else "generic")
        if use_refs:
            self.last_notice = f"基于知识库 · {len(contexts)} 条资料"
        elif self.last_turn_class == "open":
            self.last_notice = "开放题 · 未用资料"
        elif self.last_turn_class == "question":
            self.last_notice = "通用回答（知识库无命中）"
        else:
            self.last_notice = "接话 · 未用资料"
        messages = build_messages(turn, contexts if use_refs else [],
                                  self.history, mode=mode)
        parts: list[str] = []
        for delta in self.llm.stream(messages):
            parts.append(delta)
            yield delta
        answer = "".join(parts)
        self.history.append((turn, answer))
        self.history = self.history[-5:]
        if self.recorder:
            self.recorder.add_qa(turn, contexts if use_refs else [], answer)
```

`app/workers.py` `GenerateWorker.run` 中，把 `last_had_refs is False` 分支替换为：

```python
            if not got_question:
                self.question.emit("")
            notice = getattr(self.rag, "last_notice", "")
            if got_question and notice:
                self.notice.emit(notice)
            self.done.emit()
```

- [ ] **Step 4: 跑测试确认绿**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_rag.py tests/test_session.py tests/test_review_fixes.py tests/test_prompt.py -q`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add core/session.py core/rag.py app/workers.py tests/test_rag.py tests/test_session.py tests/test_review_fixes.py
git commit -m "feat: 全话轮路由——statement 不检索、距离阈值+FTS 越过、三模式标注"
```

---

### Task 5: Lucide 图标基建

**Files:**
- Create: `assets/icons/{mic,square,upload,trash,download,save,file-text,x,refresh-cw}.svg`（9 枚）
- Create: `app/icons.py`
- Test: `tests/test_icons.py`

**Interfaces:**
- Produces: `icon(name: str, color: str = "#e6e6e6") -> QIcon`（未知名返回空 QIcon，绝不抛错）；`_svg_for(name, color) -> str`。

- [ ] **Step 1: 失败测试 `tests/test_icons.py`**

```python
# tests/test_icons.py —— Lucide 图标加载与着色
def test_icon_known_name_renders_non_null():
    from app.icons import icon
    assert not icon("mic").isNull()

def test_icon_unknown_name_returns_null_without_raise():
    from app.icons import icon
    assert icon("no-such-icon").isNull()

def test_icon_color_applied():
    from app.icons import _svg_for
    assert "#5af78e" in _svg_for("mic", "#5af78e")
    assert "currentColor" not in _svg_for("mic", "#5af78e")
```

- [ ] **Step 2: 红确认**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_icons.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.icons'`

- [ ] **Step 3: 写 9 枚 SVG**

统一模板（`stroke="currentColor"` 供替换着色；square 线帽贴合 1px 直线语言）：

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="square" stroke-linejoin="miter">PATHS</svg>
```

各文件 PATHS：
- `mic.svg`: `<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v3"/>`
- `square.svg`: `<rect x="6" y="6" width="12" height="12"/>`
- `upload.svg`: `<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>`
- `trash.svg`: `<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>`
- `download.svg`: `<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>`
- `save.svg`: `<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/>`
- `file-text.svg`: `<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>`
- `x.svg`: `<path d="M18 6 6 18"/><path d="m6 6 12 12"/>`
- `refresh-cw.svg`: `<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/>`

- [ ] **Step 4: 实现 `app/icons.py`**

```python
# app/icons.py —— Lucide（ISC）图标：QSvgRenderer 渲染、按 token 着色。
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ICON_DIR = Path(__file__).resolve().parents[1] / "assets" / "icons"


@lru_cache(maxsize=None)
def _svg_for(name: str, color: str) -> str:
    path = ICON_DIR / f"{name}.svg"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").replace("currentColor", color)


@lru_cache(maxsize=None)
def icon(name: str, color: str = "#e6e6e6") -> QIcon:
    svg = _svg_for(name, color)
    if not svg:
        return QIcon()
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    renderer.render(p)
    p.end()
    return QIcon(pm)
```

- [ ] **Step 5: 绿 + Commit**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_icons.py -q`
Expected: PASS

```bash
git add assets/icons app/icons.py tests/test_icons.py
git commit -m "feat: Lucide 图标基建（9 枚 vendored SVG + QSvgRenderer 着色 helper）"
```

---

### Task 6: theme.py 重写（retro terminal QSS）

**Files:**
- Modify: `app/theme.py`（全文替换）
- Test: `tests/test_theme.py`（全文替换）

**Interfaces:**
- Produces: `TOKENS`（键：bg/bg_raise/bg_hover/fg/fg_dim/fg_faint/line/line_soft/accent/warn/danger/font）；`build_qss() -> str`；`apply(app)`（设 QFont 等宽栈 + letterSpacing 0.5 + 全局 QSS）。

- [ ] **Step 1: 全文替换 `tests/test_theme.py`**

```python
# tests/test_theme.py —— retro terminal 设计系统：tokens 齐全、暗色取值、QSS 覆盖核心控件
from app.theme import TOKENS, build_qss


def test_tokens_complete():
    need = {"bg", "bg_raise", "bg_hover", "fg", "fg_dim", "fg_faint",
            "line", "line_soft", "accent", "warn", "danger", "font"}
    assert need <= set(TOKENS)


def test_terminal_dark_values():
    assert TOKENS["bg"] == "#0a0a0a"
    assert TOKENS["fg"] == "#e6e6e6"
    assert TOKENS["accent"] == "#5af78e"
    assert TOKENS["line"] == "#2a2a2a"
    assert TOKENS["danger"] == "#f85149"


def test_font_stack_is_mono():
    assert "Cascadia Mono" in TOKENS["font"]
    assert "Microsoft YaHei UI" in TOKENS["font"]


def test_qss_covers_core_widgets_and_states():
    qss = build_qss()
    for sel in ("QMainWindow", "QPushButton", "QPushButton[accent=\"true\"]",
                "QLineEdit", "QComboBox", "QCheckBox::indicator:checked",
                "QProgressBar::chunk", "QTableView::item:selected",
                "QTextBrowser#answer", "QWidget#statusline", "QPushButton#nav_tab:checked"):
        assert sel in qss, f"QSS 缺少 {sel}"
```

- [ ] **Step 2: 红**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_theme.py -q`
Expected: FAIL（tokens 键不匹配）

- [ ] **Step 3: 全文替换 `app/theme.py`**

```python
# app/theme.py —— 设计系统 v4：retro terminal 暗色。
# 近黑底 / 磷光绿强调 / 1px 直线 / 等宽字栈；禁圆角、阴影、渐变。
TOKENS = {
    "bg":        "#0a0a0a",
    "bg_raise":  "#111111",
    "bg_hover":  "#151515",
    "fg":        "#e6e6e6",
    "fg_dim":    "#9a9a9a",
    "fg_faint":  "#5c5c5c",
    "line":      "#2a2a2a",
    "line_soft": "#1e1e1e",
    "accent":    "#5af78e",
    "warn":      "#e3b341",
    "danger":    "#f85149",
    "font":      "'Cascadia Mono', 'Consolas', 'Microsoft YaHei UI', monospace",
}


def build_qss() -> str:
    t = TOKENS
    return f"""
    QMainWindow, QDialog {{ background: {t['bg']}; }}
    QWidget {{ color: {t['fg']}; font-family: {t['font']}; font-size: 13px; }}
    QLabel {{ background: transparent; }}
    QLabel#hint, QLabel#turn_note, QLabel#dl_log {{ color: {t['fg_faint']};
        font-size: 12px; }}
    QLabel#turn_q {{ color: {t['fg_dim']}; }}
    QLabel#sec_title {{ color: {t['fg_dim']}; }}
    QLabel#status_info {{ color: {t['fg_faint']}; font-size: 12px; }}
    QLabel#status_msg {{ font-size: 12px; }}

    /* ---- 按钮：方角 1px 边框；accent=磷光绿描边 ---- */
    QPushButton {{ background: transparent; border: 1px solid {t['line']};
        padding: 6px 16px; color: {t['fg']}; }}
    QPushButton:hover {{ background: {t['bg_hover']}; border-color: {t['fg_dim']}; }}
    QPushButton:pressed {{ background: {t['bg_raise']}; }}
    QPushButton:disabled {{ color: {t['fg_faint']}; border-color: {t['line_soft']}; }}
    QPushButton[accent="true"] {{ border-color: {t['accent']}; color: {t['accent']}; }}
    QPushButton[accent="true"]:hover {{ background: rgba(90, 247, 142, 0.06); }}
    QPushButton[accent="true"]:disabled {{ color: {t['fg_faint']};
        border-color: {t['line_soft']}; }}
    QPushButton#nav_tab {{ border: none; border-bottom: 2px solid transparent;
        color: {t['fg_dim']}; padding: 12px 2px 10px; border-radius: 0; }}
    QPushButton#nav_tab:hover {{ background: transparent; color: {t['fg']}; }}
    QPushButton#nav_tab:checked {{ color: {t['fg']};
        border-bottom: 2px solid {t['accent']}; }}

    /* ---- 输入：方角、bg_raise 底、focus 绿框 ---- */
    QLineEdit, QComboBox {{ background: {t['bg_raise']}; border: 1px solid {t['line']};
        padding: 6px 10px; color: {t['fg']}; selection-background-color: {t['accent']}; }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {t['accent']}; }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {t['fg_faint']}; }}
    QComboBox QAbstractItemView {{ background: {t['bg_raise']};
        border: 1px solid {t['line']}; selection-background-color: {t['bg_hover']}; }}

    /* ---- 复选：方框 + 内实心方块（checked） ---- */
    QCheckBox {{ spacing: 8px; color: {t['fg']}; }}
    QCheckBox::indicator {{ width: 13px; height: 13px;
        border: 1px solid {t['fg_dim']}; background: transparent; }}
    QCheckBox::indicator:hover {{ border-color: {t['fg']}; }}
    QCheckBox::indicator:checked {{ background: {t['accent']};
        border: 1px solid {t['fg_dim']}; }}

    /* ---- 表格：无竖线、行间 1px、整行反白选中 ---- */
    QTableView {{ background: transparent; border: none; gridline-color: transparent;
        selection-background-color: {t['fg']}; selection-color: {t['bg']}; }}
    QTableView::item {{ padding: 10px 12px; border-bottom: 1px solid {t['line_soft']}; }}
    QTableView::item:selected {{ background: {t['fg']}; color: {t['bg']}; }}
    QHeaderView::section {{ background: transparent; border: none;
        border-bottom: 1px solid {t['line']}; padding: 8px 12px;
        color: {t['fg_faint']}; font-size: 12px; }}

    /* ---- 进度条：平面 ---- */
    QProgressBar {{ background: {t['bg_raise']}; border: 1px solid {t['line']};
        height: 10px; text-align: center; color: transparent; }}
    QProgressBar::chunk {{ background: {t['accent']}; }}

    /* ---- 对话流 / 状态行 ---- */
    QWidget#feed {{ background: {t['bg']}; }}
    QTextBrowser#answer {{ background: transparent; border: none; color: {t['fg']}; }}
    QWidget#statusline {{ border-top: 1px solid {t['line']}; background: {t['bg']}; }}
    QWidget#nav {{ border-bottom: 1px solid {t['line']}; background: {t['bg']}; }}
    QFrame#hline {{ background: {t['line_soft']}; max-height: 1px; border: none; }}

    QMenu {{ background: {t['bg_raise']}; border: 1px solid {t['line']}; }}
    QMenu::item {{ padding: 6px 20px; }}
    QMenu::item:selected {{ background: {t['bg_hover']}; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; }}
    QScrollBar::handle:vertical {{ background: {t['line']}; }}
    QScrollBar::handle:vertical:hover {{ background: {t['fg_faint']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """
}


def apply(app) -> None:
    from PySide6.QtGui import QFont
    f = QFont()
    f.setFamilies(["Cascadia Mono", "Consolas", "Microsoft YaHei UI"])
    f.setStyleHint(QFont.Monospace)
    f.setLetterSpacing(QFont.AbsoluteSpacing, 0.5)
    app.setFont(f)
    app.setStyleSheet(build_qss())
```

- [ ] **Step 4: 绿 + Commit**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_theme.py -q`
Expected: PASS

```bash
git add app/theme.py tests/test_theme.py
git commit -m "feat!: retro terminal QSS 设计系统（近黑底/磷光绿/1px 直线/等宽栈）"
```

---

### Task 7: 设置页（窗口内，含模型下载）

**Files:**
- Create: `app/settings_page.py`
- Test: `tests/test_settings_page.py`

**Interfaces:**
- Consumes: `core.downloader.models_ready`；Task 5 `icon()`。
- Produces: `SettingsPage(cfg, set_status)`，属性 `model_state: QLabel`、`dl_btn`、`progress: QProgressBar`；信号 `download_requested()`；方法 `refresh_models_state()`、`on_dl_started()`、`on_dl_progress(p: float)`、`on_dl_line(m: str)`、`on_dl_failed(msg)`、`on_dl_ok()`、`save() -> bool`。

- [ ] **Step 1: 失败测试 `tests/test_settings_page.py`**

```python
# tests/test_settings_page.py —— 设置页：保存/热键校验/下载状态
import json

import pytest

def _page(qtbot, tmp_path):
    import core.config as cc
    monkey_override = tmp_path
    from core.config import default_config
    from app.settings_page import SettingsPage
    cfg = default_config()
    statuses = []
    p = SettingsPage(cfg, set_status=lambda t, kind="info": statuses.append((t, kind)))
    qtbot.addWidget(p)
    return p, cfg, statuses

def test_save_writes_config(qtbot, tmp_path):
    p, cfg, _ = _page(qtbot, tmp_path)
    p.base_url_edit.setText("https://api.x.com/v1")
    p.model_edit.setText("m1")
    assert p.save() is True
    from core.config import load_config
    cfg2 = load_config(cfg.data_dir)
    assert cfg2.llm_base_url == "https://api.x.com/v1" and cfg2.llm_model == "m1"

def test_save_rejects_invalid_hotkey(qtbot, tmp_path):
    p, cfg, statuses = _page(qtbot, tmp_path)
    before = cfg.hotkey
    p.hotkey_edit.setText("bad!!")
    assert p.save() is False
    assert cfg.hotkey == before
    assert any("热键无效" in t for t, _ in statuses)

def test_device_combo_has_default(qtbot, tmp_path):
    p, _, _ = _page(qtbot, tmp_path)
    assert p.device_combo.currentData() == ""

def test_refresh_models_state_ready(qtbot, tmp_path):
    import core.downloader as dl
    p, cfg, _ = _page(qtbot, tmp_path)
    for rel in dl.REQUIRED:
        f = cfg.models_dir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    p.refresh_models_state()
    assert "已就绪" in p.model_state.text()

def test_download_request_signal(qtbot, tmp_path):
    p, _, _ = _page(qtbot, tmp_path)
    got = []
    p.download_requested.connect(lambda: got.append(1))
    p.dl_btn.click()
    assert got == [1]

def test_dl_progress_and_ok_flow(qtbot, tmp_path):
    p, _, _ = _page(qtbot, tmp_path)
    p.on_dl_started()
    assert not p.progress.isHidden()
    assert not p.dl_btn.isEnabled()
    p.on_dl_progress(0.62)
    assert p.progress.value() == 62
    p.on_dl_ok()
    assert "已就绪" in p.model_state.text()
    assert p.progress.isHidden()
```

- [ ] **Step 2: 红**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_settings_page.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.settings_page'`

- [ ] **Step 3: 实现 `app/settings_page.py`**

```python
# app/settings_page.py —— 设置页（窗口内，替代设置弹窗+下载向导）。
# 直线分节：语音模型（下载）/ 大模型 / 热键 / 音频与目录；保存统一落盘。
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QProgressBar, QPushButton, QVBoxLayout, QWidget)

from core.config import AppConfig, save_config
from core.downloader import models_ready

from app.icons import icon


def _sep() -> QFrame:
    from PySide6.QtWidgets import QFrame
    f = QFrame()
    f.setObjectName("hline")
    f.setFixedHeight(1)
    return f


class SettingsPage(QWidget):
    download_requested = Signal()

    def __init__(self, cfg: AppConfig, set_status, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._set_status = set_status
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)

        # -- 语音模型 --
        root.addWidget(QLabel("# 语音模型"))
        row = QHBoxLayout()
        self.model_state = QLabel("")
        self.model_state.setObjectName("model_status")
        row.addWidget(self.model_state)
        row.addStretch(1)
        self.dl_btn = QPushButton(" 下载模型")
        self.dl_btn.setIcon(icon("download", "#5af78e"))
        self.dl_btn.clicked.connect(self.download_requested.emit)
        row.addWidget(self.dl_btn)
        root.addLayout(row)
        self.progress = QProgressBar()
        self.progress.hide()
        root.addWidget(self.progress)
        self.dl_log = QLabel("")
        self.dl_log.setObjectName("dl_log")
        self.dl_log.hide()
        root.addWidget(self.dl_log)
        root.addWidget(_sep())

        # -- 大模型 --
        root.addWidget(QLabel("# 大模型"))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        self.base_url_edit = QLineEdit(cfg.llm_base_url)
        self.api_key_edit = QLineEdit(cfg.llm_api_key)
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.model_edit = QLineEdit(cfg.llm_model)
        form.addRow("base url", self.base_url_edit)
        form.addRow("api key", self.api_key_edit)
        form.addRow("模型", self.model_edit)
        root.addLayout(form)
        root.addWidget(_sep())

        # -- 热键 --
        root.addWidget(QLabel("# 热键"))
        form2 = QFormLayout()
        self.hotkey_edit = QLineEdit(cfg.hotkey)
        self.hide_hotkey_edit = QLineEdit(cfg.hide_hotkey)
        form2.addRow("触发", self.hotkey_edit)
        form2.addRow("急隐藏", self.hide_hotkey_edit)
        root.addLayout(form2)
        root.addWidget(_sep())

        # -- 音频与目录 --
        root.addWidget(QLabel("# 音频与目录"))
        form3 = QFormLayout()
        self.device_combo = QComboBox()
        self._load_devices()
        form3.addRow("音频设备", self.device_combo)
        self.models_dir_edit = QLineEdit(str(cfg.models_dir))
        self.data_dir_edit = QLineEdit(str(cfg.data_dir))
        form3.addRow("模型目录", self.models_dir_edit)
        hint = QLabel("语音识别与向量检索模型统一存放于此")
        hint.setObjectName("hint")
        form3.addRow("", hint)
        form3.addRow("数据目录", self.data_dir_edit)
        root.addLayout(form3)

        root.addStretch(1)
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.save_btn = QPushButton(" 保存")
        self.save_btn.setIcon(icon("save", "#5af78e"))
        self.save_btn.setProperty("accent", True)
        self.save_btn.clicked.connect(self._on_save_clicked)
        save_row.addWidget(self.save_btn)
        root.addLayout(save_row)

        self.refresh_models_state()

    # ---- 保存 ----
    def _on_save_clicked(self) -> None:
        if self.save():
            self._set_status("设置已保存", "ok")

    def save(self) -> bool:
        hotkey = self.hotkey_edit.text().strip() or "ctrl+alt+space"
        hide = self.hide_hotkey_edit.text().strip() or "ctrl+alt+h"
        import keyboard
        for label, text in (("触发热键", hotkey), ("急隐藏热键", hide)):
            try:
                keyboard.parse_hotkey(text)
            except Exception:
                self._set_status(f"热键无效：{label} {text}", "error")
                return False
        self.cfg.llm_base_url = self.base_url_edit.text().strip()
        self.cfg.llm_api_key = self.api_key_edit.text().strip()
        self.cfg.llm_model = self.model_edit.text().strip()
        self.cfg.models_dir = Path(self.models_dir_edit.text())
        self.cfg.data_dir = Path(self.data_dir_edit.text())
        self.cfg.hotkey = hotkey
        self.cfg.hide_hotkey = hide
        self.cfg.audio_device = self.device_combo.currentData() or ""
        save_config(self.cfg)
        return True

    # ---- 下载状态（worker 由主窗持有，页面只展示） ----
    def refresh_models_state(self) -> None:
        ok = models_ready(self.cfg.models_dir)
        self.model_state.setText("已就绪 · sherpa-onnx + bge" if ok else "未下载")
        self.dl_btn.setText(" 重新下载" if ok else " 下载模型")
        self.dl_btn.setEnabled(True)
        self.progress.hide()
        self.dl_log.hide()

    def on_dl_started(self) -> None:
        self.dl_btn.setText(" 下载中…")
        self.dl_btn.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.dl_log.show()

    def on_dl_progress(self, p: float) -> None:
        self.progress.setValue(int(p * 100))

    def on_dl_line(self, m: str) -> None:
        self.dl_log.setText(m)

    def on_dl_failed(self, msg: str) -> None:
        self.dl_log.setText(f"下载失败：{msg}（点重新下载续传）")
        self.dl_btn.setText(" 重新下载")
        self.dl_btn.setEnabled(True)

    def on_dl_ok(self) -> None:
        self.refresh_models_state()

    def _load_devices(self) -> None:
        self.device_combo.addItem("系统默认", "")
        try:
            from core.capture import list_loopback_devices
            for d in list_loopback_devices():
                label = d["name"] + ("（默认）" if d.get("default") else "")
                self.device_combo.addItem(label, d["name"])
        except Exception:
            pass  # 无音频环境仅保留"系统默认"
        idx = self.device_combo.findData(self.cfg.audio_device)
        self.device_combo.setCurrentIndex(idx if idx >= 0 else 0)
```

文件顶部 import 需含 `from pathlib import Path` 与 `from PySide6.QtWidgets import QFrame`（把 `_sep` 里的局部 import 上提即可）。

- [ ] **Step 4: 绿 + Commit**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_settings_page.py -q`
Expected: PASS

```bash
git add app/settings_page.py tests/test_settings_page.py
git commit -m "feat: 设置页（窗口内）——模型下载并入+分节表单+热键校验"
```

---

### Task 8: 监听页重写（终端转写流）

**Files:**
- Modify: `app/ui_chat.py`（全文替换）
- Test: `tests/test_main_window_ui.py`（Step 1 先替换页面相关用例；主窗用例在 Task 9 处理）

**Interfaces:**
- Produces: `ChatPage.start_btn`、`ChatPage.auto_switch`（QCheckBox）、`ChatPage.add_interviewer(text) -> InterviewerTurn`、`ChatPage.begin_answer() -> AnswerTurn`（无参）、`ChatPage.scroll_to_bottom()`；`AnswerTurn.append(delta)`、`AnswerTurn.mark_interrupted()`、`AnswerTurn.view`（QTextBrowser）、`AnswerTurn.note`（QLabel）。

- [ ] **Step 1: 全文替换 `tests/test_main_window_ui.py` 中页面用例**（主窗 fixture 暂保留旧构造——本任务只保证 `ChatPage` 级测试绿；整文件在 Task 9 完成终态）：

新建 `tests/test_ui_chat.py`：

```python
# tests/test_ui_chat.py —— 监听页终端转写流
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QTextBrowser

from app.ui_chat import AnswerTurn, ChatPage, InterviewerTurn


@pytest.fixture
def page(qtbot):
    p = ChatPage()
    qtbot.addWidget(p)
    return p


def test_header_has_only_button_and_checkbox(page):
    assert page.start_btn.text() == "开始监听"
    assert page.auto_switch.text() == "自动作答"
    assert page.auto_switch.isChecked()


def test_interviewer_turn_has_prefix_and_dim_objectname(page):
    t = page.add_interviewer("请讲讲 Redis 持久化")
    assert isinstance(t, InterviewerTurn)
    lb = t.findChildren(QLabel)[0] if False else t.layout().itemAt(0).widget()
    assert lb.text().startswith("›")


def test_answer_streams_and_mark_interrupted(page):
    b = page.begin_answer()
    b.append("**RDB** 是快照，")
    b.append("**AOF** 是日志。")
    assert "RDB" in b.view.toPlainText() and "**" not in b.view.toPlainText()
    b.mark_interrupted()
    assert "生成中断" in b.note.text()


def test_answer_view_frameless_and_no_scrollbars(page):
    b = page.begin_answer()
    assert b.view.frameShape() == QFrame.NoFrame
    assert b.view.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert b.view.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff


def test_answer_bold_renders_accent(page):
    b = page.begin_answer()
    b.append("**重点**内容")
    assert "#5af78e" in b.view.document().defaultStyleSheet().lower()


def test_turns_are_separated_by_hline(page):
    page.add_interviewer("第一句")
    page.begin_answer().append("答")
    page.add_interviewer("第二句")
    from PySide6.QtWidgets import QFrame
    frames = page.feed.findChildren(QFrame)
    assert any(f.frameShape() == QFrame.HLine or f.objectName() == "hline" for f in frames)


from PySide6.QtWidgets import QLabel  # 供上面 findChildren 使用
```

（最后一行 import 置顶整理；`test_interviewer_turn_has_prefix_and_dim_objectname` 中 QLabel 取法直接写 `t.layout().itemAt(0).widget()`。）

- [ ] **Step 2: 红**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_ui_chat.py -q`
Expected: FAIL（`begin_answer()` 不接受 0 参 / 类名不存在）

- [ ] **Step 3: 全文替换 `app/ui_chat.py`**

```python
# app/ui_chat.py —— 监听页：终端转写流（无气泡容器，1px 分割线）。
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QTextBrowser, QVBoxLayout, QWidget)

from app.icons import icon

ACCENT = "#5af78e"


class _AutoHeightBrowser(QTextBrowser):
    """无边框、无滚动条的流式正文；高度按当前视口宽实排。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setOpenExternalLinks(False)

    def refit(self) -> None:
        doc = self.document()
        doc.setTextWidth(self.viewport().width() or doc.textWidth())
        self.setFixedHeight(max(28, int(doc.size().height()) + 10))

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        if ev.oldSize().width() != self.width():
            self.refit()


def _hline() -> QFrame:
    f = QFrame()
    f.setObjectName("hline")
    f.setFrameShape(QFrame.HLine)
    f.setFixedHeight(1)
    return f


class InterviewerTurn(QWidget):
    """面试官话轮：fg_dim 文本 + “›” 前缀。"""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lb = QLabel("› " + text, self)
        lb.setObjectName("turn_q")
        lb.setWordWrap(True)
        lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(lb)


class AnswerTurn(QWidget):
    """回答话轮：markdown 正文（加粗渲染为 accent）+ 弱色标注行。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 6, 0, 10)
        col.setSpacing(6)
        self.view = _AutoHeightBrowser(self)
        self.view.setObjectName("answer")
        self.view.document().setDefaultStyleSheet(f"strong {{ color: {ACCENT}; }}")
        self.view.setPlaceholderText("正在生成…")
        self.view.setFixedHeight(36)
        col.addWidget(self.view)
        self.note = QLabel("", self)
        self.note.setObjectName("turn_note")
        self.note.setWordWrap(True)
        col.addWidget(self.note)
        self._buf = ""

    def append(self, delta: str) -> None:
        if not delta:
            return
        self._buf += delta
        self.view.setMarkdown(self._buf)
        self.view.refit()
        self._parent_scroll_to_bottom()

    def mark_interrupted(self) -> None:
        if self._buf:
            self.note.setText("生成中断——以上为已收到的部分，可稍后重试")

    def _parent_scroll_to_bottom(self) -> None:
        p = self.parent()
        while p is not None:
            if hasattr(p, "scroll_to_bottom"):
                p.scroll_to_bottom()
                return
            p = p.parent()


class ChatPage(QWidget):
    """监听页：头行（开始监听 + 自动作答）+ 转写流。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chat-page")
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 12)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(18)
        self.start_btn = QPushButton(" 开始监听")
        self.start_btn.setIcon(icon("mic", ACCENT))
        self.start_btn.setProperty("accent", True)
        head.addWidget(self.start_btn)
        self.auto_switch = QCheckBox("自动作答")
        self.auto_switch.setChecked(True)
        head.addWidget(self.auto_switch)
        head.addStretch(1)
        root.addLayout(head)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.feed = QWidget()
        self.feed.setObjectName("feed")
        self.feed_lay = QVBoxLayout(self.feed)
        self.feed_lay.setContentsMargins(0, 0, 16, 8)
        self.feed_lay.setSpacing(0)
        self.feed_lay.addStretch(1)
        self.scroll.setWidget(self.feed)
        root.addWidget(self.scroll, 1)

    def add_interviewer(self, text: str) -> InterviewerTurn:
        t = InterviewerTurn(text)
        self.feed_lay.insertWidget(self.feed_lay.count() - 1, t)
        self.feed_lay.insertWidget(self.feed_lay.count() - 1, _hline())
        self.scroll_to_bottom()
        return t

    def begin_answer(self) -> AnswerTurn:
        b = AnswerTurn()
        self.feed_lay.insertWidget(self.feed_lay.count() - 1, b)
        self.scroll_to_bottom()
        return b

    def scroll_to_bottom(self) -> None:
        sb = self.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
```

- [ ] **Step 4: 绿**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_ui_chat.py -q`
Expected: PASS

- [ ] **Step 5: 截图核对 + Commit**

用 Task 10 的截图脚本渲染 ChatPage（两问两答内容取自预览页），与预览页监听屏比对。

```bash
git add app/ui_chat.py tests/test_ui_chat.py
git commit -m "feat!: 监听页重写为终端转写流（无气泡、accent 加粗、1px 分割线）"
```

---

### Task 9: 主窗重写（voxov 壳 + 三页导航 + 状态行）

**Files:**
- Modify: `app/main_window.py`（全文替换）
- Modify: `app/tray.py`（下载模型 → 设置）
- Test: `tests/test_main_window.py`（全文替换）、`tests/test_main_window_ui.py`（删除旧文件，用例已迁移 test_ui_chat.py + 新主窗测试）、`tests/test_download_flow.py`（向导用例改设置页）

**Interfaces:**
- Consumes: Task 1 `classify_turn`、Task 7 `SettingsPage`、Task 8 `ChatPage`。
- Produces: `MainWindow(cfg, kb_factory, rag_factory)`（rehearsal 参数删除）；`set_status(text, kind="info")`；`open_settings()`；`switch_page(key)`；属性 `chat_page/settings_page/start_btn/model_status_label/status_info/status_msg`；信号 `subtitle_sig`、`audio_error_sig`。

- [ ] **Step 1: 全文替换 `tests/test_main_window.py`**

```python
# tests/test_main_window.py —— voxov 壳：tab 导航、状态行、自动作答路由、知识库表
import pytest
from app.main_window import MainWindow


class FakeRag:
    def __init__(self):
        from core.session import SessionBuffer
        self.buffer = SessionBuffer()
        self.triggered = 0
        self.last_notice = ""
    def trigger(self):
        self.triggered += 1
        yield "**答**案"


class FakeKb:
    def __init__(self):
        self.files = [("a.md", 3), ("b.md", 5)]
    def list_files(self):
        return list(self.files)
    def delete_file(self, name):
        self.files = [(f, n) for f, n in self.files if f != name]
        return 1


@pytest.fixture
def win(qtbot, tmp_path, monkeypatch):
    import core.config as cc
    monkeypatch.setattr(cc, "app_root", lambda: tmp_path)
    from core.config import default_config
    rag, kb = FakeRag(), FakeKb()
    w = MainWindow(default_config(), kb_factory=lambda: kb, rag_factory=lambda: rag)
    qtbot.addWidget(w)
    return w, rag


def test_window_title_and_nav_tabs(win):
    w, _ = win
    assert w.windowTitle() == "voxov"
    for key in ("listen", "kb", "settings"):
        assert key in w._pages


def test_switch_page_moves_stack(win):
    w, _ = win
    w.switch_page("settings")
    assert w._stack.currentWidget() is w.settings_page
    w.switch_page("listen")
    assert w._stack.currentWidget() is w.chat_page


def test_kb_table_lists_files_and_row_selection(win):
    w, _ = win
    model = w.kb_table.model()
    assert model.rowCount() == 2
    assert w.kb_table.selectionBehavior() == w.kb_table.SelectRows
    assert not w.kb_table.editTriggers()


def test_delete_selected_file(win):
    w, _ = win
    w.kb_table.selectRow(0)
    w._delete_selected()
    assert w.kb_table.model().rowCount() == 1


def test_set_status_message_and_auto_clear(win, qtbot):
    w, _ = win
    w.set_status("设置已保存", "ok")
    assert "设置已保存" in w.status_msg.text()
    w._status_timer.start(50)
    qtbot.wait(120)
    assert w.status_msg.text() == ""


def test_hotkey_triggers_generate(win, qtbot):
    w, rag = win
    w._on_hotkey()
    qtbot.waitUntil(lambda: rag.triggered == 1, timeout=3000)
    assert w._chat_answer is not None


def test_hotkey_flushes_pending_pipeline(win):
    w, rag = win
    flushed = []
    class FakePipeline:
        def flush_pending(self):
            flushed.append(1)
    w._pipeline = FakePipeline()
    w._on_hotkey()
    assert flushed == [1]


def test_subtitle_question_auto_triggers(win, monkeypatch):
    w, _ = win
    fired = []
    monkeypatch.setattr(w, "_on_hotkey", lambda: fired.append(1))
    w.subtitle_sig.emit("说说 MySQL 索引")
    assert fired == [1]


def test_subtitle_statement_auto_triggers_when_auto_on(win, monkeypatch):
    w, _ = win
    fired = []
    monkeypatch.setattr(w, "_on_hotkey", lambda: fired.append(1))
    w.subtitle_sig.emit("我们团队主要做 ToB 业务")
    assert fired == [1]                     # 陈述也是实质话轮（路由 spec）


def test_subtitle_chatter_never_triggers(win, monkeypatch):
    w, _ = win
    fired = []
    monkeypatch.setattr(w, "_on_hotkey", lambda: fired.append(1))
    w.subtitle_sig.emit("嗯好的")
    assert fired == []
    w.chat_page.auto_switch.setChecked(False)
    w.subtitle_sig.emit("说说 MySQL 索引")
    assert fired == []


def test_notice_passthrough_to_answer_note(win, qtbot):
    w, rag = win
    rag.last_notice = "开放题 · 未用资料"
    w._on_hotkey()
    qtbot.waitUntil(lambda: w._chat_answer is not None
                    and "开放题" in w._chat_answer.note.text(), timeout=3000)


def test_hide_hotkey_toggles_window(win):
    w, _ = win
    w.show()
    w._on_hide()
    assert not w.isVisible()
    w._on_hide()
    assert w.isVisible()


def test_no_rehearsal_leftovers(win):
    w, _ = win
    assert not hasattr(w, "start_rehearsal")
    assert not hasattr(w, "_rehearsal_rag_factory")
    assert not hasattr(w, "_info")
```

- [ ] **Step 2: 全文替换 `app/main_window.py`**

```python
# app/main_window.py —— 主窗口 v4：retro terminal 壳。
# 顶栏文本 tab + 底部状态行；设置/下载并入设置页；彩排已移除。
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QStackedWidget, QTableView, QVBoxLayout, QWidget)

from app.icons import icon
from app.settings_page import SettingsPage
from app.ui_chat import ChatPage

STATUS_COLOR = {"info": "#e6e6e6", "ok": "#5af78e", "warn": "#e3b341", "error": "#f85149"}


class MainWindow(QMainWindow):
    subtitle_sig = Signal(str)
    audio_error_sig = Signal(str)

    def __init__(self, cfg, kb_factory, rag_factory) -> None:
        super().__init__()
        self.cfg = cfg
        self._kb_factory = kb_factory
        self._rag_factory = rag_factory
        self._rag = None
        self._recorder = None
        self._chat_answer = None
        self._last_utterance = ""
        self.subtitle_sig.connect(self._on_subtitle)
        self.audio_error_sig.connect(self._on_audio_error)
        self._worker = None
        self._pipeline = None
        self._load_worker = None
        self._pending_build = None
        self.bridge = None
        self.tray = None
        self._hidden = False
        self._dl_worker = None
        self._started_without_models = False
        self._model_text = "model: 未下载"
        self.setWindowTitle("voxov")
        self.resize(1120, 760)
        self._build_ui()
        self._reload_kb()

    # ---- UI ----
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        nav = QWidget()
        nav.setObjectName("nav")
        nav_lay = QHBoxLayout(nav)
        nav_lay.setContentsMargins(28, 0, 28, 0)
        nav_lay.setSpacing(24)
        self._stack = QStackedWidget()
        self.chat_page = ChatPage(self)
        self._page_kb = self._build_kb_page()
        self.settings_page = SettingsPage(self.cfg, set_status=self.set_status)
        self._pages: dict[str, tuple[QPushButton, QWidget]] = {}
        for key, label, widget in (("listen", "监听", self.chat_page),
                                   ("kb", "知识库", self._page_kb),
                                   ("settings", "设置", self.settings_page)):
            btn = QPushButton(label)
            btn.setObjectName("nav_tab")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.switch_page(k))
            nav_lay.addWidget(btn)
            self._pages[key] = (btn, widget)
            self._stack.addWidget(widget)
        root.addWidget(nav)
        root.addWidget(self._stack, 1)

        footer = QWidget()
        footer.setObjectName("statusline")
        f_lay = QHBoxLayout(footer)
        f_lay.setContentsMargins(14, 4, 14, 4)
        self.status_info = QLabel("")
        self.status_info.setObjectName("status_info")
        self.status_msg = QLabel("")
        self.status_msg.setObjectName("status_msg")
        f_lay.addWidget(self.status_info)
        f_lay.addStretch(1)
        f_lay.addWidget(self.status_msg)
        root.addWidget(footer)
        self._status_timer = QTimer(self, singleShot=True, interval=4000)
        self._status_timer.timeout.connect(lambda: self.status_msg.setText(""))

        self.start_btn = self.chat_page.start_btn
        self.model_status_label = self.settings_page.model_state   # 既有引用别名
        self.start_btn.clicked.connect(self.start_listening)
        self.settings_page.download_requested.connect(self._start_download)
        self.switch_page("listen")
        self._refresh_status_info()

    def switch_page(self, key: str) -> None:
        for k, (btn, _) in self._pages.items():
            btn.setChecked(k == key)
        self._stack.setCurrentWidget(self._pages[key][1])
        if key == "settings":
            self.settings_page.refresh_models_state()

    def open_settings(self) -> None:
        self.show()
        self.switch_page("settings")

    def set_status(self, text: str, kind: str = "info", hold: int = 4000) -> None:
        self.status_msg.setStyleSheet(f"color: {STATUS_COLOR.get(kind, STATUS_COLOR['info'])};")
        self.status_msg.setText(text)
        self._status_timer.start(hold)

    def _refresh_status_info(self) -> None:
        n = len(self._kb_factory().list_files())
        self.status_info.setText(
            f"{self._model_text} · kb: {n} 文件 · hotkey: {self.cfg.hotkey}")

    def _build_kb_page(self) -> QWidget:
        from PySide6.QtWidgets import QFrame
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 20, 28, 20)
        lay.setSpacing(12)
        head = QHBoxLayout()
        for text, icon_name, handler in (("上传", "upload", self._upload),
                                         ("删除", "trash", self._delete_selected),
                                         ("导出", "download", self._export_session)):
            b = QPushButton(" " + text)
            b.setIcon(icon(icon_name))
            b.clicked.connect(handler)
            head.addWidget(b)
        head.addStretch(1)
        self.kb_count = QLabel("")
        self.kb_count.setObjectName("hint")
        head.addWidget(self.kb_count)
        lay.addLayout(head)
        line = QFrame()
        line.setObjectName("hline")
        line.setFixedHeight(1)
        lay.addWidget(line)
        self.kb_table = QTableView()
        self.kb_model = QStandardItemModel(0, 2)
        self.kb_model.setHorizontalHeaderLabels(["文件", "块数"])
        self.kb_table.setModel(self.kb_model)
        self.kb_table.horizontalHeader().setStretchLastSection(True)
        self.kb_table.setEditTriggers(QTableView.NoEditTriggers)
        self.kb_table.setSelectionBehavior(QTableView.SelectRows)
        self.kb_table.setSelectionMode(QTableView.SingleSelection)
        self.kb_table.setShowGrid(False)
        self.kb_table.verticalHeader().hide()
        lay.addWidget(self.kb_table, 1)
        return page

    def _reload_kb(self) -> None:
        self.kb_model.setRowCount(0)
        files = self._kb_factory().list_files()
        for name, n in files:
            self.kb_model.appendRow([QStandardItem(name), QStandardItem(str(n))])
        if hasattr(self, "kb_count"):
            blocks = sum(n for _, n in files)
            self.kb_count.setText(f"{len(files)} 文件 · {blocks} 块")
        self._refresh_status_info()

    def _upload(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "选择 md 文件", "", "Markdown (*.md)")
        kb = self._kb_factory()
        bad = []
        for f in files:
            try:
                kb.ingest_file(Path(f))
            except ValueError as exc:
                bad.append(str(exc))
        self._reload_kb()
        if bad:
            self.set_status(f"导入失败：{bad[0]}", "error")
        elif files:
            self.set_status(f"已导入 {len(files)} 个文件", "ok")

    def _delete_selected(self) -> None:
        idx = self.kb_table.currentIndex()
        if not idx.isValid():
            return
        name = self.kb_model.item(idx.row(), 0).text()
        self._kb_factory().delete_file(name)
        self._reload_kb()
        self.set_status(f"已删除 {name}", "ok")

    def _export_session(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出面试记录", "", "Markdown (*.md)")
        if path and self._recorder is not None:
            p = self._recorder.export_markdown(Path(path))
            self.set_status(f"已导出 {p}", "ok")

    # ---- 下载（worker 持有在主窗；页面只展示） ----
    def maybe_auto_download(self) -> None:
        from core.downloader import models_ready
        if models_ready(self.cfg.models_dir):
            self._set_model_state("ok")
            return
        self._start_download()

    def _start_download(self) -> None:
        from app.workers import DownloadWorker
        if self._dl_worker is not None and self._dl_worker.isRunning():
            return
        w = DownloadWorker(self.cfg.models_dir)
        w.failed.connect(self._on_dl_failed)
        w.finished_ok.connect(self._on_dl_ok)
        w.progress.connect(self.settings_page.on_dl_progress)
        w.line.connect(self.settings_page.on_dl_line)
        self._dl_worker = w
        self._set_model_state("dl")
        w.start()

    def _on_dl_failed(self, msg: str) -> None:
        self._set_model_state("err")
        self.settings_page.on_dl_failed(msg)
        self.set_status(f"模型下载失败：{msg}", "error")

    def _on_dl_ok(self) -> None:
        self._set_model_state("ok")
        if self._started_without_models:
            self.set_status("模型已就绪 · 重启应用后启用语义检索", "ok")
        else:
            self.set_status("模型已就绪 · 语音识别可用", "ok")

    def _set_model_state(self, state: str) -> None:
        from core.downloader import models_ready
        if state == "dl":
            self._model_text = "model: 下载中"
            self.settings_page.on_dl_started()
        elif state == "err":
            self._model_text = "model: 下载失败"
            self.model_status_label.setText("下载失败")
        else:
            ok = state == "ok" and models_ready(self.cfg.models_dir)
            self._model_text = "model: 就绪" if ok else "model: 未下载"
            self.settings_page.refresh_models_state()
        self._refresh_status_info()

    def _on_hide(self) -> None:
        self._hidden = not self._hidden
        self.setVisible(not self._hidden)
        if self.tray is not None:
            self.tray.setVisible(not self._hidden)

    def shutdown(self) -> None:
        if self._pipeline is not None:
            self._pipeline.stop()
        if self.bridge is not None:
            self.bridge.stop()
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(2000)
        if self._load_worker is not None and self._load_worker.isRunning():
            self._load_worker.wait(2000)
        if self._dl_worker is not None and self._dl_worker.isRunning():
            self._dl_worker.wait(2000)

    def quit_app(self) -> None:
        self.shutdown()
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # ---- 监听 ----
    def start_listening(self) -> None:
        if self._pipeline is not None:
            self._pipeline.stop()
            self._pipeline = None
            self.start_btn.setText(" 开始监听")
            self.start_btn.setIcon(icon("mic", "#5af78e"))
            self.set_status("已停止监听", "ok")
            return
        if self._load_worker is not None and self._load_worker.isRunning():
            return
        from core.downloader import models_ready
        if not models_ready(self.cfg.models_dir):
            self.set_status("模型未就绪 · 已切到设置页", "warn")
            self.open_settings()
            self._start_download()
            return
        self._rag = self._rag or self._rag_factory()
        rag = self._rag

        def build(tr):
            from core.capture import LiveAudioSource
            from core.pipeline import AudioPipeline
            from core.vad import make_silero_vad
            return AudioPipeline(LiveAudioSource(device_name=self.cfg.audio_device or None),
                                 tr, rag.buffer,
                                 recorder=getattr(rag, "recorder", self._recorder),
                                 vad=make_silero_vad(self.cfg.models_dir))

        self._load_and_start(build)

    def _load_and_start(self, build) -> None:
        from app.workers import LoadWorker
        self._pending_build = build
        self.start_btn.setText(" 加载模型中…")
        self.start_btn.setEnabled(False)
        w = LoadWorker(self.cfg.models_dir)
        self._load_worker = w
        w.loaded.connect(self._on_loaded)
        w.failed.connect(self._on_load_failed)
        w.start()

    def _on_loaded(self, tr) -> None:
        try:
            self._pipeline = self._pending_build(tr)
            self._pipeline.on_subtitle = self.subtitle_sig.emit
            self._pipeline.on_error = self.audio_error_sig.emit
            self._pipeline.start()
            self.start_btn.setText(" 停止监听")
            self.start_btn.setIcon(icon("square", "#f85149"))
            self.start_btn.setEnabled(True)
            self.switch_page("listen")
        except Exception as exc:
            self.set_status(f"启动失败：{exc}", "error")
            self.start_btn.setText(" 开始监听")
            self.start_btn.setEnabled(True)

    def _on_load_failed(self, msg: str) -> None:
        self.set_status(f"启动失败：{msg}", "error")
        self.start_btn.setText(" 开始监听")
        self.start_btn.setEnabled(True)

    def _on_audio_error(self, m: str) -> None:
        self._pipeline = None
        self.start_btn.setText(" 开始监听")
        self.start_btn.setEnabled(True)
        self.set_status(f"音频异常，已停止监听：{m}", "error")

    # ---- 热键 → 生成 ----
    def _on_hotkey(self) -> None:
        from app.workers import GenerateWorker
        if self._worker is not None and self._worker.isRunning():
            return
        if self._pipeline is not None:
            self._pipeline.flush_pending()
        if self._rag is None:
            self._rag = self._rag_factory()
        self._chat_answer = self.chat_page.begin_answer()
        self._worker = GenerateWorker(self._rag)
        self._worker.question.connect(self._on_question)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.notice.connect(self._on_notice)
        self._worker.failed.connect(self._on_generate_failed)
        self._worker.start()

    def _on_subtitle(self, t: str) -> None:
        self.chat_page.add_interviewer(t)
        self._last_utterance = t
        from core.heuristics import classify_turn
        worker_busy = self._worker is not None and self._worker.isRunning()
        if (self.chat_page.auto_switch.isChecked() and not worker_busy
                and classify_turn(t) != "chatter"):
            self._on_hotkey()

    def _on_question(self, q: str) -> None:
        if not q and self._chat_answer is not None:
            self._chat_answer.note.setText("未识别到问题（稍后再按）")

    def _on_chunk(self, delta: str) -> None:
        if self._chat_answer is not None:
            self._chat_answer.append(delta)
            self.chat_page.scroll_to_bottom()

    def _on_generate_failed(self, m: str) -> None:
        self.set_status(f"生成失败：{m}", "error")
        if self._chat_answer is not None:
            self._chat_answer.mark_interrupted()

    def _on_notice(self, m: str) -> None:
        if self._chat_answer is not None:
            self._chat_answer.note.setText(m)
```

- [ ] **Step 3: `app/tray.py` 菜单改造**

```python
    settings_act = QAction("设置", win)
    settings_act.triggered.connect(win.open_settings)
    quit_ = QAction("退出", win)
    quit_.triggered.connect(win.quit_app)
    menu.addAction(show)
    menu.addAction(settings_act)
    menu.addAction(quit_)
```

（`wizard` QAction 删除。）

- [ ] **Step 4: 修 `tests/test_download_flow.py`**

- 删除 4 个 wizard 用例（`_mk_wizard_env` 及 `test_wizard_*`）。
- `win` fixture 增 `monkeypatch.setattr(cc, "app_root", ...)` 保持。
- `test_auto_download_failure_marks_state` / `test_auto_download_ok_prompts_restart_*`：把 `monkeypatch.setattr(win, "_info", ...)` 改为断言 `win.status_msg.text()`（qtbot.waitUntil 至文本出现）。
- `test_dl_heartbeat_ticks_elapsed` 删除（心跳被进度条取代）。
- `test_start_listening_gated_when_models_missing`：`win._open_wizard = ...` 改 `win.open_settings = lambda: opened.append(1)`。
- `test_rehearsal_also_gated_when_models_missing` 删除。

- [ ] **Step 5: 删除 `tests/test_main_window_ui.py`、`tests/test_review_fixes.py` 中 rehearsal 用例**

`test_review_fixes.py`：删除 `test_rehearsal_uses_dedicated_rag_and_hotkey_follows`（I7 段）与 `_wav1s` 若仅被它使用。该文件其余 `win` fixture 若引用 `MainWindow(..., rehearsal_rag_factory=...)`，同步去掉该参数。

- [ ] **Step 6: 绿 + Commit**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_main_window.py tests/test_download_flow.py tests/test_review_fixes.py tests/test_ui_chat.py -q`
Expected: 全 PASS

```bash
git add app/main_window.py app/tray.py tests/test_main_window.py tests/test_download_flow.py tests/test_review_fixes.py tests/test_main_window_ui.py
git commit -m "feat!: 主窗重写为 voxov 终端壳（tab 导航/状态行/设置页集成/彩排移除）"
```

---

### Task 10: 清理、入口与打包

**Files:**
- Delete: `app/wizard.py`、`app/settings_dialog.py`、`tests/test_rehearsal.py`
- Modify: `main.py`（setTheme/rehearsal 移除）、`core/session.py`（rehearsal 分支移除）、`interview-assistant.spec`（qfluentwidgets 收集移除）
- Test: `tests/test_main_app.py`、`tests/test_export.py`（如有 rehearsal 引用）

- [ ] **Step 1: `main.py` 修改**

- 删除 `from qfluentwidgets import setTheme, Theme` 与 `setTheme(Theme.DARK)`（主题由 `app.theme.apply` 承担，已存在）。
- `build_app()` 删除 `rehearsal_rag` lambda，返回 `(cfg, kb, rag, recorder)`。
- `main()` 中 `cfg, kb, rag, recorder = build_app()`；`MainWindow(cfg, kb_factory=lambda: kb, rag_factory=lambda: rag)`；删除 `win._started_without_models` 以外的彩排残留（无）。`win.rebind_hotkeys()` 等保持。

- [ ] **Step 2: `core/session.py` rehearsal 分支移除**

`SessionRecorder.__init__` 签名改 `(self, sessions_dir: Path | None = None)`：

```python
    def __init__(self, sessions_dir: Path | None = None) -> None:
        self.turns: list[QATurn] = []
        self.transcripts: list[TranscriptEntry] = []
        self._json_path: Path | None = None
        if sessions_dir is not None:
            self._json_path = sessions_dir / f"{datetime.now():%Y%m%d-%H%M%S}.json"
```

（docstring 去掉 rehearsal 句。grep 确认 `tests/test_export.py`、`tests/test_session.py` 无 `rehearsal=` 传参；有则同步删。）

- [ ] **Step 3: 删除文件 + 打包配置**

```bash
git rm app/wizard.py app/settings_dialog.py tests/test_rehearsal.py
```

`interview-assistant.spec`：
- `datas=[("assets", "assets")]`（删 `+ collect_data_files("qfluentwidgets")`）；
- `hiddenimports=[...]`（删 `+ collect_submodules("qfluentwidgets")`）；
- import 行保留 `collect_dynamic_libs` 即可；
- 头注释去掉 qfluentwidgets 字样。

`pyproject.toml`：确认 dependencies 无 qfluentwidgets（当前即无，不改动；若 grep 到则删）。

- [ ] **Step 4: 修 `tests/test_main_app.py`**

`res = main.build_app()` 返回 4 元组，现有断言 `res[0]` 不变；补一行：

```python
    assert len(res) == 4  # cfg, kb, rag, recorder（彩排工厂已删）
```

- [ ] **Step 5: 残留 grep 清零**

Run:
```bash
grep -rn "qfluentwidgets\|rehearsal\|wizard\|SettingsDialog\|InfoBar\|_info(" --include="*.py" app core main.py tests | grep -v "WavFileSource"
```
Expected: 无输出（WavFileSource 与其测试保留）。

- [ ] **Step 6: 全量测试**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: 全 PASS（2 deselected 为 model 标记）

- [ ] **Step 7: 截图终验**

用 offscreen 渲染 MainWindow 三页（`_stack.setCurrentWidget` 切换后 `grab()` 存 PNG），与 `docs/design/2026-10-04-retro-terminal-preview.html` 三屏逐一比对：布局结构、配色、等宽、1px 线一致。

```bash
git add -A
git commit -m "chore!: 移除彩排/向导/设置弹窗与 qfluentwidgets 残留，入口与打包同步"
```

---

## Self-Review 记录

1. **Spec 覆盖**：路由 spec §4→T1、§5.1→T2、§5.2→T4、§6→T3+T4、§7→T9、§8/§9→各任务测试；UI spec §2→T6、§3→T9、§4 三页→T8/T9/T7、§5→T5、§6 删除→T9/T10、§7 测试→各任务、§8 验收→T10 Step 6-7。无缺口。
2. **占位符扫描**：无 TBD/TODO；所有代码块完整可落盘。
3. **类型一致性**：`classify_turn` 返回值串 T1→T4→T9；`SettingsPage.on_dl_*` 串 T7→T9；`icon()` 串 T5→T7/T8/T9；`begin_answer()` 无参串 T8→T9。已核对。
4. **Review Focus**：5 条均已挂测试（T1×2、T7×2、T4×1）。
