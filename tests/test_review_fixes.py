# tests/test_review_fixes.py —— 最终审查修复轮（C3/I1/I2/I12）。
# _apply_settings/rebind_hotkeys 已恢复于主窗（审查前修正轮），锚点测试在
# tests/test_main_window.py；热键保存校验由 SettingsPage 承担（tests/test_settings_page.py）；
# 彩排（I7）整体移除。
import time

import pytest

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


# --- C3：急隐藏必须藏主窗口 ---
def test_hide_hides_main_window_too(win, qtbot):
    w, _ = win
    w.show()
    w._on_hide()
    assert not w.isVisible()
    w._on_hide()
    assert w.isVisible()


# --- I1：隐藏态触发热键仍照常生成（无悬浮窗，无可见面） ---
def test_hotkey_while_hidden_still_generates(win, qtbot):
    w, rag = win
    w.show()
    w._on_hide()
    w._on_hotkey()
    qtbot.waitUntil(lambda: rag.triggered == 1, timeout=3000)
    assert not w.isVisible()


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


# --- I3a/I3c：_apply_settings/rebind_hotkeys 锚点测试在 tests/test_main_window.py；
#     I4 的保存校验由 SettingsPage 承担（tests/test_settings_page.py）---
def test_settings_page_rejects_invalid_hotkey(win, qtbot):
    w, _ = win
    before = w.cfg.hotkey
    w.settings_page.hotkey_edit.setText("bad!!")
    assert w.settings_page.save() is False   # 拒绝保存
    assert w.cfg.hotkey == before            # 未生效


# --- I3b：音频设备设置必须传到 LiveAudioSource（异步版见 test_download_flow.py）---


# --- I7：彩排已整体移除（retro 壳）——无 start_rehearsal/_rehearsal_rag_factory ---

# --- I10：首启缺模型引导 → 已升级为后台自动下载（tests/test_download_flow.py）---


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


def test_worker_notice_passthrough(qtbot):
    from app.workers import GenerateWorker
    class _R:
        last_question = "q"
        last_notice = "通用回答（知识库无命中）"
        def trigger(self):
            yield "a"
    wk = GenerateWorker(_R())
    got = []
    wk.notice.connect(got.append)
    wk.start()
    assert wk.wait(3000)
    # QThread.wait 不处理事件：队列连接的 notice 须经事件循环送达
    qtbot.waitUntil(lambda: got == ["通用回答（知识库无命中）"], timeout=3000)


def test_generic_answer_notice_shown_in_chat(win, qtbot):
    w, rag = win
    rag.last_notice = "开放题 · 未用资料"
    w._on_hotkey()
    qtbot.waitUntil(lambda: w._chat_answer is not None
                    and "开放题" in w._chat_answer.note.text(), timeout=3000)
