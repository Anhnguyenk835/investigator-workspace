"""The one place every model call passes through.

Wraps any client with the same methods as `LlmClient` (the real one, or a test fake).
Per call: preflight (kill switch, circuit breaker, budget) → clean what is sent (secrets)
→ call → account (usage, cost, breaker) → audit. The audit row is written even when the
call is refused or fails.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel

from investigator.connectors.privacy import redact_secrets
from investigator.guardrails.audit import LlmCall
from investigator.guardrails.budget import OPTIONAL_PURPOSES, estimate_tokens, price
from investigator.guardrails.context import UNBOUND, GuardContext, current
from investigator.guardrails.events import GuardBlocked, GuardDegraded
from investigator.guardrails.output.sanitize import (
    Finding,
    UrlPolicy,
    sanitize,
    urls_in,
)
from investigator.guardrails.output.stream_gate import StreamGate
from investigator.guardrails.pii.aliases import MemoryAliasBook
from investigator.guardrails.pii.detect import shown_in
from investigator.guardrails.pii.names import NameMatcher, names_in
from investigator.guardrails.pii.tokenize import (
    ReverseMap,
    StreamRestorer,
    tokenize_text,
)
from investigator.guardrails.runtime import GuardRuntime
from investigator.llm import (
    AssistantTurn,
    ChatMessage,
    GatewayError,
    LlmResponse,
    Message,
    StreamItem,
    TextDelta,
)

log = logging.getLogger(__name__)
TModel = TypeVar("TModel", bound=BaseModel)
Msg = TypeVar("Msg", Message, ChatMessage)

DAILY_RULES = (
    "global_day_cost",
    "demo_day_cost",
    "ip_day_cost",
    "ip_day_tokens",
    "actor_day_cost",
)


class _Call:
    """Bookkeeping for one call in flight."""

    def __init__(self, record: LlmCall) -> None:
        self.record = record
        # What each placeholder in this call's prompt stood for; None when nothing was swapped.
        self.reverse: ReverseMap | None = None
        self.started = time.monotonic()
        self.reached_model = False
        self.cost = 0.0
        # Addresses the model was given: the only ones it may repeat.
        self.urls = UrlPolicy()


class GuardedLlm:
    def __init__(self, inner: Any, runtime: GuardRuntime) -> None:
        self._inner = inner
        self._rt = runtime

    # ---- shared steps --------------------------------------------------------------

    async def _begin(
        self, method: str, messages: Sequence[Msg], route: str
    ) -> tuple[_Call, list[Msg]]:
        """Clean the input and run the preflight. Raises `GuardBlocked` when refused."""
        ctx = current()
        real = await self._clean(messages, route)
        if ctx is not UNBOUND:
            for m in real:
                ctx.shown |= shown_in(m.content)
                ctx.names |= names_in(m.content)
        clean, reverse = await self._swap_identifiers(real, ctx, route)
        h = hashlib.sha256()
        chars = 0
        for m in clean:
            h.update(m.role.encode())
            h.update(m.content.encode())
            chars += len(m.content)
        call = _Call(
            LlmCall(
                run_id=ctx.run_id,
                thread_id=ctx.thread_id,
                actor=ctx.actor,
                actor_verified=ctx.actor_verified,
                ip=ctx.ip,
                purpose=ctx.purpose,
                method=method,
                route=route,
                input_sha256=h.hexdigest(),
                input_chars=chars,
            )
        )
        call.reverse = reverse
        call.urls = UrlPolicy(
            allowed=urls_in(m.content for m in real), hosts=self._rt.policy.link_hosts
        )
        try:
            await self._preflight(call, route, estimate_tokens(chars))
        except GuardBlocked as exc:
            call.record.status = (
                "killed"
                if exc.guard == "kill"
                else "degraded"
                if isinstance(exc, GuardDegraded)
                else "blocked"
            )
            call.record.error_class = exc.rule or type(exc).__name__
            await self._rt.record_call(call.record)
            raise
        return call, clean

    async def _clean(self, messages: Sequence[Msg], route: str) -> list[Msg]:
        """Secrets never leave, whoever wrote them: records are redacted at the connector, but
        the question, reviewer notes and chat history are typed by people."""
        mode = self._rt.mode("secrets")
        if mode == "off":
            return list(messages)
        out: list[Msg] = []
        changed = 0
        for m in messages:
            red = redact_secrets(m.content)
            if red != m.content:
                changed += 1
                if mode == "enforce":
                    m = m.model_copy(update={"content": red})
            out.append(m)
        if changed:
            await self._rt.emit(
                "secrets",
                "redacted_in_prompt",
                enforced=mode == "enforce",
                action="redact",
                severity="medium",
                route=route,
                detail=f"{changed} message(s)",
            )
        return out

    async def _swap_identifiers(
        self, messages: list[Msg], ctx: GuardContext, route: str
    ) -> tuple[list[Msg], ReverseMap | None]:
        """Replace emails, phone numbers, account numbers and known people's names with
        placeholders. Monitor mode only counts what it would have replaced."""
        rt = self._rt
        mode = rt.mode("pii")
        if mode == "off" or not messages:
            return messages, None
        scope = ctx.run_id or ctx.thread_id
        book = rt.aliases if scope else MemoryAliasBook()
        matcher = NameMatcher(ctx.names) if ctx.names else None
        reverse = ReverseMap()
        out: list[Msg] = []
        try:
            for m in messages:
                content = await tokenize_text(
                    m.content, scope or "call", book, reverse, matcher
                )
                update: dict[str, Any] = {"content": content}
                calls = getattr(m, "tool_calls", None)
                if calls:
                    update["tool_calls"] = [
                        c.model_copy(
                            update={
                                "arguments": await tokenize_text(
                                    c.arguments, scope or "call", book, reverse, matcher
                                )
                            }
                        )
                        for c in calls
                    ]
                out.append(m.model_copy(update=update))
        except Exception as exc:
            log.exception("could not tokenize a prompt")
            if mode == "enforce":
                raise GuardBlocked(
                    "Personal details could not be protected, so nothing was sent to the AI.",
                    guard="pii",
                    rule="tokenizer_error",
                ) from exc
            return messages, None
        for kind, n in sorted(reverse.counts.items()):
            await rt.emit(
                "pii",
                kind.lower(),
                enforced=mode == "enforce",
                action="redact",
                route=route,
                detail=f"{n} in the prompt",
            )
        if mode != "enforce":
            return messages, None
        return out, reverse

    async def _preflight(self, call: _Call, route: str, est_tokens: int) -> None:
        rt = self._rt
        if not rt.policy.enabled:
            return
        ctx = current()
        purpose = ctx.purpose
        reason = await rt.kill.reason(route, purpose)
        if reason:
            await rt.emit(
                "kill",
                "kill_switch",
                enforced=True,
                action="block",
                severity="high",
                route=route,
                detail=reason,
            )
            raise GuardBlocked(
                f"AI is paused ({reason}). Nothing was lost: try again once it is resumed.",
                guard="kill",
                rule="kill_switch",
            )
        breaker_mode = rt.mode("breaker")
        if breaker_mode != "off":
            breaker = rt.breakers.of(route)
            if not breaker.allow():
                await rt.emit(
                    "breaker",
                    "circuit_open",
                    enforced=breaker_mode == "enforce",
                    action="block",
                    severity="high",
                    route=route,
                )
                if breaker_mode == "enforce":
                    raise GuardBlocked(
                        "The AI service is not responding. Try again in about "
                        f"{breaker.retry_after()} seconds.",
                        guard="breaker",
                        rule="circuit_open",
                    )
        budget_mode = rt.mode("budget")
        if budget_mode == "off":
            return
        optional = purpose in OPTIONAL_PURPOSES
        refused = [
            v
            for v in await rt.budget.check(ctx, purpose, est_tokens)
            if v.hard or optional
        ]
        for v in refused:
            await rt.emit(
                "budget",
                v.rule,
                enforced=budget_mode == "enforce",
                action="degrade" if optional and not v.hard else "block",
                severity="medium",
                route=route,
            )
        if refused and budget_mode == "enforce":
            first = refused[0]
            cls = (
                GuardBlocked
                if first.rule in DAILY_RULES or first.rule == "call_too_large"
                else GuardDegraded
            )
            raise cls(first.message, guard="budget", rule=first.rule)

    async def _report(self, found: list[Finding], mode: str, route: str) -> None:
        for f in found:
            await self._rt.emit(
                "output",
                f.kind,
                enforced=mode == "enforce",
                action="redact",
                severity="medium",
                route=route,
                detail=f.detail,
            )

    async def _scrub(self, text: str, call: _Call) -> str:
        """Take images, unapproved links and HTML out of text a person will read."""
        mode = self._rt.mode("output")
        if mode == "off" or not text:
            return text
        clean, found = sanitize(text, call.urls)
        await self._report(found, mode, call.record.route)
        return clean if mode == "enforce" else text

    async def _scrub_object(self, value: TModel, call: _Call) -> TModel:
        mode = self._rt.mode("output")
        if mode == "off":
            return value
        found: list[Finding] = []

        def walk(o: Any) -> Any:
            if isinstance(o, str):
                clean, f = sanitize(o, call.urls)
                found.extend(f)
                return clean
            if isinstance(o, list):
                return [walk(x) for x in o]
            if isinstance(o, dict):
                return {k: walk(v) for k, v in o.items()}
            return o

        data = value.model_dump()
        cleaned = walk(data)
        if not found:
            return value
        await self._report(found, mode, call.record.route)
        if mode != "enforce":
            return value
        try:
            return type(value).model_validate(cleaned)
        except ValueError:
            await self._rt.emit(
                "output",
                "unrepairable",
                enforced=True,
                action="block",
                severity="high",
                route=call.record.route,
            )
            raise GuardBlocked(
                "The model's answer carried content that could not be removed safely.",
                guard="output",
                rule="unrepairable",
            ) from None

    def _capped(self, kw: dict[str, Any]) -> dict[str, Any]:
        cap = self._rt.policy.limits.max_output_tokens
        if cap and kw.get("max_tokens") is None:
            kw = {**kw, "max_tokens": cap}
        return kw

    async def _end(
        self,
        call: _Call,
        *,
        model: str = "",
        prompt: int = 0,
        completion: int = 0,
        error: BaseException | None = None,
    ) -> None:
        rec, rt = call.record, self._rt
        rec.latency_ms = int((time.monotonic() - call.started) * 1000)
        if model:
            rec.model = model
        rec.prompt_tokens, rec.completion_tokens = prompt, completion
        breaker = rt.breakers.of(rec.route)
        if error is not None:
            rec.status = "error"
            rec.error_class = type(error).__name__
            if isinstance(error, GatewayError):
                breaker.failure()
            else:
                breaker.release_probe()
        else:
            breaker.success()
        if prompt + completion == 0 and call.reached_model and error is None:
            # The gateway reported no usage: count what was sent so budgets still move.
            rec.usage_estimated = True
            prompt = estimate_tokens(rec.input_chars)
            completion = estimate_tokens(rec.output_chars)
            rec.prompt_tokens, rec.completion_tokens = prompt, completion
        if call.reverse is not None and call.reverse.unknown:
            await rt.emit(
                "pii",
                "unknown_placeholder",
                enforced=False,
                severity="medium",
                route=rec.route,
                detail=f"{call.reverse.unknown} placeholder(s) the prompt never contained",
            )
        rec.cost_usd = price(rt.policy.limits, rec.route, prompt, completion)
        if rt.mode("budget") != "off" and rt.policy.enabled and (prompt + completion):
            ctx = current()
            try:
                await rt.budget.record(
                    ctx, rec.purpose, prompt + completion, rec.cost_usd
                )
            except Exception:
                log.exception("could not record LLM usage")
        await rt.record_call(rec)

    # ---- the four client methods ---------------------------------------------------

    async def complete(
        self, messages: Sequence[Message], route: str = "fast", **kw: Any
    ) -> LlmResponse:
        call, clean = await self._begin("complete", messages, route)
        error: BaseException | None = None
        out: LlmResponse | None = None
        try:
            call.reached_model = True
            out = await self._inner.complete(clean, route, **self._capped(kw))
            call.record.output_chars = len(out.text)
            text = call.reverse.restore(out.text) if call.reverse else out.text
            return out.model_copy(update={"text": await self._scrub(text, call)})
        except BaseException as exc:
            error = exc
            raise
        finally:
            await self._end(
                call,
                model=out.model if out else "",
                prompt=out.prompt_tokens if out else 0,
                completion=out.completion_tokens if out else 0,
                error=error,
            )

    async def complete_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: list[dict[str, Any]],
        route: str = "fast",
        **kw: Any,
    ) -> AssistantTurn:
        call, clean = await self._begin("complete_with_tools", messages, route)
        error: BaseException | None = None
        turn: AssistantTurn | None = None
        try:
            call.reached_model = True
            turn = await self._inner.complete_with_tools(clean, tools, route, **kw)
            self._note_turn(call.record, turn)
            return await self._scrub_turn(self._restore_turn(turn, call), call)
        except BaseException as exc:
            error = exc
            raise
        finally:
            await self._end(
                call,
                model=turn.model if turn else "",
                prompt=turn.prompt_tokens if turn else 0,
                completion=turn.completion_tokens if turn else 0,
                error=error,
            )

    async def stream_with_tools(
        self,
        messages: Sequence[ChatMessage],
        tools: list[dict[str, Any]],
        route: str = "fast",
        **kw: Any,
    ) -> AsyncIterator[StreamItem]:
        call, clean = await self._begin("stream_with_tools", messages, route)
        error: BaseException | None = None
        turn: AssistantTurn | None = None
        streamed = 0
        try:
            call.reached_model = True
            mode = self._rt.mode("output")
            gate = StreamGate(call.urls) if mode == "enforce" else None
            restorer = StreamRestorer(call.reverse) if call.reverse else None
            async for item in self._inner.stream_with_tools(clean, tools, route, **kw):
                if isinstance(item, AssistantTurn):
                    turn = item
                    self._note_turn(call.record, item)
                    item = self._restore_turn(item, call)
                    tail = restorer.flush() if restorer else ""
                    if gate is not None:
                        tail = gate.feed(tail) + gate.flush()
                        await self._report(gate.findings, mode, route)
                        item = item.model_copy(
                            update={
                                "message": item.message.model_copy(
                                    update={
                                        "content": sanitize(
                                            item.message.content, call.urls
                                        )[0]
                                    }
                                )
                            }
                        )
                    else:
                        item = await self._scrub_turn(item, call)
                    if tail:
                        yield TextDelta(text=tail)
                    yield item
                    continue
                streamed += len(item.text)
                # A switch thrown mid-answer cuts it off at the next piece of text.
                reason = await self._rt.kill.reason(route, call.record.purpose)
                if reason:
                    raise GuardBlocked(
                        f"AI is paused ({reason}).", guard="kill", rule="kill_switch"
                    )
                text = restorer.feed(item.text) if restorer else item.text
                if gate is not None:
                    text = gate.feed(text)
                if text:
                    yield TextDelta(text=text)
        except BaseException as exc:
            # A consumer that stops early closes the generator; that is not an error.
            if not isinstance(exc, GeneratorExit):
                error = exc
            raise
        finally:
            call.record.output_chars = call.record.output_chars or streamed
            await self._end(
                call,
                model=turn.model if turn else "",
                prompt=turn.prompt_tokens if turn else 0,
                completion=turn.completion_tokens if turn else 0,
                error=error,
            )

    async def complete_structured(
        self,
        messages: Sequence[Message],
        schema: type[TModel],
        route: str = "fast",
        **kw: Any,
    ) -> tuple[TModel, LlmResponse]:
        call, clean = await self._begin("complete_structured", messages, route)
        error: BaseException | None = None
        response: LlmResponse | None = None
        try:
            call.reached_model = True
            value, response = await self._inner.complete_structured(
                clean, schema, route, **self._capped(kw)
            )
            # A scripted test client returns no response object; the real one always does.
            if response is not None:
                call.record.output_chars = len(response.text)
            return await self._scrub_object(
                self._restore_object(value, call), call
            ), response
        except BaseException as exc:
            error = exc
            raise
        finally:
            await self._end(
                call,
                model=response.model if response else "",
                prompt=response.prompt_tokens if response else 0,
                completion=response.completion_tokens if response else 0,
                error=error,
            )

    @staticmethod
    def _restore_turn(turn: AssistantTurn, call: _Call) -> AssistantTurn:
        """Put real values back in the answer and in the arguments of the tools it asks for."""
        rev = call.reverse
        if rev is None:
            return turn
        msg = turn.message
        calls = []
        for c in msg.tool_calls or []:
            try:
                args = json.dumps(
                    rev.restore_json(json.loads(c.arguments)), ensure_ascii=False
                )
            except ValueError:
                args = rev.restore(c.arguments)
            calls.append(c.model_copy(update={"arguments": args}))
        return turn.model_copy(
            update={
                "message": msg.model_copy(
                    update={
                        "content": rev.restore(msg.content),
                        "tool_calls": calls or None,
                    }
                )
            }
        )

    @staticmethod
    def _restore_object(value: TModel, call: _Call) -> TModel:
        rev = call.reverse
        if rev is None:
            return value
        restored = rev.restore_json(value.model_dump())
        try:
            return type(value).model_validate(restored)
        except ValueError as exc:
            raise GuardBlocked(
                "The AI's answer could not be put back together after restoring personal details.",
                guard="pii",
                rule="restore_failed",
            ) from exc

    async def _scrub_turn(self, turn: AssistantTurn, call: _Call) -> AssistantTurn:
        text = await self._scrub(turn.message.content, call)
        if text == turn.message.content:
            return turn
        return turn.model_copy(
            update={"message": turn.message.model_copy(update={"content": text})}
        )

    @staticmethod
    def _note_turn(rec: LlmCall, turn: AssistantTurn) -> None:
        rec.output_chars = len(turn.message.content)
        rec.tool_call_names = [c.name for c in turn.message.tool_calls or []]


__all__ = ["GuardedLlm", "TextDelta"]
