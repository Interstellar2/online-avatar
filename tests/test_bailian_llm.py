"""BailianLLM 协议逻辑测试（httpx MockTransport，不联网）。

锁定：SSE data 行解析、增量 token 聚合、[DONE] 终止、非 200 抛 EngineError、
非法 JSON 行跳过、client 随 __aexit__ 释放、未 enter 时 stream 报错。
"""

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
import pytest

from app.core.engines import EngineError
from app.solutions.cascade.engines_bailian import BailianLLM


@asynccontextmanager
async def make_llm(handler: Callable[[httpx.Request], httpx.Response]) -> AsyncIterator[BailianLLM]:
    """进入 __aenter__ 后用 MockTransport 替换真实 client（__aexit__ 负责释放）。"""
    llm = BailianLLM(api_key="k", model="qwen-plus", base_url="https://example/v1")
    await llm.__aenter__()
    await llm._client.aclose()
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        yield llm
    finally:
        await llm.__aexit__(None, None, None)


def _sse(*chunks: dict | str) -> bytes:
    """拼 SSE 报文体：dict 序列化为 data 行，str 原样作为一行。"""
    lines = []
    for c in chunks:
        if isinstance(c, dict):
            lines.append(f"data: {json.dumps(c)}")
        else:
            lines.append(c)
    return "\n\n".join(lines).encode()


def _delta(text: str) -> dict:
    return {"choices": [{"delta": {"content": text}}]}


async def test_stream_aggregates_delta_tokens():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, content=_sse(_delta("你好"), _delta("，世界"), "[DONE]"))

    async with make_llm(handler) as llm:
        tokens = [t async for t in llm.stream_reply([{"role": "user", "content": "hi"}])]
    assert tokens == ["你好", "，世界"]
    assert captured["url"] == "https://example/v1/chat/completions"
    assert captured["auth"] == "Bearer k"
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["model"] == "qwen-plus"


async def test_stream_skips_malformed_lines():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse("data: {not-json", _delta("好"), "", "event: ping", "[DONE]"),
        )

    async with make_llm(handler) as llm:
        tokens = [t async for t in llm.stream_reply([])]
    assert tokens == ["好"]


async def test_non_200_raises_engine_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=b"invalid api key")

    async with make_llm(handler) as llm:
        with pytest.raises(EngineError, match="LLM HTTP 401"):
            async for _ in llm.stream_reply([]):
                pass


async def test_client_released_on_exit():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse("[DONE]"))

    async with make_llm(handler) as llm:
        assert llm._client is not None
    assert llm._client is None


async def test_stream_before_enter_raises():
    llm = BailianLLM(api_key="k", model="m", base_url="https://example/v1")
    with pytest.raises(EngineError, match="未初始化"):
        async for _ in llm.stream_reply([]):
            pass
