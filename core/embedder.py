# core/embedder.py —— 向量化：ONNX bge-small-zh（onnxruntime + tokenizers，无 torch）。
import hashlib
from pathlib import Path
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    dim: int

    def encode(self, texts: list[str]) -> list[list[float]]: ...

    def encode_query(self, query: str) -> list[float]:
        return self.encode([query])[0]


class HashEmbedder:
    """确定性哈希向量：不依赖模型，供单元测试与小规模开发调试。"""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim
        self.id = f"hash-sha256:{dim}"      # 嵌入空间指纹：入库/查询必须同空间

    def encode_query(self, query: str) -> list[float]:
        return self.encode([query])[0]

    def encode(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            vec = []
            for i in range(self.dim):
                vec.append((h[i % len(h)] / 255.0) * 2 - 1)
            out.append(vec)
        return out


class OnnxEmbedder:
    """BAAI/bge-small-zh-v1.5 的 ONNX 导出，mean pooling + L2 归一化，dim=512。
    查询侧加 bge 官方指令前缀（参考 VoxRecall：检索 query 必须带前缀）。"""

    QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

    def encode_query(self, query: str) -> list[float]:
        return self.encode([self.QUERY_PREFIX + query])[0]

    def __init__(self, model_dir: Path) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer
        model_dir = Path(model_dir)
        self._tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self._tok.enable_truncation(max_length=512)
        self._tok.enable_padding()          # 批内对齐长度，attention_mask 随之填充
        self._sess = ort.InferenceSession(
            str(model_dir / "model.onnx"), providers=["CPUExecutionProvider"])
        self.dim = 512
        self.id = "onnx:bge-small-zh-v1.5:512"

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        encs = self._tok.encode_batch(texts)
        ids = np.array([e.ids for e in encs], dtype="int64")
        mask = np.array([e.attention_mask for e in encs], dtype="int64")
        hidden = self._sess.run(None, {
            "input_ids": ids,
            "attention_mask": mask,
            "token_type_ids": np.zeros_like(ids),
        })[0]                                          # (B, T, H)
        m = mask.astype("float32")[:, :, None]
        mean = (hidden * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
        norm = np.linalg.norm(mean, axis=1, keepdims=True)
        return (mean / np.clip(norm, 1e-12, None)).tolist()
