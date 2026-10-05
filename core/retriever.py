# core/retriever.py
from dataclasses import dataclass

from core.embedder import Embedder
from core.kb import KnowledgeBase, merge_section_texts


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
        self.last_distances: dict[int, float] = {}
        self.space_mismatch = self.kb.space_mismatch(self.embedder)
        if not query:
            return []
        # 空间不匹配（库由不同嵌入模型构建）：向量路必须弃用，只信 FTS
        vec_hits = [] if self.space_mismatch else self.kb.vector_search(
            self.embedder.encode_query(query), k=k)
        if vec_hits:
            self.last_distances = {cid: d for cid, d in vec_hits}
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

    # ---- 检索主路：只检索问题（参考 personal-ai-memory「正文不向量化」） ----
    def match_sections(self, query: str, limit: int = 2) -> list[tuple[str, str, float]]:
        """问题向量匹配（主）+ 标题滑窗直配（辅）：并集去重，标题精确同名优先，
        再按问题向量得分降序。返回 [(source_file, heading_path, score)]。"""
        hits: dict[tuple[str, str], tuple[int, float]] = {}
        for sf, hp, score in self.kb.match_sections_by_vec(query, limit=limit):
            hits[(sf, hp)] = (1, score)
        for sf, hp in self.kb.match_sections(query, limit=limit):
            hits.setdefault((sf, hp), (0, 1.0))
        ordered = sorted(hits.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0][1]))
        return [(sf, hp, score) for (sf, hp), (_, score) in ordered[:limit]]

    def section_materials(self, hits: list) -> list[Retrieved]:
        """命中节 → 整节材料：子节全带、顺读拼接、拼缝去 50 字重叠、补回 #### 子标题。"""
        out = []
        for hit in hits:
            sf, hp = hit[0], hit[1]
            score = hit[2] if len(hit) > 2 else 0.0
            rows = self.kb.section_chunks(sf, hp)
            if not rows:
                continue
            text = merge_section_texts([(r[1], r[2]) for r in rows])
            out.append(Retrieved(rows[0][0], text, hp, sf, score=score))
        return out

    def expand_to_sections(self, contexts: list[Retrieved]) -> list[Retrieved]:
        """兜底路（正文向量/FTS）命中块 → 扩成所属问题节：只给半句话等于没给答案。"""
        out: list[Retrieved] = []
        seen: set[tuple[str, str]] = set()
        for c in contexts:
            sec = self.kb.chunk_section(c.chunk_id) or c.heading_path
            key = (c.source_file, sec)
            if key in seen:
                continue
            seen.add(key)
            rows = self.kb.section_chunks(c.source_file, sec)
            if not rows:
                out.append(c)
                continue
            text = merge_section_texts([(r[1], r[2]) for r in rows])
            out.append(Retrieved(rows[0][0], text, sec, c.source_file, c.score))
        return out
