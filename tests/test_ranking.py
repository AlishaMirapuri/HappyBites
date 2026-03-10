"""Tests for the ranking engine and /deals/nearby endpoint."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from happybites.db.models import City, Deal, Source, Venue
from happybites.ranking.engine import (
    DEFAULT_CONFIG,
    RankingConfig,
    ScoreInput,
    score_deal,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

_NOW = datetime(2024, 6, 15, 14, 0, tzinfo=timezone.utc)  # Saturday 14:00 UTC


def _inp(**kwargs) -> ScoreInput:
    defaults = dict(
        deal_id=1,
        discount_pct=20.0,
        fetched_at=_NOW - timedelta(hours=2),
        last_seen_at=_NOW - timedelta(hours=1),
        quality_score=0.8,
        confidence=0.7,
        category="Food & Dining",
        is_open_now=True,
        distance_miles=0.5,
        venue_source_count=2,
        preferred_categories=[],
        preferred_deal_types=[],
        now=_NOW,
    )
    defaults.update(kwargs)
    return ScoreInput(**defaults)


# ══════════════════════════════════════════════════════════════════════════════
# Unit tests — score_deal pure function
# ══════════════════════════════════════════════════════════════════════════════


class TestDealValueFeature:
    def test_zero_discount_contributes_zero(self):
        result = score_deal(_inp(discount_pct=0.0))
        assert result.debug["deal_value"] == 0.0

    def test_full_discount_caps_at_weight(self):
        cfg = DEFAULT_CONFIG
        result = score_deal(_inp(discount_pct=100.0))
        assert result.debug["deal_value"] == pytest.approx(cfg.w_deal_value, abs=1e-4)

    def test_fifty_percent_discount(self):
        cfg = DEFAULT_CONFIG
        result = score_deal(_inp(discount_pct=50.0))
        assert result.debug["deal_value"] == pytest.approx(cfg.w_deal_value * 0.5, abs=1e-4)

    def test_high_discount_generates_reason(self):
        # Suppress other strong signals so deal_value makes it into top 3
        result = score_deal(_inp(
            discount_pct=80.0,
            is_open_now=False,
            distance_miles=None,
            quality_score=0.0,
            confidence=0.0,
            last_seen_at=_NOW - timedelta(hours=200),
        ))
        assert any("80%" in r for r in result.reasons)

    def test_low_discount_no_reason(self):
        result = score_deal(_inp(discount_pct=5.0))
        assert not any("%" in r for r in result.reasons)


class TestOpenNowFeature:
    def test_open_now_true_boosts(self):
        cfg = DEFAULT_CONFIG
        result = score_deal(_inp(is_open_now=True))
        assert result.debug["open_now"] == pytest.approx(cfg.w_open_now, abs=1e-4)

    def test_open_now_false_zero(self):
        result = score_deal(_inp(is_open_now=False))
        assert result.debug["open_now"] == 0.0

    def test_open_now_none_neutral(self):
        cfg = DEFAULT_CONFIG
        result = score_deal(_inp(is_open_now=None))
        assert result.debug["open_now"] == pytest.approx(cfg.w_open_now * 0.5, abs=1e-4)

    def test_closed_deal_scores_lower_than_open(self):
        open_score = score_deal(_inp(is_open_now=True)).score
        closed_score = score_deal(_inp(is_open_now=False)).score
        assert open_score > closed_score

    def test_open_now_reason_included(self):
        result = score_deal(_inp(is_open_now=True, distance_miles=10.0, discount_pct=0))
        assert "Open now" in result.reasons


class TestFreshnessFeature:
    def test_very_fresh_deal_high_score(self):
        result = score_deal(_inp(last_seen_at=_NOW - timedelta(minutes=30)))
        # Should be near max weight
        assert result.debug["freshness"] > DEFAULT_CONFIG.w_freshness * 0.95

    def test_stale_deal_low_freshness(self):
        result = score_deal(_inp(last_seen_at=_NOW - timedelta(hours=200)))
        assert result.debug["freshness"] < DEFAULT_CONFIG.w_freshness * 0.05

    def test_halflife_decay(self):
        cfg = DEFAULT_CONFIG
        # At exactly halflife_hours, score should be ~0.5
        result = score_deal(_inp(last_seen_at=_NOW - timedelta(hours=cfg.freshness_halflife_hours)))
        expected = cfg.w_freshness * math.exp(-1.0)
        assert result.debug["freshness"] == pytest.approx(expected, rel=0.01)

    def test_falls_back_to_fetched_at(self):
        # No last_seen_at → use fetched_at
        result = score_deal(_inp(last_seen_at=None, fetched_at=_NOW - timedelta(hours=1)))
        assert result.debug["freshness"] > 0

    def test_fresh_stale_ordering(self):
        fresh = score_deal(_inp(last_seen_at=_NOW - timedelta(hours=1))).score
        stale = score_deal(_inp(last_seen_at=_NOW - timedelta(hours=96))).score
        assert fresh > stale


class TestDistanceFeature:
    def test_zero_distance_max_contribution(self):
        cfg = DEFAULT_CONFIG
        result = score_deal(_inp(distance_miles=0.0))
        assert result.debug["distance"] == pytest.approx(cfg.w_distance, abs=1e-4)

    def test_farther_lower_score(self):
        near = score_deal(_inp(distance_miles=0.1)).score
        far = score_deal(_inp(distance_miles=5.0)).score
        assert near > far

    def test_no_distance_neutral(self):
        cfg = DEFAULT_CONFIG
        result = score_deal(_inp(distance_miles=None))
        assert result.debug["distance"] == pytest.approx(cfg.w_distance * 0.5, abs=1e-4)

    def test_distance_generates_miles_reason(self):
        result = score_deal(_inp(distance_miles=2.5, discount_pct=0, is_open_now=False, quality_score=0, confidence=0))
        assert any("mi" in r for r in result.reasons)

    def test_very_close_generates_feet_reason(self):
        result = score_deal(_inp(distance_miles=0.05, discount_pct=0, is_open_now=False, quality_score=0, confidence=0))
        assert any("ft" in r for r in result.reasons)


class TestConfidenceFeature:
    def test_high_quality_score_contributes(self):
        cfg = DEFAULT_CONFIG
        result = score_deal(_inp(quality_score=1.0, confidence=0.0))
        assert result.debug["confidence"] == pytest.approx(cfg.w_confidence * 1.0, abs=1e-4)

    def test_uses_max_of_quality_and_confidence(self):
        cfg = DEFAULT_CONFIG
        result = score_deal(_inp(quality_score=0.3, confidence=0.9))
        assert result.debug["confidence"] == pytest.approx(cfg.w_confidence * 0.9, abs=1e-4)

    def test_none_values_default_zero(self):
        result = score_deal(_inp(quality_score=None, confidence=None))
        assert result.debug["confidence"] == 0.0


class TestPreferenceFeature:
    def test_matching_category_boosts(self):
        cfg = DEFAULT_CONFIG
        result = score_deal(_inp(
            category="Food & Dining",
            preferred_categories=["Food & Dining"],
        ))
        assert result.debug["preference_boost"] == pytest.approx(cfg.w_preference_boost, abs=1e-4)

    def test_non_matching_category_zero(self):
        result = score_deal(_inp(
            category="Electronics",
            preferred_categories=["Food & Dining"],
        ))
        assert result.debug["preference_boost"] == 0.0

    def test_case_insensitive_match(self):
        result = score_deal(_inp(
            category="food & dining",
            preferred_categories=["Food & Dining"],
        ))
        assert result.debug["preference_boost"] > 0

    def test_preference_reason_generated(self):
        result = score_deal(_inp(
            category="Food & Dining",
            preferred_categories=["Food & Dining"],
            discount_pct=0,
            distance_miles=10.0,
            is_open_now=False,
        ))
        assert any("Food & Dining" in r for r in result.reasons)


class TestVenuePopularity:
    def test_single_source_low(self):
        result = score_deal(_inp(venue_source_count=1))
        assert result.debug["venue_popularity"] > 0

    def test_more_sources_higher(self):
        one = score_deal(_inp(venue_source_count=1)).debug["venue_popularity"]
        five = score_deal(_inp(venue_source_count=5)).debug["venue_popularity"]
        assert five > one


class TestScoreRange:
    def test_score_in_range(self):
        result = score_deal(_inp())
        assert 0.0 <= result.score <= 1.0

    def test_perfect_deal_near_1(self):
        result = score_deal(_inp(
            discount_pct=100,
            is_open_now=True,
            last_seen_at=_NOW - timedelta(minutes=1),
            distance_miles=0.0,
            quality_score=1.0,
            confidence=1.0,
            venue_source_count=10,
            preferred_categories=["Food & Dining"],
        ))
        assert result.score > 0.85

    def test_worst_deal_near_0(self):
        result = score_deal(_inp(
            discount_pct=0,
            is_open_now=False,
            last_seen_at=_NOW - timedelta(days=30),
            distance_miles=50.0,
            quality_score=0.0,
            confidence=0.0,
            venue_source_count=1,
            preferred_categories=[],
        ))
        assert result.score < 0.15

    def test_returns_top_3_reasons(self):
        result = score_deal(_inp())
        assert len(result.reasons) <= 3

    def test_debug_has_all_features(self):
        result = score_deal(_inp())
        assert set(result.debug.keys()) == {
            "deal_value", "open_now", "freshness", "distance",
            "confidence", "venue_popularity", "preference_boost",
        }


class TestCustomConfig:
    def test_custom_weights_respected(self):
        cfg = RankingConfig(
            w_deal_value=0.8,
            w_open_now=0.0,
            w_freshness=0.0,
            w_distance=0.0,
            w_confidence=0.0,
            w_venue_popularity=0.0,
            w_preference_boost=0.2,
        )
        result = score_deal(_inp(discount_pct=100.0, preferred_categories=[]), cfg)
        # Only deal_value contributes (0.8 * 1.0 = 0.8)
        assert result.score == pytest.approx(0.8, abs=0.01)

    def test_distance_decay_param(self):
        slow_decay = RankingConfig(distance_decay_miles=10.0)
        fast_decay = RankingConfig(distance_decay_miles=0.5)
        slow = score_deal(_inp(discount_pct=0, distance_miles=1.0), slow_decay).debug["distance"]
        fast = score_deal(_inp(discount_pct=0, distance_miles=1.0), fast_decay).debug["distance"]
        assert slow > fast


# ══════════════════════════════════════════════════════════════════════════════
# Integration tests — /deals/nearby
# (uses conftest fixtures: db, client, seeded_db)
# ══════════════════════════════════════════════════════════════════════════════


def _seed_nearby(db: Session) -> None:
    """Seed one city + two venues + two deals at different distances.
    Reuses the 'dealnews' source that seeded_db already created.
    """
    city = db.query(City).filter(City.slug == "sf-ranking-test").first()
    if not city:
        city = City(name="San Francisco", state="CA", country="US", slug="sf-ranking-test",
                    lat=37.7749, lon=-122.4194, is_active=True)
        db.add(city)
        db.flush()

    source = db.query(Source).filter(Source.name == "dealnews").first()
    assert source is not None, "seeded_db must provide 'dealnews' source"

    # Skip seeding if already done (idempotent for savepoint-isolated sessions)
    if db.query(Deal).filter(Deal.source_deal_id == "ranking-near-1").first():
        return

    # Venue close to SF center (~0.1 mi)
    venue_near = Venue(name="Joe's Diner", slug="joes-diner-ranking", city_id=city.id,
                       lat=37.7749, lon=-122.4194, confidence=0.9, is_active=True)
    # Venue farther away (~3 mi)
    venue_far = Venue(name="Far Away Grill", slug="far-away-grill-ranking", city_id=city.id,
                      lat=37.7980, lon=-122.4200, confidence=0.5, is_active=True)
    db.add_all([venue_near, venue_far])
    db.flush()

    now = datetime.now(timezone.utc)
    deal_near = Deal(
        title="Happy Hour 50% Off",
        url="http://example.com/near",
        currency="USD",
        is_active=True,
        is_online=False,
        is_verified=False,
        source_id=source.id,
        source_deal_id="ranking-near-1",
        city_id=city.id,
        venue_id=venue_near.id,
        lat=37.7749,
        lon=-122.4194,
        discount_pct=50.0,
        quality_score=0.9,
        confidence=0.9,
        fetched_at=now,
        last_seen_at=now,
        category="Food & Dining",
    )
    deal_far = Deal(
        title="Lunch Special",
        url="http://example.com/far",
        currency="USD",
        is_active=True,
        is_online=False,
        is_verified=False,
        source_id=source.id,
        source_deal_id="ranking-far-1",
        city_id=city.id,
        venue_id=venue_far.id,
        lat=37.7980,
        lon=-122.4200,
        discount_pct=10.0,
        quality_score=0.5,
        confidence=0.5,
        fetched_at=now - timedelta(hours=36),
        last_seen_at=now - timedelta(hours=36),
        category="Food & Dining",
    )
    db.add_all([deal_near, deal_far])
    db.commit()


_NEARBY_PARAMS = {"lat": 37.7749, "lng": -122.4194, "city": "sf-ranking-test"}


class TestNearbyEndpoint:
    def test_returns_deals_within_radius(self, client, seeded_db):
        _seed_nearby(seeded_db)
        r = client.get("/deals/nearby", params={**_NEARBY_PARAMS, "radius_m": 200})
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Happy Hour 50% Off"

    def test_larger_radius_includes_both(self, client, seeded_db):
        _seed_nearby(seeded_db)
        r = client.get("/deals/nearby", params={**_NEARBY_PARAMS, "radius_m": 10000})
        assert r.status_code == 200
        assert r.json()["total"] == 2

    def test_ranked_by_score_not_distance(self, client, seeded_db):
        _seed_nearby(seeded_db)
        r = client.get("/deals/nearby", params={**_NEARBY_PARAMS, "radius_m": 10000})
        items = r.json()["items"]
        # Near deal has 50% discount + high confidence + closer → should rank first
        assert items[0]["title"] == "Happy Hour 50% Off"

    def test_rank_reasons_present(self, client, seeded_db):
        _seed_nearby(seeded_db)
        r = client.get("/deals/nearby", params={**_NEARBY_PARAMS, "radius_m": 10000})
        items = r.json()["items"]
        for item in items:
            assert item["rank_reasons"] is not None
            assert isinstance(item["rank_reasons"], list)

    def test_debug_not_included_by_default(self, client, seeded_db):
        _seed_nearby(seeded_db)
        r = client.get("/deals/nearby", params={**_NEARBY_PARAMS, "radius_m": 10000})
        items = r.json()["items"]
        for item in items:
            assert item.get("rank_debug") is None

    def test_debug_included_when_requested(self, client, seeded_db):
        _seed_nearby(seeded_db)
        r = client.get("/deals/nearby", params={**_NEARBY_PARAMS, "radius_m": 10000, "debug": "true"})
        items = r.json()["items"]
        for item in items:
            assert item["rank_debug"] is not None
            assert "deal_value" in item["rank_debug"]

    def test_category_filter(self, client, seeded_db):
        _seed_nearby(seeded_db)
        r = client.get("/deals/nearby", params={**_NEARBY_PARAMS, "radius_m": 10000, "category": "Electronics"})
        assert r.json()["total"] == 0

    def test_missing_lat_422(self, client):
        r = client.get("/deals/nearby", params={"lng": -122.4194})
        assert r.status_code == 422

    def test_distance_m_populated(self, client, seeded_db):
        _seed_nearby(seeded_db)
        r = client.get("/deals/nearby", params={**_NEARBY_PARAMS, "radius_m": 10000})
        items = r.json()["items"]
        for item in items:
            assert item["distance_m"] is not None

    def test_pagination(self, client, seeded_db):
        _seed_nearby(seeded_db)
        r1 = client.get("/deals/nearby", params={**_NEARBY_PARAMS, "radius_m": 10000, "limit": 1, "offset": 0})
        r2 = client.get("/deals/nearby", params={**_NEARBY_PARAMS, "radius_m": 10000, "limit": 1, "offset": 1})
        assert r1.json()["total"] == 2
        assert len(r1.json()["items"]) == 1
        assert len(r2.json()["items"]) == 1
        assert r1.json()["items"][0]["id"] != r2.json()["items"][0]["id"]
