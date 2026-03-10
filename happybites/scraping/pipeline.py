"""ScrapingPipeline: ties scraper → LLM/rule extractor → validation together.

Usage
─────
    from happybites.scraping.pipeline import ScrapingPipeline
    from happybites.scraping.scrapers.menu_page import MenuPageScraper
    from happybites.scraping.llm_extractor import NullExtractor

    pipeline = ScrapingPipeline(MenuPageScraper(), NullExtractor())
    candidates = pipeline.run(url="https://example.com/specials", html=raw_html)

For each ScrapedBlock produced by the scraper:
  1. Try LLMExtractor.extract(block) → raw dict or None
  2. If None → RuleExtractor.extract(block.text)
  3. If dict → convert to DealCandidate (extraction_method="llm")
  4. Run validate() and assign validation_errors
  5. Penalise confidence by 0.05 per validation error (floor 0.0)
"""

from dataclasses import replace

import structlog

from happybites.scraping.base import Scraper, ScrapeResult, ScrapedBlock
from happybites.scraping.llm_extractor import LLMExtractor, NullExtractor
from happybites.scraping.rule_extractor import RuleExtractor
from happybites.scraping.schema import DealCandidate, validate

logger = structlog.get_logger(__name__)


def _candidate_from_llm_dict(raw: dict, block: ScrapedBlock) -> DealCandidate:
    """Convert a raw LLM-returned dict into a DealCandidate."""
    return DealCandidate(
        deal_type=raw.get("deal_type", "other"),
        price=raw.get("price"),
        price_range=raw.get("price_range"),
        items_included=raw.get("items_included") or [],
        schedule_days=raw.get("schedule_days") or [],
        start_time=raw.get("start_time"),
        end_time=raw.get("end_time"),
        restrictions=raw.get("restrictions") or [],
        confidence=float(raw.get("confidence", 0.5)),
        validation_errors=[],
        source_url=block.source_url,
        source_block_text=block.text,
        extraction_method="llm",
        raw_extracted=raw,
    )


class ScrapingPipeline:
    """Orchestrates scraping + extraction for a single URL/HTML pair.

    Args:
        scraper:       A Scraper instance (MenuPageScraper or BlogListingScraper).
        llm_extractor: Optional LLMExtractor. Defaults to NullExtractor (rule-only).
    """

    def __init__(
        self,
        scraper: Scraper,
        llm_extractor: LLMExtractor | None = None,
    ) -> None:
        self._scraper = scraper
        self._llm = llm_extractor or NullExtractor()
        self._rule = RuleExtractor()

    def run(self, url: str, html: str) -> tuple[ScrapeResult, list[DealCandidate]]:
        """Scrape HTML and extract structured deal candidates.

        Returns:
            (ScrapeResult, list[DealCandidate])
            ScrapeResult contains the raw blocks and source metadata.
            DealCandidate list has validation_errors and confidence populated.
        """
        result = self._scraper.scrape(url, html)
        candidates: list[DealCandidate] = []

        for block in result.blocks:
            log = logger.bind(
                url=url,
                scraper=self._scraper.scraper_name,
                block_pos=block.position,
                block_type=block.block_type,
            )

            # 1. Try LLM
            llm_raw = self._llm.extract(block)
            if llm_raw is not None:
                candidate = _candidate_from_llm_dict(llm_raw, block)
                log.debug("scraping_llm_extraction", deal_type=candidate.deal_type)
            else:
                candidate = self._rule.extract(block.text, block.source_url)
                log.debug("scraping_rule_extraction", deal_type=candidate.deal_type)

            # 2. Validate and penalise confidence
            errors = validate(candidate)
            penalty = 0.05 * len(errors)
            new_confidence = round(max(0.0, candidate.confidence - penalty), 2)
            candidate = replace(
                candidate,
                validation_errors=errors,
                confidence=new_confidence,
            )

            candidates.append(candidate)
            log.info(
                "scraping_candidate_extracted",
                deal_type=candidate.deal_type,
                confidence=candidate.confidence,
                errors=len(errors),
            )

        return result, candidates
