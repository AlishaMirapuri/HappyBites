"""
MockYelpConnector — simulates the Yelp Fusion API (v3) using local fixtures.

Fixture schema mirrors the real Yelp /businesses/search and /businesses/{id}
response shapes so the connector can be swapped for a live client later.

Fixture location: data/fixtures/mock_yelp.json
"""

import json
from pathlib import Path

import structlog

from happybites.ingestion.base import RawDeal, RawVenue, VenueConnector

logger = structlog.get_logger(__name__)

FIXTURE_PATH = Path(__file__).parents[3] / "data" / "fixtures" / "mock_yelp.json"

# Map Yelp category aliases → canonical Venue.category values
_CATEGORY_MAP: dict[str, str] = {
    "pizza": "restaurant",
    "burgers": "restaurant",
    "sandwiches": "restaurant",
    "delis": "restaurant",
    "newamerican": "restaurant",
    "californiacuisine": "restaurant",
    "chinese": "restaurant",
    "japanese": "restaurant",
    "sushi": "restaurant",
    "bbq": "restaurant",
    "italian": "restaurant",
    "breakfast_brunch": "restaurant",
    "coffee": "cafe",
    "bakeries": "bakery",
    "cocktailbars": "bar",
    "bars": "bar",
    "wine_bars": "bar",
    "breweries": "bar",
}

# Yelp day abbreviation → Python weekday index (0=Mon)
_DAYS: dict[str, int] = {
    "Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3,
    "Fri": 4, "Sat": 5, "Sun": 6,
}


def _canonical_category(yelp_categories: list[dict]) -> str | None:
    for cat in yelp_categories:
        alias = cat.get("alias", "")
        if alias in _CATEGORY_MAP:
            return _CATEGORY_MAP[alias]
    return "restaurant"  # default for food/dining fixture data


def _price_range(price_str: str | None) -> str | None:
    return price_str  # Yelp already uses "$" / "$$" / etc.


class MockYelpConnector(VenueConnector):
    """
    Reads from data/fixtures/mock_yelp.json and produces RawVenue + RawDeal
    records that mirror what a real Yelp Fusion connector would return.

    Supported city slugs: nyc, sf, austin
    """

    source_name = "mock_yelp"
    source_type = "api"

    def __init__(self, fixture_path: Path | str | None = None):
        self._fixture_path = Path(fixture_path) if fixture_path else FIXTURE_PATH
        self._data: dict | None = None

    def _load(self) -> dict:
        if self._data is None:
            with open(self._fixture_path) as f:
                self._data = json.load(f)
        return self._data

    def available_cities(self) -> list[str]:
        return list(self._load().keys())

    def fetch(self, city: str) -> tuple[list[RawVenue], list[RawDeal]]:
        data = self._load()
        city_key = city.lower().replace(" ", "-")
        city_data = data.get(city_key)

        if city_data is None:
            logger.warning("mock_yelp_city_not_found", city=city, available=list(data.keys()))
            return [], []

        raw_venues: list[RawVenue] = []
        raw_deals: list[RawDeal] = []

        for biz in city_data.get("businesses", []):
            if biz.get("is_closed"):
                continue

            coords = biz.get("coordinates", {})
            loc = biz.get("location", {})
            categories = biz.get("categories", [])

            venue = RawVenue(
                external_id=biz["id"],
                name=biz["name"],
                city=loc.get("city", city),
                address=loc.get("address1"),
                state=loc.get("state"),
                country=loc.get("country", "US"),
                lat=coords.get("latitude"),
                lon=coords.get("longitude"),
                category=_canonical_category(categories),
                price_range=_price_range(biz.get("price")),
                rating=biz.get("rating"),
                review_count=biz.get("review_count"),
                phone=biz.get("phone"),
                website=biz.get("url"),
                image_url=biz.get("image_url"),
                raw_data=biz,
            )
            raw_venues.append(venue)

            for deal_blob in biz.get("deals", []):
                raw_deal = self._parse_deal(deal_blob, biz)
                raw_deals.append(raw_deal)

        logger.info(
            "mock_yelp_fetched",
            city=city,
            venues=len(raw_venues),
            deals=len(raw_deals),
        )
        return raw_venues, raw_deals

    def _parse_deal(self, deal_blob: dict, biz: dict) -> RawDeal:
        valid_days = deal_blob.get("valid_days", [])
        schedule_meta = {
            "venue_external_id": biz["id"],
            "venue_name": biz["name"],
            "valid_days": valid_days,
            "valid_day_indices": [_DAYS[d] for d in valid_days if d in _DAYS],
            "start_time": deal_blob.get("start_time"),
            "end_time": deal_blob.get("end_time"),
            "discount_pct": deal_blob.get("discount_pct"),
            "source": "mock_yelp",
            "raw_deal": deal_blob,
        }

        return RawDeal(
            source_deal_id=deal_blob["deal_id"],
            title=deal_blob["title"],
            url=deal_blob.get("url", biz.get("url", "")),
            description=deal_blob.get("description"),
            merchant=biz["name"],
            original_price=deal_blob.get("original_price"),
            deal_price=deal_blob.get("deal_price"),
            raw_data=schedule_meta,
        )
