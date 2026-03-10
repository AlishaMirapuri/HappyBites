"""
Repository layer — all DB read/write logic lives here.

Routes and pipeline code call these functions; they never touch the ORM directly.
This keeps SQL complexity in one place and makes tests straightforward to write.

Convention:
  - Functions that return a single row return `Model | None`.
  - Functions that return many rows return `list[Model]`.
  - Upsert functions return `tuple[Model, bool]` — (instance, created).
  - Mutating functions commit inside the function; callers don't need to.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from happybites.db.models import (
    City,
    CrawlJob,
    Deal,
    DealRaw,
    DealSchedule,
    EventLog,
    IngestionRun,
    NormalizationLog,
    Source,
    UserPreference,
    Venue,
    VenueSourceMapping,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# City
# ─────────────────────────────────────────────────────────────────────────────


def get_city(db: Session, city_id: int) -> City | None:
    return db.get(City, city_id)


def get_city_by_slug(db: Session, slug: str) -> City | None:
    return db.query(City).filter(City.slug == slug).first()


def list_cities(db: Session, *, active_only: bool = True) -> list[City]:
    q = db.query(City)
    if active_only:
        q = q.filter(City.is_active == True)  # noqa: E712
    return q.order_by(City.name).all()


def get_or_create_city(
    db: Session,
    *,
    name: str,
    state: str | None = None,
    country: str = "US",
    slug: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    timezone_str: str | None = None,
) -> tuple[City, bool]:
    _slug = slug or _make_slug(name, state)
    city = get_city_by_slug(db, _slug)
    if city:
        return city, False

    city = City(
        name=name,
        state=state,
        country=country,
        slug=_slug,
        lat=lat,
        lon=lon,
        timezone=timezone_str,
    )
    db.add(city)
    db.commit()
    db.refresh(city)
    return city, True


def _make_slug(name: str, state: str | None) -> str:
    base = name.lower().replace(" ", "-").replace(",", "")
    if state:
        base = f"{base}-{state.lower()}"
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Source
# ─────────────────────────────────────────────────────────────────────────────


def get_source(db: Session, source_id: int) -> Source | None:
    return db.get(Source, source_id)


def get_source_by_name(db: Session, name: str) -> Source | None:
    return db.query(Source).filter(Source.name == name).first()


def list_sources(db: Session, *, active_only: bool = False) -> list[Source]:
    q = db.query(Source)
    if active_only:
        q = q.filter(Source.is_active == True)  # noqa: E712
    return q.order_by(Source.name).all()


def create_source(db: Session, **kwargs) -> Source:
    source = Source(**kwargs)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def record_source_fetch(
    db: Session, source_id: int, *, success: bool, error: str | None = None
) -> None:
    """Update fetch timestamps and failure counter after an ingestion attempt."""
    source = db.get(Source, source_id)
    if not source:
        return
    now = _utcnow()
    source.last_fetched_at = now
    if success:
        source.last_successful_at = now
        source.consecutive_failures = 0
    else:
        source.consecutive_failures = (source.consecutive_failures or 0) + 1
    db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Venue
# ─────────────────────────────────────────────────────────────────────────────


def get_venue(db: Session, venue_id: int) -> Venue | None:
    return db.get(Venue, venue_id)


def list_venues(
    db: Session,
    *,
    city_id: int | None = None,
    category: str | None = None,
    active_only: bool = True,
) -> list[Venue]:
    q = db.query(Venue)
    if city_id:
        q = q.filter(Venue.city_id == city_id)
    if category:
        q = q.filter(Venue.category == category)
    if active_only:
        q = q.filter(Venue.is_active == True)  # noqa: E712
    return q.order_by(Venue.name).all()


def get_or_create_venue(
    db: Session,
    *,
    name: str,
    city_id: int | None = None,
    slug: str | None = None,
    **kwargs,
) -> tuple[Venue, bool]:
    _slug = slug or _make_slug(name, None)
    if _slug:
        existing = db.query(Venue).filter(Venue.slug == _slug).first()
        if existing:
            return existing, False

    venue = Venue(name=name, city_id=city_id, slug=_slug, **kwargs)
    db.add(venue)
    db.commit()
    db.refresh(venue)
    return venue, True


def find_venue_by_source_mapping(
    db: Session, source_id: int, external_id: str
) -> Venue | None:
    mapping = (
        db.query(VenueSourceMapping)
        .filter(
            VenueSourceMapping.source_id == source_id,
            VenueSourceMapping.external_id == external_id,
        )
        .first()
    )
    return mapping.venue if mapping else None


def get_or_create_venue_mapping(
    db: Session,
    *,
    venue_id: int,
    source_id: int,
    external_id: str,
    external_url: str | None = None,
    confidence: float = 1.0,
) -> tuple[VenueSourceMapping, bool]:
    existing = (
        db.query(VenueSourceMapping)
        .filter(
            VenueSourceMapping.source_id == source_id,
            VenueSourceMapping.external_id == external_id,
        )
        .first()
    )
    if existing:
        existing.last_seen_at = _utcnow()
        db.commit()
        return existing, False

    mapping = VenueSourceMapping(
        venue_id=venue_id,
        source_id=source_id,
        external_id=external_id,
        external_url=external_url,
        confidence=confidence,
        last_seen_at=_utcnow(),
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping, True


# ─────────────────────────────────────────────────────────────────────────────
# Deal
# ─────────────────────────────────────────────────────────────────────────────


def get_deal(db: Session, deal_id: int) -> Deal | None:
    return db.get(Deal, deal_id)


def get_deal_by_source(
    db: Session, source_id: int, source_deal_id: str
) -> Deal | None:
    return (
        db.query(Deal)
        .filter(Deal.source_id == source_id, Deal.source_deal_id == source_deal_id)
        .first()
    )


def list_deals(
    db: Session,
    *,
    city_id: int | None = None,
    venue_id: int | None = None,
    category: str | None = None,
    max_price: float | None = None,
    min_discount: float | None = None,
    is_online: bool | None = None,
    active_only: bool = True,
    sort: str = "rank_score",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Deal], int]:
    """
    Returns (deals, total_count). Supports server-side pagination.
    `sort` must be one of: rank_score | discount_pct | fetched_at | last_seen_at
    """
    q = db.query(Deal)
    if active_only:
        q = q.filter(Deal.is_active == True)  # noqa: E712
    if city_id is not None:
        q = q.filter(Deal.city_id == city_id)
    if venue_id is not None:
        q = q.filter(Deal.venue_id == venue_id)
    if category:
        q = q.filter(Deal.category == category)
    if max_price is not None:
        q = q.filter(Deal.deal_price <= max_price)
    if min_discount is not None:
        q = q.filter(Deal.discount_pct >= min_discount)
    if is_online is not None:
        q = q.filter(Deal.is_online == is_online)

    total = q.count()

    sort_col = {
        "rank_score": Deal.rank_score,
        "discount_pct": Deal.discount_pct,
        "fetched_at": Deal.fetched_at,
        "last_seen_at": Deal.last_seen_at,
    }.get(sort, Deal.rank_score)

    deals = q.order_by(sort_col.desc().nulls_last()).offset(offset).limit(limit).all()
    return deals, total


def upsert_deal(
    db: Session,
    *,
    source_id: int,
    source_deal_id: str,
    **fields: Any,
) -> tuple[Deal, bool]:
    """
    Insert or update a deal. Returns (deal, created).

    On insert: sets first_seen_at = last_seen_at = now.
    On update: updates last_seen_at and mutable fields; preserves first_seen_at.
    """
    now = _utcnow()
    existing = get_deal_by_source(db, source_id, source_deal_id)

    if existing:
        # Preserve first_seen_at; update everything else
        immutable = {"source_id", "source_deal_id", "first_seen_at"}
        for k, v in fields.items():
            if k not in immutable:
                setattr(existing, k, v)
        existing.last_seen_at = now
        db.commit()
        db.refresh(existing)
        return existing, False

    deal = Deal(
        source_id=source_id,
        source_deal_id=source_deal_id,
        first_seen_at=now,
        last_seen_at=now,
        **fields,
    )
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return deal, True


def update_deal_scores(
    db: Session,
    deal_id: int,
    *,
    rank_score: float | None = None,
    quality_score: float | None = None,
    confidence: float | None = None,
    freshness_score: float | None = None,
) -> None:
    deal = db.get(Deal, deal_id)
    if not deal:
        return
    if rank_score is not None:
        deal.rank_score = rank_score
    if quality_score is not None:
        deal.quality_score = quality_score
    if confidence is not None:
        deal.confidence = confidence
    if freshness_score is not None:
        deal.freshness_score = freshness_score
    db.commit()


def deactivate_deal(db: Session, deal_id: int) -> None:
    deal = db.get(Deal, deal_id)
    if deal:
        deal.is_active = False
        db.commit()


def get_deals_by_venue(db: Session, venue_id: int, *, active_only: bool = True) -> list[Deal]:
    q = db.query(Deal).filter(Deal.venue_id == venue_id)
    if active_only:
        q = q.filter(Deal.is_active == True)  # noqa: E712
    return q.order_by(Deal.rank_score.desc().nulls_last()).all()


# ─────────────────────────────────────────────────────────────────────────────
# DealRaw
# ─────────────────────────────────────────────────────────────────────────────


def create_deal_raw(
    db: Session,
    *,
    source_id: int,
    source_deal_id: str,
    raw_payload: dict,
    raw_url: str | None = None,
    http_status: int | None = None,
    crawl_job_id: int | None = None,
    deal_id: int | None = None,
) -> DealRaw:
    payload_str = json.dumps(raw_payload, sort_keys=True)
    content_hash = hashlib.sha256(payload_str.encode()).hexdigest()[:16]

    record = DealRaw(
        source_id=source_id,
        source_deal_id=source_deal_id,
        raw_payload=raw_payload,
        raw_url=raw_url,
        http_status=http_status,
        content_hash=content_hash,
        crawl_job_id=crawl_job_id,
        deal_id=deal_id,
        fetched_at=_utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def link_raw_to_deal(db: Session, raw_id: int, deal_id: int) -> None:
    record = db.get(DealRaw, raw_id)
    if record:
        record.deal_id = deal_id
        db.commit()


def has_content_changed(db: Session, source_id: int, source_deal_id: str, new_payload: dict) -> bool:
    """Return True if the payload is different from the last stored version."""
    payload_str = json.dumps(new_payload, sort_keys=True)
    new_hash = hashlib.sha256(payload_str.encode()).hexdigest()[:16]

    latest = (
        db.query(DealRaw)
        .filter(DealRaw.source_id == source_id, DealRaw.source_deal_id == source_deal_id)
        .order_by(DealRaw.fetched_at.desc())
        .first()
    )
    if not latest:
        return True  # no prior record — treat as changed
    return latest.content_hash != new_hash


# ─────────────────────────────────────────────────────────────────────────────
# DealSchedule
# ─────────────────────────────────────────────────────────────────────────────


def create_deal_schedule(
    db: Session,
    *,
    deal_id: int,
    day_of_week: int | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    timezone: str = "UTC",
    notes: str | None = None,
) -> DealSchedule:
    schedule = DealSchedule(
        deal_id=deal_id,
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time,
        valid_from=valid_from,
        valid_until=valid_until,
        timezone=timezone,
        notes=notes,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


def get_deal_schedules(db: Session, deal_id: int) -> list[DealSchedule]:
    return db.query(DealSchedule).filter(DealSchedule.deal_id == deal_id).all()


def replace_deal_schedules(
    db: Session, deal_id: int, schedules: list[dict]
) -> list[DealSchedule]:
    """Delete existing schedules and insert new ones atomically."""
    db.query(DealSchedule).filter(DealSchedule.deal_id == deal_id).delete()
    created = []
    for s in schedules:
        created.append(create_deal_schedule(db, deal_id=deal_id, **s))
    db.commit()
    return created


# ─────────────────────────────────────────────────────────────────────────────
# IngestionRun + CrawlJob
# ─────────────────────────────────────────────────────────────────────────────


def create_ingestion_run(
    db: Session, *, source_id: int, crawl_job_id: int | None = None
) -> IngestionRun:
    run = IngestionRun(
        source_id=source_id,
        crawl_job_id=crawl_job_id,
        started_at=_utcnow(),
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_ingestion_run(
    db: Session,
    run_id: int,
    *,
    status: str,
    deals_fetched: int = 0,
    deals_inserted: int = 0,
    deals_updated: int = 0,
    deals_skipped: int = 0,
    records_raw: int = 0,
    error_msg: str | None = None,
    error_trace: str | None = None,
) -> None:
    run = db.get(IngestionRun, run_id)
    if not run:
        return
    now = _utcnow()
    run.finished_at = now
    run.status = status
    run.deals_fetched = deals_fetched
    run.deals_inserted = deals_inserted
    run.deals_updated = deals_updated
    run.deals_skipped = deals_skipped
    run.records_raw = records_raw
    run.error_msg = error_msg
    run.error_trace = error_trace
    if run.started_at:
        started = run.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        run.duration_seconds = (now - started).total_seconds()
    db.commit()


def get_recent_runs(
    db: Session, source_id: int, *, limit: int = 10
) -> list[IngestionRun]:
    return (
        db.query(IngestionRun)
        .filter(IngestionRun.source_id == source_id)
        .order_by(IngestionRun.started_at.desc())
        .limit(limit)
        .all()
    )


def get_active_crawl_jobs(db: Session) -> list[CrawlJob]:
    return db.query(CrawlJob).filter(CrawlJob.is_active == True).all()  # noqa: E712


def update_crawl_job_status(
    db: Session, job_id: int, *, success: bool, error: str | None = None
) -> None:
    job = db.get(CrawlJob, job_id)
    if not job:
        return
    now = _utcnow()
    job.last_run_at = now
    if success:
        job.last_success_at = now
        job.consecutive_failures = 0
    else:
        job.last_failure_at = now
        job.consecutive_failures = (job.consecutive_failures or 0) + 1
    db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# NormalizationLog
# ─────────────────────────────────────────────────────────────────────────────


def create_normalization_log(
    db: Session,
    *,
    deal_id: int,
    model: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    raw_response: str | None = None,
    fallback_used: bool = False,
) -> NormalizationLog:
    log = NormalizationLog(
        deal_id=deal_id,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        raw_response=raw_response,
        normalized_at=_utcnow(),
        fallback_used=fallback_used,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


# ─────────────────────────────────────────────────────────────────────────────
# UserPreference
# ─────────────────────────────────────────────────────────────────────────────


def get_preference(db: Session, session_id: str) -> UserPreference | None:
    return (
        db.query(UserPreference)
        .filter(UserPreference.session_id == session_id)
        .first()
    )


def get_or_create_preference(
    db: Session, session_id: str
) -> tuple[UserPreference, bool]:
    pref = get_preference(db, session_id)
    if pref:
        return pref, False

    pref = UserPreference(session_id=session_id)
    db.add(pref)
    db.commit()
    db.refresh(pref)
    return pref, True


def update_preference(
    db: Session, session_id: str, **updates: Any
) -> UserPreference | None:
    pref = get_preference(db, session_id)
    if not pref:
        return None
    allowed = {
        "city_id",
        "preferred_categories",
        "excluded_categories",
        "preferred_merchants",
        "max_price",
        "min_discount_pct",
        "radius_miles",
    }
    for k, v in updates.items():
        if k in allowed:
            setattr(pref, k, v)
    db.commit()
    db.refresh(pref)
    return pref


# ─────────────────────────────────────────────────────────────────────────────
# EventLog
# ─────────────────────────────────────────────────────────────────────────────


def log_event(
    db: Session,
    *,
    event_type: str,
    session_id: str | None = None,
    deal_id: int | None = None,
    venue_id: int | None = None,
    payload: dict | None = None,
    ip_hash: str | None = None,
) -> EventLog:
    event = EventLog(
        event_type=event_type,
        session_id=session_id,
        deal_id=deal_id,
        venue_id=venue_id,
        payload=payload,
        ip_hash=ip_hash,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def count_events(
    db: Session,
    *,
    deal_id: int | None = None,
    event_type: str | None = None,
    since: datetime | None = None,
) -> int:
    q = db.query(func.count(EventLog.id))
    if deal_id is not None:
        q = q.filter(EventLog.deal_id == deal_id)
    if event_type:
        q = q.filter(EventLog.event_type == event_type)
    if since:
        q = q.filter(EventLog.created_at >= since)
    return q.scalar() or 0


# ─────────────────────────────────────────────────────────────────────────────
# Freshness helpers
# ─────────────────────────────────────────────────────────────────────────────


def get_stale_deals(
    db: Session,
    *,
    max_age_hours: float = 48.0,
    limit: int = 500,
) -> list[Deal]:
    """Return active deals not seen in the last `max_age_hours`."""
    from datetime import timedelta

    cutoff = _utcnow() - timedelta(hours=max_age_hours)
    return (
        db.query(Deal)
        .filter(
            Deal.is_active == True,  # noqa: E712
            (Deal.last_seen_at < cutoff) | (Deal.last_seen_at == None),  # noqa: E711
        )
        .limit(limit)
        .all()
    )


def purge_expired_deals(db: Session) -> int:
    """Flag deals past their expiry as inactive. Returns count."""
    now = _utcnow()
    expired = (
        db.query(Deal)
        .filter(
            Deal.is_active == True,  # noqa: E712
            Deal.expires_at != None,  # noqa: E711
            Deal.expires_at < now,
        )
        .all()
    )
    for d in expired:
        d.is_active = False
    db.commit()
    return len(expired)


def get_deal_count_by_category(db: Session, *, active_only: bool = True) -> dict[str, int]:
    q = db.query(Deal.category, func.count(Deal.id)).group_by(Deal.category)
    if active_only:
        q = q.filter(Deal.is_active == True)  # noqa: E712
    return {cat or "Unknown": count for cat, count in q.all()}


# ─────────────────────────────────────────────────────────────────────────────
# Venue deduplication helpers
# ─────────────────────────────────────────────────────────────────────────────


def get_venues_for_dedup(
    db: Session,
    *,
    city_id: int | None = None,
    active_only: bool = True,
) -> list[Venue]:
    """Return venues with their source mapping counts pre-loaded for dedup."""
    q = db.query(Venue)
    if city_id is not None:
        q = q.filter(Venue.city_id == city_id)
    if active_only:
        q = q.filter(Venue.is_active == True)  # noqa: E712
    return q.order_by(Venue.name).all()


def count_venue_source_mappings(db: Session, venue_id: int) -> int:
    """Return how many source mappings a venue has."""
    return (
        db.query(func.count(VenueSourceMapping.id))
        .filter(VenueSourceMapping.venue_id == venue_id)
        .scalar()
        or 0
    )


def merge_venues(
    db: Session,
    *,
    primary_id: int,
    secondary_id: int,
) -> tuple[int, int]:
    """Absorb secondary venue into primary.

    Reassigns all VenueSourceMappings and Deals from secondary → primary,
    then marks the secondary venue as inactive.

    Returns (mappings_reassigned, deals_reassigned).
    """
    if primary_id == secondary_id:
        raise ValueError("primary_id and secondary_id must differ")

    primary = db.get(Venue, primary_id)
    secondary = db.get(Venue, secondary_id)

    if not primary or not secondary:
        raise ValueError("One or both venue IDs not found")

    # Reassign source mappings — skip if the primary already has a mapping for
    # the same (source_id, external_id) pair to avoid unique-constraint violation.
    mappings = (
        db.query(VenueSourceMapping)
        .filter(VenueSourceMapping.venue_id == secondary_id)
        .all()
    )
    mappings_moved = 0
    for m in mappings:
        conflict = (
            db.query(VenueSourceMapping)
            .filter(
                VenueSourceMapping.venue_id == primary_id,
                VenueSourceMapping.source_id == m.source_id,
                VenueSourceMapping.external_id == m.external_id,
            )
            .first()
        )
        if conflict:
            db.delete(m)
        else:
            m.venue_id = primary_id
            mappings_moved += 1

    # Reassign deals
    deals = db.query(Deal).filter(Deal.venue_id == secondary_id).all()
    for d in deals:
        d.venue_id = primary_id
    deals_moved = len(deals)

    # Mark secondary as inactive; update primary confidence
    secondary.is_active = False
    primary.confidence = max(primary.confidence, secondary.confidence)

    db.commit()
    return mappings_moved, deals_moved


def get_reports_summary(
    db: Session,
    *,
    city_slug: str | None = None,
    limit_deals: int = 20,
) -> dict:
    """Aggregate feedback report events.

    Returns:
        {
          "city": str | None,
          "total_reports": int,
          "by_type": {"report_incorrect": N, "report_expired": N},
          "by_source": {"dealnews": N, ...},
          "by_city": {"San Francisco": N, ...},
          "most_reported": [{"deal_id", "title", "source", "city",
                              "incorrect_reports", "expired_reports",
                              "total_reports", "is_active", "quality_score"}, ...]
        }
    """
    report_types = ("report_incorrect", "report_expired")

    base_q = db.query(EventLog).filter(EventLog.event_type.in_(report_types))

    # Optional city filter — join through Deal → City
    city_label: str | None = None
    if city_slug:
        city_obj = db.query(City).filter(City.slug == city_slug).first()
        if city_obj:
            city_label = city_obj.name
            base_q = base_q.join(Deal, Deal.id == EventLog.deal_id).join(
                City, City.id == Deal.city_id
            ).filter(City.id == city_obj.id)

    all_events = base_q.all()
    total = len(all_events)

    # by_type
    by_type: dict[str, int] = {}
    for et in report_types:
        by_type[et] = sum(1 for e in all_events if e.event_type == et)

    # Collect per-deal counts
    deal_counts: dict[int, dict] = {}
    for ev in all_events:
        if ev.deal_id is None:
            continue
        if ev.deal_id not in deal_counts:
            deal_counts[ev.deal_id] = {"report_incorrect": 0, "report_expired": 0}
        if ev.event_type in deal_counts[ev.deal_id]:
            deal_counts[ev.deal_id][ev.event_type] += 1

    # Fetch deal details for top reporters
    by_source: dict[str, int] = {}
    by_city: dict[str, int] = {}
    most_reported: list[dict] = []

    if deal_counts:
        sorted_deals = sorted(
            deal_counts.items(),
            key=lambda x: x[1]["report_incorrect"] + x[1]["report_expired"],
            reverse=True,
        )
        top_deal_ids = [d[0] for d in sorted_deals[:limit_deals]]
        deals = db.query(Deal).filter(Deal.id.in_(top_deal_ids)).all()
        deal_map = {d.id: d for d in deals}

        for deal_id, counts in sorted_deals[:limit_deals]:
            deal = deal_map.get(deal_id)
            if not deal:
                continue
            total_r = counts["report_incorrect"] + counts["report_expired"]
            src = deal.source.name if deal.source else None
            city_name = deal.city.name if deal.city else None

            if src:
                by_source[src] = by_source.get(src, 0) + total_r
            if city_name:
                by_city[city_name] = by_city.get(city_name, 0) + total_r

            most_reported.append(
                {
                    "deal_id": deal_id,
                    "title": deal.title,
                    "source": src,
                    "city": city_name,
                    "incorrect_reports": counts["report_incorrect"],
                    "expired_reports": counts["report_expired"],
                    "total_reports": total_r,
                    "is_active": deal.is_active,
                    "quality_score": deal.quality_score,
                }
            )

    return {
        "city": city_label or city_slug,
        "total_reports": total,
        "by_type": by_type,
        "by_source": by_source,
        "by_city": by_city,
        "most_reported": most_reported,
    }


def mark_stale_deals_expired(
    db: Session,
    *,
    stale_hours: float = 96.0,
) -> int:
    """Mark deals as inactive if last_seen_at is older than stale_hours.
    Returns count of deals affected.
    """
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=stale_hours)
    stale = (
        db.query(Deal)
        .filter(
            Deal.is_active == True,  # noqa: E712
            Deal.last_seen_at.isnot(None),
            Deal.last_seen_at < cutoff,
        )
        .all()
    )
    for deal in stale:
        deal.is_active = False
    db.commit()
    return len(stale)
