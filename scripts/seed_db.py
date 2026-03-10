"""
Seed the database with realistic sample data.

Inserts Cities, Venues, Sources, CrawlJobs, Deals, DealSchedules,
UserPreferences, and EventLogs so the UI is populated on first run.

Usage:
    python scripts/seed_db.py              # seed everything
    python scripts/seed_db.py --reset      # drop and recreate DB first
    python scripts/seed_db.py --deals-only # only insert deals (skip venues/cities)

Safe to run multiple times — all inserts are idempotent.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from happybites.db.engine import SessionLocal, init_db
from happybites.db import repositories as repo
from happybites.db.models import Source


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Seed data definitions
# ─────────────────────────────────────────────────────────────────────────────

CITIES = [
    dict(name="San Francisco", state="CA", country="US", slug="san-francisco-ca",
         lat=37.7749, lon=-122.4194, timezone_str="America/Los_Angeles"),
    dict(name="New York", state="NY", country="US", slug="new-york-ny",
         lat=40.7128, lon=-74.0060, timezone_str="America/New_York"),
    dict(name="Austin", state="TX", country="US", slug="austin-tx",
         lat=30.2672, lon=-97.7431, timezone_str="America/Chicago"),
]

# source_name → dict
SOURCES = [
    dict(name="dealnews", display_name="DealNews", type="rss",
         base_url="https://dealnews.com/rss/deals.rss",
         fetch_interval=7200, confidence_weight=0.9, is_active=True),
    dict(name="reddit", display_name="Reddit /r/deals", type="api",
         base_url="https://www.reddit.com/r/deals",
         fetch_interval=3600, confidence_weight=0.7, is_active=True),
    dict(name="seed", display_name="Seed data", type="seed",
         base_url=None, fetch_interval=86400, confidence_weight=1.0, is_active=True),
    dict(name="sf_local", display_name="SF Local Deals", type="scrape",
         base_url="https://example-sf-deals.com", fetch_interval=43200,
         confidence_weight=0.8, is_active=True),
]

# venue slug → dict
VENUES = [
    dict(slug="tacos-el-gordo-sf", name="Tacos El Gordo", city_slug="san-francisco-ca",
         address="3000 Mission St, San Francisco, CA 94110",
         lat=37.7484, lon=-122.4185, category="restaurant",
         phone="415-555-0101", website="https://tacoselgordo.com"),
    dict(slug="blue-bottle-sf", name="Blue Bottle Coffee", city_slug="san-francisco-ca",
         address="66 Mint St, San Francisco, CA 94103",
         lat=37.7825, lon=-122.4068, category="cafe",
         phone="415-555-0102", website="https://bluebottlecoffee.com"),
    dict(slug="mighty-burger-sf", name="Mighty Burger", city_slug="san-francisco-ca",
         address="1234 Valencia St, San Francisco, CA 94110",
         lat=37.7521, lon=-122.4210, category="restaurant",
         phone="415-555-0103"),
    dict(slug="joe-coffee-nyc", name="Joe Coffee", city_slug="new-york-ny",
         address="405 W 23rd St, New York, NY 10011",
         lat=40.7472, lon=-74.0006, category="cafe",
         phone="212-555-0201", website="https://joecoffee.com"),
    dict(slug="shake-shack-nyc", name="Shake Shack", city_slug="new-york-ny",
         address="Madison Square Park, New York, NY 10010",
         lat=40.7415, lon=-73.9881, category="restaurant",
         phone="212-555-0202", website="https://shakeshack.com"),
    dict(slug="epoch-coffee-austin", name="Epoch Coffee", city_slug="austin-tx",
         address="221 W N Loop Blvd, Austin, TX 78751",
         lat=30.3209, lon=-97.7293, category="cafe",
         phone="512-555-0301", website="https://epochcoffee.com"),
    dict(slug="torchys-tacos-austin", name="Torchy's Tacos", city_slug="austin-tx",
         address="2801 Guadalupe St, Austin, TX 78705",
         lat=30.2904, lon=-97.7430, category="restaurant",
         phone="512-555-0302", website="https://torchystacos.com"),
]

# ─────────────────────────────────────────────────────────────────────────────
# Deals seed — raw dicts matching Deal fields
# ─────────────────────────────────────────────────────────────────────────────

def _deal(source_deal_id, title, url, venue_slug=None, city_slug=None, **kw):
    return dict(
        source_deal_id=source_deal_id,
        title=title,
        url=url,
        _venue_slug=venue_slug,
        _city_slug=city_slug,
        **kw,
    )


DEALS = [
    # ── Electronics (online) ──────────────────────────────────────────────────
    _deal("seed-001",
          "Apple AirPods Pro 2nd Gen with USB-C — $189.99 (was $249.99)",
          "https://www.amazon.com/dp/B0BSHF7WHW",
          description="Active noise cancellation, transparency mode, 30hr battery.",
          merchant="Amazon", category="Electronics",
          tags=json.dumps(["headphones", "apple", "wireless"]),
          original_price=249.99, deal_price=189.99, discount_pct=24.0,
          quality_score=0.92, confidence=0.95, is_online=True),

    _deal("seed-002",
          "Samsung 65\" QLED 4K Smart TV — $799.99 (was $1,299.99)",
          "https://www.bestbuy.com/site/samsung-65-qled-tv",
          description="Quantum HDR, 120Hz, Neo Smart TV.",
          merchant="Best Buy", category="Electronics",
          tags=json.dumps(["tv", "samsung", "4k"]),
          original_price=1299.99, deal_price=799.99, discount_pct=38.5,
          quality_score=0.91, confidence=0.93, is_online=True,
          expires_at=_utcnow() + timedelta(days=3)),

    _deal("seed-003",
          "Dell XPS 15 Laptop (i7, 16GB, 512GB) — $1,199 (was $1,599)",
          "https://www.dell.com/en-us/shop/laptops/xps-15",
          description="Intel Core i7-13700H, RTX 4050, 15.6\" OLED.",
          merchant="Dell", category="Electronics",
          tags=json.dumps(["laptop", "dell", "windows"]),
          original_price=1599.0, deal_price=1199.0, discount_pct=25.0,
          quality_score=0.89, confidence=0.91, is_online=True,
          expires_at=_utcnow() + timedelta(days=5)),

    _deal("seed-004",
          "Kindle Paperwhite 16GB — $99.99 (was $159.99)",
          "https://www.amazon.com/dp/B08KTZ8249",
          description="6.8\" glare-free, adjustable warm light, 10-week battery.",
          merchant="Amazon", category="Electronics",
          tags=json.dumps(["ereader", "kindle", "books"]),
          original_price=159.99, deal_price=99.99, discount_pct=37.5,
          quality_score=0.88, confidence=0.90, is_online=True),

    # ── Food (venue-specific) ─────────────────────────────────────────────────
    _deal("seed-005",
          "Happy Hour Tacos — 3 for $9 (normally $4.50 each)",
          "https://tacoselgordo.com/happy-hour",
          venue_slug="tacos-el-gordo-sf", city_slug="san-francisco-ca",
          description="Any 3 street tacos for $9. Tues–Fri 3pm–6pm only.",
          merchant="Tacos El Gordo", category="Food & Dining",
          tags=json.dumps(["tacos", "happy-hour", "san-francisco"]),
          original_price=13.50, deal_price=9.0, discount_pct=33.3,
          quality_score=0.85, confidence=0.88, is_online=False,
          location="San Francisco, CA"),

    _deal("seed-006",
          "Blue Bottle Drip Coffee — $2 off with any pastry purchase",
          "https://bluebottlecoffee.com/sf-mint",
          venue_slug="blue-bottle-sf", city_slug="san-francisco-ca",
          description="Save $2 on any drip coffee when you buy a pastry. All day.",
          merchant="Blue Bottle Coffee", category="Food & Dining",
          tags=json.dumps(["coffee", "pastry", "san-francisco"]),
          original_price=5.50, deal_price=3.50, discount_pct=36.4,
          quality_score=0.80, confidence=0.82, is_online=False,
          location="San Francisco, CA"),

    _deal("seed-007",
          "Shake Shack NYC — BOGO ShackBurger on Wednesdays",
          "https://shakeshack.com/bogo",
          venue_slug="shake-shack-nyc", city_slug="new-york-ny",
          description="Buy one ShackBurger, get one free every Wednesday with app.",
          merchant="Shake Shack", category="Food & Dining",
          tags=json.dumps(["burger", "bogo", "new-york"]),
          original_price=11.99, deal_price=5.99, discount_pct=50.0,
          quality_score=0.83, confidence=0.85, is_online=False,
          location="New York, NY"),

    _deal("seed-008",
          "Torchy's Tacos Austin — Taco Tuesday $2 tacos all day",
          "https://torchystacos.com/taco-tuesday",
          venue_slug="torchys-tacos-austin", city_slug="austin-tx",
          description="All tacos $2 every Tuesday. No limit. Dine in only.",
          merchant="Torchy's Tacos", category="Food & Dining",
          tags=json.dumps(["tacos", "tuesday", "austin"]),
          original_price=4.50, deal_price=2.0, discount_pct=55.6,
          quality_score=0.87, confidence=0.89, is_online=False,
          location="Austin, TX"),

    # ── Fashion ───────────────────────────────────────────────────────────────
    _deal("seed-009",
          "Levi's 511 Slim Jeans — $29.99 (was $69.50)",
          "https://www.levi.com/US/en_US/clothing/men/jeans/511",
          description="Multiple washes and sizes. Stretch denim.",
          merchant="Levi's", category="Fashion",
          tags=json.dumps(["jeans", "mens", "levis"]),
          original_price=69.50, deal_price=29.99, discount_pct=56.8,
          quality_score=0.86, confidence=0.88, is_online=True,
          expires_at=_utcnow() + timedelta(days=14)),

    _deal("seed-010",
          "Nike Air Zoom Pegasus 40 Running Shoes — $74.97 (was $130)",
          "https://www.nike.com/t/air-zoom-pegasus-40",
          description="Responsive cushioning, wider toe box. Men's and women's.",
          merchant="Nike", category="Sports & Outdoors",
          tags=json.dumps(["running", "shoes", "nike"]),
          original_price=130.0, deal_price=74.97, discount_pct=42.3,
          quality_score=0.90, confidence=0.92, is_online=True),

    # ── Home ──────────────────────────────────────────────────────────────────
    _deal("seed-011",
          "Instant Pot Duo 7-in-1 6qt — $59.99 (was $99.99)",
          "https://www.amazon.com/dp/B00FLYWNYQ",
          description="Pressure cooker, slow cooker, rice cooker, steamer, sauté.",
          merchant="Amazon", category="Home & Garden",
          tags=json.dumps(["instant-pot", "kitchen", "appliance"]),
          original_price=99.99, deal_price=59.99, discount_pct=40.0,
          quality_score=0.91, confidence=0.93, is_online=True),

    _deal("seed-012",
          "Dyson V15 Detect Cordless Vacuum — $499.99 (was $749.99)",
          "https://www.dyson.com/vacuum-cleaners/cordless/v15",
          description="Laser dust detection, LCD particle count, 60min runtime.",
          merchant="Dyson", category="Home & Garden",
          tags=json.dumps(["vacuum", "dyson", "cordless"]),
          original_price=749.99, deal_price=499.99, discount_pct=33.3,
          quality_score=0.88, confidence=0.90, is_online=True),

    # ── Entertainment ─────────────────────────────────────────────────────────
    _deal("seed-013",
          "Spotify Premium — 3 months for $0.99",
          "https://www.spotify.com/us/premium",
          description="New and returning eligible users. $11.99/month after.",
          merchant="Spotify", category="Entertainment",
          tags=json.dumps(["music", "streaming", "spotify"]),
          original_price=35.97, deal_price=0.99, discount_pct=97.2,
          quality_score=0.94, confidence=0.96, is_online=True,
          expires_at=_utcnow() + timedelta(days=18)),

    _deal("seed-014",
          "AMC A-List — First Month Free (then $25/mo)",
          "https://www.amctheatres.com/amc-alist",
          description="See up to 3 movies/week including IMAX and Dolby. Cancel anytime.",
          merchant="AMC Theatres", category="Entertainment",
          tags=json.dumps(["movies", "subscription", "amc"]),
          original_price=25.0, deal_price=0.0, discount_pct=100.0,
          quality_score=0.87, confidence=0.89, is_online=True,
          expires_at=_utcnow() + timedelta(days=8)),

    # ── Health ────────────────────────────────────────────────────────────────
    _deal("seed-015",
          "Peloton Bike — $1,195 + Free Delivery (was $1,445)",
          "https://www.onepeloton.com/shop/bike",
          description="21.5\" HD touchscreen, 250+ live classes/week. 0% APR available.",
          merchant="Peloton", category="Sports & Outdoors",
          tags=json.dumps(["fitness", "cycling", "peloton"]),
          original_price=1445.0, deal_price=1195.0, discount_pct=17.3,
          quality_score=0.85, confidence=0.87, is_online=True),

    # ── Travel ────────────────────────────────────────────────────────────────
    _deal("seed-016",
          "Airbnb — 20% off stays in Austin during SXSW",
          "https://www.airbnb.com/s/Austin--TX",
          city_slug="austin-tx",
          description="Use code SXSW20 at checkout. Valid for stays March 7-16.",
          merchant="Airbnb", category="Travel",
          tags=json.dumps(["travel", "airbnb", "sxsw", "austin"]),
          original_price=None, deal_price=None, discount_pct=20.0,
          quality_score=0.79, confidence=0.81, is_online=True,
          location="Austin, TX",
          expires_at=_utcnow() + timedelta(days=9)),
]

# ─────────────────────────────────────────────────────────────────────────────
# Schedule definitions  (deal_source_id → list of schedule dicts)
# ─────────────────────────────────────────────────────────────────────────────

SCHEDULES = {
    "seed-005": [  # Tacos El Gordo happy hour
        dict(day_of_week=1, start_time="15:00", end_time="18:00",
             timezone="America/Los_Angeles", notes="Tues happy hour"),
        dict(day_of_week=2, start_time="15:00", end_time="18:00",
             timezone="America/Los_Angeles", notes="Wed happy hour"),
        dict(day_of_week=3, start_time="15:00", end_time="18:00",
             timezone="America/Los_Angeles", notes="Thu happy hour"),
        dict(day_of_week=4, start_time="15:00", end_time="18:00",
             timezone="America/Los_Angeles", notes="Fri happy hour"),
    ],
    "seed-007": [  # Shake Shack BOGO Wednesdays
        dict(day_of_week=2, start_time=None, end_time=None,
             timezone="America/New_York", notes="All day Wednesday"),
    ],
    "seed-008": [  # Torchy's Taco Tuesday
        dict(day_of_week=1, start_time=None, end_time=None,
             timezone="America/Chicago", notes="All day Tuesday, dine-in only"),
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# Seeder
# ─────────────────────────────────────────────────────────────────────────────


def seed(db, *, deals_only: bool = False) -> None:
    # 1. Cities
    city_by_slug: dict[str, object] = {}
    if not deals_only:
        print("[1/6] Seeding cities...")
        for c in CITIES:
            city, created = repo.get_or_create_city(db, **c)
            city_by_slug[city.slug] = city
            status = "created" if created else "exists"
            print(f"  {city.name} ({status})")
    else:
        for c in CITIES:
            city = repo.get_city_by_slug(db, c["slug"])
            if city:
                city_by_slug[city.slug] = city

    # 2. Sources
    source_by_name: dict[str, object] = {}
    if not deals_only:
        print("[2/6] Seeding sources...")
        for s in SOURCES:
            existing = repo.get_source_by_name(db, s["name"])
            if not existing:
                source = repo.create_source(db, **s)
                print(f"  Created source: {source.name}")
            else:
                source = existing
                print(f"  Source exists: {source.name}")
            source_by_name[source.name] = source
    else:
        for s in SOURCES:
            src = repo.get_source_by_name(db, s["name"])
            if src:
                source_by_name[src.name] = src

    seed_source = source_by_name.get("seed")
    if not seed_source:
        seed_source = repo.get_source_by_name(db, "seed")
        if not seed_source:
            seed_source = repo.create_source(db, name="seed", type="seed",
                                              display_name="Seed", fetch_interval=86400,
                                              confidence_weight=1.0)
        source_by_name["seed"] = seed_source

    # 3. Venues
    venue_by_slug: dict[str, object] = {}
    if not deals_only:
        print("[3/6] Seeding venues...")
        for v in VENUES:
            city_slug = v.pop("_city_slug", None) or v.pop("city_slug", None)
            city = city_by_slug.get(city_slug) if city_slug else None
            venue, created = repo.get_or_create_venue(
                db, city_id=city.id if city else None, **{k: v[k] for k in v}
            )
            venue_by_slug[venue.slug] = venue
            status = "created" if created else "exists"
            print(f"  {venue.name} ({status})")

    else:
        for v in VENUES:
            slug = v.get("slug")
            venue = db.query(__import__("happybites.db.models", fromlist=["Venue"]).Venue)\
                      .filter_by(slug=slug).first()
            if venue:
                venue_by_slug[slug] = venue

    # 4. CrawlJobs (one per non-seed source)
    if not deals_only:
        print("[4/6] Seeding crawl jobs...")
        from happybites.db.models import CrawlJob
        for sname, src in source_by_name.items():
            if sname == "seed":
                continue
            exists = db.query(CrawlJob).filter(CrawlJob.source_id == src.id).first()
            if not exists:
                job = CrawlJob(
                    source_id=src.id,
                    name=f"{sname}-default",
                    target_url=src.base_url,
                    schedule_cron="0 */2 * * *",
                    is_active=True,
                )
                db.add(job)
                db.commit()
                print(f"  Created CrawlJob for {sname}")
            else:
                print(f"  CrawlJob exists for {sname}")

    # 5. Deals
    print("[5/6] Seeding deals...")
    now = _utcnow()
    inserted = 0
    skipped = 0

    for deal_data in DEALS:
        venue_slug = deal_data.pop("_venue_slug", None)
        city_slug = deal_data.pop("_city_slug", None)

        venue = venue_by_slug.get(venue_slug) if venue_slug else None
        city = city_by_slug.get(city_slug) if city_slug else None

        source_deal_id = deal_data.pop("source_deal_id")

        deal, created = repo.upsert_deal(
            db,
            source_id=seed_source.id,
            source_deal_id=source_deal_id,
            venue_id=venue.id if venue else None,
            city_id=city.id if city else None,
            fetched_at=now,
            normalized_at=now,
            is_active=True,
            **deal_data,
        )

        if created:
            inserted += 1

            # Normalization log
            repo.create_normalization_log(
                db,
                deal_id=deal.id,
                model=None,
                fallback_used=True,
            )

            # Schedules
            sched_data = SCHEDULES.get(source_deal_id, [])
            for s in sched_data:
                repo.create_deal_schedule(db, deal_id=deal.id, **s)
        else:
            skipped += 1

    print(f"  Deals: {inserted} created, {skipped} already exist")

    # 6. User preferences + events
    if not deals_only:
        print("[6/6] Seeding preferences and events...")
        pref1, _ = repo.get_or_create_preference(db, "demo-session-abc123")
        repo.update_preference(db, "demo-session-abc123",
                               preferred_categories=["Electronics", "Food & Dining"],
                               max_price=300.0, min_discount_pct=20.0)

        pref2, _ = repo.get_or_create_preference(db, "demo-session-def456")
        if city_by_slug.get("san-francisco-ca"):
            repo.update_preference(db, "demo-session-def456",
                                   city_id=city_by_slug["san-francisco-ca"].id,
                                   preferred_categories=["Food & Dining"],
                                   radius_miles=10.0)

        # Sample events
        from happybites.db.models import Deal
        first_deal = db.query(Deal).filter(Deal.is_active == True).first()
        if first_deal:
            repo.log_event(db, event_type="view", session_id="demo-session-abc123",
                           deal_id=first_deal.id)
            repo.log_event(db, event_type="click", session_id="demo-session-abc123",
                           deal_id=first_deal.id, payload={"referrer": "deals_list"})

        print("  Created demo preferences and events.")

    # Rank all deals
    print("Computing rank scores...")
    from happybites.ingestion.ranker import rerank_all
    count = rerank_all(db)
    print(f"  Ranked {count} deals.")


def main() -> None:
    parser = argparse.ArgumentParser(description="HappyBites DB seeder")
    parser.add_argument("--reset", action="store_true",
                        help="Drop and recreate DB before seeding")
    parser.add_argument("--deals-only", action="store_true",
                        help="Skip cities/venues/sources; only seed deals")
    args = parser.parse_args()

    if args.reset:
        from happybites.db.engine import engine, Base
        print("Dropping all tables...")
        Base.metadata.drop_all(engine)
        print("Recreating tables...")

    init_db()
    db = SessionLocal()
    try:
        seed(db, deals_only=args.deals_only)
    finally:
        db.close()

    print("\nSeed complete.")
    from happybites.db.models import Deal
    db2 = SessionLocal()
    try:
        total = db2.query(Deal).filter(Deal.is_active == True).count()
        print(f"  Active deals in DB: {total}")
        print("  Run 'make dev' to start the API.")
    finally:
        db2.close()


if __name__ == "__main__":
    main()
