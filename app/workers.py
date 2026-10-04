# app/workers.py —— 后台生成 worker。所有 UI 更新经信号（队列连接）回主线程，
# worker 线程内绝不直接碰 QWidget。
import time

from PySide6.QtCore import QThread, Signal


class DownloadWorker(QThread):
    """模型下载线程（Bug 1 / M6）：任何异常浮出为 failed，绝不静默死亡。"""
    line = Signal(str)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, models_dir) -> None:
        super().__init__()
        self.models_dir = models_dir
        self._t0 = time.monotonic()   # 创建即记起点（UI 心跳用）

    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    def run(self) -> None:
        try:
            from core.downloader import ensure_models
            ensure_models(self.models_dir, self.line.emit)
            self.finished_ok.emit()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class GenerateWorker(QThread):
    chunk = Signal(str)      # 答案增量
    question = Signal(str)   # 提取到的问题（悬浮窗标题）
    notice = Signal(str)     # 审查 I12：无知识库命中等状态提示
    done = Signal()
    failed = Signal(str)

    def __init__(self, rag) -> None:
        super().__init__()
        self.rag = rag

    def run(self) -> None:
        try:
            got_question = False
            for delta in self.rag.trigger():
                if not got_question:  # 首个 yield 前问题已提取完毕
                    self.question.emit(getattr(self.rag, "last_question", ""))
                    got_question = True
                if delta:
                    self.chunk.emit(delta)
            if not got_question:
                self.question.emit("")
            if got_question and getattr(self.rag, "last_had_refs", True) is False:
                self.notice.emit("通用回答（知识库无命中）")
            self.done.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
