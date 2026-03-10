import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from happybites.api.deps import get_db
from happybites.api.geo import bounding_box, haversine_distance, is_deal_active_at
from happybites.db.models import City, Deal
from happybites.ranking.engine import DEFAULT_CONFIG, ScoreInput, score_deal
from happybites.schemas.api import (
    DealDetailResponse,
    DealListResponse,
    DealResponse,
    DealScheduleResponse,
    VenueResponse,
)

router = APIRouter()

SORT_COLUMNS = {
    "rank_score": Deal.rank_score,
    "discount_pct": Deal.discount_pct,
    "fetched_at": Deal.fetched_at,
}

# 1 meter in miles
_METERS_TO_MILES = 0.000621371


def _deal_to_response(deal: Deal, distance_m: float | None = None) -> DealResponse:
    return DealResponse(
        id=deal.id,
        title=deal.title,
        merchant=deal.merchant,
        category=deal.category,
        original_price=deal.original_price,
        deal_price=deal.deal_price,
        discount_pct=deal.discount_pct,
        currency=deal.currency,
        url=deal.url,
        image_url=deal.image_url,
        location=deal.location,
        is_online=deal.is_online,
        starts_at=deal.starts_at,
        expires_at=deal.expires_at,
        fetched_at=deal.fetched_at,
        first_seen_at=deal.first_seen_at,
        last_seen_at=deal.last_seen_at,
        rank_score=deal.rank_score,
        quality_score=deal.quality_score,
        confidence=deal.confidence,
        source=deal.source.name if deal.source else None,
        city_id=deal.city_id,
        venue_id=deal.venue_id,
        tags=json.loads(deal.tags) if deal.tags else [],
        is_verified=deal.is_verified,
        distance_m=distance_m,
    )


def _deal_to_detail(deal: Deal) -> DealDetailResponse:
    base = _deal_to_response(deal)
    schedules = [DealScheduleResponse.model_validate(s) for s in deal.schedules]
    venue = VenueResponse.model_validate(deal.venue) if deal.venue else None
    return DealDetailResponse(
        **base.model_dump(),
        description=deal.description,
        source_url=deal.source_url,
        normalized_at=deal.normalized_at,
        ai_normalized=any(not log.fallback_used for log in deal.normalization_logs),
        schedules=schedules,
        venue=venue,
    )


def _active_query(db: Session):
    return (
        db.query(Deal)
        .options(joinedload(Deal.source))
        .filter(Deal.is_active == True)  # noqa: E712
    )


# ── /deals/nearby ──────────────────────────────────────────────────────────────


@router.get("/nearby", response_model=DealListResponse)
def deals_nearby(
    db: Annotated[Session, Depends(get_db)],
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_m: float = Query(1609.34, ge=1, le=804_672),  # default 1 mi, max 500 mi
    time: datetime | None = Query(None),
    city: str | None = None,
    open_now: bool | None = Query(None),
    deal_type: str | None = None,
    category: str | None = None,
    preferred_categories: str | None = Query(None, description="Comma-separated list"),
    debug: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    radius_miles = radius_m * _METERS_TO_MILES
    check_time = time or datetime.now(timezone.utc)
    min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lng, radius_miles)

    query = (
        db.query(Deal)
        .options(
            joinedload(Deal.source),
            joinedload(Deal.schedules),
            joinedload(Deal.venue),
        )
        .filter(
            Deal.is_active == True,  # noqa: E712
            Deal.lat.isnot(None),
            Deal.lon.isnot(None),
            Deal.lat.between(min_lat, max_lat),
            Deal.lon.between(min_lon, max_lon),
        )
    )
    if city:
        query = query.join(Deal.city).filter(City.slug.ilike(f"%{city}%"))
    if deal_type:
        query = query.filter(Deal.category == deal_type)
    if category:
        query = query.filter(Deal.category == category)

    # Pull up to 500 candidates from the bounding box, then exact-filter in Python
    candidates = query.limit(500).all()

    pref_categories = [c.strip() for c in preferred_categories.split(",")] if preferred_categories else []

    # (deal, dist_meters, rank_score, reasons, debug_contributions)
    ranked: list[tuple[Deal, float, float, list[str], dict[str, float]]] = []
    for deal in candidates:
        dist_miles = haversine_distance(lat, lng, deal.lat, deal.lon)  # type: ignore[arg-type]
        if dist_miles > radius_miles:
            continue
        is_active = is_deal_active_at(deal, check_time)
        if open_now is True and not is_active:
            continue
        if open_now is False and is_active:
            continue

        venue_source_count = 1
        if deal.venue and hasattr(deal.venue, "source_mappings"):
            venue_source_count = max(1, len(deal.venue.source_mappings))

        inp = ScoreInput(
            deal_id=deal.id,
            discount_pct=deal.discount_pct,
            fetched_at=deal.fetched_at,
            last_seen_at=deal.last_seen_at,
            quality_score=deal.quality_score,
            confidence=deal.confidence,
            category=deal.category,
            is_open_now=is_active if deal.schedules else None,
            distance_miles=dist_miles,
            venue_source_count=venue_source_count,
            preferred_categories=pref_categories,
            now=check_time,
        )
        result = score_deal(inp, DEFAULT_CONFIG)
        ranked.append((deal, dist_miles / _METERS_TO_MILES, result.score, result.reasons, result.debug))

    ranked.sort(key=lambda x: -x[2])  # sort by rank_score descending

    total = len(ranked)
    page = ranked[offset : offset + limit]

    items = []
    for deal, dist_m, _score, reasons, dbg in page:
        resp = _deal_to_response(deal, distance_m=dist_m)
        resp.rank_reasons = reasons
        if debug:
            resp.rank_debug = dbg
        items.append(resp)

    return DealListResponse(total=total, limit=limit, offset=offset, items=items)


# ── /deals/search ──────────────────────────────────────────────────────────────


@router.get("/search", response_model=DealListResponse)
def deals_search(
    db: Annotated[Session, Depends(get_db)],
    q: str | None = None,
    lat: float | None = Query(None, ge=-90, le=90),
    lng: float | None = Query(None, ge=-180, le=180),
    radius_m: float | None = Query(None, ge=1, le=804_672),
    category: str | None = None,
    max_price: float | None = Query(None, ge=0),
    min_discount: float | None = Query(None, ge=0, le=100),
    city: str | None = None,
    is_online: bool | None = None,
    sort: str = Query("rank_score", pattern="^(rank_score|discount_pct|fetched_at)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = _active_query(db)

    if q:
        term = f"%{q}%"
        query = query.filter(
            or_(
                Deal.title.ilike(term),
                Deal.description.ilike(term),
                Deal.merchant.ilike(term),
            )
        )
    if category:
        query = query.filter(Deal.category == category)
    if max_price is not None:
        query = query.filter(Deal.deal_price <= max_price)
    if min_discount is not None:
        query = query.filter(Deal.discount_pct >= min_discount)
    if city:
        query = query.join(Deal.city).filter(City.slug.ilike(f"%{city}%"))
    if is_online is not None:
        query = query.filter(Deal.is_online == is_online)
    if lat is not None and lng is not None and radius_m is not None:
        radius_miles = radius_m * _METERS_TO_MILES
        min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lng, radius_miles)
        query = query.filter(
            Deal.lat.isnot(None),
            Deal.lat.between(min_lat, max_lat),
            Deal.lon.between(min_lon, max_lon),
        )

    total = query.count()
    sort_col = SORT_COLUMNS.get(sort, Deal.rank_score)
    deals = query.order_by(sort_col.desc().nulls_last()).offset(offset).limit(limit).all()

    return DealListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[_deal_to_response(d) for d in deals],
    )


# ── /deals (list) ──────────────────────────────────────────────────────────────


@router.get("", response_model=DealListResponse)
def list_deals(
    db: Annotated[Session, Depends(get_db)],
    category: str | None = None,
    max_price: float | None = Query(None, ge=0),
    min_discount: float | None = Query(None, ge=0, le=100),
    location: str | None = None,
    sort: str = Query("rank_score", pattern="^(rank_score|discount_pct|fetched_at)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = _active_query(db)

    if category:
        query = query.filter(Deal.category == category)
    if max_price is not None:
        query = query.filter(Deal.deal_price <= max_price)
    if min_discount is not None:
        query = query.filter(Deal.discount_pct >= min_discount)
    if location:
        if location.lower() == "online":
            query = query.filter(Deal.location == None)  # noqa: E711
        else:
            query = query.filter(Deal.location.ilike(f"%{location}%"))

    total = query.count()
    sort_col = SORT_COLUMNS.get(sort, Deal.rank_score)
    deals = query.order_by(sort_col.desc().nulls_last()).offset(offset).limit(limit).all()

    return DealListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[_deal_to_response(d) for d in deals],
    )


# ── /deals/{deal_id} ───────────────────────────────────────────────────────────


@router.get("/{deal_id}", response_model=DealDetailResponse)
def get_deal(deal_id: int, db: Annotated[Session, Depends(get_db)]):
    deal = (
        db.query(Deal)
        .options(
            joinedload(Deal.source),
            joinedload(Deal.schedules),
            joinedload(Deal.normalization_logs),
            joinedload(Deal.venue),
        )
        .filter(Deal.id == deal_id)
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return _deal_to_detail(deal)
