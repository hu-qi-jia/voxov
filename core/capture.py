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
