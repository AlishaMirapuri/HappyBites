"""Confidence and quality scoring for normalized deals.

confidence  — normalization reliability (how certain are the extracted fields?)
quality     — data completeness (how many useful fields are populated?)
"""

from __future__ import annotations

# ── Base confidence by extraction method ─────────────────────────────────────

_BASE_CONFIDENCE: dict[str, float] = {
    "llm":        0.80,  # LLM-extracted structured fields
    "rule_based": 0.65,  # regex heuristics from scraping
    "raw":        0.50,  # connector RawDeal with no structured extraction
}

# Per-field confidence bonuses
_HAS_PRICE       = 0.10
_HAS_SCHEDULE    = 0.10
_HAS_TIME_WINDOW = 0.08
_HAS_ITEMS       = 0.05

# Per-issue penalty
_ISSUE_PENALTY = 0.08


def compute_confidence(
    extraction_method: str,
    existing_confidence: float | None,
    *,
    has_price: bool,
    has_schedule: bool,
    has_time_window: bool,
    has_items: bool,
    validation_issues: list[str],
) -> float:
    """Return a confidence score in [0.0, 1.0].

    Args:
        extraction_method: "llm" | "rule_based" | "raw"
        existing_confidence: confidence already computed by the extractor
                             (used as floor — we don't downgrade good extractions)
        has_price: price or price_range is populated
        has_schedule: days list is non-empty
        has_time_window: start_time or end_time is set
        has_items: items_included is non-empty
        validation_issues: list of non-fatal normalization warnings
    """
    base = _BASE_CONFIDENCE.get(extraction_method, 0.50)

    # If the extractor already assigned a confident score, respect it as a floor
    if existing_confidence is not None:
        base = max(base, existing_confidence * base)

    score = base
    if has_price:
        score += _HAS_PRICE
    if has_schedule:
        score += _HAS_SCHEDULE
    if has_time_window:
        score += _HAS_TIME_WINDOW
    if has_items:
        score += _HAS_ITEMS

    score -= _ISSUE_PENALTY * len(validation_issues)

    return round(max(0.0, min(1.0, score)), 3)


# ── Quality (data completeness) ───────────────────────────────────────────────

def compute_quality(
    *,
    title: str | None,
    description: str | None,
    deal_type: str,
    price: float | None,
    price_range: tuple[float, float] | None,
    original_price: float | None,
    items: list[str],
    days: list[int],
    start_time: str | None,
    end_time: str | None,
    merchant: str | None,
) -> float:
    """Return a quality / completeness score in [0.0, 1.0].

    Higher score = more useful fields are present.
    """
    score = 0.0

    if title and len(title) > 8:
        score += 0.15
    if description:
        score += 0.08
    if merchant:
        score += 0.10
    if deal_type != "other":
        score += 0.12
    if price is not None or price_range is not None:
        score += 0.18
    if original_price is not None:
        score += 0.07
    if days:
        score += 0.15
    if start_time and end_time:
        score += 0.10
    elif start_time or end_time:
        score += 0.05
    if items:
        score += 0.05

    return round(min(score, 1.0), 3)
