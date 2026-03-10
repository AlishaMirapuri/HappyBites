"""Base types for the ingestion pipeline."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawDeal:
    """Unvalidated deal record as fetched from a source."""

    source_deal_id: str
    title: str
    url: str
    description: str | None = None
    image_url: str | None = None
    merchant: str | None = None
    original_price: float | None = None
    deal_price: float | None = None
    expires_at: datetime | None = None
    # Arbitrary source-specific metadata; not persisted directly but stored in DealRaw
    raw_data: dict = field(default_factory=dict)


@dataclass
class RawVenue:
    """Venue record as returned by a venue-aware connector.

    `category` is a connector-native string (e.g. "pizza", "bar", "italian").
    The pipeline normalises this to a canonical Venue.category value.
    `raw_data` holds the full source payload for DealRaw provenance.
    """

    external_id: str   # connector's unique key for this venue
    name: str
    city: str          # city name (e.g. "New York")
    address: str | None = None
    state: str | None = None
    country: str = "US"
    lat: float | None = None
    lon: float | None = None
    category: str | None = None    # source-native (free-form)
    price_range: str | None = None # "$" | "$$" | "$$$" | "$$$$"
    rating: float | None = None    # 0.0–5.0
    review_count: int | None = None
    phone: str | None = None
    website: str | None = None
    image_url: str | None = None
    raw_data: dict = field(default_factory=dict)


class BaseCollector(ABC):
    """All source collectors implement this interface."""

    source_name: str  # must match sources.name in DB

    @abstractmethod
    def fetch(self, limit: int = 100) -> list[RawDeal]:
        """Fetch raw deals from the source. Returns at most `limit` records."""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} source={self.source_name}>"


class VenueConnector(ABC):
    """Connector that returns both venue metadata and deals for a city.

    Unlike BaseCollector, fetch() is city-scoped and returns a pair:
      (list[RawVenue], list[RawDeal])

    Each RawDeal.raw_data should include "venue_external_id" so the pipeline
    can link the deal to the canonical Venue record.
    """

    source_name: str   # must match sources.name in DB
    source_type: str = "api"

    @abstractmethod
    def fetch(self, city: str) -> tuple[list[RawVenue], list[RawDeal]]:
        """Return venues and deals for the given city slug (e.g. 'nyc', 'sf')."""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} source={self.source_name}>"
