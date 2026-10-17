"""Applies `sanitize` to text that arrives in pieces.

A markdown image or link can be split across pieces, so the gate holds back the start of
anything that might become one until it can tell, then lets the checked text through.
Cutting the same text at any point gives the same output."""

from __future__ import annotations

import re

from investigator.guardrails.output.sanitize import Finding, UrlPolicy, sanitize

# Longest a pending construct is held before it is treated as ordinary text.
HOLD_LIMIT = 800
_BARE_START = re.compile(r"(?i)(?:https?|ftp|javascript|data|vbscript|file):")
_PARTIAL_SCHEME = re.compile(
    r"(?i)(?:h|ht|htt|http|https|f|ft|ftp|j|ja|jav|java|javas|javasc|javascr|javascri|javascrip|javascript|d|da|dat|data|v|vb|vbs|vbsc|vbscr|vbscri|vbscrip|vbscript|fi|fil|file)$"
)


class StreamGate:
    def __init__(self, policy: UrlPolicy | None = None) -> None:
        self._policy = policy
        self._buf = ""
        self._line_start = True  # the held text begins a line
        self.findings: list[Finding] = []

    def feed(self, piece: str) -> str:
        self._buf += piece
        cut = self._safe_end(self._buf, self._line_start)
        if cut <= 0:
            return ""
        ready, self._buf = self._buf[:cut], self._buf[cut:]
        return self._clean(ready)

    def flush(self) -> str:
        ready, self._buf = self._buf, ""
        return self._clean(ready)

    def _clean(self, ready: str) -> str:
        # A sentinel stops "start of line" matching where the text only begins mid-line.
        sentinel = not self._line_start
        clean, found = sanitize(("\x00" if sentinel else "") + ready, self._policy)
        self.findings += found
        if ready:
            self._line_start = ready.endswith("\n")
        return clean[1:] if sentinel and clean.startswith("\x00") else clean

    @staticmethod
    def _safe_end(buf: str, line_start: bool = True) -> int:
        """How much of `buf` cannot be part of a construct that is still open."""
        n = len(buf)
        i = 0
        while i < n:
            c = buf[i]
            start = i
            if c == "!" and i + 1 >= n:
                return start  # may become an image
            if c == "!" and buf[i + 1] == "[":
                end = _close_bracket(buf, i + 1, line_start)
                if end is None:
                    return start if n - start < HOLD_LIMIT else n
                i = end
                continue
            if c == "[":
                end = _close_bracket(buf, i, line_start)
                if end is None:
                    return start if n - start < HOLD_LIMIT else n
                i = end
                continue
            if c == "<":
                close = buf.find(">", i)
                if close == -1:
                    return start if n - start < HOLD_LIMIT else n
                i = close + 1
                continue
            if (
                c in "hHfFjJdDvV"
                and (m := _PARTIAL_SCHEME.match(buf, i, n))
                and m.end() == n
            ):
                return start  # may be the start of a scheme: wait for the next piece
            if c in "hHfFjJdDvV" and (m := _BARE_START.match(buf, i)):
                j = m.end()
                while j < n and not buf[j].isspace() and buf[j] not in "<>()[]\"'":
                    j += 1
                if j >= n:
                    return start if n - start < HOLD_LIMIT else n
                i = j
                continue
            i += 1
        return n


def _close_bracket(buf: str, i: int, line_start: bool) -> int | None:
    """Index just past a `[...]` construct beginning at `i`, or None if not yet decidable."""
    n = len(buf)
    close = buf.find("]", i)
    if close == -1:
        return None
    nxt = close + 1
    if nxt >= n:
        return None  # `[text]` might still become `[text](url)`
    if buf[nxt] == "(":
        depth = 0
        for j in range(nxt, n):
            depth += (buf[j] == "(") - (buf[j] == ")")
            if depth == 0:
                return j + 1
            if buf[j] == "\n":
                return j  # a link cannot span lines: not one
        return None
    if buf[nxt] == "[":
        end = buf.find("]", nxt)
        return None if end == -1 else end + 1
    if buf[nxt] == ":" and ((i == 0 and line_start) or (i > 0 and buf[i - 1] == "\n")):
        end = buf.find("\n", nxt)
        return None if end == -1 else end + 1
    return nxt
