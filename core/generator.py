# core/generator.py
import json
import threading
import time
from typing import Iterator

import httpx

# 连接池按 (base_url, api_key, model) 共享：并行生成各持 LLMClient 实例，
# 但底层 TLS 连接池共享——启动预热/上一轮回答的连接对后续生成依然有效。
_CLIENT_POOL: dict[tuple, httpx.Client] = {}
_POOL_LOCK = threading.Lock()

MAX_BUDGET = 16384  # 预算增长封顶：推理模型的思考深度天花板

# 资料不足以回答时模型只输出这个哨兵（参考 personal-ai-memory）：
# 检索命中≠资料能答（如简历库里问 transformer），模型明说比硬编强。
NO_ANSWER_SENTINEL = "[无法回答]"

# 单次入 prompt 的材料总字数封顶（参考 personal-ai-memory aiMaterials：
# 3000 字≈2000 token；整合任务材料过长只会加重推理、拖慢首字）。
MAX_MATERIAL_CHARS = 4500

SYNTH_PROMPT = ("你在面试现场实时辅助求职者。下面给你的是求职者「自己的真实资料」。"
    "你的任务不是回答问题，而是把资料中与问题相关的片段整理合并成一段连贯、口语化、"
    "可直接照读的话。可以调整顺序与措辞使表达通顺，但有几条硬约束：\n"
    "1. 内容只能来自资料：绝对禁止编造、补充、推断资料之外的任何事实、数字或经历；"
    "资料没写的一律不说。\n"
    "2. 优先照抄原文表述，只在衔接处做最小改写；不要发挥、不要举例、不要延伸。\n"
    "3. 数字、日期、专有名词、项目名必须与资料逐字一致，照抄不改："
    "不换算、不四舍五入、不写「约」。\n"
    "4. 只输出合并后的正文：不要开场白（如「好的」「根据资料」），不要复述问题，"
    "不要解释思路，不要分点，不要任何 markdown 标记。\n"
    "5. 篇幅控制在一分钟内能说完。\n"
    f"6. 资料不足以回答当前问题时，只输出这五个字：{NO_ANSWER_SENTINEL}")


def cap_materials(contexts: list, max_chars: int = MAX_MATERIAL_CHARS) -> list:
    """材料总字数封顶：超限的尾部整块丢弃，不切半截——半句话喂给模型比少一块更糟。
    首块超限也保留（能被检索出来就是最相关的，丢弃等于无米下锅）。"""
    out: list = []
    total = 0
    for c in contexts:
        if out and total + len(c.text) > max_chars:
            break
        out.append(c)
        total += len(c.text)
    return out


def build_messages(question: str, contexts: list,
                   history: list[tuple[str, str]]) -> list[dict]:
    """命中知识库的整理式 prompt：资料全量入 prompt，LLM 只做整理合并（禁编造）。"""
    parts: list[str] = []
    if contexts:
        refs = "\n\n".join(
            f"[资料{i+1}] {c.source_file} › {c.heading_path}\n{c.text}"
            for i, c in enumerate(contexts))
        parts.append(f"你的真实资料：\n{refs}")
    for q, a in history[-2:]:
        parts.append(f"之前的问题：{q}\n之前的回答：{a}")
    parts.append(f"当前问题：{question}")
    return [
        {"role": "system", "content": SYNTH_PROMPT},
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
                 max_tokens: int = 4096, max_rounds: int = 3) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = httpx.Timeout(connect_timeout, read=read_timeout)
        self.max_tokens = max_tokens   # 4096：推理型模型的思考+整合正文都要吃额度
        self.max_rounds = max_rounds   # 续写轮次封顶：初始 1 轮 + 最多 2 次续写
        self._transport = None  # 测试注入 MockTransport
        self._client: httpx.Client | None = None

    def _http(self) -> httpx.Client:
        key = (self.base_url, self.api_key, self.model,
               id(self._transport) if self._transport is not None else None)
        with _POOL_LOCK:
            client = _CLIENT_POOL.get(key)
            if client is None:
                client = httpx.Client(transport=self._transport, timeout=self.timeout)
                _CLIENT_POOL[key] = client
        return client

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

    def stream(self, messages: list[dict], temperature: float = 0.2,
               max_tokens: int | None = None,
               deadline_s: float = 240.0) -> Iterator[str]:
        budget = self.max_tokens if max_tokens is None else max_tokens
        growable = max_tokens is None   # 调用方显式给预算（warmup 探针）时不许增长
        convo = list(messages)
        produced = 0                    # 跨轮累计：最终是否产出过正文
        for rnd in range(self.max_rounds):
            last = rnd == self.max_rounds - 1
            payload = {"model": self.model, "messages": convo, "stream": True,
                       "temperature": temperature, "max_tokens": budget}
            parts: list[str] = []
            try:
                finish = yield from self._stream_round(payload, parts, deadline_s)
            except (httpx.HTTPError, KeyError) as exc:
                if parts:  # 已吐过内容：续写抢救，整发重试会重复
                    if last:
                        raise LLMError(f"生成中断（已收到部分内容）: {exc}") from exc
                    convo = self._with_continue(convo, parts)
                    budget = min(budget * 2, MAX_BUDGET)
                    continue
                try:       # 未吐字：整发重试恰好一次
                    finish = yield from self._stream_round(payload, parts, deadline_s)
                except (httpx.HTTPError, KeyError) as exc2:
                    if parts:
                        raise LLMError(f"生成中断（已收到部分内容）: {exc2}") from exc2
                    raise LLMError(f"LLM 调用失败（已重试 1 次）: {exc2}") from exc2
            produced += len(parts)
            if not parts:
                # 零正文：推理型模型把预算全花在思考上（finish=length、content 空，
                # 实测 deepseek-flash 真实规模 prompt 下 reasoning_tokens=1024 打满），
                # 续写无从续起——只能加大预算重发原始消息；显式预算/已封顶/无轮次：
                # 如实上报，让 UI 终结「正在生成…」（旧逻辑在此静默空回＝气泡永久卡死）。
                if finish == "length" and growable and budget < MAX_BUDGET and not last:
                    budget = min(budget * 4, MAX_BUDGET)
                    continue
                raise LLMError(
                    f"模型未输出正文（finish={finish or 'none'}, max_tokens={budget}）"
                    "——多为推理 token 耗尽预算，可调大额度或换非推理模型")
            if finish == "length":  # 预算打满：续写轮补齐（额度也放宽，思考+正文都要花）
                if last:
                    return      # 有内容、轮次用尽：安静收尾（正文已可见）
                convo = self._with_continue(convo, parts)
                budget = min(budget * 2, MAX_BUDGET)
                continue
            return
        if not produced:
            raise LLMError("模型未输出正文")

    def warmup(self) -> None:
        """预建连接池 + 预热服务端首字（供后台线程调用；失败静默）。
        参考 VoxRecall 的 probe_llm_warmup：第一条真答案不该付冷启动的钱。"""
        try:
            list(self.stream([{"role": "user", "content": "ping"}],
                             temperature=0.0, max_tokens=1))
        except Exception:
            pass
