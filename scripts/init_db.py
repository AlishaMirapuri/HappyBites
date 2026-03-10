"""
Initialize the database.

Uses Alembic to apply migrations, which is the correct approach for both
development and production. Falls back to create_all for environments where
Alembic is not configured.

Usage:
    python scripts/init_db.py              # apply migrations (recommended)
    python scripts/init_db.py --direct     # use create_all (skip Alembic)
    python scripts/init_db.py --check      # check current migration status
"""

import argparse
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parents[1]))


def migrate_with_alembic(check_only: bool = False) -> None:
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    if check_only:
        print("Current migration status:")
        command.current(alembic_cfg, verbose=True)
        print("\nMigration history:")
        command.history(alembic_cfg)
        return

    print("Applying Alembic migrations...")
    command.upgrade(alembic_cfg, "head")
    print("  Done — DB is at head revision.")


def init_with_create_all() -> None:
    from happybites.db.engine import init_db

    print("Initializing DB with create_all (no Alembic)...")
    init_db()
    print("  Done — all tables created.")


def ensure_default_sources() -> None:
    """Insert the three default sources if they don't already exist."""
    from happybites.db.engine import SessionLocal
    from happybites.db.models import Source

    db = SessionLocal()
    try:
        defaults = [
            dict(name="dealnews", type="rss", base_url="https://dealnews.com/rss/deals.rss",
                 display_name="DealNews", fetch_interval=7200, confidence_weight=0.9),
            dict(name="reddit", type="api", base_url="https://www.reddit.com/r/deals",
                 display_name="Reddit /r/deals", fetch_interval=3600, confidence_weight=0.7),
            dict(name="seed", type="seed", base_url=None,
                 display_name="Seed data", fetch_interval=86400, confidence_weight=1.0),
        ]
        created = 0
        for d in defaults:
            if not db.query(Source).filter(Source.name == d["name"]).first():
                db.add(Source(**d))
                created += 1
        db.commit()
        print(f"  Sources: {created} created, {len(defaults) - created} already exist.")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="HappyBites DB initializer")
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Use SQLAlchemy create_all instead of Alembic",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Show current migration status and exit",
    )
    args = parser.parse_args()

    if args.check:
        migrate_with_alembic(check_only=True)
        return

    if args.direct:
        init_with_create_all()
    else:
        migrate_with_alembic()

    ensure_default_sources()
    print("\nDB initialization complete.")
    print("Run `python scripts/seed_db.py` to load sample data.")


if __name__ == "__main__":
    main()
