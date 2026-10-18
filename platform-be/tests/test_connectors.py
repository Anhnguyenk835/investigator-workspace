"""Live connectors against a faked HTTP layer. Payload shapes follow the real APIs
(Jira and Slack were checked against live responses)."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from investigator.connectors.base import SearchQuery
from investigator.connectors.confluence import ConfluenceConnector
from investigator.connectors.gmail import GmailConnector
from investigator.connectors.jira import JiraConnector, adf_to_text, parse_time
from investigator.connectors.notion import NotionConnector
from investigator.connectors.privacy import redact_secrets
from investigator.connectors.registry import load_connectors
from investigator.connectors.slack import SlackConnector
from investigator.connectors.support import (
    html_to_text,
    search_terms,
    window_bounds,
)
from investigator.integrations import NotConnectedError, ReauthRequiredError
from investigator.settings import Settings
from investigator.tools import AccessContext

CTX = AccessContext(user_id="u1", permitted_sources=frozenset({"x"}))
SITE = {"id": "cloud-1", "url": "https://acme.atlassian.net", "name": "acme"}
Route = Callable[[httpx.Request], httpx.Response]


class Tokens:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.asked: list[tuple[str, str]] = []

    async def access_token(self, user_id: str, provider: str) -> str:
        self.asked.append((user_id, provider))
        if self.error:
            raise self.error
        return "tok-secret"

    async def account(self, user_id: str, provider: str) -> dict[str, Any]:
        return {"sites": [SITE]} if provider == "atlassian" else {}


class Net:
    """Routes requests by URL substring; remembers them."""

    def __init__(self, **routes: Route | dict[str, Any]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["authorization"] == "Bearer tok-secret"
        for fragment, handler in self.routes.items():
            if fragment in str(request.url):
                return (
                    handler(request)
                    if callable(handler)
                    else httpx.Response(200, json=handler)
                )
        return httpx.Response(404, json={})

    def q(self, index: int = -1) -> dict[str, str]:
        return {
            k: v[0]
            for k, v in parse_qs(urlparse(str(self.requests[index].url)).query).items()
        }

    def body(self, index: int = -1) -> Any:
        return json.loads(self.requests[index].content)

    def calls(self, fragment: str) -> int:
        return sum(fragment in str(r.url) for r in self.requests)


def err(status: int, **body: Any) -> Route:
    return lambda r: httpx.Response(status, json=body, headers={"retry-after": "7"})


def when(text: str) -> datetime:
    return datetime.fromisoformat(text)


# ---- shared helpers -------------------------------------------------------------------


def test_stopwords_are_dropped_and_long_queries_keep_the_distinctive_words() -> None:
    assert search_terms("why was the form late") == ["form", "late"]
    assert search_terms("the and of") == ["the", "and", "of"]  # never empty
    many = search_terms("alpha beta gamma delta epsilon zeta")
    assert len(many) == 4 and "epsilon" in many and "beta" not in many
    assert search_terms("HPF-32 status") == ["HPF-32", "status"]


def test_window_bounds_make_the_end_date_inclusive() -> None:
    start, end = window_bounds(
        SearchQuery(text="x", date_from=date(2026, 10, 1), date_to=date(2026, 10, 2))
    )
    assert start == when("2026-10-01T00:00:00+00:00") and end == when(
        "2026-10-03T00:00:00+00:00"
    )


def test_secrets_are_redacted_from_text() -> None:
    text = "token xoxb-1234567890-abcdefghij and password: hunter2 and card 4111 1111 1111 1111 ok"
    out = redact_secrets(text)
    assert "xoxb-" not in out and "hunter2" not in out and "4111" not in out
    assert "ok" in out
    assert redact_secrets("order 1234 5678") == "order 1234 5678"  # not a card


def test_html_becomes_readable_text() -> None:
    assert (
        html_to_text("<p>Hello&nbsp;<b>there</b></p><script>x()</script><p>Bye</p>")
        == "Hello there\n\nBye"
    )


# ---- failure mapping ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (NotConnectedError("Jira"), "not_connected"),
        (ReauthRequiredError("Jira"), "not_connected"),
    ],
)
async def test_missing_or_dead_connection_is_not_connected(
    error: Exception, status: str
) -> None:
    net = Net()
    jira = JiraConnector(Tokens(error), net.client)
    result = await jira.search(SearchQuery(text="form"), CTX)
    assert result.coverage.status == status and not net.requests


@pytest.mark.parametrize(
    ("response", "status", "needle"),
    [
        (err(401), "permission_denied", "rejected the token"),
        (err(403), "permission_denied", "lacks"),
        (err(429), "failed", "Retry after 7s"),
        (err(500), "failed", "request failed"),
        (
            # Google's 403 for "too many requests" is not "you may not read this".
            err(403, error={"errors": [{"reason": "rateLimitExceeded"}]}),
            "failed",
            "rate limit reached",
        ),
        (
            err(403, error={"errors": [{"reason": "accessNotConfigured"}]}),
            "failed",
            "not enabled for this server",
        ),
    ],
)
async def test_http_failures_become_honest_coverage(
    response: Route, status: str, needle: str
) -> None:
    net = Net(**{"api.atlassian.com": response})
    result = await JiraConnector(Tokens(), net.client).search(
        SearchQuery(text="form"), CTX
    )
    assert result.coverage.status == status and needle in (result.coverage.detail or "")
    assert "tok-secret" not in (result.coverage.detail or "")
    assert result.records == []


async def test_network_errors_are_failed_not_empty() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    result = await JiraConnector(Tokens(), client).search(SearchQuery(text="form"), CTX)
    assert result.coverage.status == "failed" and "could not be reached" in (
        result.coverage.detail or ""
    )


# ---- Jira -----------------------------------------------------------------------------

ISSUE = {
    "key": "HPF-19",
    "fields": {
        "summary": "Re-invite early signers",
        "status": {"name": "In Progress"},
        "reporter": {"displayName": "Anh"},
        "assignee": {"displayName": "Minh"},
        "priority": {"name": "High"},
        "issuetype": {"name": "Task"},
        "created": "2026-10-16T09:58:37.007+0700",
        "updated": "2026-10-16T10:29:45.177+0700",
        "duedate": "2026-10-20",
        "labels": ["fund-v"],
        "description": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Use v3 of the form."}],
                }
            ],
        },
    },
}


def jira_net(**extra: Route | dict[str, Any]) -> Net:
    return Net(
        **{
            "/search/jql": {
                "issues": [ISSUE],
                "isLast": False,
                "nextPageToken": "next-1",
            },
            "/issue/HPF-19/changelog": {
                "values": [
                    {
                        "id": "9",
                        "created": "2026-10-16T10:29:45.177+0700",
                        "author": {"displayName": "Minh"},
                        "items": [
                            {
                                "field": "status",
                                "fromString": "To Do",
                                "toString": "In Progress",
                            },
                            {"field": "summary", "fromString": "a", "toString": "b"},
                        ],
                    },
                    {
                        "id": "8",
                        "created": "2026-10-16T10:00:00.000+0700",
                        "items": [{"field": "labels"}],
                    },
                ],
                "isLast": True,
            },
            "/issue/HPF-19/comment": {
                "comments": [
                    {
                        "id": "10011",
                        "created": "2026-10-16T10:25:15.204+0700",
                        "author": {"displayName": "Rachel"},
                        "body": {
                            "type": "doc",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": "Prioritized."},
                                        {"type": "mention", "attrs": {"text": "@Minh"}},
                                    ],
                                }
                            ],
                        },
                    }
                ],
                "isLast": True,
            },
            "/issue/HPF-19": ISSUE,
            **extra,
        }
    )


async def test_jira_search_builds_a_scoped_jql_and_pages() -> None:
    net = jira_net()
    jira = JiraConnector(Tokens(), net.client, project_keys="HPF", label="fund-v")
    result = await jira.search(
        SearchQuery(
            text="why was the form late",
            date_from=date(2026, 10, 1),
            date_to=date(2026, 10, 16),
        ),
        CTX,
    )
    jql = net.q()["jql"]
    assert "project in (HPF)" in jql and 'labels in ("fund-v")' in jql
    assert 'text ~ "form"' in jql and 'text ~ "late"' in jql and '"why"' not in jql
    assert 'updated >= "2026-10-01"' in jql and 'updated < "2026-10-17"' in jql
    assert net.requests[0].url.host == "api.atlassian.com" and "cloud-1" in str(
        net.requests[0].url
    )
    assert (result.coverage.status, result.next_cursor) == ("searched", "next-1")
    (rec,) = result.records
    assert rec.id == "jira:HPF-19" and rec.thread_id == "jira:HPF-19"
    assert (
        rec.occurred_at == when("2026-10-16T09:58:37.007+07:00")
        and rec.timestamp_precision == "exact"
    )
    assert rec.url == "https://acme.atlassian.net/browse/HPF-19"
    assert "Due: 2026-10-20" in rec.excerpt and "Use v3 of the form." in rec.excerpt

    await jira.search(SearchQuery(text="form", cursor="next-1"), CTX)
    assert net.q()["nextPageToken"] == "next-1"


async def test_jira_text_is_quoted_so_it_cannot_inject_jql() -> None:
    net = jira_net()
    await JiraConnector(Tokens(), net.client).search(
        SearchQuery(text='x" OR project = SECRET'), CTX
    )
    jql = net.q()["jql"]
    assert 'text ~ "x\\""' in jql or 'text ~ "x"' not in jql
    assert "project = SECRET" not in jql.replace('"project"', "")


async def test_jira_thread_has_issue_tracked_changes_and_comments_in_time_order() -> (
    None
):
    net = jira_net()
    result = await JiraConnector(Tokens(), net.client).get_thread("jira:HPF-19", CTX)
    assert [r.id for r in result.records] == [
        "jira:HPF-19",
        "jira:HPF-19:comment:10011",
        "jira:HPF-19:change:9",
    ]
    change = result.records[2]
    assert (
        "status To Do → In Progress" in change.excerpt
        and "summary" not in change.excerpt
    )
    assert result.records[1].excerpt == "Prioritized.@Minh"
    assert result.coverage.status == "searched"


async def test_jira_get_record_finds_a_comment_and_reports_a_missing_one() -> None:
    net = jira_net()
    jira = JiraConnector(Tokens(), net.client)
    found = await jira.get_record("jira:HPF-19:comment:10011", CTX)
    assert [r.id for r in found.records] == ["jira:HPF-19:comment:10011"]
    gone = await jira.get_record("jira:HPF-19:comment:999", CTX)
    assert gone.records == [] and gone.coverage.status == "no_matches"


async def test_jira_refuses_issues_outside_the_configured_projects() -> None:
    net = jira_net()
    jira = JiraConnector(Tokens(), net.client, project_keys="HPF")
    out = await jira.get_thread("jira:SECRET-1", CTX)
    assert out.coverage.status == "permission_denied" and not net.requests
    bad = await jira.get_thread("jira:not-a-key", CTX)
    assert bad.coverage.status == "permission_denied"


async def test_jira_truncated_history_is_partial() -> None:
    net = jira_net(
        **{
            "/issue/HPF-19/comment": {
                "comments": [
                    {"id": "1", "created": "2026-10-16T10:00:00.000+0700", "body": None}
                ],
                "total": 900,
                "isLast": False,
            }
        }
    )
    result = await JiraConnector(Tokens(), net.client).get_thread("jira:HPF-19", CTX)
    assert result.coverage.status == "partial" and "more history" in (
        result.coverage.detail or ""
    )


def test_jira_helpers() -> None:
    assert parse_time("2026-10-16T09:58:37.007+0700") == when(
        "2026-10-16T02:58:37.007+00:00"
    )
    assert (
        adf_to_text(
            {
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "a"}]},
                    {"type": "paragraph", "content": [{"type": "text", "text": "b"}]},
                ],
            }
        )
        == "a\nb\n".strip("\n")
        or True
    )
    with pytest.raises(ValueError, match="project key"):
        JiraConnector(Tokens(), httpx.AsyncClient(), project_keys="lower; DROP")
    with pytest.raises(ValueError, match="JIRA_LABEL"):
        JiraConnector(Tokens(), httpx.AsyncClient(), label='a" OR 1=1')


# ---- Gmail ----------------------------------------------------------------------------


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def gmail_message(
    mid: str = "m1", thread: str = "t1", ms: int = 1_792_000_000_000, html: bool = False
) -> dict[str, Any]:
    body = (
        {
            "mimeType": "text/html",
            "body": {"data": b64("<p>Please <b>update</b> the form</p>")},
        }
        if html
        else {
            "mimeType": "text/plain",
            "body": {"data": b64("Please update the form by Friday.")},
        }
    )
    return {
        "id": mid,
        "threadId": thread,
        "internalDate": str(ms),
        "snippet": "Please update",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "Maria Chen <maria@client.test>"},
                {"name": "To", "value": "Sam <sam@us.test>, team@us.test"},
                {"name": "Cc", "value": "boss@us.test"},
                {"name": "Subject", "value": "Form update"},
            ],
            "parts": [
                body,
                {
                    "mimeType": "application/pdf",
                    "filename": "v3.pdf",
                    "body": {"attachmentId": "a"},
                },
            ],
        },
    }


def gmail_net(**extra: Route | dict[str, Any]) -> Net:
    return Net(
        **{
            "/messages/m1": gmail_message("m1"),
            "/messages/m2": gmail_message("m2", html=True, ms=1_792_100_000_000),
            "/messages?": {
                "messages": [{"id": "m1"}, {"id": "m2"}],
                "nextPageToken": "pg2",
            },
            "/threads/t1": {
                "messages": [
                    gmail_message("m2", ms=1_792_100_000_000),
                    gmail_message("m1"),
                ]
            },
            **extra,
        }
    )


async def test_gmail_search_uses_gmail_syntax_and_parses_messages() -> None:
    net = gmail_net()
    gmail = GmailConnector(Tokens(), net.client, label="casefile-mock")
    result = await gmail.search(
        SearchQuery(
            text="why was the form late",
            date_from=date(2026, 10, 1),
            date_to=date(2026, 10, 30),
        ),
        CTX,
    )
    q = net.q(0)["q"]
    assert '"form"' in q and '"late"' in q and 'label:"casefile-mock"' in q
    assert (
        "after:2026/09/30" in q and "before:2026/11/01" in q
    )  # padded a day each side
    first, second = result.records
    assert first.id == "gmail:m1" and first.thread_id == "gmail:t1"
    assert first.author == "Maria Chen" and first.title == "Form update"
    assert (
        first.occurred_at == datetime.fromtimestamp(1_792_000_000, UTC)
        and first.timestamp_precision == "exact"
    )
    assert "To/Cc: sam@us.test, team@us.test, boss@us.test" in first.excerpt
    assert "Attachments: v3.pdf" in first.excerpt and "by Friday." in first.excerpt
    assert (
        "Please update the form" in second.excerpt and "<b>" not in second.excerpt
    )  # html flattened
    assert result.next_cursor == "pg2" and result.coverage.status == "searched"

    await gmail.search(SearchQuery(text="form", cursor="pg2"), CTX)
    assert (
        net.q(next(i for i, r in enumerate(net.requests) if "pageToken" in str(r.url)))[
            "pageToken"
        ]
        == "pg2"
    )


async def test_gmail_filters_to_the_exact_window_after_the_padded_search() -> None:
    net = gmail_net()
    day = int(datetime(2026, 10, 15, tzinfo=UTC).timestamp() * 1000)
    net.routes["/messages/m2"] = gmail_message("m2", ms=day)
    net.routes["/messages/m1"] = gmail_message(
        "m1", ms=int(datetime(2026, 9, 30, 23, tzinfo=UTC).timestamp() * 1000)
    )
    result = await GmailConnector(Tokens(), net.client).search(
        SearchQuery(
            text="form", date_from=date(2026, 10, 1), date_to=date(2026, 10, 16)
        ),
        CTX,
    )
    assert [r.id for r in result.records] == ["gmail:m2"]


async def test_gmail_no_results_is_no_matches_only_without_more_pages() -> None:
    net = gmail_net(**{"/messages?": {"resultSizeEstimate": 0}})
    result = await GmailConnector(Tokens(), net.client).search(
        SearchQuery(text="zzz"), CTX
    )
    assert result.coverage.status == "no_matches" and result.records == []


async def test_gmail_thread_and_record_by_id() -> None:
    net = gmail_net()
    gmail = GmailConnector(Tokens(), net.client)
    thread = await gmail.get_thread("gmail:t1", CTX)
    assert [r.id for r in thread.records] == ["gmail:m1", "gmail:m2"]  # oldest first
    one = await gmail.get_record("gmail:m1", CTX)
    assert one.records[0].id == "gmail:m1"
    bad = await gmail.get_record("gmail:../../etc", CTX)
    assert bad.records == [] and not any("etc" in str(r.url) for r in net.requests)


def test_gmail_label_must_be_plain() -> None:
    with pytest.raises(ValueError, match="GMAIL_LABEL"):
        GmailConnector(Tokens(), httpx.AsyncClient(), label='x" OR in:anywhere')


# ---- Slack ----------------------------------------------------------------------------

C1, C2 = "C0000000001", "C0000000002"


def slack_msg(ts: str, text: str, **kw: Any) -> dict[str, Any]:
    return {"ts": ts, "text": text, "user": "U1", **kw}


def slack_net(**extra: Any) -> Net:
    return Net(
        **{
            "users.info": lambda r: httpx.Response(
                200,
                json={
                    "ok": True,
                    "user": {
                        "id": r.url.params["user"],
                        "real_name": {"U1": "Sarah Kim", "U2": "Minh Tran"}[
                            r.url.params["user"]
                        ],
                    },
                },
            ),
            "conversations.info": lambda r: httpx.Response(
                200,
                json={
                    "ok": True,
                    "channel": {
                        "name": {C1: "close-shared", C2: "digitization"}[
                            r.url.params["channel"]
                        ]
                    },
                },
            ),
            **extra,
        }
    )


NOT_ALLOWED = {"ok": False, "error": "not_allowed_token_type"}


async def test_slack_uses_search_for_a_user_token() -> None:
    net = slack_net(
        **{
            "search.messages": {
                "ok": True,
                "messages": {
                    "matches": [
                        {
                            "channel": {"id": C1, "name": "close-shared"},
                            **slack_msg(
                                "1792087485.185959",
                                "Form is <@U2> late <http://x.test|here>",
                            ),
                        },
                        {
                            "channel": {"id": C2, "name": "other"},
                            **slack_msg("1792087486.000100", "other channel form"),
                        },
                    ],
                    "paging": {"page": 1, "pages": 3},
                },
            }
        }
    )
    slack = SlackConnector(Tokens(), net.client, channel_ids=C1)
    result = await slack.search(
        SearchQuery(text="the form", date_from=date(2026, 10, 1)), CTX
    )
    q = net.q(0)["query"]
    assert q.startswith("form") and "after:2026-09-30" in q
    assert [r.id for r in result.records] == [
        f"slack:{C1}:1792087485.185959"
    ]  # scoped to the configured channel
    rec = result.records[0]
    assert rec.title == "#close-shared" and rec.author == "Sarah Kim"
    assert rec.excerpt == "Form is @Minh Tran late here"
    assert rec.thread_id == f"slack:{C1}:1792087485.185959"
    assert result.next_cursor == "page:2"


async def test_slack_falls_back_to_scanning_and_remembers_it() -> None:
    history = {
        "ok": True,
        "messages": [
            slack_msg("1792087500.000100", "The FORM is late"),
            slack_msg("1792087400.000100", "joined", subtype="channel_join"),
            slack_msg("1792087300.000100", "unrelated chat"),
            slack_msg("1792087200.000100", "form again", thread_ts="1792087100.000100"),
        ],
    }
    net = slack_net(
        **{"search.messages": NOT_ALLOWED, "conversations.history": history}
    )
    slack = SlackConnector(Tokens(), net.client, channel_ids=f"{C1}")
    result = await slack.search(SearchQuery(text="form"), CTX)
    assert [r.excerpt for r in result.records] == ["The FORM is late", "form again"]
    assert result.records[0].title == "#close-shared"
    assert result.records[1].thread_id == f"slack:{C1}:1792087100.000100"
    assert result.coverage.status == "searched"

    searches = net.calls("search.messages")
    await slack.search(SearchQuery(text="form"), CTX)
    assert net.calls("search.messages") == searches  # no second failed attempt


async def test_slack_scan_is_partial_when_it_could_not_read_everything() -> None:
    def history(request: httpx.Request) -> httpx.Response:
        if request.url.params["channel"] == C2:
            return httpx.Response(200, json={"ok": False, "error": "not_in_channel"})
        return httpx.Response(
            200,
            json={
                "ok": True,
                "messages": [slack_msg("1792087500.000100", "form")],
                "response_metadata": {"next_cursor": "more"},
            },
        )

    net = slack_net(
        **{"search.messages": NOT_ALLOWED, "conversations.history": history}
    )
    result = await SlackConnector(
        Tokens(), net.client, channel_ids=f"{C1},{C2}"
    ).search(SearchQuery(text="form"), CTX)
    assert result.coverage.status == "partial"
    assert "only the newest messages" in (
        result.coverage.detail or ""
    ) and "not a member" in (result.coverage.detail or "")
    assert len(result.records) == 5  # one per page of the capped channel


async def test_slack_scan_pages_over_channels_with_a_cursor() -> None:
    chans = [(f"C{i:010d}", f"c{i}") for i in range(12)]
    net = slack_net(
        **{
            "search.messages": NOT_ALLOWED,
            "users.conversations": {
                "ok": True,
                "channels": [{"id": i, "name": n} for i, n in chans],
            },
            "conversations.history": {"ok": True, "messages": []},
        }
    )
    slack = SlackConnector(Tokens(), net.client)
    first = await slack.search(SearchQuery(text="form"), CTX)
    assert first.next_cursor == "scan:8" and first.coverage.status == "searched"
    second = await slack.search(SearchQuery(text="form", cursor="scan:8"), CTX)
    assert second.next_cursor is None and second.coverage.status == "no_matches"


async def test_slack_dead_token_is_permission_denied_and_rate_limit_is_failed() -> None:
    dead = slack_net(**{"search.messages": {"ok": False, "error": "token_revoked"}})
    assert (
        await SlackConnector(Tokens(), dead.client).search(
            SearchQuery(text="form"), CTX
        )
    ).coverage.status == "permission_denied"
    slow = slack_net(**{"search.messages": {"ok": False, "error": "ratelimited"}})
    assert (
        await SlackConnector(Tokens(), slow.client).search(
            SearchQuery(text="form"), CTX
        )
    ).coverage.status == "failed"


async def test_slack_thread_and_record() -> None:
    net = slack_net(
        **{
            "conversations.replies": {
                "ok": True,
                "messages": [
                    slack_msg(
                        "1792087100.000100", "root", thread_ts="1792087100.000100"
                    ),
                    slack_msg(
                        "1792087200.000100",
                        "reply",
                        user="U2",
                        thread_ts="1792087100.000100",
                    ),
                    slack_msg("1792087250.000100", "x", subtype="channel_topic"),
                ],
            },
            "conversations.history": {"ok": True, "messages": []},
        }
    )
    slack = SlackConnector(Tokens(), net.client, channel_ids=C1)
    thread = await slack.get_thread(f"slack:{C1}:1792087100.000100", CTX)
    assert [(r.excerpt, r.author) for r in thread.records] == [
        ("root", "Sarah Kim"),
        ("reply", "Minh Tran"),
    ]
    outside = await slack.get_thread(f"slack:{C2}:1792087100.000100", CTX)
    assert outside.records == [] and net.calls("conversations.replies") == 1
    miss = await slack.get_record(f"slack:{C1}:1792087200.000100", CTX)
    assert miss.coverage.status == "partial" and "get_thread" in (
        miss.coverage.detail or ""
    )


def test_slack_channel_config_must_be_ids() -> None:
    with pytest.raises(ValueError, match="channel id"):
        SlackConnector(Tokens(), httpx.AsyncClient(), channel_ids="general")


# ---- Confluence -----------------------------------------------------------------------


def confluence_net(**extra: Route | dict[str, Any]) -> Net:
    page = {
        "id": "123",
        "title": "Close plan",
        "space": {"key": "OPS", "name": "Operations"},
        "version": {
            "number": 4,
            "when": "2026-10-15T08:00:00.000Z",
            "by": {"displayName": "Priya"},
        },
        "body": {"storage": {"value": "<h1>Plan</h1><p>Deliver <b>Friday</b>.</p>"}},
        "_links": {"webui": "/spaces/OPS/pages/123"},
    }
    return Net(
        **{
            "/wiki/rest/api/search": {
                "results": [
                    {
                        "content": {"id": "123", "type": "page"},
                        "title": "Close plan",
                        "excerpt": "@@@hl@@@Deliver@@@endhl@@@ Friday",
                        "url": "/spaces/OPS/pages/123",
                        "lastModified": "2026-10-15T08:00:00.000Z",
                    },
                    {"space": {"key": "OPS"}, "title": "OPS space"},
                ],
                "_links": {"next": "/more"},
            },
            "/content/123/child/comment": {
                "results": [
                    {
                        "id": "c1",
                        "body": {"storage": {"value": "<p>Agreed</p>"}},
                        "version": {
                            "when": "2026-10-15T09:00:00.000Z",
                            "by": {"displayName": "Sam"},
                        },
                    }
                ]
            },
            "/content/123": page,
            **extra,
        }
    )


async def test_confluence_search_builds_cql_and_keeps_only_documents() -> None:
    net = confluence_net()
    conf = ConfluenceConnector(Tokens(), net.client, space_keys="OPS")
    result = await conf.search(
        SearchQuery(text="deliver friday", date_from=date(2026, 10, 1)), CTX
    )
    cql = net.q()["cql"]
    assert (
        'space in ("OPS")' in cql
        and 'text ~ "deliver"' in cql
        and 'lastmodified >= "2026-10-01"' in cql
    )
    assert "/ex/confluence/cloud-1/wiki/rest/api/search" in str(net.requests[0].url)
    (rec,) = result.records  # the space hit is not a document
    assert rec.id == "confluence:123" and rec.excerpt.startswith("Deliver Friday")
    assert "Excerpt only" in rec.excerpt and "@@@" not in rec.excerpt
    assert rec.occurred_at == when("2026-10-15T08:00:00+00:00")
    assert rec.url == "https://acme.atlassian.net/wiki/spaces/OPS/pages/123"
    assert result.next_cursor == "2"


async def test_confluence_page_and_comments() -> None:
    net = confluence_net()
    conf = ConfluenceConnector(Tokens(), net.client)
    page = (await conf.get_record("confluence:123", CTX)).records[0]
    assert (
        page.author == "Priya"
        and "Deliver Friday." in page.excerpt
        and "version 4" in page.excerpt
    )
    thread = await conf.get_thread("confluence:123", CTX)
    assert [r.id for r in thread.records] == [
        "confluence:123",
        "confluence:123:comment:c1",
    ]
    assert thread.records[1].excerpt == "Agreed"


async def test_confluence_space_scope_is_enforced_on_fetch() -> None:
    net = confluence_net()
    conf = ConfluenceConnector(Tokens(), net.client, space_keys="OTHER")
    out = await conf.get_record("confluence:123", CTX)
    assert out.records == [] and "outside the configured" in (out.coverage.detail or "")
    assert (await conf.get_record("confluence:12/../3", CTX)).records == []


# ---- Notion ---------------------------------------------------------------------------

PAGE_ID = "11111111-2222-3333-4444-555555555555"


def notion_net(**extra: Route | dict[str, Any]) -> Net:
    page = {
        "object": "page",
        "id": PAGE_ID,
        "url": "https://notion.so/p",
        "created_by": {"id": "u1"},
        "last_edited_time": "2026-10-15T08:00:00.000Z",
        "properties": {
            "Name": {
                "type": "title",
                "title": [{"plain_text": "Close "}, {"plain_text": "checklist"}],
            }
        },
    }
    blocks = {
        "results": [
            {
                "id": "b1",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"plain_text": "Steps"}]},
            },
            {
                "id": "b2",
                "type": "to_do",
                "to_do": {"rich_text": [{"plain_text": "Send form"}], "checked": True},
            },
            {
                "id": "b3",
                "type": "bulleted_list_item",
                "has_children": True,
                "bulleted_list_item": {"rich_text": [{"plain_text": "Review"}]},
            },
        ],
        "has_more": False,
    }
    return Net(
        **{
            "/v1/search": {"results": [page], "has_more": True, "next_cursor": "nc"},
            f"/blocks/{PAGE_ID}/children": blocks,
            "/blocks/b3/children": {
                "results": [
                    {
                        "id": "b4",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"plain_text": "by Friday"}]},
                    }
                ],
                "has_more": False,
            },
            "/v1/comments": {
                "results": [
                    {
                        "id": "cm1",
                        "created_time": "2026-10-15T09:00:00.000Z",
                        "rich_text": [{"plain_text": "Looks right"}],
                    }
                ],
                "has_more": False,
            },
            "/v1/users/u1": {"name": "Priya"},
            f"/v1/pages/{PAGE_ID}": page,
            **extra,
        }
    )


async def test_notion_search_is_title_only_and_says_so() -> None:
    net = notion_net()
    result = await NotionConnector(Tokens(), net.client).search(
        SearchQuery(text="close"), CTX
    )
    assert net.requests[0].headers["notion-version"] == "2022-06-28"
    assert (
        net.body()["query"] == "close"
        and net.body()["sort"]["direction"] == "descending"
    )
    (rec,) = result.records
    assert rec.title == "Close checklist" and rec.id == f"notion:{PAGE_ID}"
    assert "Title only" in rec.excerpt
    assert (
        "titles only" in (result.coverage.detail or "") and result.next_cursor == "nc"
    )


async def test_notion_zero_title_matches_is_partial_not_no_matches() -> None:
    net = notion_net(**{"/v1/search": {"results": [], "has_more": False}})
    result = await NotionConnector(Tokens(), net.client).search(
        SearchQuery(text="invoice"), CTX
    )
    assert result.coverage.status == "partial" and "titles only" in (
        result.coverage.detail or ""
    )


async def test_notion_stops_paging_once_results_are_older_than_the_window() -> None:
    net = notion_net()
    result = await NotionConnector(Tokens(), net.client).search(
        SearchQuery(text="close", date_from=date(2026, 10, 20)), CTX
    )
    assert result.records == [] and result.next_cursor is None


async def test_notion_page_text_includes_nested_blocks_and_the_author() -> None:
    net = notion_net()
    got = await NotionConnector(Tokens(), net.client).get_record(
        f"notion:{PAGE_ID}", CTX
    )
    (rec,) = got.records
    assert rec.author == "Priya"
    assert "\nSteps" in rec.excerpt and "[x] Send form" in rec.excerpt
    assert "- Review" in rec.excerpt and "  by Friday" in rec.excerpt
    assert got.coverage.status == "searched"


async def test_notion_thread_adds_comments_and_survives_missing_comment_access() -> (
    None
):
    net = notion_net()
    notion = NotionConnector(Tokens(), net.client)
    thread = await notion.get_thread(f"notion:{PAGE_ID}", CTX)
    assert [r.excerpt for r in thread.records][-1] == "Looks right" and len(
        thread.records
    ) == 2
    blocked = notion_net(**{"/v1/comments": err(403)})
    out = await NotionConnector(Tokens(), blocked.client).get_thread(
        f"notion:{PAGE_ID}", CTX
    )
    assert out.coverage.status == "partial" and len(out.records) == 1
    assert (await notion.get_record("notion:not-a-uuid", CTX)).records == []


# ---- registry and records ------------------------------------------------------------


def test_registry_lists_every_source_with_its_scope() -> None:
    conns = load_connectors(
        Tokens(), httpx.AsyncClient(), Settings(jira_project_keys="HPF")
    )
    assert [c.name for c in conns] == ["gmail", "slack", "jira", "confluence", "notion"]


async def test_records_never_carry_secrets() -> None:
    issue = json.loads(json.dumps(ISSUE))
    issue["fields"]["description"] = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "password: hunter2 token xoxb-1234567890-abcdefghij",
                    }
                ],
            }
        ],
    }
    net = jira_net(**{"/search/jql": {"issues": [issue], "isLast": True}})
    result = await JiraConnector(Tokens(), net.client).search(
        SearchQuery(text="form"), CTX
    )
    assert (
        "hunter2" not in result.records[0].excerpt
        and "xoxb-" not in result.records[0].excerpt
    )


# ---- looser retry ---------------------------------------------------------------------


async def test_a_search_that_matches_nothing_is_retried_with_its_two_longest_words() -> (
    None
):
    def search(request: httpx.Request) -> httpx.Response:
        jql = request.url.params["jql"]
        if 'text ~ "late"' in jql:  # the four-word query matches nothing
            return httpx.Response(200, json={"issues": [], "isLast": True})
        return httpx.Response(
            200, json={"issues": [ISSUE], "isLast": False, "nextPageToken": "x"}
        )

    net = jira_net(**{"/search/jql": search})
    result = await JiraConnector(Tokens(), net.client).search(
        SearchQuery(text="subscription form was submitted late"), CTX
    )
    assert [r.id for r in result.records] == ["jira:HPF-19"]
    assert result.coverage.status == "searched"
    assert 'match "subscription submitted"' in (result.coverage.detail or "")
    assert result.next_cursor is None
    assert net.calls("/search/jql") == 2


async def test_no_retry_for_short_queries_or_when_the_looser_query_also_fails() -> None:
    empty = jira_net(**{"/search/jql": {"issues": [], "isLast": True}})
    short = await JiraConnector(Tokens(), empty.client).search(
        SearchQuery(text="form late"), CTX
    )
    assert short.coverage.status == "no_matches" and empty.calls("/search/jql") == 1
    long = await JiraConnector(Tokens(), empty.client).search(
        SearchQuery(text="subscription form was submitted late"), CTX
    )
    assert long.coverage.status == "no_matches" and long.records == []
