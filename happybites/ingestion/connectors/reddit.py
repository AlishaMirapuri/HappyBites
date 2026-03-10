"""Reddit /r/deals collector via the JSON API (no OAuth required for public data)."""

import re
from datetime import datetime, timezone

import httpx
import structlog

from happybites.config import settings
from happybites.ingestion.base import BaseCollector, RawDeal

logger = structlog.get_logger(__name__)

REDDIT_JSON_URL = "https://www.reddit.com/r/deals/hot.json"
PRICE_RE = re.compile(r"\$([0-9]+(?:\.[0-9]{1,2})?)")


def _parse_price(text: str | None) -> float | None:
    if not text:
        return None
    match = PRICE_RE.search(text)
    return float(match.group(1)) if match else None


def _parse_prices(title: str) -> tuple[float | None, float | None]:
    """Try to extract original + deal price from patterns like '$99 (was $149)'."""
    was_match = re.search(r"was\s+\$([0-9]+(?:\.[0-9]{1,2})?)", title, re.IGNORECASE)
    prices = PRICE_RE.findall(title)

    original = float(was_match.group(1)) if was_match else None
    deal = float(prices[0]) if prices else None

    # If both found in order and no "was" marker, infer from position
    if not original and len(prices) >= 2:
        original = float(prices[1])

    return original, deal


class RedditDealsCollector(BaseCollector):
    source_name = "reddit"

    def __init__(self, subreddit: str = "deals", limit: int = 100):
        self.subreddit = subreddit
        self._limit = limit

    def _build_headers(self) -> dict[str, str]:
        return {"User-Agent": settings.reddit_user_agent}

    def fetch(self, limit: int = 100) -> list[RawDeal]:
        log = logger.bind(source=self.source_name, subreddit=self.subreddit)
        effective_limit = min(limit, self._limit, 100)

        url = f"https://www.reddit.com/r/{self.subreddit}/hot.json"
        params = {"limit": effective_limit, "t": "day"}

        try:
            response = httpx.get(
                url,
                params=params,
                headers=self._build_headers(),
                timeout=15,
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.error("fetch_failed", error=str(exc))
            return []

        data = response.json()
        posts = data.get("data", {}).get("children", [])
        log.info("fetched", count=len(posts))

        deals: list[RawDeal] = []
        for post in posts:
            p = post.get("data", {})

            # Skip non-link posts, self posts with no URL, and stickied/pinned
            if p.get("stickied") or p.get("is_self") and not p.get("url"):
                continue
            # Require a flair or title that suggests a deal
            title = (p.get("title") or "").strip()
            if not title:
                continue

            original, deal = _parse_prices(title)
            created_utc = p.get("created_utc", 0)
            fetched_at = datetime.fromtimestamp(created_utc, tz=timezone.utc)

            deals.append(
                RawDeal(
                    source_deal_id=p.get("id", ""),
                    title=title,
                    url=p.get("url") or f"https://www.reddit.com{p.get('permalink', '')}",
                    description=p.get("selftext") or None,
                    original_price=original,
                    deal_price=deal,
                    expires_at=None,  # Reddit posts don't have expiry
                    raw_data={
                        "score": p.get("score", 0),
                        "num_comments": p.get("num_comments", 0),
                        "flair": p.get("link_flair_text", ""),
                        "created_utc": created_utc,
                    },
                )
            )

        log.info("parsed", deals=len(deals))
        return deals
