"""Wording the product must not put in front of a customer, or assert as fact, in English
and Vietnamese. One table, used by the validation checks, the customer-draft checks and
the chat answer checks, so the sets cannot drift apart."""

from __future__ import annotations

import re

_W = r"(?<!\w)"
_E = r"(?!\w)"

BLAME = re.compile(
    r"\b(at fault|fault|blame[ds]?|negligen\w*|careless\w*|"
    r"(?:responsible|accountable) for (?:the )?(?:delay|failure|error|mistake|issue)|"
    r"caused by)\b"
    r"|lỗi của|đổ lỗi|chịu trách nhiệm|do (?:phía|bên) (?:khách hàng|chúng tôi|họ)"
    r"|tại (?:phía|bên) (?:khách hàng|chúng tôi|họ)|sơ suất|cẩu thả",
    re.IGNORECASE,
)

PROMISE = re.compile(
    r"\b(guarantee[ds]?|we promise|will be (?:ready|delivered|completed|fixed|resolved) by)\b"
    rf"|{_W}(?:cam kết|đảm bảo|bảo đảm|chắc chắn sẽ|xin hứa|hứa sẽ){_E}"
    rf"|{_W}sẽ (?:hoàn thành|hoàn tiền|giao|xử lý xong|sửa xong) (?:trước|vào|chậm nhất){_E}",
    re.IGNORECASE,
)

INTERNAL = re.compile(
    r"internal[- ]only|\[internal\]|do not share|confidential"
    rf"|{_W}(?:nội bộ|không chia sẻ|bảo mật|tuyệt mật){_E}",
    re.IGNORECASE,
)

# `<PERSON_3>`: a placeholder the model was given for a real value. One left in text a
# person reads means a value was not restored.
PLACEHOLDER = re.compile(r"<(?:PERSON|EMAIL|PHONE|IBAN|ACCT|TAXID)_\d+>")
