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
        self.last_question: str = ""
        self.last_had_refs = True  # 审查 I12：知识库是否命中（无命中 → UI 标"通用回答"）

    def trigger(self, now: float | None = None) -> Iterator[str]:
        question = extract_question(self.buffer.entries, now or time.time())
        self.last_question = question
        if not question:
            self.last_had_refs = True
            yield ""  # 空问题短路：不调 LLM，UI 显示"未识别到问题"
            return
        contexts = self.retriever.retrieve(question, k=5)
        self.last_had_refs = bool(contexts)
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
