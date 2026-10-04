# core/splitter.py
import re
from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    heading_path: str
    source_file: str
    index: int


def _blocks(lines: list[str]) -> list[tuple[str, str]]:
    """把 md 行流切成 (heading_path, block) 序列；block 是段落/代码块/表格。"""
    headings: list[str] = []
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level, title = len(m.group(1)), m.group(2).strip()
            headings = headings[: level - 1] + [title]
            i += 1
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]

            def _bare(s: str) -> bool:  # 裸围栏行：fence+可选空白
                t = s.strip()
                return t.startswith(fence) and not t[len(fence):].strip()

            def _fencey(s: str) -> bool:
                t = s.strip()
                return t.startswith(fence)

            # 深度追踪：```inner 类带后缀围栏视作嵌套内容 +1，裸围栏 -1，归零才关闭。
            # 普通 ```python 开块不受影响；嵌套围栏与其说明文字保持同块（Review Focus #2）。
            code = [line]
            i += 1
            depth = 1
            while i < len(lines):
                if _bare(lines[i]):
                    depth -= 1
                    code.append(lines[i])
                    i += 1
                    if depth == 0:
                        break
                elif _fencey(lines[i]):
                    depth += 1
                    code.append(lines[i])
                    i += 1
                else:
                    code.append(lines[i])
                    i += 1
            out.append(("/".join(headings), "\n".join(code)))
            continue
        if stripped.startswith("|"):
            tbl = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                tbl.append(lines[i])
                i += 1
            out.append(("/".join(headings), "\n".join(tbl)))
            continue
        if not stripped:
            i += 1
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith(("#", "`", "~", "|")):
            para.append(lines[i])
            i += 1
        out.append(("/".join(headings), " ".join(para)))
    return out


def split_markdown(text: str, source_file: str, target: int = 400, overlap: int = 50) -> list[Chunk]:
    chunks: list[Chunk] = []
    atomic: list[bool] = []  # 与 chunks 对齐：True=代码块/表格（不参与相邻重叠）

    def emit(body: str, path: str, is_atomic: bool = False) -> None:
        if chunks and overlap > 0 and not atomic[-1] and not is_atomic:
            body = chunks[-1].text[-overlap:] + "\n\n" + body
        chunks.append(Chunk(text=body, heading_path=path, source_file=source_file, index=len(chunks)))
        atomic.append(is_atomic)

    buf: list[str] = []
    buf_path = ""

    def flush() -> None:
        nonlocal buf, buf_path
        if not buf:
            return
        emit("\n\n".join(buf), buf_path)
        buf, buf_path = [], ""

    for path, block in _blocks(text.splitlines()):
        if block.lstrip().startswith(("```", "~~~", "|")):
            flush()  # 代码块/表格独立成块，绝不与文字合并切断
            emit(block, path, is_atomic=True)
            continue
        if buf and path != buf_path:
            flush()
        buf_path = buf_path or path
        buf.append(block)
        joined = "\n\n".join(buf)
        while len(joined) >= target:  # 单段落超长也按 target 切片
            emit(joined[:target], buf_path)
            joined = joined[target:]
            buf = [joined] if joined else []
            if not joined:
                break
    flush()
    return chunks
