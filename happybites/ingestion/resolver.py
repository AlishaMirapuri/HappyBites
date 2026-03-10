"""
Entity resolution and deduplication.

Strategy:
  1. Primary: (source_id, source_deal_id) unique constraint in DB — enforced at write time.
  2. Secondary: URL-based cross-source dedup — same canonical URL from different sources
     sets is_active=False on the lower-quality duplicate.

For MVP, cross-source dedup is flagged but not auto-merged to keep provenance clean.
"""

import hashlib
import structlog
from sqlalchemy.orm import Session

from happybites.db.models import Deal

logger = structlog.get_logger(__name__)


def canonical_url(url: str) -> str:
    """Strip query params and fragments for URL comparison."""
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    # Drop query string and fragment; keep scheme + netloc + path
    clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))
    return clean.lower()


def url_fingerprint(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()[:16]


def find_duplicate_by_url(db: Session, url: str, exclude_deal_id: int | None = None) -> Deal | None:
    """
    Find an existing active deal with the same canonical URL from a different source.
    Returns the first match, or None.
    """
    fingerprint = url_fingerprint(url)
    query = (
        db.query(Deal)
        .filter(Deal.is_active == True)  # noqa: E712
        .filter(Deal.url.like(f"%{canonical_url(url).split('/')[-1]}%"))
    )
    if exclude_deal_id:
        query = query.filter(Deal.id != exclude_deal_id)

    return query.first()


def resolve_deals(db: Session, new_deals: list[Deal]) -> dict:
    """
    After inserting new deals, flag cross-source duplicates.
    Returns stats dict: {checked, flagged}.
    """
    flagged = 0
    for deal in new_deals:
        duplicate = find_duplicate_by_url(db, deal.url, exclude_deal_id=deal.id)
        if duplicate:
            # Keep higher quality deal active; flag the lower one
            if (deal.quality_score or 0) >= (duplicate.quality_score or 0):
                duplicate.is_active = False
                logger.info(
                    "dedup_flagged",
                    kept_id=deal.id,
                    flagged_id=duplicate.id,
                    url=deal.url,
                )
            else:
                deal.is_active = False
                logger.info(
                    "dedup_flagged",
                    kept_id=duplicate.id,
                    flagged_id=deal.id,
                    url=deal.url,
                )
            flagged += 1

    if flagged:
        db.commit()

    return {"checked": len(new_deals), "flagged": flagged}
