# interview-assistant.spec —— v4：sherpa-onnx 语音层 + Qt 原生 retro terminal UI
from PyInstaller.utils.hooks import collect_dynamic_libs

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=collect_dynamic_libs("sqlite_vec") + collect_dynamic_libs("sherpa_onnx"),
    datas=[("assets", "assets")],
    hiddenimports=[
        "sherpa_onnx", "sqlite_vec", "pyaudiowpatch", "keyboard",
        "tokenizers", "onnxruntime",
    ],
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
