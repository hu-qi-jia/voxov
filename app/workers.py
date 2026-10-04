# app/workers.py —— 后台生成 worker。所有 UI 更新经信号（队列连接）回主线程，
# worker 线程内绝不直接碰 QWidget。
from PySide6.QtCore import QThread, Signal


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
