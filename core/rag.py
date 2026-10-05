# core/rag.py —— 触发编排 v3（二元路由）：全部话轮统一检索，
# 命中（距离闸内/FTS 越过/降级有结果）→ LLM 只做素材整理合并；
# 未命中 → 显示「知识库无对应内容」（不调 LLM）。不做话轮分类过滤。
import re
import time
from typing import Iterator

from core.generator import LLMClient, build_messages
from core.retriever import Retriever
from core.session import SessionBuffer, SessionRecorder, extract_turn


def _fts_exact_hit(query: str, contexts: list) -> bool:
    """查询中 ≥4 字词项在任一检出 chunk 子串命中 → 越过距离阈值（防误杀）。

    中文无词边界：整串跑段提取会让「介绍一下你的项目经历」永远提不出
    「项目经历」，故中文用滑动 4 字窗口穷举词项；西文/数字仍取整段（≥4 字符）。
    """
    toks = re.findall(r"[0-9A-Za-z_]{4,}", query)
    toks += re.findall(r"(?=([一-鿿]{4}))", query)
    return any(tok in c.text for c in contexts for tok in toks)


class RagService:
    """热键/自动触发的完整编排：提取话轮 → 检索 → 命中整理/未命中提示 → 记录。"""

    REF_DIST_MAX = 0.95   # 实测校准（2026-10-05，标题锚定嵌入 + 用户真实库 308 块）：
                          # 相关问法 top=0.778-0.917，无关问题 ~1.013；0.95 两侧有余量。
                          # 调参入口在此；L2（单位向量）⇔ cos≥约0.55

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
        self.last_missed = False
        self.pending_turn: str | None = None

    def trigger(self, now: float | None = None,
                turn: str | None = None) -> Iterator[str]:
        """turn 可由调用方（主线程预提取）直达，避免子线程重复提取。"""
        self.last_notice = ""
        self.last_missed = False
        turn = getattr(self, "pending_turn", None) or turn
        self.pending_turn = None
        if turn is None:
            turn = extract_turn(self.buffer.entries, now or time.time())
        self.last_question = turn
        if not turn:
            self.last_had_refs = False
            self.last_missed = True
            self.last_notice = "知识库无对应内容"
            yield ""
            return
        contexts = self.retriever.retrieve(turn, k=5)
        reliable = (getattr(self.retriever, "distances_reliable", False)
                    and not getattr(self.retriever, "space_mismatch", False))
        top = getattr(self.retriever, "last_top_distance", None)
        hit = bool(contexts) and (
            not reliable
            or (top is not None and top <= self.REF_DIST_MAX)
            or _fts_exact_hit(turn, contexts))
        self.last_had_refs = hit
        materials = contexts if hit else []
        if not hit:
            self.last_missed = True
            self.last_notice = "知识库无对应内容"
            yield ""                  # 未命中：不调 LLM，UI 显示无对应内容
            return
        self.last_notice = f"基于知识库 · 已整理 {len(contexts)} 段资料"
        messages = build_messages(turn, materials, self.history)
        parts: list[str] = []
        for delta in self.llm.stream(messages):
            parts.append(delta)
            yield delta
        answer = "".join(parts)
        self.history.append((turn, answer))
        self.history = self.history[-5:]
        if self.recorder:
            self.recorder.add_qa(turn, materials, answer)
