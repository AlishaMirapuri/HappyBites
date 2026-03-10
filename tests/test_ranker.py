"""Unit tests for the ranking formula."""

from datetime import datetime, timedelta, timezone

import pytest

from happybites.ingestion.ranker import compute_rank_score


FROZEN_NOW = datetime(2026, 3, 6, 12, 0, 0, tzinfo=timezone.utc)


def test_perfect_deal_scores_near_one():
    fetched_at = FROZEN_NOW - timedelta(minutes=5)
    score = compute_rank_score(
        discount_pct=80.0,
        fetched_at=fetched_at,
        quality_score=1.0,
        now=FROZEN_NOW,
    )
    assert score > 0.90, f"Expected > 0.90, got {score}"


def test_stale_deal_scores_lower():
    fresh = FROZEN_NOW - timedelta(hours=1)
    stale = FROZEN_NOW - timedelta(hours=120)

    fresh_score = compute_rank_score(50.0, fresh, 0.8, now=FROZEN_NOW)
    stale_score = compute_rank_score(50.0, stale, 0.8, now=FROZEN_NOW)

    assert fresh_score > stale_score


def test_higher_discount_scores_higher():
    fetched = FROZEN_NOW - timedelta(hours=6)
    low = compute_rank_score(10.0, fetched, 0.7, now=FROZEN_NOW)
    high = compute_rank_score(60.0, fetched, 0.7, now=FROZEN_NOW)
    assert high > low


def test_category_boost_adds_ten_points():
    fetched = FROZEN_NOW - timedelta(hours=2)
    without = compute_rank_score(30.0, fetched, 0.7, category_boost=False, now=FROZEN_NOW)
    with_boost = compute_rank_score(30.0, fetched, 0.7, category_boost=True, now=FROZEN_NOW)
    assert abs(with_boost - without - 0.10) < 0.01


def test_category_boost_capped_at_one():
    fetched = FROZEN_NOW  # perfectly fresh
    score = compute_rank_score(100.0, fetched, 1.0, category_boost=True, now=FROZEN_NOW)
    assert score <= 1.0


def test_none_discount_treated_as_zero():
    fetched = FROZEN_NOW - timedelta(hours=1)
    score = compute_rank_score(None, fetched, 0.5, now=FROZEN_NOW)
    assert 0.0 <= score <= 1.0


def test_none_quality_defaults_to_half():
    fetched = FROZEN_NOW - timedelta(hours=1)
    score_none = compute_rank_score(30.0, fetched, None, now=FROZEN_NOW)
    score_half = compute_rank_score(30.0, fetched, 0.5, now=FROZEN_NOW)
    assert score_none == score_half


def test_score_always_between_zero_and_one():
    cases = [
        (None, FROZEN_NOW, None),
        (0.0, FROZEN_NOW - timedelta(days=30), 0.0),
        (150.0, FROZEN_NOW, 2.0),  # out of range inputs
    ]
    for discount, fetched, quality in cases:
        score = compute_rank_score(discount, fetched, quality, now=FROZEN_NOW)
        assert 0.0 <= score <= 1.0, f"Out of range: {score} for {(discount, fetched, quality)}"
