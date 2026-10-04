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
        self._speech: list[bytes] = []
        self._speech_start: float | None = None
        self._speech_lock = threading.Lock()
        self._flush_lock = threading.Lock()  # 审查 I6：转写单飞（热键 flush 与自然 flush 串行）
        self._last_activity = time.time()

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self.run, daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()
        self.source.stop()

    def run(self) -> None:
        try:
            for block in self.source.chunks():
                if self._stop.is_set():
                    break
                now = time.time()
                block_dur = len(block) / 2 / self.source.sample_rate
                if rms(block) > 500:  # 语音
                    with self._speech_lock:
                        if not self._speech:
                            self._speech_start = now - block_dur
                        self._speech.append(block)
                    self._last_activity = now
                else:
                    with self._speech_lock:
                        has_pending = bool(self._speech)
                    if has_pending and now - self._last_activity >= self.silence_sec:
                        self._drain_and_flush()
                time.sleep(0)  # 让出 GIL
            self._drain_and_flush()
        except Exception as exc:  # 设备拔出等
            if self.on_error:
                self.on_error(str(exc))

    def _drain_and_flush(self) -> None:
        """锁内摘下 pending 语音，锁外转写（避免长时间持锁阻塞采集线程）。"""
        with self._speech_lock:
            blocks, start = self._speech, self._speech_start
            self._speech, self._speech_start = [], None
        if blocks and start is not None:
            with self._flush_lock:
                self._flush(blocks, start, self._last_activity)

    def flush_pending(self) -> None:
        """热键路径专用（spec §6.6）：立即转写未达静音阈值的 pending 语音，
        保证提取的问题包含面试官刚说完的最后一句。"""
        self._drain_and_flush()

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
