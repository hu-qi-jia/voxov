# tests/test_download_flow.py —— 开箱即用下载链路：DownloadWorker / 向导 / 首启自动下载 / 监听门禁
import time

import pytest

import core.downloader as dl


# --- 向导：打开即自动下载（开箱即用），异常可见、可重试 ---
def _mk_wizard_env(qtbot, monkeypatch, behavior):
    """starter 提供共享 DownloadWorker；behavior: 'ok' | 'fail' | 'slow'。"""
    from app.workers import DownloadWorker

    calls = {"n": 0}

    def fake_ensure(md, log):
        calls["n"] += 1
        if behavior == "fail" and calls["n"] == 1:
            raise RuntimeError("网络错误")
        log("[开始下载] iic/SenseVoiceSmall")
        if behavior == "slow":
            time.sleep(0.4)
        log("[完成] SenseVoiceSmall")

    monkeypatch.setattr(dl, "ensure_models", fake_ensure)
    holder = {"w": None}

    def starter():
        w = DownloadWorker(models_dir=None)
        holder["w"] = w
        w.start()
        return w

    from app.wizard import ModelWizard
    wiz = ModelWizard(starter)
    qtbot.addWidget(wiz)
    return wiz, holder, calls


def test_wizard_auto_starts_download_without_click(qtbot, monkeypatch):
    wiz, holder, calls = _mk_wizard_env(qtbot, monkeypatch, "ok")
    qtbot.waitUntil(lambda: "[完成]" in wiz.log_view.toPlainText(), timeout=3000)
    assert calls["n"] == 1                       # 未点任何按钮，下载已发生
    assert not wiz.retry_btn.isEnabled()         # 下载中重试按钮禁用


def test_wizard_failure_shows_error_and_enables_retry(qtbot, monkeypatch):
    wiz, holder, calls = _mk_wizard_env(qtbot, monkeypatch, "fail")
    qtbot.waitUntil(lambda: "下载失败" in wiz.log_view.toPlainText(), timeout=3000)
    assert "网络错误" in wiz.log_view.toPlainText()   # 错误必须可见（Bug 1）
    assert wiz.retry_btn.isEnabled()
    wiz.retry_btn.click()                        # 重试 = 断点续传
    qtbot.waitUntil(lambda: calls["n"] == 2, timeout=3000)
    qtbot.waitUntil(lambda: "[完成]" in wiz.log_view.toPlainText(), timeout=3000)


def test_wizard_success_message(qtbot, monkeypatch):
    wiz, holder, calls = _mk_wizard_env(qtbot, monkeypatch, "ok")
    qtbot.waitUntil(lambda: "全部完成" in wiz.log_view.toPlainText(), timeout=3000)


def test_wizard_heartbeat_label(qtbot, monkeypatch):
    wiz, holder, calls = _mk_wizard_env(qtbot, monkeypatch, "slow")
    qtbot.waitUntil(lambda: "[开始下载]" in wiz.log_view.toPlainText(), timeout=3000)
    wiz._tick_heartbeat()
    assert "下载中" in wiz.heart_label.text()
    # 收尾必须等线程结束、信号送达——否则悬空投递+活动线程拖到解释器
    # 退出期，PySide6 硬崩（exit 127），且毒化同一进程内后续所有退出。
    qtbot.waitUntil(lambda: "全部完成" in wiz.log_view.toPlainText(), timeout=3000)
    holder["w"].wait(3000)


# --- 首启自动下载（开箱即用）：不弹窗，后台下载 + 状态灯 ---
class _Rag:
    def __init__(self):
        from core.session import SessionBuffer, SessionRecorder
        self.buffer = SessionBuffer()
        self.recorder = SessionRecorder()
    def trigger(self):
        yield "a"


class _Kb:
    def list_files(self):
        return []


@pytest.fixture
def win(qtbot, tmp_path, monkeypatch):
    import core.config as cc
    monkeypatch.setattr(cc, "app_root", lambda: tmp_path)
    from core.config import default_config
    from app.main_window import MainWindow
    rag = _Rag()
    w = MainWindow(default_config(), kb_factory=lambda: _Kb(), rag_factory=lambda: rag)
    qtbot.addWidget(w)
    return w


def _fake_ensure(behavior):
    def fake(md, log):
        if behavior == "fail":
            raise RuntimeError("网络错误")
        log("[完成] x")
    return fake


def test_auto_download_starts_when_models_missing(win, qtbot, monkeypatch):
    monkeypatch.setattr(dl, "ensure_models", _fake_ensure("ok"))
    win.maybe_auto_download()
    assert win._dl_worker is not None
    qtbot.waitUntil(lambda: "下载中" in win.model_status_label.text(), timeout=3000)
    # 等 finished_ok 送达（事件循环），不留未投递信号/活动定时器给拆除期
    qtbot.waitUntil(lambda: "就绪" in win.model_status_label.text(), timeout=3000)


def test_auto_download_skips_when_models_ready(win, qtbot):
    for sub in ("SenseVoiceSmall", "fsmn-vad", "ct-punc", "bge-small-zh-v1.5"):
        (win.cfg.models_dir / sub).mkdir(parents=True, exist_ok=True)
    win.maybe_auto_download()
    assert win._dl_worker is None
    assert "就绪" in win.model_status_label.text()


def test_auto_download_failure_marks_state(win, qtbot, monkeypatch):
    monkeypatch.setattr(dl, "ensure_models", _fake_ensure("fail"))
    win.maybe_auto_download()
    qtbot.waitUntil(lambda: "下载失败" in win.model_status_label.text(), timeout=3000)
    assert "下载失败" in win.statusBar().currentMessage()


def test_auto_download_ok_prompts_restart_when_embedder_fell_back(win, qtbot, monkeypatch):
    monkeypatch.setattr(dl, "ensure_models", _fake_ensure("ok"))
    win._started_without_models = True
    win.maybe_auto_download()
    qtbot.waitUntil(lambda: win._dl_worker is not None and not win._dl_worker.isRunning(),
                    timeout=3000)
    qtbot.waitUntil(lambda: "就绪" in win.model_status_label.text(), timeout=3000)
    assert "重启" in win.statusBar().currentMessage()


def test_dl_heartbeat_ticks_elapsed(win, qtbot, monkeypatch):
    monkeypatch.setattr(dl, "ensure_models", _fake_ensure("ok"))
    win.maybe_auto_download()
    win._tick_dl_heartbeat()
    assert "已" in win.model_status_label.text() and "s" in win.model_status_label.text()
    qtbot.waitUntil(lambda: "就绪" in win.model_status_label.text(), timeout=3000)


# --- DownloadWorker：异常必须浮出为 failed 信号（Bug 1 根因 M6） ---
def test_download_worker_emits_failed_on_error(qtbot, monkeypatch):
    from app.workers import DownloadWorker

    def boom(models_dir, log):
        log("[开始下载] fake")
        raise RuntimeError("modelscope import 失败")

    monkeypatch.setattr(dl, "ensure_models", boom)
    w = DownloadWorker(models_dir=None)
    lines, fails = [], []
    w.line.connect(lines.append)
    w.failed.connect(fails.append)
    w.start()
    qtbot.waitUntil(lambda: len(fails) == 1, timeout=3000)
    assert "modelscope import 失败" in fails[0]
    assert lines == ["[开始下载] fake"]


def test_download_worker_emits_finished_ok_on_success(qtbot, monkeypatch):
    from app.workers import DownloadWorker

    monkeypatch.setattr(dl, "ensure_models", lambda md, log: log("[完成] x"))
    w = DownloadWorker(models_dir=None)
    lines, oks = [], []
    w.line.connect(lines.append)
    w.finished_ok.connect(lambda: oks.append(1))
    w.start()
    qtbot.waitUntil(lambda: oks == [1], timeout=3000)
    assert lines == ["[完成] x"]


def test_download_worker_finished_ok_after_wait(qtbot, monkeypatch):
    """QThread.wait 不处理事件：结束后须经事件循环取队列信号（审查轮教训）。"""
    from app.workers import DownloadWorker

    monkeypatch.setattr(dl, "ensure_models", lambda md, log: None)
    w = DownloadWorker(models_dir=None)
    oks = []
    w.finished_ok.connect(lambda: oks.append(1))
    w.start()
    assert w.wait(3000)
    qtbot.waitUntil(lambda: oks == [1], timeout=3000)


# --- Bug 2：监听门禁 + 转写器后台加载 ---
def test_load_worker_loaded_and_failed(qtbot, monkeypatch):
    import core.transcriber as tr
    from app.workers import LoadWorker

    class _FT:
        def transcribe(self, pcm, sample_rate=16000): return "x"

    monkeypatch.setattr(tr, "FunasrTranscriber", lambda md: _FT())
    w = LoadWorker(models_dir=None)
    got = []
    w.loaded.connect(got.append)
    w.start()
    qtbot.waitUntil(lambda: len(got) == 1 and isinstance(got[0], _FT), timeout=3000)

    def raiser(md):
        raise RuntimeError("模型损坏")

    monkeypatch.setattr(tr, "FunasrTranscriber", raiser)
    w2 = LoadWorker(models_dir=None)
    fails = []
    w2.failed.connect(fails.append)
    w2.start()
    qtbot.waitUntil(lambda: len(fails) == 1, timeout=3000)
    assert "模型损坏" in fails[0]


def test_start_listening_gated_when_models_missing(win, qtbot, monkeypatch):
    import core.transcriber as tr
    monkeypatch.setattr(dl, "models_ready", lambda md: False)

    def boom(md):
        raise AssertionError("门禁未生效：不应构造转写器")

    monkeypatch.setattr(tr, "FunasrTranscriber", boom)
    opened = []
    win._open_wizard = lambda: opened.append(1)
    win.start_listening()
    assert win._pipeline is None
    assert opened == [1]
    assert "未就绪" in win.statusBar().currentMessage()


def _patch_av(monkeypatch, transcriber_text="x"):
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
        def stop(self):
            pass

    class _FT:
        def transcribe(self, pcm, sample_rate=16000):
            return transcriber_text

    monkeypatch.setattr(cap, "LiveAudioSource", _FakeLive)
    monkeypatch.setattr(tr, "FunasrTranscriber", lambda md: _FT())
    monkeypatch.setattr(dl, "models_ready", lambda md: True)
    return made


def test_start_listening_loads_async_and_passes_device(win, qtbot, monkeypatch):
    made = _patch_av(monkeypatch)
    win.cfg.audio_device = "Speakers (Realtek)"
    win.start_listening()
    assert not win.start_btn.isEnabled()        # 加载期间禁用（Bug 2：无响应观感）
    qtbot.waitUntil(lambda: win._pipeline is not None, timeout=5000)
    assert made["device"] == "Speakers (Realtek)"   # 审查 I3b 不回退
    assert win.start_btn.isEnabled()                # 完成后恢复
    win._pipeline.stop()
    win._pipeline = None


def test_start_listening_load_failure_surfaces(win, qtbot, monkeypatch):
    import core.transcriber as tr
    monkeypatch.setattr(dl, "models_ready", lambda md: True)
    monkeypatch.setattr(tr, "FunasrTranscriber",
                        lambda md: (_ for _ in ()).throw(RuntimeError("模型损坏")))
    win.start_listening()
    qtbot.waitUntil(lambda: "启动失败" in win.statusBar().currentMessage(), timeout=5000)
    assert win._pipeline is None
    assert win.start_btn.isEnabled()            # 失败后可重试
    assert "启动失败" in win.overlay.status_label.text()


def test_rehearsal_also_gated_when_models_missing(win, qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(dl, "models_ready", lambda md: False)
    opened = []
    win._open_wizard = lambda: opened.append(1)
    win.start_rehearsal(tmp_path / "x.wav")
    assert win._pipeline is None
    assert opened == [1]
