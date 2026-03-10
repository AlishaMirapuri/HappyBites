"""
Tests for the data model layer.

Covers:
  - Schema (Pydantic) validation
  - ORM model CRUD via repository functions
  - FK constraints and cascade behavior
  - Unique constraints
  - Relationship traversal
  - Freshness / staleness helpers
  - JSON columns round-trip
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from happybites.db import repositories as repo
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
from happybites.schemas.api import (
    DealScheduleCreate,
    EventLogCreate,
    UserPreferenceUpdate,
    VenueResponse,
)
from happybites.schemas.internal import DealFilterParams, GeoFilter, GeoPoint, NormalizedDeal


def _utcnow():
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / shared fixtures
# ─────────────────────────────────────────────────────────────────────────────


def make_source(db, name="test-source", stype="api") -> Source:
    existing = repo.get_source_by_name(db, name)
    if existing:
        return existing
    return repo.create_source(
        db, name=name, type=stype, fetch_interval=3600,
        is_active=True, consecutive_failures=0, confidence_weight=1.0,
    )


def make_city(db, slug="test-city-ca") -> City:
    city, _ = repo.get_or_create_city(
        db, name="Test City", state="CA", country="US", slug=slug,
        lat=37.0, lon=-122.0,
    )
    return city


def make_venue(db, city_id: int | None = None, slug="test-venue") -> Venue:
    venue, _ = repo.get_or_create_venue(db, name="Test Venue", city_id=city_id, slug=slug)
    return venue


def make_deal(db, source: Source, **overrides) -> Deal:
    now = _utcnow()
    defaults = dict(
        source_deal_id="deal-001",
        title="Test Deal — $50",
        url="https://example.com/deal/1",
        deal_price=50.0,
        original_price=100.0,
        discount_pct=50.0,
        category="Electronics",
        tags=json.dumps(["gadget", "sale"]),
        quality_score=0.85,
        confidence=0.90,
        fetched_at=now,
        is_active=True,
    )
    defaults.update(overrides)
    deal, _ = repo.upsert_deal(db, source_id=source.id, **defaults)
    return deal


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic schema validation
# ─────────────────────────────────────────────────────────────────────────────


class TestSchemaValidation:
    def test_deal_schedule_valid(self):
        s = DealScheduleCreate(day_of_week=0, start_time="09:00", end_time="17:00")
        assert s.day_of_week == 0

    def test_deal_schedule_invalid_day(self):
        with pytest.raises(Exception):
            DealScheduleCreate(day_of_week=7)

    def test_deal_schedule_invalid_time_format(self):
        with pytest.raises(Exception):
            DealScheduleCreate(start_time="9am")

    def test_deal_schedule_invalid_time_value(self):
        with pytest.raises(Exception):
            DealScheduleCreate(start_time="25:00")

    def test_schedule_populates_day_name(self):
        from happybites.schemas.api import DealScheduleResponse

        r = DealScheduleResponse(
            id=1, deal_id=1, day_of_week=0, start_time="10:00",
            end_time="18:00", valid_from=None, valid_until=None,
            timezone="UTC", notes=None,
        )
        assert r.day_name == "Mon"

    def test_user_preference_update_validates_discount(self):
        with pytest.raises(Exception):
            UserPreferenceUpdate(min_discount_pct=101.0)

    def test_user_preference_update_validates_radius(self):
        with pytest.raises(Exception):
            UserPreferenceUpdate(radius_miles=-5.0)

    def test_event_log_create_valid_type(self):
        e = EventLogCreate(event_type="click", deal_id=1)
        assert e.event_type == "click"

    def test_event_log_create_invalid_type(self):
        with pytest.raises(Exception):
            EventLogCreate(event_type="invalid_type")

    def test_normalized_deal_clamps_quality_score(self):
        nd = NormalizedDeal(quality_score=1.5)
        assert nd.quality_score == 1.0

    def test_normalized_deal_clamps_negative_score(self):
        nd = NormalizedDeal(confidence=-0.1)
        assert nd.confidence == 0.0

    def test_deal_filter_params_clamps_limit(self):
        f = DealFilterParams(limit=9999)
        assert f.limit == 200

    def test_deal_filter_params_invalid_sort(self):
        with pytest.raises(Exception):
            DealFilterParams(sort="bad_field")

    def test_geo_point_valid(self):
        g = GeoPoint(lat=37.7749, lon=-122.4194)
        assert g.lat == 37.7749

    def test_geo_point_invalid_lat(self):
        with pytest.raises(Exception):
            GeoPoint(lat=91.0, lon=0.0)

    def test_geo_point_invalid_lon(self):
        with pytest.raises(Exception):
            GeoPoint(lat=0.0, lon=200.0)

    def test_geo_filter_invalid_radius(self):
        with pytest.raises(Exception):
            GeoFilter(origin=GeoPoint(lat=0, lon=0), radius_miles=0.0)


# ─────────────────────────────────────────────────────────────────────────────
# City CRUD
# ─────────────────────────────────────────────────────────────────────────────


class TestCityCRUD:
    def test_create_city(self, db):
        city, created = repo.get_or_create_city(
            db, name="Portland", state="OR", country="US", slug="portland-or"
        )
        assert created is True
        assert city.id is not None
        assert city.slug == "portland-or"

    def test_get_or_create_city_idempotent(self, db):
        _, _ = repo.get_or_create_city(db, name="Denver", state="CO", slug="denver-co")
        city2, created2 = repo.get_or_create_city(db, name="Denver", state="CO", slug="denver-co")
        assert created2 is False
        assert city2.name == "Denver"

    def test_get_city_by_slug(self, db):
        repo.get_or_create_city(db, name="Phoenix", state="AZ", slug="phoenix-az")
        found = repo.get_city_by_slug(db, "phoenix-az")
        assert found is not None
        assert found.state == "AZ"

    def test_get_city_by_slug_missing(self, db):
        assert repo.get_city_by_slug(db, "nonexistent-city") is None

    def test_list_cities(self, db):
        repo.get_or_create_city(db, name="Seattle", state="WA", slug="seattle-wa")
        cities = repo.list_cities(db)
        assert any(c.slug == "seattle-wa" for c in cities)

    def test_city_has_timestamps(self, db):
        city, _ = repo.get_or_create_city(db, name="Tampa", state="FL", slug="tampa-fl")
        assert city.created_at is not None
        assert city.updated_at is not None


# ─────────────────────────────────────────────────────────────────────────────
# Source CRUD
# ─────────────────────────────────────────────────────────────────────────────


class TestSourceCRUD:
    def test_create_source(self, db):
        src = make_source(db, name="test-source-create")
        assert src.id is not None
        assert src.consecutive_failures == 0
        assert src.confidence_weight == 1.0

    def test_get_source_by_name(self, db):
        make_source(db, name="findable-source")
        found = repo.get_source_by_name(db, "findable-source")
        assert found is not None

    def test_record_source_fetch_success(self, db):
        src = make_source(db, name="fetch-success-src")
        repo.record_source_fetch(db, src.id, success=True)
        db.refresh(src)
        assert src.last_fetched_at is not None
        assert src.last_successful_at is not None
        assert src.consecutive_failures == 0

    def test_record_source_fetch_failure_increments(self, db):
        src = make_source(db, name="fetch-fail-src")
        repo.record_source_fetch(db, src.id, success=False)
        repo.record_source_fetch(db, src.id, success=False)
        db.refresh(src)
        assert src.consecutive_failures == 2

    def test_record_source_fetch_success_resets_failures(self, db):
        src = make_source(db, name="fetch-reset-src")
        src.consecutive_failures = 3
        db.commit()
        repo.record_source_fetch(db, src.id, success=True)
        db.refresh(src)
        assert src.consecutive_failures == 0

    def test_list_sources_active_only(self, db):
        src = make_source(db, name="inactive-src")
        src.is_active = False
        db.commit()
        active = repo.list_sources(db, active_only=True)
        assert not any(s.name == "inactive-src" for s in active)


# ─────────────────────────────────────────────────────────────────────────────
# Venue CRUD
# ─────────────────────────────────────────────────────────────────────────────


class TestVenueCRUD:
    def test_create_venue(self, db):
        venue, created = repo.get_or_create_venue(
            db, name="The New Venue", slug="the-new-venue"
        )
        assert created is True
        assert venue.id is not None

    def test_get_or_create_venue_idempotent(self, db):
        repo.get_or_create_venue(db, name="Idempotent Venue", slug="idempotent-venue")
        _, created = repo.get_or_create_venue(db, name="Idempotent Venue", slug="idempotent-venue")
        assert created is False

    def test_venue_linked_to_city(self, db):
        city = make_city(db, slug="venue-city-ca")
        venue, _ = repo.get_or_create_venue(
            db, name="City Venue", slug="city-venue", city_id=city.id
        )
        db.refresh(venue)
        assert venue.city_id == city.id
        assert venue.city.slug == "venue-city-ca"

    def test_venue_source_mapping_created(self, db):
        src = make_source(db, name="mapping-source")
        venue, _ = repo.get_or_create_venue(db, name="Mapped Venue", slug="mapped-venue")
        mapping, created = repo.get_or_create_venue_mapping(
            db,
            venue_id=venue.id,
            source_id=src.id,
            external_id="yelp-12345",
            external_url="https://yelp.com/biz/mapped-venue",
        )
        assert created is True
        assert mapping.external_id == "yelp-12345"

    def test_venue_source_mapping_idempotent(self, db):
        src = make_source(db, name="mapping-source-2")
        venue, _ = repo.get_or_create_venue(db, name="Mapped Venue 2", slug="mapped-venue-2")
        repo.get_or_create_venue_mapping(
            db, venue_id=venue.id, source_id=src.id, external_id="ext-001"
        )
        _, created2 = repo.get_or_create_venue_mapping(
            db, venue_id=venue.id, source_id=src.id, external_id="ext-001"
        )
        assert created2 is False

    def test_find_venue_by_source_mapping(self, db):
        src = make_source(db, name="find-by-mapping-source")
        venue, _ = repo.get_or_create_venue(db, name="Found Venue", slug="found-venue")
        repo.get_or_create_venue_mapping(
            db, venue_id=venue.id, source_id=src.id, external_id="find-me"
        )
        found = repo.find_venue_by_source_mapping(db, src.id, "find-me")
        assert found is not None
        assert found.id == venue.id

    def test_find_venue_mapping_returns_none_for_missing(self, db):
        src = make_source(db, name="missing-mapping-src")
        assert repo.find_venue_by_source_mapping(db, src.id, "does-not-exist") is None

    def test_venue_response_schema(self, db):
        venue, _ = repo.get_or_create_venue(
            db, name="Schema Venue", slug="schema-venue",
            lat=37.77, lon=-122.41, category="restaurant",
        )
        schema = VenueResponse.model_validate(venue)
        assert schema.lat == 37.77
        assert schema.category == "restaurant"


# ─────────────────────────────────────────────────────────────────────────────
# Deal CRUD
# ─────────────────────────────────────────────────────────────────────────────


class TestDealCRUD:
    def test_create_deal(self, db):
        src = make_source(db, name="deal-create-src")
        deal = make_deal(db, src)
        assert deal.id is not None
        assert deal.first_seen_at is not None
        assert deal.last_seen_at is not None

    def test_upsert_deal_creates(self, db):
        src = make_source(db, name="upsert-src-1")
        deal, created = repo.upsert_deal(
            db, source_id=src.id, source_deal_id="new-001",
            title="New Deal", url="https://ex.com", fetched_at=_utcnow(),
        )
        assert created is True

    def test_upsert_deal_updates_on_second_call(self, db):
        src = make_source(db, name="upsert-src-2")
        _, created1 = repo.upsert_deal(
            db, source_id=src.id, source_deal_id="upd-001",
            title="Original Title", url="https://ex.com",
            deal_price=50.0, fetched_at=_utcnow(),
        )
        deal, created2 = repo.upsert_deal(
            db, source_id=src.id, source_deal_id="upd-001",
            title="Updated Title", url="https://ex.com",
            deal_price=45.0, fetched_at=_utcnow(),
        )
        assert created1 is True
        assert created2 is False
        assert deal.title == "Updated Title"
        assert deal.deal_price == 45.0

    def test_upsert_deal_preserves_first_seen_at(self, db):
        src = make_source(db, name="first-seen-src")
        deal1, _ = repo.upsert_deal(
            db, source_id=src.id, source_deal_id="fs-001",
            title="T", url="https://ex.com", fetched_at=_utcnow(),
        )
        first_seen = deal1.first_seen_at
        deal2, _ = repo.upsert_deal(
            db, source_id=src.id, source_deal_id="fs-001",
            title="T Updated", url="https://ex.com", fetched_at=_utcnow(),
        )
        assert deal2.first_seen_at == first_seen

    def test_deal_unique_constraint(self, db):
        import sqlalchemy.exc

        src = make_source(db, name="uc-src")
        db.add(Deal(
            source_id=src.id, source_deal_id="dup-001",
            title="D", url="https://ex.com",
            fetched_at=_utcnow(), is_active=True,
        ))
        db.commit()

        db.add(Deal(
            source_id=src.id, source_deal_id="dup-001",
            title="D2", url="https://ex.com",
            fetched_at=_utcnow(), is_active=True,
        ))
        with pytest.raises(Exception):  # IntegrityError from unique constraint
            db.commit()
        db.rollback()

    def test_get_deal_by_source(self, db):
        src = make_source(db, name="get-by-src")
        make_deal(db, src, source_deal_id="find-me-deal")
        found = repo.get_deal_by_source(db, src.id, "find-me-deal")
        assert found is not None

    def test_deactivate_deal(self, db):
        src = make_source(db, name="deactivate-src")
        deal = make_deal(db, src, source_deal_id="deact-001")
        repo.deactivate_deal(db, deal.id)
        db.refresh(deal)
        assert deal.is_active is False

    def test_update_deal_scores(self, db):
        src = make_source(db, name="scores-src")
        deal = make_deal(db, src, source_deal_id="scores-001")
        repo.update_deal_scores(db, deal.id, rank_score=0.88, freshness_score=0.75)
        db.refresh(deal)
        assert deal.rank_score == 0.88
        assert deal.freshness_score == 0.75

    def test_list_deals_filter_category(self, db):
        src = make_source(db, name="filter-cat-src")
        make_deal(db, src, source_deal_id="cat-elec", category="Electronics")
        make_deal(db, src, source_deal_id="cat-food", category="Food & Dining")
        deals, total = repo.list_deals(db, category="Electronics")
        assert all(d.category == "Electronics" for d in deals)

    def test_list_deals_filter_max_price(self, db):
        src = make_source(db, name="filter-price-src")
        make_deal(db, src, source_deal_id="price-low", deal_price=10.0)
        make_deal(db, src, source_deal_id="price-high", deal_price=999.0)
        deals, _ = repo.list_deals(db, max_price=50.0)
        assert all((d.deal_price or 0) <= 50.0 for d in deals if d.deal_price)

    def test_list_deals_filter_min_discount(self, db):
        src = make_source(db, name="filter-disc-src")
        make_deal(db, src, source_deal_id="disc-high", discount_pct=60.0)
        make_deal(db, src, source_deal_id="disc-low", discount_pct=5.0)
        deals, _ = repo.list_deals(db, min_discount=50.0)
        assert all((d.discount_pct or 0) >= 50.0 for d in deals if d.discount_pct)

    def test_list_deals_filter_city(self, db):
        city = make_city(db, slug="deal-city-filter-ca")
        src = make_source(db, name="city-filter-src")
        make_deal(db, src, source_deal_id="city-deal", city_id=city.id)
        make_deal(db, src, source_deal_id="no-city-deal")
        deals, _ = repo.list_deals(db, city_id=city.id)
        assert all(d.city_id == city.id for d in deals)

    def test_list_deals_pagination(self, db):
        src = make_source(db, name="page-src")
        for i in range(5):
            make_deal(db, src, source_deal_id=f"page-deal-{i}")
        page1, total = repo.list_deals(db, limit=2, offset=0)
        page2, _ = repo.list_deals(db, limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert total >= 5
        assert {d.id for d in page1}.isdisjoint({d.id for d in page2})

    def test_deal_venue_relationship(self, db):
        city = make_city(db, slug="rel-city-ca")
        venue = make_venue(db, city_id=city.id, slug="rel-venue")
        src = make_source(db, name="rel-src")
        deal = make_deal(db, src, source_deal_id="rel-deal", venue_id=venue.id)
        db.refresh(deal)
        assert deal.venue is not None
        assert deal.venue.name == "Test Venue"

    def test_get_deals_by_venue(self, db):
        venue = make_venue(db, slug="venue-deals-test")
        src = make_source(db, name="venue-deals-src")
        make_deal(db, src, source_deal_id="vd-001", venue_id=venue.id)
        make_deal(db, src, source_deal_id="vd-002", venue_id=venue.id)
        make_deal(db, src, source_deal_id="vd-003")  # no venue
        deals = repo.get_deals_by_venue(db, venue.id)
        assert len(deals) == 2
        assert all(d.venue_id == venue.id for d in deals)


# ─────────────────────────────────────────────────────────────────────────────
# DealRaw
# ─────────────────────────────────────────────────────────────────────────────


class TestDealRaw:
    def test_create_deal_raw(self, db):
        src = make_source(db, name="raw-src")
        raw = repo.create_deal_raw(
            db,
            source_id=src.id,
            source_deal_id="raw-001",
            raw_payload={"title": "Test Deal", "price": "$50"},
            raw_url="https://example.com/raw",
            http_status=200,
        )
        assert raw.id is not None
        assert raw.content_hash is not None
        assert len(raw.content_hash) == 16

    def test_deal_raw_json_roundtrip(self, db):
        src = make_source(db, name="raw-json-src")
        payload = {"title": "Deal", "nested": {"price": 49.99}, "tags": ["a", "b"]}
        raw = repo.create_deal_raw(
            db, source_id=src.id, source_deal_id="json-001", raw_payload=payload
        )
        db.refresh(raw)
        assert raw.raw_payload == payload  # JSON column round-trips correctly

    def test_link_raw_to_deal(self, db):
        src = make_source(db, name="link-raw-src")
        deal = make_deal(db, src, source_deal_id="link-deal")
        raw = repo.create_deal_raw(
            db, source_id=src.id, source_deal_id="link-raw-001",
            raw_payload={"t": "x"}
        )
        repo.link_raw_to_deal(db, raw.id, deal.id)
        db.refresh(raw)
        assert raw.deal_id == deal.id

    def test_has_content_changed_no_prior(self, db):
        src = make_source(db, name="change-src-1")
        assert repo.has_content_changed(db, src.id, "new-001", {"t": "x"}) is True

    def test_has_content_changed_same_payload(self, db):
        src = make_source(db, name="change-src-2")
        payload = {"title": "Same"}
        repo.create_deal_raw(db, source_id=src.id, source_deal_id="same-001", raw_payload=payload)
        assert repo.has_content_changed(db, src.id, "same-001", payload) is False

    def test_has_content_changed_different_payload(self, db):
        src = make_source(db, name="change-src-3")
        repo.create_deal_raw(
            db, source_id=src.id, source_deal_id="diff-001",
            raw_payload={"title": "Old Price"}
        )
        assert repo.has_content_changed(
            db, src.id, "diff-001", {"title": "New Price"}
        ) is True


# ─────────────────────────────────────────────────────────────────────────────
# DealSchedule
# ─────────────────────────────────────────────────────────────────────────────


class TestDealSchedule:
    def test_create_schedule(self, db):
        src = make_source(db, name="sched-src")
        deal = make_deal(db, src, source_deal_id="sched-deal")
        s = repo.create_deal_schedule(
            db, deal_id=deal.id, day_of_week=1,
            start_time="15:00", end_time="18:00", timezone="America/Los_Angeles"
        )
        assert s.id is not None
        assert s.day_of_week == 1

    def test_get_deal_schedules(self, db):
        src = make_source(db, name="get-sched-src")
        deal = make_deal(db, src, source_deal_id="get-sched-deal")
        for day in [0, 2, 4]:  # Mon, Wed, Fri
            repo.create_deal_schedule(db, deal_id=deal.id, day_of_week=day)
        schedules = repo.get_deal_schedules(db, deal.id)
        assert len(schedules) == 3
        assert {s.day_of_week for s in schedules} == {0, 2, 4}

    def test_replace_deal_schedules(self, db):
        src = make_source(db, name="replace-sched-src")
        deal = make_deal(db, src, source_deal_id="replace-sched-deal")
        repo.create_deal_schedule(db, deal_id=deal.id, day_of_week=0)
        repo.create_deal_schedule(db, deal_id=deal.id, day_of_week=1)

        repo.replace_deal_schedules(
            db, deal.id,
            [{"day_of_week": 5, "start_time": "12:00"}]
        )
        schedules = repo.get_deal_schedules(db, deal.id)
        assert len(schedules) == 1
        assert schedules[0].day_of_week == 5

    def test_deal_schedule_no_day_means_every_day(self, db):
        src = make_source(db, name="allday-src")
        deal = make_deal(db, src, source_deal_id="allday-deal")
        s = repo.create_deal_schedule(db, deal_id=deal.id, day_of_week=None)
        assert s.day_of_week is None


# ─────────────────────────────────────────────────────────────────────────────
# IngestionRun + CrawlJob
# ─────────────────────────────────────────────────────────────────────────────


class TestIngestionRun:
    def test_create_ingestion_run(self, db):
        src = make_source(db, name="run-src")
        run = repo.create_ingestion_run(db, source_id=src.id)
        assert run.id is not None
        assert run.status == "running"
        assert run.started_at is not None

    def test_finish_ingestion_run_success(self, db):
        src = make_source(db, name="finish-src")
        run = repo.create_ingestion_run(db, source_id=src.id)
        repo.finish_ingestion_run(
            db, run.id,
            status="success",
            deals_fetched=10,
            deals_inserted=8,
            deals_updated=2,
        )
        db.refresh(run)
        assert run.status == "success"
        assert run.deals_fetched == 10
        assert run.finished_at is not None
        assert run.duration_seconds is not None
        assert run.duration_seconds >= 0

    def test_finish_ingestion_run_error(self, db):
        src = make_source(db, name="error-src")
        run = repo.create_ingestion_run(db, source_id=src.id)
        repo.finish_ingestion_run(
            db, run.id, status="error",
            error_msg="Connection refused",
            error_trace="Traceback (most recent call last):\n  ...",
        )
        db.refresh(run)
        assert run.status == "error"
        assert "Connection refused" in run.error_msg

    def test_get_recent_runs_ordering(self, db):
        src = make_source(db, name="recency-src")
        for _ in range(3):
            repo.create_ingestion_run(db, source_id=src.id)
        runs = repo.get_recent_runs(db, src.id, limit=3)
        assert len(runs) == 3
        # Should be descending by started_at
        for i in range(len(runs) - 1):
            assert runs[i].started_at >= runs[i + 1].started_at

    def test_crawl_job_update_status(self, db):
        src = make_source(db, name="cj-status-src")
        job = CrawlJob(
            source_id=src.id, name="test-job",
            target_url="https://example.com", is_active=True,
        )
        db.add(job)
        db.commit()

        repo.update_crawl_job_status(db, job.id, success=True)
        db.refresh(job)
        assert job.last_success_at is not None
        assert job.consecutive_failures == 0

        repo.update_crawl_job_status(db, job.id, success=False, error="Timeout")
        db.refresh(job)
        assert job.consecutive_failures == 1
        assert job.last_failure_at is not None


# ─────────────────────────────────────────────────────────────────────────────
# UserPreference
# ─────────────────────────────────────────────────────────────────────────────


class TestUserPreference:
    def test_get_or_create_preference(self, db):
        pref, created = repo.get_or_create_preference(db, "session-abc")
        assert created is True
        assert pref.session_id == "session-abc"
        assert pref.radius_miles == 25.0

    def test_get_or_create_preference_idempotent(self, db):
        repo.get_or_create_preference(db, "session-idem")
        _, created = repo.get_or_create_preference(db, "session-idem")
        assert created is False

    def test_update_preference_categories(self, db):
        repo.get_or_create_preference(db, "session-upd")
        updated = repo.update_preference(
            db, "session-upd",
            preferred_categories=["Electronics", "Food & Dining"],
            min_discount_pct=20.0,
        )
        assert updated is not None
        assert "Electronics" in updated.preferred_categories
        assert updated.min_discount_pct == 20.0

    def test_update_preference_json_list_roundtrip(self, db):
        repo.get_or_create_preference(db, "session-json")
        repo.update_preference(
            db, "session-json",
            preferred_merchants=["Amazon", "Nike", "Dyson"],
        )
        pref = repo.get_preference(db, "session-json")
        assert isinstance(pref.preferred_merchants, list)
        assert "Nike" in pref.preferred_merchants

    def test_update_preference_invalid_session(self, db):
        result = repo.update_preference(db, "does-not-exist", max_price=100.0)
        assert result is None

    def test_preference_linked_to_city(self, db):
        city = make_city(db, slug="pref-city-ca")
        repo.get_or_create_preference(db, "session-city")
        repo.update_preference(db, "session-city", city_id=city.id)
        pref = repo.get_preference(db, "session-city")
        assert pref.city_id == city.id


# ─────────────────────────────────────────────────────────────────────────────
# EventLog
# ─────────────────────────────────────────────────────────────────────────────


class TestEventLog:
    def test_log_event_basic(self, db):
        event = repo.log_event(db, event_type="view", session_id="s-001")
        assert event.id is not None
        assert event.event_type == "view"
        assert event.created_at is not None

    def test_log_event_with_deal(self, db):
        src = make_source(db, name="ev-deal-src")
        deal = make_deal(db, src, source_deal_id="ev-deal")
        event = repo.log_event(
            db, event_type="click",
            session_id="s-002", deal_id=deal.id,
            payload={"referrer": "home_page"},
        )
        assert event.deal_id == deal.id
        assert event.payload["referrer"] == "home_page"

    def test_log_event_payload_json_roundtrip(self, db):
        event = repo.log_event(
            db, event_type="search",
            payload={"query": "pizza", "filters": {"max_price": 20}},
        )
        db.refresh(event)
        assert event.payload["query"] == "pizza"
        assert event.payload["filters"]["max_price"] == 20

    def test_count_events_by_deal(self, db):
        src = make_source(db, name="count-ev-src")
        deal = make_deal(db, src, source_deal_id="count-ev-deal")
        repo.log_event(db, event_type="view", deal_id=deal.id)
        repo.log_event(db, event_type="click", deal_id=deal.id)
        repo.log_event(db, event_type="view")  # unrelated event

        count = repo.count_events(db, deal_id=deal.id)
        assert count == 2

    def test_count_events_by_type(self, db):
        repo.log_event(db, event_type="view", session_id="s-count-1")
        repo.log_event(db, event_type="view", session_id="s-count-2")
        repo.log_event(db, event_type="click", session_id="s-count-3")
        views = repo.count_events(db, event_type="view")
        assert views >= 2

    def test_event_log_relationship_to_venue(self, db):
        venue = make_venue(db, slug="ev-venue")
        event = repo.log_event(db, event_type="view", venue_id=venue.id)
        db.refresh(event)
        assert event.venue is not None
        assert event.venue.slug == "ev-venue"


# ─────────────────────────────────────────────────────────────────────────────
# Freshness helpers
# ─────────────────────────────────────────────────────────────────────────────


class TestFreshnessHelpers:
    def test_get_stale_deals(self, db):
        src = make_source(db, name="stale-src")
        old_time = _utcnow() - timedelta(hours=100)
        stale = Deal(
            source_id=src.id, source_deal_id="stale-001",
            title="Stale Deal", url="https://ex.com",
            fetched_at=old_time, last_seen_at=old_time,
            is_active=True,
        )
        db.add(stale)
        db.commit()

        results = repo.get_stale_deals(db, max_age_hours=48.0)
        assert any(d.id == stale.id for d in results)

    def test_get_stale_deals_excludes_fresh(self, db):
        src = make_source(db, name="fresh-src")
        fresh = Deal(
            source_id=src.id, source_deal_id="fresh-001",
            title="Fresh Deal", url="https://ex.com",
            fetched_at=_utcnow(), last_seen_at=_utcnow(),
            is_active=True,
        )
        db.add(fresh)
        db.commit()

        stale_results = repo.get_stale_deals(db, max_age_hours=1.0)
        assert not any(d.id == fresh.id for d in stale_results)

    def test_purge_expired_deals(self, db):
        src = make_source(db, name="purge-src")
        expired = Deal(
            source_id=src.id, source_deal_id="expired-001",
            title="Expired Deal", url="https://ex.com",
            fetched_at=_utcnow(),
            expires_at=_utcnow() - timedelta(days=1),
            is_active=True,
        )
        not_expired = Deal(
            source_id=src.id, source_deal_id="live-001",
            title="Live Deal", url="https://ex.com",
            fetched_at=_utcnow(),
            expires_at=_utcnow() + timedelta(days=1),
            is_active=True,
        )
        db.add_all([expired, not_expired])
        db.commit()

        count = repo.purge_expired_deals(db)
        assert count >= 1
        db.refresh(expired)
        db.refresh(not_expired)
        assert expired.is_active is False
        assert not_expired.is_active is True

    def test_get_deal_count_by_category(self, db):
        src = make_source(db, name="cat-count-src")
        make_deal(db, src, source_deal_id="cat-a-1", category="Electronics")
        make_deal(db, src, source_deal_id="cat-a-2", category="Electronics")
        make_deal(db, src, source_deal_id="cat-b-1", category="Fashion")

        counts = repo.get_deal_count_by_category(db)
        assert counts.get("Electronics", 0) >= 2
        assert counts.get("Fashion", 0) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# NormalizationLog
# ─────────────────────────────────────────────────────────────────────────────


class TestNormalizationLog:
    def test_create_normalization_log(self, db):
        src = make_source(db, name="norm-log-src")
        deal = make_deal(db, src, source_deal_id="norm-log-deal")
        log = repo.create_normalization_log(
            db, deal_id=deal.id,
            model="claude-sonnet-4-6",
            prompt_tokens=120,
            completion_tokens=80,
            fallback_used=False,
        )
        assert log.id is not None
        assert log.model == "claude-sonnet-4-6"
        assert log.fallback_used is False

    def test_normalization_log_relationship(self, db):
        src = make_source(db, name="norm-rel-src")
        deal = make_deal(db, src, source_deal_id="norm-rel-deal")
        repo.create_normalization_log(db, deal_id=deal.id, fallback_used=True)
        db.refresh(deal)
        assert len(deal.normalization_logs) == 1
        assert deal.normalization_logs[0].fallback_used is True
