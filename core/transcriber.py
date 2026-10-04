# core/transcriber.py —— 语音转文字：sherpa-onnx SenseVoice（ONNX，无 torch/funasr）。
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


class SherpaTranscriber:
    """sherpa-onnx 离线识别：asr/model.int8.onnx + tokens.txt，CPU 实时，中文优先。"""

    def __init__(self, models_dir: Path) -> None:
        import sherpa_onnx
        asr_dir = Path(models_dir) / "asr"
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(asr_dir / "model.int8.onnx"),
            tokens=str(asr_dir / "tokens.txt"),
            num_threads=2,
            use_itn=True,
        )

    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> str:
        samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        stream = self._recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        self._recognizer.decode_streams([stream])
        return clean_sensevoice_text(stream.result.text)
