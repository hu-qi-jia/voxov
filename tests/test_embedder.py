# tests/test_embedder.py
import pytest
from core.embedder import HashEmbedder

def test_hash_embedder_deterministic_and_dim():
    e = HashEmbedder(dim=512)
    a, b, _ = e.encode(["Redis 持久化", "Redis 持久化", "不同的文本"])
    assert len(a) == 512 and a == b and a != c if (c := e.encode(["不同的文本"])[0]) else True

def test_hash_embedder_batch_length():
    e = HashEmbedder(dim=64)
    out = e.encode(["一", "二", "三"])
    assert len(out) == 3 and all(len(v) == 64 for v in out)

def test_hash_embedder_empty_input():
    assert HashEmbedder().encode([]) == []

@pytest.mark.model
def test_onnx_embedder_real_model():
    from core.embedder import OnnxEmbedder
    from core.config import default_config
    cfg = default_config()
    model_dir = cfg.models_dir / "embed"
    if not (model_dir / "model.onnx").exists():
        pytest.skip("模型未下载")
    e = OnnxEmbedder(model_dir)
    a, b = e.encode(["Redis 持久化有哪几种方式", "RDB 和 AOF 的区别"])
    assert len(a) == 512
    # 语义相近的中文句子余弦相似度应高于无关句
    c, = e.encode(["今天天气不错"])
    sim_ab = sum(x * y for x, y in zip(a, b))
    sim_ac = sum(x * y for x, y in zip(a, c))
    assert sim_ab > sim_ac
