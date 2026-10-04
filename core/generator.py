# core/generator.py
import json
from typing import Iterator

import httpx

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


class LLMError(Exception):
    pass


class LLMClient:
    """OpenAI 兼容 /chat/completions 流式客户端（spec §3）。失败自动重试 1 次。"""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._transport = None  # 测试注入 MockTransport

    def stream(self, messages: list[dict], temperature: float = 0.3,
               max_tokens: int = 500) -> Iterator[str]:
        payload = {"model": self.model, "messages": messages, "stream": True,
                   "temperature": temperature, "max_tokens": max_tokens}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        client = httpx.Client(transport=self._transport, timeout=self.timeout)
        last_err: Exception | None = None
        for _attempt in range(2):
            try:
                with client.stream("POST", f"{self.base_url}/chat/completions",
                                   json=payload, headers=headers) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            return
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue  # 忽略非 JSON 行
                        try:
                            delta = obj["choices"][0]["delta"].get("content")
                        except (KeyError, IndexError):
                            continue
                        if delta:
                            yield delta
                    return
            except (httpx.HTTPError, KeyError) as exc:
                last_err = exc
        raise LLMError(f"LLM 调用失败（已重试 1 次）: {last_err}")
