from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from happybites.api.deps import get_db
from happybites.db.models import Deal
from happybites.schemas.api import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(db: Annotated[Session, Depends(get_db)]):
    now = datetime.now(timezone.utc)
    db_ok = True

    try:
        total = db.query(Deal).filter(Deal.is_active == True).count()  # noqa: E712
    except Exception:
        db_ok = False
        total = 0

    # Count deals fetched in last 24h
    from datetime import timedelta

    cutoff_24h = now - timedelta(hours=24)
    fresh_24h = (
        db.query(Deal)
        .filter(Deal.is_active == True, Deal.fetched_at >= cutoff_24h)  # noqa: E712
        .count()
        if db_ok
        else 0
    )

    # Oldest active deal age
    oldest = (
        db.query(Deal.fetched_at)
        .filter(Deal.is_active == True)  # noqa: E712
        .order_by(Deal.fetched_at.asc())
        .first()
        if db_ok
        else None
    )
    oldest_hours = None
    if oldest and oldest[0]:
        fetched = oldest[0]
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        oldest_hours = round((now - fetched).total_seconds() / 3600, 1)

    stale = fresh_24h == 0 and total > 0

    return HealthResponse(
        status="degraded" if stale or not db_ok else "ok",
        db_reachable=db_ok,
        deals_total=total,
        deals_fresh_24h=fresh_24h,
        oldest_deal_hours=oldest_hours,
        stale=stale,
    )
