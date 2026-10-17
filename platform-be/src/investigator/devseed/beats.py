"""A story is a list of beats. A beat says who does what, with the facts that must appear in
the words; the words themselves are written later (compose.py), so two seeds give two
differently worded, equally true, versions of the same story."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

Source = Literal["email", "slack", "jira", "confluence"]


@dataclass
class Attach:
    name: str
    kind: Literal["pdf", "csv", "txt", "docx"]
    title: str = ""
    lines: list[str] = field(default_factory=list)  # the document's text, one line each


@dataclass
class Beat:
    id: str
    source: Source
    thread: str  # an email thread, a Slack conversation, a Jira issue or a page
    actor: str  # person key
    intent: str  # what this message does, in plain words
    must: list[str] = field(default_factory=list)  # strings that must appear verbatim
    day: float | None = (
        None  # days BEFORE now it happened; None means "when it is posted"
    )
    to: list[str] = field(default_factory=list)  # email recipients (person keys)
    cc: list[str] = field(default_factory=list)
    subject: str = ""
    reply_to: str = ""  # beat id this answers (email reply / Slack thread)
    channel: str = ""  # slack channel key
    # jira
    action: Literal["create", "comment", "transition", "page"] = "create"
    project: str = ""
    issue_type: str = ""
    to_status: str = ""
    labels: list[str] = field(default_factory=list)
    space: str = ""
    attach: list[Attach] = field(default_factory=list)
    length: Literal["short", "medium", "long"] = "medium"
    adversarial: str = (
        ""  # text a third party planted that must appear verbatim in the body
    )
    quote: bool = False  # an email reply carries the message it answers, quoted
    language: str = ""  # "", "vi" or "mixed"
    # filled in by compose / post
    text: str = ""
    title: str = ""
    at: str = ""  # ISO time for a backdated beat


@dataclass
class Fact:
    """Ground truth about the story, for scoring what an investigation finds."""

    kind: Literal["event", "commitment", "root_cause", "conflict", "status", "trap"]
    statement: str
    who: str = ""
    due: str = ""
    met: bool | None = None  # for a commitment: was it kept?
    where: list[str] = field(default_factory=list)  # beat ids that show it


@dataclass
class Story:
    id: str
    customer: str  # org key
    title: str
    summary: str  # neutral, for the writer's context
    question: str  # what a person would ask the investigator
    span_days: int  # how long ago it began
    channels: list[str]  # slack channel keys it uses
    beats: list[Beat]
    facts: list[Fact]
    labels: list[str] = field(default_factory=list)  # jira labels
    spaces: list[str] = field(default_factory=list)


def at(now: datetime, days_ago: float, hour: float) -> datetime:
    """`days_ago` days before `now`, at `hour` local-ish (UTC-based, only for ordering)."""
    base = (now - timedelta(days=days_ago)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (base + timedelta(hours=hour)).astimezone(UTC)
