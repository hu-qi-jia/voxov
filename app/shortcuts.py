# app/shortcuts.py —— 桌面快捷方式（Windows .lnk，经 PowerShell WScript.Shell，零新依赖）。
# 打包版指向 exe 本体；开发版指向 pythonw + main.py（无控制台窗口）。
import os
import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000


def _module_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _desktop_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Desktop")


def build_shortcut_script(target: str, workdir: str, lnk_path: str,
                          arguments: str = "") -> str:
    esc = lambda s: s.replace("'", "''")  # noqa: E731 —— PowerShell 单引号转义
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$lnk = $ws.CreateShortcut('{esc(lnk_path)}'); "
        f"$lnk.TargetPath = '{esc(target)}'; "
        f"$lnk.WorkingDirectory = '{esc(workdir)}'; "
    )
    if arguments:
        script += f"$lnk.Arguments = '{esc(arguments)}'; "
    script += f"$lnk.IconLocation = '{esc(target)}, 0'; " + "$lnk.Save()"
    return script


def create_desktop_shortcut(runner=None) -> str:
    """创建桌面 voxov.lnk，返回路径。runner 可注入（测试）。失败抛 RuntimeError。"""
    lnk = os.path.join(_desktop_dir(), "voxov.lnk")
    if getattr(sys, "frozen", False):
        target = sys.executable
        workdir = os.path.dirname(target)
        arguments = ""
    else:
        root = os.path.dirname(_module_dir())
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        target = pythonw if os.path.exists(pythonw) else sys.executable
        workdir = root
        arguments = "main.py"
    script = build_shortcut_script(target, workdir, lnk, arguments)
    runner = runner or (lambda cmd: subprocess.run(
        cmd, creationflags=CREATE_NO_WINDOW, capture_output=True))
    result = runner(["powershell", "-NoProfile", "-Command", script])
    if result.returncode != 0:
        err = (result.stderr or b"").decode(errors="ignore")[:200]
        raise RuntimeError(f"快捷方式创建失败：{err}")
    return lnk
