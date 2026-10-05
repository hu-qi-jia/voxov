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
    # 嵌入空间自愈：KB 若由不同嵌入模型构建（如降级期入库），用当前模型重嵌全部内容。
    # 只在真实模型下执行——降级模式重嵌会污染空间（kb._ensure_space 会拒绝降级入库）。
    try:
        stored = kb.embedder_id()
        if ((stored is None and kb.chunk_count() > 0) or
                (stored not in (None, embedder.id) and embedder.id.startswith("onnx:"))):
            n = kb.reembed(embedder)
            print(f"[知识库] 嵌入空间不匹配（{stored}），已用当前模型重嵌 {n} 块")
    except Exception:
        pass
    if cfg.llm_base_url and cfg.llm_api_key:   # 后台预热 LLM 连接，首答不付冷启动
        import threading
        import time as _time

        def _warmup_loop():
            """连接池按 (url,key,model) 共享——周期预热让任何时刻的首答都拿到热连接
            （启动时的一次性预热撑不过面试前几小时的空窗）。"""
            while True:
                try:
                    rag.llm.warmup()
                except Exception:
                    pass
                _time.sleep(240)

        threading.Thread(target=_warmup_loop, daemon=True, name="llm-warmup").start()
    return cfg, kb, make_rag, recorder


def main() -> int:
    app = QApplication(sys.argv)
    from app.theme import apply as apply_theme
    apply_theme(app)
    app.setQuitOnLastWindowClosed(False)
    cfg, kb, make_rag, recorder = build_app()
    rag = make_rag(recorder)       # 启动默认实例（warmup/兼容）；每次生成由工厂新建
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
        faulthandler.enable(file=fh)   # 崩溃（含 Qt fatal）时留 Python 侧栈
        faulthandler.dump_traceback_later(45, exit=False, file=fh)
    except Exception:
        pass
    # 诊断：Qt 消息（含 qFatal 原因文本）落盘——窗口版 stderr 丢失，闪退曾无从排查
    try:
        from PySide6.QtCore import qInstallMessageHandler, QtMsgType

        def _qt_log(msg_type, context, message):
            kinds = {QtMsgType.QtDebugMsg: "DEBUG", QtMsgType.QtInfoMsg: "INFO",
                     QtMsgType.QtWarningMsg: "WARN", QtMsgType.QtCriticalMsg: "CRIT",
                     QtMsgType.QtFatalMsg: "FATAL"}
            with open(cfg.data_dir / "qt.log", "a", encoding="utf-8") as f:
                f.write(f"{kinds.get(msg_type, '?')} {message}\n")

        qInstallMessageHandler(_qt_log)
    except Exception:
        pass
    from core.downloader import models_ready
    models_ok = models_ready(cfg.models_dir)
    win = MainWindow(cfg, kb_factory=lambda: kb,
                     rag_factory=lambda: make_rag(recorder))
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
