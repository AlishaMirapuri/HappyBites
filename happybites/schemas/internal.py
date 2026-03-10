"""
Internal schemas — used by the ingestion pipeline, not exposed via the API.

These describe data flowing between pipeline stages:
  Collector → RawDeal → Normalizer → NormalizedDeal → DB
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline input / output
# ─────────────────────────────────────────────────────────────────────────────


class NormalizedDeal(BaseModel):
    """
    Output of the Normalizer. All fields are optional because normalization
    may only partially succeed (especially with regex fallback).

    Private fields prefixed with _ carry Claude API metadata for the
    NormalizationLog; they're stripped before writing to the deals table.
    """

    category: str | None = None
    tags: list[str] = []
    merchant: str | None = None
    original_price: float | None = None
    deal_price: float | None = None
    discount_pct: float | None = None
    expires_at: datetime | None = None
    quality_score: float | None = None
    confidence: float | None = None

    # Claude metadata (written to NormalizationLog, not to deals table)
    _model: str | None = None
    _prompt_tokens: int | None = None
    _completion_tokens: int | None = None
    _raw_response: str | None = None
    _fallback_used: bool = False

    @field_validator("quality_score", "confidence")
    @classmethod
    def clamp_score(cls, v: float | None) -> float | None:
        if v is not None:
            return round(max(0.0, min(1.0, v)), 4)
        return v


class DealFilterParams(BaseModel):
    """
    Filter parameters for the deal listing pipeline.
    Shared between the API query-param layer and internal ranking calls.
    """

    city_id: int | None = None
    venue_id: int | None = None
    category: str | None = None
    max_price: float | None = None
    min_discount: float | None = None
    is_online: bool | None = None
    sort: str = "rank_score"
    limit: int = 50
    offset: int = 0

    @field_validator("sort")
    @classmethod
    def validate_sort(cls, v: str) -> str:
        allowed = {"rank_score", "discount_pct", "fetched_at", "last_seen_at"}
        if v not in allowed:
            raise ValueError(f"sort must be one of {sorted(allowed)}")
        return v

    @field_validator("limit")
    @classmethod
    def validate_limit(cls, v: int) -> int:
        return max(1, min(200, v))


class IngestionStats(BaseModel):
    """Result stats returned by the scheduler after a run."""

    source: str
    run_id: int | None = None
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    records_raw: int = 0
    duration_seconds: float | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None


class RawPayload(BaseModel):
    """
    Structured wrapper for data stored in DealRaw.raw_payload.

    Captures everything from the source response so we can re-normalize
    without re-fetching.
    """

    source_name: str
    source_deal_id: str
    title: str
    url: str
    description: str | None = None
    image_url: str | None = None
    merchant: str | None = None
    original_price: float | None = None
    deal_price: float | None = None
    expires_at: str | None = None  # ISO string from source
    raw_html: str | None = None    # full HTML for scraper sources
    extra: dict[str, Any] = {}    # source-specific fields


# ─────────────────────────────────────────────────────────────────────────────
# Geo
# ─────────────────────────────────────────────────────────────────────────────


class GeoPoint(BaseModel):
    lat: float
    lon: float

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not (-90 <= v <= 90):
            raise ValueError("lat must be between -90 and 90")
        return v

    @field_validator("lon")
    @classmethod
    def validate_lon(cls, v: float) -> float:
        if not (-180 <= v <= 180):
            raise ValueError("lon must be between -180 and 180")
        return v


class GeoFilter(BaseModel):
    """Used to build proximity-based deal queries."""

    origin: GeoPoint
    radius_miles: float = 25.0

    @field_validator("radius_miles")
    @classmethod
    def validate_radius(cls, v: float) -> float:
        if v <= 0 or v > 500:
            raise ValueError("radius_miles must be between 0 and 500")
        return v
