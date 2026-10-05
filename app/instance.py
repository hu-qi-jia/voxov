# app/instance.py —— 单实例锁 + 唤起通道。
# 第二次启动不再死路提示：经 QLocalSocket 唤起首实例（reveal 急隐藏态），自己静默退出；
# 崩溃残留锁由 removeStaleLockFile 清除后重试。
from PySide6.QtCore import QLockFile
from PySide6.QtNetwork import QLocalServer, QLocalSocket

SUMMON_SERVER_NAME = "voxov-summon"

_lock: QLockFile | None = None
_server: QLocalServer | None = None


def acquire_single_instance(data_dir) -> bool:
    global _lock
    if _lock is not None:
        return _lock.isLocked() and _lock.tryLock(0)
    _lock = QLockFile(str(data_dir / "app.lock"))
    if _lock.tryLock(0):
        return True
    _lock.removeStaleLockFile()   # 持锁进程已死的残留锁：清除后重试一次
    return _lock.tryLock(0)


def try_summon_running_instance(name: str = SUMMON_SERVER_NAME) -> bool:
    """唤起已在运行的首实例（reveal）。无首实例返回 False。"""
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(300):
        return False
    sock.write(b"show\n")
    sock.flush()
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    return True


def start_summon_server(name: str, on_summon) -> QLocalServer:
    """首实例监听唤起通道；收到连接即回调 on_summon。"""
    global _server
    QLocalServer.removeServer(name)   # 清崩溃残留的命名管道
    srv = QLocalServer()
    srv.listen(name)

    def _on_conn() -> None:
        conn = srv.nextPendingConnection()
        if conn is not None:
            conn.readAll()
            conn.disconnectFromServer()
        on_summon()

    srv.newConnection.connect(_on_conn)
    _server = srv
    return srv


def release_single_instance() -> None:
    global _lock, _server
    if _server is not None:
        _server.close()
        _server = None
    if _lock is not None:
        _lock.unlock()
        _lock = None
