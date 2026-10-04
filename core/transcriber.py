# core/transcriber.py
import re
from pathlib import Path
from typing import Protocol

import numpy as np


class Transcriber(Protocol):
    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> str: ...


def clean_sensevoice_text(text: str) -> str:
    """剥离 SenseVoice 富标签（<|zh|>、<|NEUTRAL|>、<|laughter|> 等）。"""
    return re.sub(r"<\|[^|]*\|>", "", text).strip()


class FakeTranscriber:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> str:
        return self.text


class FunasrTranscriber:
    """FunASR：SenseVoice-Small + fsmn-vad + ct-punc，全部本地加载（spec §3）。"""

    def __init__(self, models_dir: Path) -> None:
        from core.paths import ascii_model_path, patch_sentencepiece_unicode
        models_dir = ascii_model_path(models_dir)   # C++ 层打不开中文路径
        patch_sentencepiece_unicode()               # 兜底：字节注入绕开路径层
        from funasr import AutoModel
        self.asr = AutoModel(
            model=str(models_dir / "SenseVoiceSmall"),
            vad_model=str(models_dir / "fsmn-vad"),
            punc_model=str(models_dir / "ct-punc"),
            disable_update=True, disable_pbar=True, disable_log=True,
        )

    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> str:
        wav = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        res = self.asr.generate(input=wav, fs=sample_rate, language="zh", use_itn=True)
        text = res[0].get("text", "") if res else ""
        return clean_sensevoice_text(text)
