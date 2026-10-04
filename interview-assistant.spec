# interview-assistant.spec —— v3：sherpa-onnx 语音层 + qfluentwidgets UI
from PyInstaller.utils.hooks import (collect_dynamic_libs, collect_data_files,
                                     collect_submodules)

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=collect_dynamic_libs("sqlite_vec") + collect_dynamic_libs("sherpa_onnx"),
    datas=[("assets", "assets")] \
        + collect_data_files("qfluentwidgets"),   # qss/字体/图标资源
    hiddenimports=[
        "sherpa_onnx", "sqlite_vec", "pyaudiowpatch", "keyboard",
        "tokenizers", "onnxruntime",
    ] + collect_submodules("qfluentwidgets"),
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "torch", "transformers", "scipy",
              "llvmlite", "numba", "librosa", "sentence_transformers",
              "funasr", "modelscope", "sentencepiece"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name="notes-viewer", debug=False,   # 对外中性名（spec §6.5）
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name="notes-viewer")
