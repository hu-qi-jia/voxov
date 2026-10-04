# tests/test_llm_client.py
import json
import httpx
import pytest
from core.generator import LLMClient, LLMError

def sse(*chunks):
    body = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n\n" for c in chunks)
    return body + "data: [DONE]\n\n"

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
    assert captured["json"]["temperature"] == 0.3 and captured["json"]["max_tokens"] == 500

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
