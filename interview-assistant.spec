# interview-assistant.spec
# -*- mode: python ; coding: utf-8 -*-
# 打包缺陷修复（Bug 1 根因）：funasr 运行时按模型 config 动态 import 子模块，
# 只靠静态分析会漏掉 funasr.models/* 等 —— 必须显式 collect_submodules；
# modelscope 元数据/数据文件缺失会在冻结环境下 import 失败 —— collect_data_files + copy_metadata。
from PyInstaller.utils.hooks import (collect_dynamic_libs, collect_submodules,
                                     collect_data_files, copy_metadata)

# funasr/register.py 对每个注册类 inspect.getsourcelines —— 冻结环境无源码即抛
# OSError("could not get source code")。把 .py 一并打进 _internal/funasr/（与模块
# __file__ 一致），inspect 即可读到。
datas = [("assets", "assets")] \
    + collect_data_files("modelscope") \
    + collect_data_files("funasr") \
    + collect_data_files("funasr", include_py_files=True) \
    + copy_metadata("modelscope") \
    + copy_metadata("funasr") \
    + copy_metadata("huggingface_hub")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=collect_dynamic_libs("sqlite_vec"),  # vec0.dll 是包数据，需显式收集
    datas=datas,
    hiddenimports=[
        "funasr", "funasr.auto", "sqlite_vec",
        "sentence_transformers", "pyaudiowpatch",
        "keyboard", "torch", "transformers",
    ] + collect_submodules("funasr") + collect_submodules("modelscope"),
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
