"""Tests for the ingestion orchestrator and FixtureCollector."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from happybites.ingestion.connectors.fixture import FixtureCollector
from happybites.ingestion.orchestrator import OrchestratorResult, run_orchestrator


# ══════════════════════════════════════════════════════════════════════════════
# Unit: FixtureCollector
# ══════════════════════════════════════════════════════════════════════════════

# Resolve the fixture HTML directory relative to this project
_FIXTURE_DIR = Path(__file__).parents[1] / "data" / "fixtures" / "html"


class TestFixtureCollector:
    def test_fixture_dir_exists(self):
        assert _FIXTURE_DIR.exists(), f"Fixture dir missing: {_FIXTURE_DIR}"

    def test_fetch_returns_deals(self):
        collector = FixtureCollector(fixture_dir=_FIXTURE_DIR)
        deals = collector.fetch()
        assert len(deals) > 0

    def test_all_deals_have_source_deal_id(self):
        collector = FixtureCollector(fixture_dir=_FIXTURE_DIR)
        deals = collector.fetch()
        for deal in deals:
            assert deal.source_deal_id, "source_deal_id must not be empty"
            assert deal.source_deal_id.startswith("fix-"), (
                f"Expected 'fix-' prefix, got: {deal.source_deal_id}"
            )

    def test_all_deals_have_title(self):
        collector = FixtureCollector(fixture_dir=_FIXTURE_DIR)
        deals = collector.fetch()
        for deal in deals:
            assert deal.title, "All deals must have a non-empty title"
            assert 5 <= len(deal.title) <= 250

    def test_all_deals_have_url(self):
        collector = FixtureCollector(fixture_dir=_FIXTURE_DIR)
        deals = collector.fetch()
        for deal in deals:
            assert deal.url.startswith("file://"), (
                f"Expected file:// URL, got: {deal.url}"
            )

    def test_source_deal_ids_are_unique(self):
        collector = FixtureCollector(fixture_dir=_FIXTURE_DIR)
        deals = collector.fetch()
        ids = [d.source_deal_id for d in deals]
        assert len(ids) == len(set(ids)), "source_deal_id values must be unique"

    def test_ids_are_stable(self):
        """fetch() called twice produces the same IDs in the same order."""
        collector = FixtureCollector(fixture_dir=_FIXTURE_DIR)
        ids_first = [d.source_deal_id for d in collector.fetch()]
        ids_second = [d.source_deal_id for d in collector.fetch()]
        assert ids_first == ids_second

    def test_price_extracted_from_sf_deals(self):
        """At least one deal from sf_deals.html should have a deal_price."""
        collector = FixtureCollector(fixture_dir=_FIXTURE_DIR)
        deals = collector.fetch()
        sf_deals = [d for d in deals if "sf_deals" in d.source_deal_id]
        assert sf_deals, "Expected deals from sf_deals.html"
        priced = [d for d in sf_deals if d.deal_price is not None]
        assert priced, "Expected at least one priced deal from sf_deals.html"

    def test_limit_respected(self):
        collector = FixtureCollector(fixture_dir=_FIXTURE_DIR)
        deals = collector.fetch(limit=3)
        assert len(deals) <= 3

    def test_missing_fixture_dir_returns_empty(self, tmp_path):
        empty_dir = tmp_path / "nonexistent"
        collector = FixtureCollector(fixture_dir=empty_dir)
        assert collector.fetch() == []

    def test_source_name_is_fixture(self):
        collector = FixtureCollector()
        assert collector.source_name == "fixture"

    def test_navigation_text_not_parsed_as_deal(self):
        """'Newsletter' and 'Subscribe' headings should be filtered out."""
        collector = FixtureCollector(fixture_dir=_FIXTURE_DIR)
        deals = collector.fetch()
        titles_lower = [d.title.lower() for d in deals]
        for bad in ("newsletter", "subscribe", "contact", "privacy"):
            assert not any(bad in t for t in titles_lower), (
                f"Title containing '{bad}' should have been filtered"
            )

    def test_description_populated(self):
        """At least some deals should have a non-None description."""
        collector = FixtureCollector(fixture_dir=_FIXTURE_DIR)
        deals = collector.fetch()
        with_desc = [d for d in deals if d.description]
        assert with_desc, "Expected at least one deal with a description"

    def test_raw_data_contains_fixture_file(self):
        collector = FixtureCollector(fixture_dir=_FIXTURE_DIR)
        deals = collector.fetch()
        for deal in deals:
            assert "fixture_file" in deal.raw_data
            assert deal.raw_data["fixture_file"].endswith(".html")


# ══════════════════════════════════════════════════════════════════════════════
# Unit: OrchestratorResult.to_dict
# ══════════════════════════════════════════════════════════════════════════════


class TestOrchestratorResultToDict:
    def _make_result(self, **kwargs) -> OrchestratorResult:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        defaults = dict(
            started_at=now,
            finished_at=now,
            duration_seconds=0.5,
            sources_run=["fixture"],
            total_fetched=5,
            total_inserted=5,
            total_updated=0,
            total_errors=0,
            errors=[],
            run_ids=[1],
        )
        defaults.update(kwargs)
        return OrchestratorResult(**defaults)

    def test_to_dict_has_all_keys(self):
        result = self._make_result()
        d = result.to_dict()
        for key in (
            "started_at", "finished_at", "duration_seconds", "sources_run",
            "total_fetched", "total_inserted", "total_updated",
            "total_errors", "errors", "run_ids",
        ):
            assert key in d

    def test_to_dict_datetimes_are_strings(self):
        result = self._make_result()
        d = result.to_dict()
        assert isinstance(d["started_at"], str)
        assert isinstance(d["finished_at"], str)

    def test_to_dict_sources_run_is_list(self):
        result = self._make_result(sources_run=["fixture", "seed"])
        d = result.to_dict()
        assert isinstance(d["sources_run"], list)
        assert "fixture" in d["sources_run"]


# ══════════════════════════════════════════════════════════════════════════════
# Integration: run_orchestrator (mocked scheduler)
# ══════════════════════════════════════════════════════════════════════════════

_MOCK_STATS = {
    "fixture": {"fetched": 7, "inserted": 7, "updated": 0, "run_id": 1},
    "seed": {"fetched": 3, "inserted": 2, "updated": 1, "run_id": 2},
}


def _mock_run_source(source_name: str) -> dict:
    return _MOCK_STATS.get(source_name, {"fetched": 0, "inserted": 0, "updated": 0, "run_id": 99})


class TestRunOrchestrator:
    def _patched_orchestrator(self, **kwargs):
        """
        Run run_orchestrator with:
        - run_ingestion_for_source mocked (returns canned stats)
        - SessionLocal patched to return a mock that returns no active sources
        """
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        with (
            patch(
                "happybites.ingestion.orchestrator.SessionLocal",
                return_value=mock_db,
            ),
            patch(
                "happybites.ingestion.scheduler.run_ingestion_for_source",
                side_effect=_mock_run_source,
            ),
        ):
            return run_orchestrator(**kwargs)

    def test_fixture_mode_adds_fixture_source(self):
        result = self._patched_orchestrator(sources=None, fixture_mode=True)
        assert "fixture" in result.sources_run

    def test_explicit_sources_used_when_given(self):
        result = self._patched_orchestrator(sources=["seed"], fixture_mode=False)
        assert result.sources_run == ["seed"]

    def test_fixture_mode_false_does_not_force_fixture(self):
        result = self._patched_orchestrator(sources=["seed"], fixture_mode=False)
        assert "fixture" not in result.sources_run

    def test_fixture_not_duplicated_if_already_in_list(self):
        result = self._patched_orchestrator(sources=["fixture"], fixture_mode=True)
        assert result.sources_run.count("fixture") == 1

    def test_aggregates_fetched(self):
        result = self._patched_orchestrator(sources=["fixture", "seed"], fixture_mode=False)
        assert result.total_fetched == 7 + 3

    def test_aggregates_inserted(self):
        result = self._patched_orchestrator(sources=["fixture", "seed"], fixture_mode=False)
        assert result.total_inserted == 7 + 2

    def test_aggregates_updated(self):
        result = self._patched_orchestrator(sources=["fixture", "seed"], fixture_mode=False)
        assert result.total_updated == 0 + 1

    def test_no_errors_when_all_succeed(self):
        result = self._patched_orchestrator(sources=["fixture"], fixture_mode=False)
        assert result.total_errors == 0
        assert result.errors == []

    def test_errors_captured(self):
        def error_source(name):
            if name == "fixture":
                return {"error": "connection refused"}
            return _mock_run_source(name)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        with (
            patch("happybites.ingestion.orchestrator.SessionLocal", return_value=mock_db),
            patch("happybites.ingestion.scheduler.run_ingestion_for_source", side_effect=error_source),
        ):
            result = run_orchestrator(sources=["fixture"], fixture_mode=False)

        assert result.total_errors == 1
        assert any("connection refused" in e for e in result.errors)

    def test_run_ids_collected(self):
        result = self._patched_orchestrator(sources=["fixture", "seed"], fixture_mode=False)
        assert 1 in result.run_ids
        assert 2 in result.run_ids

    def test_duration_positive(self):
        result = self._patched_orchestrator(sources=["fixture"], fixture_mode=False)
        assert result.duration_seconds >= 0

    def test_timestamps_set(self):
        result = self._patched_orchestrator(sources=["fixture"], fixture_mode=False)
        assert result.started_at is not None
        assert result.finished_at is not None
        assert result.finished_at >= result.started_at


# ══════════════════════════════════════════════════════════════════════════════
# Integration: POST /admin/run_ingest endpoint
# ══════════════════════════════════════════════════════════════════════════════


class TestRunIngestEndpoint:
    def _mock_orchestrator_result(self):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        return OrchestratorResult(
            started_at=now,
            finished_at=now,
            duration_seconds=0.42,
            sources_run=["fixture"],
            total_fetched=7,
            total_inserted=7,
            total_updated=0,
            total_errors=0,
            errors=[],
            run_ids=[1],
        )

    # The endpoint imports run_orchestrator inside the function body,
    # so we patch the canonical module path.
    _ORCH_PATH = "happybites.ingestion.orchestrator.run_orchestrator"

    def test_run_ingest_returns_200(self, client):
        with patch(self._ORCH_PATH, return_value=self._mock_orchestrator_result()):
            r = client.post("/admin/run_ingest", json={"fixture_mode": True})
        assert r.status_code == 200

    def test_run_ingest_response_has_required_fields(self, client):
        with patch(self._ORCH_PATH, return_value=self._mock_orchestrator_result()):
            r = client.post("/admin/run_ingest", json={"fixture_mode": True})
        data = r.json()
        for field in (
            "started_at", "finished_at", "duration_seconds", "sources_run",
            "total_fetched", "total_inserted", "total_updated",
            "total_errors", "errors", "run_ids",
        ):
            assert field in data, f"Missing field: {field}"

    def test_run_ingest_fixture_mode_false(self, client):
        with patch(self._ORCH_PATH, return_value=self._mock_orchestrator_result()) as mock_orch:
            r = client.post("/admin/run_ingest", json={"fixture_mode": False})
        assert r.status_code == 200
        mock_orch.assert_called_once()
        _, call_kwargs = mock_orch.call_args
        assert call_kwargs.get("fixture_mode") is False

    def test_run_ingest_with_explicit_sources(self, client):
        with patch(self._ORCH_PATH, return_value=self._mock_orchestrator_result()) as mock_orch:
            r = client.post(
                "/admin/run_ingest",
                json={"sources": ["fixture"], "fixture_mode": False},
            )
        assert r.status_code == 200
        _, call_kwargs = mock_orch.call_args
        assert call_kwargs.get("sources") == ["fixture"]

    def test_run_ingest_default_body(self, client):
        with patch(self._ORCH_PATH, return_value=self._mock_orchestrator_result()):
            # Empty body → fixture_mode defaults to True, sources defaults to None
            r = client.post("/admin/run_ingest", json={})
        assert r.status_code == 200
