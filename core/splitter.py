# core/splitter.py
import re
from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    heading_path: str
    source_file: str
    index: int
    section: str = ""   # 所属「问题节」= 最近一个 ≤3 级标题的路径（### 问题，以下皆回答）


def _blocks(lines: list[str]) -> list[tuple[str, str, str]]:
    """把 md 行流切成 (heading_path, section, block) 序列；block 是段落/代码块/表格。
    section = 最近一个 ≤3 级标题的路径：### 三级标题为问题，三级以下（含 ####）
    的全部内容都归入该问题的回答。"""
    headings: list[tuple[int, str]] = []      # (level, title)：标准大纲弹栈
    out: list[tuple[str, str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level, title = len(m.group(1)), m.group(2).strip()
            # 按级别弹栈：同级标题互为兄弟，绝不因层级断档（# 直接 ###）错位嵌套
            # （旧实现 headings[:level-1] 按位置截断，### 兄弟会钻进前一个 ### 的子树）
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, title))
            i += 1
            continue
        section = "/".join(t for l, t in headings if l <= 3)
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
            out.append(("/".join(t for _, t in headings), section, "\n".join(code)))
            continue
        if stripped.startswith("|"):
            tbl = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                tbl.append(lines[i])
                i += 1
            out.append(("/".join(t for _, t in headings), section, "\n".join(tbl)))
            continue
        if not stripped:
            i += 1
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith(("#", "`", "~", "|")):
            para.append(lines[i])
            i += 1
        out.append(("/".join(t for _, t in headings), section, " ".join(para)))
    return out


def split_markdown(text: str, source_file: str, target: int = 400, overlap: int = 50) -> list[Chunk]:
    chunks: list[Chunk] = []
    atomic: list[bool] = []  # 与 chunks 对齐：True=代码块/表格（不参与相邻重叠）

    def emit(body: str, path: str, section: str, is_atomic: bool = False) -> None:
        # 重叠只在同一标题节内拼接：跨节尾巴会污染标题锚定嵌入（heading+text 同空间）
        # 并让 FTS 拉进不相关的相邻节——检索为主，锚必须干净。
        if (chunks and overlap > 0 and not atomic[-1] and not is_atomic
                and chunks[-1].heading_path == path):
            body = chunks[-1].text[-overlap:] + "\n\n" + body
        chunks.append(Chunk(text=body, heading_path=path, source_file=source_file,
                            index=len(chunks), section=section))
        atomic.append(is_atomic)

    buf: list[str] = []
    buf_path = ""
    buf_sec = ""

    def flush() -> None:
        nonlocal buf, buf_path, buf_sec
        if not buf:
            return
        emit("\n\n".join(buf), buf_path, buf_sec)
        buf, buf_path, buf_sec = [], "", ""

    for path, section, block in _blocks(text.splitlines()):
        if block.lstrip().startswith(("```", "~~~", "|")):
            flush()  # 代码块/表格独立成块，绝不与文字合并切断
            emit(block, path, section, is_atomic=True)
            continue
        if buf and path != buf_path:
            flush()
        buf_path = buf_path or path
        buf_sec = buf_sec or section
        buf.append(block)
        joined = "\n\n".join(buf)
        while len(joined) >= target:  # 单段落超长也按 target 切片
            emit(joined[:target], buf_path, buf_sec)
            joined = joined[target:]
            buf = [joined] if joined else []
            if not joined:
                # 消费殆尽必须清锚：buf_path 残留会让下一节的块继承本节标题
                # （heading_path 是检索锚，标错节 = 检索归因错位）
                buf_path = ""
                buf_sec = ""
                break
    flush()
    return chunks
