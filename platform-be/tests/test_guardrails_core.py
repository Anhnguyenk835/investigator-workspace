"""M0: the guard runtime wraps any client, records every call, and carries who it is for."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from investigator.guardrails import (
    BufferedAuditSink,
    GuardedLlm,
    GuardPolicy,
    GuardRuntime,
    MemoryAuditSink,
    bind,
    current,
    purpose,
)
from investigator.llm import ChatMessage, LlmError, Message
from tests.fakes import ScriptedLlm, text_turn, tool_turn


def make(llm: ScriptedLlm) -> tuple[GuardedLlm, MemoryAuditSink]:
    sink = MemoryAuditSink()
    return GuardedLlm(llm, GuardRuntime.for_tests(sink=sink)), sink


MSG = [ChatMessage(role="user", content="hello")]


async def test_records_a_call_with_who_it_was_for() -> None:
    llm, sink = make(ScriptedLlm([text_turn("hi")]))
    with bind(run_id="r1", actor="Sam", ip="10.0.0.1", purpose="chat"):
        turn = await llm.complete_with_tools(MSG, [])
    assert turn.message.content == "hi"
    (call,) = sink.calls
    assert (call.run_id, call.actor, call.ip, call.purpose) == (
        "r1",
        "Sam",
        "10.0.0.1",
        "chat",
    )
    assert call.status == "ok" and call.actor_verified is False
    assert call.input_chars == 5 and call.output_chars == 2
    assert len(call.input_sha256) == 64 and "hello" not in call.model_dump_json()


async def test_unbound_calls_are_still_recorded() -> None:
    llm, sink = make(ScriptedLlm([text_turn("x")]))
    await llm.complete_with_tools(MSG, [])
    assert sink.calls[0].purpose == "unbound" and sink.calls[0].run_id is None


async def test_failed_call_is_recorded_and_reraised() -> None:
    llm, sink = make(ScriptedLlm(fail_tools=True))
    with pytest.raises(LlmError):
        await llm.complete_with_tools(MSG, [])
    assert sink.calls[0].status == "error" and sink.calls[0].error_class == "LlmError"


async def test_tool_call_names_are_recorded_not_arguments() -> None:
    llm, sink = make(ScriptedLlm([tool_turn(("search", {"q": "secret-term"}))]))
    await llm.complete_with_tools(MSG, [])
    assert sink.calls[0].tool_call_names == ["search"]
    assert "secret-term" not in sink.calls[0].model_dump_json()


async def test_stream_passes_items_through_and_audits_once() -> None:
    llm, sink = make(ScriptedLlm([text_turn("one two three")]))
    items = [i async for i in llm.stream_with_tools(MSG, [])]
    assert "".join(getattr(i, "text", "") for i in items) == "one two three "[:-1] + ""
    assert len(sink.calls) == 1 and sink.calls[0].output_chars == len("one two three")


async def test_stream_closed_early_is_audited_without_error() -> None:
    llm, sink = make(ScriptedLlm([text_turn("one two three four")]))
    stream = llm.stream_with_tools(MSG, [])
    async for _ in stream:
        break
    await stream.aclose()  # type: ignore[attr-defined]
    assert len(sink.calls) == 1 and sink.calls[0].status == "ok"


class Out(BaseModel):
    n: int = 0


async def test_structured_works_with_a_client_that_has_no_complete() -> None:
    llm, sink = make(ScriptedLlm(structured={Out: Out(n=3)}))
    value, _ = await llm.complete_structured([Message(role="user", content="q")], Out)
    assert value.n == 3 and sink.calls[0].method == "complete_structured"


async def test_context_reaches_concurrent_calls() -> None:
    llm, sink = make(ScriptedLlm([text_turn("a"), text_turn("b"), text_turn("c")]))
    with bind(run_id="r2", actor="Kim"):
        await asyncio.gather(*(llm.complete_with_tools(MSG, []) for _ in range(3)))
    assert {c.run_id for c in sink.calls} == {"r2"} and len(sink.calls) == 3


async def test_purpose_labels_inner_calls_and_restores() -> None:
    with bind(run_id="r3", purpose="investigation"):
        with purpose("support.check"):
            assert current().purpose == "support.check"
            assert current().run_id == "r3"
        assert current().purpose == "investigation"
    assert current().run_id is None


async def test_audit_failure_does_not_fail_the_call() -> None:
    class Broken(MemoryAuditSink):
        async def call(self, record: object) -> None:
            raise RuntimeError("db down")

    llm = GuardedLlm(
        ScriptedLlm([text_turn("ok")]), GuardRuntime.for_tests(sink=Broken())
    )
    assert (await llm.complete_with_tools(MSG, [])).message.content == "ok"


async def test_audit_failure_can_be_made_to_fail_the_call() -> None:
    class Broken(MemoryAuditSink):
        async def call(self, record: object) -> None:
            raise RuntimeError("db down")

    rt = GuardRuntime.for_tests(GuardPolicy(audit_fail_closed=True), Broken())
    with pytest.raises(RuntimeError):
        await GuardedLlm(ScriptedLlm([text_turn("ok")]), rt).complete_with_tools(
            MSG, []
        )


async def test_disabled_guards_record_nothing() -> None:
    sink = MemoryAuditSink()
    rt = GuardRuntime.for_tests(GuardPolicy(enabled=False), sink)
    await GuardedLlm(ScriptedLlm([text_turn("x")]), rt).complete_with_tools(MSG, [])
    assert sink.calls == [] and rt.mode("pii") == "off"


def test_policy_fingerprint_changes_with_content() -> None:
    a, b = GuardPolicy(), GuardPolicy(pii="enforce")
    assert a.fingerprint != b.fingerprint and a.fingerprint == GuardPolicy().fingerprint


async def test_events_carry_context_and_policy_version() -> None:
    sink = MemoryAuditSink()
    rt = GuardRuntime.for_tests(sink=sink)
    with bind(run_id="r4", actor="Lee", ip="1.2.3.4"):
        await rt.emit("pii", "email", enforced=False, action="redact", detail="x" * 500)
    (e,) = sink.events
    assert (e.run_id, e.actor, e.ip, e.enforced) == ("r4", "Lee", "1.2.3.4", False)
    assert e.policy_version == rt.policy.fingerprint and len(e.detail or "") == 160


async def test_buffered_sink_flushes_and_survives_inner_failure() -> None:
    inner = MemoryAuditSink()
    buffered = BufferedAuditSink(inner)
    buffered.start()
    llm = GuardedLlm(
        ScriptedLlm([text_turn("a"), text_turn("b")]),
        GuardRuntime.for_tests(sink=buffered),
    )
    await llm.complete_with_tools(MSG, [])
    await llm.complete_with_tools(MSG, [])
    await buffered.aclose()
    assert len(inner.calls) == 2 and buffered.dropped == 0


async def test_buffered_sink_drops_oldest_when_full() -> None:
    buffered = BufferedAuditSink(MemoryAuditSink(), maxsize=2)  # not started: it fills
    rt = GuardRuntime.for_tests(sink=buffered)
    for _ in range(4):
        await rt.emit("pii", "r", enforced=False)
    assert buffered.dropped == 2
