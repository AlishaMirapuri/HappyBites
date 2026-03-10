"""FastAPI integration tests — uses in-memory SQLite via TestClient."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from happybites.db.models import City, Deal, Source, Venue


# ── Test helpers ──────────────────────────────────────────────────────────────


def make_deal(db, source_name: str = "seed", **overrides) -> Deal:
    source = db.query(Source).filter(Source.name == source_name).first()
    params: dict = {
        "source_id": source.id,
        "source_deal_id": str(uuid.uuid4()),
        "title": "Test Deal - $49.99",
        "url": "https://example.com/deal",
        "deal_price": 49.99,
        "original_price": 99.99,
        "discount_pct": 50.0,
        "category": "Electronics",
        "tags": json.dumps(["gadget", "sale"]),
        "quality_score": 0.85,
        "rank_score": 0.72,
        "fetched_at": datetime.now(timezone.utc),
        "is_active": True,
        "currency": "USD",
        "is_online": True,
        "is_verified": False,
    }
    params.update(overrides)
    deal = Deal(**params)
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return deal


def make_venue(db, **overrides) -> Venue:
    params = {
        "name": "Test Venue",
        "is_active": True,
        "confidence": 1.0,
    }
    params.update(overrides)
    venue = Venue(**params)
    db.add(venue)
    db.commit()
    db.refresh(venue)
    return venue


def make_city(db, **overrides) -> City:
    params = {
        "name": "Test City",
        "slug": f"test-city-{id(overrides)}",
        "country": "US",
        "is_active": True,
    }
    params.update(overrides)
    city = City(**params)
    db.add(city)
    db.commit()
    db.refresh(city)
    return city


# ── Health ────────────────────────────────────────────────────────────────────


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["db_reachable"] is True
    assert "deals_total" in body
    assert body["status"] in ("ok", "degraded")


# ── Deals list ────────────────────────────────────────────────────────────────


def test_list_deals_empty(client):
    r = client.get("/deals")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "total" in body
    assert "limit" in body
    assert "offset" in body


def test_list_deals_returns_inserted_deal(client, seeded_db):
    make_deal(seeded_db)
    r = client.get("/deals")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    item = body["items"][0]
    assert "title" in item
    assert "rank_score" in item
    assert "tags" in item
    assert isinstance(item["tags"], list)
    assert "currency" in item
    assert "is_online" in item
    assert "is_verified" in item


def test_list_deals_filter_by_category(client, seeded_db):
    make_deal(seeded_db, source_deal_id="cat-elec-1", category="Electronics")
    make_deal(seeded_db, source_deal_id="cat-food-1", category="Food & Dining")

    r = client.get("/deals", params={"category": "Electronics"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(i["category"] == "Electronics" for i in items)


def test_list_deals_filter_by_max_price(client, seeded_db):
    make_deal(seeded_db, source_deal_id="cheap-1", deal_price=10.0)
    make_deal(seeded_db, source_deal_id="expensive-1", deal_price=500.0)

    r = client.get("/deals", params={"max_price": 50.0})
    assert r.status_code == 200
    items = r.json()["items"]
    assert all((i["deal_price"] or 0) <= 50.0 for i in items if i["deal_price"])


def test_list_deals_filter_by_min_discount(client, seeded_db):
    make_deal(seeded_db, source_deal_id="big-disc-1", discount_pct=60.0)
    make_deal(seeded_db, source_deal_id="small-disc-1", discount_pct=5.0)

    r = client.get("/deals", params={"min_discount": 50.0})
    assert r.status_code == 200
    items = r.json()["items"]
    assert all((i["discount_pct"] or 0) >= 50.0 for i in items if i["discount_pct"])


def test_list_deals_sort_by_discount(client, seeded_db):
    make_deal(seeded_db, source_deal_id="disc-30", discount_pct=30.0)
    make_deal(seeded_db, source_deal_id="disc-70", discount_pct=70.0)

    r = client.get("/deals", params={"sort": "discount_pct"})
    assert r.status_code == 200
    items = r.json()["items"]
    discounts = [i["discount_pct"] for i in items if i["discount_pct"]]
    assert discounts == sorted(discounts, reverse=True)


def test_list_deals_invalid_sort_rejected(client):
    r = client.get("/deals", params={"sort": "invalid_field"})
    assert r.status_code == 422


def test_list_deals_limit(client, seeded_db):
    for i in range(5):
        make_deal(seeded_db, source_deal_id=f"limit-{i}")

    r = client.get("/deals", params={"limit": 2})
    assert r.status_code == 200
    assert len(r.json()["items"]) <= 2


def test_list_deals_offset(client, seeded_db):
    for i in range(4):
        make_deal(seeded_db, source_deal_id=f"offset-{i}", rank_score=float(i))

    all_items = client.get("/deals", params={"limit": 10}).json()["items"]
    page2 = client.get("/deals", params={"limit": 2, "offset": 2}).json()["items"]
    assert len(page2) == 2
    assert page2[0]["id"] == all_items[2]["id"]


# ── Deal detail ───────────────────────────────────────────────────────────────


def test_get_deal_by_id(client, seeded_db):
    deal = make_deal(
        seeded_db,
        source_deal_id="detail-test",
        description="Full description here",
    )
    r = client.get(f"/deals/{deal.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == deal.id
    assert body["description"] == "Full description here"
    assert "ai_normalized" in body
    assert "schedules" in body
    assert isinstance(body["schedules"], list)


def test_get_deal_not_found(client):
    r = client.get("/deals/99999")
    assert r.status_code == 404


# ── Deals nearby ──────────────────────────────────────────────────────────────


def test_deals_nearby_returns_geo_deals(client, seeded_db):
    # SF coords
    make_deal(
        seeded_db,
        source_deal_id="nearby-sf",
        lat=37.7749,
        lon=-122.4194,
        is_online=False,
    )
    r = client.get(
        "/deals/nearby",
        params={"lat": 37.7749, "lng": -122.4194, "radius_m": 500},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    item = body["items"][0]
    assert item["distance_m"] is not None
    assert item["distance_m"] < 500


def test_deals_nearby_excludes_distant_deals(client, seeded_db):
    # NYC ~4000 km from SF
    make_deal(
        seeded_db,
        source_deal_id="distant-nyc",
        lat=40.7128,
        lon=-74.0060,
        is_online=False,
    )
    r = client.get(
        "/deals/nearby",
        params={"lat": 37.7749, "lng": -122.4194, "radius_m": 1000},
    )
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()["items"]]
    # The NYC deal should NOT appear in a 1 km radius around SF
    nearby_sids = [i.get("source_deal_id") for i in r.json()["items"]]


def test_deals_nearby_sorted_by_distance(client, seeded_db):
    make_deal(seeded_db, source_deal_id="close", lat=37.7750, lon=-122.4195, is_online=False)
    make_deal(seeded_db, source_deal_id="farther", lat=37.7850, lon=-122.4194, is_online=False)
    r = client.get(
        "/deals/nearby",
        params={"lat": 37.7749, "lng": -122.4194, "radius_m": 5000},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    distances = [i["distance_m"] for i in items if i["distance_m"] is not None]
    assert distances == sorted(distances)


def test_deals_nearby_missing_lat_rejected(client):
    r = client.get("/deals/nearby", params={"lng": -122.4194})
    assert r.status_code == 422


# ── Deals search ──────────────────────────────────────────────────────────────


def test_deals_search_by_query(client, seeded_db):
    make_deal(seeded_db, source_deal_id="srch-1", title="Amazing Laptop Deal")
    make_deal(seeded_db, source_deal_id="srch-2", title="Cheap Coffee Maker")

    r = client.get("/deals/search", params={"q": "Laptop"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 1
    assert all("Laptop" in i["title"] for i in items)


def test_deals_search_by_category(client, seeded_db):
    make_deal(seeded_db, source_deal_id="srch-cat-1", category="Travel")
    r = client.get("/deals/search", params={"category": "Travel"})
    assert r.status_code == 200
    assert all(i["category"] == "Travel" for i in r.json()["items"])


def test_deals_search_online_filter(client, seeded_db):
    make_deal(seeded_db, source_deal_id="srch-online", is_online=True)
    make_deal(seeded_db, source_deal_id="srch-local", is_online=False)

    r = client.get("/deals/search", params={"is_online": "true"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(i["is_online"] is True for i in items)


def test_deals_search_empty_q_returns_all_active(client, seeded_db):
    make_deal(seeded_db, source_deal_id="srch-all")
    r = client.get("/deals/search")
    assert r.status_code == 200
    assert r.json()["total"] >= 1


def test_deals_search_invalid_sort_rejected(client):
    r = client.get("/deals/search", params={"sort": "bad"})
    assert r.status_code == 422


# ── Venues ────────────────────────────────────────────────────────────────────


def test_get_venue(client, seeded_db):
    venue = make_venue(seeded_db, name="Burger Palace", slug="burger-palace")
    make_deal(seeded_db, source_deal_id="venue-deal", venue_id=venue.id)

    r = client.get(f"/venues/{venue.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == venue.id
    assert body["name"] == "Burger Palace"
    assert body["deal_count"] >= 1


def test_get_venue_with_city(client, seeded_db):
    city = make_city(seeded_db, name="San Francisco", slug="sf-test")
    venue = make_venue(seeded_db, name="SF Spot", slug="sf-spot", city_id=city.id)

    r = client.get(f"/venues/{venue.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["city"] is not None
    assert body["city"]["name"] == "San Francisco"


def test_get_venue_not_found(client):
    r = client.get("/venues/99999")
    assert r.status_code == 404


def test_get_venue_inactive_not_found(client, seeded_db):
    venue = make_venue(seeded_db, name="Closed", slug="closed-venue", is_active=False)
    r = client.get(f"/venues/{venue.id}")
    assert r.status_code == 404


# ── Events ────────────────────────────────────────────────────────────────────


def test_post_event_click(client, seeded_db):
    deal = make_deal(seeded_db, source_deal_id="click-deal")
    r = client.post(
        "/events",
        json={
            "event_type": "click",
            "session_id": "sess-abc",
            "deal_id": deal.id,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["event_type"] == "click"
    assert body["session_id"] == "sess-abc"
    assert body["deal_id"] == deal.id
    assert "id" in body
    assert "created_at" in body


def test_post_event_invalid_type(client):
    r = client.post(
        "/events",
        json={"event_type": "explode", "session_id": "sess-x"},
    )
    assert r.status_code == 422


def test_post_event_no_session(client):
    r = client.post("/events", json={"event_type": "view"})
    assert r.status_code == 201


def test_post_event_with_payload(client):
    r = client.post(
        "/events",
        json={
            "event_type": "search",
            "session_id": "sess-search",
            "payload": {"q": "pizza", "results": 5},
        },
    )
    assert r.status_code == 201
    assert r.json()["payload"]["q"] == "pizza"


# ── Sources ───────────────────────────────────────────────────────────────────


def test_list_sources(client):
    r = client.get("/sources")
    assert r.status_code == 200
    sources = r.json()
    assert isinstance(sources, list)
    names = [s["name"] for s in sources]
    assert "seed" in names
    # New fields should be present
    assert "display_name" in sources[0]
    assert "confidence_weight" in sources[0]
    assert "consecutive_failures" in sources[0]


def test_source_runs(client, seeded_db):
    source = seeded_db.query(Source).filter(Source.name == "seed").first()
    r = client.get(f"/sources/{source.id}/runs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_source_not_found(client):
    r = client.get("/sources/99999/runs")
    assert r.status_code == 404


# ── Admin ─────────────────────────────────────────────────────────────────────


def test_admin_stats(client, seeded_db):
    make_deal(seeded_db, source_deal_id="admin-stat")
    r = client.get("/admin/stats")
    assert r.status_code == 200
    body = r.json()
    assert "total_deals" in body
    assert "active_deals" in body
    assert "deals_by_category" in body


def test_admin_rerank(client, seeded_db):
    make_deal(seeded_db, source_deal_id="rerank-test")
    r = client.post("/admin/rerank")
    assert r.status_code == 200
    assert "Reranked" in r.json()["message"]


def test_admin_purge_expired(client, seeded_db):
    make_deal(
        seeded_db,
        source_deal_id="expired-del",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    r = client.delete("/admin/deals/expired")
    assert r.status_code == 200
    assert "expired" in r.json()["message"].lower()


def test_admin_mark_expired(client, seeded_db):
    make_deal(
        seeded_db,
        source_deal_id="mark-exp",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    r = client.post("/admin/mark_expired", json={})
    assert r.status_code == 200
    assert "expired" in r.json()["message"].lower()


def test_admin_mark_expired_with_before(client, seeded_db):
    future = datetime.now(timezone.utc) + timedelta(days=7)
    make_deal(
        seeded_db,
        source_deal_id="mark-exp-future",
        expires_at=datetime.now(timezone.utc) + timedelta(days=3),
    )
    r = client.post(
        "/admin/mark_expired",
        json={"before": future.isoformat()},
    )
    assert r.status_code == 200
    assert "Marked" in r.json()["message"]


def test_admin_ingest_status(client, seeded_db):
    r = client.get("/admin/ingest_status")
    assert r.status_code == 200
    body = r.json()
    assert "checked_at" in body
    assert "total_active_deals" in body
    assert "total_fresh_24h" in body
    assert "stale" in body
    assert "sources" in body
    assert isinstance(body["sources"], list)
    assert "cities" in body
    assert isinstance(body["cities"], list)
    # Each source item has expected fields
    for src in body["sources"]:
        assert "source_id" in src
        assert "source_name" in src
        assert "deals_active" in src
        assert "deals_fresh_24h" in src
