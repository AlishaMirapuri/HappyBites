"""MenuPageScraper — extracts specials from restaurant menu/specials pages.

Strategy
────────
1. Parse HTML with BeautifulSoup (html.parser — no lxml dependency).
2. Search for container elements whose class or id contains any of the
   SPECIALS_KEYWORDS. Each matching container becomes one ScrapedBlock.
3. Search for section/heading elements (h2, h3, h4) whose text contains a
   keyword. Collect the heading + all sibling <p> and <li> content until the
   next same-level heading. These become "heading_paragraph" blocks.
4. Deduplicate by text fingerprint so we don't double-emit a section that was
   also matched by class.

Handles
───────
• Heavily styled HTML (inline styles, font tags, nested spans)
• <br> converted to newlines before text extraction
• Malformed / unclosed tags (html.parser is lenient)
• Missing semantic structure (falls back to keyword-in-text scan)
"""

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from happybites.scraping.base import Scraper, ScrapedBlock, ScrapeResult

_SPECIALS_KEYWORDS = frozenset({
    "special", "specials", "happy", "happy-hour", "happyhour",
    "lunch", "prix", "early-bird", "earlybird", "promo", "promotion",
    "deal", "offer", "dinner",
})

_HEADING_TAGS = {"h1", "h2", "h3", "h4"}
_IGNORE_TAGS = {"nav", "footer", "header", "script", "style", "meta", "head"}


def _has_keyword(element: Tag, attrs: tuple[str, ...] = ("class", "id")) -> bool:
    """True if any of the given attributes contain a specials keyword."""
    for attr in attrs:
        val = element.get(attr, "")
        combined = " ".join(val) if isinstance(val, list) else (val or "")
        combined = combined.lower().replace("-", " ").replace("_", " ")
        if any(kw in combined for kw in _SPECIALS_KEYWORDS):
            return True
    return False


def _heading_has_keyword(tag: Tag) -> bool:
    text = tag.get_text(separator=" ").lower()
    return any(kw in text for kw in _SPECIALS_KEYWORDS)


def _element_context(element: Tag) -> str:
    """Build a CSS-selector-like path (max 3 ancestors)."""
    parts: list[str] = []
    node = element
    while node and node.name and node.name not in ("[document]", "html", "body"):
        sel = node.name
        if node.get("id"):
            sel += f'#{node["id"]}'
        elif node.get("class"):
            sel += f'.{node["class"][0]}'
        parts.append(sel)
        node = node.parent  # type: ignore[assignment]
    parts.reverse()
    return " > ".join(parts[-4:]) if parts else "unknown"


def _clean_text(element: Tag) -> str:
    """Extract text, converting <br> to newlines and collapsing whitespace."""
    # Work on a copy to avoid mutating the tree
    clone = BeautifulSoup(str(element), "html.parser")
    for br in clone.find_all("br"):
        br.replace_with("\n")
    text = clone.get_text(separator=" ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Decode HTML entities (BeautifulSoup already handles most, but just in case)
    return text.strip()


def _collect_section_text(heading: Tag) -> str:
    """Gather text from a heading and all following siblings until the next heading."""
    parts = [_clean_text(heading)]
    for sib in heading.next_siblings:
        if isinstance(sib, Comment):
            continue
        if isinstance(sib, NavigableString):
            stripped = str(sib).strip()
            if stripped:
                parts.append(stripped)
            continue
        if not isinstance(sib, Tag):
            continue
        if sib.name in _HEADING_TAGS:
            break
        if sib.name in _IGNORE_TAGS:
            continue
        parts.append(_clean_text(sib))
    return "\n".join(p for p in parts if p).strip()


def _text_fingerprint(text: str) -> str:
    """Short key for deduplication — first 80 chars of whitespace-normalised text."""
    return re.sub(r"\s+", " ", text).strip()[:80]


class MenuPageScraper(Scraper):
    """Extracts specials/promotions from restaurant menu or specials pages.

    Recognises:
    • Containers with class/id matching specials keywords
    • Section headings (h2/h3/h4) followed by descriptive paragraphs and lists
    """

    scraper_name = "menu_page"

    def scrape(self, url: str, html: str) -> ScrapeResult:
        soup = BeautifulSoup(html, "html.parser")

        # Remove boilerplate sections we never want
        for tag in soup.find_all(_IGNORE_TAGS):
            tag.decompose()

        page_title = ""
        title_tag = soup.find("title")
        if title_tag:
            page_title = title_tag.get_text().strip()

        blocks: list[ScrapedBlock] = []
        seen: set[str] = set()
        position = 0

        def _maybe_add(text: str, ctx: str, btype: str) -> None:
            nonlocal position
            if len(text) < 20:
                return
            fp = _text_fingerprint(text)
            if fp in seen:
                return
            seen.add(fp)
            blocks.append(ScrapedBlock(
                text=text,
                source_url=url,
                html_context=ctx,
                block_type=btype,
                scraper_name=self.scraper_name,
                position=position,
            ))
            position += 1

        # Pass 1: containers with specials class/id
        for tag in soup.find_all(True):
            if tag.name in _HEADING_TAGS | _IGNORE_TAGS:
                continue
            if _has_keyword(tag):
                text = _clean_text(tag)
                _maybe_add(text, _element_context(tag), "specials_section")

        # Pass 2: headings with specials keywords
        for heading in soup.find_all(_HEADING_TAGS):
            if _heading_has_keyword(heading):
                text = _collect_section_text(heading)
                _maybe_add(text, _element_context(heading), "heading_paragraph")

        return ScrapeResult(
            blocks=blocks,
            source_metadata={
                "url": url,
                "scraper_name": self.scraper_name,
                "page_title": page_title,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "block_count": len(blocks),
            },
        )
