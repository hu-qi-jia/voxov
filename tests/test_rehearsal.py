# tests/test_rehearsal.py —— 彩排模式（spec §5④）：wav 回放走完整实时链路
import wave
import numpy as np
import pytest
from app.main_window import MainWindow


class _Rag:
    def __init__(self):
        from core.session import SessionBuffer
        self.buffer = SessionBuffer()
    def trigger(self):
        yield ""


class _Kb:
    def list_files(self):
        return []


@pytest.fixture
def win2(qtbot, tmp_path, monkeypatch):
    import core.config as cc
    cc.app_root = lambda: tmp_path
    from core.config import default_config
    cfg = default_config()
    w = MainWindow(cfg, kb_factory=_Kb, rag_factory=_Rag)
    qtbot.addWidget(w)
    return w


def _wav(tmp_path):
    p = tmp_path / "r.wav"
    with wave.open(str(p), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000)
        f.writeframes((np.ones(16000) * 4000).astype(np.int16).tobytes())  # 1s 语音
    return p


def test_start_rehearsal_builds_pipeline_and_transcribes(win2, qtbot, tmp_path, monkeypatch):
    wav = _wav(tmp_path)

    class FakeTranscriber:
        def transcribe(self, pcm, sample_rate=16000):
            return "彩排文本"

    import core.transcriber as tr
    monkeypatch.setattr(tr, "FunasrTranscriber", lambda models_dir: FakeTranscriber())
    win2.start_rehearsal(wav)
    assert win2._pipeline is not None
    qtbot.waitUntil(lambda: len(win2._rag.buffer.entries) == 1, timeout=15000)
    assert win2._rag.buffer.entries[0].text == "彩排文本"
    win2._pipeline.stop()

def test_rehearsal_button_exists(win2):
    assert win2.rehearse_btn is not None
