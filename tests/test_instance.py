# tests/test_instance.py —— 单实例：残留锁清除 + 唤起通道
import subprocess
import sys

from PySide6.QtCore import QLockFile


def _hold_lock_process(lock_path):
    """独立进程持锁（模拟另一实例）。返回 (proc, script_path)。"""
    script = lock_path.parent / "_holder.py"
    script.write_text(
        "import sys, time\n"
        "from PySide6.QtCore import QLockFile\n"
        f"lk = QLockFile(r'{lock_path}')\n"
        "lk.lock()\n"
        "print('locked', flush=True)\n"
        "time.sleep(30)\n",
        encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(script)],
                            creationflags=subprocess.CREATE_NO_WINDOW,
                            stdout=subprocess.PIPE)
    return proc, script


def test_stale_lock_is_cleared_and_acquired(tmp_path):
    """进程被 kill 后残留的锁：先失败→清残留→再成功。"""
    from app.instance import acquire_single_instance, release_single_instance
    lock_path = tmp_path / "app.lock"
    held, script = _hold_lock_process(lock_path)
    try:
        held.stdout.readline()           # 等外部进程真实持锁
        probe = QLockFile(str(lock_path))
        assert probe.tryLock(0) is False  # 确认锁被他人持有
        held.kill()                       # 模拟崩溃：持锁进程死亡
        held.wait(timeout=5)
        assert acquire_single_instance(tmp_path) is True   # 残留锁被清、获锁成功
        release_single_instance()
    finally:
        if held.poll() is None:
            held.kill()
        script.unlink(missing_ok=True)


def test_try_summon_returns_false_without_server():
    from app.instance import try_summon_running_instance
    assert try_summon_running_instance("voxov-summon-test-absent") is False


def test_summon_server_receives_notification(qtbot):
    from app.instance import start_summon_server, try_summon_running_instance
    got = []
    srv = start_summon_server("voxov-summon-test", lambda: got.append(1))
    try:
        assert try_summon_running_instance("voxov-summon-test") is True
        qtbot.waitUntil(lambda: got == [1], timeout=2000)
    finally:
        srv.close()
