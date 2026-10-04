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
    from modelscope import snapshot_download
    snapshot_download(repo, local_dir=str(dest))


def _download_hf(repo: str, dest: Path, log: Callable[[str], None]) -> None:
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
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
