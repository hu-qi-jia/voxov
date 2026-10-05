# tests/test_shortcuts.py —— 桌面快捷方式：脚本内容、目标阶梯回退、失败路径
import base64
import os

import pytest

from app import shortcuts


def test_build_shortcut_script_contains_paths_and_save():
    s = shortcuts.build_shortcut_script(r"T:\app.exe", r"T:\cwd", r"D:\links\voxov.lnk")
    assert r"T:\app.exe" in s and r"D:\links\voxov.lnk" in s
    assert "WorkingDirectory" in s and "Save()" in s


def test_build_shortcut_script_with_arguments():
    s = shortcuts.build_shortcut_script("pythonw.exe", "root", "x.lnk", arguments="main.py")
    assert "Arguments" in s and "main.py" in s


def _run_ok(cmd):
    class R:
        returncode = 0
        stderr = b""

    return R()


def _run_fail(cmd):
    class R:
        returncode = 1
        stderr = b"boom"

    return R()


def test_create_desktop_shortcut_uses_encoded_command(tmp_path, monkeypatch):
    """脚本经 -EncodedCommand（UTF-16LE base64）执行：零临时文件、零码页风险。"""
    monkeypatch.setattr(shortcuts, "_shortcut_targets", lambda: [str(tmp_path)])
    calls = []
    script_seen = {}

    def fake_runner(cmd):
        calls.append(cmd)
        decoded = base64.b64decode(cmd[-1]).decode("utf-16-le")
        script_seen["decoded"] = decoded
        import re
        open(re.search(r"CreateShortcut\('([^']+)'\)", decoded).group(1),
             "wb").write(b"lnk")                # 模拟 PowerShell 真实落盘
        return _run_ok(cmd)

    lnk = shortcuts.create_desktop_shortcut(runner=fake_runner)
    assert lnk == str(tmp_path / "voxov.lnk")
    assert calls and calls[0][0] == "powershell"
    assert "-EncodedCommand" in calls[0]
    body = script_seen["decoded"]
    assert str(tmp_path / "voxov.lnk") in body
    assert "Save()" in body


def test_shortcut_ladder_falls_back_when_first_target_denied(tmp_path, monkeypatch):
    """注册表桌面不可写（如 D: 根拒绝访问）→ 自动落到下一目标（C: 用户桌面）。"""
    denied = tmp_path / "denied"
    real = tmp_path / "real_desk"
    real.mkdir()
    monkeypatch.setattr(shortcuts, "_shortcut_targets", lambda: [str(denied), str(real)])

    def runner(cmd):
        import re
        decoded = base64.b64decode(cmd[-1]).decode("utf-16-le")
        target = re.search(r"CreateShortcut\('([^']+)'\)", decoded).group(1)
        if target.startswith(str(denied)):
            return _run_fail(cmd)
        open(target, "wb").write(b"lnk")        # 模拟 PowerShell 真实落盘
        return _run_ok(cmd)

    lnk = shortcuts.create_desktop_shortcut(runner=runner)
    assert lnk == str(real / "voxov.lnk")


def test_shortcut_all_targets_fail_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(shortcuts, "_shortcut_targets", lambda: [str(tmp_path)])

    with pytest.raises(RuntimeError, match="尝试过"):
        shortcuts.create_desktop_shortcut(runner=_run_fail)


def test_dev_mode_targets_pythonw_with_main_py(monkeypatch, tmp_path):
    """非冻结环境：快捷方式应指向 pythonw + main.py，而非解释器本身。"""
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "main.py").write_text("x", encoding="utf-8")
    fake_pyw = tmp_path / "pythonw.exe"
    fake_pyw.write_bytes(b"")
    monkeypatch.setattr(shortcuts, "_module_dir", lambda: str(root / "app"))
    real_exists = os.path.exists
    monkeypatch.setattr(shortcuts.os.path, "exists",
                        lambda p: True if str(p) == str(fake_pyw) else real_exists(p))
    monkeypatch.setattr(shortcuts.sys, "executable", str(tmp_path / "python.exe"))
    monkeypatch.setattr(shortcuts, "_shortcut_targets", lambda: [str(tmp_path)])
    captured = {}

    def fake_builder(target, workdir, lnk, arguments=""):
        captured.update(target=target, workdir=workdir, arguments=arguments)
        return "script"

    monkeypatch.setattr(shortcuts, "build_shortcut_script", fake_builder)

    def runner(cmd):
        open(shortcuts._shortcut_targets()[0] + os.sep + "voxov.lnk",
             "wb").write(b"")                   # 模拟落盘
        return _run_ok(cmd)

    shortcuts.create_desktop_shortcut(runner=runner)
    assert captured["target"] == str(fake_pyw)
    assert captured["workdir"] == str(root)
    assert captured["arguments"] == "main.py"


def _run_ok(cmd):
    class R:
        returncode = 0
        stderr = b""

    return R()


def _run_fail(cmd):
    class R:
        returncode = 1
        stderr = b"boom"

    return R()
