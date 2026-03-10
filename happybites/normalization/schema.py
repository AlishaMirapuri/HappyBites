"""Output schema for the normalization layer.

NormalizedDeal is a pure-Python dataclass (no ORM) that maps closely to the
Deal DB model but carries no DB-specific foreign keys.  The pipeline layer is
responsible for mapping NormalizedDeal → Deal ORM object and persisting.

Field notes
───────────
deal_id         16-char hex hash; deterministic from (source, source_deal_id).
                Stable identity: same deal across re-ingests → same ID.

source_deal_id  The original source's identifier.  For scraped candidates
                where no ID exists, a content-hash is generated.

price           Exact single price in `currency`.  Mutually exclusive with
                price_range.  0.0 represents a free / complimentary deal.

price_range     (lo, hi) float pair.  Used when the deal spans a range
                (e.g. brunch combo $14-$18).  Serialised as a 2-element list
                in JSON / to_dict().

days            Expanded integer list (0=Mon … 6=Sun).
                "weekdays" → [0,1,2,3,4]; "daily" → [0,1,2,3,4,5,6].
                Empty list means "schedule unknown / always active".

confidence      Normalization reliability: how certain are we that the
                extracted fields are correct?  0.0–1.0.

quality_score   Data completeness: how many useful fields are populated?
                0.0–1.0.  Feeds into the rank_score formula.

dedup_key       Similarity fingerprint used within a batch to find duplicates
                (same merchant + deal_type + time window).  NOT globally unique.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Provenance:
    """Batch-level provenance metadata applied to every deal in a normalize call."""

    source: str                     # e.g. "mock_yelp", "menu_page", "blog_listing"
    ingest_run_id: str | None = None
    last_seen: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class NormalizedDeal:
    """Canonical normalized deal.  DB-agnostic; no SQLAlchemy types."""

    # ── Identity ───────────────────────────────────────────────────────────
    deal_id: str                        # 16-char hex, deterministic
    source_deal_id: str                 # source's own ID (or content hash)

    # ── Content ────────────────────────────────────────────────────────────
    title: str
    description: str | None
    deal_type: str                      # happy_hour | lunch_special | …
    merchant: str | None                # normalized venue/merchant name

    # ── Pricing ────────────────────────────────────────────────────────────
    currency: str                       # ISO 4217 e.g. "USD"
    price: float | None                 # exact price (exclusive with price_range)
    price_range: tuple[float, float] | None   # (lo, hi)
    original_price: float | None
    discount_pct: float | None

    # ── Schedule ───────────────────────────────────────────────────────────
    days: list[int]                     # 0=Mon … 6=Sun, sorted, expanded
    start_time: str | None              # "HH:MM" 24h
    end_time: str | None                # "HH:MM" 24h

    # ── Items / restrictions ───────────────────────────────────────────────
    items_included: list[str]
    restrictions: list[str]

    # ── Provenance ─────────────────────────────────────────────────────────
    source: str
    source_url: str
    last_seen: datetime
    ingest_run_id: str | None

    # ── Quality ────────────────────────────────────────────────────────────
    confidence: float                   # 0.0–1.0
    quality_score: float                # 0.0–1.0
    validation_issues: list[str]        # non-fatal normalization warnings

    # ── Dedup ──────────────────────────────────────────────────────────────
    dedup_key: str

    # ──────────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize to a plain dict suitable for JSON encoding."""
        return {
            "deal_id": self.deal_id,
            "source_deal_id": self.source_deal_id,
            "title": self.title,
            "description": self.description,
            "deal_type": self.deal_type,
            "merchant": self.merchant,
            "currency": self.currency,
            "price": self.price,
            "price_range": list(self.price_range) if self.price_range else None,
            "original_price": self.original_price,
            "discount_pct": self.discount_pct,
            "days": self.days,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "items_included": self.items_included,
            "restrictions": self.restrictions,
            "source": self.source,
            "source_url": self.source_url,
            "last_seen": self.last_seen.isoformat(),
            "ingest_run_id": self.ingest_run_id,
            "confidence": self.confidence,
            "quality_score": self.quality_score,
            "validation_issues": self.validation_issues,
            "dedup_key": self.dedup_key,
        }
