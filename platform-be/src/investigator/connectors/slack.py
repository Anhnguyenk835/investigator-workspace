"""Slack, read-only. With a user token that has `search:read`, search.messages
finds messages across everything that person can read. Without it (a bot token,
or the scope missing) the connector scans the channels the token belongs to,
which is slower and says so when it could not look at everything."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import httpx

from investigator.connectors.base import EvidenceRecord, SearchQuery, SearchResult
from investigator.connectors.support import (
    PAGE_SIZE,
    LiveConnector,
    SourceDenied,
    SourceHttpError,
    done,
    in_bounds,
    narrowed,
    padded,
    record,
    scoped,
    search_terms,
    window_bounds,
)
from investigator.integrations import TokenProvider
from investigator.tools import AccessContext

NAME = "slack"
API = "https://slack.com/api"
CHANNEL = re.compile(r"^[CGD][A-Z0-9]{6,}$")
TS = re.compile(r"^\d{9,11}\.\d{3,6}$")
# Joins, topic changes and pins are Slack announcing something, not people talking.
CONVERSATION = {None, "bot_message", "thread_broadcast", "file_share", "me_message"}
DENIED = {
    "invalid_auth",
    "token_revoked",
    "account_inactive",
    "not_authed",
    "token_expired",
}
NO_SEARCH = {"missing_scope", "not_allowed_token_type"}
MENTION = re.compile(r"<@([A-Z0-9]+)(?:\|([^>]*))?>")
LINK = re.compile(r"<(https?://[^|>]+)(?:\|([^>]+))?>")
CHANNEL_REF = re.compile(r"<#([A-Z0-9]+)(?:\|([^>]*))?>")
HISTORY_PAGES = 5  # per channel and call, 200 messages each
CHANNELS_PER_CALL = 8
MAX_NAME_LOOKUPS = 15


def message_ts(ts: str) -> datetime:
    return datetime.fromtimestamp(float(ts), UTC)


class SlackConnector(LiveConnector):
    name = NAME
    provider = "slack"
    label = "Slack"

    def __init__(
        self, tokens: TokenProvider, http: httpx.AsyncClient, *, channel_ids: str = ""
    ) -> None:
        super().__init__(tokens, http)
        self._channels = scoped(channel_ids)
        for c in self._channels:
            if not CHANNEL.match(c):
                raise ValueError(f"{c!r} is not a Slack channel id")
        self._scan_only: set[str] = set()  # users whose token cannot search
        self._channel_cache: dict[str, str] = {}

    def _allowed(self, ctx: AccessContext) -> frozenset[str]:
        """Channels the case may read: this server's limit and the case's mapping together."""
        f = self.case_filter(ctx)
        return narrowed(self._channels, f.channels if f else [])

    # ---- API ------------------------------------------------------------------------

    async def _call(
        self, method: str, token: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Slack answers 200 with ok=false on most failures."""
        data: dict[str, Any] = await self._get(f"{API}/{method}", token, params)
        if not data.get("ok"):
            code = str(data.get("error") or "unknown_error")
            if code in DENIED:
                raise SourceDenied(
                    f"Slack rejected the token ({code}); connect it again."
                )
            if code == "ratelimited":
                raise SourceHttpError(429)
            raise SourceHttpError(400, code=code)
        return data

    async def _names(self, token: str, ids: set[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for uid in sorted(ids)[:MAX_NAME_LOOKUPS]:
            try:
                info = (await self._call("users.info", token, {"user": uid}))["user"]
            except (SourceHttpError, KeyError):
                continue  # a missing name is not worth failing a search for
            out[uid] = (
                info.get("real_name")
                or (info.get("profile") or {}).get("display_name")
                or info.get("name")
                or uid
            )
        return out

    def _render(self, text: str, names: dict[str, str]) -> str:
        text = MENTION.sub(
            lambda m: "@" + (names.get(m.group(1)) or m.group(2) or m.group(1)), text
        )
        text = CHANNEL_REF.sub(lambda m: "#" + (m.group(2) or m.group(1)), text)
        text = LINK.sub(lambda m: m.group(2) or m.group(1), text)
        return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")

    def _record(
        self,
        channel: str,
        channel_name: str | None,
        msg: dict[str, Any],
        names: dict[str, str],
    ) -> EvidenceRecord:
        ts = str(msg["ts"])
        uid = msg.get("user")
        author = names.get(uid or "") or msg.get("username") or uid or msg.get("bot_id")
        files = [f.get("name") for f in msg.get("files", []) if f.get("name")]
        text = self._render(msg.get("text") or "", names)
        if files:
            text += "\nAttachments: " + ", ".join(files)
        thread = msg.get("thread_ts") or ts
        return record(
            id=f"{NAME}:{channel}:{ts}",
            source=NAME,
            title=f"#{channel_name or channel}",
            author=author,
            author_id=uid if isinstance(uid, str) else None,
            meta={
                "channel": channel,
                # A message with no replies and not itself a reply has no thread to read.
                "thread": "multi"
                if (msg.get("reply_count") or msg.get("thread_ts") not in (None, ts))
                else "single",
            },
            occurred_at=message_ts(ts),
            timestamp_precision="exact",
            excerpt=text,
            url=f"https://slack.com/archives/{channel}/p{ts.replace('.', '')}"
            + (f"?thread_ts={thread}" if thread != ts else ""),
            thread_id=f"{NAME}:{channel}:{thread}",
        )

    async def _channel_names(self, token: str, ids: set[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for cid in sorted(ids)[:MAX_NAME_LOOKUPS]:
            if cid in self._channel_cache:
                out[cid] = self._channel_cache[cid]
                continue
            try:
                info = (
                    await self._call("conversations.info", token, {"channel": cid})
                )["channel"]
            except (SourceHttpError, KeyError):
                continue
            if info.get("name"):
                out[cid] = self._channel_cache[cid] = info["name"]
        return out

    async def _records(
        self, token: str, found: list[tuple[str, str | None, dict[str, Any]]]
    ) -> list[EvidenceRecord]:
        wanted = {
            u
            for _, _, m in found
            for u in [m.get("user"), *MENTION.findall(m.get("text") or "")]
            if isinstance(u, str) and u
        }
        wanted |= {
            u for _, _, m in found for u, _ in MENTION.findall(m.get("text") or "")
        }
        names = await self._names(
            token, {u for u in wanted if re.fullmatch(r"[A-Z0-9]+", u)}
        )
        unnamed = {c for c, n, _ in found if not n}
        channel_names = await self._channel_names(token, unnamed) if unnamed else {}
        return [
            self._record(c, n or channel_names.get(c), m, names) for c, n, m in found
        ]

    # ---- search ---------------------------------------------------------------------

    async def _search(
        self, token: str, query: SearchQuery, ctx: AccessContext
    ) -> SearchResult:
        allowed = self._allowed(ctx)
        f = self.case_filter(ctx)
        note = (
            "No Slack channel is mapped to this case, so the search was not narrowed."
            if f is not None and f.is_empty()
            else None
        )
        if f is not None and f.channels and self._channels and not allowed:
            return done(
                NAME,
                [],
                detail="The channels mapped to this case are outside the channels this server may read.",
            )
        scanning = ctx.user_id in self._scan_only or (query.cursor or "").startswith(
            "scan:"
        )
        if not scanning:
            try:
                return await self._api_search(token, query, allowed, note)
            except SourceHttpError as exc:
                if exc.code not in NO_SEARCH:
                    raise
                self._scan_only.add(ctx.user_id)
        return await self._scan(token, query, allowed, note)

    async def _api_search(
        self, token: str, query: SearchQuery, allowed: frozenset[str], note: str | None
    ) -> SearchResult:
        terms = list(search_terms(query.text))
        if query.date_from:
            terms.append(f"after:{padded(query.date_from, -1):%Y-%m-%d}")
        if query.date_to:
            terms.append(f"before:{padded(query.date_to, 1):%Y-%m-%d}")
        page = int(query.cursor.removeprefix("page:")) if query.cursor else 1
        data = await self._call(
            "search.messages",
            token,
            {
                "query": " ".join(terms),
                "count": PAGE_SIZE,
                "page": page,
                "sort": "timestamp",
                "sort_dir": "desc",
            },
        )
        block = data.get("messages", {})
        bounds = window_bounds(query)
        found = [
            (m["channel"]["id"], m["channel"].get("name"), m)
            for m in block.get("matches", [])
            if (not allowed or m["channel"]["id"] in allowed)
            and in_bounds(message_ts(str(m["ts"])), bounds)
        ]
        more = page < int(block.get("paging", {}).get("pages", 1))
        return done(
            NAME,
            await self._records(token, found),
            f"page:{page + 1}" if more else None,
        )

    async def _channel_list(
        self, token: str, allowed: frozenset[str]
    ) -> list[tuple[str, str | None]]:
        if allowed:
            return [(c, None) for c in sorted(allowed)]
        out: list[tuple[str, str | None]] = []
        cursor = ""
        types = "public_channel,private_channel"
        for _ in range(5):
            try:
                data = await self._call(
                    "users.conversations",
                    token,
                    {
                        "types": types,
                        "exclude_archived": "true",
                        "limit": 200,
                        "cursor": cursor,
                    },
                )
            except SourceHttpError as exc:
                # A token without the private-channel scope can still list public ones.
                if exc.code == "missing_scope" and types != "public_channel":
                    types = "public_channel"
                    continue
                raise
            out += [(c["id"], c.get("name")) for c in data.get("channels", [])]
            cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break
        return sorted(out)

    async def _history(
        self, token: str, channel: str, query: SearchQuery, terms: list[str]
    ) -> tuple[list[dict[str, Any]], bool]:
        """Matching messages of one channel inside the window, and whether it was cut short."""
        start, end = window_bounds(query)
        params: dict[str, Any] = {"channel": channel, "limit": 200}
        if start:
            params["oldest"] = f"{start.timestamp():.6f}"
        if end:
            params["latest"] = f"{end.timestamp():.6f}"
        hits: list[dict[str, Any]] = []
        for _ in range(HISTORY_PAGES):
            data = await self._call("conversations.history", token, params)
            for m in data.get("messages", []):
                text = (m.get("text") or "").lower()
                if m.get("subtype") in CONVERSATION and all(
                    t.lower() in text for t in terms
                ):
                    hits.append(m)
            cursor = (data.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                return hits, False
            params["cursor"] = cursor
        return hits, True

    async def _scan(
        self, token: str, query: SearchQuery, allowed: frozenset[str], note: str | None
    ) -> SearchResult:
        channels = await self._channel_list(token, allowed)
        cursor = query.cursor or ""
        index = int(cursor.removeprefix("scan:")) if cursor.startswith("scan:") else 0
        terms = search_terms(query.text)
        found: list[tuple[str, str | None, dict[str, Any]]] = []
        cut: list[str] = []
        unreadable: list[str] = []
        looked = 0
        while (
            index < len(channels)
            and looked < CHANNELS_PER_CALL
            and len(found) < PAGE_SIZE
        ):
            channel, name = channels[index]
            index += 1
            looked += 1
            try:
                hits, truncated = await self._history(token, channel, query, terms)
            except SourceHttpError as exc:
                if exc.code in {"not_in_channel", "channel_not_found"}:
                    unreadable.append(name or channel)
                    continue
                raise
            if truncated:
                cut.append(name or channel)
            found += [(channel, name, m) for m in hits]
        found = found[:PAGE_SIZE]
        notes = [note] if note else []
        if cut:
            notes.append("only the newest messages were read in " + ", ".join(cut))
        if unreadable:
            notes.append("not a member of " + ", ".join(unreadable))
        more = f"scan:{index}" if index < len(channels) else None
        return done(
            NAME,
            await self._records(token, found),
            more,
            detail="; ".join(notes) or None,
            partial=bool(cut or unreadable),
        )

    async def _suggest(self, token: str, ctx: AccessContext) -> list[dict[str, str]]:
        return [
            {"id": c, "label": f"#{n}" if n else c}
            for c, n in await self._channel_list(token, frozenset())
        ]

    # ---- by id ----------------------------------------------------------------------

    def _split(self, ident: str, ctx: AccessContext) -> tuple[str, str] | None:
        parts = ident.removeprefix(f"{NAME}:").split(":")
        if len(parts) != 2 or not CHANNEL.match(parts[0]) or not TS.match(parts[1]):
            return None
        allowed = self._allowed(ctx)
        if allowed and parts[0] not in allowed:
            return None
        return parts[0], parts[1]

    async def _get_thread(
        self, token: str, thread_id: str, ctx: AccessContext
    ) -> SearchResult:
        pair = self._split(thread_id, ctx)
        if pair is None:
            return done(NAME, [], detail=f"{thread_id} is not a readable Slack thread.")
        channel, ts = pair
        messages: list[dict[str, Any]] = []
        params: dict[str, Any] = {"channel": channel, "ts": ts, "limit": 200}
        for _ in range(HISTORY_PAGES):
            data = await self._call("conversations.replies", token, params)
            messages += data.get("messages", [])
            cursor = (data.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
            params["cursor"] = cursor
        else:
            cursor = "more"
        found: list[tuple[str, str | None, dict[str, Any]]] = [
            (channel, None, m) for m in messages if m.get("subtype") in CONVERSATION
        ]
        return done(
            NAME,
            await self._records(token, found),
            partial=bool(cursor),
            detail="The thread is longer than was read." if cursor else None,
        )

    async def _get_record(
        self, token: str, record_id: str, ctx: AccessContext
    ) -> SearchResult:
        pair = self._split(record_id, ctx)
        if pair is None:
            return done(
                NAME, [], detail=f"{record_id} is not a readable Slack message."
            )
        channel, ts = pair
        data = await self._call(
            "conversations.history",
            token,
            {
                "channel": channel,
                "oldest": ts,
                "latest": ts,
                "inclusive": "true",
                "limit": 1,
            },
        )
        messages = [m for m in data.get("messages", []) if str(m.get("ts")) == ts]
        if not messages:
            # Thread replies are not in channel history; the thread call finds them.
            return done(
                NAME,
                [],
                detail="Not in channel history; it may be a thread reply (use get_thread).",
                partial=True,
            )
        return done(NAME, await self._records(token, [(channel, None, messages[0])]))
