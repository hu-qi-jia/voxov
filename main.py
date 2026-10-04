# main.py
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.hotkey import HotkeyBridge
from app.main_window import MainWindow
from app.overlay import OverlayWindow
from app.tray import create_tray
from core.config import default_config, load_config


def build_app():
    cfg = load_config(Path(__file__).parent / "data")
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
    llm = LLMClient(cfg.llm_base_url, cfg.llm_api_key, cfg.llm_model)
    recorder = SessionRecorder()
    rag = RagService(Retriever(kb, embedder), llm, recorder=recorder)
    return cfg, kb, rag, recorder


def main() -> int:
    app = QApplication(sys.argv)
    from app.theme import apply as apply_theme
    apply_theme(app)
    app.setQuitOnLastWindowClosed(False)
    cfg, kb, rag, recorder = build_app()
    win = MainWindow(cfg, kb_factory=lambda: kb, rag_factory=lambda: rag)
    win._recorder = recorder
    win.show()
    bridge = HotkeyBridge(cfg.hotkey, cfg.hide_hotkey)
    bridge.pressed.connect(win._on_hotkey)
    bridge.hidden.connect(win._on_hide)   # 急隐藏（spec §6.5）
    tray = create_tray(win)
    win.tray = tray
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
