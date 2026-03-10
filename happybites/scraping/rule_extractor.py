"""Rule-based extractor: converts a text block into a DealCandidate.

All parsing is regex + heuristics — no external calls. The LLM extractor
(llm_extractor.py) wraps this as a fallback when it cannot produce a result.

Time-parsing heuristic
──────────────────────
Restaurant hours are almost always PM, so for bare numeric times with no
AM/PM suffix we apply a simple rule:
  • 1–6  → assume PM  (happy-hour and dinner window)
  • 7–9  → assume PM  (late evening)
  • 10–12 → leave as-is (brunch/lunch window, likely AM)
Explicit "am"/"pm" always overrides the heuristic.
"""

import re

from happybites.scraping.schema import DealCandidate, VALID_DEAL_TYPES

# ── Deal type ─────────────────────────────────────────────────────────────────

_DEAL_TYPE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bhappy[\s\-]?hour\b", re.IGNORECASE), "happy_hour"),
    (re.compile(r"\blunch\s+(?:special|deal|menu|combo|offer)\b", re.IGNORECASE), "lunch_special"),
    (re.compile(r"\bmidday\s+special\b", re.IGNORECASE), "lunch_special"),
    (re.compile(r"\bearly[\s\-]?bird\b", re.IGNORECASE), "early_bird"),
    (re.compile(r"\bprix[\s\-]fixe\b|\btasting\s+menu\b", re.IGNORECASE), "prix_fixe"),
    (re.compile(r"\bdinner\s+special\b", re.IGNORECASE), "dinner_special"),
]


def _detect_deal_type(text: str) -> str:
    for pattern, deal_type in _DEAL_TYPE_PATTERNS:
        if pattern.search(text):
            return deal_type
    return "other"


# ── Schedule days ─────────────────────────────────────────────────────────────

_DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_DAY_ALIASES: dict[str, str] = {
    "monday": "monday",    "mon": "monday",
    "tuesday": "tuesday",  "tue": "tuesday",  "tues": "tuesday",
    "wednesday": "wednesday", "wed": "wednesday",
    "thursday": "thursday", "thu": "thursday", "thur": "thursday", "thurs": "thursday",
    "friday": "friday",    "fri": "friday",
    "saturday": "saturday", "sat": "saturday",
    "sunday": "sunday",    "sun": "sunday",
}

_WEEKDAY_PAT = re.compile(
    r"\bweekdays?\b|\bmon(?:day)?\s*(?:–|-|through|to)\s*fri(?:day)?\b|\bm\s*[-–]\s*f\b",
    re.IGNORECASE,
)
_WEEKEND_PAT = re.compile(
    r"\bweekends?\b|\bsat(?:urday)?\s*(?:and|&|to|–|-|through)\s*sun(?:day)?\b",
    re.IGNORECASE,
)
_DAILY_PAT = re.compile(
    r"\bdaily\b|\bevery\s+day\b|\ball\s+week\b|\b7\s+days\b",
    re.IGNORECASE,
)
# "Tuesday through Thursday" → expand range
_DAY_RANGE_PAT = re.compile(
    r"\b(mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|"
    r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)\s*(?:through|–|-|to)\s*"
    r"(mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|"
    r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
    re.IGNORECASE,
)
_SINGLE_DAY_PAT = re.compile(
    r"\b(mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|"
    r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
    re.IGNORECASE,
)


def _normalise_day(abbr: str) -> str | None:
    return _DAY_ALIASES.get(abbr.lower().rstrip("."))


def _expand_day_range(start: str, end: str) -> list[str]:
    s = _normalise_day(start)
    e = _normalise_day(end)
    if s is None or e is None:
        return []
    si, ei = _DAY_ORDER.index(s), _DAY_ORDER.index(e)
    if si <= ei:
        return _DAY_ORDER[si: ei + 1]
    # wrap-around (e.g. Thu–Mon)
    return _DAY_ORDER[si:] + _DAY_ORDER[: ei + 1]


def _detect_days(text: str) -> list[str]:
    if _DAILY_PAT.search(text):
        return ["daily"]
    if _WEEKDAY_PAT.search(text) and _WEEKEND_PAT.search(text):
        return ["daily"]
    if _WEEKDAY_PAT.search(text):
        return ["weekdays"]
    if _WEEKEND_PAT.search(text):
        return ["weekends"]

    # Explicit day ranges: "Tuesday through Thursday"
    range_m = _DAY_RANGE_PAT.search(text)
    if range_m:
        expanded = _expand_day_range(range_m.group(1), range_m.group(2))
        if expanded:
            # If Mon-Fri, collapse to "weekdays"
            if set(expanded) == {"monday", "tuesday", "wednesday", "thursday", "friday"}:
                return ["weekdays"]
            # If Sat-Sun, collapse to "weekends"
            if set(expanded) == {"saturday", "sunday"}:
                return ["weekends"]
            return expanded

    # Individual day mentions
    days_found: list[str] = []
    seen: set[str] = set()
    for m in _SINGLE_DAY_PAT.finditer(text):
        day = _normalise_day(m.group(1))
        if day and day not in seen:
            days_found.append(day)
            seen.add(day)

    # Collapse named sets
    if set(days_found) == {"monday", "tuesday", "wednesday", "thursday", "friday"}:
        return ["weekdays"]
    if set(days_found) == {"saturday", "sunday"}:
        return ["weekends"]

    return days_found


# ── Time parsing ──────────────────────────────────────────────────────────────

_NOON_PAT = re.compile(r"\bnoon\b", re.IGNORECASE)
_MIDNIGHT_PAT = re.compile(r"\bmidnight\b", re.IGNORECASE)
_AFTER_PAT = re.compile(
    r"\bafter\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\b",
    re.IGNORECASE,
)
_UNTIL_PAT = re.compile(
    r"\b(?:until|before|by)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\b",
    re.IGNORECASE,
)
_RANGE_PAT = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?"
    r"\s*(?:–|-|to|through|until)\s*"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?",
    re.IGNORECASE,
)
_SINGLE_TIME_PAT = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)\b",
    re.IGNORECASE,
)


def _apply_ampm(hour: int, minute: int, ampm: str | None) -> tuple[int, int]:
    """Convert to 24-hour, applying restaurant-context heuristic when ampm is absent."""
    if ampm:
        a = ampm.lower().replace(".", "").replace(" ", "")
        if a == "pm" and hour != 12:
            hour += 12
        elif a == "am" and hour == 12:
            hour = 0
    elif hour <= 9:
        # Heuristic: 1-9 without explicit am/pm → assume PM in restaurant context
        hour += 12
    # 10-12 without am/pm: leave as-is (brunch/lunch window)
    return hour, minute


def _build_time(h_str: str, m_str: str | None, ampm: str | None) -> str | None:
    hour = int(h_str)
    minute = int(m_str) if m_str else 0
    hour, minute = _apply_ampm(hour, minute, ampm)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def _parse_time_range(text: str) -> tuple[str | None, str | None]:
    """Return (start_HH:MM, end_HH:MM). Either may be None."""
    # Noon / midnight substitution for range matching
    normalised = _NOON_PAT.sub("12:00pm", text)
    normalised = _MIDNIGHT_PAT.sub("00:00am", normalised)

    # "after 5" / "after 5pm"
    m = _AFTER_PAT.search(normalised)
    if m and not _RANGE_PAT.search(normalised):
        return _build_time(m.group(1), m.group(2), m.group(3)), None

    # "until 7pm" / "before 7"
    m = _UNTIL_PAT.search(normalised)
    if m and not _RANGE_PAT.search(normalised):
        return None, _build_time(m.group(1), m.group(2), m.group(3))

    # Full range: "5-7pm", "5pm to 7pm", "5:00 to 7:00 pm"
    m = _RANGE_PAT.search(normalised)
    if m:
        h1, m1, ap1 = m.group(1), m.group(2), m.group(3)
        h2, m2, ap2 = m.group(4), m.group(5), m.group(6)
        # Propagate end AM/PM to start when start is bare ("5-7pm" → both pm)
        if not ap1 and ap2 and int(h1) <= int(h2):
            ap1 = ap2
        start = _build_time(h1, m1, ap1)
        end = _build_time(h2, m2, ap2)
        return start, end

    # Single explicit time with am/pm
    m = _SINGLE_TIME_PAT.search(normalised)
    if m:
        return _build_time(m.group(1), m.group(2), m.group(3)), None

    # Plain "noon" / "midnight" with no range
    if _NOON_PAT.search(text):
        return "12:00", None
    if _MIDNIGHT_PAT.search(text):
        return "00:00", None

    return None, None


# ── Price ─────────────────────────────────────────────────────────────────────

_PRICE_RANGE_PAT = re.compile(r"\$(\d+(?:\.\d{1,2})?)\s*(?:–|-|to)\s*\$(\d+(?:\.\d{1,2})?)")
_PRICE_PAT = re.compile(r"\$(\d+(?:\.\d{1,2})?)")


def _extract_price(text: str) -> tuple[float | None, str | None]:
    """Return (price, price_range). At most one is non-None."""
    m = _PRICE_RANGE_PAT.search(text)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        lo_s = f"{lo:.0f}" if lo == int(lo) else str(lo)
        hi_s = f"{hi:.0f}" if hi == int(hi) else str(hi)
        return None, f"${lo_s}-${hi_s}"

    prices = [float(m.group(1)) for m in _PRICE_PAT.finditer(text)]
    if prices:
        return prices[0], None
    return None, None


# ── Items included ────────────────────────────────────────────────────────────

_ITEMS_TRIGGER = re.compile(
    r"(?:including|includes?|featuring|features?|such\s+as|with)\s*:?\s*",
    re.IGNORECASE,
)
_COLON_LIST = re.compile(r":\s*([^\n.!?]+)")
_ITEM_SEP = re.compile(r",\s*|\s+and\s+|\s*&\s*|\s*\+\s*")
_STOP_PAT = re.compile(r"\b(?:not valid|restriction|dine.in|must be|limit|21\+)\b", re.IGNORECASE)


def _extract_items(text: str) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()

    _LEADING_CONJ = re.compile(r"^(?:and|or|&)\s+", re.IGNORECASE)

    def _add(chunk: str) -> None:
        parts = _ITEM_SEP.split(chunk.strip())
        for p in parts:
            p = _LEADING_CONJ.sub("", p.strip().strip(".").strip())
            if 2 < len(p) < 60 and p.lower() not in seen:
                items.append(p)
                seen.add(p.lower())

    # Trigger-word extraction: "including X, Y and Z"
    m = _ITEMS_TRIGGER.search(text)
    if m:
        rest = text[m.end():]
        stop = _STOP_PAT.search(rest)
        chunk = rest[: stop.start()] if stop else rest
        # Trim to first sentence
        sent_end = re.search(r"[.!?]|\n", chunk)
        if sent_end:
            chunk = chunk[: sent_end.start()]
        _add(chunk)

    # Colon lists: "combo: soup, sandwich, drink"
    if not items:
        for cm in _COLON_LIST.finditer(text):
            chunk = cm.group(1)
            if not _STOP_PAT.search(chunk) and len(chunk) < 150:
                _add(chunk)
                if items:
                    break

    # Bullet/dash lines
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(("- ", "* ", "• ", "· ")):
            _add(line[2:])

    return items[:10]


# ── Restrictions ──────────────────────────────────────────────────────────────

_RESTRICTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"dine[\s\-]?in\s+only", re.IGNORECASE), "dine-in only"),
    (re.compile(r"no\s+(?:takeout|to[\s\-]go|delivery)", re.IGNORECASE), "no takeout"),
    (re.compile(r"no\s+substitution", re.IGNORECASE), "no substitutions"),
    (re.compile(r"must\s+be\s+21|21\s*\+|ages?\s+21|over\s+21", re.IGNORECASE), "21+"),
    (re.compile(r"reservations?\s+required", re.IGNORECASE), "reservations required"),
    (re.compile(r"no\s+reservations?", re.IGNORECASE), "no reservations"),
    (re.compile(r"not\s+valid\s+with\s+other\s+offer", re.IGNORECASE), "not valid with other offers"),
    (re.compile(r"(?:bar|lounge)\s+only", re.IGNORECASE), "bar only"),
    (re.compile(r"limit\s+\d+\s+per\s+(?:table|person|guest)", re.IGNORECASE), None),
    (re.compile(r"not\s+available\s+on\s+holidays?", re.IGNORECASE), "not available on holidays"),
    (re.compile(r"while\s+supplies?\s+last", re.IGNORECASE), "while supplies last"),
    (re.compile(r"per\s+person", re.IGNORECASE), "per person"),
]


def _extract_restrictions(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for pattern, canonical in _RESTRICTION_PATTERNS:
        m = pattern.search(text)
        if m:
            label = canonical if canonical else m.group(0).strip().lower()
            if label not in seen:
                found.append(label)
                seen.add(label)
    return found


# ── Confidence ────────────────────────────────────────────────────────────────

def _compute_confidence(
    deal_type: str,
    days: list[str],
    start: str | None,
    end: str | None,
    price: float | None,
    price_range: str | None,
    items: list[str],
) -> float:
    score = 0.3  # base: something was extracted
    if deal_type != "other":
        score += 0.20
    if days:
        score += 0.15
    if start or end:
        score += 0.15
    if price is not None or price_range is not None:
        score += 0.10
    if items:
        score += 0.10
    return round(min(score, 1.0), 2)


# ── Public extractor ──────────────────────────────────────────────────────────

class RuleExtractor:
    """Converts a raw text block into a DealCandidate using regex heuristics."""

    def extract(self, text: str, source_url: str = "") -> DealCandidate:
        deal_type = _detect_deal_type(text)
        schedule_days = _detect_days(text)
        start_time, end_time = _parse_time_range(text)
        price, price_range = _extract_price(text)
        items = _extract_items(text)
        restrictions = _extract_restrictions(text)
        confidence = _compute_confidence(
            deal_type, schedule_days, start_time, end_time, price, price_range, items
        )

        return DealCandidate(
            deal_type=deal_type,
            price=price,
            price_range=price_range,
            items_included=items,
            schedule_days=schedule_days,
            start_time=start_time,
            end_time=end_time,
            restrictions=restrictions,
            confidence=confidence,
            validation_errors=[],   # caller runs validate() and assigns
            source_url=source_url,
            source_block_text=text,
            extraction_method="rule_based",
            raw_extracted={},
        )
