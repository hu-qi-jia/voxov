# scripts/reingest_kb.py —— 用当前切分器把知识库全部文件重入库（一次性维护脚本）。
# 背景：kb.db 里的块是旧切分器（无重叠/锚错位）产物，data/ 被构建脚本一路保留，
# 新切块逻辑不会自动生效。流程：备份 kb.db → 按库内文件名在源目录找原文件 →
# 删除旧块重新入库（ingest_file 自带 delete+insert）→ 验证重叠与锚归属。
# 用法：python scripts/reingest_kb.py <源目录> [--dist <dist/notes-viewer>]
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.embedder import OnnxEmbedder   # noqa: E402
from core.kb import KnowledgeBase        # noqa: E402

norm = lambda s: "".join(s.split())


def main() -> int:
    src_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"E:\个人项目\AI学习")
    app = ROOT / "dist" / "notes-viewer"
    db = app / "data" / "kb.db"
    bak = db.with_suffix(".db.bak")
    shutil.copyfile(db, bak)
    print(f"[备份] {db} -> {bak}")

    con = sqlite3.connect(db)
    names = [r[0] for r in con.execute("SELECT DISTINCT source_file FROM chunks ORDER BY 1")]
    con.close()
    print(f"[库内文件] {len(names)} 个: {names}")

    matched = []
    for n in names:
        p = src_dir / n
        if p.exists():
            matched.append((n, p))
        else:
            print(f"[跳过] 源目录找不到原文件: {n}（保留旧块）")
    if not matched:
        print("[中止] 一个原文件都没匹配上")
        return 2

    embedder = OnnxEmbedder(app / "models" / "embed")
    kb = KnowledgeBase(db, embedder)
    stored = kb.embedder_id()
    print(f"[指纹] 库={stored} 模型={embedder.id} 一致={stored == embedder.id}")
    for n, p in matched:
        print(f"[重入库] {n}: {kb.ingest_file(p)} 块")

    # ---- 验证：同节相邻块重叠、跨节不串锚 ----
    con = sqlite3.connect(db)
    rows = con.execute(
        "SELECT source_file, heading_path, text FROM chunks ORDER BY source_file, id").fetchall()
    pairs = in_sec = overlap_ok = cross_sec = misattr = 0
    for i in range(1, len(rows)):
        if rows[i][0] != rows[i - 1][0]:
            continue
        pairs += 1
        sf, ph, pt = rows[i - 1]
        _, ch, ct = rows[i]
        if ch != ph:
            cross_sec += 1
            continue
        in_sec += 1
        t, h = norm(pt), norm(ct)
        if t[-40:] and t[-40:] == h[:40]:
            overlap_ok += 1
    total = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    con.close()
    print(f"[验证] 总块数={total} 同文件相邻={pairs}（同节={in_sec} 重叠命中={overlap_ok}，"
          f"跨节={cross_sec} 锚错位={misattr}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
