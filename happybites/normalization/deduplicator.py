"""Deduplication of NormalizedDeal lists.

Two deals are considered duplicates when they share the same merchant (slug),
deal_type, day schedule, and time window.  Within a group the winner is
selected by: highest confidence first, then most recent last_seen.

dedup_key format:
    {merchant_slug}|{deal_type}|{days_str}|{start_time or ''}|{end_time or ''}

Examples of same dedup_key:
    "spotted-dog|happy_hour|01234|17:00|19:00"   — two scrapes of same deal
    "|lunch_special|01234|11:00|15:00"            — no merchant, same window
"""

from __future__ import annotations

import hashlib

from happybites.normalization.schema import NormalizedDeal


def make_dedup_key(
    merchant_slug: str,
    deal_type: str,
    days: list[int],
    start_time: str | None,
    end_time: str | None,
) -> str:
    """Build the deduplication key for a normalized deal.

    The key is NOT a hash — it's a human-readable pipe-separated string
    so it can be inspected in tests and logs.
    """
    days_str = "".join(str(d) for d in sorted(days))
    return "|".join([
        merchant_slug,
        deal_type,
        days_str,
        start_time or "",
        end_time or "",
    ])


def _winner(a: NormalizedDeal, b: NormalizedDeal) -> NormalizedDeal:
    """Return the better deal between two duplicates."""
    if a.confidence != b.confidence:
        return a if a.confidence > b.confidence else b
    # Equal confidence → prefer fresher
    return a if a.last_seen >= b.last_seen else b


def deduplicate(deals: list[NormalizedDeal]) -> list[NormalizedDeal]:
    """Reduce a list to one deal per dedup_key.

    Within each group, keep the deal with the highest confidence.
    Ties resolved by most-recent last_seen.

    Insertion order of the winning deals in the output matches the order
    of first occurrence of each key.
    """
    best: dict[str, NormalizedDeal] = {}
    order: list[str] = []

    for deal in deals:
        key = deal.dedup_key
        if key not in best:
            best[key] = deal
            order.append(key)
        else:
            best[key] = _winner(best[key], deal)

    return [best[k] for k in order]


# ── Stable deal_id helpers ────────────────────────────────────────────────────

def make_deal_id(source: str, source_deal_id: str) -> str:
    """Deterministic 16-char hex ID from (source, source_deal_id)."""
    raw = f"{source}:{source_deal_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
