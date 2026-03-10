"""
Ingestion orchestrator.

Coordinates all ingestion sources end-to-end:
  1. Resolve which sources to run (explicit list or all active)
  2. Optionally inject fixture (HTML-based) source for demo / testing
  3. Ensure each source has a DB record; create on first use
  4. Run ingestion: fetch → normalize → upsert → rank → resolve cross-source dedup
  5. Aggregate per-source IngestionRun metrics into a single OrchestratorResult
  6. Return a dataclass summary the API can serialise

Designed to run inline (no background thread) so FastAPI endpoints can
call it and return the result immediately.  For production you'd offload
this to a task queue; for an MVP the inline call is fine.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import structlog

from happybites.db.engine import SessionLocal
from happybites.db.models import Source

logger = structlog.get_logger(__name__)

# ── Result type ────────────────────────────────────────────────────────────────


@dataclass
class OrchestratorResult:
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    sources_run: list[str]
    total_fetched: int
    total_inserted: int
    total_updated: int
    total_errors: int
    errors: list[str]
    run_ids: list[int]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["started_at"] = self.started_at.isoformat()
        d["finished_at"] = self.finished_at.isoformat()
        return d


# ── Source bootstrap ───────────────────────────────────────────────────────────


def _ensure_source(db, name: str, display_name: str, source_type: str) -> Source:
    """Get or create a Source record for the given name."""
    src = db.query(Source).filter(Source.name == name).first()
    if not src:
        src = Source(
            name=name,
            display_name=display_name,
            type=source_type,
            fetch_interval=86400,
            confidence_weight=0.8,
            is_active=True,
        )
        db.add(src)
        db.commit()
        db.refresh(src)
        logger.info("source_created", name=name)
    return src


# ── Core orchestrator ──────────────────────────────────────────────────────────


def run_orchestrator(
    sources: list[str] | None = None,
    *,
    fixture_mode: bool = True,
) -> OrchestratorResult:
    """
    Run the full ingestion pipeline.

    Parameters
    ──────────
    sources       Explicit list of source names to run.  None → all active
                  sources in DB plus "fixture" if fixture_mode=True.
    fixture_mode  When True, always include the local-HTML fixture collector.
                  Default True so the demo works without any API keys.

    Returns
    ───────
    OrchestratorResult  Consolidated metrics across all sources.
    """
    from happybites.ingestion.scheduler import run_ingestion_for_source

    started_at = datetime.now(timezone.utc)

    # Determine which sources to run
    db = SessionLocal()
    try:
        if sources is not None:
            run_names = list(sources)
        else:
            active = db.query(Source).filter(Source.is_active == True).all()  # noqa: E712
            run_names = [s.name for s in active]

        if fixture_mode and "fixture" not in run_names:
            run_names.append("fixture")

        # Guarantee a DB record exists for the fixture source
        if "fixture" in run_names:
            _ensure_source(db, "fixture", "Local HTML Fixtures", "scrape")
    finally:
        db.close()

    logger.info("orchestrator_start", sources=run_names, fixture_mode=fixture_mode)

    # Run each source sequentially; collect stats
    all_stats: list[dict] = []
    for name in run_names:
        stats = run_ingestion_for_source(name)
        all_stats.append({"source": name, **stats})

    finished_at = datetime.now(timezone.utc)
    duration = (finished_at - started_at).total_seconds()

    # Aggregate
    total_fetched = sum(s.get("fetched", 0) for s in all_stats)
    total_inserted = sum(s.get("inserted", 0) for s in all_stats)
    total_updated = sum(s.get("updated", 0) for s in all_stats)
    errors = [
        f"{s['source']}: {s['error']}"
        for s in all_stats
        if "error" in s
    ]
    run_ids = [s["run_id"] for s in all_stats if "run_id" in s]

    result = OrchestratorResult(
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=round(duration, 2),
        sources_run=run_names,
        total_fetched=total_fetched,
        total_inserted=total_inserted,
        total_updated=total_updated,
        total_errors=len(errors),
        errors=errors,
        run_ids=run_ids,
    )

    logger.info(
        "orchestrator_complete",
        duration_s=result.duration_seconds,
        fetched=total_fetched,
        inserted=total_inserted,
        updated=total_updated,
        errors=len(errors),
    )
    return result
