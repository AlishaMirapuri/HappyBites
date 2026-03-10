"""Canonicalization functions for price, schedule, deal type and text.

All functions are pure (no side-effects, no DB access) and importable
independently for unit testing.
"""

from __future__ import annotations

import html as html_lib
import re
import unicodedata

# ── Currency ──────────────────────────────────────────────────────────────────

_CURRENCY_SYMBOLS: dict[str, str] = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
}


def detect_currency(text: str) -> str:
    """Return the ISO-4217 code for the first currency symbol found."""
    for sym, code in _CURRENCY_SYMBOLS.items():
        if sym in text:
            return code
    return "USD"


# ── Price ─────────────────────────────────────────────────────────────────────

_FREE_PAT = re.compile(
    r"\b(?:free|complimentary|on\s+the\s+house|no\s+charge|gratis)\b",
    re.IGNORECASE,
)

# "under $10", "less than 10 dollars", "up to $15", "max $20"
_UNDER_PAT = re.compile(
    r"\b(?:under|less\s+than|up\s+to|below|max\.?|no\s+more\s+than)\s*"
    r"[$€£¥]?\s*(\d{1,6}(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:dollars?|bucks?|usd|eur|gbp)?",
    re.IGNORECASE,
)

# Explicit currency-led range: "$8-$12", "$8 to $12", "$8–$18"
# Negative lookahead prevents matching time ranges like "5-7pm"
_RANGE_DOLLAR_PAT = re.compile(
    r"[$€£¥]\s*(\d{1,6}(?:,\d{3})*(?:\.\d{1,2})?)"
    r"\s*(?:[–\-]|to|through)\s*"
    r"[$€£¥]?\s*(\d{1,6}(?:,\d{3})*(?:\.\d{1,2})?)"
    r"(?!\s*(?:am|pm|:\d{2}))",  # not a time range
    re.IGNORECASE,
)

# Word-based range: "8 to 12 dollars", "8-12 bucks"
_RANGE_WORDS_PAT = re.compile(
    r"(\d{1,6}(?:,\d{3})*(?:\.\d{1,2})?)"
    r"\s*(?:[–\-]|to|through)\s*"
    r"(\d{1,6}(?:,\d{3})*(?:\.\d{1,2})?)"
    r"\s+(?:dollars?|bucks?)\b",
    re.IGNORECASE,
)

# Single price: "$8", "$8.50"
_SINGLE_DOLLAR_PAT = re.compile(
    r"[$€£¥]\s*(\d{1,6}(?:,\d{3})*(?:\.\d{1,2})?)"
    r"(?!\s*(?:\d|am|pm|:\d{2}))",  # not part of a date/time
)

# Single price: "8 dollars", "8 bucks"
_SINGLE_WORD_PAT = re.compile(
    r"\b(\d{1,6}(?:,\d{3})*(?:\.\d{1,2})?)\s+(?:dollars?|bucks?)\b",
    re.IGNORECASE,
)

# DealCandidate price_range string: "$8-$12"
_PRICE_RANGE_STR_PAT = re.compile(
    r"^\$(\d+(?:\.\d+)?)\s*\-\s*\$(\d+(?:\.\d+)?)$"
)


def _parse_num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_price_text(
    text: str,
    existing_price: float | None = None,
    existing_original: float | None = None,
) -> tuple[float | None, tuple[float, float] | None, str]:
    """Extract (price, price_range, currency) from free-form text.

    Handles: "$8", "8 dollars", "8 bucks", "under $10", "$8-$12",
             "8 to 12 dollars", "free", "complimentary".
    Falls back to existing_price when text contains no price signal.
    """
    currency = detect_currency(text)

    # Free / complimentary
    if _FREE_PAT.search(text):
        return 0.0, None, currency

    # "under X" → upper-bounded range (0, X)
    m = _UNDER_PAT.search(text)
    if m:
        return None, (0.0, _parse_num(m.group(1))), currency

    # Currency-led range: "$8-$12"
    m = _RANGE_DOLLAR_PAT.search(text)
    if m:
        lo, hi = _parse_num(m.group(1)), _parse_num(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return None, (lo, hi), currency

    # Word-led range: "8 to 12 dollars"
    m = _RANGE_WORDS_PAT.search(text)
    if m:
        lo, hi = _parse_num(m.group(1)), _parse_num(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return None, (lo, hi), currency

    # Single price with currency symbol
    m = _SINGLE_DOLLAR_PAT.search(text)
    if m:
        return _parse_num(m.group(1)), None, currency

    # Single price with word
    m = _SINGLE_WORD_PAT.search(text)
    if m:
        return _parse_num(m.group(1)), None, currency

    # Fall back to pre-parsed values from the raw deal
    if existing_price is not None:
        return existing_price, None, currency

    return None, None, currency


def parse_price_range_str(s: str | None) -> tuple[float, float] | None:
    """Convert "$8-$12" → (8.0, 12.0). Returns None for None or bad format."""
    if s is None:
        return None
    m = _PRICE_RANGE_STR_PAT.match(s.strip())
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return (min(lo, hi), max(lo, hi))
    return None


def compute_discount(original: float | None, deal: float | None) -> float | None:
    if original and deal is not None and original > 0 and deal < original:
        return round((original - deal) / original * 100, 2)
    return None


# ── Schedule ──────────────────────────────────────────────────────────────────

_DAY_EXPANSION: dict[str, list[int]] = {
    "monday":    [0],
    "tuesday":   [1],
    "wednesday": [2],
    "thursday":  [3],
    "friday":    [4],
    "saturday":  [5],
    "sunday":    [6],
    "weekdays":  [0, 1, 2, 3, 4],
    "weekends":  [5, 6],
    "daily":     [0, 1, 2, 3, 4, 5, 6],
}


def expand_days(schedule_days: list[str]) -> list[int]:
    """Expand canonical day-name strings to a sorted integer list (0=Mon, 6=Sun).

    Examples:
        ["weekdays"]             → [0, 1, 2, 3, 4]
        ["daily"]                → [0, 1, 2, 3, 4, 5, 6]
        ["monday", "wednesday"]  → [0, 2]
        ["weekdays", "saturday"] → [0, 1, 2, 3, 4, 5]
    """
    if not schedule_days:
        return []
    result: set[int] = set()
    for day in schedule_days:
        result.update(_DAY_EXPANSION.get(day.lower(), []))
    return sorted(result)


_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


def canonicalize_time(t: str | None) -> str | None:
    """Pass through valid HH:MM times; return None for anything else."""
    if t is None:
        return None
    if _TIME_RE.match(t):
        return t
    return None


# ── Deal type ─────────────────────────────────────────────────────────────────

_VALID_DEAL_TYPES: frozenset[str] = frozenset({
    "happy_hour", "lunch_special", "early_bird",
    "prix_fixe", "dinner_special", "other",
})

_DEAL_TYPE_KW: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bhappy[\s\-]?hour\b", re.IGNORECASE), "happy_hour"),
    (re.compile(r"\blunch\s+(?:special|deal|menu|combo|offer)\b", re.IGNORECASE), "lunch_special"),
    (re.compile(r"\bmidday\s+special\b", re.IGNORECASE), "lunch_special"),
    (re.compile(r"\bearly[\s\-]?bird\b", re.IGNORECASE), "early_bird"),
    (re.compile(r"\bprix[\s\-]fixe\b|\btasting\s+menu\b", re.IGNORECASE), "prix_fixe"),
    (re.compile(r"\bdinner\s+special\b", re.IGNORECASE), "dinner_special"),
]


def classify_deal_type(
    existing: str | None,
    title: str,
    description: str | None = None,
) -> str:
    """Return a canonical deal type.

    Uses `existing` when it's already a valid type; otherwise infers from
    title then description.  Falls back to "other".
    """
    if existing and existing in _VALID_DEAL_TYPES:
        return existing
    text = f"{title} {description or ''}"
    for pat, deal_type in _DEAL_TYPE_KW:
        if pat.search(text):
            return deal_type
    return "other"


# ── Text cleanup ──────────────────────────────────────────────────────────────

# Unicode dashes/quotes → ASCII equivalents
_UNICODE_MAP = str.maketrans({
    "\u2013": "-",   # en dash
    "\u2014": " - ", # em dash
    "\u2018": "'",   # left single quote
    "\u2019": "'",   # right single quote
    "\u201c": '"',   # left double quote
    "\u201d": '"',   # right double quote
    "\u00a0": " ",   # non-breaking space
    "\u00ab": '"',   # « left guillemet
    "\u00bb": '"',   # » right guillemet
})

# Footnote markers: *, **, †, ‡ at word boundaries or end of text
_FOOTNOTE_PAT = re.compile(r"(?:^\s*\*+\s*|\s*\*+\s*$|\s+\*\S+)", re.MULTILINE)
# HTML tags that may have leaked through
_HTML_TAG_PAT = re.compile(r"<[^>]+>")
# Two-or-more whitespace → single space / normalize line endings
_MULTISPACE_PAT = re.compile(r"[^\S\n]+")
_MULTILINE_PAT = re.compile(r"\n{3,}")


def clean_text(text: str | None) -> str | None:
    """Normalize a string for storage.

    Steps:
      1. Return None for None / blank input.
      2. Decode HTML entities (&amp; → &, &nbsp; → space).
      3. Strip leaked HTML tags.
      4. Translate Unicode punctuation to ASCII equivalents.
      5. Remove footnote asterisks (* at start/end of words).
      6. Collapse runs of whitespace.
      7. Strip leading/trailing whitespace.
    """
    if not text:
        return None
    # HTML entities
    text = html_lib.unescape(text)
    # Leaked HTML tags
    text = _HTML_TAG_PAT.sub(" ", text)
    # Unicode normalisation (NFC) then char map
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_UNICODE_MAP)
    # Footnote markers
    text = _FOOTNOTE_PAT.sub(" ", text)
    # Whitespace
    text = _MULTISPACE_PAT.sub(" ", text)
    text = _MULTILINE_PAT.sub("\n\n", text)
    text = text.strip()
    return text or None


# ── Merchant / slug helpers ───────────────────────────────────────────────────

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def merchant_slug(merchant: str | None) -> str:
    """Lowercase, alphanumeric slug for dedup key construction."""
    if not merchant:
        return ""
    return _NON_ALNUM.sub("-", merchant.lower()).strip("-")


def extract_merchant_from_block(text: str) -> str | None:
    """Best-effort merchant extraction from a scraped block's first line.

    Handles blog-listing headings like "1. The Spotted Dog — Tribeca".
    Falls back to the raw first line if it looks like a venue name.
    """
    first_line = text.strip().split("\n")[0].strip()
    # "1. Restaurant Name — Neighbourhood" pattern
    m = re.match(r"^\d+\.\s*(.+?)(?:\s*[—\-]\s*.+)?$", first_line)
    if m:
        name = m.group(1).strip()
        if 3 < len(name) < 80:
            return name
    # Bare heading with no number
    if 5 < len(first_line) < 80 and not first_line[0].isdigit():
        return first_line
    return None
