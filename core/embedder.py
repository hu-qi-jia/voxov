# core/embedder.py
import hashlib
from pathlib import Path
from typing import Protocol


class Embedder(Protocol):
    dim: int

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """确定性哈希向量：不依赖模型，供单元测试与小规模开发调试。"""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            vec = []
            for i in range(self.dim):
                vec.append((h[i % len(h)] / 255.0) * 2 - 1)
            out.append(vec)
        return out


class BgeEmbedder:
    """BAAI/bge-small-zh-v1.5，本地加载，dim=512。"""

    def __init__(self, model_dir: Path) -> None:
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(str(model_dir))
        self.dim = 512

    def encode(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vecs]
