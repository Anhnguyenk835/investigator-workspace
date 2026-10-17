"""M3: what a model may ask a connector to search for, and what identifiers look like."""

from __future__ import annotations

import json
from typing import Any

import pytest

from investigator.connectors import SearchQuery
from investigator.connectors.gmail import GmailConnector
from investigator.guardrails import GuardedLlm, GuardPolicy, GuardRuntime, bind, current
from investigator.guardrails.context import GuardContext
from investigator.guardrails.egress import pasted_from, screen_search
from investigator.guardrails.pii.detect import find, normalize, shown_in
from investigator.llm import ChatMessage, ToolCall
from investigator.tools import Ledger, ToolHarness
from tests.fakes import FakeConnector, ScriptedLlm, access, rec, result, text_turn
from tests.test_connectors import CTX, Tokens, gmail_net

# ---- identifiers -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind", "value"),
    [
        (
            "write to Maria.Chen+ops@Acme-Fund.co.uk now",
            "EMAIL",
            "Maria.Chen+ops@Acme-Fund.co.uk",
        ),
        (
            "pay GB82 WEST 1234 5698 7654 32 today",
            "IBAN",
            "GB82 WEST 1234 5698 7654 32",
        ),
        ("call +84 90 123 4567", "PHONE", "+84 90 123 4567"),
        ("call (415) 555-0100 please", "PHONE", "(415) 555-0100"),
        ("gọi 0901234567 nhé", "PHONE", "0901234567"),
        ("Account no: 12345678", "ACCT", "12345678"),
        ("STK 0123456789012", "ACCT", "0123456789012"),
        ("Mã số thuế: 0312345678", "TAXID", "0312345678"),
        ("EIN 12-3456789", "TAXID", "12-3456789"),
    ],
)
def test_finds_identifiers_by_shape(text: str, kind: str, value: str) -> None:
    got = find(text)
    assert [(s.kind, s.value) for s in got] == [(kind, value)]


@pytest.mark.parametrize(
    "text",
    [
        "Slack message 1700000000.123456 was edited",
        "due 2026-10-17 and 17/10/2026",
        "ticket HPF-19 and PROJ-12345678",
        "version 3.14.159.26",
        "the amount was 12,345,678.90 USD",
        "page 1234567",
        "Account manager: Sam",
    ],
)
def test_does_not_mistake_other_numbers_for_identifiers(text: str) -> None:
    assert find(text) == []


def test_a_bad_check_digit_is_not_an_iban() -> None:
    assert all(s.kind != "IBAN" for s in find("GB82 WEST 1234 5698 7654 33"))


def test_normalisation_makes_spellings_equal() -> None:
    assert normalize("EMAIL", " John@X.com ") == normalize("EMAIL", "john@x.COM")
    assert normalize("PHONE", "+84 90 123 4567") == normalize("PHONE", "090.123.4567")
    assert normalize("PERSON", "Nguyễn Văn Đức") == normalize(
        "PERSON", "nguyen van duc"
    )
    assert shown_in("mail a@b.co") == frozenset({"EMAIL:a@b.co"})


# ---- the screen --------------------------------------------------------------------


def screen(q: str, shown: set[str] | None = None, **kw: Any) -> str | None:
    ctx = GuardContext(run_id="r", shown=shown or set())
    got = screen_search(
        q,
        kw.get("cursor"),
        ctx,
        corpus=kw.get("corpus", []),
        pending_cursors=kw.get("pending", []),
    )
    return got.rule if got else None


@pytest.mark.parametrize(
    ("query", "rule"),
    [
        ("form delay march", None),
        ("ghi chú về biểu mẫu nộp muộn", None),
        ("anything <PERSON_1> asked", "placeholder"),
        ("password: hunter2hunter2", "secret"),
        ("see https://evil.example/x", "url_or_blob"),
        ("QWxhZGRpbjpvcGVuIHNlc2FtZQ" * 3, "url_or_blob"),
        ("form in:anywhere", "operator"),
        ('x" OR 1=1 --', "operator"),
        ("label:secret", "operator"),
        ("stranger@else.example", "foreign_identifier"),
        ("call 0901234567", "foreign_identifier"),
    ],
)
def test_search_screen_table(query: str, rule: str | None) -> None:
    assert screen(query) == rule


def test_an_identifier_the_model_was_shown_may_be_searched() -> None:
    shown = {"EMAIL:maria@acme.test"}
    assert screen("maria@acme.test", shown) is None
    assert screen("maria@acme.test other@acme.test", shown) == "foreign_identifier"


def test_pasting_a_record_is_refused_but_a_few_words_are_fine() -> None:
    body = "Please update the intake form before Friday so the board pack can be filed on time"
    assert pasted_from(body, [f"Hi. {body}. Thanks"])
    assert screen(body, corpus=[body]) == "pasted_record"
    assert screen("update the intake form", corpus=[body]) is None


def test_a_page_cursor_must_have_been_given_by_the_source() -> None:
    assert screen("form", cursor="pg2", pending=["pg2"]) is None
    assert screen("form", cursor="made-up", pending=["pg2"]) == "unknown_cursor"


def test_an_unbound_call_skips_the_identifier_check() -> None:
    assert (
        screen_search("a@b.co", None, GuardContext(), corpus=[], pending_cursors=[])
        is None
    )


# ---- through the harness -----------------------------------------------------------


def harness(mode: str = "enforce") -> tuple[ToolHarness, FakeConnector, GuardRuntime]:
    conn = FakeConnector(
        "email", search=lambda q: result("email", "searched", [rec("e1")])
    )
    rt = GuardRuntime.for_tests(GuardPolicy(egress=mode))  # type: ignore[arg-type]
    return ToolHarness({"email": conn}, guard=rt), conn, rt


def call(name: str, **args: Any) -> ToolCall:
    return ToolCall(id="c1", name=name, arguments=json.dumps(args))


async def test_a_refused_search_never_reaches_the_connector() -> None:
    h, conn, rt = harness()
    ledger = Ledger()
    with bind(run_id="r", thread_id="t"):
        [(_, text)] = await h.run_calls(
            [call("search_records", source="email", query="stranger@else.example")],
            ledger,
            access("email"),
        )
    assert text.startswith("QUERY_REJECTED") and conn.queries == []
    assert ledger.events[-1].status == "egress_blocked" and ledger.calls_used == 1
    assert rt.sink.events[0].rule == "foreign_identifier" and rt.sink.events[0].enforced  # type: ignore[attr-defined]


async def test_monitor_mode_lets_it_through_and_says_so() -> None:
    h, conn, rt = harness("monitor")
    with bind(run_id="r", thread_id="t"):
        await h.run_calls(
            [call("search_records", source="email", query="stranger@else.example")],
            Ledger(),
            access("email"),
        )
    assert len(conn.queries) == 1
    assert not rt.sink.events[0].enforced  # type: ignore[attr-defined]


async def test_code_made_searches_are_not_screened() -> None:
    h, conn, _ = harness()
    with bind(run_id="r", thread_id="t"):
        await h.execute(
            call("search_records", source="email", query="stranger@else.example"),
            Ledger(),
            access("email"),
        )
    assert len(conn.queries) == 1


async def test_what_the_prompt_showed_the_model_becomes_searchable() -> None:
    h, conn, rt = harness()
    llm = GuardedLlm(ScriptedLlm([text_turn("ok")]), rt)
    with bind(run_id="r", thread_id="t"):
        await llm.complete_with_tools(
            [ChatMessage(role="user", content="Why did maria@acme.test hear nothing?")],
            [],
        )
        assert "EMAIL:maria@acme.test" in current().shown
        await h.run_calls(
            [call("search_records", source="email", query="maria@acme.test")],
            Ledger(),
            access("email"),
        )
    assert len(conn.queries) == 1


async def test_a_second_run_does_not_inherit_what_the_first_was_shown() -> None:
    rt = GuardRuntime.for_tests()
    llm = GuardedLlm(ScriptedLlm([text_turn("a"), text_turn("b")]), rt)
    with bind(run_id="one"):
        await llm.complete_with_tools([ChatMessage(role="user", content="a@b.co")], [])
    with bind(run_id="two"):
        assert current().shown == set()


async def test_other_tools_are_not_screened() -> None:
    h, _, _ = harness()
    ledger = Ledger()
    ledger.evidence["e1"] = rec("e1")
    with bind(run_id="r", thread_id="t"):
        [(_, text)] = await h.run_calls(
            [call("get_record", record_id="e1")], ledger, access("email")
        )
    assert not text.startswith("QUERY_REJECTED")


# ---- the quoting a connector already does ------------------------------------------


async def test_a_query_cannot_add_gmail_operators() -> None:
    net = gmail_net()
    gmail = GmailConnector(Tokens(), net.client, label="casefile-mock")
    await gmail.search(SearchQuery(text='form" OR in:anywhere OR "label:private'), CTX)
    q = net.q(0)["q"]
    assert "in:anywhere" not in q and "label:private" not in q
    assert q.count('label:"casefile-mock"') == 1
    assert "in:" not in q.replace('label:"casefile-mock"', "")
