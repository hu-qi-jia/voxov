# core/downloader.py
import os
from pathlib import Path
from typing import Callable

MS_REPOS = {
    "SenseVoiceSmall": "iic/SenseVoiceSmall",
    "fsmn-vad": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    "ct-punc": "iic/punc_ct-transformer_cn-en-common-vocab471067-large",
}
HF_REPOS = {"bge-small-zh-v1.5": "BAAI/bge-small-zh-v1.5"}


def models_ready(models_dir: Path) -> bool:
    return all((models_dir / name).exists() for name in [*MS_REPOS, *HF_REPOS])


def _download_modelscope(repo: str, dest: Path, log: Callable[[str], None]) -> None:
    # 缓存与 SDK 配置目录一并重定位到应用 models/_cache：用户主目录常被安全软件
    # （受控文件夹访问）拦下 WinError 5 → modelscope_hub ensure_dirs 抛 E1022。
    # E1022 拦的是 MODELSCOPE_HOME（~/.modelscope 配置目录），不是 MODELSCOPE_CACHE。
    # setdefault 必须在 import 前——SDK 在 import 期就 ensure_dirs。
    os.environ.setdefault("MODELSCOPE_CACHE", str(dest.parent / "_cache" / "modelscope"))
    os.environ.setdefault("MODELSCOPE_HOME", str(dest.parent / "_cache" / "modelscope_home"))
    log("[初始化] 加载下载组件（首次较慢，约 1–2 分钟）…")
    from modelscope import snapshot_download
    log("[初始化] 下载组件就绪")
    snapshot_download(repo, local_dir=str(dest))


def _download_hf(repo: str, dest: Path, log: Callable[[str], None]) -> None:
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HOME", str(dest.parent / "_cache" / "huggingface"))
    from huggingface_hub import snapshot_download
    snapshot_download(repo, local_dir=str(dest))


def ensure_models(models_dir: Path, log: Callable[[str], None]) -> None:
    """逐项下载缺失模型；已存在跳过；snapshot 自带断点续传。"""
    models_dir.mkdir(parents=True, exist_ok=True)
    for name, repo in {**MS_REPOS, **HF_REPOS}.items():
        dest = models_dir / name
        if dest.exists():
            log(f"[跳过] {name} 已存在")
            continue
        log(f"[开始下载] {repo} → {dest}")
        fn = _download_modelscope if name in MS_REPOS else _download_hf
        fn(repo, dest, log)
        log(f"[完成] {name}")
