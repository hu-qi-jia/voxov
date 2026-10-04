# core/paths.py —— Windows 非 ASCII 路径兼容。
# sentencepiece / torch 的 C++ 层用窄字符 ifstream 打开模型文件，
# 路径含中文等非 ASCII 字符时直接 NOT_FOUND（文件明明存在）。
# 双保险：① ASCII 路径 junction 指向真实模型目录；② 给 sentencepiece
# 打补丁——Python 读文件字节后走 LoadFromSerializedProto，绕开 C++ 路径层。
import hashlib
import os
import subprocess
from pathlib import Path


def _ascii_candidates(models_dir: Path) -> list[Path]:
    tag = hashlib.sha1(str(models_dir).encode("utf-8")).hexdigest()[:8]
    out = []
    try:
        out.append(Path(models_dir.anchor) / f"NotesModelsLink_{tag}")   # 同盘根目录
    except (IndexError, ValueError):
        pass
    base = os.environ.get("PUBLIC")
    if base:
        out.append(Path(base) / f"NotesModelsLink_{tag}")
    return out


def ascii_model_path(models_dir: Path) -> Path:
    """models_dir 含非 ASCII 时返回可用的 ASCII 路径（junction）；
    候选位置都建不了时原样返回（由上层报出原始错误）。"""
    s = str(models_dir)
    if s.isascii():
        return models_dir
    for link in _ascii_candidates(models_dir):
        try:
            if os.path.lexists(link):
                os.rmdir(link)      # junction 用 rmdir 移除，不动目标内容
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), s],
                check=True, capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return link
        except (OSError, subprocess.SubprocessError):
            continue
    return models_dir


def patch_sentencepiece_unicode() -> None:
    """SentencePieceProcessor 的 C++ 层打不开非 ASCII 路径：先试原路；
    失败则 Python 读字节后走 LoadFromSerializedProto。
    funasr 调小写 load（类创建时与 Load 独立的别名），两个名字都要包。"""
    try:
        import sentencepiece as spm
    except ImportError:
        return
    spp = spm.SentencePieceProcessor
    if getattr(spp, "_notes_unicode_patch", False):
        return
    try:
        origs = {}
        for name in ("Load", "load"):
            fn = spp.__dict__.get(name)
            if fn is not None:
                origs[name] = fn

        def make(orig):
            def load_any(self, f):
                try:
                    return orig(self, f)
                except Exception:
                    if isinstance(f, (str, os.PathLike)):
                        data = Path(f).read_bytes()
                        return self.LoadFromSerializedProto(data)
                    raise
            return load_any

        for name, fn in origs.items():
            setattr(spp, name, make(fn))
        if not origs:
            return
        spp._notes_unicode_patch = True
    except (AttributeError, TypeError):
        pass
