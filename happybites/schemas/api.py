"""
Pydantic schemas for API request / response models.

Naming convention:
  *Response  — read models (returned by API)
  *Create    — write models (accepted by POST endpoints)
  *Update    — patch models (accepted by PATCH/PUT endpoints)
  *List      — paginated list wrappers
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


# ─────────────────────────────────────────────────────────────────────────────
# City
# ─────────────────────────────────────────────────────────────────────────────


class CityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    state: str | None
    country: str
    slug: str
    lat: float | None
    lon: float | None
    timezone: str | None
    is_active: bool


# ─────────────────────────────────────────────────────────────────────────────
# Source
# ─────────────────────────────────────────────────────────────────────────────


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    display_name: str | None
    type: str
    base_url: str | None
    city_id: int | None
    fetch_interval: int
    last_fetched_at: datetime | None
    last_successful_at: datetime | None
    consecutive_failures: int
    confidence_weight: float
    is_active: bool


# ─────────────────────────────────────────────────────────────────────────────
# Venue
# ─────────────────────────────────────────────────────────────────────────────


class VenueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str | None
    city_id: int | None
    address: str | None
    lat: float | None
    lon: float | None
    category: str | None
    phone: str | None
    website: str | None
    image_url: str | None
    confidence: float
    is_active: bool


class VenueDetailResponse(VenueResponse):
    city: CityResponse | None = None
    deal_count: int = 0


class VenueSourceMappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    venue_id: int
    source_id: int
    external_id: str
    external_url: str | None
    last_seen_at: datetime | None
    confidence: float


# ─────────────────────────────────────────────────────────────────────────────
# DealSchedule
# ─────────────────────────────────────────────────────────────────────────────

DAY_NAMES = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}


class DealScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    deal_id: int
    day_of_week: int | None
    day_name: str | None = None
    start_time: str | None
    end_time: str | None
    valid_from: datetime | None
    valid_until: datetime | None
    timezone: str
    notes: str | None

    @model_validator(mode="after")
    def populate_day_name(self) -> "DealScheduleResponse":
        if self.day_of_week is not None:
            self.day_name = DAY_NAMES.get(self.day_of_week)
        return self


class DealScheduleCreate(BaseModel):
    day_of_week: int | None = None
    start_time: str | None = None   # "HH:MM"
    end_time: str | None = None     # "HH:MM"
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    timezone: str = "UTC"
    notes: str | None = None

    @field_validator("day_of_week")
    @classmethod
    def validate_day(cls, v: int | None) -> int | None:
        if v is not None and v not in range(7):
            raise ValueError("day_of_week must be 0 (Mon) – 6 (Sun)")
        return v

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time_format(cls, v: str | None) -> str | None:
        if v is not None:
            parts = v.split(":")
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                raise ValueError("Time must be in HH:MM format")
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError("Invalid time value")
        return v


# ─────────────────────────────────────────────────────────────────────────────
# Deal
# ─────────────────────────────────────────────────────────────────────────────


class DealResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    merchant: str | None
    category: str | None
    original_price: float | None
    deal_price: float | None
    discount_pct: float | None
    currency: str
    url: str
    image_url: str | None
    location: str | None
    is_online: bool
    starts_at: datetime | None
    expires_at: datetime | None
    fetched_at: datetime
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    rank_score: float | None
    quality_score: float | None
    confidence: float | None
    source: str | None
    city_id: int | None
    venue_id: int | None
    tags: list[str]
    is_verified: bool
    # Populated only by /deals/nearby; None for all other endpoints
    distance_m: float | None = None
    # Populated by ranked endpoints
    rank_reasons: list[str] | None = None
    rank_debug: dict[str, float] | None = None


class DealDetailResponse(DealResponse):
    description: str | None
    source_url: str | None
    normalized_at: datetime | None
    ai_normalized: bool
    schedules: list[DealScheduleResponse] = []
    venue: VenueResponse | None = None


class DealListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[DealResponse]


# ─────────────────────────────────────────────────────────────────────────────
# DealRaw
# ─────────────────────────────────────────────────────────────────────────────


class DealRawResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    deal_id: int | None
    source_deal_id: str
    raw_url: str | None
    http_status: int | None
    content_hash: str | None
    fetched_at: datetime
    # raw_payload intentionally excluded from list responses (large)


class DealRawDetailResponse(DealRawResponse):
    raw_payload: dict[str, Any]


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion
# ─────────────────────────────────────────────────────────────────────────────


class IngestionRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    source_name: str
    crawl_job_id: int | None
    started_at: datetime
    finished_at: datetime | None
    status: str
    deals_fetched: int
    deals_inserted: int
    deals_updated: int
    deals_skipped: int
    records_raw: int
    duration_seconds: float | None
    error_msg: str | None


class IngestTriggerRequest(BaseModel):
    source_id: int | None = None


class IngestTriggerResponse(BaseModel):
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# UserPreference
# ─────────────────────────────────────────────────────────────────────────────


class UserPreferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    city_id: int | None
    preferred_categories: list[str] | None
    excluded_categories: list[str] | None
    preferred_merchants: list[str] | None
    max_price: float | None
    min_discount_pct: float | None
    radius_miles: float
    created_at: datetime
    updated_at: datetime


class UserPreferenceUpdate(BaseModel):
    city_id: int | None = None
    preferred_categories: list[str] | None = None
    excluded_categories: list[str] | None = None
    preferred_merchants: list[str] | None = None
    max_price: float | None = None
    min_discount_pct: float | None = None
    radius_miles: float | None = None

    @field_validator("min_discount_pct")
    @classmethod
    def validate_discount(cls, v: float | None) -> float | None:
        if v is not None and not (0 <= v <= 100):
            raise ValueError("min_discount_pct must be between 0 and 100")
        return v

    @field_validator("radius_miles")
    @classmethod
    def validate_radius(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("radius_miles must be positive")
        return v


# ─────────────────────────────────────────────────────────────────────────────
# EventLog
# ─────────────────────────────────────────────────────────────────────────────

VALID_EVENT_TYPES = frozenset(
    {
        "click",
        "view",
        "search",
        "filter",
        "report",
        "feedback",
        "ingest_trigger",
        "save",
        "report_incorrect",
        "report_expired",
        "rating",
    }
)


class EventLogCreate(BaseModel):
    event_type: str
    session_id: str | None = None
    deal_id: int | None = None
    venue_id: int | None = None
    payload: dict[str, Any] | None = None

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        if v not in VALID_EVENT_TYPES:
            raise ValueError(f"event_type must be one of {sorted(VALID_EVENT_TYPES)}")
        return v

    @model_validator(mode="after")
    def validate_rating_payload(self) -> "EventLogCreate":
        if self.event_type == "rating":
            if (
                self.payload is None
                or "value" not in self.payload
                or self.payload["value"] not in range(1, 6)
            ):
                raise ValueError(
                    "rating events require payload with 'value' between 1 and 5 (inclusive)"
                )
        return self


class EventLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    session_id: str | None
    deal_id: int | None
    venue_id: int | None
    payload: dict[str, Any] | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Health + Admin
# ─────────────────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str       # "ok" | "degraded"
    db_reachable: bool
    deals_total: int
    deals_fresh_24h: int
    oldest_deal_hours: float | None
    stale: bool


class AdminStatsResponse(BaseModel):
    total_deals: int
    active_deals: int
    ai_normalized: int
    fallback_normalized: int
    total_runs: int
    failed_runs: int
    deals_by_category: dict[str, int]
    sources: list[dict]


class ResetResponse(BaseModel):
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# Admin — mark_expired / ingest_status
# ─────────────────────────────────────────────────────────────────────────────


class MarkExpiredRequest(BaseModel):
    before: datetime | None = None  # if None, uses server time


class SourceStatusItem(BaseModel):
    source_id: int
    source_name: str
    last_fetched_at: datetime | None
    last_successful_at: datetime | None
    consecutive_failures: int
    deals_active: int
    deals_fresh_24h: int
    is_active: bool


class CityStatusItem(BaseModel):
    city_id: int
    city_name: str
    deals_active: int
    deals_fresh_24h: int
    oldest_deal_hours: float | None


class IngestStatusResponse(BaseModel):
    checked_at: datetime
    total_active_deals: int
    total_fresh_24h: int
    stale: bool
    sources: list[SourceStatusItem]
    cities: list[CityStatusItem]


# ─────────────────────────────────────────────────────────────────────────────
# Venue deduplication
# ─────────────────────────────────────────────────────────────────────────────


class MatchReasonResponse(BaseModel):
    field: str
    description: str
    score_delta: float


class VenueSnapshotResponse(BaseModel):
    id: int
    name: str
    address: str | None
    phone: str | None
    lat: float | None
    lon: float | None
    city_id: int | None
    source_count: int


class VenueMatchResponse(BaseModel):
    venue_a: VenueSnapshotResponse
    venue_b: VenueSnapshotResponse
    match_score: float
    confidence: str          # "high" | "review"
    reasons: list[MatchReasonResponse]
    fields_used: list[str]
    is_chain_collision: bool


class VenueMatchesResponse(BaseModel):
    city: str | None
    total_venues_scanned: int
    candidates: list[VenueMatchResponse]


class MergeVenuesRequest(BaseModel):
    primary_venue_id: int    # venue to keep
    secondary_venue_id: int  # venue to absorb into primary
    force: bool = False      # required to merge chain collisions


class MergeVenuesResponse(BaseModel):
    message: str
    primary_venue_id: int
    mappings_reassigned: int
    deals_reassigned: int


# ─────────────────────────────────────────────────────────────────────────────
# Feedback / Reports
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────


class RunIngestRequest(BaseModel):
    sources: list[str] | None = None
    fixture_mode: bool = True


class OrchestratorResultResponse(BaseModel):
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    sources_run: list[str]
    total_fetched: int
    total_inserted: int
    total_updated: int
    total_errors: int
    errors: list[str]
    run_ids: list[int]


class ReportedDealItem(BaseModel):
    deal_id: int
    title: str
    source: str | None
    city: str | None
    incorrect_reports: int
    expired_reports: int
    total_reports: int
    is_active: bool
    quality_score: float | None


class ReportsSummaryResponse(BaseModel):
    city: str | None
    total_reports: int
    by_type: dict[str, int]
    by_source: dict[str, int]
    by_city: dict[str, int]
    most_reported: list[ReportedDealItem]
