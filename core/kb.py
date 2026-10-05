# core/kb.py
import re
import sqlite3
import threading
from pathlib import Path

import numpy as np
import sqlite_vec
from sqlite_vec import serialize_float32

from core.embedder import Embedder
from core.splitter import split_markdown

QUESTION_VEC_THRESHOLD = 0.60   # 实测校准（2026-10-05，真实库 271 节）：正确问题命中
                                # 0.625-0.807，第二名噪声 ≤0.607；0.60 一刀切开


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
        CREATE TABLE IF NOT EXISTS sections(
          source_file TEXT NOT NULL,
          heading_path TEXT NOT NULL,
          title TEXT NOT NULL,
          qvec BLOB NOT NULL,
          PRIMARY KEY(source_file, heading_path)
        );
        """)
        try:   # 旧库升级：块所属「问题节」（### 三级标题为问题，以下皆回答）
            self.con.execute("ALTER TABLE chunks ADD COLUMN section TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass

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
                        "INSERT INTO chunks(source_file, heading_path, seq, text, section) "
                        "VALUES(?,?,?,?,?)",
                        (c.source_file, c.heading_path, c.index, c.text, c.section))
                    self.con.execute(
                        "INSERT INTO vec_chunks(chunk_id, embedding) VALUES(?,?)",
                        (cur.lastrowid, serialize_float32(v)))
                    self.con.execute(
                        "INSERT INTO chunks_fts(rowid, text) VALUES(?,?)",
                        (cur.lastrowid, c.text))
                self._refresh_file_sections(md_path.name)
        return len(chunks)

    def _refresh_file_sections(self, name: str) -> None:
        """重建该文件的问题向量：### 问题节一条，向量 = 节标题（### 标题）。
        检索主路「只检索问题」的索引（参考 personal-ai-memory：正文不向量化）。"""
        self.con.execute("DELETE FROM sections WHERE source_file=?", (name,))
        rows = self.con.execute(
            "SELECT section FROM chunks WHERE source_file=? AND section<>'' "
            "GROUP BY section", (name,)).fetchall()
        titles = [s.split("/")[-1].strip() for (s,) in rows]
        if not titles:
            return
        vecs = self.embedder.encode(titles)
        for (sec,), title, v in zip(rows, titles, vecs):
            self.con.execute(
                "INSERT OR REPLACE INTO sections(source_file, heading_path, title, qvec) "
                "VALUES(?,?,?,?)", (name, sec, title, serialize_float32(v)))

    def ensure_question_vectors(self) -> None:
        """旧库回填/换空间自愈：sections 行数与库内问题节总数不符时全量重建
        （用当前 embedder —— 与 reembed 后的块向量同空间）。"""
        with self._lock:
            have = self.con.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
            want = self.con.execute(
                "SELECT COUNT(*) FROM (SELECT DISTINCT source_file, section "
                "FROM chunks WHERE section<>'')").fetchone()[0]
        if have != want:
            self.rebuild_question_vectors()

    def rebuild_question_vectors(self) -> None:
        with self._lock:
            self.con.execute("DELETE FROM sections")
            files = [r[0] for r in self.con.execute(
                "SELECT DISTINCT source_file FROM chunks WHERE section<>''")]
            for name in files:
                self._refresh_file_sections(name)

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

    # ---- 标题直配 + 命中扩节（检索为主：问答式文档的节标题≈面试问题） ----
    def match_sections_by_vec(self, query: str, threshold: float = QUESTION_VEC_THRESHOLD,
                              limit: int = 2) -> list[tuple[str, str, float]]:
        """检索主路：查询向量 ⨯ 全部节的问题向量（节标题）暴力余弦。
        向量已 L2 归一化 → 点积即余弦。命中节按得分降序，后代节被祖先覆盖。
        降级（Hash）模式的问题向量无语义：一律不命中，只信标题直配。"""
        from core.embedder import OnnxEmbedder
        if not isinstance(self.embedder, OnnxEmbedder):
            return []
        self.ensure_question_vectors()
        with self._lock:
            rows = self.con.execute(
                "SELECT source_file, heading_path, qvec FROM sections").fetchall()
        if not rows:
            return []
        qv = np.asarray(self.embedder.encode_query(query), dtype=np.float32)
        scored = []
        for sf, hp, blob in rows:
            sv = np.frombuffer(blob, dtype=np.float32)
            scored.append((float(sv @ qv), sf, hp))
        # 得分降序；同分浅层优先（祖先扩节自带子树，覆盖面大）
        scored.sort(key=lambda x: (-x[0], x[2].count("/"), x[1], x[2]))
        out: list[tuple[str, str, float]] = []
        accepted: list[tuple[str, str]] = []
        for score, sf, hp in scored:
            if score < threshold:
                break
            if any(hp.startswith(a + "/") for a in
                   (p for s, p in accepted if s == sf)):
                continue                       # 后代节已被祖先覆盖（扩节自带子树）
            accepted.append((sf, hp))
            out.append((sf, hp, score))
            if len(out) >= limit:
                break
        return out

    def match_sections(self, query: str, limit: int = 2) -> list[tuple[str, str]]:
        """查询的 4 字滑窗（中文）/ ≥4 字符词项（西文，大小写不敏感）命中
        节标题（heading_path 末段）→ 候选节。嵌套命中只留最浅节
        （扩节时子树自然带上）；精确同名优先，然后按路径深度浅者优先。
        实测动机：向量检索对请求式问句（「请你做一个自我介绍」）会把真正的
        自我介绍正文排到第 20 名（d=0.986 过不了 0.95 的闸）——标题匹配硬得多。"""
        toks = [t.lower() for t in re.findall(r"[0-9A-Za-z_]{4,}", query)]
        toks += re.findall(r"(?=([一-鿿]{4}))", query)
        if not toks:
            return []
        rows = self.con.execute(
            "SELECT DISTINCT source_file, heading_path FROM chunks").fetchall()
        matched = []
        for sf, hp in rows:
            title = hp.split("/")[-1].strip().lower()
            exact = any(title == t for t in toks)
            if exact or any(t in title for t in toks):
                matched.append((0 if exact else 1, hp.count("/"), sf, hp))
        matched.sort()
        out: list[tuple[str, str]] = []
        for _, _, sf, hp in matched:
            if any(hp.startswith(a + "/") for a in
                   (p for s, p in out if s == sf)):
                continue                       # 后代节已被祖先覆盖（扩节自带子树）
            out.append((sf, hp))
            if len(out) >= limit:
                break
        return out

    def section_chunks(self, source_file: str, section: str) -> list[tuple[int, str, str]]:
        """问题节的全部块（### 标题以下直到下一个同级及更高标题），按 seq 顺读序。
        返回 (id, heading_path, text)——heading_path 用于拼回答时补回 #### 子标题。"""
        return [(int(r[0]), r[1], r[2]) for r in self.con.execute(
            "SELECT id, heading_path, text FROM chunks "
            "WHERE source_file=? AND section=? ORDER BY seq",
            (source_file, section))]

    def chunk_section(self, chunk_id: int) -> str:
        """块所属的问题节路径（兜底路命中块 → 扩节用）。"""
        row = self.con.execute("SELECT section FROM chunks WHERE id=?",
                               (chunk_id,)).fetchone()
        return (row[0] or "") if row else ""

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
            self.con.execute("DELETE FROM sections")   # 问题向量同空间重建（惰性回填）
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


def merge_section_texts(rows: list[tuple[str, str]]) -> str:
    """顺读拼接问题节文本，三条规则：
    1. 拼缝去掉切块重叠（splitter 的 50 字尾 + 空行分隔）；对不上就原样分段
    2. 跨 #### 子标题处补一行四级标题——否则子标题只存在元数据里，回答丢层级
    3. 连续空格/全角空格折叠为单个（源文档的对齐空格会让直出参差不齐）"""
    out = ""
    prev_title = None
    for hp, text in rows:
        text = re.sub(r"[ \t　]{2,}", " ", text)
        text = "\n".join(line.rstrip() for line in text.splitlines())
        title = hp.split("/")[-1].strip() if hp else ""
        if not out:
            out = text
        elif title and title != prev_title:
            out += f"\n\n#### {title}\n\n{text}"
        else:
            seam = out[-50:] + "\n\n"
            out += text[len(seam):] if text.startswith(seam) else "\n\n" + text
        if title:
            prev_title = title
    return out
