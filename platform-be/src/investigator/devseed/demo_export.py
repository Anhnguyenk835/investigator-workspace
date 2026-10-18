"""Turns a seeded plan into the stored demo: records, a directory, and the ground truth.

The live platforms stamp a Slack message or a ticket with the moment it is written, so on them a
story's chat and tickets all land on one day. A database holds any timestamp, so here every
record gets the time its story gives it: history over weeks, the escalation in the last day or
two. Same words, same people, same facts as the plan.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from random import Random
from typing import Any

from investigator.auth.access import SAMPLE_ID
from investigator.connectors.base import EvidenceRecord
from investigator.devseed.beats import Beat, Story
from investigator.devseed.cast import World
from investigator.directory import (
    Customer,
    Person,
    Project,
)

PLACEHOLDER = re.compile(r"\{jira:([\w-]+)\}")
SPACE = "SEEDKB"
LAST_HOURS = 30.0  # the live part of a story happens in this window before "now"


def channel_id(name: str) -> str:
    return (
        "CD" + hashlib.md5(name.encode(), usedforsecurity=False).hexdigest()[:9].upper()
    )


@dataclass
class DemoBuild:
    records: list[EvidenceRecord] = field(default_factory=list)
    customers: list[Customer] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)
    truth: list[dict[str, Any]] = field(default_factory=list)
    # (story id, customer id, project id, question, name), for running the sample investigations.
    samples: list[tuple[str, str, str, str, str]] = field(default_factory=list)


def _schedule(
    stories: list[Story], plan_now: datetime, now: datetime, rng: Random
) -> dict[str, datetime]:
    """A time for every beat. History keeps its date (moved forward by however long ago the
    plan was made); the live part is spread over the last day or so, in story order."""
    shift = now - plan_now
    when: dict[str, datetime] = {}
    for s in stories:
        last = None
        for b in s.beats:
            if b.day is not None and b.at:
                when[b.id] = datetime.fromisoformat(b.at) + shift
                last = max(last, when[b.id]) if last else when[b.id]
        live = [b for b in _live_order(s)]
        if not live:
            continue
        if s.id.startswith("noise"):
            for b in live:  # routine chatter and tickets: anywhere in the last month
                when[b.id] = now - timedelta(hours=rng.uniform(2, 24 * 30))
            continue
        start = max(
            (last or now - timedelta(hours=LAST_HOURS)) + timedelta(hours=1),
            now - timedelta(hours=LAST_HOURS),
        )
        end = now - timedelta(minutes=45)
        step = (end - start) / (len(live) + 1)
        for i, b in enumerate(live, 1):
            when[b.id] = start + step * i + timedelta(minutes=rng.uniform(-4, 4))
    return when


def _live_order(s: Story) -> list[Beat]:
    live = [b for b in s.beats if b.day is None]
    creates = [b for b in live if b.source == "jira" and b.action == "create"]
    return creates + [
        b for b in live if not (b.source == "jira" and b.action == "create")
    ]


def _wiki_pages(
    out: DemoBuild,
    world: World,
    groups: dict[str, list[dict[str, str]]],
    first: int,
    now: datetime,
    rng: Random,
) -> None:
    """Extra Confluence pages (written by `confluence-plan`), dated over the last weeks and
    authored by the internal team. Titles are unique, as Confluence requires."""
    staff = sorted(k for k, p in world.people.items() if p.side == "internal")
    if not staff:
        return
    seen = {r.title.lower() for r in out.records if r.source == "confluence"}
    n = first
    for group in sorted(groups):
        for page in groups[group]:
            title, k = page["title"].strip()[:250], 2
            while title.lower() in seen:
                title, k = f"{page['title'].strip()[:240]} ({k})", k + 1
            seen.add(title.lower())
            n += 1
            p = world.p(rng.choice(staff))
            rid = f"confluence:{9000 + n}"
            out.records.append(
                EvidenceRecord(
                    id=rid, source="confluence", title=title, author=p.name,
                    occurred_at=now - timedelta(hours=rng.uniform(3, 24 * 21)), timestamp_precision="exact",
                    excerpt=f"Author: {p.name}, {p.title}\n\n{page['markdown'].strip()}",
                    url=f"https://demo.atlassian.example/wiki/spaces/{SPACE}/pages/{9000 + n}",
                    thread_id=rid, meta={"space": SPACE},
                )
            )  # fmt: skip


def build(
    stories: list[Story],
    world: World,
    plan_now: datetime,
    now: datetime,
    seed: int = 7,
    extra_pages: dict[str, list[dict[str, str]]] | None = None,
) -> DemoBuild:
    rng = Random(seed)
    when = _schedule(stories, plan_now, now, rng)
    out = DemoBuild()
    keys: dict[str, str] = {}  # jira issue thread -> key
    counters: dict[str, int] = {}
    # Issue keys first, in the order the issues are created, so any message can name them.
    for s in stories:
        for b in sorted(
            (x for x in s.beats if x.source == "jira" and x.action == "create"),
            key=lambda x: when[x.id],
        ):
            counters[b.project] = counters.get(b.project, 0) + 1
            keys[b.thread] = f"{b.project}-{counters[b.project]}"

    def fill(text: str) -> str:
        return PLACEHOLDER.sub(lambda m: keys.get(m.group(1), "the Jira ticket"), text)

    person = world.p
    slack_ts: dict[str, str] = {}
    msg_ids: dict[str, str] = {}
    statuses: dict[str, str] = {}
    comment_n: dict[str, int] = {}
    pages = 0
    subject_of: dict[str, str] = {}
    for s in stories:
        for b in s.beats:
            if b.source == "email" and b.subject:
                subject_of.setdefault(b.thread, b.subject)

    for s in stories:
        slack_roots: dict[str, str] = {}
        for b in sorted(s.beats, key=lambda x: when[x.id]):
            at = when[b.id]
            p = person(b.actor)
            text = fill(b.text)
            if b.source == "email":
                subject = b.subject or subject_of.get(b.thread, "(no subject)")
                if b.reply_to and not subject.lower().startswith("re:"):
                    subject = "RE: " + subject
                recipients = [person(k).email for k in [*b.to, *b.cc]]
                names = [a.name for a in b.attach]
                header = [f"From: {p.name} <{p.email}>", f"Subject: {subject}"]
                if recipients:
                    header.append("To/Cc: " + ", ".join(recipients))
                if names:
                    header.append("Attachments: " + ", ".join(names))
                rid = f"gmail:{b.id}"
                msg_ids[b.id] = rid
                out.records.append(
                    EvidenceRecord(
                        id=rid, source="gmail", title=subject, author=p.name, author_id=p.email,
                        participants=recipients, occurred_at=at, timestamp_precision="exact",
                        excerpt="\n".join(header) + "\n\n" + text,
                        url=f"https://mail.google.com/mail/u/0/#all/{rid.split(':')[1]}",
                        thread_id=f"gmail:{b.thread}",
                    )
                )  # fmt: skip
                for n, a in enumerate(b.attach, 1):
                    body = "\n".join([a.title, *a.lines] if a.title else a.lines)
                    out.records.append(
                        EvidenceRecord(
                            id=f"{rid}:att:{n}", source="gmail", title=a.name, author=p.name, author_id=p.email,
                            participants=recipients, occurred_at=at, timestamp_precision="exact",
                            excerpt=f'Attachment "{a.name}" of the email "{subject}"\n\n{body}',
                            url=f"https://mail.google.com/mail/u/0/#all/{rid.split(':')[1]}",
                            thread_id=f"gmail:{b.thread}", meta={"kind": "attachment", "thread": "multi"},
                        )
                    )  # fmt: skip
            elif b.source == "slack":
                cid = channel_id(b.channel)
                ts = f"{at.timestamp():.6f}"
                root = slack_roots.get(b.reply_to) if b.reply_to else None
                thread_ts = root or ts
                slack_roots[b.id] = thread_ts
                slack_ts[b.id] = ts
                out.records.append(
                    EvidenceRecord(
                        id=f"slack:{cid}:{ts}", source="slack", title=f"#{b.channel}", author=p.name,
                        occurred_at=at, timestamp_precision="exact", excerpt=text,
                        url=f"https://demo.slack.example/archives/{cid}/p{ts.replace('.', '')}",
                        thread_id=f"slack:{cid}:{thread_ts}",
                        meta={"channel": cid, "thread": "multi" if root or any(x.reply_to == b.id for x in s.beats) else "single"},
                    )
                )  # fmt: skip
            elif b.source == "jira":
                key = keys[b.thread]
                labels = sorted(
                    {*b.labels, *s.labels, "investigator-seed"} - {"investigator-seed"}
                )
                meta = {
                    "jira_key": key,
                    "labels": ",".join(labels or [x for x in s.labels]),
                }
                if b.action == "create":
                    statuses[key] = "To Do"
                    lines = [
                        f"{key}: {b.title}",
                        f"Type: {b.issue_type or 'Task'}",
                        "Status: To Do",
                        f"Reporter: {p.name}",
                    ]
                    if labels:
                        lines.append("Labels: " + ", ".join(labels))
                    out.records.append(
                        EvidenceRecord(
                            id=f"jira:{key}", source="jira", title=f"{key}: {b.title}", author=p.name,
                            occurred_at=at, timestamp_precision="exact", excerpt="\n".join([*lines, "", text]),
                            url=f"https://demo.atlassian.example/browse/{key}", thread_id=f"jira:{key}", meta=meta,
                        )
                    )  # fmt: skip
                elif b.action == "comment":
                    comment_n[key] = comment_n.get(key, 0) + 1
                    out.records.append(
                        EvidenceRecord(
                            id=f"jira:{key}:comment:{comment_n[key]}", source="jira", title=f"{key}: comment",
                            author=p.name, occurred_at=at, timestamp_precision="exact", excerpt=text,
                            url=f"https://demo.atlassian.example/browse/{key}", thread_id=f"jira:{key}", meta=meta,
                        )
                    )  # fmt: skip
                else:
                    before = statuses.get(key, "To Do")
                    statuses[key] = b.to_status
                    comment_n[key] = comment_n.get(key, 0) + 1
                    out.records.append(
                        EvidenceRecord(
                            id=f"jira:{key}:change:{comment_n[key]}", source="jira", title=f"{key}: status changed",
                            author=p.name, occurred_at=at, timestamp_precision="exact",
                            excerpt=f"{key}: status {before} → {b.to_status}",
                            url=f"https://demo.atlassian.example/browse/{key}", thread_id=f"jira:{key}", meta=meta,
                        )
                    )  # fmt: skip
            else:
                pages += 1
                out.records.append(
                    EvidenceRecord(
                        id=f"confluence:{9000 + pages}", source="confluence", title=b.title, author=p.name,
                        occurred_at=at, timestamp_precision="exact",
                        excerpt=f"Author: {p.name}, {p.title}\n\n{text}",
                        url=f"https://demo.atlassian.example/wiki/spaces/{SPACE}/pages/{9000 + pages}",
                        thread_id=f"confluence:{9000 + pages}", meta={"space": b.space or SPACE},
                    )
                )  # fmt: skip
    _wiki_pages(out, world, extra_pages or {}, pages, now, rng)
    out.records.sort(key=lambda r: r.occurred_at or now)

    # Directory: who the customers, projects and people are. The demo's is shared and read-only.
    cust_ids: dict[str, str] = {}
    for s in stories:
        if not s.facts:
            continue
        org = world.orgs[s.customer]
        if s.customer not in cust_ids:
            cust_ids[s.customer] = f"cus_demo_{s.customer}"
            out.customers.append(
                Customer(
                    id=cust_ids[s.customer],
                    name=org.name,
                    aliases=[org.name.split()[0]],
                    email_domains=[org.domain],
                )
            )
        channels = [channel_id(c) for c in s.channels]
        pid = f"pro_demo_{s.id}"
        out.projects.append(
            Project(
                id=pid, name=f"{org.name} - {s.title}", customer_id=cust_ids[s.customer], aliases=[s.id],
                jira_labels=s.labels, slack_channel_ids=channels,
            )
        )  # fmt: skip
        out.samples.append(
            (
                s.id,
                cust_ids[s.customer],
                pid,
                s.question,
                f"{org.name}: {s.title}"[:120],
            )
        )
        out.truth.append({"id": s.id, "customer": s.customer, "title": s.title, "question": s.question,
                          "facts": [f.__dict__ for f in s.facts]})  # fmt: skip
    for key, p in world.people.items():
        if p.role == "vendor":
            continue
        org_key = next((k for k, o in world.orgs.items() if o.name == p.org), None)
        out.people.append(
            Person(
                id=f"per_demo_{key}", name=p.name, aliases=list(p.aliases), emails=[p.email], side=p.side,  # type: ignore[arg-type]
                role=p.role, customer_id=cust_ids.get(org_key or "") if p.side == "customer" else None,
            )
        )  # fmt: skip
    return out


_ = SAMPLE_ID
