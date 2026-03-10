"""Manual ingestion trigger endpoint (for dev/demo use)."""

from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from happybites.api.deps import get_db
from happybites.db.models import Source
from happybites.schemas.api import IngestTriggerRequest, IngestTriggerResponse

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.post("/trigger", response_model=IngestTriggerResponse, status_code=202)
def trigger_ingest(
    request: IngestTriggerRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
):
    from happybites.ingestion.scheduler import run_all_sources, run_ingestion_for_source

    if request.source_id is not None:
        source = db.query(Source).filter(Source.id == request.source_id).first()
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        background_tasks.add_task(run_ingestion_for_source, source.name)
        logger.info("ingest_triggered", source=source.name)
        return IngestTriggerResponse(message=f"Ingestion triggered for source '{source.name}'")

    background_tasks.add_task(run_all_sources)
    logger.info("ingest_triggered_all")
    return IngestTriggerResponse(message="Ingestion triggered for all active sources")
