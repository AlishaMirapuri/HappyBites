import hashlib
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from happybites.api.deps import get_db
from happybites.db.models import EventLog
from happybites.feedback.quality import apply_quality_adjustments
from happybites.schemas.api import EventLogCreate, EventLogResponse

router = APIRouter()
logger = structlog.get_logger(__name__)

_REPORT_TYPES = {"report_incorrect", "report_expired"}


def _hash_ip(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()[:32]


@router.post("", response_model=EventLogResponse, status_code=201)
def log_event(
    body: EventLogCreate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    ip = request.client.host if request.client else None
    ip_hash = _hash_ip(ip) if ip else None

    event = EventLog(
        event_type=body.event_type,
        session_id=body.session_id,
        deal_id=body.deal_id,
        venue_id=body.venue_id,
        payload=body.payload,
        ip_hash=ip_hash,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    # Trigger quality adjustments after report events
    if body.event_type in _REPORT_TYPES and body.deal_id:
        actions = apply_quality_adjustments(db, body.deal_id)
        logger.info(
            "quality_adjustment",
            event_type=body.event_type,
            deal_id=body.deal_id,
            **actions,
        )

    logger.info("event_logged", event_type=body.event_type, session_id=body.session_id)
    return EventLogResponse.model_validate(event)
