# core/pipeline.py —— v3（参考 VoxRecall 迭代）：
#   ① 自适应噪声底：低音量系统音频不再被固定阈值判成静音（识别不出来的主因）
#   ② 转写独立线程：长句转写不再阻塞采集循环（中断感的主因）
#   ③ 最长持句 max_hold_sec：连续说话也定期落句，字幕保持流动
import queue
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
    """采集→能量VAD分段→独立转写线程→会话缓冲；新文本回调 on_subtitle。"""

    def __init__(self, source: AudioSource, transcriber: Transcriber,
                 buffer: SessionBuffer, recorder: SessionRecorder | None = None,
                 silence_sec: float = 1.0, min_speech_sec: float = 0.3,
                 max_hold_sec: float = 12.0, min_rms: float = 150.0) -> None:
        self.source = source
        self.transcriber = transcriber
        self.buffer = buffer
        self.recorder = recorder
        self.silence_sec = silence_sec
        self.min_speech_sec = min_speech_sec
        self.max_hold_sec = max_hold_sec
        self.min_rms = min_rms
        self.on_subtitle: Callable[[str], None] | None = None
        self.on_error: Callable[[str], None] | None = None
        self._stop = threading.Event()
        self._speech: list[bytes] = []
        self._speech_start: float | None = None
        self._speech_lock = threading.Lock()
        self._flush_lock = threading.Lock()  # 转写单飞（热键 flush 与自然 flush 串行）
        self._last_activity = time.time()
        self._noise = 0.0          # 自适应噪声底（安静块的 EMA）
        self._have_noise = False
        self._utt_q: queue.Queue = queue.Queue()
        self._utt_thread: threading.Thread | None = None
        self._drained = threading.Event()
        self._drained.set()

    def start(self) -> threading.Thread:
        self._utt_thread = threading.Thread(target=self._utt_loop, daemon=True,
                                            name="asr-flush")
        self._utt_thread.start()
        t = threading.Thread(target=self.run, daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()
        self.source.stop()

    # ------------------------------------------------------------ 采集循环
    def run(self) -> None:
        try:
            for block in self.source.chunks():
                if self._stop.is_set():
                    break
                self._vad_block(block)
            self._drain_speech()          # 采集结束：冲出最后一句
            if self._utt_thread is not None:
                self._utt_q.put(None)     # 哨兵：转写线程退出
                self._utt_thread.join(timeout=10)  # run 返回 = 全部落定
        except Exception as exc:  # 设备拔出等
            if self.on_error:
                self.on_error(str(exc))

    def _vad_block(self, block: bytes) -> None:
        now = time.time()
        dur = len(block) / 2 / self.source.sample_rate
        level = rms(block)
        threshold = max(self.min_rms, self._noise * 3.0) if self._have_noise else self.min_rms
        if level > threshold:  # 语音
            with self._speech_lock:
                if not self._speech:
                    self._speech_start = now - dur
                self._speech.append(block)
                start = self._speech_start
            self._last_activity = now
            if now - start >= self.max_hold_sec:  # 连续说话也定期落句
                self._drain_speech()
        else:
            with self._speech_lock:
                pending = bool(self._speech)
            self._noise = (0.9 * self._noise + 0.1 * level) if self._have_noise else level
            self._have_noise = True
            if pending and now - self._last_activity >= self.silence_sec:
                self._drain_speech()
        time.sleep(0)  # 让出 GIL

    def _drain_speech(self) -> None:
        """锁内摘下 pending 语音，提交转写（独立线程；未启动时同步执行）。"""
        with self._speech_lock:
            blocks, start = self._speech, self._speech_start
            self._speech, self._speech_start = [], None
        if blocks and start is not None:
            end, self._last_activity = self._last_activity, time.time()
            pcm = b"".join(blocks)
            if self._utt_thread is not None and self._utt_thread.is_alive():
                self._drained.clear()
                self._utt_q.put((pcm, start, end))
            else:
                self._transcribe_one(pcm, start, end)   # 无消费者（测试/未启动）：同步

    def flush_pending(self) -> None:
        """热键路径专用（spec §6.6）：立即转写未达静音阈值的 pending 语音。
        返回时转写已落缓冲（等消费者清空队列）。"""
        self._drain_speech()
        self._drained.wait(6.0)

    # ------------------------------------------------------------ 转写线程
    def _utt_loop(self) -> None:
        while True:
            try:
                item = self._utt_q.get(timeout=0.2)
            except queue.Empty:
                self._drained.set()
                continue
            if item is None:
                self._drained.set()
                break
            pcm, start, end = item
            self._transcribe_one(pcm, start, end)

    def _transcribe_one(self, pcm: bytes, start: float, end: float) -> None:
        with self._flush_lock:  # 审查 I6：转写单飞
            try:
                if len(pcm) / 2 / 16000 < self.min_speech_sec:
                    return
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
