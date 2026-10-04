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
    assert win._dl_worker.wait(3000)
    qtbot.waitUntil(lambda: win._dl_worker is None or not win._dl_worker.isRunning(), timeout=3000)


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
    win._dl_worker.wait(3000)


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
