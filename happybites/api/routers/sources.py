from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from happybites.api.deps import get_db
from happybites.db.models import IngestionRun, Source
from happybites.schemas.api import IngestionRunResponse, SourceResponse

router = APIRouter()


@router.get("", response_model=list[SourceResponse])
def list_sources(db: Annotated[Session, Depends(get_db)]):
    sources = db.query(Source).order_by(Source.name).all()
    return [SourceResponse.model_validate(s) for s in sources]


@router.get("/{source_id}/runs", response_model=list[IngestionRunResponse])
def list_runs(
    source_id: int,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
):
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    runs = (
        db.query(IngestionRun)
        .filter(IngestionRun.source_id == source_id)
        .order_by(IngestionRun.started_at.desc())
        .limit(limit)
        .all()
    )

    return [
        IngestionRunResponse(
            id=r.id,
            source_id=r.source_id,
            source_name=source.name,
            crawl_job_id=r.crawl_job_id,
            started_at=r.started_at,
            finished_at=r.finished_at,
            status=r.status,
            deals_fetched=r.deals_fetched,
            deals_inserted=r.deals_inserted,
            deals_updated=r.deals_updated,
            deals_skipped=r.deals_skipped,
            records_raw=r.records_raw,
            duration_seconds=r.duration_seconds,
            error_msg=r.error_msg,
        )
        for r in runs
    ]
