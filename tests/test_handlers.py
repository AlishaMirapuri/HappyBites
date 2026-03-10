"""Unit tests for geo utilities and handler helpers."""

import math
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from happybites.api.geo import bounding_box, haversine_distance, is_deal_active_at


# ── haversine_distance ────────────────────────────────────────────────────────


def test_haversine_same_point():
    assert haversine_distance(37.7749, -122.4194, 37.7749, -122.4194) == pytest.approx(0.0)


def test_haversine_sf_to_nyc():
    # SF → NYC is approximately 2571 miles
    dist = haversine_distance(37.7749, -122.4194, 40.7128, -74.0060)
    assert 2500 < dist < 2650


def test_haversine_equator():
    # 1 degree of longitude at equator ≈ 69.17 miles
    dist = haversine_distance(0, 0, 0, 1)
    assert 68 < dist < 70


def test_haversine_symmetry():
    d1 = haversine_distance(37.7749, -122.4194, 40.7128, -74.0060)
    d2 = haversine_distance(40.7128, -74.0060, 37.7749, -122.4194)
    assert d1 == pytest.approx(d2)


def test_haversine_short_distance():
    # 0.01 degree at mid-latitudes ≈ ~0.6 miles
    dist = haversine_distance(37.0, -122.0, 37.01, -122.0)
    assert 0.5 < dist < 0.8


# ── bounding_box ──────────────────────────────────────────────────────────────


def test_bounding_box_structure():
    min_lat, max_lat, min_lon, max_lon = bounding_box(37.7749, -122.4194, 1.0)
    assert min_lat < 37.7749 < max_lat
    assert min_lon < -122.4194 < max_lon


def test_bounding_box_symmetric():
    lat, lon = 37.7749, -122.4194
    min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lon, 5.0)
    assert (max_lat - lat) == pytest.approx(lat - min_lat, rel=1e-9)
    assert (max_lon - lon) == pytest.approx(lon - min_lon, rel=1e-9)


def test_bounding_box_larger_radius_bigger_box():
    small = bounding_box(37.7749, -122.4194, 1.0)
    large = bounding_box(37.7749, -122.4194, 10.0)
    small_span = small[1] - small[0]
    large_span = large[1] - large[0]
    assert large_span > small_span


def test_bounding_box_point_inside():
    """Any point within radius_miles must fall inside the bounding box."""
    lat, lon = 37.7749, -122.4194
    radius = 5.0
    min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lon, radius)
    # A point 4 miles north
    north_lat = lat + (4.0 / 3958.8) * (180 / math.pi)
    assert min_lat <= north_lat <= max_lat


# ── is_deal_active_at ─────────────────────────────────────────────────────────


def _make_schedule(**kwargs):
    """Return a mock DealSchedule with sensible defaults."""
    sched = MagicMock()
    sched.day_of_week = kwargs.get("day_of_week", None)
    sched.start_time = kwargs.get("start_time", None)
    sched.end_time = kwargs.get("end_time", None)
    sched.valid_from = kwargs.get("valid_from", None)
    sched.valid_until = kwargs.get("valid_until", None)
    return sched


def _make_deal(schedules):
    deal = MagicMock()
    deal.schedules = schedules
    return deal


def test_no_schedules_always_active():
    deal = _make_deal([])
    t = datetime(2024, 6, 15, 14, 0, tzinfo=timezone.utc)
    assert is_deal_active_at(deal, t) is True


def test_schedule_any_day_any_time():
    deal = _make_deal([_make_schedule()])
    t = datetime(2024, 6, 15, 14, 0, tzinfo=timezone.utc)
    assert is_deal_active_at(deal, t) is True


def test_schedule_day_match():
    # 2024-06-17 is a Monday (weekday=0)
    t = datetime(2024, 6, 17, 14, 0, tzinfo=timezone.utc)
    deal = _make_deal([_make_schedule(day_of_week=0)])
    assert is_deal_active_at(deal, t) is True


def test_schedule_day_mismatch():
    # 2024-06-17 is Monday (0); schedule is for Tuesday (1)
    t = datetime(2024, 6, 17, 14, 0, tzinfo=timezone.utc)
    deal = _make_deal([_make_schedule(day_of_week=1)])
    assert is_deal_active_at(deal, t) is False


def test_schedule_time_window_inside():
    t = datetime(2024, 6, 17, 17, 30, tzinfo=timezone.utc)
    deal = _make_deal([_make_schedule(start_time="17:00", end_time="19:00")])
    assert is_deal_active_at(deal, t) is True


def test_schedule_time_window_outside():
    t = datetime(2024, 6, 17, 20, 0, tzinfo=timezone.utc)
    deal = _make_deal([_make_schedule(start_time="17:00", end_time="19:00")])
    assert is_deal_active_at(deal, t) is False


def test_schedule_time_window_at_boundary():
    t_start = datetime(2024, 6, 17, 17, 0, tzinfo=timezone.utc)
    t_end = datetime(2024, 6, 17, 19, 0, tzinfo=timezone.utc)
    sched = _make_schedule(start_time="17:00", end_time="19:00")
    deal = _make_deal([sched])
    assert is_deal_active_at(deal, t_start) is True
    assert is_deal_active_at(deal, t_end) is True


def test_schedule_valid_from_in_future():
    t = datetime(2024, 6, 17, 14, 0, tzinfo=timezone.utc)
    future = datetime(2024, 7, 1, 0, 0)
    deal = _make_deal([_make_schedule(valid_from=future)])
    assert is_deal_active_at(deal, t) is False


def test_schedule_valid_until_in_past():
    t = datetime(2024, 6, 17, 14, 0, tzinfo=timezone.utc)
    past = datetime(2024, 6, 1, 0, 0)
    deal = _make_deal([_make_schedule(valid_until=past)])
    assert is_deal_active_at(deal, t) is False


def test_schedule_multiple_one_matches():
    t = datetime(2024, 6, 17, 17, 30, tzinfo=timezone.utc)  # Monday 17:30
    schedules = [
        _make_schedule(day_of_week=2),  # Wednesday — no match
        _make_schedule(day_of_week=0, start_time="17:00", end_time="19:00"),  # Monday HH
    ]
    deal = _make_deal(schedules)
    assert is_deal_active_at(deal, t) is True


def test_schedule_multiple_none_matches():
    t = datetime(2024, 6, 17, 12, 0, tzinfo=timezone.utc)  # Monday noon
    schedules = [
        _make_schedule(day_of_week=2),  # Wednesday
        _make_schedule(day_of_week=0, start_time="17:00", end_time="19:00"),  # Monday HH only
    ]
    deal = _make_deal(schedules)
    assert is_deal_active_at(deal, t) is False


# ── _deal_to_response (handler helper) ───────────────────────────────────────


def test_deal_to_response_fields():
    """Smoke-test that _deal_to_response maps all expected fields without error."""
    import json as _json
    from happybites.api.routers.deals import _deal_to_response

    deal = MagicMock()
    deal.id = 1
    deal.title = "50% Off Tacos"
    deal.merchant = "Taco Town"
    deal.category = "Food & Dining"
    deal.original_price = 20.0
    deal.deal_price = 10.0
    deal.discount_pct = 50.0
    deal.currency = "USD"
    deal.url = "https://example.com"
    deal.image_url = None
    deal.location = "San Francisco"
    deal.is_online = False
    deal.starts_at = None
    deal.expires_at = None
    deal.fetched_at = datetime.now(timezone.utc)
    deal.first_seen_at = None
    deal.last_seen_at = None
    deal.rank_score = 0.8
    deal.quality_score = 0.9
    deal.confidence = 0.95
    deal.source.name = "seed"
    deal.city_id = 1
    deal.venue_id = None
    deal.tags = _json.dumps(["food", "tacos"])
    deal.is_verified = True

    resp = _deal_to_response(deal)
    assert resp.title == "50% Off Tacos"
    assert resp.tags == ["food", "tacos"]
    assert resp.currency == "USD"
    assert resp.is_verified is True
    assert resp.distance_m is None

    resp_nearby = _deal_to_response(deal, distance_m=250.5)
    assert resp_nearby.distance_m == 250.5
