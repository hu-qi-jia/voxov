# interview-assistant.spec
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_dynamic_libs

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=collect_dynamic_libs("sqlite_vec"),  # vec0.dll 是包数据，需显式收集
    datas=[("assets", "assets")],
    hiddenimports=[
        "funasr", "funasr.auto", "sqlite_vec",
        "sentence_transformers", "pyaudiowpatch",
        "keyboard", "torch", "transformers",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name="notes-viewer", debug=False,   # 对外中性名（spec §6.5）
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
              name="notes-viewer")
