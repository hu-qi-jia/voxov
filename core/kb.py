# core/kb.py
import re
import sqlite3
from pathlib import Path

import sqlite_vec
from sqlite_vec import serialize_float32

from core.embedder import Embedder
from core.splitter import split_markdown


class KnowledgeBase:
    def __init__(self, db_path: Path, embedder: Embedder) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self.con = sqlite3.connect(db_path)
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
        """)

    def ingest_file(self, md_path: Path) -> int:
        text = md_path.read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError(f"文件为空: {md_path}")
        chunks = split_markdown(text, md_path.name)
        if not chunks:
            raise ValueError(f"无可切分内容: {md_path}")
        vecs = self.embedder.encode([c.text for c in chunks])
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
        ids = [r[0] for r in self.con.execute(
            "SELECT id FROM chunks WHERE source_file=?", (name,))]
        with self.con:
            for i in ids:
                self.con.execute("DELETE FROM vec_chunks WHERE chunk_id=?", (i,))
                self.con.execute("DELETE FROM chunks_fts WHERE rowid=?", (i,))
            cur = self.con.execute("DELETE FROM chunks WHERE source_file=?", (name,))
        return cur.rowcount

    def list_files(self) -> list[tuple[str, int]]:
        return list(self.con.execute(
            "SELECT source_file, COUNT(*) FROM chunks GROUP BY source_file ORDER BY source_file"))

    def vector_search(self, vec: list[float], k: int = 5) -> list[tuple[int, float]]:
        rows = self.con.execute(
            "SELECT chunk_id, distance FROM vec_chunks WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (serialize_float32(vec), k))
        return [(int(r[0]), float(r[1])) for r in rows]

    def fts_search(self, query: str, k: int = 5) -> list[int]:
        phrase = '"' + re.sub(r'["\s]+', ' ', query).strip() + '"'
        if len(phrase.strip('"')) < 3:  # trigram 最短 3 字符
            return []
        try:
            rows = self.con.execute(
                "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                (phrase, k))
        except sqlite3.OperationalError:
            return []
        return [int(r[0]) for r in rows]

    def get_chunks(self, ids: list[int]) -> list[tuple[int, str, str, str]]:
        if not ids:
            return []
        ph = ",".join("?" * len(ids))
        return [(int(r[0]), r[4], r[2], r[1]) for r in self.con.execute(
            f"SELECT id, source_file, heading_path, seq, text FROM chunks WHERE id IN ({ph}) ORDER BY id", ids)]
