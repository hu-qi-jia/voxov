# core/session.py
import time as _time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable


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
