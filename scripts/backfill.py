"""
Backfill script: initialize the database and load seed deals.

Usage:
    python scripts/backfill.py [--normalize] [--no-rank]

Options:
    --normalize     Run Claude normalization on seed deals (requires ANTHROPIC_API_KEY)
    --no-rank       Skip rank score computation
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on the path when run directly
sys.path.insert(0, str(Path(__file__).parents[1]))

from happybites.db.engine import SessionLocal, init_db
from happybites.db.models import Deal, NormalizationLog, Source
from happybites.ingestion.connectors.seed import SeedCollector
from happybites.ingestion.normalizer import Normalizer
from happybites.ingestion.ranker import rank_deal


def ensure_source(db, name: str, source_type: str) -> Source:
    source = db.query(Source).filter(Source.name == name).first()
    if not source:
        source = Source(name=name, type=source_type, fetch_interval=86400, is_active=True)
        db.add(source)
        db.commit()
        print(f"  Created source: {name}")
    return source


def backfill(run_normalize: bool = False, run_rank: bool = True):
    print("HappyBites backfill starting...")

    # 1. Initialize DB
    print("[1/4] Initializing database...")
    init_db()

    db = SessionLocal()

    try:
        # 2. Ensure all default sources exist
        print("[2/4] Ensuring sources...")
        ensure_source(db, "dealnews", "rss")
        ensure_source(db, "reddit", "api")
        seed_source = ensure_source(db, "seed", "seed")

        # 3. Load seed deals
        print("[3/4] Loading seed deals...")
        collector = SeedCollector()
        raw_deals = collector.fetch(limit=200)
        print(f"  Found {len(raw_deals)} seed records")

        normalizer = Normalizer() if run_normalize else None
        inserted = 0
        skipped = 0

        for raw in raw_deals:
            existing = (
                db.query(Deal)
                .filter(
                    Deal.source_id == seed_source.id,
                    Deal.source_deal_id == raw.source_deal_id,
                )
                .first()
            )
            if existing:
                skipped += 1
                continue

            now = datetime.now(timezone.utc)

            if normalizer:
                fields, fallback_used = normalizer.normalize(raw)
            else:
                # Use values directly from JSON (already normalized in seed)
                fields = {
                    "category": raw.raw_data.get("category"),
                    "tags": raw.raw_data.get("tags", []),
                    "merchant": raw.merchant,
                    "original_price": raw.original_price,
                    "deal_price": raw.deal_price,
                    "expires_at": raw.expires_at.isoformat() if raw.expires_at else None,
                    "quality_score": 0.75,
                    "discount_pct": None,
                }
                fallback_used = True

            # Derive discount
            orig = fields.get("original_price") or raw.original_price
            deal_p = fields.get("deal_price") or raw.deal_price
            discount_pct = None
            if orig and deal_p and orig > 0 and deal_p < orig:
                discount_pct = round((orig - deal_p) / orig * 100, 2)

            expires_at = None
            if fields.get("expires_at"):
                try:
                    expires_at = datetime.fromisoformat(fields["expires_at"]).replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    pass

            deal = Deal(
                source_id=seed_source.id,
                source_deal_id=raw.source_deal_id,
                title=raw.title,
                description=raw.description,
                url=raw.url,
                image_url=raw.image_url,
                merchant=fields.get("merchant") or raw.merchant,
                category=fields.get("category"),
                tags=json.dumps(fields.get("tags", [])),
                original_price=orig,
                deal_price=deal_p,
                discount_pct=discount_pct,
                expires_at=expires_at,
                fetched_at=now,
                normalized_at=now,
                quality_score=fields.get("quality_score", 0.75),
                is_active=True,
            )
            db.add(deal)
            db.flush()

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
            inserted += 1

        db.commit()
        print(f"  Inserted: {inserted}, Skipped (already exist): {skipped}")

        # 4. Rank all deals
        if run_rank:
            print("[4/4] Computing rank scores...")
            from happybites.ingestion.ranker import rerank_all
            count = rerank_all(db)
            print(f"  Ranked {count} deals")
        else:
            print("[4/4] Skipping rank computation (--no-rank)")

        print("\nBackfill complete.")
        print(f"  Total active deals: {db.query(Deal).filter(Deal.is_active == True).count()}")
        print("  Run 'make dev' to start the API, then 'make frontend' for the UI.")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HappyBites DB backfill")
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="Run Claude normalization (requires ANTHROPIC_API_KEY)",
    )
    parser.add_argument("--no-rank", action="store_true", help="Skip rank score computation")
    args = parser.parse_args()

    backfill(run_normalize=args.normalize, run_rank=not args.no_rank)
