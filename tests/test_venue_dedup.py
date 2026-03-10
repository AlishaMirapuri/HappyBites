"""Tests for venue entity resolution and deduplication.

Covers:
  - Unit tests for matcher.py (phone normalisation, name fuzzy matching,
    street extraction, geo distance, chain collision detection, score clamping)
  - Unit tests for resolver.py (batch candidate generation, ordering, filtering)
  - Integration tests for FastAPI endpoints via TestClient
    (GET /admin/venue_matches, POST /admin/merge_venues)
  - Repository-level merge_venues tests
"""

from __future__ import annotations

import pytest

from happybites.venue_dedup.matcher import (
    VenueSnapshot,
    MatchResult,
    _normalize_phone,
    _normalize_name,
    _extract_street,
    _haversine_miles,
    match_venues,
)
from happybites.venue_dedup.resolver import find_duplicate_candidates


# ── Helpers ───────────────────────────────────────────────────────────────────


def snap(
    id: int = 1,
    name: str = "The Rusty Anchor",
    address: str | None = None,
    phone: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    city_id: int | None = 1,
    source_count: int = 1,
) -> VenueSnapshot:
    return VenueSnapshot(
        id=id, name=name, address=address, phone=phone,
        lat=lat, lon=lon, city_id=city_id, source_count=source_count,
    )


# ── Phone normalisation ───────────────────────────────────────────────────────


class TestNormalizePhone:
    def test_strips_formatting(self):
        assert _normalize_phone("(212) 555-1234") == "2125551234"

    def test_strips_country_code(self):
        assert _normalize_phone("+1-212-555-1234") == "2125551234"

    def test_none_returns_none(self):
        assert _normalize_phone(None) is None

    def test_too_short_returns_none(self):
        assert _normalize_phone("123") is None

    def test_dots(self):
        assert _normalize_phone("212.555.1234") == "2125551234"

    def test_seven_digit_local(self):
        # 7 digits still valid
        assert _normalize_phone("555-1234") == "5551234"


# ── Name normalisation ────────────────────────────────────────────────────────


class TestNormalizeName:
    def test_lowercases(self):
        assert _normalize_name("The SPOTTED Dog") == "the spotted dog"

    def test_strips_punctuation(self):
        assert "'" not in _normalize_name("O'Malley's")

    def test_collapses_whitespace(self):
        result = _normalize_name("Joe's   Bar  & Grill")
        assert "  " not in result

    def test_unicode_normalization(self):
        result = _normalize_name("Café Central")
        # é → e after NFD decomposition and strip
        assert "caf" in result.lower()


# ── Street extraction ─────────────────────────────────────────────────────────


class TestExtractStreet:
    def test_splits_on_comma(self):
        result = _extract_street("123 Main Street, New York, NY 10001")
        assert result == "123 main street"

    def test_normalizes_st_suffix(self):
        result = _extract_street("45 Park St., Brooklyn")
        assert "street" in result

    def test_normalizes_ave(self):
        result = _extract_street("22 Broadway Ave, Manhattan")
        assert "avenue" in result

    def test_none_returns_none(self):
        assert _extract_street(None) is None

    def test_no_comma(self):
        result = _extract_street("100 W 57th St")
        assert result is not None


# ── Haversine ─────────────────────────────────────────────────────────────────


class TestHaversine:
    def test_same_point(self):
        assert _haversine_miles(40.7128, -74.0060, 40.7128, -74.0060) == pytest.approx(0.0, abs=1e-6)

    def test_known_distance(self):
        # NYC to roughly 1 mile north
        d = _haversine_miles(40.7128, -74.0060, 40.7273, -74.0060)
        assert 0.9 < d < 1.1

    def test_transatlantic(self):
        # NYC to London is roughly 3459 miles
        d = _haversine_miles(40.7128, -74.0060, 51.5074, -0.1278)
        assert 3400 < d < 3600


# ── match_venues ──────────────────────────────────────────────────────────────


class TestMatchVenues:
    def test_returns_none_below_threshold(self):
        a = snap(1, "The Blue Moon", phone="2125551111")
        b = snap(2, "Totally Different Place", phone="9175559999")
        assert match_venues(a, b) is None

    def test_phone_match_boosts_score(self):
        a = snap(1, "Blue Moon Bar", phone="2125551234")
        b = snap(2, "Blue Moon Bar & Grill", phone="2125551234")
        result = match_venues(a, b)
        assert result is not None
        # phone (+0.40) + similar name 81% (+0.20) = 0.60 — above review threshold
        assert result.match_score >= 0.55
        phone_reasons = [r for r in result.reasons if r.field == "phone"]
        assert any(r.score_delta > 0 for r in phone_reasons)

    def test_phone_mismatch_penalises(self):
        a = snap(1, "The Blue Moon", phone="2125551111")
        b = snap(2, "The Blue Moon", phone="9175559999")
        result = match_venues(a, b)
        # Name is identical, but phone mismatch reduces score
        if result:
            # Name-only match without phone mismatch would be high; mismatch drags it down
            phone_reasons = [r for r in result.reasons if r.field == "phone"]
            assert any(r.score_delta < 0 for r in phone_reasons)

    def test_identical_name_no_other_signals(self):
        a = snap(1, "Spotted Dog")
        b = snap(2, "Spotted Dog")
        result = match_venues(a, b)
        assert result is not None
        assert result.match_score >= 0.30
        assert result.confidence == "review"  # name only → not high confidence

    def test_geo_close_boosts(self):
        # 0.01 miles apart → same-building bonus
        a = snap(1, "Anchor Bar", lat=40.7128, lon=-74.0060)
        b = snap(2, "Anchor Bar", lat=40.7129, lon=-74.0060)
        result = match_venues(a, b)
        assert result is not None
        geo_reasons = [r for r in result.reasons if r.field == "geo"]
        assert any(r.score_delta > 0 for r in geo_reasons)

    def test_geo_far_penalises(self):
        a = snap(1, "Anchor Bar", lat=40.7128, lon=-74.0060)
        b = snap(2, "Anchor Bar", lat=40.7500, lon=-74.0060)  # ~2.6 miles away
        result = match_venues(a, b)
        if result:
            geo_reasons = [r for r in result.reasons if r.field == "geo"]
            assert any(r.score_delta < 0 for r in geo_reasons)

    def test_chain_collision_detected_with_phone_signal(self):
        # Same name + same phone (boosts score above threshold), but far apart → chain collision
        a = snap(1, "Shake Shack", phone="2125551234", lat=40.7589, lon=-73.9851)
        b = snap(2, "Shake Shack", phone="2125551234", lat=40.6892, lon=-74.0445)
        result = match_venues(a, b)
        assert result is not None
        assert result.is_chain_collision is True

    def test_chain_collision_not_triggered_when_close(self):
        # Same name AND close together → not a chain collision
        a = snap(1, "Shake Shack", lat=40.7589, lon=-73.9851)
        b = snap(2, "Shake Shack", lat=40.7590, lon=-73.9852)
        result = match_venues(a, b)
        assert result is not None
        assert result.is_chain_collision is False

    def test_name_only_far_apart_below_threshold(self):
        # Same name but geo penalty brings score below threshold → correctly excluded
        a = snap(1, "Shake Shack", lat=40.7589, lon=-73.9851)
        b = snap(2, "Shake Shack", lat=40.6892, lon=-74.0445)  # ~5 miles away
        result = match_venues(a, b)
        # 0.35 (name) - 0.15 (geo penalty) = 0.20 → below _REVIEW_THRESHOLD
        assert result is None

    def test_street_match_boosts(self):
        a = snap(1, "The Anchor", address="45 West 45th Street, New York, NY")
        b = snap(2, "The Anchor Bar", address="45 W 45th St., New York, NY")
        result = match_venues(a, b)
        assert result is not None
        street_reasons = [r for r in result.reasons if r.field == "street"]
        assert len(street_reasons) > 0

    def test_fields_used_populated(self):
        a = snap(1, "Joe's Bar", phone="2125551234", address="100 Main St, NYC", lat=40.71, lon=-74.00)
        b = snap(2, "Joe's Bar", phone="2125551234", address="100 Main St, NYC", lat=40.71, lon=-74.00)
        result = match_venues(a, b)
        assert result is not None
        assert "phone" in result.fields_used
        assert "name" in result.fields_used

    def test_score_clamped_to_one(self):
        # Perfect match on all signals should not exceed 1.0
        a = snap(1, "Joe's Bar", phone="2125551234", address="100 Main St, NYC",
                 lat=40.7128, lon=-74.0060)
        b = snap(2, "Joe's Bar", phone="2125551234", address="100 Main St, NYC",
                 lat=40.7128, lon=-74.0061)
        result = match_venues(a, b)
        assert result is not None
        assert result.match_score <= 1.0

    def test_score_non_negative(self):
        # Multiple penalties shouldn't go below 0.0 (and below threshold = None)
        a = snap(1, "AAA Diner", phone="2125551111")
        b = snap(2, "ZZZ Bistro", phone="9175559999", lat=40.0, lon=-74.0)
        result = match_venues(a, b)
        # Either None or clamped ≥ 0
        if result:
            assert result.match_score >= 0.0

    def test_different_city_ids_still_matches(self):
        # match_venues itself doesn't filter by city_id; resolver does
        a = snap(1, "Spotted Dog", city_id=1)
        b = snap(2, "Spotted Dog", city_id=2)
        result = match_venues(a, b)
        assert result is not None  # matcher is city-agnostic


# ── find_duplicate_candidates ─────────────────────────────────────────────────


class TestFindDuplicateCandidates:
    def test_empty_list(self):
        assert find_duplicate_candidates([]) == []

    def test_single_venue(self):
        assert find_duplicate_candidates([snap(1)]) == []

    def test_finds_obvious_duplicate(self):
        a = snap(1, "The Blue Moon Bar", phone="2125551234", city_id=1)
        b = snap(2, "Blue Moon Bar", phone="2125551234", city_id=1)
        results = find_duplicate_candidates([a, b])
        assert len(results) == 1

    def test_sorted_by_score_descending(self):
        # Strong match + weak match
        a = snap(1, "Spotted Dog", phone="2125551111", city_id=1)
        b = snap(2, "Spotted Dog", phone="2125551111", city_id=1)
        c = snap(3, "Spotted Frog", city_id=1)
        results = find_duplicate_candidates([a, b, c])
        scores = [r.match_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_same_city_only_filters_cross_city(self):
        a = snap(1, "Joe's Bar", phone="2125551234", city_id=1)
        b = snap(2, "Joe's Bar", phone="2125551234", city_id=2)
        results = find_duplicate_candidates([a, b], same_city_only=True)
        assert len(results) == 0

    def test_same_city_only_false_allows_cross_city(self):
        a = snap(1, "Joe's Bar", phone="2125551234", city_id=1)
        b = snap(2, "Joe's Bar", phone="2125551234", city_id=2)
        results = find_duplicate_candidates([a, b], same_city_only=False)
        assert len(results) == 1

    def test_primary_has_more_source_mappings(self):
        # Venue with source_count=3 should be venue_a in the result
        a = snap(1, "Joe's Bar", phone="2125551234", city_id=1, source_count=1)
        b = snap(2, "Joe's Bar", phone="2125551234", city_id=1, source_count=3)
        results = find_duplicate_candidates([a, b])
        assert len(results) == 1
        assert results[0].venue_a.id == 2  # the one with more mappings

    def test_no_candidates_below_threshold(self):
        a = snap(1, "AAA Diner", city_id=1)
        b = snap(2, "ZZZ Bistro", city_id=1)
        # Low name similarity, no other signals → should be below 0.40
        results = find_duplicate_candidates([a, b])
        for r in results:
            assert r.match_score >= 0.40

    def test_skip_none_city_id_with_same_city_only(self):
        a = snap(1, "Joe's Bar", phone="2125551234", city_id=None)
        b = snap(2, "Joe's Bar", phone="2125551234", city_id=1)
        results = find_duplicate_candidates([a, b], same_city_only=True)
        assert len(results) == 0


# ── Repository: merge_venues ──────────────────────────────────────────────────


class TestMergeVenuesRepo:
    def _make_venue(self, db, name: str, city_id: int = None) -> "Venue":
        from happybites.db.models import Venue
        v = Venue(name=name, city_id=city_id, confidence=0.8)
        db.add(v)
        db.flush()
        return v

    def test_merge_reassigns_deals(self, fresh_db):
        from happybites.db.models import Source, Deal, Venue
        from happybites.db import repositories as repo
        from datetime import datetime, timezone

        src = Source(name="test_src", type="api", fetch_interval=3600,
                     confidence_weight=1.0, consecutive_failures=0)
        fresh_db.add(src)
        fresh_db.flush()

        primary = self._make_venue(fresh_db, "Primary Venue")
        secondary = self._make_venue(fresh_db, "Secondary Venue")
        fresh_db.commit()

        # Attach a deal to secondary
        deal = Deal(
            source_id=src.id,
            source_deal_id="d001",
            title="Happy Hour",
            url="http://example.com",
            fetched_at=datetime.now(timezone.utc),
            venue_id=secondary.id,
        )
        fresh_db.add(deal)
        fresh_db.commit()

        mappings_moved, deals_moved = repo.merge_venues(
            fresh_db, primary_id=primary.id, secondary_id=secondary.id
        )

        assert deals_moved == 1
        fresh_db.refresh(deal)
        assert deal.venue_id == primary.id

    def test_merge_deactivates_secondary(self, fresh_db):
        from happybites.db import repositories as repo
        primary = self._make_venue(fresh_db, "Primary")
        secondary = self._make_venue(fresh_db, "Secondary")
        fresh_db.commit()

        repo.merge_venues(fresh_db, primary_id=primary.id, secondary_id=secondary.id)
        fresh_db.refresh(secondary)
        assert secondary.is_active is False

    def test_merge_raises_on_same_id(self, fresh_db):
        from happybites.db import repositories as repo
        primary = self._make_venue(fresh_db, "Primary")
        fresh_db.commit()

        with pytest.raises(ValueError, match="differ"):
            repo.merge_venues(fresh_db, primary_id=primary.id, secondary_id=primary.id)

    def test_merge_raises_on_missing_venue(self, fresh_db):
        from happybites.db import repositories as repo
        primary = self._make_venue(fresh_db, "Primary")
        fresh_db.commit()

        with pytest.raises(ValueError, match="not found"):
            repo.merge_venues(fresh_db, primary_id=primary.id, secondary_id=99999)

    def test_merge_source_mappings_reassigned(self, fresh_db):
        from happybites.db.models import Source, VenueSourceMapping
        from happybites.db import repositories as repo

        src = Source(name="src_for_vsm", type="api", fetch_interval=3600,
                     confidence_weight=1.0, consecutive_failures=0)
        fresh_db.add(src)
        fresh_db.flush()

        primary = self._make_venue(fresh_db, "Primary")
        secondary = self._make_venue(fresh_db, "Secondary")
        fresh_db.commit()

        vsm = VenueSourceMapping(
            venue_id=secondary.id, source_id=src.id, external_id="ext-001", confidence=1.0
        )
        fresh_db.add(vsm)
        fresh_db.commit()

        repo.merge_venues(fresh_db, primary_id=primary.id, secondary_id=secondary.id)
        fresh_db.refresh(vsm)
        assert vsm.venue_id == primary.id

    def test_merge_updates_primary_confidence(self, fresh_db):
        """Primary's confidence is raised to the max of the two venues."""
        from happybites.db import repositories as repo
        from happybites.db.models import Venue

        primary = Venue(name="Primary", confidence=0.7)
        secondary = Venue(name="Secondary", confidence=0.95)
        fresh_db.add_all([primary, secondary])
        fresh_db.commit()

        repo.merge_venues(fresh_db, primary_id=primary.id, secondary_id=secondary.id)
        fresh_db.refresh(primary)
        assert primary.confidence == pytest.approx(0.95)


# ── Integration: /admin/venue_matches ────────────────────────────────────────


class TestVenueMatchesEndpoint:
    def _seed_venues(self, db):
        """Insert two near-duplicate venues (idempotent: reuses existing city)."""
        from happybites.db.models import Venue, City

        city = db.query(City).filter(City.slug == "new-york-ny").first()
        if not city:
            city = City(name="New York", slug="new-york-ny", country="US")
            db.add(city)
            db.flush()

        v1 = Venue(name="The Blue Moon Bar", phone="2125551234", city_id=city.id,
                   address="45 Main St, New York, NY", lat=40.7128, lon=-74.0060,
                   confidence=1.0)
        v2 = Venue(name="Blue Moon Bar & Grill", phone="2125551234", city_id=city.id,
                   address="45 Main Street, New York, NY", lat=40.7128, lon=-74.0061,
                   confidence=0.9)
        db.add_all([v1, v2])
        db.commit()
        return city

    def test_returns_candidates(self, client, seeded_db):
        city = self._seed_venues(seeded_db)
        response = client.get("/admin/venue_matches", params={"city": "new-york-ny"})
        assert response.status_code == 200
        data = response.json()
        assert data["total_venues_scanned"] == 2
        assert len(data["candidates"]) >= 1

    def test_high_confidence_pair(self, client, seeded_db):
        self._seed_venues(seeded_db)
        response = client.get("/admin/venue_matches", params={"city": "new-york-ny"})
        assert response.status_code == 200
        candidates = response.json()["candidates"]
        assert candidates[0]["confidence"] == "high"
        assert candidates[0]["match_score"] >= 0.70

    def test_reasons_present(self, client, seeded_db):
        self._seed_venues(seeded_db)
        response = client.get("/admin/venue_matches", params={"city": "new-york-ny"})
        assert response.status_code == 200
        candidate = response.json()["candidates"][0]
        assert len(candidate["reasons"]) > 0
        assert "fields_used" in candidate

    def test_unknown_city_returns_404(self, client, seeded_db):
        response = client.get("/admin/venue_matches", params={"city": "no-such-city"})
        assert response.status_code == 404

    def test_no_city_scans_all(self, client, seeded_db):
        self._seed_venues(seeded_db)
        response = client.get("/admin/venue_matches")
        assert response.status_code == 200
        data = response.json()
        assert data["total_venues_scanned"] >= 2


# ── Integration: /admin/merge_venues ─────────────────────────────────────────


class TestMergeVenuesEndpoint:
    def _seed_pair(self, db):
        from happybites.db.models import Venue
        v1 = Venue(name="Primary Venue", confidence=1.0)
        v2 = Venue(name="Secondary Venue", confidence=0.8)
        db.add_all([v1, v2])
        db.commit()
        return v1, v2

    def test_merge_success(self, client, seeded_db):
        v1, v2 = self._seed_pair(seeded_db)
        response = client.post(
            "/admin/merge_venues",
            json={"primary_venue_id": v1.id, "secondary_venue_id": v2.id, "force": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["primary_venue_id"] == v1.id
        assert "Merged" in data["message"]

    def test_merge_deactivates_secondary(self, client, seeded_db):
        from happybites.db.models import Venue
        v1, v2 = self._seed_pair(seeded_db)
        client.post(
            "/admin/merge_venues",
            json={"primary_venue_id": v1.id, "secondary_venue_id": v2.id, "force": False},
        )
        seeded_db.expire_all()
        v2_refreshed = seeded_db.get(Venue, v2.id)
        assert v2_refreshed.is_active is False

    def test_merge_missing_primary_404(self, client, seeded_db):
        _, v2 = self._seed_pair(seeded_db)
        response = client.post(
            "/admin/merge_venues",
            json={"primary_venue_id": 99999, "secondary_venue_id": v2.id},
        )
        assert response.status_code == 404

    def test_merge_missing_secondary_404(self, client, seeded_db):
        v1, _ = self._seed_pair(seeded_db)
        response = client.post(
            "/admin/merge_venues",
            json={"primary_venue_id": v1.id, "secondary_venue_id": 99999},
        )
        assert response.status_code == 404

    def test_merge_already_inactive_409(self, client, seeded_db):
        from happybites.db.models import Venue
        v1, v2 = self._seed_pair(seeded_db)
        v2.is_active = False
        seeded_db.commit()
        response = client.post(
            "/admin/merge_venues",
            json={"primary_venue_id": v1.id, "secondary_venue_id": v2.id},
        )
        assert response.status_code == 409

    def test_chain_collision_rejected_without_force(self, client, seeded_db):
        from happybites.db.models import Venue
        # Two Shake Shacks far apart — same phone makes match_venues return a result with chain flag
        v1 = Venue(name="Shake Shack", phone="2125551234", lat=40.7589, lon=-73.9851, confidence=1.0)
        v2 = Venue(name="Shake Shack", phone="2125551234", lat=40.6892, lon=-74.0445, confidence=1.0)
        seeded_db.add_all([v1, v2])
        seeded_db.commit()
        response = client.post(
            "/admin/merge_venues",
            json={"primary_venue_id": v1.id, "secondary_venue_id": v2.id, "force": False},
        )
        assert response.status_code == 409
        assert "chain collision" in response.json()["detail"].lower()

    def test_chain_collision_allowed_with_force(self, client, seeded_db):
        from happybites.db.models import Venue
        v1 = Venue(name="Shake Shack", phone="2125551234", lat=40.7589, lon=-73.9851, confidence=1.0)
        v2 = Venue(name="Shake Shack", phone="2125551234", lat=40.6892, lon=-74.0445, confidence=1.0)
        seeded_db.add_all([v1, v2])
        seeded_db.commit()
        response = client.post(
            "/admin/merge_venues",
            json={"primary_venue_id": v1.id, "secondary_venue_id": v2.id, "force": True},
        )
        assert response.status_code == 200
