# core/generator.py
SYSTEM_PROMPT = ("你是面试实时辅助。输出口语化中文，像求职者当场回答，可直接照读，"
    "禁止书面腔和套话开场。分点输出，每点一句完整的话，关键词加粗。按重要性排序，"
    "最重要的点放第一条。共 4-6 点，全篇不超过 250 字。优先使用参考资料，资料不足时用自身知识。")


def build_messages(question: str, contexts: list, history: list[tuple[str, str]]) -> list[dict]:
    parts: list[str] = []
    if contexts:
        refs = "\n\n".join(
            f"[资料{i+1}] {c.source_file} › {c.heading_path}\n{c.text}"
            for i, c in enumerate(contexts))
        parts.append(f"参考资料：\n{refs}")
    for q, a in history[-2:]:
        parts.append(f"之前的问题：{q}\n之前的回答：{a}")
    parts.append(f"当前问题：{question}")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
