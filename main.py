# main.py
import sys

from PySide6.QtWidgets import QApplication

import core.config as cc
from app.main_window import MainWindow
from app.tray import create_tray


def build_app():
    cfg = cc.load_config(cc.app_root() / "data")  # 审查 C2：打包后 __file__ 在 _internal
    cfg.ensure_dirs()
    from core.embedder import OnnxEmbedder, HashEmbedder
    from core.kb import KnowledgeBase
    from core.rag import RagService
    from core.generator import LLMClient
    from core.retriever import Retriever
    from core.session import SessionRecorder
    from core.downloader import models_ready
    models_ok = models_ready(cfg.models_dir)
    try:
        embedder = OnnxEmbedder(cfg.models_dir / "embed") if models_ok else HashEmbedder()
    except Exception:
        embedder = HashEmbedder()
    kb = KnowledgeBase(cfg.kb_path, embedder)

    def make_rag(recorder):
        return RagService(Retriever(kb, embedder),
                          LLMClient(cfg.llm_base_url, cfg.llm_api_key, cfg.llm_model),
                          recorder=recorder)

    recorder = SessionRecorder(sessions_dir=cfg.sessions_dir)          # 审查 I7：落盘
    rag = make_rag(recorder)
    if cfg.llm_base_url and cfg.llm_api_key:   # 后台预热 LLM 连接，首答不付冷启动
        import threading
        threading.Thread(target=rag.llm.warmup, daemon=True, name="llm-warmup").start()
    return cfg, kb, rag, recorder


def main() -> int:
    app = QApplication(sys.argv)
    from app.theme import apply as apply_theme
    apply_theme(app)
    app.setQuitOnLastWindowClosed(False)
    cfg, kb, rag, recorder = build_app()
    # 单实例：两个实例同时自动下载同一目录会互相破坏。
    # 第二次启动不劝退——先尝试唤起首实例（reveal 急隐藏态），唤起失败才提示。
    from app.instance import (acquire_single_instance, release_single_instance,
                              start_summon_server, try_summon_running_instance)
    if not acquire_single_instance(cfg.data_dir):
        if try_summon_running_instance():
            return 0    # 已把首实例唤到前台（含急隐藏态），本次启动静默退出
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(
            None, "voxov",
            "应用已在运行，但唤起失败。\n可在运行中的应用里按 ctrl+alt+h 切换显示。")
        return 1
    app.aboutToQuit.connect(release_single_instance)
    # 诊断：启动 45s 后把全部 Python 线程栈落盘（排查冻结环境 worker 卡点）
    try:
        import faulthandler
        fh = open(cfg.data_dir / "threads_dump.log", "w", encoding="utf-8")
        faulthandler.dump_traceback_later(45, exit=False, file=fh)
    except Exception:
        pass
    from core.downloader import models_ready
    models_ok = models_ready(cfg.models_dir)
    win = MainWindow(cfg, kb_factory=lambda: kb, rag_factory=lambda: rag)
    win._recorder = recorder
    win._started_without_models = not models_ok   # 成功后提示重启升级语义检索
    win.show()
    win.maybe_auto_download()      # 开箱即用：缺模型后台自动下载，不弹窗
    win.rebind_hotkeys()           # 审查 I3c：热键由主窗口持有，设置保存后重绑
    tray = create_tray(win)
    win.tray = tray
    # 唤起通道：后续启动经此把首实例带到前台（含从急隐藏找回）
    from app.instance import SUMMON_SERVER_NAME
    start_summon_server(SUMMON_SERVER_NAME, lambda: win.reveal())
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
