# core/downloader.py —— 模型获取 v2：纯 HTTP 单文件下载，无任何 SDK。
# 语音识别：sherpa-onnx 官方 SenseVoice int8 onnx（GitHub Releases，约 250MB）
# 向量模型：bge-small-zh-v1.5 onnx + tokenizer（hf-mirror，约 25MB）
# 下载到 .part 临时文件，完成后原子改名——models_ready 只认最终文件名。
import shutil
import tarfile
import urllib.request
from pathlib import Path
from typing import Callable

ASR_URLS = [
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2",
    "https://ghproxy.cn/https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2",
]
ASR_FILES = ("model.int8.onnx", "tokens.txt")
EMBED_URLS = [
    "https://hf-mirror.com/Xenova/bge-small-zh-v1.5/resolve/main/onnx/model.onnx",
    "https://huggingface.co/Xenova/bge-small-zh-v1.5/resolve/main/onnx/model.onnx",
]
TOKENIZER_URLS = [
    "https://hf-mirror.com/Xenova/bge-small-zh-v1.5/resolve/main/tokenizer.json",
    "https://huggingface.co/Xenova/bge-small-zh-v1.5/resolve/main/tokenizer.json",
]

REQUIRED = ("asr/model.int8.onnx", "asr/tokens.txt",
            "embed/model.onnx", "embed/tokenizer.json")


def models_ready(models_dir: Path) -> bool:
    """就绪 = 四个最终文件齐全（.part 临时文件不算数）。"""
    return all((models_dir / rel).exists() for rel in REQUIRED)


def _fetch_to(urls: list[str], dest: Path, progress: Callable[[float], None] | None = None) -> None:
    """依次尝试镜像下载到 dest.part，成功后原子改名。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last_err: Exception | None = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "notes-viewer/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                with open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if progress and total:
                            progress(min(1.0, done / total))
            if total and tmp.stat().st_size != total:
                raise IOError(f"下载不完整：{tmp.stat().st_size}/{total}")
            shutil.move(str(tmp), str(dest))
            return
        except Exception as exc:  # 换下一个镜像
            last_err = exc
            if tmp.exists():
                tmp.unlink()
    raise RuntimeError(f"下载失败（已尝试 {len(urls)} 个源）：{last_err}")


def ensure_models(models_dir: Path, log: Callable[[str], None],
                  progress: Callable[[float], None] | None = None,
                  fetch: Callable | None = None) -> None:
    """缺失则下载；已齐全直接跳过。fetch 可注入用于测试（同 _fetch_to 签名）。"""
    fetch = fetch or _fetch_to
    models_dir.mkdir(parents=True, exist_ok=True)
    asr_dir = models_dir / "asr"
    emb_dir = models_dir / "embed"

    if not all((asr_dir / f).exists() for f in ASR_FILES):
        log("[下载] 语音识别模型（约 250MB，一次即可）…")
        arch = models_dir / "asr_archive.tar.bz2"
        fetch(ASR_URLS, arch, progress)
        log("[解压] 语音识别模型…")
        asr_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(arch, "r:bz2") as t:
            for m in t.getmembers():
                if Path(m.name).name in ASR_FILES and m.isfile():
                    src = t.extractfile(m)
                    (asr_dir / Path(m.name).name).write_bytes(src.read())
        arch.unlink()

    if not (emb_dir / "model.onnx").exists():
        log("[下载] 向量模型（约 25MB）…")
        fetch(EMBED_URLS, emb_dir / "model.onnx", progress)

    if not (emb_dir / "tokenizer.json").exists():
        log("[下载] 分词器…")
        fetch(TOKENIZER_URLS, emb_dir / "tokenizer.json", progress)

    log("[完成] 全部模型就绪")
