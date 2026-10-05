# core/kb.py
import re
import sqlite3
import threading
from pathlib import Path

import sqlite_vec
from sqlite_vec import serialize_float32

from core.embedder import Embedder
from core.splitter import split_markdown


class KnowledgeBase:
    def __init__(self, db_path: Path, embedder: Embedder) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self._lock = threading.RLock()  # 审查 C1：主线程建连、worker 线程检索
        self.con = sqlite3.connect(db_path, check_same_thread=False)
        self.con.enable_load_extension(True)
        sqlite_vec.load(self.con)
        self.con.enable_load_extension(False)
        self.con.executescript(f"""
        CREATE TABLE IF NOT EXISTS chunks(
          id INTEGER PRIMARY KEY,
          source_file TEXT NOT NULL,
          heading_path TEXT NOT NULL,
          seq INTEGER NOT NULL,
          text TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks
          USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[{embedder.dim}]);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, tokenize='trigram');
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        """)

    def ingest_file(self, md_path: Path) -> int:
        text = md_path.read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError(f"文件为空: {md_path}")
        chunks = split_markdown(text, md_path.name)
        if not chunks:
            raise ValueError(f"无可切分内容: {md_path}")
        self._ensure_space()
        vecs = self.embedder.encode([self._embed_input(c) for c in chunks])
        with self._lock:
            with self.con:
                self.delete_file(md_path.name)
                for c, v in zip(chunks, vecs):
                    cur = self.con.execute(
                        "INSERT INTO chunks(source_file, heading_path, seq, text) VALUES(?,?,?,?)",
                        (c.source_file, c.heading_path, c.index, c.text))
                    self.con.execute(
                        "INSERT INTO vec_chunks(chunk_id, embedding) VALUES(?,?)",
                        (cur.lastrowid, serialize_float32(v)))
                    self.con.execute(
                        "INSERT INTO chunks_fts(rowid, text) VALUES(?,?)",
                        (cur.lastrowid, c.text))
        return len(chunks)

    def delete_file(self, name: str) -> int:
        with self._lock:
            ids = [r[0] for r in self.con.execute(
                "SELECT id FROM chunks WHERE source_file=?", (name,))]
            with self.con:
                for i in ids:
                    self.con.execute("DELETE FROM vec_chunks WHERE chunk_id=?", (i,))
                    self.con.execute("DELETE FROM chunks_fts WHERE rowid=?", (i,))
                cur = self.con.execute("DELETE FROM chunks WHERE source_file=?", (name,))
            return cur.rowcount

    def list_files(self) -> list[tuple[str, int]]:
        with self._lock:
            return list(self.con.execute(
                "SELECT source_file, COUNT(*) FROM chunks GROUP BY source_file ORDER BY source_file"))

    def vector_search(self, vec: list[float], k: int = 5) -> list[tuple[int, float]]:
        with self._lock:
            rows = self.con.execute(
                "SELECT chunk_id, distance FROM vec_chunks WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
                (serialize_float32(vec), k))
            return [(int(r[0]), float(r[1])) for r in rows]

    def fts_search(self, query: str, k: int = 5) -> list[int]:
        # 审查 I5：整句短语匹配对自然提问失效 → 按词项 OR（拉丁/数字 ≥3、汉字连串 ≥3）
        tokens = [t for t in re.findall(r"[0-9A-Za-z_]{3,}|[一-鿿]{3,}", query)
                  if '"' not in t]
        if not tokens:  # trigram 最短 3 字符
            return []
        expr = " OR ".join(f'"{t}"' for t in tokens)
        try:
            rows = self.con.execute(
                "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                (expr, k))
        except sqlite3.OperationalError:
            return []
        return [int(r[0]) for r in rows]

    def get_chunks(self, ids: list[int]) -> list[tuple[int, str, str, str]]:
        if not ids:
            return []
        ph = ",".join("?" * len(ids))
        with self._lock:
            return [(int(r[0]), r[4], r[2], r[1]) for r in self.con.execute(
                f"SELECT id, source_file, heading_path, seq, text FROM chunks WHERE id IN ({ph}) ORDER BY id", ids)]

    @staticmethod
    def _embed_input(chunk) -> str:
        """入库向量 = 标题锚 + 正文：标题是主题语义锚（如「自我介绍」），
        长正文被 mean-pooling 稀释后短问题仍能对准。"""
        return f"{chunk.heading_path}\n{chunk.text}"

    # ---- 嵌入空间指纹：库内向量必须与查询向量同空间（事故：降级期入库、修复后查询） ----
    def embedder_id(self) -> str | None:
        with self._lock:
            row = self.con.execute(
                "SELECT value FROM meta WHERE key='embedder_id'").fetchone()
        return row[0] if row else None

    def set_embedder_id(self, value: str) -> None:
        with self._lock:
            with self.con:
                self.con.execute(
                    "INSERT INTO meta(key, value) VALUES('embedder_id', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (value,))

    def space_mismatch(self, embedder) -> bool:
        stored = self.embedder_id()
        return stored is not None and stored != embedder.id

    def chunk_count(self) -> int:
        with self._lock:
            return int(self.con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

    def reembed(self, embedder) -> int:
        """用指定嵌入模型重嵌全部 chunk（文本在库，无需原始文件）。"""
        with self._lock:
            rows = self.con.execute("SELECT id, heading_path, text FROM chunks").fetchall()
            self.con.execute("DELETE FROM vec_chunks")
            for i in range(0, len(rows), 64):
                batch = rows[i:i + 64]
                vecs = embedder.encode([
                    self._embed_input(type("C", (), {"heading_path": h, "text": t})())
                    for _, h, t in batch])
                for (rid, _h, _t), v in zip(batch, vecs):
                    self.con.execute(
                        "INSERT INTO vec_chunks(chunk_id, embedding) VALUES(?,?)",
                        (rid, serialize_float32(v)))
            with self.con:
                self.set_embedder_id(embedder.id)
        return len(rows)

    def _ensure_space(self) -> None:
        """入库前保证空间一致：不匹配则重嵌全部；降级模式入库直接拒绝。"""
        stored = self.embedder_id()
        current = self.embedder.id
        if stored == current:
            return
        if not current.startswith("onnx:"):
            # 降级（Hash）模式：真实向量若已存在则不能污染，直接拒绝入库
            if stored and stored.startswith("onnx:"):
                raise ValueError(
                    "嵌入模型未就绪（当前为降级模式），入库会污染语义空间——请先完成模型下载")
            self.set_embedder_id(current)      # 空库/纯降级库：如实记录
            return
        self.reembed(self.embedder)            # 用真实模型重嵌（含无指纹旧库自愈）
