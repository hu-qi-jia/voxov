# tests/test_live_source.py
import pytest
from core.capture import list_loopback_devices, LiveAudioSource

def test_list_loopback_devices_returns_list():
    devs = list_loopback_devices()
    assert isinstance(devs, list)
    # CI/无音频环境可能为空，本机应有默认设备
    for d in devs:
        assert "name" in d and "index" in d

def test_live_source_first_chunk_format():
    devs = list_loopback_devices()
    if not devs:
        pytest.skip("无 loopback 设备（静音环境）")
    src = LiveAudioSource()
    it = src.chunks()
    chunk = next(it, None)
    src.stop()
    if chunk is None:
        pytest.skip("系统静音，未产生音频块")
    assert len(chunk) % 2 == 0  # int16
    assert src.sample_rate == 16000 and src.channels == 1
