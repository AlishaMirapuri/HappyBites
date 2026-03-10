"""
Deal ranking.

rank_score = w_discount * discount_norm
           + w_freshness * freshness_norm
           + w_quality  * quality_score
           [+ 0.1 category boost, capped at 1.0]

discount_norm  = min(discount_pct / 100, 1.0)        — linear, capped at 100%
freshness_norm = exp(-age_hours / halflife_hours)     — exponential decay
quality_score  = 0.0–1.0 from normalizer             — completeness + plausibility
"""

import math
from datetime import datetime, timezone

import structlog
from sqlalchemy.orm import Session

from happybites.config import settings
from happybites.db.models import Deal

logger = structlog.get_logger(__name__)


def compute_rank_score(
    discount_pct: float | None,
    fetched_at: datetime,
    quality_score: float | None,
    *,
    category_boost: bool = False,
    now: datetime | None = None,
) -> float:
    """
    Pure function — no DB access. All inputs explicit.
    Pass `now` in tests to freeze time.
    """
    _now = now or datetime.now(timezone.utc)
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)

    # Discount component
    d = min((discount_pct or 0.0) / 100.0, 1.0)

    # Freshness component — exponential decay
    age_hours = (_now - fetched_at).total_seconds() / 3600
    f = math.exp(-age_hours / settings.freshness_halflife_hours)

    # Quality component
    q = quality_score if quality_score is not None else 0.5

    score = settings.weight_discount * d + settings.weight_freshness * f + settings.weight_quality * q

    if category_boost:
        score = min(score + 0.10, 1.0)

    return round(score, 4)


def rank_deal(deal: Deal, preferred_categories: list[str] | None = None) -> float:
    """Compute rank_score for a single Deal ORM object."""
    boost = bool(
        preferred_categories
        and deal.category
        and deal.category in preferred_categories
    )
    return compute_rank_score(
        discount_pct=deal.discount_pct,
        fetched_at=deal.fetched_at,
        quality_score=deal.quality_score,
        category_boost=boost,
    )


def rerank_all(db: Session, preferred_categories: list[str] | None = None) -> int:
    """
    Recompute rank_score for all active deals.
    Returns count of deals updated.
    """
    deals = db.query(Deal).filter(Deal.is_active == True).all()  # noqa: E712
    for deal in deals:
        deal.rank_score = rank_deal(deal, preferred_categories)

    db.commit()
    logger.info("reranked", count=len(deals))
    return len(deals)
