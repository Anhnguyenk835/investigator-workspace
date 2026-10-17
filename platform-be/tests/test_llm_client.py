import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel

from investigator.llm import LlmClient, LlmError, LlmNotConfiguredError, Message


def make_client(handler: httpx.MockTransport) -> LlmClient:
    client = LlmClient("http://gateway.test", "sk-virtual")
    client._client = AsyncOpenAI(
        base_url="http://gateway.test/v1",
        api_key="sk-virtual",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=handler),  # type: ignore[arg-type]
    )
    return client


def completion(text: str) -> dict[str, object]:
    return {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "gemini-3.1-flash-lite",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": text},
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }


def test_requires_virtual_key() -> None:
    with pytest.raises(LlmNotConfiguredError):
        LlmClient("http://gateway.test", "")


async def test_complete_sends_route_as_model() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        seen["path"] = request.url.path
        return httpx.Response(200, json=completion("pong"))

    result = await make_client(httpx.MockTransport(handler)).complete(
        [Message(role="user", content="ping")], "strong"
    )
    assert seen["model"] == "strong"
    assert seen["path"] == "/v1/chat/completions"
    assert result.text == "pong"
    assert result.prompt_tokens == 3


class Answer(BaseModel):
    verdict: str


async def test_structured_parses_valid_json() -> None:
    client = make_client(
        httpx.MockTransport(
            lambda r: httpx.Response(200, json=completion('{"verdict":"ok"}'))
        )
    )
    parsed, _ = await client.complete_structured(
        [Message(role="user", content="q")], Answer
    )
    assert parsed.verdict == "ok"


async def test_structured_rejects_invalid_output() -> None:
    client = make_client(
        httpx.MockTransport(lambda r: httpx.Response(200, json=completion("not json")))
    )
    with pytest.raises(LlmError):
        await client.complete_structured([Message(role="user", content="q")], Answer)


async def test_gateway_error_is_wrapped() -> None:
    client = make_client(
        httpx.MockTransport(
            lambda r: httpx.Response(429, json={"error": {"message": "budget"}})
        )
    )
    with pytest.raises(LlmError):
        await client.complete([Message(role="user", content="q")])


def sse(*chunks: dict[str, object]) -> httpx.Response:
    import json

    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(
        200, content=body, headers={"content-type": "text/event-stream"}
    )


def chunk(delta: dict[str, object], **extra: object) -> dict[str, object]:
    return {
        "id": "x",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "gemini-3.1-flash-lite",
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
        **extra,
    }


async def test_stream_yields_text_pieces_then_the_finished_turn() -> None:
    from investigator.llm import AssistantTurn, ChatMessage, TextDelta

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return sse(
            chunk({"role": "assistant", "content": ""}),
            chunk({"content": "Hel"}),
            chunk({"content": "lo"}),
            {
                "id": "x",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "gemini-3.1-flash-lite",
                "choices": [],
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 2,
                    "total_tokens": 9,
                },
            },
        )

    client = make_client(httpx.MockTransport(handler))
    items = [
        i
        async for i in client.stream_with_tools(
            [ChatMessage(role="user", content="hi")], [], "strong"
        )
    ]
    assert seen["stream"] is True and seen["model"] == "strong" and "tools" not in seen
    assert [i.text for i in items if isinstance(i, TextDelta)] == ["Hel", "lo"]
    turn = items[-1]
    assert isinstance(turn, AssistantTurn)
    assert turn.message.content == "Hello" and turn.message.tool_calls is None
    assert (turn.prompt_tokens, turn.completion_tokens) == (7, 2)


async def test_stream_assembles_tool_calls_from_fragments() -> None:
    from investigator.llm import AssistantTurn, ChatMessage

    def call(index: int, **fn: str) -> dict[str, object]:
        part: dict[str, object] = {"index": index, "function": fn}
        if "name" in fn:
            part.update(id=f"call_{index}", type="function")
        return chunk({"tool_calls": [part]})

    client = make_client(
        httpx.MockTransport(
            lambda r: sse(
                call(0, name="search_records", arguments='{"source": "em'),
                call(0, arguments='ail", "query": "form"}'),
                call(1, name="get_record", arguments='{"record_id": "e1"}'),
            )
        )
    )
    tools = [{"type": "function", "function": {"name": "search_records"}}]
    items = [
        i
        async for i in client.stream_with_tools(
            [ChatMessage(role="user", content="hi")], tools, "fast"
        )
    ]
    turn = items[-1]
    assert isinstance(turn, AssistantTurn) and turn.message.tool_calls
    first, second = turn.message.tool_calls
    assert (first.id, first.name) == ("call_0", "search_records")
    assert first.arguments == '{"source": "email", "query": "form"}'
    assert (second.name, second.arguments) == ("get_record", '{"record_id": "e1"}')


async def test_stream_gateway_failure_is_an_llm_error() -> None:
    from investigator.llm import ChatMessage

    client = make_client(
        httpx.MockTransport(
            lambda r: httpx.Response(500, json={"error": {"message": "down"}})
        )
    )
    with pytest.raises(LlmError):
        async for _ in client.stream_with_tools(
            [ChatMessage(role="user", content="x")], [], "fast"
        ):
            pass
