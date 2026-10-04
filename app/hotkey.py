# app/hotkey.py
from PySide6.QtCore import QObject, Signal


class HotkeyBridge(QObject):
    """keyboard 库的回调跑在独立线程；经 Qt 信号（队列连接） marshal 到主线程。
    pressed = 触发生成；hidden = 急隐藏切换（spec §6.5）。"""
    pressed = Signal()
    hidden = Signal()

    def __init__(self, combo: str = "ctrl+alt+space",
                 hide_combo: str = "ctrl+alt+h") -> None:
        super().__init__()
        import keyboard
        keyboard.add_hotkey(combo, self.pressed.emit)
        keyboard.add_hotkey(hide_combo, self.hidden.emit)

    def stop(self) -> None:
        import keyboard
        keyboard.unhook_all()
