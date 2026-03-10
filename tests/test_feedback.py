"""Tests for the feedback / quality adjustment system."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from happybites.db.models import City, Deal, EventLog, Source
from happybites.feedback.quality import (
    EXPIRED_THRESHOLD,
    INCORRECT_THRESHOLD,
    apply_quality_adjustments,
    count_reports,
    demote_deal,
    expire_deal,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

_NOW = datetime.now(timezone.utc)


def _make_deal(db: Session, source_id: int, **kwargs) -> Deal:
    defaults = dict(
        title="Test Deal",
        url="http://example.com/test",
        currency="USD",
        is_active=True,
        is_online=False,
        is_verified=False,
        source_deal_id=f"td-{id(kwargs)}",
        fetched_at=_NOW,
        quality_score=0.8,
        confidence=0.7,
    )
    defaults.update(kwargs)
    deal = Deal(source_id=source_id, **defaults)
    db.add(deal)
    db.flush()
    return deal


def _add_events(db: Session, deal_id: int, event_type: str, count: int) -> None:
    for i in range(count):
        db.add(EventLog(
            deal_id=deal_id,
            event_type=event_type,
            session_id=f"sess-{i}",
        ))
    db.flush()


@pytest.fixture()
def source(seeded_db):
    return seeded_db.query(Source).filter(Source.name == "dealnews").first()


# ══════════════════════════════════════════════════════════════════════════════
# Unit: count_reports
# ══════════════════════════════════════════════════════════════════════════════


class TestCountReports:
    def test_zero_when_no_events(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id)
        assert count_reports(seeded_db, deal.id, "report_incorrect") == 0

    def test_counts_matching_type(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id)
        _add_events(seeded_db, deal.id, "report_incorrect", 2)
        assert count_reports(seeded_db, deal.id, "report_incorrect") == 2

    def test_does_not_count_other_types(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id)
        _add_events(seeded_db, deal.id, "report_expired", 5)
        assert count_reports(seeded_db, deal.id, "report_incorrect") == 0

    def test_isolates_by_deal(self, seeded_db, source):
        deal_a = _make_deal(seeded_db, source.id, source_deal_id="qc-a")
        deal_b = _make_deal(seeded_db, source.id, source_deal_id="qc-b")
        _add_events(seeded_db, deal_a.id, "report_incorrect", 3)
        assert count_reports(seeded_db, deal_b.id, "report_incorrect") == 0


# ══════════════════════════════════════════════════════════════════════════════
# Unit: demote_deal
# ══════════════════════════════════════════════════════════════════════════════


class TestDemoteDeal:
    def test_reduces_quality_score(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id, quality_score=0.8)
        demote_deal(seeded_db, deal)
        assert deal.quality_score == pytest.approx(0.5, abs=0.01)

    def test_reduces_confidence(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id, confidence=0.7)
        demote_deal(seeded_db, deal)
        assert deal.confidence == pytest.approx(0.4, abs=0.01)

    def test_clamps_at_zero_quality(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id, quality_score=0.1)
        demote_deal(seeded_db, deal)
        assert deal.quality_score == 0.0

    def test_clamps_at_zero_confidence(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id, confidence=0.1)
        demote_deal(seeded_db, deal)
        assert deal.confidence == 0.0

    def test_none_quality_treated_as_0_5(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id, quality_score=None)
        changed = demote_deal(seeded_db, deal)
        assert changed is True
        assert deal.quality_score == pytest.approx(0.2, abs=0.01)

    def test_returns_true_when_changed(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id, quality_score=0.8)
        assert demote_deal(seeded_db, deal) is True

    def test_returns_false_when_already_zero(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id, quality_score=0.0, confidence=0.0)
        assert demote_deal(seeded_db, deal) is False


# ══════════════════════════════════════════════════════════════════════════════
# Unit: expire_deal
# ══════════════════════════════════════════════════════════════════════════════


class TestExpireDeal:
    def test_marks_deal_inactive(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id, is_active=True)
        expire_deal(seeded_db, deal)
        assert deal.is_active is False

    def test_sets_expires_at_if_none(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id, expires_at=None)
        expire_deal(seeded_db, deal)
        assert deal.expires_at is not None

    def test_overwrites_future_expires_at(self, seeded_db, source):
        future = _NOW + timedelta(days=30)
        deal = _make_deal(seeded_db, source.id, expires_at=future)
        expire_deal(seeded_db, deal)
        assert deal.expires_at <= datetime.now(timezone.utc) + timedelta(seconds=5)

    def test_returns_false_if_already_inactive(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id, is_active=False)
        assert expire_deal(seeded_db, deal) is False

    def test_returns_true_when_changed(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id, is_active=True)
        assert expire_deal(seeded_db, deal) is True


# ══════════════════════════════════════════════════════════════════════════════
# Unit: apply_quality_adjustments
# ══════════════════════════════════════════════════════════════════════════════


class TestApplyQualityAdjustments:
    def test_no_action_below_threshold(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id)
        _add_events(seeded_db, deal.id, "report_incorrect", INCORRECT_THRESHOLD - 1)
        result = apply_quality_adjustments(seeded_db, deal.id)
        assert result == {"demoted": False, "expired": False}
        assert deal.is_active is True

    def test_demotes_at_incorrect_threshold(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id, quality_score=0.8)
        _add_events(seeded_db, deal.id, "report_incorrect", INCORRECT_THRESHOLD)
        result = apply_quality_adjustments(seeded_db, deal.id)
        assert result["demoted"] is True
        assert deal.quality_score < 0.8

    def test_expires_at_expired_threshold(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id)
        _add_events(seeded_db, deal.id, "report_expired", EXPIRED_THRESHOLD)
        result = apply_quality_adjustments(seeded_db, deal.id)
        assert result["expired"] is True
        assert deal.is_active is False

    def test_handles_missing_deal_gracefully(self, seeded_db):
        result = apply_quality_adjustments(seeded_db, 999999)
        assert result == {"demoted": False, "expired": False}

    def test_both_adjustments_independently(self, seeded_db, source):
        deal = _make_deal(seeded_db, source.id, quality_score=0.8)
        _add_events(seeded_db, deal.id, "report_incorrect", INCORRECT_THRESHOLD)
        _add_events(seeded_db, deal.id, "report_expired", EXPIRED_THRESHOLD)
        result = apply_quality_adjustments(seeded_db, deal.id)
        assert result["demoted"] is True
        assert result["expired"] is True


# ══════════════════════════════════════════════════════════════════════════════
# Integration: POST /events
# ══════════════════════════════════════════════════════════════════════════════


class TestEventsEndpoint:
    def _seed_deal(self, db: Session) -> Deal:
        existing = db.query(Deal).filter(Deal.source_deal_id == "fb-test-1").first()
        if existing:
            # Reset state so each test starts with an active deal
            existing.is_active = True
            existing.quality_score = 0.8
            existing.confidence = 0.7
            db.commit()
            return existing
        source = db.query(Source).filter(Source.name == "dealnews").first()
        deal = Deal(
            title="Feedback Test Deal",
            url="http://example.com/fb",
            currency="USD",
            is_active=True,
            is_online=False,
            is_verified=False,
            source_id=source.id,
            source_deal_id="fb-test-1",
            fetched_at=_NOW,
            quality_score=0.8,
            confidence=0.7,
        )
        db.add(deal)
        db.commit()
        return deal

    def test_post_view_event(self, client, seeded_db):
        deal = self._seed_deal(seeded_db)
        r = client.post("/events", json={
            "event_type": "view",
            "deal_id": deal.id,
            "session_id": "test-session",
        })
        assert r.status_code == 201
        assert r.json()["event_type"] == "view"

    def test_post_click_event(self, client, seeded_db):
        deal = self._seed_deal(seeded_db)
        r = client.post("/events", json={"event_type": "click", "deal_id": deal.id})
        assert r.status_code == 201

    def test_post_save_event(self, client, seeded_db):
        deal = self._seed_deal(seeded_db)
        r = client.post("/events", json={"event_type": "save", "deal_id": deal.id})
        assert r.status_code == 201

    def test_post_rating_event_valid(self, client, seeded_db):
        deal = self._seed_deal(seeded_db)
        r = client.post("/events", json={
            "event_type": "rating",
            "deal_id": deal.id,
            "payload": {"value": 4},
        })
        assert r.status_code == 201

    def test_post_rating_missing_value_422(self, client, seeded_db):
        deal = self._seed_deal(seeded_db)
        r = client.post("/events", json={
            "event_type": "rating",
            "deal_id": deal.id,
            "payload": {},
        })
        assert r.status_code == 422

    def test_post_rating_invalid_value_422(self, client, seeded_db):
        deal = self._seed_deal(seeded_db)
        r = client.post("/events", json={
            "event_type": "rating",
            "deal_id": deal.id,
            "payload": {"value": 6},
        })
        assert r.status_code == 422

    def test_post_report_incorrect_stored(self, client, seeded_db):
        deal = self._seed_deal(seeded_db)
        r = client.post("/events", json={
            "event_type": "report_incorrect",
            "deal_id": deal.id,
        })
        assert r.status_code == 201

    def test_post_report_expired_stored(self, client, seeded_db):
        deal = self._seed_deal(seeded_db)
        r = client.post("/events", json={
            "event_type": "report_expired",
            "deal_id": deal.id,
        })
        assert r.status_code == 201

    def test_invalid_event_type_422(self, client, seeded_db):
        r = client.post("/events", json={"event_type": "explode"})
        assert r.status_code == 422

    def test_report_incorrect_triggers_demotion_at_threshold(self, client, seeded_db):
        deal = self._seed_deal(seeded_db)
        original_q = deal.quality_score
        # Send enough reports to always exceed threshold regardless of prior events
        for _ in range(INCORRECT_THRESHOLD + 2):
            client.post("/events", json={"event_type": "report_incorrect", "deal_id": deal.id})
        seeded_db.refresh(deal)
        assert deal.quality_score < original_q

    def test_report_expired_triggers_expiry_at_threshold(self, client, seeded_db):
        deal = self._seed_deal(seeded_db)
        # Send enough reports to always exceed threshold regardless of prior events
        for _ in range(EXPIRED_THRESHOLD + 2):
            client.post("/events", json={"event_type": "report_expired", "deal_id": deal.id})
        seeded_db.refresh(deal)
        assert deal.is_active is False


# ══════════════════════════════════════════════════════════════════════════════
# Integration: GET /admin/reports_summary
# ══════════════════════════════════════════════════════════════════════════════


class TestReportsSummaryEndpoint:
    def _seed_reports(self, db: Session) -> Deal:
        source = db.query(Source).filter(Source.name == "dealnews").first()
        city = db.query(City).filter(City.slug == "test-city-reports").first()
        if not city:
            city = City(name="Test City", state="CA", country="US", slug="test-city-reports",
                        is_active=True)
            db.add(city)
            db.flush()
        deal = db.query(Deal).filter(Deal.source_deal_id == "rep-deal-1").first()
        if not deal:
            deal = Deal(
                title="Reported Deal",
                url="http://example.com/rep",
                currency="USD",
                is_active=True,
                is_online=False,
                is_verified=False,
                source_id=source.id,
                source_deal_id="rep-deal-1",
                city_id=city.id,
                fetched_at=_NOW,
            )
            db.add(deal)
            db.flush()
            for i in range(2):
                db.add(EventLog(deal_id=deal.id, event_type="report_incorrect", session_id=f"s{i}"))
            db.add(EventLog(deal_id=deal.id, event_type="report_expired", session_id="s99"))
            db.commit()
        return deal

    def test_summary_returns_200(self, client, seeded_db):
        r = client.get("/admin/reports_summary")
        assert r.status_code == 200

    def test_summary_counts_reports(self, client, seeded_db):
        deal = self._seed_reports(seeded_db)
        r = client.get("/admin/reports_summary")
        data = r.json()
        assert data["total_reports"] >= 3

    def test_summary_by_type_breakdown(self, client, seeded_db):
        self._seed_reports(seeded_db)
        r = client.get("/admin/reports_summary")
        data = r.json()
        assert "report_incorrect" in data["by_type"]
        assert "report_expired" in data["by_type"]

    def test_summary_most_reported_has_title(self, client, seeded_db):
        self._seed_reports(seeded_db)
        r = client.get("/admin/reports_summary")
        data = r.json()
        if data["most_reported"]:
            assert "title" in data["most_reported"][0]
            assert "total_reports" in data["most_reported"][0]
