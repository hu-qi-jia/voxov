# tests/test_vad_pipeline.py —— Silero VAD 门控 + 检索前缀 + 生成中断语义
import numpy as np
import pytest


class _Src:
    sample_rate = 16000
    channels = 1

    def __init__(self, blocks):
        self._blocks = blocks

    def chunks(self):
        yield from self._blocks

    def stop(self):
        pass


class FakeVad:
    """假 Silero：攒够 3 块就吐一个段（模拟神经 VAD 的整段输出）。"""

    def __init__(self):
        self._buf = []
        self.flushed = False

    def accept_waveform(self, samples):
        self._buf.extend(samples.tolist())

    def empty(self):
        return self.flushed or len(self._buf) < 8000   # 攒够 0.5s 再出段

    @property
    def front(self):
        class _Seg:
            samples = np.array(self._buf, dtype=np.float32)

        return _Seg()

    def pop(self):
        self.flushed = True

    def flush(self):
        self.flushed = True


def test_vad_pipeline_transcribes_neural_segments(tmp_path):
    from core.pipeline import AudioPipeline
    from core.session import SessionBuffer
    from core.transcriber import FakeTranscriber

    blocks = [np.full(1600, 500, dtype=np.int16).tobytes() for _ in range(8)]
    buf = SessionBuffer()
    p = AudioPipeline(_Src(blocks), FakeTranscriber("神经VAD出的句子"), buf,
                      vad=FakeVad())
    p.start().join(timeout=15)
    assert len(buf.entries) == 1 and buf.entries[0].text == "神经VAD出的句子"


def test_vad_failure_falls_back_to_rms(tmp_path):
    from core.pipeline import AudioPipeline
    from core.session import SessionBuffer
    from core.transcriber import FakeTranscriber

    class BoomVad:
        def accept_waveform(self, samples):
            raise RuntimeError("vad crashed")

    blocks = [np.full(1600, 5000, dtype=np.int16).tobytes() for _ in range(6)]
    buf = SessionBuffer()
    p = AudioPipeline(_Src(blocks), FakeTranscriber("回退路径"), buf, vad=BoomVad())
    p.start().join(timeout=15)
    assert len(buf.entries) >= 1      # VAD 挂了 → 退回 RMS 门控，链路不断


def test_vad_factory_returns_none_without_model(tmp_path):
    from core.vad import make_silero_vad
    assert make_silero_vad(tmp_path) is None


# --- 检索：bge 查询侧指令前缀 ---
def test_onnx_embedder_query_prefix():
    from core.embedder import OnnxEmbedder
    e = OnnxEmbedder.__new__(OnnxEmbedder)   # 跳过模型加载，只验前缀逻辑
    e.encode = lambda texts: [texts[0]]
    out = e.encode_query("Redis 持久化")
    assert out.startswith("为这个句子生成表示以用于检索相关文章：")
    assert out.endswith("Redis 持久化")


# --- 生成中断：流中途失败不重发（防重复），已收部分保留 ---
def test_mid_stream_failure_raises_no_retry(monkeypatch):
    import httpx
    from core.generator import LLMClient, LLMError

    n = {"req": 0}

    def body_gen():
        yield b'data: {"choices": [{"delta": {"content": "Part 1"}}]}\n\n'
        raise httpx.ReadError("connection lost")

    def handler(req):
        n["req"] += 1
        return httpx.Response(200, content=body_gen())

    transport = httpx.MockTransport(handler)
    c = LLMClient("https://api.example.com/v1", "sk", "m")
    c._transport = transport
    outs = []
    with pytest.raises(LLMError, match="生成中断"):
        for d in c.stream([{"role": "user", "content": "x"}]):
            outs.append(d)
    assert outs == ["Part 1"]
    assert n["req"] == 1                    # 已吐字后失败：不整发重试


def test_connect_failure_still_retries_once():
    import httpx
    from core.generator import LLMClient, LLMError

    n = {"req": 0}

    def handler(req):
        n["req"] += 1
        raise httpx.ConnectError("refused")

    c = LLMClient("https://api.example.com/v1", "sk", "m")
    c._transport = httpx.MockTransport(handler)
    with pytest.raises(LLMError, match="已重试 1 次"):
        list(c.stream([{"role": "user", "content": "x"}]))
    assert n["req"] == 2
