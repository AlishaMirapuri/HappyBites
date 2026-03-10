"""Tests for source collectors — all external HTTP calls mocked."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import respx
import httpx

from happybites.ingestion.connectors.dealnews import DealNewsCollector
from happybites.ingestion.connectors.reddit import RedditDealsCollector
from happybites.ingestion.connectors.seed import SeedCollector
from happybites.ingestion.base import RawDeal

# ── DealNews ──────────────────────────────────────────────────────────────────

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>DealNews</title>
    <item>
      <title>Sony WH-1000XM5 Headphones for $279.99</title>
      <link>https://dealnews.com/deal/sony-wh1000xm5</link>
      <id>https://dealnews.com/deal/sony-wh1000xm5</id>
      <description>Save 30% on Sony noise-cancelling headphones.</description>
      <pubDate>Thu, 06 Mar 2026 08:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Nike Running Shoes - $59.99</title>
      <link>https://dealnews.com/deal/nike-shoes</link>
      <id>https://dealnews.com/deal/nike-shoes</id>
      <description>Nike Air Zoom Pegasus on sale.</description>
      <pubDate>Thu, 06 Mar 2026 07:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""


@respx.mock
def test_dealnews_fetch_parses_rss():
    respx.get("https://dealnews.com/rss/deals.rss").mock(
        return_value=httpx.Response(200, text=SAMPLE_RSS)
    )
    collector = DealNewsCollector()
    deals = collector.fetch(limit=10)

    assert len(deals) == 2
    assert isinstance(deals[0], RawDeal)
    assert "Sony" in deals[0].title
    assert deals[0].url == "https://dealnews.com/deal/sony-wh1000xm5"


@respx.mock
def test_dealnews_fetch_returns_empty_on_http_error():
    respx.get("https://dealnews.com/rss/deals.rss").mock(
        return_value=httpx.Response(500)
    )
    collector = DealNewsCollector()
    deals = collector.fetch()
    assert deals == []


@respx.mock
def test_dealnews_respects_limit():
    respx.get("https://dealnews.com/rss/deals.rss").mock(
        return_value=httpx.Response(200, text=SAMPLE_RSS)
    )
    collector = DealNewsCollector()
    deals = collector.fetch(limit=1)
    assert len(deals) == 1


# ── Reddit ────────────────────────────────────────────────────────────────────

SAMPLE_REDDIT = {
    "data": {
        "children": [
            {
                "data": {
                    "id": "abc123",
                    "title": "[Deal] Samsung 65\" QLED TV for $799.99 (was $1299.99)",
                    "url": "https://www.amazon.com/dp/B09XYZ",
                    "selftext": "",
                    "is_self": False,
                    "stickied": False,
                    "score": 342,
                    "num_comments": 45,
                    "link_flair_text": "Electronics",
                    "created_utc": 1741248000.0,
                    "permalink": "/r/deals/comments/abc123/",
                }
            },
            {
                "data": {
                    "id": "def456",
                    "title": "Stickied mod post",
                    "url": "https://reddit.com/r/deals",
                    "selftext": "",
                    "is_self": True,
                    "stickied": True,
                    "score": 1,
                    "num_comments": 0,
                    "link_flair_text": None,
                    "created_utc": 1741248000.0,
                    "permalink": "/r/deals/comments/def456/",
                }
            },
        ]
    }
}


@respx.mock
def test_reddit_fetch_parses_posts():
    respx.get("https://www.reddit.com/r/deals/hot.json").mock(
        return_value=httpx.Response(200, json=SAMPLE_REDDIT)
    )
    collector = RedditDealsCollector()
    deals = collector.fetch(limit=10)

    # Stickied post should be filtered out
    assert len(deals) == 1
    assert "Samsung" in deals[0].title
    assert deals[0].source_deal_id == "abc123"


@respx.mock
def test_reddit_fetch_returns_empty_on_http_error():
    respx.get("https://www.reddit.com/r/deals/hot.json").mock(
        return_value=httpx.Response(429)
    )
    collector = RedditDealsCollector()
    deals = collector.fetch()
    assert deals == []


# ── Seed ──────────────────────────────────────────────────────────────────────

def test_seed_fetch_loads_json(tmp_path: Path):
    seed_data = [
        {
            "source_deal_id": "seed-001",
            "title": "Test Deal - $50",
            "url": "https://example.com/deal",
            "description": "A test deal",
            "merchant": "TestMerchant",
            "original_price": 100.0,
            "deal_price": 50.0,
            "expires_at": None,
        }
    ]
    seed_file = tmp_path / "seed.json"
    seed_file.write_text(json.dumps(seed_data))

    collector = SeedCollector(seed_path=seed_file)
    deals = collector.fetch()

    assert len(deals) == 1
    assert deals[0].source_deal_id == "seed-001"
    assert deals[0].deal_price == 50.0
    assert deals[0].merchant == "TestMerchant"


def test_seed_fetch_missing_file_returns_empty(tmp_path: Path):
    collector = SeedCollector(seed_path=tmp_path / "nonexistent.json")
    deals = collector.fetch()
    assert deals == []


def test_seed_fetch_respects_limit(tmp_path: Path):
    seed_data = [
        {"source_deal_id": f"seed-{i}", "title": f"Deal {i}", "url": f"https://ex.com/{i}"}
        for i in range(10)
    ]
    seed_file = tmp_path / "seed.json"
    seed_file.write_text(json.dumps(seed_data))

    collector = SeedCollector(seed_path=seed_file)
    deals = collector.fetch(limit=3)
    assert len(deals) == 3
