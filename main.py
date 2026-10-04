# main.py
import sys

from PySide6.QtWidgets import QApplication

import core.config as cc
from app.main_window import MainWindow
from app.tray import create_tray


def build_app():
    cfg = cc.load_config(cc.app_root() / "data")  # 审查 C2：打包后 __file__ 在 _internal
    cfg.ensure_dirs()
    from core.embedder import BgeEmbedder, HashEmbedder
    from core.kb import KnowledgeBase
    from core.rag import RagService
    from core.generator import LLMClient
    from core.retriever import Retriever
    from core.session import SessionRecorder
    from core.downloader import models_ready
    models_ok = models_ready(cfg.models_dir)
    embedder = BgeEmbedder(cfg.models_dir / "bge-small-zh-v1.5") if models_ok else HashEmbedder()
    kb = KnowledgeBase(cfg.kb_path, embedder)

    def make_rag(recorder):
        return RagService(Retriever(kb, embedder),
                          LLMClient(cfg.llm_base_url, cfg.llm_api_key, cfg.llm_model),
                          recorder=recorder)

    recorder = SessionRecorder(sessions_dir=cfg.sessions_dir)          # 审查 I7：落盘
    rehearsal_rag = lambda: make_rag(SessionRecorder(  # noqa: E731 - 彩排独立会话（spec §5④）
        sessions_dir=cfg.sessions_dir, rehearsal=True))
    rag = make_rag(recorder)
    return cfg, kb, rag, recorder, rehearsal_rag


def main() -> int:
    app = QApplication(sys.argv)
    from app.theme import apply as apply_theme
    apply_theme(app)
    app.setQuitOnLastWindowClosed(False)
    cfg, kb, rag, recorder, rehearsal_factory = build_app()
    from core.downloader import models_ready
    models_ok = models_ready(cfg.models_dir)
    win = MainWindow(cfg, kb_factory=lambda: kb, rag_factory=lambda: rag,
                     rehearsal_rag_factory=rehearsal_factory)
    win._recorder = recorder
    win._started_without_models = not models_ok   # 成功后提示重启升级语义检索
    win.show()
    win.maybe_auto_download()      # 开箱即用：缺模型后台自动下载，不弹窗
    win.rebind_hotkeys()           # 审查 I3c：热键由主窗口持有，设置保存后重绑
    tray = create_tray(win)
    win.tray = tray
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
