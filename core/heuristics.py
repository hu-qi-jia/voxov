# core/heuristics.py —— 轻量启发式：判断一句转写是否像"值得回答的问题"。
QUESTION_WORDS = (
    "什么", "怎么", "怎样", "如何", "为什么", "为何", "哪些", "哪个",
    "区别", "对比", "介绍一下", "讲讲", "说说", "谈谈", "聊聊",
    "了解", "熟悉", "用过", "原理", "场景", "优缺点", "手写", "实现一个",
)


def looks_like_question(text: str) -> bool:
    t = (text or "").strip()
    if not (4 <= len(t) <= 200):
        return False
    if t.endswith(("？", "?")):
        return True
    return any(k in t for k in QUESTION_WORDS)
