# tests/test_shortcuts.py —— 桌面快捷方式：脚本内容与创建失败路径
import os

import pytest


def test_build_shortcut_script_contains_paths_and_save():
    from app.shortcuts import build_shortcut_script
    s = build_shortcut_script(r"T:\app.exe", r"T:\cwd", r"D:\links\voxov.lnk")
    assert r"T:\app.exe" in s and r"D:\links\voxov.lnk" in s
    assert "WorkingDirectory" in s and "Save()" in s


def test_build_shortcut_script_with_arguments():
    from app.shortcuts import build_shortcut_script
    s = build_shortcut_script("pythonw.exe", "root", "x.lnk", arguments="main.py")
    assert "Arguments" in s and "main.py" in s


def test_create_desktop_shortcut_uses_runner(tmp_path, monkeypatch):
    from app import shortcuts
    monkeypatch.setattr(shortcuts, "_desktop_dir", lambda: str(tmp_path))
    calls = []
    ps1_content = {}

    def fake_runner(cmd):
        calls.append(cmd)
        with open(cmd[-1], "rb") as f:        # ps1 在 finally 里会被删，运行中取内容
            ps1_content["head"] = f.read(3)
            ps1_content["body"] = f.read().decode("utf-8-sig")

        class R:
            returncode = 0
            stderr = b""

        return R()

    lnk = shortcuts.create_desktop_shortcut(runner=fake_runner)
    assert lnk == str(tmp_path / "voxov.lnk")
    assert calls and calls[0][0] == "powershell"
    assert "-File" in calls[0]
    # 脚本走 UTF-8 BOM 临时 .ps1（中文用户名路径经 -Command 会乱码）
    assert ps1_content["head"] == b"\xef\xbb\xbf"            # BOM
    assert str(tmp_path / "voxov.lnk") in ps1_content["body"]
    assert not os.path.exists(calls[0][-1])                   # 用后即清


def test_create_desktop_shortcut_failure_raises(tmp_path, monkeypatch):
    from app import shortcuts
    monkeypatch.setattr(shortcuts, "_desktop_dir", lambda: str(tmp_path))

    def bad(cmd):
        class R:
            returncode = 1
            stderr = b"boom"

        return R()

    with pytest.raises(RuntimeError, match="boom"):
        shortcuts.create_desktop_shortcut(runner=bad)


def test_dev_mode_targets_pythonw_with_main_py(monkeypatch, tmp_path):
    """非冻结环境：快捷方式应指向 pythonw + main.py，而非解释器本身。"""
    from app import shortcuts
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "main.py").write_text("x", encoding="utf-8")
    monkeypatch.setattr(shortcuts, "_module_dir", lambda: str(root / "app"))
    fake_pyw = tmp_path / "pythonw.exe"
    fake_pyw.write_bytes(b"")
    monkeypatch.setattr(shortcuts.os.path, "exists",
                        lambda p: str(p) == str(fake_pyw))
    monkeypatch.setattr(shortcuts.sys, "executable", str(tmp_path / "python.exe"))
    captured = {}

    def fake_builder(target, workdir, lnk, arguments=""):
        captured.update(target=target, workdir=workdir, arguments=arguments)
        return "script"

    monkeypatch.setattr(shortcuts, "build_shortcut_script", fake_builder)

    class R:
        returncode = 0
        stderr = b""

    shortcuts.create_desktop_shortcut(runner=lambda cmd: R())
    assert captured["target"] == str(fake_pyw)
    assert captured["workdir"] == str(root)
    assert captured["arguments"] == "main.py"
