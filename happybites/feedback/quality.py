"""
Deal quality adjustment rules driven by user feedback.

Thresholds
──────────
INCORRECT_THRESHOLD = 3   report_incorrect events → demote quality
EXPIRED_THRESHOLD   = 3   report_expired events   → mark deal inactive

Demotion:
  quality_score  = max(0.0, (quality_score or 0.5) - 0.3)
  confidence     = max(0.0, (confidence or 0.5)    - 0.3)
  rank_score remains — will be fixed on next rerank pass

Expiry:
  is_active  = False
  expires_at = now  (if expires_at was None or in the future)
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from happybites.db.models import Deal, EventLog
from sqlalchemy import func

INCORRECT_THRESHOLD = 3
EXPIRED_THRESHOLD = 3


def count_reports(
    db: Session,
    deal_id: int,
    event_type: str,
) -> int:
    """Count how many times this event_type has been reported for a deal."""
    return (
        db.query(func.count(EventLog.id))
        .filter(EventLog.deal_id == deal_id, EventLog.event_type == event_type)
        .scalar()
        or 0
    )


def demote_deal(db: Session, deal: Deal) -> bool:
    """Lower quality_score and confidence due to incorrect reports.
    Returns True if a change was made.
    """
    changed = False
    current_q = deal.quality_score if deal.quality_score is not None else 0.5
    current_c = deal.confidence if deal.confidence is not None else 0.5
    new_q = max(0.0, current_q - 0.3)
    new_c = max(0.0, current_c - 0.3)
    if new_q != current_q:
        deal.quality_score = round(new_q, 3)
        changed = True
    if new_c != current_c:
        deal.confidence = round(new_c, 3)
        changed = True
    return changed


def expire_deal(db: Session, deal: Deal) -> bool:
    """Mark a deal as inactive due to expired reports.
    Returns True if a change was made.
    """
    if not deal.is_active:
        return False
    deal.is_active = False
    now = datetime.now(timezone.utc)
    if deal.expires_at is None or deal.expires_at > now:
        deal.expires_at = now
    return True


def apply_quality_adjustments(db: Session, deal_id: int) -> dict[str, bool]:
    """Check report thresholds and apply adjustments if needed.

    Returns a dict indicating what actions were taken:
      {"demoted": bool, "expired": bool}
    """
    deal = db.get(Deal, deal_id)
    if not deal:
        return {"demoted": False, "expired": False}

    demoted = False
    expired = False

    incorrect_count = count_reports(db, deal_id, "report_incorrect")
    if incorrect_count >= INCORRECT_THRESHOLD:
        demoted = demote_deal(db, deal)

    expired_count = count_reports(db, deal_id, "report_expired")
    if expired_count >= EXPIRED_THRESHOLD:
        expired = expire_deal(db, deal)

    if demoted or expired:
        db.commit()

    return {"demoted": demoted, "expired": expired}
