# tests/test_capture.py
import wave
import numpy as np
import pytest
from core.capture import WavFileSource

def write_wav(path, data_int16, rate, channels):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(data_int16.tobytes())

def test_mono_16k_passthrough(tmp_path):
    t = np.arange(16000, dtype=np.int16)  # 1 秒
    p = tmp_path / "a.wav"; write_wav(p, t, 16000, 1)
    src = WavFileSource(p, realtime=False)
    blocks = list(src.chunks())
    total = b"".join(blocks)
    assert src.sample_rate == 16000 and src.channels == 1
    assert len(total) == 32000  # 1s × 16000样本 × 2字节
    assert all(len(b) % 2 == 0 for b in blocks)

def test_stereo_48k_downmix_resample(tmp_path):
    t = np.arange(48000, dtype=np.float64) / 48000.0
    left = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16)
    right = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16)
    stereo = np.empty(48000 * 2, dtype=np.int16)
    stereo[0::2], stereo[1::2] = left, right
    p = tmp_path / "b.wav"; write_wav(p, stereo, 48000, 2)
    src = WavFileSource(p, realtime=False)
    total = np.frombuffer(b"".join(src.chunks()), dtype=np.int16)
    assert len(total) == 16000  # 1 秒重采样后
    # 440Hz 正弦重采样后仍是同频正弦：与参考相关系数极高
    ref = (np.sin(2 * np.pi * 440 * np.arange(16000) / 16000.0) * 10000)
    corr = np.corrcoef(total.astype(np.float64), ref)[0, 1]
    assert corr > 0.99

def test_block_size_about_100ms(tmp_path):
    t = np.zeros(16000, dtype=np.int16)
    p = tmp_path / "c.wav"; write_wav(p, t, 16000, 1)
    blocks = list(WavFileSource(p, block_ms=100, realtime=False).chunks())
    assert all(len(b) == 3200 for b in blocks)

def test_stop_terminates_iteration(tmp_path):
    t = np.zeros(16000 * 5, dtype=np.int16)
    p = tmp_path / "d.wav"; write_wav(p, t, 16000, 1)
    src = WavFileSource(p, realtime=False)
    it = src.chunks()
    next(it)
    src.stop()
    with pytest.raises(StopIteration):
        next(it)
