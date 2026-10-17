"""LLM client. Every model call goes through the LiteLLM gateway.

The gateway (infra/llm-gateway) owns provider keys, fallbacks and budgets.
This client holds only a virtual key and speaks the OpenAI-compatible API, so
callers name a logical route ("fast" or "strong"), never a provider model.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Awaitable, Sequence
from functools import lru_cache
from typing import Any, Literal, Protocol, TypeVar, cast

from openai import APIError, AsyncOpenAI, Omit
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONSchema
from pydantic import BaseModel, ValidationError

from investigator.settings import get_settings

Route = Literal["fast", "strong"]

TModel = TypeVar("TModel", bound=BaseModel)


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str  # raw JSON as the model wrote it; the harness validates it


class ChatMessage(BaseModel):
    """A message in a tool-using conversation (adds tool calls and results)."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class AssistantTurn(BaseModel):
    message: ChatMessage
    model: str
    prompt_tokens: int
    completion_tokens: int


def messages_as_text(messages: Sequence[ChatMessage]) -> list[ChatMessage]:
    """The history with tool calls and results written out as plain messages.

    Used for the final turn, where no tools are bound: a provider may refuse a
    history holding tool calls when none are offered.
    """
    out: list[ChatMessage] = []
    for m in messages:
        if m.role == "assistant" and m.tool_calls:
            calls = "; ".join(f"{c.name}({c.arguments})" for c in m.tool_calls)
            out.append(
                ChatMessage(
                    role="assistant", content=f"{m.content}\n[Called {calls}]".strip()
                )
            )
        elif m.role == "tool":
            out.append(
                ChatMessage(
                    role="user", content=f"[{m.name or 'tool'} returned]\n{m.content}"
                )
            )
        else:
            out.append(ChatMessage(role=m.role, content=m.content))
    return out


def _wire(m: ChatMessage) -> ChatCompletionMessageParam:
    wire: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        wire["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": c.arguments},
            }
            for c in m.tool_calls
        ]
    if m.tool_call_id:
        wire["tool_call_id"] = m.tool_call_id
    return cast(ChatCompletionMessageParam, wire)


class TextDelta(BaseModel):
    """A piece of the answer as the model writes it."""

    text: str


# A streamed turn is zero or more text deltas, then the finished turn.
StreamItem = TextDelta | AssistantTurn


class LlmResponse(BaseModel):
    text: str
    route: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


class LlmError(Exception):
    """The gateway call failed or returned something unusable."""


class GatewayError(LlmError):
    """The gateway itself failed (network, 5xx, quota), as opposed to the model's output
    being unusable. These are the failures a circuit breaker counts."""


class LlmNotConfiguredError(LlmError):
    """No virtual key is set; the gateway cannot be called."""


class Llm(Protocol):
    """What the agents need from a model client: the real one, the guarded wrapper, or a fake."""

    def complete(
        self,
        messages: Sequence[Message],
        route: Route = ...,
        *,
        temperature: float = ...,
        max_tokens: int | None = ...,
        response_format: ResponseFormatJSONSchema | None = ...,
    ) -> Awaitable[LlmResponse]: ...

    def complete_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: list[dict[str, Any]],
        route: Route = ...,
        *,
        temperature: float = ...,
    ) -> Awaitable[AssistantTurn]: ...

    def stream_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: list[dict[str, Any]],
        route: Route = ...,
        *,
        temperature: float = ...,
    ) -> AsyncIterator[StreamItem]: ...

    def complete_structured(
        self,
        messages: Sequence[Message],
        schema: type[TModel],
        route: Route = ...,
        *,
        temperature: float = ...,
        max_tokens: int | None = ...,
    ) -> Awaitable[tuple[TModel, LlmResponse]]: ...


class LlmClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        if not api_key:
            raise LlmNotConfiguredError(
                "LITELLM_API_KEY is not set. Mint one with "
                "infra/llm-gateway/scripts/provision-virtual-key.sh."
            )
        # The proxy serves the OpenAI API under /v1.
        base = base_url.rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        self._client = AsyncOpenAI(
            base_url=base, api_key=api_key, max_retries=2, timeout=120
        )

    async def complete(
        self,
        messages: Sequence[Message],
        route: Route = "fast",
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: ResponseFormatJSONSchema | None = None,
    ) -> LlmResponse:
        started = time.monotonic()
        payload: list[ChatCompletionMessageParam] = [
            cast(ChatCompletionMessageParam, {"role": m.role, "content": m.content})
            for m in messages
        ]
        try:
            result = await self._client.chat.completions.create(
                model=route,
                messages=payload,
                temperature=temperature,
                max_tokens=max_tokens if max_tokens is not None else Omit(),
                response_format=response_format
                if response_format is not None
                else Omit(),
            )
        except APIError as exc:
            raise GatewayError(
                f"gateway call failed on route '{route}': {exc.message}"
            ) from exc
        usage = result.usage
        return LlmResponse(
            text=result.choices[0].message.content or "",
            route=route,
            model=result.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    async def complete_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: list[dict[str, Any]],
        route: Route = "fast",
        *,
        temperature: float = 0.0,
    ) -> AssistantTurn:
        """One model turn. With `tools` empty the model cannot call anything."""
        try:
            result = await self._client.chat.completions.create(
                model=route,
                messages=[_wire(m) for m in messages],
                temperature=temperature,
                tools=cast(Any, tools) if tools else Omit(),
            )
        except APIError as exc:
            raise GatewayError(
                f"gateway call failed on route '{route}': {exc.message}"
            ) from exc
        choice = result.choices[0].message
        calls = [
            ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments)
            for c in (choice.tool_calls or [])
            if c.type == "function"
        ]
        usage = result.usage
        return AssistantTurn(
            message=ChatMessage(
                role="assistant", content=choice.content or "", tool_calls=calls or None
            ),
            model=result.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )

    async def stream_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: list[dict[str, Any]],
        route: Route = "fast",
        *,
        temperature: float = 0.0,
    ) -> AsyncIterator[StreamItem]:
        """Like `complete_with_tools`, but yields text as it arrives.

        Always ends with the finished `AssistantTurn`, so a caller that ignores the
        deltas gets exactly what `complete_with_tools` would have returned.
        """
        text: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        model: str = route
        prompt_tokens = completion_tokens = 0
        try:
            stream = await self._client.chat.completions.create(
                model=route,
                messages=[_wire(m) for m in messages],
                temperature=temperature,
                tools=cast(Any, tools) if tools else Omit(),
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                model = chunk.model or model
                if chunk.usage:
                    prompt_tokens = chunk.usage.prompt_tokens
                    completion_tokens = chunk.usage.completion_tokens
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    text.append(delta.content)
                    yield TextDelta(text=delta.content)
                for part in delta.tool_calls or []:
                    slot = calls.setdefault(
                        part.index, {"id": "", "name": "", "arguments": ""}
                    )
                    slot["id"] = part.id or slot["id"]
                    if part.function:
                        slot["name"] += part.function.name or ""
                        slot["arguments"] += part.function.arguments or ""
        except APIError as exc:
            raise GatewayError(
                f"gateway call failed on route '{route}': {exc.message}"
            ) from exc
        tool_calls = [
            ToolCall(
                id=c["id"] or f"call_{i}", name=c["name"], arguments=c["arguments"]
            )
            for i, c in sorted(calls.items())
            if c["name"]
        ]
        yield AssistantTurn(
            message=ChatMessage(
                role="assistant", content="".join(text), tool_calls=tool_calls or None
            ),
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    async def complete_structured(
        self,
        messages: Sequence[Message],
        schema: type[TModel],
        route: Route = "fast",
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> tuple[TModel, LlmResponse]:
        """Ask for JSON matching `schema`; raise LlmError if it does not parse.

        Never returns a partially filled or guessed object: unknown is an error
        the caller must handle.
        """
        response = await self.complete(
            messages,
            route,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                    "strict": False,
                },
            },
        )
        try:
            return schema.model_validate(json.loads(response.text)), response
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LlmError(
                f"route '{route}' returned output that does not match {schema.__name__}"
            ) from exc


@lru_cache(maxsize=1)
def get_llm_client() -> LlmClient:
    settings = get_settings()
    return LlmClient(settings.litellm_base_url, settings.litellm_api_key)
