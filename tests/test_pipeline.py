# tests/test_pipeline.py
import wave
import numpy as np
import pytest
from pathlib import Path
from core.capture import WavFileSource
from core.pipeline import AudioPipeline, rms
from core.session import SessionBuffer, SessionRecorder
from core.transcriber import FakeTranscriber

def make_wav(path, seconds_of_speech=1, lead_silence=1, tail_silence=1.6, rate=16000):
    n = int(rate * (lead_silence + seconds_of_speech + tail_silence))
    t = np.arange(n) / rate
    sig = np.where(
        (t >= lead_silence) & (t < lead_silence + seconds_of_speech),
        np.sin(2 * np.pi * 440 * t) * 8000, 0.0)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(sig.astype(np.int16).tobytes())

def test_rms_zero_for_silence():
    assert rms(b"\x00\x00" * 8000) < 1.0
    assert rms((np.ones(8000) * 1000).astype(np.int16).tobytes()) > 500

def test_pipeline_produces_entry_and_subtitle(tmp_path):
    wav = tmp_path / "a.wav"; make_wav(wav)
    subs = []
    buf = SessionBuffer()
    p = AudioPipeline(WavFileSource(wav), FakeTranscriber("请介绍Redis"), buf)
    p.on_subtitle = subs.append
    t = p.start(); t.join(timeout=30)
    assert subs == ["请介绍Redis"]
    assert len(buf.entries) == 1
    e = buf.entries[0]
    assert 0.9 <= (e.end_ts - e.ts) <= 1.6  # 语音段时长≈1s
    assert e.text == "请介绍Redis"

def test_pipeline_silence_creates_pause_gap(tmp_path):
    # 两段语音间隔 2s > min_pause，应产出两个 entry，段间 gap ≈ 2s
    rate = 16000
    n = int(rate * 5)
    t = np.arange(n) / rate
    speech = ((t >= 1) & (t < 2)) | ((t >= 4) & (t < 5))
    sig = np.where(speech, np.sin(2 * np.pi * 440 * t) * 8000, 0.0)
    wav = tmp_path / "b.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(sig.astype(np.int16).tobytes())
    buf = SessionBuffer()
    p = AudioPipeline(WavFileSource(wav), FakeTranscriber("段"), buf)
    t2 = p.start(); t2.join(timeout=30)
    assert len(buf.entries) == 2
    gap = buf.entries[1].ts - buf.entries[0].end_ts
    assert 1.5 <= gap <= 2.5

def test_pipeline_records_transcript(tmp_path):
    wav = tmp_path / "c.wav"; make_wav(wav)
    buf, rec = SessionBuffer(), SessionRecorder()
    p = AudioPipeline(WavFileSource(wav), FakeTranscriber("文本"), buf, recorder=rec)
    p.start().join(timeout=30)
    assert len(rec.transcripts) == 1

def test_flush_pending_drains_speech_buffer(tmp_path):
    # spec §6.6 竞态：语音尚未达静音阈值（管线仍在等待），热键路径强刷应立即产出
    wav = tmp_path / "e.wav"; make_wav(wav)
    p = AudioPipeline(WavFileSource(wav), FakeTranscriber("刚说完的问题"), SessionBuffer())
    speech = (np.ones(16000, dtype=np.int16) * 4000).tobytes()  # 1s 语音，rms>500
    with p._speech_lock:  # 注入 pending 状态（等价于静音等待期）
        p._speech = [speech]
        p._speech_start = 100.0
    p._last_activity = 101.0
    p.flush_pending()
    assert len(p.buffer.entries) == 1
    assert p.buffer.entries[0].text == "刚说完的问题"
    with p._speech_lock:
        assert p._speech == []  # 已清空，不会重复转写

def test_flush_pending_noop_when_idle(tmp_path):
    wav = tmp_path / "f.wav"; make_wav(wav)
    buf = SessionBuffer()
    p = AudioPipeline(WavFileSource(wav), FakeTranscriber("x"), buf)
    p.flush_pending()  # 无 pending：安全空转
    assert buf.entries == []

def test_pipeline_transcriber_error_calls_on_error(tmp_path):
    wav = tmp_path / "d.wav"; make_wav(wav)
    errs = []
    class Boom:
        def transcribe(self, pcm, sample_rate=16000):
            raise RuntimeError("asr崩了")
    p = AudioPipeline(WavFileSource(wav), Boom(), SessionBuffer())
    p.on_error = errs.append
    p.start().join(timeout=30)
    assert errs and "asr崩了" in errs[0]
