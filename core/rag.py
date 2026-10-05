# core/rag.py —— 触发编排 v2：话轮分类 → 检索路由（距离阈值+FTS 越过）→ 三模式生成。
import re
import time
from typing import Iterator

from core.generator import LLMClient, build_messages
from core.heuristics import classify_turn
from core.retriever import Retriever
from core.session import SessionBuffer, SessionRecorder, extract_turn


def _fts_exact_hit(query: str, contexts: list) -> bool:
    """查询中 ≥4 字词项在任一检出 chunk 子串命中 → 越过距离阈值（防误杀）。

    中文无词边界：整串跑段提取会让「介绍一下你的项目经历」永远提不出
    「项目经历」（spec 验收 4：简历入库后开放题须能命中资料），故中文用
    滑动 4 字窗口穷举词项；西文/数字仍取整段（≥4 字符）。
    """
    toks = re.findall(r"[0-9A-Za-z_]{4,}", query)
    toks += re.findall(r"(?=([一-鿿]{4}))", query)
    return any(tok in c.text for c in contexts for tok in toks)


class RagService:
    """热键/自动触发的完整编排：提取话轮 → 分类 → 检索路由 → 流式生成 → 记录。"""

    REF_DIST_MAX = 0.92   # 实测校准（2026-10-05，bge-small-zh + 用户真实库 245 块）：
                          # 相关问法 top=0.76-0.87，无关问题 ~1.00；0.92 两侧有余量。
                          # 调参入口在此；L2（单位向量）⇔ cos≥约0.58

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
            reliable = (getattr(self.retriever, "distances_reliable", False)
                        and not getattr(self.retriever, "space_mismatch", False))
            if reliable:
                top = getattr(self.retriever, "last_top_distance", None)
                use_refs = bool(contexts) and (
                    (top is not None and top <= self.REF_DIST_MAX)
                    or _fts_exact_hit(turn, contexts))
            else:
                use_refs = bool(contexts)         # Hash/空间错配：FTS 兜底，有结果即注入
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
