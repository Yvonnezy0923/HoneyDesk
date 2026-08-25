"""PII (Personally Identifiable Information) detection and sanitization module.

Detects buyers' PII in text content before it is written to long-term memory.
Supports detection, blocking, and sanitization/masking for GDPR compliance.

FR-ME-05: PII detection must be regex-based, fast, and configurable.
Detection is conservative: false positive is preferred over false negative.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Pattern


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PII_TYPES: list[str] = [
    "email",
    "phone",
    "address",
    "ssn",
    "passport",
    "id_card",
    "credit_card",
    "bank_account",
    "personal_url",
    "ip_address",
    "full_name_context",
    "date_of_birth",
    "company_contact",
]

# ---------------------------------------------------------------------------
# PII regex patterns (conservative — favour false positive over false negative)
# ---------------------------------------------------------------------------

_PII_PATTERNS: dict[str, list[Pattern[str]]] = {
    # ── Email addresses ──────────────────────────────────────────────
    "email": [
        re.compile(
            r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9]"
            r"(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
            r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*"
            r"\.[a-zA-Z]{2,}",
            re.IGNORECASE,
        ),
    ],

    # ── Phone numbers ────────────────────────────────────────────────
    "phone": [
        # Chinese mobile: 1[3-9]\d{9} (MUST be before generic patterns to avoid false positives)
        re.compile(
            r"(?<!\d)1[3-9]\d{9}(?!\d)",
            re.IGNORECASE,
        ),
        # Chinese landline: 0\d{2,3}-?\d{7,8}
        re.compile(
            r"(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)",
            re.IGNORECASE,
        ),
        # US-style: (XXX) XXX-XXXX or XXX-XXX-XXXX
        re.compile(
            r"(?<!\d)\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?:\s*(?:ext|x|内线)\s*\d{1,5})?(?!\d)",
            re.IGNORECASE,
        ),
        # International: +<country><number> with optional separators
        # Requires + prefix (not 00) to avoid false positives with ID card numbers
        re.compile(
            r"(?<!\d)\+[1-9]\d{0,3}[-. (]?\d{1,6}[-. )]?\d{1,14}(?:[\s.-]?\d{1,13})*",
            re.IGNORECASE,
        ),
        # Generic loose number sequence that looks like a phone (>= 7 digits with common prefixes)
        re.compile(
            r"(?:\btel[.:]?\s*|phone[.:]?\s*|电话[：:]?\s*|手机[：:]?\s*|mobile[.:]?\s*)"
            r"[+\d\s\-()./]{7,20}",
            re.IGNORECASE,
        ),
    ],

    # ── Physical addresses ───────────────────────────────────────────
    "address": [
        # PO Box
        re.compile(
            r"\bP\.?\s*O\.?\s*Box\s+\d{1,10}\b",
            re.IGNORECASE,
        ),
        # Street / Road / Avenue / Lane / Drive patterns
        re.compile(
            r"\b\d{1,10}\s+[A-Za-z0-9\s.',-]+"
            r"(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|"
            r"Court|Ct|Place|Pl|Boulevard|Blvd|Way|Terrace|Ter|"
            r"Circle|Cir|Highway|Hwy|Parkway|Pkwy|"
            r"大楼|大厦|号|路|街|巷|弄|段|区|栋|室|楼)\b",
            re.IGNORECASE,
        ),
        # Chinese address prefixes: 地址/住址/收货地址 followed by content
        re.compile(
            r"(?:地址|住址|收货地址|通讯地址|邮寄地址)[：:]\s*.{5,100}",
            re.IGNORECASE,
        ),
        # English address context prefixes
        re.compile(
            r"(?:address|shipping address|billing address|mailing address|"
            r"located at|live at|residence)[:\s]+.{5,120}",
            re.IGNORECASE,
        ),
    ],

    # ── SSN (US Social Security Number) ──────────────────────────────
    "ssn": [
        re.compile(
            r"(?<!\d)(?!000|666|9\d{2})\d{3}[- ](?!00)\d{2}[- ](?!0000)\d{4}(?!\d)",
            re.IGNORECASE,
        ),
        # SSN with context prefix
        re.compile(
            r"(?:SSN|Social Security|社会安全号|社保号)[：:.\s]*"
            r"(?!000|666|9\d{2})\d{3}[- ](?!00)\d{2}[- ](?!0000)\d{4}",
            re.IGNORECASE,
        ),
    ],

    # ── Passport numbers ─────────────────────────────────────────────
    "passport": [
        # US passport: 9 digits
        re.compile(
            r"(?<!\d)\d{9}(?!\d)",
            re.IGNORECASE,
        ),
        # Generic passport: 1-2 letters followed by 5-9 digits (common format)
        # Also catches Chinese passport: E/G followed by 8 digits
        re.compile(
            r"(?<![a-zA-Z0-9])[A-Za-z]{1,2}\d{5,9}(?![a-zA-Z0-9])",
            re.IGNORECASE,
        ),
        # Passport context prefix
        re.compile(
            r"(?:护照|passport|travel document)[：:.\s]*[A-Za-z0-9]{5,12}",
            re.IGNORECASE,
        ),
    ],

    # ── Chinese ID card number (18 digits with optional X) ───────────
    "id_card": [
        # Strict 18-digit pattern with validation of first two digits (province code)
        # Use (?<!\d)/(?!\d) instead of \b because CJK characters are \w in Python
        re.compile(
            r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])"
            r"\d{3}[\dXx](?!\d)",
            re.IGNORECASE,
        ),
        # ID card context prefix — allow any non-digit between keyword and number
        re.compile(
            r"(?:身份证|ID card|身份证号|公民身份号码|居民身份证)"
            r"(?:[^0-9]*?)"
            r"[1-9]\d{5}\d{8}[\dXx]{4}",
            re.IGNORECASE,
        ),
    ],

    # ── Credit card numbers ──────────────────────────────────────────
    "credit_card": [
        # Visa: starts with 4, 13-16 digits
        re.compile(
            r"(?<!\d)4\d{3}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}(?:[- ]?\d{3})?(?!\d)",
            re.IGNORECASE,
        ),
        # Mastercard: starts with 51-55 or 2221-2720, 16 digits
        re.compile(
            r"(?<!\d)(?:5[1-5]\d{2}|2[2-7]\d{2})[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}(?!\d)",
            re.IGNORECASE,
        ),
        # American Express: starts with 34 or 37, 15 digits
        re.compile(
            r"(?<!\d)3[47]\d{2}[- ]?\d{6}[- ]?\d{5}(?!\d)",
            re.IGNORECASE,
        ),
        # Discover: starts with 6011, 622126-622925, 644-649, 65, 16-19 digits
        re.compile(
            r"(?<!\d)(?:6011|65\d{2}|64[4-9]\d)[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}(?:[- ]?\d{1,4})?(?!\d)",
            re.IGNORECASE,
        ),
        # Generic card number context prefix
        re.compile(
            r"(?:卡号|card number|credit card|银行卡|借记卡|信用卡)[：:.\s]*"
            r"\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}",
            re.IGNORECASE,
        ),
        # UnionPay: 62开头, 16-19 digits
        re.compile(
            r"(?<!\d)62\d{2}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}(?:[- ]?\d{0,4})?(?!\d)",
            re.IGNORECASE,
        ),
    ],

    # ── Bank account numbers ─────────────────────────────────────────
    "bank_account": [
        # Generic bank account: 8-17 digits with context
        re.compile(
            r"(?:账号|银行账号|account number|account no|bank account)[：:.\s]*"
            r"\d{6,20}",
            re.IGNORECASE,
        ),
        # Chinese bank card: 16-19 digits (also caught by credit_card patterns,
        # but the standalone 16-19 digit sequence is worth flagging)
        re.compile(
            r"(?<!\d)\d{16,19}(?!\d)",
            re.IGNORECASE,
        ),
        # Routing / sort code pattern
        re.compile(
            r"(?:routing number|sort code|swift code|BIC)[：:.\s]*[A-Za-z0-9]{6,11}",
            re.IGNORECASE,
        ),
    ],

    # ── URLs containing personal identifiers ─────────────────────────
    "personal_url": [
        # URLs with email-like user info
        re.compile(
            r"https?://[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            re.IGNORECASE,
        ),
        # URLs with personal query parameters (token, session, user_id, etc.)
        re.compile(
            r"https?://[^\s]+?"
            r"(?:token|session|api[_-]?key|secret|access[_-]?token|refresh[_-]?token|"
            r"user[_-]?id|account[_-]?id|customer[_-]?id|"
            r"password|passwd|auth|signature)[=:][^\s&]+",
            re.IGNORECASE,
        ),
    ],

    # ── IP addresses ─────────────────────────────────────────────────
    "ip_address": [
        # IPv4
        re.compile(
            r"(?<!\d)(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)(?!\d)",
            re.IGNORECASE,
        ),
        # IPv6 (simplified — catches common notation)
        re.compile(
            r"(?<![a-fA-F0-9])(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}(?![a-fA-F0-9])",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?<![a-fA-F0-9])(?:[0-9a-fA-F]{1,4}:){1,7}:?(?:[0-9a-fA-F]{1,4}:){1,7}[0-9a-fA-F]{1,4}(?![a-fA-F0-9])",
            re.IGNORECASE,
        ),
    ],

    # ── Full names via context patterns ──────────────────────────────
    "full_name_context": [
        re.compile(
            r"(?:my name is|my name's|I am|I'm|call me|name is|full name|"
            r"我叫|本人|我是|姓名|名字是|全名|联系方式|联系人)[：:.\s]+"
            r"[A-Za-z\u4e00-\u9fff]{2,30}(?:\s+[A-Za-z\u4e00-\u9fff]{1,30}){0,3}",
            re.IGNORECASE,
        ),
        # "姓 X, 名 Y" pattern
        re.compile(
            r"姓[：:.\s]*[\u4e00-\u9fff]{1,10}[，,]\s*名[：:.\s]*[\u4e00-\u9fff]{1,10}",
            re.IGNORECASE,
        ),
        # English salutation + full name (e.g., "Dear John Smith" at line start)
        re.compile(
            r"^(?:Dear|Hello|Hi|Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Prof\.?)"
            r"\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}",
            re.IGNORECASE,
        ),
    ],

    # ── Dates of birth ───────────────────────────────────────────────
    "date_of_birth": [
        # DOB context prefix
        re.compile(
            r"(?:DOB|date of birth|birth date|birthday|born on|"
            r"出生日期|生日|出生年月|出生)[：:.\s]*"
            r"\d{1,4}[-/年.]\s*\d{1,2}[-/月.]\s*\d{1,4}(?:[日号]|$|\s|,|\.)",
            re.IGNORECASE,
        ),
        # Standalone patterns that look like DOB (YYYY-MM-DD, YYYY/MM/DD, DD/MM/YYYY, etc.)
        # Only match if the year is plausible (1900-2010 for a living person)
        re.compile(
            r"(?<!\d)(?:19[0-9]\d|20[0-1]\d)[-/](?:0[1-9]|1[0-2])[-/](?:0[1-9]|[12]\d|3[01])(?!\d)",
            re.IGNORECASE,
        ),
        # DD/MM/YYYY or MM/DD/YYYY (conservative: catch both)
        re.compile(
            r"(?<!\d)(?:0[1-9]|[12]\d|3[01])[-/](?:0[1-9]|1[0-2])[-/](?:19[0-9]\d|20[0-1]\d)(?!\d)",
            re.IGNORECASE,
        ),
        # Chinese date format: YYYY年MM月DD日
        re.compile(
            r"(?<!\d)(?:19[0-9]\d|20[0-1]\d)年(?:0?[1-9]|1[0-2])月(?:0?[1-9]|[12]\d|3[01])[日号]?(?!\d)",
            re.IGNORECASE,
        ),
    ],

    # ── Company names with personal contact info ─────────────────────
    "company_contact": [
        # Company name + contact person pattern
        re.compile(
            r"(?:公司|company|firm|企业|单位|organization)[：:.\s]*"
            r".{1,50}?[，,]\s*(?:联系人|contact|tel|电话|手机|email|邮箱|地址)"
            r"[：:.\s]*[^\n]{5,60}",
            re.IGNORECASE,
        ),
        # Contact info section headers that typically contain PII
        re.compile(
            r"^(?:联系方式|contact|contact info|contact information|"
            r"personal info|个人信息|客户信息|buyer info)[：:.\s]*\n?.+",
            re.IGNORECASE | re.MULTILINE,
        ),
    ],
}


# ---------------------------------------------------------------------------
# Dataclass for detected PII items
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PIIMatch:
    """A single PII detection result."""

    type: str
    """PII type identifier (matches keys in _PII_TYPES)."""

    pattern: str
    """The regex pattern string that matched."""

    match: str
    """The actual matched text."""

    start: int
    """Start character index in the original text."""

    end: int
    """End character index (exclusive) in the original text."""

    confidence: float
    """Confidence score 0.0–1.0 (1.0 = high confidence)."""


# ---------------------------------------------------------------------------
# Thread-safe stats tracker
# ---------------------------------------------------------------------------

@dataclass
class _Stats:
    """In-memory thread-safe counters for PII detection operations."""

    total_checks: int = 0
    total_blocks: int = 0
    total_sanitizations: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def increment_checks(self, n: int = 1) -> None:
        with self._lock:
            self.total_checks += n

    def increment_blocks(self, n: int = 1) -> None:
        with self._lock:
            self.total_blocks += n

    def increment_sanitizations(self, n: int = 1) -> None:
        with self._lock:
            self.total_sanitizations += n

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "total_checks": self.total_checks,
                "total_blocks": self.total_blocks,
                "total_sanitizations": self.total_sanitizations,
            }


_stats = _Stats()

# ---------------------------------------------------------------------------
# Confidence tiers
# ---------------------------------------------------------------------------

_HIGH_CONFIDENCE_TYPES: frozenset[str] = frozenset({
    "email",
    "ssn",
    "credit_card",
    "id_card",
})

_MEDIUM_CONFIDENCE_TYPES: frozenset[str] = frozenset({
    "phone",
    "passport",
    "bank_account",
    "ip_address",
    "date_of_birth",
})

_LOW_CONFIDENCE_TYPES: frozenset[str] = frozenset({
    "address",
    "personal_url",
    "full_name_context",
    "company_contact",
})

_CONFIDENCE_MAP: dict[str, float] = {
    typ: 0.95 for typ in _HIGH_CONFIDENCE_TYPES
}
_CONFIDENCE_MAP.update({typ: 0.80 for typ in _MEDIUM_CONFIDENCE_TYPES})
_CONFIDENCE_MAP.update({typ: 0.60 for typ in _LOW_CONFIDENCE_TYPES})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_pii(text: str) -> list[dict]:
    """Scan *text* for PII and return a list of detection dicts.

    Each result dict contains:
        type (str)       — PII type identifier
        pattern (str)    — the regex pattern string that produced the match
        match (str)      — the matched text snippet
        start (int)      — start byte offset in *text*
        end (int)        — end byte offset (exclusive)
        confidence (float) — 0.0–1.0 confidence score

    Detection is conservative: false positives are preferred over false negatives.
    """
    _stats.increment_checks()
    results: list[dict] = []
    seen_ranges: set[tuple[int, int]] = set()

    for pii_type, patterns in _PII_PATTERNS.items():
        base_confidence = _CONFIDENCE_MAP.get(pii_type, 0.5)
        for pattern_obj in patterns:
            for match in pattern_obj.finditer(text):
                start, end = match.start(), match.end()
                # Deduplicate overlapping matches — keep the first one
                if _overlaps_any(start, end, seen_ranges):
                    continue
                seen_ranges.add((start, end))

                matched_text = match.group()
                results.append({
                    "type": pii_type,
                    "pattern": pattern_obj.pattern,
                    "match": matched_text,
                    "start": start,
                    "end": end,
                    "confidence": _adjust_confidence(base_confidence, matched_text, pii_type),
                })

    results.sort(key=lambda d: d["start"])
    return results


def has_pii(text: str) -> bool:
    """Return ``True`` if any PII is detected in *text*.

    Performs a quick scan and is slightly more efficient than calling
    ``detect_pii`` when only a boolean answer is needed.
    """
    _stats.increment_checks()
    for pii_type, patterns in _PII_PATTERNS.items():
        for pattern_obj in patterns:
            if pattern_obj.search(text):
                return True
    return False


def sanitize(text: str, mask_char: str = "*") -> str:
    """Replace all detected PII in *text* with masked characters.

    The *mask_char* controls the replacement character (default ``*``).
    Whitespace and structural separators (spaces, dashes, slashes, dots,
    parentheses) in the original match are preserved so that the general
    shape of the text remains readable while the actual values are hidden.

    Examples::

        >>> sanitize("Email: alice@example.com")
        'Email: ******@********.***'

        >>> sanitize("Phone: +86 138-0000-0000", mask_char="#")
        'Phone: +## ###-####-####'
    """
    matches = detect_pii(text)
    if not matches:
        return text

    _stats.increment_sanitizations(len(matches))

    # Build result by iterating over segments
    result_parts: list[str] = []
    cursor = 0
    for detection in matches:
        # Append text before this match
        result_parts.append(text[cursor: detection["start"]])
        # Append sanitized match
        result_parts.append(
            _sanitize_match(text[detection["start"]: detection["end"]], mask_char)
        )
        cursor = detection["end"]
    # Append remaining text after the last match
    result_parts.append(text[cursor:])
    return "".join(result_parts)


def get_pii_types() -> list[str]:
    """Return a copy of the list of all supported PII type identifiers."""
    return list(_PII_TYPES)


def add_custom_pattern(pii_type: str, pattern: str) -> None:
    """Register a custom regex *pattern* for the given *pii_type*.

    If *pii_type* is not already in ``_PII_TYPES`` it will be appended.
    The *pattern* string is compiled and added to the detection list.

    Args:
        pii_type: PII type identifier (e.g. ``"custom_token"``).
        pattern: A valid regular expression string.

    Raises:
        re.error: If *pattern* is not a valid regex.
    """
    compiled = re.compile(pattern, re.IGNORECASE)
    if pii_type not in _PII_PATTERNS:
        _PII_PATTERNS[pii_type] = []
    _PII_PATTERNS[pii_type].append(compiled)
    if pii_type not in _PII_TYPES:
        _PII_TYPES.append(pii_type)
    if pii_type not in _CONFIDENCE_MAP:
        _CONFIDENCE_MAP[pii_type] = 0.70


def stats() -> dict:
    """Return detection statistics as a dictionary.

    Returns:
        A dict with keys ``total_checks``, ``total_blocks``, and
        ``total_sanitizations`` reflecting cumulative counts.
    """
    return _stats.snapshot()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_WHITESPACE_PRESERVE_CHARS: frozenset[str] = frozenset(
    " \t\n\r\-/._:;,+()@"
)


def _sanitize_match(matched_text: str, mask_char: str) -> str:
    """Replace alphanumeric characters in *matched_text* with *mask_char*.

    Whitespace and common structural separators are preserved so the
    original formatting layout is maintained.
    """
    return "".join(
        ch if ch in _WHITESPACE_PRESERVE_CHARS else mask_char
        for ch in matched_text
    )


def _overlaps_any(start: int, end: int, ranges: set[tuple[int, int]]) -> bool:
    """Return ``True`` if the interval [start, end) overlaps any range in *ranges*."""
    for s, e in ranges:
        if start < e and end > s:
            return True
    return False


def _adjust_confidence(base: float, matched_text: str, pii_type: str) -> float:
    """Adjust confidence score based on context and match length.

    Boosts or reduces the *base* confidence slightly based on heuristics.
    """
    length = len(matched_text)
    # Very short matches are less reliable
    if length < 4:
        return max(0.3, base - 0.2)
    # Context-prefixed matches (longer patterns) are more reliable
    if length > 30:
        return min(1.0, base + 0.1)
    # For credit cards, a Luhn-valid-length match is a strong signal
    if pii_type == "credit_card":
        digits_only = re.sub(r"\D", "", matched_text)
        if 13 <= len(digits_only) <= 19:
            return min(1.0, base + 0.05)
    return base


# ---------------------------------------------------------------------------
# Module-level convenience: reset stats (useful for testing)
# ---------------------------------------------------------------------------

def _reset_stats() -> None:
    """Reset all detection counters to zero (testing helper)."""
    global _stats
    _stats = _Stats()