# tests/test_transcriber.py
import numpy as np
import pytest
from core.transcriber import FakeTranscriber, clean_sensevoice_text

def test_clean_strips_rich_tags():
    raw = "<|zh|><|NEUTRAL|>今天天气<|laughter|>不错<|/laughter|>。"
    assert clean_sensevoice_text(raw) == "今天天气不错。"

def test_clean_plain_text_untouched():
    assert clean_sensevoice_text("普通句子。") == "普通句子。"

def test_fake_transcriber_returns_fixed():
    t = FakeTranscriber("你好")
    assert t.transcribe(b"\x00\x00" * 1600) == "你好"

@pytest.mark.model
def test_sherpa_real_model_chinese(real_app_root):
    from core.config import default_config
    from core.transcriber import SherpaTranscriber
    cfg = default_config()
    if not (cfg.models_dir / "asr" / "model.int8.onnx").exists():
        pytest.skip("模型未下载")
    t = SherpaTranscriber(cfg.models_dir)
    # 1 秒 440Hz 正弦（主要验证链路不崩、返回字符串）
    pcm = (np.sin(2 * np.pi * 440 * np.arange(16000) / 16000) * 8000).astype(np.int16)
    out = t.transcribe(pcm.tobytes())
    assert isinstance(out, str)
