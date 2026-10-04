# core/vad.py —— Silero 神经 VAD 工厂：模型在则用神经 VAD，否则 None（退回 RMS 门控）。
from pathlib import Path


def make_silero_vad(models_dir: Path, threshold: float = 0.5,
                    min_silence_duration: float = 0.5):
    p = Path(models_dir) / "asr" / "silero_vad.onnx"
    if not p.exists():
        return None
    try:
        import sherpa_onnx
        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = str(p)
        cfg.silero_vad.threshold = threshold
        cfg.silero_vad.min_silence_duration = min_silence_duration
        cfg.sample_rate = 16000
        return sherpa_onnx.Vad(cfg, buffer_size_in_seconds=120)
    except Exception:
        return None
