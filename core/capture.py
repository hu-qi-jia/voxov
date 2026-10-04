# core/capture.py
import queue
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


class AudioDeviceError(RuntimeError):
    pass


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
        import pyaudiowpatch as pyaudio
        if self._device_name:
            for d in p.get_loopback_device_info_generator():
                if self._device_name in d["name"]:
                    return d
            raise AudioDeviceError(f"找不到 loopback 设备: {self._device_name}")
        # 默认输出对应的 loopback
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
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
