"""
Database ORM models.

All timestamps are stored in UTC (timezone-naive in SQLite; use timezone.utc in Python).
JSON columns use SQLAlchemy's JSON type — TEXT in SQLite, native JSON in Postgres.
No code changes required to switch backends; only DATABASE_URL changes.

Model dependency order (FK constraints):
  City → Source → CrawlJob
  City → Venue → VenueSourceMapping
  Source, Venue, City → Deal → DealRaw, DealSchedule, NormalizationLog, EventLog
  Source, CrawlJob → IngestionRun
  City → UserPreference
"""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from happybites.db.engine import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Mixins
# ─────────────────────────────────────────────────────────────────────────────


class TimestampMixin:
    """Adds created_at / updated_at to any model."""

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# City
# ─────────────────────────────────────────────────────────────────────────────


class City(TimestampMixin, Base):
    """Canonical city entity. Deals and Venues belong to a city."""

    __tablename__ = "cities"
    __table_args__ = (
        Index("ix_cities_slug", "slug"),
        Index("ix_cities_country_state", "country", "state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str | None] = mapped_column(String(64))
    country: Mapped[str] = mapped_column(String(64), default="US", nullable=False)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    timezone: Mapped[str | None] = mapped_column(String(64))  # e.g. "America/New_York"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    sources: Mapped[list["Source"]] = relationship("Source", back_populates="city")
    venues: Mapped[list["Venue"]] = relationship("Venue", back_populates="city")
    deals: Mapped[list["Deal"]] = relationship("Deal", back_populates="city")
    user_preferences: Mapped[list["UserPreference"]] = relationship(
        "UserPreference", back_populates="city"
    )

    def __repr__(self) -> str:
        return f"<City {self.slug}>"


# ─────────────────────────────────────────────────────────────────────────────
# Source
# ─────────────────────────────────────────────────────────────────────────────


class Source(TimestampMixin, Base):
    """
    An ingestion source (RSS feed, API, scraper, seed file).

    `confidence_weight` is a multiplier applied to quality scores from this
    source — lower trust sources produce lower-confidence deals.
    `config` holds source-specific configuration (auth tokens, selectors, etc.)
    stored as JSON so the schema stays stable as sources evolve.
    """

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # rss|api|scrape|seed
    base_url: Mapped[str | None] = mapped_column(String(512))
    city_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("cities.id"))
    fetch_interval: Mapped[int] = mapped_column(Integer, default=7200)  # seconds
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_successful_at: Mapped[datetime | None] = mapped_column(DateTime)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict | None] = mapped_column(JSON)  # source-specific config blob
    confidence_weight: Mapped[float] = mapped_column(Float, default=1.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    city: Mapped["City | None"] = relationship("City", back_populates="sources")
    deals: Mapped[list["Deal"]] = relationship("Deal", back_populates="source")
    runs: Mapped[list["IngestionRun"]] = relationship("IngestionRun", back_populates="source")
    crawl_jobs: Mapped[list["CrawlJob"]] = relationship("CrawlJob", back_populates="source")
    raw_records: Mapped[list["DealRaw"]] = relationship("DealRaw", back_populates="source")
    venue_mappings: Mapped[list["VenueSourceMapping"]] = relationship(
        "VenueSourceMapping", back_populates="source"
    )

    def __repr__(self) -> str:
        return f"<Source {self.name}>"


# ─────────────────────────────────────────────────────────────────────────────
# CrawlJob
# ─────────────────────────────────────────────────────────────────────────────


class CrawlJob(TimestampMixin, Base):
    """
    Defines a discrete crawl target within a source.

    A Source can have many CrawlJobs — e.g. DealNews has separate jobs per
    category. Each job is independently scheduled and tracked.
    """

    __tablename__ = "crawl_jobs"
    __table_args__ = (Index("ix_crawl_jobs_source_id", "source_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    target_url: Mapped[str | None] = mapped_column(String(1024))
    config: Mapped[dict | None] = mapped_column(JSON)  # selectors, headers, pagination
    schedule_cron: Mapped[str | None] = mapped_column(String(64))  # "0 */2 * * *"
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    source: Mapped["Source"] = relationship("Source", back_populates="crawl_jobs")
    runs: Mapped[list["IngestionRun"]] = relationship("IngestionRun", back_populates="crawl_job")
    raw_records: Mapped[list["DealRaw"]] = relationship("DealRaw", back_populates="crawl_job")

    def __repr__(self) -> str:
        return f"<CrawlJob {self.name} source={self.source_id}>"


# ─────────────────────────────────────────────────────────────────────────────
# Venue
# ─────────────────────────────────────────────────────────────────────────────


class Venue(TimestampMixin, Base):
    """
    Canonical venue entity (restaurant, retailer, bar, etc.).

    Multiple sources may refer to the same physical venue under different IDs.
    VenueSourceMapping links external IDs back here.
    `confidence` reflects entity-resolution certainty (1.0 = verified match).
    """

    __tablename__ = "venues"
    __table_args__ = (
        Index("ix_venues_city_id", "city_id"),
        Index("ix_venues_category", "category"),
        Index("ix_venues_lat_lon", "lat", "lon"),  # geo proximity queries
        Index("ix_venues_slug", "slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(256), unique=True)
    city_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("cities.id"))
    address: Mapped[str | None] = mapped_column(String(512))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    category: Mapped[str | None] = mapped_column(String(64))  # restaurant|bar|retail|...
    phone: Mapped[str | None] = mapped_column(String(32))
    website: Mapped[str | None] = mapped_column(String(512))
    image_url: Mapped[str | None] = mapped_column(String(1024))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    city: Mapped["City | None"] = relationship("City", back_populates="venues")
    deals: Mapped[list["Deal"]] = relationship("Deal", back_populates="venue")
    source_mappings: Mapped[list["VenueSourceMapping"]] = relationship(
        "VenueSourceMapping", back_populates="venue"
    )
    event_logs: Mapped[list["EventLog"]] = relationship("EventLog", back_populates="venue")

    def __repr__(self) -> str:
        return f"<Venue {self.name}>"


# ─────────────────────────────────────────────────────────────────────────────
# VenueSourceMapping
# ─────────────────────────────────────────────────────────────────────────────


class VenueSourceMapping(Base):
    """
    Links a canonical Venue to an external ID in a Source system.

    Example: Venue "Tacos El Gordo" ↔ Yelp ID "tacos-el-gordo-san-francisco"
    `confidence` reflects how certain we are that this external record is the
    canonical venue (set by entity resolution logic).
    """

    __tablename__ = "venue_source_mappings"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_venue_mapping_per_source"),
        Index("ix_vsm_venue_id", "venue_id"),
        Index("ix_vsm_source_external", "source_id", "external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    venue_id: Mapped[int] = mapped_column(Integer, ForeignKey("venues.id"), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    external_url: Mapped[str | None] = mapped_column(String(1024))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)

    venue: Mapped["Venue"] = relationship("Venue", back_populates="source_mappings")
    source: Mapped["Source"] = relationship("Source", back_populates="venue_mappings")

    def __repr__(self) -> str:
        return f"<VenueSourceMapping venue={self.venue_id} source={self.source_id} ext={self.external_id}>"


# ─────────────────────────────────────────────────────────────────────────────
# Deal
# ─────────────────────────────────────────────────────────────────────────────


class Deal(Base):
    """
    Canonical normalized deal record.

    Provenance chain: Source → DealRaw → Deal → NormalizationLog
    - `first_seen_at`: when we first ingested this deal
    - `last_seen_at`: most recent fetch that included this deal (freshness)
    - `confidence`: normalization confidence (1.0 = AI-extracted, 0.5 = regex)
    - `quality_score`: data completeness (set by normalizer)
    - `rank_score`: personalized relevance (set by ranker, re-computed periodically)
    - `freshness_score`: recency component of rank (derived from last_seen_at)
    """

    __tablename__ = "deals"
    __table_args__ = (
        UniqueConstraint("source_id", "source_deal_id", name="uq_deal_per_source"),
        Index("ix_deals_city_id", "city_id"),
        Index("ix_deals_venue_id", "venue_id"),
        Index("ix_deals_category", "category"),
        Index("ix_deals_expires_at", "expires_at"),
        Index("ix_deals_fetched_at", "fetched_at"),
        Index("ix_deals_last_seen_at", "last_seen_at"),
        Index("ix_deals_rank_score", "rank_score"),
        Index("ix_deals_lat_lon", "lat", "lon"),
        # Compound: the most common query pattern
        Index("ix_deals_active_rank", "is_active", "rank_score"),
        Index("ix_deals_active_category", "is_active", "category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Foreign keys
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    venue_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("venues.id"))
    city_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("cities.id"))

    # Source provenance
    source_deal_id: Mapped[str] = mapped_column(String(256), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024))  # URL at origin source

    # Core content
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1024))
    merchant: Mapped[str | None] = mapped_column(String(256))
    category: Mapped[str | None] = mapped_column(String(64))
    tags: Mapped[str | None] = mapped_column(Text)  # JSON array (legacy Text; use JSON for new cols)

    # Pricing
    original_price: Mapped[float | None] = mapped_column(Float)
    deal_price: Mapped[float | None] = mapped_column(Float)
    discount_pct: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="USD")

    # Location (coordinates for geo queries; location text for display)
    location: Mapped[str | None] = mapped_column(String(128))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    radius_miles: Mapped[float | None] = mapped_column(Float)
    is_online: Mapped[bool] = mapped_column(Boolean, default=True)

    # Timing
    starts_at: Mapped[datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime)  # set on first insert
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)   # updated on re-fetch
    normalized_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Scoring
    quality_score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)      # normalization confidence
    freshness_score: Mapped[float | None] = mapped_column(Float)  # decayed recency score
    rank_score: Mapped[float | None] = mapped_column(Float)       # final composite score

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    source: Mapped["Source"] = relationship("Source", back_populates="deals")
    venue: Mapped["Venue | None"] = relationship("Venue", back_populates="deals")
    city: Mapped["City | None"] = relationship("City", back_populates="deals")
    raw_records: Mapped[list["DealRaw"]] = relationship("DealRaw", back_populates="deal")
    schedules: Mapped[list["DealSchedule"]] = relationship("DealSchedule", back_populates="deal")
    normalization_logs: Mapped[list["NormalizationLog"]] = relationship(
        "NormalizationLog", back_populates="deal"
    )
    event_logs: Mapped[list["EventLog"]] = relationship("EventLog", back_populates="deal")

    def __repr__(self) -> str:
        return f"<Deal {self.id}: {self.title[:40]}>"


# ─────────────────────────────────────────────────────────────────────────────
# DealRaw
# ─────────────────────────────────────────────────────────────────────────────


class DealRaw(Base):
    """
    Immutable raw payload as received from the source.

    Written at fetch time, before normalization. Linked to a Deal after
    normalization succeeds. Retained for:
      - Re-normalization when the schema changes
      - Debugging normalization failures
      - Change detection via content_hash
    """

    __tablename__ = "deals_raw"
    __table_args__ = (
        Index("ix_deals_raw_source_id", "source_id"),
        Index("ix_deals_raw_fetched_at", "fetched_at"),
        Index("ix_deals_raw_content_hash", "content_hash"),
        Index("ix_deals_raw_deal_id", "deal_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    deal_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("deals.id"))
    crawl_job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("crawl_jobs.id"))
    source_deal_id: Mapped[str] = mapped_column(String(256), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)  # full raw response
    raw_url: Mapped[str | None] = mapped_column(String(1024))
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(64))  # SHA-256[:16] for change detection
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    source: Mapped["Source"] = relationship("Source", back_populates="raw_records")
    deal: Mapped["Deal | None"] = relationship("Deal", back_populates="raw_records")
    crawl_job: Mapped["CrawlJob | None"] = relationship("CrawlJob", back_populates="raw_records")

    def __repr__(self) -> str:
        return f"<DealRaw source={self.source_id} deal={self.deal_id} hash={self.content_hash}>"


# ─────────────────────────────────────────────────────────────────────────────
# DealSchedule
# ─────────────────────────────────────────────────────────────────────────────


class DealSchedule(Base):
    """
    Time windows during which a deal is valid.

    A deal can have multiple schedule rows — one per valid window.
    day_of_week: 0=Monday … 6=Sunday; None = valid every day.
    start_time / end_time: "HH:MM" 24h strings; None = all day.
    valid_from / valid_until: absolute datetime bounds (deal's meta expiry).
    """

    __tablename__ = "deal_schedules"
    __table_args__ = (Index("ix_deal_schedules_deal_id", "deal_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(Integer, ForeignKey("deals.id"), nullable=False)
    day_of_week: Mapped[int | None] = mapped_column(Integer)   # 0–6; None = all days
    start_time: Mapped[str | None] = mapped_column(String(8))  # "HH:MM"
    end_time: Mapped[str | None] = mapped_column(String(8))    # "HH:MM"
    valid_from: Mapped[datetime | None] = mapped_column(DateTime)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    notes: Mapped[str | None] = mapped_column(Text)

    deal: Mapped["Deal"] = relationship("Deal", back_populates="schedules")

    def __repr__(self) -> str:
        return f"<DealSchedule deal={self.deal_id} day={self.day_of_week} {self.start_time}-{self.end_time}>"


# ─────────────────────────────────────────────────────────────────────────────
# IngestionRun
# ─────────────────────────────────────────────────────────────────────────────


class IngestionRun(Base):
    """Audit log for a single ingestion execution."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        Index("ix_ingestion_runs_source_id", "source_id"),
        Index("ix_ingestion_runs_started_at", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    crawl_job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("crawl_jobs.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|success|error|skipped
    deals_fetched: Mapped[int] = mapped_column(Integer, default=0)
    deals_inserted: Mapped[int] = mapped_column(Integer, default=0)
    deals_updated: Mapped[int] = mapped_column(Integer, default=0)
    deals_skipped: Mapped[int] = mapped_column(Integer, default=0)
    records_raw: Mapped[int] = mapped_column(Integer, default=0)      # DealRaw rows written
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    error_msg: Mapped[str | None] = mapped_column(Text)
    error_trace: Mapped[str | None] = mapped_column(Text)

    source: Mapped["Source"] = relationship("Source", back_populates="runs")
    crawl_job: Mapped["CrawlJob | None"] = relationship("CrawlJob", back_populates="runs")

    def __repr__(self) -> str:
        return f"<IngestionRun {self.id} source={self.source_id} status={self.status}>"


# ─────────────────────────────────────────────────────────────────────────────
# NormalizationLog
# ─────────────────────────────────────────────────────────────────────────────


class NormalizationLog(Base):
    """Provenance log for every AI/regex normalization call."""

    __tablename__ = "normalization_log"
    __table_args__ = (Index("ix_norm_log_deal_id", "deal_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(Integer, ForeignKey("deals.id"), nullable=False)
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    raw_response: Mapped[str | None] = mapped_column(Text)
    normalized_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)

    deal: Mapped["Deal"] = relationship("Deal", back_populates="normalization_logs")

    def __repr__(self) -> str:
        return f"<NormalizationLog deal={self.deal_id} fallback={self.fallback_used}>"


# ─────────────────────────────────────────────────────────────────────────────
# UserPreference
# ─────────────────────────────────────────────────────────────────────────────


class UserPreference(TimestampMixin, Base):
    """
    Lightweight, session-based personalization.

    Uses an anonymous session_id (UUID) — no auth required.
    JSON columns store lists that drive preference-boosted ranking.
    """

    __tablename__ = "user_preferences"
    __table_args__ = (Index("ix_user_prefs_session_id", "session_id", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    city_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("cities.id"))
    preferred_categories: Mapped[list | None] = mapped_column(JSON)   # ["Electronics", ...]
    excluded_categories: Mapped[list | None] = mapped_column(JSON)
    preferred_merchants: Mapped[list | None] = mapped_column(JSON)
    max_price: Mapped[float | None] = mapped_column(Float)
    min_discount_pct: Mapped[float | None] = mapped_column(Float)
    radius_miles: Mapped[float] = mapped_column(Float, default=25.0)

    city: Mapped["City | None"] = relationship("City", back_populates="user_preferences")

    def __repr__(self) -> str:
        return f"<UserPreference session={self.session_id}>"


# ─────────────────────────────────────────────────────────────────────────────
# EventLog
# ─────────────────────────────────────────────────────────────────────────────


class EventLog(Base):
    """
    Immutable user-interaction event stream.

    Captures clicks, views, searches, reports, and feedback.
    Used for freshness signals, abuse detection, and future ML training data.
    ip_hash is SHA-256(ip + salt) — never store raw IPs.
    """

    __tablename__ = "event_log"
    __table_args__ = (
        Index("ix_event_log_event_type", "event_type"),
        Index("ix_event_log_session_id", "session_id"),
        Index("ix_event_log_deal_id", "deal_id"),
        Index("ix_event_log_created_at", "created_at"),
        # Hot query: events per deal in a time window
        Index("ix_event_log_deal_type_time", "deal_id", "event_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # "click" | "view" | "search" | "filter" | "report" | "feedback" | "ingest_trigger"
    deal_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("deals.id"))
    venue_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("venues.id"))
    payload: Mapped[dict | None] = mapped_column(JSON)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    deal: Mapped["Deal | None"] = relationship("Deal", back_populates="event_logs")
    venue: Mapped["Venue | None"] = relationship("Venue", back_populates="event_logs")

    def __repr__(self) -> str:
        return f"<EventLog {self.event_type} deal={self.deal_id} session={self.session_id}>"
