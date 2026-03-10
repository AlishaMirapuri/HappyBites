"""Static JSON seed collector — for development and testing."""

import json
from datetime import datetime, timezone
from pathlib import Path

import structlog

from happybites.ingestion.base import BaseCollector, RawDeal

logger = structlog.get_logger(__name__)

DEFAULT_SEED_PATH = Path(__file__).parents[3] / "data" / "seed_deals.json"


class SeedCollector(BaseCollector):
    source_name = "seed"

    def __init__(self, seed_path: Path | str | None = None):
        self.seed_path = Path(seed_path) if seed_path else DEFAULT_SEED_PATH

    def fetch(self, limit: int = 100) -> list[RawDeal]:
        log = logger.bind(source=self.source_name, path=str(self.seed_path))

        if not self.seed_path.exists():
            log.warning("seed_file_not_found")
            return []

        with open(self.seed_path) as f:
            raw = json.load(f)

        records = raw[:limit]
        log.info("loaded", count=len(records))

        deals: list[RawDeal] = []
        for item in records:
            expires_at = None
            if item.get("expires_at"):
                try:
                    expires_at = datetime.fromisoformat(item["expires_at"]).replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    pass

            deals.append(
                RawDeal(
                    source_deal_id=item["source_deal_id"],
                    title=item["title"],
                    url=item["url"],
                    description=item.get("description"),
                    image_url=item.get("image_url"),
                    merchant=item.get("merchant"),
                    original_price=item.get("original_price"),
                    deal_price=item.get("deal_price"),
                    expires_at=expires_at,
                    raw_data=item.get("raw_data", {}),
                )
            )

        return deals
