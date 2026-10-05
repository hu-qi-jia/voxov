# core/generator.py
import json
import time
from typing import Iterator

import httpx

SYSTEM_PROMPT = ("你是面试实时辅助。输出口语化中文，像求职者当场回答，可直接照读，"
    "禁止书面腔和套话开场。分点输出，每点一句完整的话，关键词加粗。按重要性排序，"
    "最重要的点放第一条。共 4-6 点，全篇不超过 250 字。优先使用参考资料，资料不足时用自身知识。")

GENERIC_PROMPT = ("你是面试实时辅助。知识库中没有相关资料，凭你自己的知识与经历回答。"
    "输出口语化中文，像求职者当场回答，可直接照读，禁止书面腔和套话开场。"
    "分点输出，每点一句完整的话，关键词加粗。按重要性排序，最重要的点放第一条。"
    "共 4-6 点，全篇不超过 250 字。禁止虚构或引用任何资料。")

STATEMENT_PROMPT = ("你是面试实时辅助。面试官正在做陈述或铺垫，不是提问。"
    "给出求职者此刻最该说的自然回应：一两句话即可，口语化、可直接照读，"
    "顺势带出自己的相关经验或优势。不要分点，不要超过 80 字。")


def build_messages(question: str, contexts: list, history: list[tuple[str, str]],
                   mode: str = "refs") -> list[dict]:
    if mode == "statement":
        system = STATEMENT_PROMPT
    elif mode == "generic":
        system = GENERIC_PROMPT
    else:
        system = SYSTEM_PROMPT
    parts: list[str] = []
    if mode == "refs" and contexts:
        refs = "\n\n".join(
            f"[资料{i+1}] {c.source_file} › {c.heading_path}\n{c.text}"
            for i, c in enumerate(contexts))
        parts.append(f"参考资料：\n{refs}")
    for q, a in history[-2:]:
        parts.append(f"之前的问题：{q}\n之前的回答：{a}")
    label = "当前面试官发言" if mode == "statement" else "当前问题"
    parts.append(f"{label}：{question}")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


class LLMError(Exception):
    pass


class LLMClient:
    """OpenAI 兼容 /chat/completions 流式客户端（spec §3）。失败自动重试 1 次。
    连接保活：httpx.Client 实例持久复用（参考 VoxRecall 的 keepalive/warmup），
    每次调用不再重新 TCP+TLS 握手——首字延迟显著下降。
    回答中断的两类根因都在这里收口：
    - finish_reason=length（max_tokens 打满；推理型模型思考 token 也计入额度）
    - 流中途网络断（已收到部分内容）
    两者都带已收内容做助手前缀自动续写，从断点接着写、绝不重复输出。"""

    CONTINUE_HINT = "继续，直接从上文断点接着写，不要重复任何已有内容。"

    def __init__(self, base_url: str, api_key: str, model: str,
                 connect_timeout: float = 10.0, read_timeout: float = 90.0,
                 max_tokens: int = 1024, max_rounds: int = 3) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = httpx.Timeout(connect_timeout, read=read_timeout)
        self.max_tokens = max_tokens   # 500 对推理型模型不够：思考也吃额度
        self.max_rounds = max_rounds   # 续写轮次封顶：初始 1 轮 + 最多 2 次续写
        self._transport = None  # 测试注入 MockTransport
        self._client: httpx.Client | None = None

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(transport=self._transport, timeout=self.timeout)
        return self._client

    def _stream_round(self, payload: dict, parts: list[str],
                      deadline_s: float) -> Iterator[str]:
        """单轮流：增量透传并收进 parts；return finish_reason（''=未收到）。
        总时长看门狗：部分服务端定期发 keepalive 帧骗过逐字节读超时——
        按墙钟判死，防止「正在生成…」永久挂起。"""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        client = self._http()
        finish = ""
        t0 = time.monotonic()
        with client.stream("POST", f"{self.base_url}/chat/completions",
                           json=payload, headers=headers) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if time.monotonic() - t0 > deadline_s:
                    raise httpx.ReadError(
                        f"生成超时（{deadline_s:.0f}s 未收尾，已收 {len(parts)} 段）")
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue  # 忽略非 JSON 行
                try:
                    choice = obj["choices"][0]
                    delta = (choice.get("delta") or {}).get("content")
                except (KeyError, IndexError):
                    continue
                if delta:
                    parts.append(delta)
                    yield delta
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
        return finish

    def _with_continue(self, convo: list[dict], parts: list[str]) -> list[dict]:
        """续写轮消息：已收内容做助手前缀 + 继续指令（从断点接着写，不重复）。"""
        return convo + [{"role": "assistant", "content": "".join(parts)},
                        {"role": "user", "content": self.CONTINUE_HINT}]

    def stream(self, messages: list[dict], temperature: float = 0.3,
               max_tokens: int | None = None,
               deadline_s: float = 240.0) -> Iterator[str]:
        budget = self.max_tokens if max_tokens is None else max_tokens
        convo = list(messages)
        for _round in range(self.max_rounds):
            payload = {"model": self.model, "messages": convo, "stream": True,
                       "temperature": temperature, "max_tokens": budget}
            parts: list[str] = []
            try:
                finish = yield from self._stream_round(payload, parts, deadline_s)
            except (httpx.HTTPError, KeyError) as exc:
                if parts:  # 已吐过内容：续写抢救，整发重试会重复
                    if _round == self.max_rounds - 1:  # 没有下一轮了：如实上报
                        raise LLMError(f"生成中断（已收到部分内容）: {exc}") from exc
                    convo = self._with_continue(convo, parts)
                    continue
                try:       # 未吐字：整发重试恰好一次
                    finish = yield from self._stream_round(payload, parts, deadline_s)
                except (httpx.HTTPError, KeyError) as exc2:
                    if parts:
                        raise LLMError(f"生成中断（已收到部分内容）: {exc2}") from exc2
                    raise LLMError(f"LLM 调用失败（已重试 1 次）: {exc2}") from exc2
            if finish == "length":  # 预算打满：续写轮补齐
                convo = self._with_continue(convo, parts)
                continue
            return
        # 轮次用尽：内容已尽力补齐，安静收尾（再抛错只是吓人）

    def warmup(self) -> None:
        """预建连接池 + 预热服务端首字（供后台线程调用；失败静默）。
        参考 VoxRecall 的 probe_llm_warmup：第一条真答案不该付冷启动的钱。"""
        try:
            list(self.stream([{"role": "user", "content": "ping"}],
                             temperature=0.0, max_tokens=1))
        except Exception:
            pass
