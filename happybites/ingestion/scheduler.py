"""
APScheduler-based ingestion scheduler.

Runs inside the FastAPI process (no separate worker needed for MVP).
Each source gets its own job keyed by source name.
"""

import json
from datetime import datetime, timezone

import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from happybites.config import settings
from happybites.db.engine import SessionLocal
from happybites.db.models import Deal, IngestionRun, NormalizationLog, Source
from happybites.ingestion.base import RawDeal
from happybites.ingestion.normalizer import Normalizer
from happybites.ingestion.ranker import rank_deal
from happybites.ingestion.resolver import resolve_deals

logger = structlog.get_logger(__name__)

_scheduler: BackgroundScheduler | None = None
_normalizer: Normalizer | None = None


def get_normalizer() -> Normalizer:
    global _normalizer
    if _normalizer is None:
        _normalizer = Normalizer()
    return _normalizer


def _get_collector(source_name: str):
    """Lazy import to avoid circular deps; returns a configured collector or None."""
    from happybites.ingestion.connectors.dealnews import DealNewsCollector
    from happybites.ingestion.connectors.fixture import FixtureCollector
    from happybites.ingestion.connectors.reddit import RedditDealsCollector
    from happybites.ingestion.connectors.seed import SeedCollector

    collectors = {
        "dealnews": DealNewsCollector,
        "fixture": FixtureCollector,
        "reddit": RedditDealsCollector,
        "seed": SeedCollector,
    }
    cls = collectors.get(source_name)
    return cls() if cls else None


def run_ingestion_for_source(source_name: str) -> dict:
    """
    Fetch → normalize → persist deals for a single source.
    Returns a stats dict.
    """
    db: Session = SessionLocal()
    log = logger.bind(source=source_name)

    try:
        source = db.query(Source).filter(Source.name == source_name).first()
        if not source:
            log.error("source_not_found")
            return {"error": "source not found"}
        if not source.is_active:
            log.info("source_inactive_skipped")
            return {"skipped": True}

        run = IngestionRun(
            source_id=source.id,
            started_at=datetime.now(timezone.utc),
            status="running",
        )
        db.add(run)
        db.commit()

        collector = _get_collector(source_name)
        if not collector:
            run.status = "error"
            run.error_msg = f"No collector registered for source '{source_name}'"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            return {"error": run.error_msg}

        raw_deals: list[RawDeal] = collector.fetch(limit=settings.max_deals_per_run)
        run.deals_fetched = len(raw_deals)

        normalizer = get_normalizer()
        inserted, updated = 0, 0
        new_deal_objects: list[Deal] = []

        for raw in raw_deals:
            # Normalize
            fields, fallback_used = normalizer.normalize(raw)

            now = datetime.now(timezone.utc)
            expires_at = None
            if fields.get("expires_at"):
                try:
                    expires_at = datetime.fromisoformat(fields["expires_at"]).replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    pass

            # Build deal record
            deal_data = {
                "source_id": source.id,
                "source_deal_id": raw.source_deal_id,
                "title": raw.title,
                "description": raw.description,
                "url": raw.url,
                "image_url": raw.image_url,
                "merchant": fields.get("merchant") or raw.merchant,
                "category": fields.get("category"),
                "tags": json.dumps(fields.get("tags", [])),
                "original_price": fields.get("original_price"),
                "deal_price": fields.get("deal_price"),
                "discount_pct": fields.get("discount_pct"),
                "expires_at": expires_at,
                "fetched_at": now,
                "normalized_at": now,
                "quality_score": fields.get("quality_score"),
                "is_active": True,
            }

            # Upsert: insert or skip on unique constraint
            existing = (
                db.query(Deal)
                .filter(Deal.source_id == source.id, Deal.source_deal_id == raw.source_deal_id)
                .first()
            )

            if existing:
                # Update mutable fields on re-fetch
                for k, v in deal_data.items():
                    if k not in ("source_id", "source_deal_id", "fetched_at"):
                        setattr(existing, k, v)
                deal = existing
                updated += 1
            else:
                deal = Deal(**deal_data)
                db.add(deal)
                db.flush()  # populate deal.id
                inserted += 1
                new_deal_objects.append(deal)

            # Rank score
            deal.rank_score = rank_deal(deal)

            # Provenance log
            norm_log = NormalizationLog(
                deal_id=deal.id,
                model=fields.get("_model"),
                prompt_tokens=fields.get("_prompt_tokens"),
                completion_tokens=fields.get("_completion_tokens"),
                raw_response=fields.get("_raw_response"),
                normalized_at=now,
                fallback_used=fallback_used,
            )
            db.add(norm_log)

        db.commit()

        # Cross-source dedup
        if new_deal_objects:
            resolve_deals(db, new_deal_objects)

        # Update source last_fetched_at
        source.last_fetched_at = datetime.now(timezone.utc)
        run.deals_inserted = inserted
        run.deals_updated = updated
        run.status = "success"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()

        stats = {
            "source": source_name,
            "fetched": len(raw_deals),
            "inserted": inserted,
            "updated": updated,
            "run_id": run.id,
        }
        log.info("ingestion_complete", **stats)
        return stats

    except Exception as exc:
        log.exception("ingestion_error", error=str(exc))
        try:
            run.status = "error"
            run.error_msg = str(exc)
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            pass
        return {"error": str(exc)}
    finally:
        db.close()


def run_all_sources() -> list[dict]:
    db = SessionLocal()
    try:
        sources = db.query(Source).filter(Source.is_active == True).all()  # noqa: E712
        names = [s.name for s in sources]
    finally:
        db.close()

    return [run_ingestion_for_source(name) for name in names]


def run_source(source_name: str) -> dict:
    return run_ingestion_for_source(source_name)


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        run_all_sources,
        trigger="interval",
        seconds=settings.ingest_interval_seconds,
        id="ingest_all",
        replace_existing=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info(
        "scheduler_started",
        interval_seconds=settings.ingest_interval_seconds,
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")
