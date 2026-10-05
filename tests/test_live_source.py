# tests/test_live_source.py
import pytest
import threading
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
    result = []

    def grab():
        result.append(next(it, None))

    # 环境完全安静时 chunks() 可能长时间不产出：限时等待，超时按静音跳过
    th = threading.Thread(target=grab, daemon=True)
    th.start()
    th.join(timeout=10)
    src.stop()
    if not result or result[0] is None:
        pytest.skip("10s 内无音频块（环境安静）")
    chunk = result[0]
    assert len(chunk) % 2 == 0  # int16
    assert src.sample_rate == 16000 and src.channels == 1
