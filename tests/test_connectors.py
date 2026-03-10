"""
Tests for MockYelpConnector, MockDiningConnector, and VenueIngestionPipeline.

All tests use in-memory SQLite (via the session-scope engine fixture from conftest)
and load from the real fixture files in data/fixtures/.
"""

import json
from pathlib import Path

import pytest

from happybites.ingestion.base import RawDeal, RawVenue
from happybites.ingestion.connectors.mock_yelp import MockYelpConnector
from happybites.ingestion.connectors.mock_dining import MockDiningConnector
from happybites.ingestion.venue_pipeline import VenueIngestionPipeline, normalise_city_slug
from happybites.db.models import Deal, DealRaw, DealSchedule, Source, Venue, VenueSourceMapping

FIXTURE_DIR = Path(__file__).parents[1] / "data" / "fixtures"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _yelp_connector(tmp_path=None):
    path = tmp_path / "mock_yelp.json" if tmp_path else FIXTURE_DIR / "mock_yelp.json"
    return MockYelpConnector(fixture_path=path)


def _dining_connector(tmp_path=None):
    path = tmp_path / "mock_dining.json" if tmp_path else FIXTURE_DIR / "mock_dining.json"
    return MockDiningConnector(fixture_path=path)


# ── City slug normalisation ───────────────────────────────────────────────────


def test_normalise_city_slug_lowercase():
    assert normalise_city_slug("NYC") == "nyc"


def test_normalise_city_slug_spaces():
    assert normalise_city_slug("San Francisco") == "san-francisco"


def test_normalise_city_slug_mixed():
    assert normalise_city_slug("New York, NY") == "new-york-ny"


# ── MockYelpConnector ─────────────────────────────────────────────────────────


class TestMockYelpConnector:
    def test_available_cities(self):
        c = _yelp_connector()
        cities = c.available_cities()
        assert "nyc" in cities
        assert "sf" in cities

    def test_fetch_returns_venues_and_deals(self):
        venues, deals = _yelp_connector().fetch("nyc")
        assert len(venues) >= 3
        assert len(deals) >= 3

    def test_fetch_sf(self):
        venues, deals = _yelp_connector().fetch("sf")
        assert len(venues) >= 2
        assert len(deals) >= 2

    def test_fetch_unknown_city_returns_empty(self):
        venues, deals = _yelp_connector().fetch("atlantis")
        assert venues == []
        assert deals == []

    def test_venues_are_raw_venue_instances(self):
        venues, _ = _yelp_connector().fetch("nyc")
        for v in venues:
            assert isinstance(v, RawVenue)

    def test_deals_are_raw_deal_instances(self):
        _, deals = _yelp_connector().fetch("nyc")
        for d in deals:
            assert isinstance(d, RawDeal)

    def test_venue_fields_populated(self):
        venues, _ = _yelp_connector().fetch("nyc")
        joes = next(v for v in venues if "Joe" in v.name)
        assert joes.external_id == "joes-pizza-new-york"
        assert joes.lat is not None
        assert joes.lon is not None
        assert joes.address is not None
        assert joes.rating == 4.5
        assert joes.phone is not None
        assert joes.city == "New York"
        assert joes.country == "US"
        assert joes.category is not None
        assert joes.price_range == "$"

    def test_deal_fields_populated(self):
        _, deals = _yelp_connector().fetch("nyc")
        lunch = next(d for d in deals if "Lunch" in d.title and "Joe" in (d.merchant or ""))
        assert lunch.source_deal_id == "joes-pizza-nyc-lunch"
        assert lunch.deal_price == 7.00
        assert lunch.original_price == 10.50
        assert lunch.description is not None
        assert lunch.url is not None

    def test_deal_raw_data_has_schedule_fields(self):
        _, deals = _yelp_connector().fetch("nyc")
        for deal in deals:
            assert "venue_external_id" in deal.raw_data
            assert "valid_day_indices" in deal.raw_data
            assert isinstance(deal.raw_data["valid_day_indices"], list)

    def test_happy_hour_deal_has_time_window(self):
        _, deals = _yelp_connector().fetch("nyc")
        hh = next(d for d in deals if "Happy Hour" in d.title)
        assert hh.raw_data["start_time"] == "17:00"
        assert hh.raw_data["end_time"] == "19:00"

    def test_all_day_deal_has_null_time_window(self):
        _, deals = _yelp_connector().fetch("nyc")
        combo = next(d for d in deals if "Combo" in d.title and "Shake" in (d.merchant or ""))
        assert combo.raw_data["start_time"] is None
        assert combo.raw_data["end_time"] is None

    def test_category_mapping_pizza(self):
        venues, _ = _yelp_connector().fetch("nyc")
        joes = next(v for v in venues if "Joe" in v.name)
        assert joes.category == "restaurant"

    def test_category_mapping_bar(self):
        venues, _ = _yelp_connector().fetch("nyc")
        rabbit = next(v for v in venues if "Dead Rabbit" in v.name)
        assert rabbit.category == "bar"

    def test_closed_businesses_excluded(self, tmp_path):
        data = {
            "test": {
                "businesses": [
                    {
                        "id": "open-place",
                        "name": "Open Place",
                        "is_closed": False,
                        "url": "https://example.com",
                        "review_count": 10,
                        "categories": [{"alias": "pizza", "title": "Pizza"}],
                        "rating": 4.0,
                        "coordinates": {"latitude": 40.7, "longitude": -74.0},
                        "price": "$",
                        "location": {"address1": "1 Main St", "city": "Test", "state": "NY", "country": "US", "zip_code": "10001"},
                        "phone": "+15551234567",
                        "deals": [],
                    },
                    {
                        "id": "closed-place",
                        "name": "Closed Place",
                        "is_closed": True,
                        "url": "https://example.com/closed",
                        "review_count": 5,
                        "categories": [{"alias": "pizza", "title": "Pizza"}],
                        "rating": 3.0,
                        "coordinates": {"latitude": 40.7, "longitude": -74.0},
                        "price": "$",
                        "location": {"address1": "2 Main St", "city": "Test", "state": "NY", "country": "US", "zip_code": "10001"},
                        "phone": "+15551234568",
                        "deals": [],
                    },
                ]
            }
        }
        fp = tmp_path / "mock_yelp.json"
        fp.write_text(json.dumps(data))
        c = MockYelpConnector(fixture_path=fp)
        venues, _ = c.fetch("test")
        assert len(venues) == 1
        assert venues[0].name == "Open Place"

    def test_fetch_austin(self):
        venues, deals = _yelp_connector().fetch("austin")
        assert len(venues) >= 2
        assert len(deals) >= 2


# ── MockDiningConnector ───────────────────────────────────────────────────────


class TestMockDiningConnector:
    def test_available_cities(self):
        cities = _dining_connector().available_cities()
        assert "nyc" in cities
        assert "sf" in cities

    def test_fetch_returns_venues_and_deals(self):
        venues, deals = _dining_connector().fetch("nyc")
        assert len(venues) >= 3
        assert len(deals) >= 3

    def test_fetch_sf(self):
        venues, deals = _dining_connector().fetch("sf")
        assert len(venues) >= 2
        assert len(deals) >= 2

    def test_fetch_unknown_city_returns_empty(self):
        venues, deals = _dining_connector().fetch("miami")
        assert venues == []
        assert deals == []

    def test_venue_fields_populated(self):
        venues, _ = _dining_connector().fetch("nyc")
        carbone = next(v for v in venues if "Carbone" in v.name)
        assert carbone.external_id == "carbone-nyc"
        assert carbone.lat is not None
        assert carbone.lon is not None
        assert carbone.rating == 4.8
        assert carbone.price_range == "$$$$"
        assert carbone.category == "restaurant"

    def test_price_range_mapping(self):
        venues, _ = _dining_connector().fetch("nyc")
        katz = next(v for v in venues if "Katz" in v.name)
        assert katz.price_range == "$$"   # price_range=2 → "$$"

    def test_promotion_fields_populated(self):
        _, deals = _dining_connector().fetch("nyc")
        carbone_deal = next(d for d in deals if "Carbone" in (d.merchant or ""))
        assert "Prix Fixe" in carbone_deal.title
        assert carbone_deal.deal_price == 65.00
        assert carbone_deal.original_price == 110.00
        assert carbone_deal.description is not None

    def test_deal_raw_data_has_venue_id(self):
        _, deals = _dining_connector().fetch("nyc")
        for deal in deals:
            assert "venue_external_id" in deal.raw_data
            assert deal.raw_data["venue_external_id"] is not None

    def test_deal_schedule_metadata(self):
        _, deals = _dining_connector().fetch("nyc")
        theatre_deal = next(d for d in deals if "Pre-Theatre" in d.title)
        assert theatre_deal.raw_data["start_time"] == "17:00"
        assert theatre_deal.raw_data["end_time"] == "18:30"
        # Mon–Fri = indices 0,1,2,3,4
        assert theatre_deal.raw_data["valid_day_indices"] == [0, 1, 2, 3, 4]

    def test_discount_pct_in_raw_data(self):
        _, deals = _dining_connector().fetch("sf")
        pasta_deal = next(d for d in deals if "Pasta" in d.title)
        assert pasta_deal.raw_data["discount_pct"] == 50.0


# ── VenueIngestionPipeline ────────────────────────────────────────────────────


class TestVenueIngestionPipeline:
    def test_run_inserts_venues(self, fresh_db):
        pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        stats = pipeline.run("nyc")
        assert stats.venues_inserted >= 3
        assert stats.errors == []

    def test_run_inserts_deals(self, fresh_db):
        pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        stats = pipeline.run("nyc")
        assert stats.deals_inserted >= 3

    def test_run_creates_source_row(self, fresh_db):
        pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        pipeline.run("sf")
        source = fresh_db.query(Source).filter(Source.name == "mock_yelp").first()
        assert source is not None
        assert source.is_active is True

    def test_run_creates_city_row(self, fresh_db):
        from happybites.db.models import City
        pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        pipeline.run("nyc")
        city = fresh_db.query(City).filter(City.slug == "nyc").first()
        assert city is not None
        assert city.name == "New York"
        assert city.state == "NY"

    def test_run_creates_venue_source_mappings(self, fresh_db):
        pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        pipeline.run("nyc")
        source = fresh_db.query(Source).filter(Source.name == "mock_yelp").first()
        mappings = fresh_db.query(VenueSourceMapping).filter(
            VenueSourceMapping.source_id == source.id
        ).all()
        assert len(mappings) >= 3

    def test_run_stores_deal_raw_records(self, fresh_db):
        pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        stats = pipeline.run("nyc")
        raw_records = fresh_db.query(DealRaw).all()
        assert len(raw_records) == stats.raw_records_written
        assert stats.raw_records_written >= 3

    def test_deal_raw_has_content_hash(self, fresh_db):
        pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        pipeline.run("nyc")
        raw_records = fresh_db.query(DealRaw).all()
        for r in raw_records:
            assert r.content_hash is not None
            assert len(r.content_hash) == 16
            assert r.http_status == 200
            assert r.raw_payload is not None

    def test_deal_raw_payload_contains_source_deal_id(self, fresh_db):
        pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        pipeline.run("nyc")
        raw_records = fresh_db.query(DealRaw).all()
        for r in raw_records:
            assert "source_deal_id" in r.raw_payload

    def test_deals_linked_to_venues(self, fresh_db):
        pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        pipeline.run("nyc")
        deals_with_venue = fresh_db.query(Deal).filter(Deal.venue_id.isnot(None)).all()
        assert len(deals_with_venue) >= 3

    def test_deals_linked_to_city(self, fresh_db):
        pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        pipeline.run("nyc")
        deals_with_city = fresh_db.query(Deal).filter(Deal.city_id.isnot(None)).all()
        assert len(deals_with_city) >= 3

    def test_deals_are_not_online(self, fresh_db):
        pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        pipeline.run("nyc")
        deals = fresh_db.query(Deal).all()
        assert all(d.is_online is False for d in deals)

    def test_deal_schedules_created(self, fresh_db):
        pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        pipeline.run("nyc")
        schedules = fresh_db.query(DealSchedule).all()
        assert len(schedules) >= 3  # at least one per deal that has schedule

    def test_happy_hour_creates_weekday_schedules(self, fresh_db):
        pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        pipeline.run("nyc")
        # The Dead Rabbit happy hour is Mon-Fri
        hh_deal = fresh_db.query(Deal).filter(Deal.source_deal_id == "dead-rabbit-happy-hour").first()
        assert hh_deal is not None
        schedules = fresh_db.query(DealSchedule).filter(DealSchedule.deal_id == hh_deal.id).all()
        assert len(schedules) == 5  # Mon–Fri
        day_indices = {s.day_of_week for s in schedules}
        assert day_indices == {0, 1, 2, 3, 4}
        for s in schedules:
            assert s.start_time == "17:00"
            assert s.end_time == "19:00"

    def test_weekend_deal_creates_weekend_schedules(self, fresh_db):
        pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        pipeline.run("nyc")
        brunch_deal = fresh_db.query(Deal).filter(
            Deal.source_deal_id == "russ-daughters-weekend-brunch"
        ).first()
        assert brunch_deal is not None
        schedules = fresh_db.query(DealSchedule).filter(DealSchedule.deal_id == brunch_deal.id).all()
        assert len(schedules) == 2  # Sat + Sun
        day_indices = {s.day_of_week for s in schedules}
        assert day_indices == {5, 6}

    def test_idempotent_second_run_skips_deals(self, fresh_db):
        connector = MockYelpConnector()
        pipeline = VenueIngestionPipeline(fresh_db, connector)
        stats1 = pipeline.run("nyc")
        stats2 = pipeline.run("nyc")
        assert stats1.deals_inserted >= 3
        assert stats2.deals_inserted == 0
        assert stats2.deals_skipped == stats1.deals_inserted

    def test_idempotent_second_run_no_duplicate_venues(self, fresh_db):
        connector = MockYelpConnector()
        pipeline = VenueIngestionPipeline(fresh_db, connector)
        pipeline.run("nyc")
        count_after_first = fresh_db.query(Venue).count()
        pipeline.run("nyc")
        count_after_second = fresh_db.query(Venue).count()
        assert count_after_first == count_after_second

    def test_dining_connector_run(self, fresh_db):
        pipeline = VenueIngestionPipeline(fresh_db, MockDiningConnector())
        stats = pipeline.run("nyc")
        assert stats.venues_inserted >= 3
        assert stats.deals_inserted >= 3
        assert stats.errors == []

    def test_two_connectors_same_city_no_source_collision(self, fresh_db):
        yelp_pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        dining_pipeline = VenueIngestionPipeline(fresh_db, MockDiningConnector())
        yelp_stats = yelp_pipeline.run("nyc")
        dining_stats = dining_pipeline.run("nyc")
        assert yelp_stats.errors == []
        assert dining_stats.errors == []
        sources = fresh_db.query(Source).all()
        source_names = [s.name for s in sources]
        assert "mock_yelp" in source_names
        assert "mock_dining" in source_names

    def test_rank_score_set_on_deals(self, fresh_db):
        pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        pipeline.run("nyc")
        deals = fresh_db.query(Deal).all()
        assert all(d.rank_score is not None for d in deals)

    def test_ingestion_run_record_created(self, fresh_db):
        from happybites.db.models import IngestionRun
        pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        stats = pipeline.run("nyc")
        run = fresh_db.query(IngestionRun).filter(IngestionRun.id == stats.run_id).first()
        assert run is not None
        assert run.status == "success"
        assert run.deals_inserted >= 1
        assert run.finished_at is not None

    def test_unknown_city_returns_zero_stats(self, fresh_db):
        pipeline = VenueIngestionPipeline(fresh_db, MockYelpConnector())
        stats = pipeline.run("atlantis")
        assert stats.deals_inserted == 0
        assert stats.venues_inserted == 0


# ── Fixture sanity checks ─────────────────────────────────────────────────────


class TestFixtureSanity:
    def test_yelp_fixture_exists(self):
        assert (FIXTURE_DIR / "mock_yelp.json").exists()

    def test_dining_fixture_exists(self):
        assert (FIXTURE_DIR / "mock_dining.json").exists()

    def test_yelp_fixture_valid_json(self):
        data = json.loads((FIXTURE_DIR / "mock_yelp.json").read_text())
        assert isinstance(data, dict)
        assert "nyc" in data
        assert "sf" in data

    def test_dining_fixture_valid_json(self):
        data = json.loads((FIXTURE_DIR / "mock_dining.json").read_text())
        assert isinstance(data, dict)
        assert "nyc" in data
        assert "sf" in data

    def test_yelp_all_deals_have_required_fields(self):
        data = json.loads((FIXTURE_DIR / "mock_yelp.json").read_text())
        for city, city_data in data.items():
            for biz in city_data.get("businesses", []):
                for deal in biz.get("deals", []):
                    assert "deal_id" in deal, f"Missing deal_id in {city}/{biz['id']}"
                    assert "title" in deal, f"Missing title in {city}/{biz['id']}"
                    assert "url" in deal, f"Missing url in {city}/{biz['id']}"

    def test_dining_all_promos_have_required_fields(self):
        data = json.loads((FIXTURE_DIR / "mock_dining.json").read_text())
        for city, city_data in data.items():
            for restaurant in city_data.get("restaurants", []):
                for promo in restaurant.get("promotions", []):
                    assert "promo_id" in promo, f"Missing promo_id in {city}/{restaurant['restaurant_id']}"
                    assert "title" in promo, f"Missing title in {city}/{restaurant['restaurant_id']}"

    def test_yelp_deal_ids_are_unique_globally(self):
        data = json.loads((FIXTURE_DIR / "mock_yelp.json").read_text())
        ids = []
        for city_data in data.values():
            for biz in city_data.get("businesses", []):
                for deal in biz.get("deals", []):
                    ids.append(deal["deal_id"])
        assert len(ids) == len(set(ids)), "Duplicate deal_ids found in mock_yelp.json"

    def test_dining_promo_ids_are_unique_globally(self):
        data = json.loads((FIXTURE_DIR / "mock_dining.json").read_text())
        ids = []
        for city_data in data.values():
            for restaurant in city_data.get("restaurants", []):
                for promo in restaurant.get("promotions", []):
                    ids.append(promo["promo_id"])
        assert len(ids) == len(set(ids)), "Duplicate promo_ids found in mock_dining.json"
