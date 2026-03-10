"""
CLI runner for venue-aware ingestion connectors.

Usage:
    python -m happybites.ingestion.run --city NYC
    python -m happybites.ingestion.run --city SF --connector mock_yelp
    python -m happybites.ingestion.run --city NYC --all-connectors
    python -m happybites.ingestion.run --city NYC --dry-run
    python -m happybites.ingestion.run --list-cities

Supported connectors: mock_yelp, mock_dining
Supported city slugs:  nyc, sf, austin  (also accepts: "New York", "San Francisco", etc.)
"""

import argparse
import json
import sys

import structlog

from happybites.ingestion.venue_pipeline import (
    VenueIngestionPipeline,
    normalise_city_slug,
)

logger = structlog.get_logger(__name__)

_CONNECTORS: dict[str, type] = {}


def _get_connectors() -> dict[str, type]:
    global _CONNECTORS
    if not _CONNECTORS:
        from happybites.ingestion.connectors.mock_yelp import MockYelpConnector
        from happybites.ingestion.connectors.mock_dining import MockDiningConnector

        _CONNECTORS = {
            "mock_yelp": MockYelpConnector,
            "mock_dining": MockDiningConnector,
        }
    return _CONNECTORS


def run_city(city: str, connector_name: str, dry_run: bool = False) -> dict:
    """Run one connector for one city. Returns the stats summary dict."""
    slug = normalise_city_slug(city)
    connectors = _get_connectors()

    if connector_name not in connectors:
        print(f"Unknown connector '{connector_name}'. Available: {list(connectors)}", file=sys.stderr)
        sys.exit(1)

    connector_cls = connectors[connector_name]
    connector = connector_cls()

    if dry_run:
        print(f"[dry-run] Would run {connector_name} for city={slug}")
        raw_venues, raw_deals = connector.fetch(slug)
        summary = {
            "connector": connector_name,
            "city": slug,
            "dry_run": True,
            "venues": len(raw_venues),
            "deals": len(raw_deals),
            "venue_names": [v.name for v in raw_venues],
            "deal_titles": [d.title for d in raw_deals],
        }
        print(json.dumps(summary, indent=2))
        return summary

    from happybites.db.engine import SessionLocal
    from happybites.ingestion.normalizer import Normalizer

    db = SessionLocal()
    try:
        pipeline = VenueIngestionPipeline(db, connector, Normalizer())
        stats = pipeline.run(slug)
        return stats.summary()
    finally:
        db.close()


def run_all(city: str, dry_run: bool = False) -> list[dict]:
    """Run all registered connectors for the given city."""
    return [
        run_city(city, name, dry_run=dry_run)
        for name in _get_connectors()
    ]


def list_cities() -> None:
    """Print all cities available across all connectors."""
    connectors = _get_connectors()
    cities: set[str] = set()
    for name, cls in connectors.items():
        try:
            c = cls()
            if hasattr(c, "available_cities"):
                for city in c.available_cities():
                    cities.add(city)
        except Exception:
            pass
    print("Available cities:")
    for city in sorted(cities):
        print(f"  {city}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m happybites.ingestion.run",
        description="Ingest venue and deal data from mock connectors.",
    )
    p.add_argument(
        "--city",
        metavar="CITY",
        help="City slug or name to ingest (e.g. nyc, SF, 'San Francisco')",
    )
    p.add_argument(
        "--connector",
        metavar="NAME",
        default=None,
        help="Connector to run (mock_yelp | mock_dining). Default: all",
    )
    p.add_argument(
        "--all-connectors",
        action="store_true",
        help="Run all registered connectors for the given city",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print fixture data without writing to the database",
    )
    p.add_argument(
        "--list-cities",
        action="store_true",
        help="Print all cities available in the fixture files and exit",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.list_cities:
        list_cities()
        return

    if not args.city:
        parser.error("--city is required (or use --list-cities)")

    if args.all_connectors or args.connector is None:
        results = run_all(args.city, dry_run=args.dry_run)
    else:
        results = [run_city(args.city, args.connector, dry_run=args.dry_run)]

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        for r in results:
            print(f"\n{'─' * 50}")
            print(f"  source  : {r.get('source', r.get('connector'))}")
            print(f"  city    : {r.get('city')}")
            if r.get("dry_run"):
                print(f"  venues  : {r.get('venues')} (dry-run)")
                print(f"  deals   : {r.get('deals')} (dry-run)")
            else:
                print(f"  venues  : +{r.get('venues_inserted',0)} inserted / {r.get('venues_updated',0)} updated")
                print(f"  deals   : +{r.get('deals_inserted',0)} inserted / {r.get('deals_updated',0)} updated / {r.get('deals_skipped',0)} skipped")
                print(f"  raw recs: {r.get('raw_records_written',0)} written")
                if r.get("errors"):
                    print(f"  errors  : {r['errors']}")
        print()


if __name__ == "__main__":
    main()
