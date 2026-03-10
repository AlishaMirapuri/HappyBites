#!/usr/bin/env python
"""
Demo ingestion script.

Initialises the database (create_all), then runs the full ingestion
orchestrator in fixture mode so you can see the pipeline working without
any external API keys.

Usage
─────
    python scripts/run_ingest_demo.py           # fixture mode (default)
    python scripts/run_ingest_demo.py --all     # all active sources + fixture
    python scripts/run_ingest_demo.py --source seed   # single source
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path when running directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description="HappyBites ingestion demo")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--all",
        action="store_true",
        help="Run all active sources in addition to fixture",
    )
    group.add_argument(
        "--source",
        metavar="NAME",
        help="Run a single named source (e.g. seed, dealnews, fixture)",
    )
    parser.add_argument(
        "--no-fixture",
        action="store_true",
        help="Disable the local HTML fixture source",
    )
    args = parser.parse_args()

    # ── Bootstrap DB ──────────────────────────────────────────────────────────
    print("Initialising database …")
    from happybites.db.engine import init_db

    init_db()
    print("Database ready.\n")

    # ── Build sources list ────────────────────────────────────────────────────
    sources: list[str] | None = None
    if args.source:
        sources = [args.source]
    elif not args.all:
        # Default: fixture only
        sources = ["fixture"]

    fixture_mode = not args.no_fixture

    # ── Run orchestrator ──────────────────────────────────────────────────────
    from happybites.ingestion.orchestrator import run_orchestrator

    print(f"Running ingestion  (sources={sources or 'all-active'}, fixture_mode={fixture_mode}) …\n")
    result = run_orchestrator(sources=sources, fixture_mode=fixture_mode)

    # ── Print summary ─────────────────────────────────────────────────────────
    print("─" * 60)
    print(f"Duration  : {result.duration_seconds:.2f}s")
    print(f"Sources   : {', '.join(result.sources_run)}")
    print(f"Fetched   : {result.total_fetched}")
    print(f"Inserted  : {result.total_inserted}")
    print(f"Updated   : {result.total_updated}")
    print(f"Errors    : {result.total_errors}")
    if result.errors:
        for err in result.errors:
            print(f"  ! {err}")
    print("─" * 60)

    if result.total_errors == 0:
        print("\nDone — no errors.")
        print("\nNext steps:")
        print("  make dev       → start the API  at http://localhost:8000")
        print("  make frontend  → start the UI   at http://localhost:8501")
        print("  API docs       → http://localhost:8000/docs")
    else:
        print(f"\nDone with {result.total_errors} error(s). Check logs above.")

    return 0 if result.total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
