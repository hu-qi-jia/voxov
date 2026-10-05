# tests/test_llm_client.py
import json
import httpx
import pytest
from core.generator import LLMClient, LLMError

def sse(*chunks):
    body = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n\n" for c in chunks)
    return body + "data: [DONE]\n\n"

def sse_chunk(*chunks):
    """仅内容块、不带 [DONE]：截断/续写场景需手工控制流结束方式。"""
    return "".join(f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n\n"
                   for c in chunks)

def sse_end(finish):
    """正常收尾：finish_reason 块 + [DONE]。"""
    return ("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": finish}]})
            + "\n\ndata: [DONE]\n\n")

def make_client(handler):
    transport = httpx.MockTransport(handler)
    c = LLMClient("https://api.example.com/v1", "sk-test", "test-model")
    c._transport = transport  # 测试注入
    return c

def test_stream_yields_deltas():
    c = make_client(lambda req: httpx.Response(200, text=sse("你", "好", "。")))
    assert "".join(c.stream([{"role": "user", "content": "hi"}])) == "你好。"

def test_payload_and_headers():
    captured = {}
    def handler(req):
        captured["url"] = str(req.url)
        captured["auth"] = req.headers["Authorization"]
        captured["json"] = json.loads(req.content)
        return httpx.Response(200, text=sse("ok"))
    list(make_client(handler).stream([{"role": "user", "content": "x"}]))
    assert captured["url"].endswith("/chat/completions")
    assert captured["auth"] == "Bearer sk-test"
    assert captured["json"]["stream"] is True
    assert captured["json"]["temperature"] == 0.2 and captured["json"]["max_tokens"] == 4096

def test_malformed_sse_ignored():
    body = "data: not-json\n\ndata: {\"choices\": [{\"delta\": {\"content\": \"好\"}}]}\n\ndata: [DONE]\n\n"
    c = make_client(lambda req: httpx.Response(200, text=body))
    assert "".join(c.stream([{"role": "user", "content": "x"}])) == "好"

def test_no_content_delta_skipped():
    body = ("data: {\"choices\": [{\"delta\": {\"role\": \"assistant\"}}]}\n\n"
            "data: {\"choices\": [{\"delta\": {\"content\": \"答\"}}]}\n\ndata: [DONE]\n\n")
    c = make_client(lambda req: httpx.Response(200, text=body))
    assert "".join(c.stream([{"role": "user", "content": "x"}])) == "答"

def test_http_500_raises_after_retry():
    calls = {"n": 0}
    def handler(req):
        calls["n"] += 1
        return httpx.Response(500, text="err")
    with pytest.raises(LLMError):
        list(make_client(handler).stream([{"role": "user", "content": "x"}]))
    assert calls["n"] == 2  # 重试恰好一次

def test_retry_once_then_succeeds():
    n = {"n": 0}
    def handler(req):
        n["n"] += 1
        if n["n"] == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, text=sse("恢复"))
    assert "".join(make_client(handler).stream([{"role": "user", "content": "x"}])) == "恢复"


def test_client_reused_across_calls(monkeypatch):
    """连接保活：多次调用只建一个 httpx.Client（省去每次 TCP+TLS 握手）。"""
    built = {"n": 0}
    real_client = httpx.Client

    class CountingClient(real_client):
        def __init__(self, *a, **k):
            built["n"] += 1
            super().__init__(*a, **k)

    monkeypatch.setattr(httpx, "Client", CountingClient)
    c = make_client(lambda req: httpx.Response(200, text=sse("ok")))
    assert built["n"] == 0                      # 构造 LLMClient 不建连接
    list(c.stream([{"role": "user", "content": "x"}]))
    assert built["n"] == 1
    list(c.stream([{"role": "user", "content": "y"}]))
    assert built["n"] == 1                      # 第二次复用，不再新建


def test_warmup_sends_tiny_request_and_swallows_errors():
    captured = {}
    def handler(req):
        captured["json"] = json.loads(req.content)
        return httpx.Response(200, text=sse("h"))
    c = make_client(handler)
    c.warmup()
    assert captured["json"]["max_tokens"] == 1
    # 服务端挂了也不许炸：静默
    def dead(req):
        raise httpx.ConnectError("down")
    c2 = make_client(dead)
    c2.warmup()                                 # 不抛即通过


# --- 回答中断修复：max_tokens 打满 / 流中途断开 → 带前缀自动续写（不重复） ---
def test_finish_reason_length_auto_continues():
    """finish_reason=length：静默截断的主因（推理型模型思考也计入 max_tokens）。"""
    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        if len(calls) == 1:
            return httpx.Response(200, text=sse_chunk("第一段被截断的") + sse_end("length"))
        return httpx.Response(200, text=sse_chunk("续上的后半段。") + sse_end("stop"))

    out = "".join(make_client(handler).stream([{"role": "user", "content": "x"}]))
    assert out == "第一段被截断的续上的后半段。"      # 无缝拼接、不重复
    assert len(calls) == 2
    # 第二次请求带上了已收内容做助手前缀 + 继续指令
    assert calls[1]["messages"][-2] == {"role": "assistant", "content": "第一段被截断的"}
    assert "继续" in calls[1]["messages"][-1]["content"]

def test_midstream_break_salvages_with_continuation():
    """流中途网络断：已收内容不丢，续写补齐而非整发重试（整发会重复）。"""
    calls = []

    def broken_then_ok(req):
        calls.append(json.loads(req.content))
        if len(calls) == 1:
            def gen():
                yield sse_chunk("开头").encode()
                raise httpx.ReadError("connection reset")   # 吐到一半断流
            return httpx.Response(200, content=gen())
        return httpx.Response(200, text=sse_chunk("结尾") + sse_end("stop"))

    out = "".join(make_client(broken_then_ok).stream([{"role": "user", "content": "x"}]))
    assert out == "开头结尾"
    assert calls[1]["messages"][-2]["content"] == "开头"

def test_continuation_rounds_capped():
    """每轮都 length 也不许无限续写：封顶后停止，不炸不挂。"""
    n = {"n": 0}
    def handler(req):
        n["n"] += 1
        return httpx.Response(200, text=sse_chunk(f"第{n['n']}段") + sse_end("length"))
    c = make_client(handler)
    c.max_rounds = 3
    out = "".join(c.stream([{"role": "user", "content": "x"}]))
    assert out == "第1段第2段第3段"
    assert n["n"] == 3

def test_midstream_break_every_round_raises_llmerror():
    """续写轮也断流：浮出 LLMError，UI 才能标注截断。"""
    def always_break(req):
        def gen():
            yield sse_chunk("片段").encode()
            raise httpx.ReadError("reset")
        return httpx.Response(200, content=gen())
    c = make_client(always_break)
    c.max_rounds = 2
    with pytest.raises(LLMError):
        "".join(c.stream([{"role": "user", "content": "x"}]))


# --- 零内容流（2026-10-05 事故根因）：deepseek-flash 为推理模型，思考吃满
# max_tokens 后 finish=length 且 content 零输出；旧逻辑续写轮同预算重试再耗尽、
# 轮次用尽后「安静收尾」——零 yield 零异常，UI 永远停在「正在生成…」。 ---
def test_reasoning_exhausts_budget_grows_and_recovers():
    """finish=length 且零正文：无可续写，加大 max_tokens 重发原始消息。"""
    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        if len(calls) == 1:
            return httpx.Response(200, text=sse_end("length"))   # 思考耗尽，零 content
        return httpx.Response(200, text=sse_chunk("真正的回答") + sse_end("stop"))

    out = "".join(make_client(handler).stream([{"role": "user", "content": "x"}]))
    assert out == "真正的回答"
    assert calls[1]["max_tokens"] == 16384                 # 4096*4：给思考留足额度
    assert calls[1]["messages"] == calls[0]["messages"]    # 重发原始消息（前缀为空，续写无意义）

def test_zero_content_clean_stop_raises():
    """流干净结束但零 content（服务端异常）：必须浮出 LLMError，不许静默空回。"""
    def handler(req):
        return httpx.Response(200, text=sse_end("stop"))
    with pytest.raises(LLMError):
        "".join(make_client(handler).stream([{"role": "user", "content": "x"}]))

def test_explicit_budget_not_grown_zero_content_raises():
    """调用方显式给预算（warmup 探针 max_tokens=1）：不许增长，零正文直接浮错。"""
    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        return httpx.Response(200, text=sse_end("length"))

    with pytest.raises(LLMError):
        "".join(make_client(handler).stream([{"role": "user", "content": "x"}],
                                            max_tokens=1))
    assert len(calls) == 1                                  # 未重发
    assert calls[0]["max_tokens"] == 1

def test_budget_growth_capped_zero_content_raises():
    """预算到封顶仍是零正文：如实上报，不许无限重试。"""
    def handler(req):
        return httpx.Response(200, text=sse_end("length"))
    c = make_client(handler)
    c.max_rounds = 4
    with pytest.raises(LLMError):
        "".join(c.stream([{"role": "user", "content": "x"}]))
