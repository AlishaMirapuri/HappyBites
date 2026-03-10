"""Strict schema for extracted deal candidates.

DealCandidate is the output of the extraction step. Every field is explicitly
nullable; `validation_errors` records schema violations so callers can triage
low-quality extractions rather than silently dropping them.

Valid field values
──────────────────
deal_type       : one of VALID_DEAL_TYPES
price           : non-negative float (mutually exclusive with price_range)
price_range     : "$N-$M" string (e.g. "$8-$12")
schedule_days   : list drawn from VALID_DAYS
start_time      : "HH:MM" 24-hour format
end_time        : "HH:MM" 24-hour format, must be after start_time
confidence      : 0.0–1.0
"""

import re
from dataclasses import dataclass, field

VALID_DEAL_TYPES: set[str] = {
    "happy_hour",
    "lunch_special",
    "early_bird",
    "prix_fixe",
    "dinner_special",
    "other",
}

VALID_DAYS: set[str] = {
    "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday",
    "weekdays",   # Monday–Friday
    "weekends",   # Saturday–Sunday
    "daily",      # all seven days
}

_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_PRICE_RANGE_RE = re.compile(r"^\$[\d.]+\-\$[\d.]+$")


@dataclass
class DealCandidate:
    """Structured deal candidate produced by the extraction step.

    Both `price` and `price_range` may be None; at most one should be set.
    `validation_errors` is populated by `validate()` after construction.
    `raw_extracted` holds whatever the extractor returned before mapping.
    """

    deal_type: str                  # from VALID_DEAL_TYPES
    price: float | None             # e.g. 9.99 — exact per-deal price
    price_range: str | None         # e.g. "$8-$12"
    items_included: list[str]       # e.g. ["draft beer", "well drinks"]
    schedule_days: list[str]        # from VALID_DAYS
    start_time: str | None          # "HH:MM" 24h
    end_time: str | None            # "HH:MM" 24h
    restrictions: list[str]         # e.g. ["dine-in only", "21+"]
    confidence: float               # 0.0–1.0
    validation_errors: list[str]    # populated by validate()
    source_url: str
    source_block_text: str
    extraction_method: str          # "rule_based" | "llm"
    raw_extracted: dict = field(default_factory=dict)


def validate(candidate: DealCandidate) -> list[str]:
    """Validate a DealCandidate against the schema.

    Returns a (possibly empty) list of human-readable error strings.
    Does NOT mutate the candidate; assign the result to candidate.validation_errors.
    """
    errors: list[str] = []

    if candidate.deal_type not in VALID_DEAL_TYPES:
        errors.append(
            f"invalid deal_type '{candidate.deal_type}'; "
            f"must be one of {sorted(VALID_DEAL_TYPES)}"
        )

    if candidate.price is not None and candidate.price < 0:
        errors.append(f"price must be non-negative, got {candidate.price}")

    if candidate.price_range is not None and not _PRICE_RANGE_RE.match(candidate.price_range):
        errors.append(
            f"price_range '{candidate.price_range}' must match '$N-$M' (e.g. '$8-$12')"
        )

    if candidate.price is not None and candidate.price_range is not None:
        errors.append("price and price_range are mutually exclusive; set only one")

    invalid_days = [d for d in candidate.schedule_days if d not in VALID_DAYS]
    if invalid_days:
        errors.append(f"invalid schedule_days: {invalid_days}; must be from {sorted(VALID_DAYS)}")

    for label, t_val in [("start_time", candidate.start_time), ("end_time", candidate.end_time)]:
        if t_val is not None and not _TIME_RE.match(t_val):
            errors.append(f"{label} '{t_val}' must be 'HH:MM' in 24-hour format")

    if (
        candidate.start_time and candidate.end_time
        and _TIME_RE.match(candidate.start_time)
        and _TIME_RE.match(candidate.end_time)
        and candidate.start_time >= candidate.end_time
    ):
        errors.append(
            f"start_time {candidate.start_time} must be before end_time {candidate.end_time}"
        )

    if not (0.0 <= candidate.confidence <= 1.0):
        errors.append(f"confidence {candidate.confidence} must be between 0.0 and 1.0")

    return errors
