"""BlogListingScraper — extracts deal descriptions from listicle-style pages.

Strategy
────────
1. Locate the main content area: <article>, elements with class matching
   post-content / entry-content / article-body, or <main>.
2. Within the content area, walk the headings (h2, h3) in document order.
   Each heading starts a new "item". Collect the heading text + all following
   <p>, <ul>, and <ol> siblings until the next same-or-higher heading.
3. Fall back to top-level <li> items if no headings are found (pure list
   listicles).

Handles
───────
• Inline HTML decoration inside headings (spans, strong, em, anchors)
• HTML entities (&amp; &nbsp; etc.) — BeautifulSoup decodes these
• Malformed / deeply nested HTML
• Sidebars and ads (only content area is searched)
"""

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from happybites.scraping.base import Scraper, ScrapedBlock, ScrapeResult

_CONTENT_CLASSES = re.compile(
    r"post[\-_]?content|entry[\-_]?content|article[\-_]?body|"
    r"blog[\-_]?content|main[\-_]?content|content[\-_]?area",
    re.IGNORECASE,
)
_IGNORE_TAGS = frozenset({"nav", "footer", "header", "aside", "script", "style", "meta", "head"})
_HEADING_TAGS = {"h1", "h2", "h3", "h4"}
_BLOCK_TAGS = {"p", "ul", "ol", "blockquote", "div"}


def _find_content_area(soup: BeautifulSoup) -> Tag:
    """Return the best candidate for the main article content area."""
    # 1. <article>
    article = soup.find("article")
    if article:
        return article  # type: ignore[return-value]

    # 2. Element with content-class attribute
    for tag in soup.find_all(True):
        cls = " ".join(tag.get("class", []))
        if _CONTENT_CLASSES.search(cls):
            return tag  # type: ignore[return-value]

    # 3. <main>
    main = soup.find("main")
    if main:
        return main  # type: ignore[return-value]

    # 4. Fallback: body
    return soup.find("body") or soup  # type: ignore[return-value]


def _clean_text(element: Tag) -> str:
    """Extract clean text from an element, normalising whitespace."""
    clone = BeautifulSoup(str(element), "html.parser")
    for br in clone.find_all("br"):
        br.replace_with("\n")
    text = clone.get_text(separator=" ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _element_context(element: Tag, area: Tag) -> str:
    """CSS-selector-like path relative to the content area."""
    parts: list[str] = []
    node = element
    while node and node != area and node.name not in ("[document]", "html", "body"):
        sel = node.name
        if node.get("id"):
            sel += f'#{node["id"]}'
        elif node.get("class"):
            sel += f'.{node["class"][0]}'
        parts.append(sel)
        node = node.parent  # type: ignore[assignment]
    parts.reverse()
    return " > ".join(parts[-3:]) if parts else element.name or "unknown"


def _collect_item(heading: Tag, area: Tag) -> str:
    """Collect heading + following block-level siblings until next heading."""
    parts = [_clean_text(heading)]
    for sib in heading.next_siblings:
        if isinstance(sib, Comment):
            continue
        if isinstance(sib, NavigableString):
            s = str(sib).strip()
            if s:
                parts.append(s)
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
    return re.sub(r"\s+", " ", text).strip()[:80]


class BlogListingScraper(Scraper):
    """Extracts deal listings from blog/listicle pages.

    Recognises heading-per-item structure (e.g. "## 1. The Spotted Dog")
    and falls back to <li> items for plain list formats.
    """

    scraper_name = "blog_listing"

    def scrape(self, url: str, html: str) -> ScrapeResult:
        soup = BeautifulSoup(html, "html.parser")

        # Read title before stripping <head>
        page_title = ""
        title_tag = soup.find("title")
        if title_tag:
            page_title = title_tag.get_text().strip()

        # Strip boilerplate
        for tag in soup.find_all(_IGNORE_TAGS):
            tag.decompose()

        content_area = _find_content_area(soup)
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

        # Primary strategy: heading-based items
        # Only consider h2/h3 (h1 is usually the page title, h4+ too granular)
        headings = content_area.find_all(["h2", "h3"])
        for heading in headings:
            text = _collect_item(heading, content_area)
            ctx = _element_context(heading, content_area)
            _maybe_add(text, ctx, "heading_paragraph")

        # Fallback: top-level <li> items when there are no useful headings
        if not blocks:
            for li in content_area.find_all("li"):
                # Skip nested <li> (only take top-level items)
                if li.find_parent("li"):
                    continue
                text = _clean_text(li)
                ctx = _element_context(li, content_area)
                _maybe_add(text, ctx, "list_item")

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
