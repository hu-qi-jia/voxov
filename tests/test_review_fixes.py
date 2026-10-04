# tests/test_review_fixes.py —— 最终审查修复轮（C3/I1/I2/I3/I4/I7拆分/I10/I12）
import time

import numpy as np
import pytest
import wave as _wave

from app.main_window import MainWindow


class _Rag:
    def __init__(self):
        from core.session import SessionBuffer, SessionRecorder
        self.buffer = SessionBuffer()
        self.recorder = SessionRecorder()
        self.triggered = 0
    def trigger(self):
        self.triggered += 1
        yield "**答**案"


class _Kb:
    def list_files(self):
        return []


@pytest.fixture
def win(qtbot, tmp_path, monkeypatch):
    import core.config as cc
    monkeypatch.setattr(cc, "app_root", lambda: tmp_path)
    from core.config import default_config
    rag = _Rag()
    w = MainWindow(default_config(), kb_factory=lambda: _Kb(), rag_factory=lambda: rag)
    qtbot.addWidget(w)
    return w, rag


def _wav1s(tmp_path):
    p = tmp_path / "r.wav"
    with _wave.open(str(p), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000)
        f.writeframes((np.ones(16000) * 4000).astype(np.int16).tobytes())
    return p


# --- C3：急隐藏必须藏主窗口 ---
def test_hide_hides_main_window_too(win, qtbot):
    w, _ = win
    w.show()
    w.overlay.show()
    w._on_hide()
    assert not w.isVisible() and not w.overlay.isVisible()
    w._on_hide()
    assert w.isVisible() and w.overlay.isVisible()


# --- I1：隐藏态触发热键不得弹出悬浮窗 ---
def test_hotkey_while_hidden_keeps_overlay_hidden(win, qtbot):
    w, rag = win
    w.overlay.show()
    w._on_hide()
    w._on_hotkey()
    qtbot.waitUntil(lambda: rag.triggered == 1, timeout=3000)
    assert not w.overlay.isVisible()


# --- I2：退出必须真正结束进程（清理热钩/管线） ---
def test_quit_app_stops_everything_and_quits(win, qtbot):
    w, _ = win
    stopped = []
    class _FP:
        def stop(self): stopped.append("pipeline")
    class _FB:
        def stop(self): stopped.append("bridge")
    class _FW:
        def isRunning(self): return False
    w._pipeline = _FP()
    w.bridge = _FB()
    w._worker = _FW()
    quits = []
    class _StubApp:
        def quit(self): quits.append(1)
        def processEvents(self): pass
    from PySide6.QtWidgets import QApplication
    saved_app = QApplication.instance()
    QApplication.instance = staticmethod(lambda: _StubApp())
    try:
        w.quit_app()
    finally:
        del QApplication.instance  # 还原继承的原始方法
        assert QApplication.instance() is saved_app
    assert sorted(stopped) == ["bridge", "pipeline"]
    assert quits == [1]


# --- I3a：设置保存后重建 LLM 客户端（首配 key 即刻生效） ---
class _Sig:
    def connect(self, *a): pass

def test_settings_apply_rebuilds_llm_client(win, qtbot, monkeypatch):
    w, rag = win
    import app.hotkey as hk
    class _FB:
        def __init__(self, c, h):
            self.pressed = _Sig()
            self.hidden = _Sig()
        def stop(self): pass
    monkeypatch.setattr(hk, "HotkeyBridge", _FB)
    w._on_hotkey()  # 创建 _rag
    w.cfg.llm_base_url = "https://new.example/v1"
    w.cfg.llm_api_key = "k"
    w.cfg.llm_model = "m9"
    w._apply_settings()
    assert w._rag.llm.base_url == "https://new.example/v1"
    assert w._rag.llm.model == "m9"


# --- I3b：音频设备设置必须传到 LiveAudioSource ---
def test_start_listening_passes_audio_device(win, qtbot, monkeypatch):
    w, _ = win
    import core.capture as cap
    import core.transcriber as tr
    made = {}
    class _FakeLive:
        sample_rate = 16000
        channels = 1
        def __init__(self, device_name=None, block_ms=100):
            made["device"] = device_name
        def chunks(self):
            return iter([])
        def stop(self): pass
    class _FT:
        def transcribe(self, pcm, sample_rate=16000): return "x"
    monkeypatch.setattr(cap, "LiveAudioSource", _FakeLive)
    monkeypatch.setattr(tr, "FunasrTranscriber", lambda md: _FT())
    w.cfg.audio_device = "Speakers (Realtek)"
    w.start_listening()
    assert made["device"] == "Speakers (Realtek)"
    w._pipeline = None


# --- I3c + I4：热键改后即重绑；非法热键被拒绝/回退 ---
def test_rebind_hotkeys_recreates_and_falls_back(win, qtbot, monkeypatch):
    w, _ = win
    import app.hotkey as hk
    made = []
    class _FB:
        def __init__(self, c, h):
            if c == "bad!!":
                raise ValueError("bad combo")
            made.append((c, h))
            self.pressed = _Sig()
            self.hidden = _Sig()
        def stop(self): made.append("stop")
    monkeypatch.setattr(hk, "HotkeyBridge", _FB)
    old = _FB("old", "old2")
    w.bridge = old
    w.cfg.hotkey = "ctrl+alt+q"
    w.rebind_hotkeys()
    assert ("ctrl+alt+q", "ctrl+alt+h") in made
    assert "stop" in made and w.bridge is not old
    w.cfg.hotkey = "bad!!"
    w.rebind_hotkeys()
    assert made[-1] == ("ctrl+alt+space", "ctrl+alt+h")  # 回退默认，不崩溃


def test_settings_rejects_invalid_hotkey(win, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from app.settings_dialog import SettingsDialog
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    w, _ = win
    before = w.cfg.hotkey
    dlg = SettingsDialog(w.cfg, parent=w)
    dlg.hotkey_edit.setText("bad!!")
    dlg._save()
    assert w.cfg.hotkey == before      # 未生效
    assert not dlg.result()            # 未 accept


# --- I7：彩排用独立 rag/recorder，热键走当前活跃会话 ---
def test_rehearsal_uses_dedicated_rag_and_hotkey_follows(win, qtbot, tmp_path, monkeypatch):
    w, live = win
    rehearse = _Rag()
    w._rehearsal_rag_factory = lambda: rehearse
    import core.transcriber as tr
    class _FT:
        def transcribe(self, pcm, sample_rate=16000): return "彩排"
    monkeypatch.setattr(tr, "FunasrTranscriber", lambda md: _FT())
    w.start_rehearsal(_wav1s(tmp_path))
    assert w._rehearsal_rag is rehearse
    assert w._active_rag() is rehearse
    qtbot.waitUntil(lambda: len(rehearse.buffer.entries) == 1, timeout=15000)
    w._pipeline.stop()
    w._pipeline = None
    w._on_hotkey()
    qtbot.waitUntil(lambda: rehearse.triggered == 1, timeout=3000)
    assert live.triggered == 0


# --- I10：模型缺失时首启自动弹下载向导 ---
def test_first_run_wizard_auto_opens(win, qtbot, monkeypatch):
    w, _ = win
    called = []
    w._open_wizard = lambda: called.append(1)
    w.maybe_first_run_wizard()
    assert called == [1]


def test_first_run_wizard_skips_when_models_ready(win, qtbot, monkeypatch):
    w, _ = win
    for sub in ("SenseVoiceSmall", "fsmn-vad", "ct-punc", "bge-small-zh-v1.5"):
        (w.cfg.models_dir / sub).mkdir(parents=True, exist_ok=True)
    called = []
    w._open_wizard = lambda: called.append(1)
    w.maybe_first_run_wizard()
    assert called == []


# --- I12：知识库无命中时给出"通用回答"标记 ---
def test_rag_tracks_whether_refs_found(tmp_path):
    from core.rag import RagService
    from core.retriever import Retrieved
    from core.session import TranscriptEntry
    class _R:
        def __init__(self, out): self.out = out
        def retrieve(self, q, k=5): return self.out
    class _L:
        def stream(self, m, temperature=0.3, max_tokens=500): yield "a"
    ref = Retrieved(chunk_id=1, text="t", heading_path="h", source_file="f.md", score=1.0)
    for out, expect in (([], False), ([ref], True)):
        s = RagService(_R(out), _L())
        now = time.time()
        s.buffer.add_transcript(TranscriptEntry(now - 5, now - 1, "问Redis"))
        list(s.trigger())
        assert s.last_had_refs is expect


def test_worker_notice_when_no_refs(qtbot):
    from app.workers import GenerateWorker
    class _R:
        last_question = "q"
        last_had_refs = False
        def trigger(self):
            yield "a"
    wk = GenerateWorker(_R())
    got = []
    wk.notice.connect(got.append)
    wk.start()
    assert wk.wait(3000)
    # QThread.wait 不处理事件：队列连接的 notice 须经事件循环送达
    qtbot.waitUntil(lambda: got == ["通用回答（知识库无命中）"], timeout=3000)


def test_generic_answer_notice_shown_in_overlay(win, qtbot):
    w, rag = win
    rag.last_had_refs = False
    w._on_hotkey()
    qtbot.waitUntil(lambda: "通用回答" in w.overlay.status_label.text(), timeout=3000)
