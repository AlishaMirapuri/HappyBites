"""
Local HTML fixture collector for demo and testing.

Parses the HTML files in data/fixtures/html/ and returns RawDeal objects.
No network access — fully offline. Works with both blog-article layouts
(h2 + following paragraphs) and restaurant-page layouts (section + ul).

Supported fixture formats
─────────────────────────
Blog article  data/fixtures/html/blog_listing.html  (NYC happy hours)
Restaurant    data/fixtures/html/menu_page.html     (The Rusty Anchor)
SF blog       data/fixtures/html/sf_deals.html      (SF food deals)
"""

from __future__ import annotations

import re
from pathlib import Path

import structlog
from bs4 import BeautifulSoup

from happybites.ingestion.base import BaseCollector, RawDeal

logger = structlog.get_logger(__name__)

# Three directory levels up from connectors/ → project root / data/fixtures/html
_DEFAULT_FIXTURE_DIR = Path(__file__).parents[3] / "data" / "fixtures" / "html"

# Tags whose text is never deals (navigation chrome, boilerplate)
_SKIP_TAGS = frozenset(["nav", "footer", "aside", "script", "style", "header"])

# Heading text patterns that are definitely not deals
_SKIP_TITLE_RE = re.compile(
    r"(newsletter|subscribe|contact|privacy|terms|copyright|follow us|"
    r"social media|top picks|our menu|reservations|about)",
    re.IGNORECASE,
)

_PRICE_RE = re.compile(r"\$([0-9]+(?:\.[0-9]{1,2})?)")


def _extract_prices(text: str) -> list[float]:
    return [float(m) for m in _PRICE_RE.findall(text)]


def _slug(text: str) -> str:
    """Stable lowercase slug for generating deal IDs."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50]


def _clean_title(raw: str) -> str:
    """Strip leading numbering and unicode punctuation."""
    t = re.sub(r"^\d+[.)]\s*", "", raw)
    # Replace common unicode dashes/apostrophes
    for old, new in [("\u2013", "-"), ("\u2014", "-"), ("\u2019", "'"), ("\u00e9", "e")]:
        t = t.replace(old, new)
    return t.strip()


class FixtureCollector(BaseCollector):
    """Reads local HTML fixtures instead of hitting the network.

    Each .html file in fixture_dir is parsed; h2/h3 headings + their
    following siblings form one RawDeal each.
    """

    source_name = "fixture"

    def __init__(self, fixture_dir: Path | str | None = None):
        self.fixture_dir = Path(fixture_dir) if fixture_dir else _DEFAULT_FIXTURE_DIR

    # ── Public API ────────────────────────────────────────────────────────────

    def fetch(self, limit: int = 100) -> list[RawDeal]:
        log = logger.bind(source=self.source_name, dir=str(self.fixture_dir))
        if not self.fixture_dir.exists():
            log.warning("fixture_dir_not_found")
            return []

        deals: list[RawDeal] = []
        for html_file in sorted(self.fixture_dir.glob("*.html")):
            file_deals = self._parse_file(html_file)
            log.info("parsed_fixture", file=html_file.name, deals=len(file_deals))
            deals.extend(file_deals)

        log.info("fixture_fetch_complete", total=len(deals))
        return deals[:limit]

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse_file(self, path: Path) -> list[RawDeal]:
        html = path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")

        # Remove non-content chrome
        for tag in soup(_SKIP_TAGS):
            tag.decompose()

        # Prefer article or main; fall back to body
        container = soup.find("article") or soup.find("main") or soup.body
        if not container:
            return []

        deals: list[RawDeal] = []
        seen_ids: set[str] = set()

        for heading in container.find_all(["h2", "h3"]):
            deal = self._heading_to_deal(heading, path, seen_ids)
            if deal:
                deals.append(deal)
                seen_ids.add(deal.source_deal_id)

        return deals

    def _heading_to_deal(
        self,
        heading,
        path: Path,
        seen_ids: set[str],
    ) -> RawDeal | None:
        raw_title = heading.get_text(separator=" ", strip=True)
        title = _clean_title(raw_title)

        if not title or len(title) < 5 or len(title) > 250:
            return None
        if _SKIP_TITLE_RE.search(title):
            return None

        # Collect description text from siblings until the next heading
        desc_parts: list[str] = []
        for sibling in heading.next_siblings:
            sib_name = getattr(sibling, "name", None)
            if sib_name in ("h1", "h2", "h3"):
                break
            if sib_name in _SKIP_TAGS:
                continue
            if sib_name:
                text = sibling.get_text(separator=" ", strip=True)
            else:
                text = str(sibling).strip()
            if text:
                desc_parts.append(text)

        description: str | None = " ".join(desc_parts)[:500] or None

        # Price extraction from combined text
        full_text = f"{title} {description or ''}"
        prices = _extract_prices(full_text)
        deal_price = min(prices) if prices else None
        original_price = max(prices) if len(prices) > 1 else None

        # Stable deal ID: file stem + title slug
        deal_id = f"fix-{path.stem}-{_slug(title)}"
        if deal_id in seen_ids:
            return None

        return RawDeal(
            source_deal_id=deal_id,
            title=title,
            url=f"file://{path.resolve()}",
            description=description,
            deal_price=deal_price,
            original_price=original_price,
            raw_data={"fixture_file": path.name, "fixture_dir": str(path.parent)},
        )
