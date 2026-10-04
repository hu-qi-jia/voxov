# core/heuristics.py —— 轻量启发式：判断一句转写是否像"值得回答的问题"。
import re

QUESTION_WORDS = (
    "什么", "怎么", "怎样", "如何", "为什么", "为何", "哪些", "哪个",
    "区别", "对比", "介绍一下", "讲讲", "说说", "谈谈", "聊聊",
    # 了解/熟悉/用过 是过渡动词不作问题信号（「好的我们了解一下」须保持 chatter）；
    # 真问题「你了解 Redis 吗」由 strong_q 的「吗」尾兜住。
    "原理", "场景", "优缺点", "手写", "实现一个",
)


def looks_like_question(text: str) -> bool:
    t = (text or "").strip()
    if not (4 <= len(t) <= 200):
        return False
    if t.endswith(("？", "?")):
        return True
    return any(k in t for k in QUESTION_WORDS)


# --- 全话轮分类（路由 spec §4）：先到先得 chatter → open → question → statement ---
CHATTER_WORDS = ("嗯", "好的", "好的啊", "行", "谢谢", "辛苦", "下一题", "继续",
                 "明白", "清楚", "不错", "可以", "没问题", "开始吧", "等一下", "稍等")
# 子串替换只用 ≥2 字词：单字「嗯/行/好/对」参与 replace 会削「运行/银行」等实词
CHATTER_REPLACE_WORDS = tuple(w for w in CHATTER_WORDS if len(w) >= 2)
STRONG_Q_WORDS = ("什么", "怎么", "怎样", "如何", "为什么", "为何", "哪些", "哪个")
OPEN_ENDED_WORDS = ("自我介绍", "项目经历", "项目亮点", "职业规划", "离职原因",
                    "优缺点", "你的优势", "性格", "团队协作", "加班", "期望薪资",
                    "聊聊你", "说说你", "谈谈你", "遇到的困难", "失败经历", "成就感")
_WORD_RE = re.compile(r"[\w一-鿿]")


def classify_turn(text: str | None) -> str:
    t = (text or "").strip()
    if not _WORD_RE.search(t):
        return "chatter"                      # 空/纯标点兜底
    if len(t) < 8:
        return "chatter"                      # 寒暄/短反馈几乎低于此线
    open_hit = any(k in t for k in OPEN_ENDED_WORDS)
    strong_q = t.endswith(("？", "?", "吗")) or any(k in t for k in STRONG_Q_WORDS)
    if len(t) < 16 and not open_hit and not strong_q:
        residual = t
        for w in sorted(CHATTER_REPLACE_WORDS, key=len, reverse=True):
            residual = residual.replace(w, "")
        if len(residual.strip()) < 4 or (t.startswith(CHATTER_WORDS)
                                         and not looks_like_question(t)):
            return "chatter"
        if len(residual) < len(t):
            return "question"                # 剥离寒暄词后仍剩实质内容 → 寒暄+新话题，按提问路由
    if open_hit:
        return "open"
    if strong_q or looks_like_question(t):
        return "question"
    return "statement"
