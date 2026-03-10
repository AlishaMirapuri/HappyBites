"""DealNews RSS feed collector."""

import re
from datetime import datetime, timezone

import feedparser
import httpx
import structlog

from happybites.ingestion.base import BaseCollector, RawDeal

logger = structlog.get_logger(__name__)

DEALNEWS_FEED_URL = "https://dealnews.com/rss/deals.rss"


def _parse_price(text: str | None) -> float | None:
    """Extract the first USD price from a text string."""
    if not text:
        return None
    match = re.search(r"\$([0-9]+(?:\.[0-9]{1,2})?)", text)
    return float(match.group(1)) if match else None


def _parse_published(entry) -> datetime | None:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    return None


class DealNewsCollector(BaseCollector):
    source_name = "dealnews"

    def __init__(self, feed_url: str = DEALNEWS_FEED_URL):
        self.feed_url = feed_url

    def fetch(self, limit: int = 100) -> list[RawDeal]:
        log = logger.bind(source=self.source_name)
        log.info("fetching", url=self.feed_url)

        try:
            response = httpx.get(self.feed_url, timeout=15, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.error("fetch_failed", error=str(exc))
            return []

        feed = feedparser.parse(response.text)
        entries = feed.entries[:limit]
        log.info("fetched", count=len(entries))

        deals: list[RawDeal] = []
        for entry in entries:
            deal_id = entry.get("id") or entry.get("link", "")
            title = entry.get("title", "").strip()
            url = entry.get("link", "").strip()
            summary = entry.get("summary", "").strip()

            if not deal_id or not title or not url:
                continue

            deal_price = _parse_price(title) or _parse_price(summary)
            expires_at = _parse_published(entry)  # DealNews doesn't expose expiry in RSS

            deals.append(
                RawDeal(
                    source_deal_id=deal_id,
                    title=title,
                    url=url,
                    description=summary or None,
                    deal_price=deal_price,
                    expires_at=expires_at,
                    raw_data={
                        "tags": [t.get("term", "") for t in entry.get("tags", [])],
                        "published": entry.get("published", ""),
                    },
                )
            )

        log.info("parsed", deals=len(deals))
        return deals
