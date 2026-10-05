# app/shortcuts.py —— 桌面快捷方式（Windows .lnk，经 PowerShell WScript.Shell，零新依赖）。
# 打包版指向 exe 本体；开发版指向 pythonw + main.py（无控制台窗口）。
import os
import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000


def _module_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _desktop_dir() -> str:
    """注册表 Shell Folders 的桌面（OneDrive/换盘重定向也正确）。
    注意 join 陷阱：注册表值可能为 'D:'，必须补分隔符否则得到 'D:voxov.lnk'。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion"
                            r"\Explorer\User Shell Folders") as k:
            v, _ = winreg.QueryValueEx(k, "Desktop")
        desk = os.path.normpath(os.path.expandvars(v))
        return desk if desk.endswith(("\\", "/")) else desk + os.sep
    except Exception:
        return os.path.join(os.path.expanduser("~"), "Desktop")


def _shortcut_targets() -> list[str]:
    """创建目标阶梯：注册表桌面 → C: 用户桌面 → 开始菜单程序组（APPDATA 必可写）。"""
    out = [_desktop_dir(),
           os.path.join(os.path.expanduser("~"), "Desktop"),
           os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                        "Microsoft", "Windows", "Start Menu", "Programs")]
    seen, uniq = set(), []
    for p in out:
        if p and p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


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
    """创建桌面 voxov.lnk，返回实际落盘路径。runner 可注入（测试）。
    目标阶梯：注册表桌面 → C: 用户桌面 → 开始菜单；以「文件确实存在」为成功
    判据（曾出现 rc=0 但 COM 静默失败的场景——D 盘根不可写）。"""
    import base64
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
    runner = runner or (lambda cmd: subprocess.run(
        cmd, creationflags=CREATE_NO_WINDOW, capture_output=True))
    errs: list[str] = []
    for desk in _shortcut_targets():
        lnk = os.path.join(desk, "voxov.lnk")
        script = build_shortcut_script(target, workdir, lnk, arguments)
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        result = runner(["powershell", "-NoProfile", "-EncodedCommand", encoded])
        if result.returncode == 0 and os.path.exists(lnk):
            return lnk
        errs.append(lnk)
    raise RuntimeError("快捷方式创建失败，尝试过：" + " → ".join(errs))
