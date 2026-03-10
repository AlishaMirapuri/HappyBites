"""
MockDiningConnector — simulates an OpenTable-like dining reservation API
using local fixtures.

Fixture schema mirrors a simplified OpenTable REST response for restaurant
search and promotions, enabling easy swap-out for a live client.

Fixture location: data/fixtures/mock_dining.json
"""

import json
from pathlib import Path

import structlog

from happybites.ingestion.base import RawDeal, RawVenue, VenueConnector

logger = structlog.get_logger(__name__)

FIXTURE_PATH = Path(__file__).parents[3] / "data" / "fixtures" / "mock_dining.json"

# OpenTable-style price_range int → "$" string
_PRICE_RANGE_MAP = {1: "$", 2: "$$", 3: "$$$", 4: "$$$$"}

# Cuisine → canonical Venue.category
_CUISINE_MAP: dict[str, str] = {
    "Italian": "restaurant",
    "French Seafood": "restaurant",
    "Deli": "restaurant",
    "Contemporary American": "restaurant",
    "American": "restaurant",
    "Californian": "restaurant",
    "Mediterranean": "restaurant",
    "French": "restaurant",
    "Japanese": "restaurant",
    "Seafood": "restaurant",
    "Steakhouse": "restaurant",
}

_DAYS: dict[str, int] = {
    "Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3,
    "Fri": 4, "Sat": 5, "Sun": 6,
}


class MockDiningConnector(VenueConnector):
    """
    Reads from data/fixtures/mock_dining.json and produces RawVenue + RawDeal
    records that mirror what a real OpenTable connector would return.

    Supported city slugs: nyc, sf, austin
    """

    source_name = "mock_dining"
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
            logger.warning(
                "mock_dining_city_not_found", city=city, available=list(data.keys())
            )
            return [], []

        raw_venues: list[RawVenue] = []
        raw_deals: list[RawDeal] = []

        for restaurant in city_data.get("restaurants", []):
            coords = restaurant.get("coordinates", {})
            addr = restaurant.get("address", {})
            cuisine = restaurant.get("cuisine", "")

            venue = RawVenue(
                external_id=restaurant["restaurant_id"],
                name=restaurant["name"],
                city=addr.get("city", city),
                address=addr.get("street"),
                state=addr.get("state"),
                country=addr.get("country", "US"),
                lat=coords.get("lat"),
                lon=coords.get("lng"),
                category=_CUISINE_MAP.get(cuisine, "restaurant"),
                price_range=_PRICE_RANGE_MAP.get(restaurant.get("price_range", 0)),
                rating=restaurant.get("rating"),
                review_count=restaurant.get("review_count"),
                phone=restaurant.get("phone"),
                website=restaurant.get("website"),
                image_url=restaurant.get("image_url"),
                raw_data=restaurant,
            )
            raw_venues.append(venue)

            for promo in restaurant.get("promotions", []):
                raw_deal = self._parse_promotion(promo, restaurant)
                raw_deals.append(raw_deal)

        logger.info(
            "mock_dining_fetched",
            city=city,
            venues=len(raw_venues),
            deals=len(raw_deals),
        )
        return raw_venues, raw_deals

    def _parse_promotion(self, promo: dict, restaurant: dict) -> RawDeal:
        valid_days = promo.get("valid_days", [])
        booking_url = restaurant.get("booking_url") or restaurant.get("website", "")

        schedule_meta = {
            "venue_external_id": restaurant["restaurant_id"],
            "venue_name": restaurant["name"],
            "valid_days": valid_days,
            "valid_day_indices": [_DAYS[d] for d in valid_days if d in _DAYS],
            "start_time": promo.get("start_time"),
            "end_time": promo.get("end_time"),
            "discount_pct": promo.get("discount_pct"),
            "booking_url": booking_url,
            "source": "mock_dining",
            "raw_promo": promo,
        }

        return RawDeal(
            source_deal_id=promo["promo_id"],
            title=promo["title"],
            url=promo.get("url") or booking_url or "",
            description=promo.get("description"),
            merchant=restaurant["name"],
            original_price=promo.get("original_price"),
            deal_price=promo.get("deal_price"),
            raw_data=schedule_meta,
        )
