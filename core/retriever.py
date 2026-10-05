# core/retriever.py
from dataclasses import dataclass

from core.embedder import Embedder
from core.kb import KnowledgeBase


@dataclass
class Retrieved:
    chunk_id: int
    text: str
    heading_path: str
    source_file: str
    score: float


def rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[int]:
    """Reciprocal Rank Fusion：两路排名 → 融合排序（spec §6.2）。"""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return [cid for cid, _ in sorted(scores.items(), key=lambda x: (-x[1], x[0]))]


class Retriever:
    def __init__(self, kb: KnowledgeBase, embedder: Embedder) -> None:
        self.kb = kb
        self.embedder = embedder
        self.last_top_distance: float | None = None

    @property
    def distances_reliable(self) -> bool:
        from core.embedder import OnnxEmbedder
        return isinstance(self.embedder, OnnxEmbedder)

    def retrieve(self, query: str, k: int = 5) -> list[Retrieved]:
        query = query.strip()
        self.last_top_distance = None
        self.space_mismatch = self.kb.space_mismatch(self.embedder)
        if not query:
            return []
        # 空间不匹配（库由不同嵌入模型构建）：向量路必须弃用，只信 FTS
        vec_hits = [] if self.space_mismatch else self.kb.vector_search(
            self.embedder.encode_query(query), k=k)
        if vec_hits:
            self.last_top_distance = min(d for _, d in vec_hits)
        rankings = [
            [cid for cid, _ in vec_hits],
            self.kb.fts_search(query, k=k),
        ]
        fused = rrf_fuse([r for r in rankings if r], k=60)[:k]
        rows = {r[0]: r for r in self.kb.get_chunks(fused)}
        order = {cid: i for i, cid in enumerate(fused)}
        out = []
        for cid in sorted(fused, key=order.get):
            rid, text, heading, source = rows[cid]
            out.append(Retrieved(cid, text, heading, source, score=-order.get(cid, 999)))
        return out
