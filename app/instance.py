# app/instance.py —— 单实例锁：两个实例同时自动下载同一目录会互相破坏（竞态/半包）。
from PySide6.QtCore import QLockFile

_lock: QLockFile | None = None


def acquire_single_instance(data_dir) -> bool:
    global _lock
    if _lock is not None:
        return _lock.isLocked() and _lock.tryLock(0)
    _lock = QLockFile(str(data_dir / "app.lock"))
    return _lock.tryLock(0)


def release_single_instance() -> None:
    global _lock
    if _lock is not None:
        _lock.unlock()
        _lock = None
