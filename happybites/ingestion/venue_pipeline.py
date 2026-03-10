"""
VenueIngestionPipeline — orchestrates the full ingest cycle for
venue-aware connectors (VenueConnector subclasses).

Pipeline steps:
  1. Ensure Source row exists for the connector
  2. Ensure City row exists for the requested city
  3. fetch(city) → (RawVenue list, RawDeal list)
  4. Upsert each venue + VenueSourceMapping
  5. For each deal:
     a. Compute content hash; skip if unchanged
     b. Write DealRaw (provenance)
     c. Normalize with Normalizer (Claude or regex fallback)
     d. Upsert canonical Deal with city_id and venue_id
     e. Write DealSchedule rows from schedule metadata
     f. Write NormalizationLog
  6. Update IngestionRun stats and Source.last_fetched_at

Returns an IngestionStats dataclass summarising the run.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog

from happybites.db.models import (
    Deal,
    DealRaw,
    DealSchedule,
    IngestionRun,
    NormalizationLog,
    Source,
    Venue,
    VenueSourceMapping,
)
from happybites.db.repositories import (
    get_or_create_city,
    get_or_create_venue,
    get_or_create_venue_mapping,
    record_source_fetch,
)
from happybites.ingestion.base import RawDeal, RawVenue, VenueConnector
from happybites.ingestion.normalizer import Normalizer
from happybites.ingestion.ranker import rank_deal

logger = structlog.get_logger(__name__)


# ── City slug normalisation ──────────────────────────────────────────────────

_CITY_ALIASES: dict[str, tuple[str, str | None, str]] = {
    # slug: (canonical_name, state, country)
    "nyc":           ("New York",      "NY", "US"),
    "new-york":      ("New York",      "NY", "US"),
    "sf":            ("San Francisco", "CA", "US"),
    "san-francisco": ("San Francisco", "CA", "US"),
    "austin":        ("Austin",        "TX", "US"),
    "la":            ("Los Angeles",   "CA", "US"),
    "los-angeles":   ("Los Angeles",   "CA", "US"),
    "chicago":       ("Chicago",       "IL", "US"),
    "boston":        ("Boston",        "MA", "US"),
    "seattle":       ("Seattle",       "WA", "US"),
}


def normalise_city_slug(city: str) -> str:
    """Return the lowercase slug used in fixture files (e.g. 'NYC' → 'nyc')."""
    return city.lower().strip().replace(" ", "-").replace(",", "")


def city_display_name(slug: str) -> tuple[str, str | None, str]:
    """Return (canonical_name, state, country) for a slug."""
    info = _CITY_ALIASES.get(slug)
    if info:
        return info
    # Fall back: capitalise each word and treat as-is
    return slug.replace("-", " ").title(), None, "US"


# ── Stats ────────────────────────────────────────────────────────────────────


@dataclass
class IngestionStats:
    source: str
    city: str
    venues_inserted: int = 0
    venues_updated: int = 0
    deals_fetched: int = 0
    deals_inserted: int = 0
    deals_updated: int = 0
    deals_skipped: int = 0
    raw_records_written: int = 0
    run_id: int | None = None
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "source": self.source,
            "city": self.city,
            "venues_inserted": self.venues_inserted,
            "venues_updated": self.venues_updated,
            "deals_fetched": self.deals_fetched,
            "deals_inserted": self.deals_inserted,
            "deals_updated": self.deals_updated,
            "deals_skipped": self.deals_skipped,
            "raw_records_written": self.raw_records_written,
            "run_id": self.run_id,
            "errors": self.errors,
        }


# ── Pipeline ─────────────────────────────────────────────────────────────────


class VenueIngestionPipeline:
    """
    Runs a full venue + deal ingestion cycle for a single connector + city.

    Usage:
        from sqlalchemy.orm import Session
        pipeline = VenueIngestionPipeline(db, MockYelpConnector())
        stats = pipeline.run("nyc")
    """

    def __init__(self, db, connector: VenueConnector, normalizer: Normalizer | None = None):
        self.db = db
        self.connector = connector
        self._normalizer = normalizer or Normalizer()

    # ── Public entry-point ──────────────────────────────────────────────────

    def run(self, city: str) -> IngestionStats:
        slug = normalise_city_slug(city)
        log = logger.bind(source=self.connector.source_name, city=slug)
        stats = IngestionStats(source=self.connector.source_name, city=slug)

        source = self._ensure_source()
        city_obj = self._ensure_city(slug)

        run = IngestionRun(
            source_id=source.id,
            started_at=datetime.now(timezone.utc),
            status="running",
        )
        self.db.add(run)
        self.db.commit()
        stats.run_id = run.id

        try:
            raw_venues, raw_deals = self.connector.fetch(slug)
            stats.deals_fetched = len(raw_deals)
            log.info("fetch_complete", venues=len(raw_venues), deals=len(raw_deals))

            # Step 1 — Upsert venues
            venue_map: dict[str, Venue] = {}
            for rv in raw_venues:
                venue, created = self._upsert_venue(rv, city_obj.id, source)
                venue_map[rv.external_id] = venue
                if created:
                    stats.venues_inserted += 1
                else:
                    stats.venues_updated += 1

            # Step 2 — Upsert deals
            for rd in raw_deals:
                venue_ext_id = rd.raw_data.get("venue_external_id")
                venue = venue_map.get(venue_ext_id) if venue_ext_id else None
                result = self._upsert_deal(rd, source, city_obj.id, venue)
                if result == "inserted":
                    stats.deals_inserted += 1
                    stats.raw_records_written += 1
                elif result == "updated":
                    stats.deals_updated += 1
                    stats.raw_records_written += 1
                else:
                    stats.deals_skipped += 1

            # Finalise run
            record_source_fetch(self.db, source.id, success=True)
            run.status = "success"
            run.deals_fetched = stats.deals_fetched
            run.deals_inserted = stats.deals_inserted
            run.deals_updated = stats.deals_updated
            run.records_raw = stats.raw_records_written
            run.finished_at = datetime.now(timezone.utc)
            self.db.commit()

            log.info("pipeline_complete", **stats.summary())

        except Exception as exc:
            log.exception("pipeline_error", error=str(exc))
            stats.errors.append(str(exc))
            record_source_fetch(self.db, source.id, success=False, error=str(exc))
            run.status = "error"
            run.error_msg = str(exc)
            run.finished_at = datetime.now(timezone.utc)
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()

        return stats

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _ensure_source(self) -> Source:
        source = (
            self.db.query(Source)
            .filter(Source.name == self.connector.source_name)
            .first()
        )
        if not source:
            source = Source(
                name=self.connector.source_name,
                display_name=self.connector.source_name.replace("_", " ").title(),
                type=self.connector.source_type,
                fetch_interval=3600,
                is_active=True,
                consecutive_failures=0,
                confidence_weight=1.0,
            )
            self.db.add(source)
            self.db.commit()
            self.db.refresh(source)
            logger.info("source_created", name=source.name)
        return source

    def _ensure_city(self, slug: str):
        name, state, country = city_display_name(slug)
        city, created = get_or_create_city(
            self.db,
            name=name,
            state=state,
            country=country,
            slug=slug,
        )
        if created:
            logger.info("city_created", slug=slug, name=name)
        return city

    def _upsert_venue(self, rv: RawVenue, city_id: int, source: Source) -> tuple[Venue, bool]:
        # Check if we already have a mapping for this external ID
        existing_mapping = (
            self.db.query(VenueSourceMapping)
            .filter(
                VenueSourceMapping.source_id == source.id,
                VenueSourceMapping.external_id == rv.external_id,
            )
            .first()
        )

        if existing_mapping:
            venue = existing_mapping.venue
            # Refresh mutable fields
            venue.rating = rv.rating
            venue.image_url = rv.image_url
            existing_mapping.last_seen_at = datetime.now(timezone.utc)
            self.db.commit()
            return venue, False

        # Create or find venue by slug
        slug = rv.name.lower().replace(" ", "-").replace("'", "").replace("&", "and")
        slug = f"{slug}-{rv.city.lower().replace(' ', '-')}"

        venue, created = get_or_create_venue(
            self.db,
            name=rv.name,
            city_id=city_id,
            slug=slug,
            address=rv.address,
            lat=rv.lat,
            lon=rv.lon,
            category=rv.category,
            phone=rv.phone,
            website=rv.website,
            image_url=rv.image_url,
            confidence=1.0,
        )

        # Always create the source mapping (we checked it doesn't exist above)
        get_or_create_venue_mapping(
            self.db,
            venue_id=venue.id,
            source_id=source.id,
            external_id=rv.external_id,
            external_url=rv.website,
            confidence=1.0,
        )

        return venue, created

    def _content_hash(self, payload: dict) -> str:
        serialised = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()[:16]

    def _upsert_deal(
        self,
        rd: RawDeal,
        source: Source,
        city_id: int,
        venue: Venue | None,
    ) -> str:
        """Persist one deal. Returns 'inserted' | 'updated' | 'skipped'."""
        now = datetime.now(timezone.utc)
        raw_payload = {
            "source_deal_id": rd.source_deal_id,
            "title": rd.title,
            "description": rd.description,
            "url": rd.url,
            "merchant": rd.merchant,
            "original_price": rd.original_price,
            "deal_price": rd.deal_price,
            **rd.raw_data,
        }
        content_hash = self._content_hash(raw_payload)

        # Check for existing DealRaw with the same hash → skip if unchanged
        existing_raw = (
            self.db.query(DealRaw)
            .filter(
                DealRaw.source_id == source.id,
                DealRaw.source_deal_id == rd.source_deal_id,
            )
            .order_by(DealRaw.fetched_at.desc())
            .first()
        )
        if existing_raw and existing_raw.content_hash == content_hash:
            # Content unchanged — update last_seen_at on the deal and skip
            if existing_raw.deal_id:
                deal = self.db.get(Deal, existing_raw.deal_id)
                if deal:
                    deal.last_seen_at = now
                    self.db.commit()
            return "skipped"

        # Normalise
        fields, fallback_used = self._normalizer.normalize(rd)
        discount_pct = fields.get("discount_pct") or rd.raw_data.get("discount_pct")

        # Compute discount_pct from raw if normalizer didn't
        if discount_pct is None and rd.original_price and rd.deal_price:
            if rd.original_price > 0 and rd.deal_price < rd.original_price:
                discount_pct = round(
                    (rd.original_price - rd.deal_price) / rd.original_price * 100, 2
                )

        deal_data: dict = {
            "source_id": source.id,
            "source_deal_id": rd.source_deal_id,
            "source_url": rd.url,
            "title": rd.title,
            "description": rd.description,
            "url": rd.url,
            "image_url": rd.image_url or (venue.image_url if venue else None),
            "merchant": rd.merchant or fields.get("merchant"),
            "category": fields.get("category", "Food & Dining"),
            "tags": json.dumps(fields.get("tags", [])),
            "original_price": rd.original_price or fields.get("original_price"),
            "deal_price": rd.deal_price or fields.get("deal_price"),
            "discount_pct": discount_pct,
            "currency": "USD",
            "fetched_at": now,
            "last_seen_at": now,
            "normalized_at": now,
            "quality_score": fields.get("quality_score"),
            "confidence": 0.9 if not fallback_used else 0.6,
            "is_online": False,
            "is_active": True,
            "is_verified": False,
            "city_id": city_id,
            "venue_id": venue.id if venue else None,
        }

        # Upsert deal
        existing_deal = (
            self.db.query(Deal)
            .filter(
                Deal.source_id == source.id,
                Deal.source_deal_id == rd.source_deal_id,
            )
            .first()
        )

        if existing_deal:
            result = "updated"
            for k, v in deal_data.items():
                if k not in ("source_id", "source_deal_id", "first_seen_at"):
                    setattr(existing_deal, k, v)
            deal = existing_deal
        else:
            result = "inserted"
            deal_data["first_seen_at"] = now
            deal = Deal(**deal_data)
            self.db.add(deal)
            self.db.flush()  # populate deal.id

        deal.rank_score = rank_deal(deal)

        # Write DealRaw for provenance
        deal_raw = DealRaw(
            source_id=source.id,
            deal_id=deal.id,
            source_deal_id=rd.source_deal_id,
            raw_payload=raw_payload,
            raw_url=f"mock://{source.name}/v1/{normalise_city_slug(rd.raw_data.get('venue_name', 'venue'))}",
            http_status=200,
            content_hash=content_hash,
            fetched_at=now,
        )
        self.db.add(deal_raw)

        # Write NormalizationLog
        norm_log = NormalizationLog(
            deal_id=deal.id,
            model=fields.get("_model"),
            prompt_tokens=fields.get("_prompt_tokens"),
            completion_tokens=fields.get("_completion_tokens"),
            raw_response=fields.get("_raw_response"),
            normalized_at=now,
            fallback_used=fallback_used,
        )
        self.db.add(norm_log)

        # Write DealSchedule rows from connector schedule metadata
        if result == "inserted":
            self._create_schedules(deal, rd.raw_data)

        self.db.commit()
        return result

    def _create_schedules(self, deal: Deal, meta: dict) -> None:
        day_indices: list[int] = meta.get("valid_day_indices", [])
        start_time: str | None = meta.get("start_time")
        end_time: str | None = meta.get("end_time")

        if not day_indices and not start_time:
            return  # no schedule constraints

        if day_indices:
            for day_idx in day_indices:
                sched = DealSchedule(
                    deal_id=deal.id,
                    day_of_week=day_idx,
                    start_time=start_time,
                    end_time=end_time,
                    timezone="UTC",
                )
                self.db.add(sched)
        else:
            # Time window with no specific day constraint
            sched = DealSchedule(
                deal_id=deal.id,
                day_of_week=None,
                start_time=start_time,
                end_time=end_time,
                timezone="UTC",
            )
            self.db.add(sched)
