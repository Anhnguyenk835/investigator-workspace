from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import date
from typing import Any

from investigator.connectors import (
    CoverageStatus,
    EvidenceRecord,
    SearchQuery,
    SearchResult,
    SourceCoverage,
)
from investigator.llm import (
    AssistantTurn,
    ChatMessage,
    LlmError,
    Message,
    StreamItem,
    TextDelta,
    ToolCall,
)
from investigator.tools import AccessContext


def rec(id: str, source: str = "email", **kw: Any) -> EvidenceRecord:
    fields: dict[str, Any] = {"title": f"title {id}", "excerpt": f"text {id}", **kw}
    return EvidenceRecord(id=id, source=source, **fields)


def result(
    source: str,
    status: CoverageStatus = "searched",
    records: list[EvidenceRecord] | None = None,
    cursor: str | None = None,
    detail: str | None = None,
) -> SearchResult:
    return SearchResult(
        coverage=SourceCoverage(source=source, status=status, detail=detail),
        records=records or [],
        next_cursor=cursor,
    )


class FakeConnector:
    def __init__(
        self,
        name: str = "email",
        *,
        search: Callable[[SearchQuery], SearchResult] | None = None,
        records: dict[str, EvidenceRecord] | None = None,
        threads: dict[str, list[EvidenceRecord]] | None = None,
        raises: Exception | None = None,
        delay: float = 0.0,
        options: list[dict[str, str]] | None = None,
        options_status: str = "ok",
    ) -> None:
        self.name = name
        self.options = options or []
        self.options_status = options_status
        self.listed = 0
        # The filter each search ran under, as the connector sees it.
        self.filters: list[Any] = []
        self._search = search or (lambda q: result(name, "no_matches"))
        self.records = records or {}
        self.threads = threads or {}
        self.raises = raises
        self.delay = delay
        self.queries: list[SearchQuery] = []
        self.fetched: list[str] = []

    async def suggestions(self, ctx: AccessContext) -> tuple[str, list[dict[str, str]]]:
        self.listed += 1
        return self.options_status, self.options

    async def search(self, query: SearchQuery, ctx: AccessContext) -> SearchResult:
        self.queries.append(query)
        self.filters.append(ctx.filter_for(self.name))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raises:
            raise self.raises
        return self._search(query)

    async def get_record(self, record_id: str, ctx: AccessContext) -> SearchResult:
        self.fetched.append(record_id)
        r = self.records.get(record_id)
        return result(self.name, "searched", [r] if r else [])

    async def get_thread(self, thread_id: str, ctx: AccessContext) -> SearchResult:
        self.fetched.append(f"thread:{thread_id}")
        return result(self.name, "searched", self.threads.get(thread_id, []))


class WholeSourceConnector(FakeConnector):
    """A source that cannot list its parts (Notion): it has no `suggestions`."""

    suggestions = None  # type: ignore[assignment]


def tool_turn(*calls: tuple[str, dict[str, Any]], text: str = "") -> AssistantTurn:
    import json

    tcs = [
        ToolCall(id=f"c{i}", name=n, arguments=json.dumps(a))
        for i, (n, a) in enumerate(calls)
    ]
    return AssistantTurn(
        message=ChatMessage(role="assistant", content=text, tool_calls=tcs or None),
        model="m",
        prompt_tokens=0,
        completion_tokens=0,
    )


def text_turn(text: str) -> AssistantTurn:
    return tool_turn(text=text)


class ScriptedLlm:
    """Plays back scripted tool-loop turns and per-schema structured results.

    `structured` maps a schema class to a value, an exception to raise, or a list
    played in order (the last item repeats). Unlisted schemas return an empty
    instance, which every optional-output schema allows.
    """

    def __init__(
        self,
        turns: Sequence[AssistantTurn] = (),
        structured: dict[type, Any] | None = None,
        fail_tools: bool = False,
    ) -> None:
        self.turns = list(turns)
        self.structured = structured or {}
        self.fail_tools = fail_tools
        self.tool_calls_seen: list[tuple[list[ChatMessage], list[dict[str, Any]]]] = []
        self.structured_calls: list[type] = []

    async def complete_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: list[dict[str, Any]],
        route: str = "fast",
        **_: Any,
    ) -> AssistantTurn:
        self.tool_calls_seen.append((list(messages), tools))
        if self.fail_tools:
            raise LlmError("boom")
        return self.turns.pop(0) if self.turns else text_turn("done")

    async def stream_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: list[dict[str, Any]],
        route: str = "fast",
        **_: Any,
    ) -> AsyncIterator[StreamItem]:
        """The scripted turn, with its text delivered in word-sized pieces first."""
        turn = await self.complete_with_tools(messages, tools, route)
        for word in re.findall(r"\S+\s*", turn.message.content):
            yield TextDelta(text=word)
        yield turn

    async def complete_structured(
        self, messages: Sequence[Message], schema: type, route: str = "fast", **_: Any
    ) -> tuple[Any, Any]:
        self.structured_calls.append(schema)
        value = self.structured.get(schema)
        if callable(value):  # a responder that reads what it was asked
            value = value(messages)
        if isinstance(value, list):
            value = value.pop(0) if len(value) > 1 else value[0]
        if isinstance(value, Exception):
            raise value
        return (schema() if value is None else value), None

    def count(self, schema: type) -> int:
        return sum(1 for s in self.structured_calls if s is schema)


def access(*sources: str, **kw: Any) -> AccessContext:
    return AccessContext(user_id="u", permitted_sources=frozenset(sources), **kw)


D = date


class RecordingLlm(ScriptedLlm):
    """A scripted model that also keeps everything it was ever sent, so a test can assert
    on what the model was shown. `seen()` is all of it as one string."""

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self.structured_seen: list[list[Message]] = []

    async def complete_structured(
        self, messages: Sequence[Message], schema: type, route: str = "fast", **kw: Any
    ) -> tuple[Any, Any]:
        self.structured_seen.append(list(messages))
        return await super().complete_structured(messages, schema, route, **kw)

    def seen(self) -> str:
        parts = [m.content for ms in self.structured_seen for m in ms]
        parts += [m.content for ms, _ in self.tool_calls_seen for m in ms]
        return "\n".join(parts)
