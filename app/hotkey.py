# app/hotkey.py
from PySide6.QtCore import QObject, Signal


class HotkeyBridge(QObject):
    """keyboard 库的回调跑在独立线程；经 Qt 信号（队列连接） marshal 到主线程。
    pressed = 触发生成；hidden = 急隐藏切换（spec §6.5）。
    errors = 单键注册失败清单（如权限不足/组合无法解析），供 UI 可见化。"""
    pressed = Signal()
    hidden = Signal()

    def __init__(self, combo: str = "ctrl+alt+space",
                 hide_combo: str = "ctrl+alt+h") -> None:
        super().__init__()
        self.errors: list[str] = []
        import keyboard
        for key, cb, label in ((combo, self.pressed.emit, "触发"),
                               (hide_combo, self.hidden.emit, "急隐藏")):
            try:
                keyboard.add_hotkey(key, cb)
            except Exception as exc:
                self.errors.append(f"{label} {key}：{exc}")

    def stop(self) -> None:
        import keyboard
        keyboard.unhook_all()
