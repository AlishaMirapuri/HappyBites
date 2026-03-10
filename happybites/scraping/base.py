"""Base types and interface for HTML scrapers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ScrapedBlock:
    """A text block extracted from an HTML page."""

    text: str
    source_url: str
    html_context: str   # CSS-selector-like breadcrumb, e.g. "section#happy-hour > p"
    block_type: str     # "specials_section" | "list_item" | "heading_paragraph"
    scraper_name: str
    position: int = 0   # index within the page (for ordering)


@dataclass
class ScrapeResult:
    """Full output of a scraper run."""

    blocks: list[ScrapedBlock]
    source_metadata: dict   # url, scraper_name, page_title, scraped_at, block_count


class Scraper(ABC):
    """All HTML scrapers implement this interface.

    Input:  url (str) + html (str)
    Output: ScrapeResult containing extracted text blocks and source metadata

    Scrapers must be stateless: each call to scrape() is independent.
    """

    scraper_name: str

    @abstractmethod
    def scrape(self, url: str, html: str) -> ScrapeResult:
        """Extract text blocks from raw HTML.

        Args:
            url:  The URL the HTML was fetched from — used as provenance metadata.
                  Not used for live HTTP requests; pass the fixture URL for tests.
            html: Raw HTML string. May be malformed, partial, or heavily styled.

        Returns:
            ScrapeResult with extracted blocks and metadata dict.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} scraper={self.scraper_name}>"
