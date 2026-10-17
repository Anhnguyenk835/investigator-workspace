"""Writes the plan into the real systems. Everything it creates is marked so it can be found
and removed: mail carries an `X-Investigator-Seed` header, Slack channels a purpose marker,
Jira issues a `seed-<run>` label, Confluence one space.

Limits of the platforms, stated plainly: mail can be dated in the past; Slack messages, Jira
issues and Confluence pages are stamped with the time they are written, so a story's backdated
history is email, and its live part (chat, tickets, pages) is posted in story order today."""

from __future__ import annotations

import html
import imaplib
import re
import time
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime, formataddr
from typing import Any

import httpx

from investigator.devseed.attachments import build
from investigator.devseed.beats import Beat, Story
from investigator.devseed.cast import World

PURPOSE_MARK = "[investigator-seed]"
JIRA_PH = re.compile(r"\{jira:([\w-]+)\}")
EMOJI = [
    ":man-office-worker:",
    ":woman-office-worker:",
    ":technologist:",
    ":female-technologist:",
    ":man-raising-hand:",
    ":woman-raising-hand:",
    ":briefcase:",
    ":lawyer:" if False else ":scales:",
    ":bank:",
    ":chart_with_upwards_trend:",
]


def emoji_for(key: str) -> str:
    return EMOJI[sum(map(ord, key)) % len(EMOJI)]


class Poster:
    """Holds the connections. `dry` records what would be written and writes nothing."""

    def __init__(self, world: World, run: str, *, dry: bool = False) -> None:
        self.w = world
        self.run = run
        self.dry = dry
        self.jira_keys: dict[str, str] = {}
        self.slack_ts: dict[str, str] = {}
        self.channels: dict[str, str] = {}
        self.msg_ids: dict[str, str] = {}  # beat id -> Message-ID
        self.thread_refs: dict[str, list[str]] = {}
        self.done: dict[str, str] = {}
        self.counts: dict[str, int] = {
            "email": 0,
            "slack": 0,
            "jira": 0,
            "confluence": 0,
        }
        self._imap: imaplib.IMAP4_SSL | None = None
        self._imap_at = 0.0
        self.google_account = ""
        self._token_fn: Any = None
        self.slack_http: httpx.Client | None = None
        self.jira_http: httpx.Client | None = None
        self.space_id = ""
        self.errors: list[str] = []

    # ---- connections ---------------------------------------------------------------

    def connect(
        self,
        *,
        slack_token: str,
        jira_base: str,
        jira_auth: tuple[str, str],
        google: tuple[str, Any],
    ) -> None:
        self.slack_http = httpx.Client(
            base_url="https://slack.com/api/",
            headers={"Authorization": f"Bearer {slack_token}"},
            timeout=30,
        )
        self.jira_http = httpx.Client(
            base_url=jira_base.rstrip("/"), auth=jira_auth, timeout=60
        )
        self.google_account, self._token_fn = google

    def mailbox(self) -> imaplib.IMAP4_SSL:
        if self._imap is not None and time.monotonic() - self._imap_at < 900:
            return self._imap
        if self._imap is not None:
            try:
                self._imap.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
        auth = f"user={self.google_account}\x01auth=Bearer {self._token_fn()}\x01\x01"
        m = imaplib.IMAP4_SSL("imap.gmail.com")
        m.authenticate("XOAUTH2", lambda _: auth.encode())
        m.create('"casefile-mock"')
        self._imap, self._imap_at = m, time.monotonic()
        return m

    def close(self) -> None:
        if self._imap is not None:
            try:
                self._imap.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
        for c in (self.slack_http, self.jira_http):
            if c is not None:
                c.close()

    # ---- text helpers --------------------------------------------------------------

    def fill(self, text: str) -> str:
        return JIRA_PH.sub(
            lambda m: self.jira_keys.get(m.group(1), "the Jira ticket"), text
        )

    def signature(self, key: str) -> str:
        p = self.w.p(key)
        org = next((o for o in self.w.orgs.values() if o.name == p.org), None)
        lines = ["--", p.name, f"{p.title} | {p.org}"]
        if (
            p.phone
            and p.side != "third_party"
            or p.role in ("counsel", "administrator")
        ):
            lines.append(f"T {p.phone}")
        lines.append(p.email)
        if org is not None and org.disclaimer:
            lines += ["", org.disclaimer]
        return "\n".join(lines)

    # ---- email ---------------------------------------------------------------------

    def email(self, story: Story, b: Beat, when: datetime) -> str:
        p = self.w.p(b.actor)
        body = self.fill(b.text)
        if b.quote and b.reply_to and b.reply_to in self.msg_ids:
            prior = next((x for x in story.beats if x.id == b.reply_to), None)
            if prior is not None:
                quoted = "\n".join(
                    "> " + ln for ln in self.fill(prior.text).splitlines()
                )
                who = self.w.p(prior.actor)
                body += f"\n\nOn {prior_date(self, prior)}, {who.name} <{who.email}> wrote:\n{quoted}"
        msg = EmailMessage()
        msg["From"] = formataddr((p.name, p.email))
        msg["To"] = ", ".join(
            formataddr((self.w.p(k).name, self.w.p(k).email)) for k in b.to
        )
        if b.cc:
            msg["Cc"] = ", ".join(
                formataddr((self.w.p(k).name, self.w.p(k).email)) for k in b.cc
            )
        subject = b.subject or next(
            (x.subject for x in story.beats if x.thread == b.thread and x.subject),
            "(no subject)",
        )
        if b.reply_to and not subject.lower().startswith("re:"):
            subject = "RE: " + subject
        msg["Subject"] = subject
        msg["Date"] = format_datetime(when)
        mid = f"<{b.id}.{self.run}@seed.investigator.example>"
        msg["Message-ID"] = mid
        refs = self.thread_refs.setdefault(b.thread, [])
        if refs:
            msg["In-Reply-To"] = refs[-1]
            msg["References"] = " ".join(refs[-6:])
        msg["X-Investigator-Seed"] = self.run
        msg.set_content(f"{body}\n\n{self.signature(b.actor)}\n")
        for a in b.attach:
            data, main, sub = build(a)
            msg.add_attachment(data, maintype=main, subtype=sub, filename=a.name)
        if not self.dry:
            m = self.mailbox()
            status, detail = m.append(
                '"casefile-mock"',
                "(\\Seen)",
                imaplib.Time2Internaldate(when),
                msg.as_bytes(),
            )
            if status != "OK":
                raise RuntimeError(f"IMAP append failed: {detail}")
        refs.append(mid)
        self.msg_ids[b.id] = mid
        self.counts["email"] += 1
        return mid

    # ---- slack ---------------------------------------------------------------------

    def _slack(self, method: str, **data: Any) -> dict[str, Any]:
        assert self.slack_http is not None
        for _ in range(6):
            r = self.slack_http.post(method, data=data)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", "2")) + 0.5)
                continue
            body: dict[str, Any] = r.json()
            return body
        raise RuntimeError(f"Slack kept rate-limiting {method}")

    def channel(self, name: str) -> str:
        if name in self.channels:
            return self.channels[name]
        if self.dry:
            self.channels[name] = f"C{abs(hash(name)) % 10**9:09d}"
            return self.channels[name]
        made = self._slack("conversations.create", name=name, is_private="false")
        if made.get("ok"):
            cid = made["channel"]["id"]
            self._slack(
                "conversations.setPurpose",
                channel=cid,
                purpose=f"{PURPOSE_MARK} run {self.run}",
            )
        elif made.get("error") == "name_taken":
            cid = ""
            cursor = ""
            while not cid:
                page = self._slack(
                    "conversations.list",
                    types="public_channel",
                    limit="200",
                    exclude_archived="true",
                    cursor=cursor,
                )
                for ch in page.get("channels", []):
                    if ch["name"] == name:
                        if PURPOSE_MARK not in (ch.get("purpose") or {}).get(
                            "value", ""
                        ):
                            raise RuntimeError(
                                f"#{name} exists and was not made by the seeder; rename or archive it"
                            )
                        cid = ch["id"]
                cursor = (page.get("response_metadata") or {}).get("next_cursor", "")
                if not cursor:
                    break
            if not cid:
                raise RuntimeError(f"#{name} exists but cannot be found")
        else:
            raise RuntimeError(f"conversations.create {name}: {made.get('error')}")
        self._slack("conversations.join", channel=cid)
        self.channels[name] = cid
        return str(cid)

    def slack(self, story: Story, b: Beat) -> None:
        p = self.w.p(b.actor)
        data: dict[str, Any] = {
            "channel": self.channel(b.channel),
            "text": self.fill(b.text),
            "username": p.name,
            "icon_emoji": emoji_for(b.actor),
        }
        parent = self.slack_ts.get(b.reply_to) if b.reply_to else None
        if parent:
            data["thread_ts"] = parent
        if self.dry:
            self.slack_ts[b.id] = f"{time.time():.6f}"
        else:
            res = self._slack("chat.postMessage", **data)
            if not res.get("ok"):
                raise RuntimeError(f"chat.postMessage: {res.get('error')}")
            self.slack_ts[b.id] = res["ts"]
        self.counts["slack"] += 1

    # ---- jira ----------------------------------------------------------------------

    def _jira(
        self, method: str, path: str, **kw: Any
    ) -> httpx.Response:  # also used for Confluence
        assert self.jira_http is not None
        for _ in range(6):
            r = self.jira_http.request(method, path, **kw)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", "3")) + 0.5)
                continue
            return r
        raise RuntimeError("Jira kept rate-limiting")

    @staticmethod
    def adf(text: str) -> dict[str, Any]:
        paras = [pp for pp in re.split(r"\n{2,}", text.strip()) if pp.strip()] or [
            text or " "
        ]
        return {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": para}]}
                for para in paras
            ],
        }

    def ensure_project(self, key: str, name: str) -> None:
        if self.dry:
            return
        if self._jira("GET", f"/rest/api/3/project/{key}").status_code == 200:
            return
        me = self._jira("GET", "/rest/api/3/myself").json()
        r = self._jira(
            "POST",
            "/rest/api/3/project",
            json={
                "key": key,
                "name": name,
                "projectTypeKey": "software",
                "projectTemplateKey": "com.pyxis.greenhopper.jira:gh-simplified-agility-kanban",
                "leadAccountId": me["accountId"],
                "assigneeType": "UNASSIGNED",
            },
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(
                f"cannot create Jira project {key}: {r.status_code} {r.text[:200]}"
            )

    def jira(self, story: Story, b: Beat) -> None:
        p = self.w.p(b.actor)
        by = f"[{p.name} - {p.title}, {p.org}]"
        if b.action == "create":
            labels = sorted(
                {*b.labels, *story.labels, f"seed-{self.run}", "investigator-seed"}
            )
            issue_type = b.issue_type or "Task"
            fields: dict[str, Any] = {
                "project": {"key": b.project},
                "issuetype": {"name": b.issue_type or "Task"},
                "summary": self.fill(b.title)[:240],
                "description": self.adf(f"{by}\n\n{self.fill(b.text)}"),
                "labels": labels,
            }
            if self.dry:
                key = f"{b.project}-{len(self.jira_keys) + 1}"
            else:
                r = self._jira("POST", "/rest/api/3/issue", json={"fields": fields})
                if r.status_code == 400 and issue_type != "Task":
                    fields["issuetype"] = {"name": "Task"}
                    r = self._jira("POST", "/rest/api/3/issue", json={"fields": fields})
                if r.status_code not in (200, 201):
                    raise RuntimeError(f"create issue: {r.status_code} {r.text[:200]}")
                key = r.json()["key"]
            self.jira_keys[b.thread] = key
        else:
            key = self.jira_keys.get(b.thread, "")
            if not key:
                raise RuntimeError(f"no issue yet for {b.thread}")
            if b.action == "comment":
                if not self.dry:
                    r = self._jira(
                        "POST",
                        f"/rest/api/3/issue/{key}/comment",
                        json={"body": self.adf(f"{by}\n\n{self.fill(b.text)}")},
                    )
                    if r.status_code not in (200, 201):
                        raise RuntimeError(f"comment: {r.status_code} {r.text[:200]}")
            elif b.action == "transition" and not self.dry:
                listing = self._jira(
                    "GET", f"/rest/api/3/issue/{key}/transitions"
                ).json()["transitions"]
                match = next(
                    (
                        t
                        for t in listing
                        if t["to"]["name"].lower() == b.to_status.lower()
                    ),
                    None,
                )
                if match is None:
                    raise RuntimeError(f"{key}: no transition to {b.to_status}")
                self._jira(
                    "POST",
                    f"/rest/api/3/issue/{key}/transitions",
                    json={"transition": {"id": match["id"]}},
                ).raise_for_status()
        self.counts["jira"] += 1

    # ---- confluence ----------------------------------------------------------------

    def ensure_space(self, key: str, name: str) -> None:
        if self.dry:
            self.space_id = "0"
            return
        r = self._jira("GET", "/wiki/api/v2/spaces", params={"keys": key})
        found = r.json().get("results", []) if r.status_code == 200 else []
        if not found:
            made = self._jira(
                "POST",
                "/wiki/rest/api/space",
                json={
                    "key": key,
                    "name": name,
                    "description": {
                        "plain": {
                            "value": f"{PURPOSE_MARK} run {self.run}",
                            "representation": "plain",
                        }
                    },
                },
            )
            if made.status_code not in (200, 201):
                raise RuntimeError(
                    f"cannot create Confluence space: {made.status_code} {made.text[:200]}"
                )
            r = self._jira("GET", "/wiki/api/v2/spaces", params={"keys": key})
            found = r.json()["results"]
        self.space_id = found[0]["id"]

    @staticmethod
    def storage(md: str) -> str:
        out: list[str] = []
        in_list = False
        for raw in md.splitlines():
            line = raw.rstrip()
            m = re.match(r"^(#{1,4})\s+(.*)", line)
            li = re.match(r"^\s*[-*]\s+(.*)", line)
            if li:
                if not in_list:
                    out.append("<ul>")
                    in_list = True
                out.append(f"<li>{inline(li.group(1))}</li>")
                continue
            if in_list:
                out.append("</ul>")
                in_list = False
            if m:
                n = len(m.group(1))
                out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
            elif line.strip():
                out.append(f"<p>{inline(line)}</p>")
        if in_list:
            out.append("</ul>")
        return "".join(out) or "<p></p>"

    def page(self, story: Story, b: Beat) -> None:
        p = self.w.p(b.actor)
        body = (
            f"<p><em>Author: {html.escape(p.name)}, {html.escape(p.title)}</em></p>"
            + self.storage(self.fill(b.text))
        )
        if not self.dry:
            r = self._jira(
                "POST",
                "/wiki/api/v2/pages",
                json={
                    "spaceId": self.space_id,
                    "status": "current",
                    "title": b.title,
                    "body": {"representation": "storage", "value": body},
                },
            )
            if r.status_code not in (200, 201):
                raise RuntimeError(f"create page: {r.status_code} {r.text[:200]}")
        self.counts["confluence"] += 1

    # ---- dispatch ------------------------------------------------------------------

    def post(self, story: Story, b: Beat, when: datetime | None = None) -> None:
        if b.source == "email":
            self.email(story, b, when or datetime.now(UTC))
        elif b.source == "slack":
            self.slack(story, b)
        elif b.source == "jira":
            self.jira(story, b)
        else:
            self.page(story, b)


def inline(text: str) -> str:
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", t)


def prior_date(poster: Poster, prior: Beat) -> str:
    when = datetime.fromisoformat(prior.at) if prior.at else datetime.now(UTC)
    return f"{when:%a, %b} {when.day}, {when:%Y} at {when:%H:%M}"
