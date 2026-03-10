"""
User event logging for deal interactions.

MVP: logs to structlog (stdout/file).
Future: write to an `events` table or stream to an analytics backend.
"""

from datetime import datetime, timezone
from enum import StrEnum

import structlog

logger = structlog.get_logger(__name__)


class EventType(StrEnum):
    DEAL_VIEWED = "deal_viewed"
    DEAL_CLICKED = "deal_clicked"
    DEAL_SEARCHED = "deal_searched"
    FILTER_APPLIED = "filter_applied"
    INGEST_TRIGGERED = "ingest_triggered"
    RERANK_TRIGGERED = "rerank_triggered"


def log_event(
    event_type: EventType,
    session_id: str | None = None,
    **payload,
) -> None:
    """
    Log a structured user event.

    All events include a UTC timestamp. Extra keyword arguments
    are included as payload fields.
    """
    logger.info(
        "user_event",
        event_type=str(event_type),
        session_id=session_id,
        ts=datetime.now(timezone.utc).isoformat(),
        **payload,
    )
