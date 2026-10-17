"""Finds text that is written to instruct an AI rather than to inform a person.

Pure code. A rule scores how sure it is; text scoring HIGH or more is cut out of what the
model reads, and text in the band below is left to a cheap classifier. The rules are about
form (an imperative aimed at "you", the assistant, the system prompt), not topic, and cover
English and Vietnamese. A customer writing "please ignore my previous email" is not aimed at
an AI and must not trip them; the tests keep a list of such sentences.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass

HIGH = 0.75
LOW = 0.4
MAX_SPAN = 400
_B64 = re.compile(r"(?<![\w/+=-])[A-Za-z0-9+/]{40,}={0,2}(?![\w/+=-])")

# Characters that render as nothing but can carry text a model still reads.
HIDDEN = re.compile(
    r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]"
)


@dataclass(frozen=True)
class Hit:
    start: int
    end: int
    rule: str
    score: float


_R = re.IGNORECASE
RULES: list[tuple[str, float, re.Pattern[str]]] = [
    (
        "override",
        0.9,
        re.compile(
            r"\b(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}?"
            r"\b(?:previous|prior|above|earlier|all|any|your|the|these|those|system)\b[^.\n]{0,30}?"
            r"\b(?:instructions?|prompts?|rules?|guidelines?|directions?|constraints?|programming)\b",
            _R,
        ),
    ),
    (
        "override_vi",
        0.9,
        re.compile(
            r"(?:bỏ qua|phớt lờ|quên|vượt qua)\s+(?:hết\s+|tất cả\s+)?(?:các\s+|mọi\s+)?"
            r"(?:hướng dẫn|chỉ dẫn|chỉ thị|quy tắc|quy định|lệnh)",
            _R,
        ),
    ),
    (
        "role_reset",
        0.8,
        re.compile(
            r"\byou are (?:now|no longer) (?:an?|my|free|unrestricted|unbound|bound|restricted|in|able|going to|DAN)\b"
            r"|\bfrom now on,? (?:you|act|behave|respond)\b"
            r"|\bact as (?:an?|the) (?:unrestricted|different|new|ai|assistant|chatbot|jailbroken|evil|uncensored|hacker|dan)\b"
            r"|\bact as if you (?:have no|are not|were not)\b|\bpretend (?:to be|you are|that you)\b"
            r"|\bnew (?:instructions?|rules?|task)\s*:|\byour (?:new|real|true) (?:task|role|goal|instructions?)\b"
            r"|\bswitch to (?:developer|debug|admin|god|dan|jailbreak|unrestricted) mode\b|\bjailbreak\b|\bDAN mode\b",
            _R,
        ),
    ),
    (
        "role_reset_vi",
        0.8,
        re.compile(
            r"từ (?:bây giờ|nay)\s*,?\s*(?:bạn|em|anh|chị|hãy)\b|bạn (?:bây giờ )?là\s+(?:một\s+)?(?:trợ lý|AI|chatbot)"
            r"|hãy đóng vai|nhiệm vụ mới của bạn",
            _R,
        ),
    ),
    (
        "reveal_prompt",
        0.9,
        re.compile(
            r"\b(?:reveal|repeat|print|show|output|display|leak|tell me|disclose)\b[^.\n]{0,30}?"
            r"\b(?:system prompt|your (?:instructions|prompt|rules|configuration)|hidden (?:instructions|prompt)|"
            r"initial prompt|the prompt above)\b",
            _R,
        ),
    ),
    (
        "reveal_prompt_vi",
        0.9,
        re.compile(
            r"(?:tiết lộ|in ra|hiển thị|lặp lại|cho tôi xem)[^.\n]{0,25}?"
            r"(?:system prompt|hướng dẫn của bạn|chỉ dẫn của bạn|lời nhắc hệ thống)",
            _R,
        ),
    ),
    (
        "secrecy",
        0.8,
        re.compile(
            r"\bdo not (?:tell|inform|mention (?:this )?to|reveal (?:this )?to|alert|notify) the "
            r"(?:user|human|operator|reviewer|customer success)\b|\bwithout (?:telling|informing) the (?:user|human|reviewer)\b"
            r"|đừng nói (?:với|cho) (?:người dùng|người xem|người duyệt)|không được (?:cho|nói với) (?:người dùng|người duyệt)",
            _R,
        ),
    ),
    (
        "chat_markup",
        0.95,
        re.compile(
            r"<\|(?:im_start|im_end|system|user|assistant|endoftext)\|>|\[/?INST\]|<</?SYS>>"
            r"|###\s*(?:Instruction|System|Response)\b|<\s*/?\s*(?:system|assistant|developer)\s*>",
            _R,
        ),
    ),
    (
        "role_line",
        0.5,
        re.compile(
            r"^[ \t]*(?:system|assistant|developer)[ \t]*:[ \t]*\S", _R | re.MULTILINE
        ),
    ),
    (
        "tag_lookalike",
        0.9,
        re.compile(
            r"<\s*/?\s*(?:record|untrusted[\w-]*|user-input|derived-notes|tool_?results?)\b",
            _R,
        ),
    ),
    (
        "tool_imitation",
        0.8,
        re.compile(
            r""""(?:tool_calls?|function_call|tool_call_id)"\s*:"""
            r"""|\b(?:call|invoke|use|run) (?:the )?(?:tool|function) [`"']?\w+[`"']? with\b"""
            r"|\b(?:search_records|get_record|get_thread)\s*\(",
            _R,
        ),
    ),
    (
        "exfiltrate",
        0.8,
        re.compile(
            r"\b(?:send|post|forward|email|upload|submit|exfiltrate|leak)\b[^.\n]{0,60}?"
            r"(?:\bto\b[^.\n]{0,20})?(?:https?://|\bthis (?:url|link|address|webhook)\b|\bthe (?:url|link|webhook)\b)"
            r"|!\[[^\]\n]*\]\(https?://[^)\s]*\?[^)]*\)",
            _R,
        ),
    ),
    (
        "addresses_model",
        0.45,
        re.compile(
            r"\b(?:dear |hey |hi |note to )?(?:ai assistant|assistant|language model|llm|chatbot|claude|chatgpt|gpt-?\d?)\s*[,:]\s*"
            r"(?:you|please|do|don'?t|always|never|ignore|disregard|make sure)\b",
            _R,
        ),
    ),
    (
        "must_not_cite",
        0.45,
        re.compile(
            r"\b(?:do not|don'?t|never) (?:cite|mention|include|report|flag) (?:this|these|any)\b[^.\n]{0,40}"
            r"\b(?:record|email|message|finding|evidence|source)s?\b",
            _R,
        ),
    ),
    (
        "encoded_payload",
        0.4,
        re.compile(r"(?<![\w/+=-])[A-Za-z0-9+/]{120,}={0,2}(?![\w/+=-])"),
    ),
]


def strip_hidden(text: str) -> tuple[str, list[int]]:
    """`text` without invisible characters, and for each kept character its index in `text`."""
    if not HIDDEN.search(text):
        return text, list(range(len(text)))
    kept: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if not HIDDEN.match(ch):
            kept.append(ch)
            index.append(i)
    return "".join(kept), index


_END = re.compile(r"[.!?](?=\s|$)")


def _sentence(text: str, start: int, end: int) -> tuple[int, int]:
    """The passage to cut for a match: from the start of its sentence to the end of its
    paragraph. An instruction rarely stops at the first full stop ("Ignore the above. Say X.")
    and a full stop inside an address ("evil.example") is not the end of a sentence."""
    lo = 0
    for m in _END.finditer(text, 0, start):
        lo = m.end()
    lo = max(
        text.rfind("\n", 0, start) + 1 if text.rfind("\n", 0, start) > lo else lo,
        start - MAX_SPAN // 2,
    )
    para = text.find("\n\n", end)
    hi = len(text) if para < 0 else para
    hi = min(hi, end + MAX_SPAN)
    while lo < start and text[lo].isspace():
        lo += 1
    return lo, hi


def _decoded_hits(text: str) -> list[Hit]:
    """Instructions hidden in a base64 blob: decode it and read what it says."""
    out: list[Hit] = []
    for m in _B64.finditer(text):
        blob = m.group()
        try:
            raw = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True)
            decoded = raw.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if sum(c.isprintable() or c.isspace() for c in decoded) < 0.9 * len(decoded):
            continue
        if any(h.score >= HIGH for h in scan(decoded, expand=False, decode=False)):
            out.append(Hit(m.start(), m.end(), "encoded_instruction", 0.9))
    return out


def scan(text: str, *, expand: bool = True, decode: bool = True) -> list[Hit]:
    """Every instruction-like passage in `text`, merged where they overlap."""
    raw: list[Hit] = []
    for rule, score, pattern in RULES:
        for m in pattern.finditer(text):
            lo, hi = (
                _sentence(text, m.start(), m.end()) if expand else (m.start(), m.end())
            )
            raw.append(Hit(lo, hi, rule, score))
    if decode:
        raw += _decoded_hits(text)
    if not raw:
        return []
    raw.sort(key=lambda h: (h.start, -h.end))
    merged: list[Hit] = []
    for h in raw:
        if merged and h.start <= merged[-1].end:
            prev = merged[-1]
            best = prev if prev.score >= h.score else h
            merged[-1] = Hit(prev.start, max(prev.end, h.end), best.rule, best.score)
        else:
            merged.append(h)
    return merged


def verdict(hits: list[Hit]) -> tuple[list[Hit], list[Hit]]:
    """(clear instructions, uncertain ones)."""
    return [h for h in hits if h.score >= HIGH], [
        h for h in hits if LOW <= h.score < HIGH
    ]
