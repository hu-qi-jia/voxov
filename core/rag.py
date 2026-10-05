# core/rag.py —— 触发编排 v4（检索为主，参考 personal-ai-memory「正文不向量化」）：
# 主路=问题向量+标题直配命中节 → 单节直出原文（0 时延），跨节才交 LLM 缝合；
# 兜底=正文向量/FTS 过闸（命中块扩成整节）；全空 →「知识库无对应内容」（不调 LLM）。
import re
import time
from datetime import datetime
from typing import Iterator

from core.generator import LLMClient, NO_ANSWER_SENTINEL, build_messages, cap_materials
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
                 recorder: SessionRecorder | None = None,
                 log_file=None) -> None:
        self.retriever = retriever
        self.llm = llm
        self.recorder = recorder
        self.log_file = log_file           # data/rag.log：检索路径/耗时落盘（冻结态取证）
        self.buffer = SessionBuffer()
        self.history: list[tuple[str, str]] = []
        self.last_question: str = ""
        self.last_had_refs = True
        self.last_notice = ""
        self.last_missed = False
        self.pending_turn: str | None = None

    def _log(self, msg: str) -> None:
        if self.log_file is None:
            return
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%H:%M:%S} {msg}\n")
        except OSError:
            pass

    def _match_sections_materials(self, turn: str) -> list:
        """检索主路：问题向量+标题直配命中节 → 整节材料。测试桩没有这两个
        方法时返回空（自动退回正文向量兜底路）。"""
        matcher = getattr(self.retriever, "match_sections", None)
        loader = getattr(self.retriever, "section_materials", None)
        if matcher is None or loader is None:
            return []
        hits = matcher(turn)
        return loader(hits) if hits else []

    def trigger(self, now: float | None = None,
                turn: str | None = None) -> Iterator[str]:
        """turn 可由调用方（主线程预提取）直达，避免子线程重复提取。

        三层漏斗（检索为主，LLM 只做跨节缝合）：
        ① 问题向量+标题直配命中节 → 单节直出原文（0 时延）；多节交 LLM 缝合
        ② 正文向量/FTS 过闸 → 命中块扩成整节（同上分流）
        ③ 全空 → 「知识库无对应内容」（不调 LLM）"""
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
            self._log("miss 空话轮")
            yield ""
            return
        t0 = time.monotonic()
        materials = self._match_sections_materials(turn)
        if not materials:
            contexts = self.retriever.retrieve(turn, k=5)
            reliable = (getattr(self.retriever, "distances_reliable", False)
                        and not getattr(self.retriever, "space_mismatch", False))
            top = getattr(self.retriever, "last_top_distance", None)
            hit = bool(contexts) and (
                not reliable
                or (top is not None and top <= self.REF_DIST_MAX)
                or _fts_exact_hit(turn, contexts))
            if not hit:
                self.last_had_refs = False
                self.last_missed = True
                self.last_notice = "知识库无对应内容"
                self._log(f"miss 兜底未过闸 耗时={time.monotonic()-t0:.2f}s")
                yield ""              # 未命中：不调 LLM，UI 显示无对应内容
                return
            self.last_had_refs = True
            expand = getattr(self.retriever, "expand_to_sections", None)
            materials = cap_materials(expand(contexts) if expand else contexts)
        materials = cap_materials(materials)
        if len(materials) > 1 and 0 < materials[1].score < 1.0:
            # 直出收紧：第二名是向量擦边命中（score<1.0）且第一名足够强（≥0.72）
            # 或明显领先（分差 ≥0.08）时——直出第一名，不劳 LLM 缝合。
            #（实测「本地协议客户管理」top1=0.716 / top2=0.559 曾被送进 50s 的 LLM 路。
            #  双精确标题命中 score=1.0 豁免：两节都被点名时确实该缝合。）
            top, second = materials[0], materials[1]
            if top.score >= 0.72 or top.score - second.score >= 0.08:
                materials = materials[:1]
        if len(materials) == 1:
            # 单节命中：答案就在库里，原文直出——零时延、零 token、永不失败
            m = materials[0]
            self.last_notice = f"知识库原文 · {m.source_file} › {m.heading_path}"
            self._log(f"direct [{m.source_file} › {m.heading_path}] "
                      f"{len(m.text)}字 耗时={time.monotonic()-t0:.2f}s")
            yield m.text
            self.history.append((turn, m.text))
            self.history = self.history[-5:]
            if self.recorder:
                self.recorder.add_qa(turn, [m], m.text)
            return
        self.last_notice = f"基于知识库 · 已整理 {len(materials)} 节资料"
        self._log(f"llm {len(materials)}节 "
                  f"[{' | '.join(m.heading_path[:20] for m in materials)}] "
                  f"检索耗时={time.monotonic()-t0:.2f}s")
        messages = build_messages(turn, materials, self.history)
        parts: list[str] = []
        held = ""                     # 哨兵扣留（参考 personal-ai-memory aiIntegrate）：
        released = False              # 前几个字符先不出，确认不是「[无法回答]」再放行，
        for delta in self.llm.stream(messages):   # 否则面板会先把哨兵当答案渲染再抹掉
            parts.append(delta)
            if released:
                yield delta
                continue
            held += delta
            t = held.lstrip()
            if len(t) <= len(NO_ANSWER_SENTINEL) and NO_ANSWER_SENTINEL.startswith(t):
                continue              # 仍可能是哨兵前缀：继续扣
            released = True
            yield held                # 放行扣留的全部
            held = ""
        answer = "".join(parts).strip()
        rest = answer[len(NO_ANSWER_SENTINEL):]
        is_no_answer = (
            # 哨兵±标点/空白：资料不足以回答
            (answer.startswith(NO_ANSWER_SENTINEL)
             and (not rest or not re.search(r"[\w一-鿿]", rest)))
            # 流在哨兵中途被截断（一直没放行）：同为「明说答不了」
            or (not released and bool(answer) and NO_ANSWER_SENTINEL.startswith(answer)))
        if is_no_answer:
            # 模型判定资料不足以回答：等同未命中，哨兵不给用户、不入历史、不记 QA
            self.last_had_refs = False
            self.last_missed = True
            self.last_notice = "知识库无对应内容"
            yield ""
            return
        self.history.append((turn, answer))
        self.history = self.history[-5:]
        if self.recorder:
            self.recorder.add_qa(turn, materials, answer)
