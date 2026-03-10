"""Admin operations: stats, rerank, cleanup, ingest status, venue dedup."""

from datetime import datetime, timedelta, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from happybites.api.deps import get_db
from happybites.db.models import City, Deal, IngestionRun, NormalizationLog, Source
from happybites.db import repositories as repo
from happybites.schemas.api import (
    AdminStatsResponse,
    CityStatusItem,
    IngestStatusResponse,
    MarkExpiredRequest,
    MatchReasonResponse,
    MergeVenuesRequest,
    MergeVenuesResponse,
    OrchestratorResultResponse,
    ReportedDealItem,
    ReportsSummaryResponse,
    ResetResponse,
    RunIngestRequest,
    SourceStatusItem,
    VenueMatchesResponse,
    VenueMatchResponse,
    VenueSnapshotResponse,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/stats", response_model=AdminStatsResponse)
def admin_stats(db: Annotated[Session, Depends(get_db)]):
    total_deals = db.query(Deal).count()
    active_deals = db.query(Deal).filter(Deal.is_active == True).count()  # noqa: E712
    ai_normalized = (
        db.query(NormalizationLog).filter(NormalizationLog.fallback_used == False).count()  # noqa: E712
    )
    fallback_normalized = (
        db.query(NormalizationLog).filter(NormalizationLog.fallback_used == True).count()  # noqa: E712
    )
    total_runs = db.query(IngestionRun).count()
    failed_runs = db.query(IngestionRun).filter(IngestionRun.status == "error").count()

    categories = (
        db.query(Deal.category, func.count(Deal.id))
        .filter(Deal.is_active == True)  # noqa: E712
        .group_by(Deal.category)
        .order_by(func.count(Deal.id).desc())
        .all()
    )

    sources = db.query(Source).all()
    source_stats = [
        {
            "name": s.name,
            "is_active": s.is_active,
            "last_fetched_at": s.last_fetched_at.isoformat() if s.last_fetched_at else None,
            "deal_count": db.query(Deal)
            .filter(Deal.source_id == s.id, Deal.is_active == True)  # noqa: E712
            .count(),
        }
        for s in sources
    ]

    return AdminStatsResponse(
        total_deals=total_deals,
        active_deals=active_deals,
        ai_normalized=ai_normalized,
        fallback_normalized=fallback_normalized,
        total_runs=total_runs,
        failed_runs=failed_runs,
        deals_by_category=dict(categories),
        sources=source_stats,
    )


@router.post("/rerank", response_model=ResetResponse)
def rerank_all(db: Annotated[Session, Depends(get_db)]):
    from happybites.ingestion.ranker import rerank_all as _rerank

    count = _rerank(db)
    logger.info("admin_rerank", updated=count)
    return ResetResponse(message=f"Reranked {count} active deals")


@router.delete("/deals/expired", response_model=ResetResponse)
def purge_expired(db: Annotated[Session, Depends(get_db)]):
    now = datetime.now(timezone.utc)
    expired = (
        db.query(Deal)
        .filter(Deal.expires_at != None, Deal.expires_at < now)  # noqa: E711
        .all()
    )
    count = len(expired)
    for deal in expired:
        deal.is_active = False
    db.commit()
    logger.info("admin_purge_expired", flagged=count)
    return ResetResponse(message=f"Flagged {count} expired deals as inactive")


@router.post("/mark_expired", response_model=ResetResponse)
def mark_expired(body: MarkExpiredRequest, db: Annotated[Session, Depends(get_db)]):
    cutoff = body.before or datetime.now(timezone.utc)
    expired = (
        db.query(Deal)
        .filter(
            Deal.expires_at.isnot(None),
            Deal.expires_at < cutoff,
            Deal.is_active == True,  # noqa: E712
        )
        .all()
    )
    count = len(expired)
    for deal in expired:
        deal.is_active = False
    db.commit()
    logger.info("admin_mark_expired", count=count)
    return ResetResponse(message=f"Marked {count} deals as expired")


@router.get("/ingest_status", response_model=IngestStatusResponse)
def ingest_status(db: Annotated[Session, Depends(get_db)]):
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)

    total_active = db.query(Deal).filter(Deal.is_active == True).count()  # noqa: E712
    total_fresh = (
        db.query(Deal)
        .filter(
            Deal.is_active == True,  # noqa: E712
            Deal.last_seen_at >= cutoff_24h,
        )
        .count()
    )

    sources = db.query(Source).order_by(Source.name).all()
    source_items: list[SourceStatusItem] = []
    for s in sources:
        active_count = (
            db.query(Deal)
            .filter(Deal.source_id == s.id, Deal.is_active == True)  # noqa: E712
            .count()
        )
        fresh_count = (
            db.query(Deal)
            .filter(
                Deal.source_id == s.id,
                Deal.is_active == True,  # noqa: E712
                Deal.last_seen_at >= cutoff_24h,
            )
            .count()
        )
        source_items.append(
            SourceStatusItem(
                source_id=s.id,
                source_name=s.name,
                last_fetched_at=s.last_fetched_at,
                last_successful_at=s.last_successful_at,
                consecutive_failures=s.consecutive_failures,
                deals_active=active_count,
                deals_fresh_24h=fresh_count,
                is_active=s.is_active,
            )
        )

    # City-level freshness
    cities_with_deals = (
        db.query(City)
        .join(Deal, Deal.city_id == City.id)
        .filter(Deal.is_active == True)  # noqa: E712
        .distinct()
        .all()
    )
    city_items: list[CityStatusItem] = []
    for c in cities_with_deals:
        active_count = (
            db.query(Deal)
            .filter(Deal.city_id == c.id, Deal.is_active == True)  # noqa: E712
            .count()
        )
        fresh_count = (
            db.query(Deal)
            .filter(
                Deal.city_id == c.id,
                Deal.is_active == True,  # noqa: E712
                Deal.last_seen_at >= cutoff_24h,
            )
            .count()
        )
        oldest = (
            db.query(Deal.last_seen_at)
            .filter(Deal.city_id == c.id, Deal.is_active == True)  # noqa: E712
            .order_by(Deal.last_seen_at.asc())
            .first()
        )
        oldest_hours: float | None = None
        if oldest and oldest[0]:
            ts = oldest[0]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            oldest_hours = round((now - ts).total_seconds() / 3600, 1)

        city_items.append(
            CityStatusItem(
                city_id=c.id,
                city_name=c.name,
                deals_active=active_count,
                deals_fresh_24h=fresh_count,
                oldest_deal_hours=oldest_hours,
            )
        )

    return IngestStatusResponse(
        checked_at=now,
        total_active_deals=total_active,
        total_fresh_24h=total_fresh,
        stale=total_fresh == 0 and total_active > 0,
        sources=source_items,
        cities=city_items,
    )


# ── Venue deduplication ────────────────────────────────────────────────────────


@router.get("/venue_matches", response_model=VenueMatchesResponse)
def venue_matches(
    db: Annotated[Session, Depends(get_db)],
    city: str | None = Query(None, description="City slug to filter venues"),
):
    """Find candidate duplicate venue pairs within a city.

    Runs pairwise fuzzy matching on all active venues in the specified city
    (or all cities if omitted) and returns pairs ranked by match_score.

    Query params:
        city: city slug (e.g. "new-york-ny").  Omit to scan all cities.
    """
    from happybites.venue_dedup.matcher import VenueSnapshot
    from happybites.venue_dedup.resolver import find_duplicate_candidates

    city_id: int | None = None
    city_label: str | None = city

    if city:
        city_obj = repo.get_city_by_slug(db, city)
        if not city_obj:
            raise HTTPException(status_code=404, detail=f"City '{city}' not found")
        city_id = city_obj.id
        city_label = city_obj.name

    venues = repo.get_venues_for_dedup(db, city_id=city_id)
    source_counts = {v.id: repo.count_venue_source_mappings(db, v.id) for v in venues}

    snapshots = [
        VenueSnapshot(
            id=v.id,
            name=v.name,
            address=v.address,
            phone=v.phone,
            lat=v.lat,
            lon=v.lon,
            city_id=v.city_id,
            source_count=source_counts.get(v.id, 1),
        )
        for v in venues
    ]

    candidates = find_duplicate_candidates(snapshots, same_city_only=city_id is not None)
    logger.info(
        "venue_dedup_scan",
        city=city,
        venues_scanned=len(snapshots),
        candidates=len(candidates),
    )

    match_responses = [
        VenueMatchResponse(
            venue_a=VenueSnapshotResponse(**vars(c.venue_a)),
            venue_b=VenueSnapshotResponse(**vars(c.venue_b)),
            match_score=c.match_score,
            confidence=c.confidence,
            reasons=[MatchReasonResponse(**vars(r)) for r in c.reasons],
            fields_used=c.fields_used,
            is_chain_collision=c.is_chain_collision,
        )
        for c in candidates
    ]

    return VenueMatchesResponse(
        city=city_label,
        total_venues_scanned=len(snapshots),
        candidates=match_responses,
    )


@router.post("/merge_venues", response_model=MergeVenuesResponse)
def merge_venues(
    body: MergeVenuesRequest,
    db: Annotated[Session, Depends(get_db)],
):
    """Merge a secondary venue into a primary venue.

    All source mappings and deals from the secondary are reassigned to the
    primary.  The secondary is marked inactive.

    Set `force: true` to merge chain collisions (same brand, different
    locations) — by default this is refused to prevent accidental merges.
    """
    from happybites.venue_dedup.matcher import VenueSnapshot, match_venues

    primary = repo.get_venue(db, body.primary_venue_id)
    secondary = repo.get_venue(db, body.secondary_venue_id)

    if not primary:
        raise HTTPException(status_code=404, detail=f"Primary venue {body.primary_venue_id} not found")
    if not secondary:
        raise HTTPException(status_code=404, detail=f"Secondary venue {body.secondary_venue_id} not found")
    if not secondary.is_active:
        raise HTTPException(status_code=409, detail="Secondary venue is already inactive/merged")

    # Guard against chain collision merges unless explicitly forced
    if not body.force:
        snap_a = VenueSnapshot(
            id=primary.id, name=primary.name, address=primary.address,
            phone=primary.phone, lat=primary.lat, lon=primary.lon,
            city_id=primary.city_id,
        )
        snap_b = VenueSnapshot(
            id=secondary.id, name=secondary.name, address=secondary.address,
            phone=secondary.phone, lat=secondary.lat, lon=secondary.lon,
            city_id=secondary.city_id,
        )
        result = match_venues(snap_a, snap_b)
        if result and result.is_chain_collision:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This pair looks like a chain collision (same brand, different locations). "
                    "Set force=true to override."
                ),
            )

    try:
        mappings_moved, deals_moved = repo.merge_venues(
            db,
            primary_id=body.primary_venue_id,
            secondary_id=body.secondary_venue_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(
        "venue_merge",
        primary=body.primary_venue_id,
        secondary=body.secondary_venue_id,
        mappings=mappings_moved,
        deals=deals_moved,
    )

    return MergeVenuesResponse(
        message=(
            f"Merged venue {body.secondary_venue_id} into {body.primary_venue_id}: "
            f"{mappings_moved} mappings, {deals_moved} deals reassigned"
        ),
        primary_venue_id=body.primary_venue_id,
        mappings_reassigned=mappings_moved,
        deals_reassigned=deals_moved,
    )


@router.post("/run_ingest", response_model=OrchestratorResultResponse)
def run_ingest(body: RunIngestRequest):
    """Trigger the full ingestion orchestrator inline.

    Runs all active sources (plus fixture if fixture_mode=True).
    Returns aggregated metrics across all sources.  Runs synchronously —
    suitable for demo and dev; for production, offload to a task queue.
    """
    from happybites.ingestion.orchestrator import run_orchestrator

    result = run_orchestrator(sources=body.sources, fixture_mode=body.fixture_mode)
    logger.info(
        "admin_run_ingest",
        sources=result.sources_run,
        fetched=result.total_fetched,
        inserted=result.total_inserted,
        errors=result.total_errors,
    )
    return result.to_dict()


@router.get("/reports_summary", response_model=ReportsSummaryResponse)
def reports_summary(
    db: Annotated[Session, Depends(get_db)],
    city: str | None = Query(None, description="City slug to filter"),
    limit: int = Query(20, ge=1, le=100),
):
    """Aggregate report events (report_incorrect + report_expired) by deal/city/source."""
    from happybites.db import repositories as _repo
    summary = _repo.get_reports_summary(db, city_slug=city, limit_deals=limit)
    return ReportsSummaryResponse(
        city=summary["city"],
        total_reports=summary["total_reports"],
        by_type=summary["by_type"],
        by_source=summary["by_source"],
        by_city=summary["by_city"],
        most_reported=[ReportedDealItem(**item) for item in summary["most_reported"]],
    )


@router.post("/mark_stale", response_model=ResetResponse)
def mark_stale(
    db: Annotated[Session, Depends(get_db)],
    stale_hours: float = Query(96.0, ge=1.0, description="Age threshold in hours"),
):
    """Mark deals inactive if last_seen_at is older than stale_hours (default 96h = 4 days)."""
    from happybites.db import repositories as _repo
    count = _repo.mark_stale_deals_expired(db, stale_hours=stale_hours)
    logger.info("admin_mark_stale", count=count, stale_hours=stale_hours)
    return ResetResponse(message=f"Marked {count} stale deals as inactive")
