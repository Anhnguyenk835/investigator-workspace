"""What a model's text may contain when a person's browser renders it.

A markdown image is fetched by the browser the moment it is shown, so its address is a
channel for carrying data out. A link takes a click. Neither is wanted in an investigation
answer unless it points at something the model was actually given. Everything here is
text-in, text-out and deterministic.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

SAFE_SCHEMES = {"http", "https"}
# Pages of the connected tools: a link to one of these (without a query) is not a channel.
DEFAULT_LINK_HOSTS = (
    "mail.google.com",
    "docs.google.com",
    "drive.google.com",
    ".slack.com",
    ".atlassian.net",
    "atlassian.com",
    "notion.so",
    ".notion.so",
    ".notion.site",
)

_BAD_TAGS = (
    "script|style|iframe|object|embed|img|image|a|form|input|button|svg|link|meta|base|"
    "video|audio|source|math|frame|frameset|textarea|select|details"
)
_URL = r"[^\s<>()\[\]\"']+"

TOKEN = re.compile(
    rf"""
    (?P<image>!\[(?P<ialt>[^\]\n]*)\]\((?P<iurl>(?:[^()\n]|\([^()\n]*\))*)\))
  | (?P<imageref>!\[(?P<iralt>[^\]\n]*)\]\[[^\]\n]*\])
  | (?P<link>\[(?P<ltext>[^\]\n]+)\]\(\s*<?(?P<lurl>(?:[^()\s>]|\([^()\s>]*\))*)>?(?:\s+"[^"\n]*")?\s*\))
  | (?P<refdef>^[ \t]{{0,3}}\[[^\]\n]+\]:[ \t]*<?\S+>?[^\n]*$)
  | (?P<html><!--.*?-->|</?(?:{_BAD_TAGS})\b[^>]*>)
  | (?P<autolink><(?P<aurl>[a-zA-Z][a-zA-Z0-9+.-]*:[^\s<>]*)>)
  | (?P<bare>\b(?:https?|ftp|javascript|data|vbscript|file):(?://)?{_URL})
    """,
    re.IGNORECASE | re.MULTILINE | re.DOTALL | re.VERBOSE,
)
TRAILING = ".,;:!?)\"'"
URL_IN_TEXT = re.compile(rf"https?://{_URL}", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    kind: str  # image | link | bare_url | html | scheme | reference
    detail: str = ""


@dataclass(frozen=True)
class UrlPolicy:
    """What a link may point at: addresses the model was given, and the connected tools."""

    allowed: frozenset[str] = frozenset()
    hosts: tuple[str, ...] = DEFAULT_LINK_HOSTS

    def permits(self, url: str) -> bool:
        url = url.strip()
        try:
            parts = urlsplit(url)
        except ValueError:
            return False
        if parts.scheme.lower() not in SAFE_SCHEMES or not parts.hostname:
            return False
        if url in self.allowed or url.rstrip(TRAILING) in self.allowed:
            return True
        if parts.query or parts.fragment or parts.username or parts.password:
            return False
        host = parts.hostname.lower()
        return any(
            host == h.lstrip(".") or (h.startswith(".") and host.endswith(h))
            for h in self.hosts
        )


def urls_in(texts: Iterable[str]) -> frozenset[str]:
    """Every web address written in `texts`: the ones the model may repeat."""
    found: set[str] = set()
    for t in texts:
        for m in URL_IN_TEXT.finditer(t):
            found.add(m.group().rstrip(TRAILING))
    return frozenset(found)


def sanitize(text: str, policy: UrlPolicy | None = None) -> tuple[str, list[Finding]]:
    """The text with images, unapproved links and HTML taken out; and what was taken."""
    pol = policy or UrlPolicy()
    found: list[Finding] = []

    def host_of(url: str) -> str:
        try:
            return urlsplit(url).hostname or url[:40]
        except ValueError:
            return url[:40]

    def repl(m: re.Match[str]) -> str:
        if m.group("image") is not None or m.group("imageref") is not None:
            found.append(Finding("image", host_of(m.group("iurl") or "")))
            return "[image removed]"
        if m.group("link") is not None:
            url = m.group("lurl")
            if pol.permits(url):
                return m.group()
            found.append(
                Finding(
                    "scheme"
                    if urlsplit(url).scheme.lower() not in SAFE_SCHEMES
                    else "link",
                    host_of(url),
                )
            )
            return m.group("ltext")
        if m.group("refdef") is not None:
            found.append(Finding("reference"))
            return ""
        if m.group("html") is not None:
            found.append(Finding("html", m.group()[:30]))
            return ""
        if m.group("autolink") is not None:
            url = m.group("aurl")
            if pol.permits(url):
                return m.group()
            found.append(Finding("link", host_of(url)))
            return "[link removed]"
        url = m.group("bare")
        core = url.rstrip(TRAILING)
        tail = url[len(core) :]
        if pol.permits(core):
            return m.group()
        found.append(Finding("bare_url", host_of(core)))
        return "[link removed]" + tail

    out = TOKEN.sub(repl, text)
    return out, found
