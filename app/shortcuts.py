# app/shortcuts.py —— 桌面快捷方式（Windows .lnk，经 PowerShell WScript.Shell，零新依赖）。
# 打包版指向 exe 本体；开发版指向 pythonw + main.py（无控制台窗口）。
import os
import subprocess
import sys
import tempfile

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
    """创建桌面 voxov.lnk，返回路径。runner 可注入（测试）。失败抛 RuntimeError。
    脚本经 UTF-8 BOM 的临时 .ps1 + -File 执行：中文用户名/路径走 -Command 会被
    PowerShell 按本地码页解码成乱码（实测）。"""
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
    ps1 = os.path.join(tempfile.gettempdir(), "voxov_shortcut.ps1")
    with open(ps1, "w", encoding="utf-8-sig") as f:
        f.write(script)
    try:
        runner = runner or (lambda cmd: subprocess.run(
            cmd, creationflags=CREATE_NO_WINDOW, capture_output=True))
        result = runner(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                         "-File", ps1])
        if result.returncode != 0:
            err = (result.stderr or b"").decode(errors="ignore")[:200]
            raise RuntimeError(f"快捷方式创建失败：{err}")
    finally:
        try:
            os.unlink(ps1)
        except OSError:
            pass
    return lnk
