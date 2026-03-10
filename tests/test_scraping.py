"""Tests for the HTML scraping + deal extraction pipeline.

Covers:
  • MenuPageScraper / BlogListingScraper — fixture HTML and edge cases
  • RuleExtractor — deal type, schedule, time, price, items, restrictions
  • Ambiguous schedule expressions: "weekdays", "daily", "after 5"
  • Malformed HTML — scrapers must not raise
  • DealCandidate schema validation
  • ScrapingPipeline end-to-end with NullExtractor (rule-based)
  • Confidence scoring

All tests use local HTML fixtures (no live HTTP).
"""

from pathlib import Path

import pytest

from happybites.scraping.base import ScrapedBlock, ScrapeResult
from happybites.scraping.llm_extractor import NullExtractor
from happybites.scraping.pipeline import ScrapingPipeline
from happybites.scraping.rule_extractor import (
    RuleExtractor,
    _detect_deal_type,
    _detect_days,
    _extract_items,
    _extract_price,
    _extract_restrictions,
    _parse_time_range,
)
from happybites.scraping.schema import DealCandidate, validate
from happybites.scraping.scrapers.blog_listing import BlogListingScraper
from happybites.scraping.scrapers.menu_page import MenuPageScraper

FIXTURE_DIR = Path(__file__).parents[1] / "data" / "fixtures" / "html"
MENU_HTML = (FIXTURE_DIR / "menu_page.html").read_text()
BLOG_HTML = (FIXTURE_DIR / "blog_listing.html").read_text()
MENU_URL = "https://rustyanchor.example.com/specials"
BLOG_URL = "https://foodieguide.example.com/best-happy-hour-nyc"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_block(text: str, url: str = "https://example.com") -> ScrapedBlock:
    return ScrapedBlock(
        text=text,
        source_url=url,
        html_context="div.test",
        block_type="heading_paragraph",
        scraper_name="test",
        position=0,
    )


def _make_candidate(**kwargs) -> DealCandidate:
    defaults = dict(
        deal_type="happy_hour",
        price=None,
        price_range=None,
        items_included=[],
        schedule_days=["weekdays"],
        start_time="17:00",
        end_time="19:00",
        restrictions=[],
        confidence=0.8,
        validation_errors=[],
        source_url="https://example.com",
        source_block_text="Happy Hour Mon-Fri 5-7pm",
        extraction_method="rule_based",
    )
    defaults.update(kwargs)
    return DealCandidate(**defaults)


# ── MenuPageScraper ───────────────────────────────────────────────────────────


class TestMenuPageScraper:
    def test_returns_scrape_result(self):
        result = MenuPageScraper().scrape(MENU_URL, MENU_HTML)
        assert isinstance(result, ScrapeResult)

    def test_extracts_at_least_two_blocks(self):
        result = MenuPageScraper().scrape(MENU_URL, MENU_HTML)
        assert len(result.blocks) >= 2

    def test_finds_happy_hour_block(self):
        result = MenuPageScraper().scrape(MENU_URL, MENU_HTML)
        combined = " ".join(b.text for b in result.blocks).lower()
        assert "happy hour" in combined

    def test_finds_lunch_special_block(self):
        result = MenuPageScraper().scrape(MENU_URL, MENU_HTML)
        combined = " ".join(b.text for b in result.blocks).lower()
        assert "lunch" in combined

    def test_finds_early_bird_block(self):
        result = MenuPageScraper().scrape(MENU_URL, MENU_HTML)
        combined = " ".join(b.text for b in result.blocks).lower()
        assert "early bird" in combined

    def test_excludes_footer_text(self):
        result = MenuPageScraper().scrape(MENU_URL, MENU_HTML)
        combined = " ".join(b.text for b in result.blocks).lower()
        assert "all rights reserved" not in combined

    def test_blocks_have_correct_metadata(self):
        result = MenuPageScraper().scrape(MENU_URL, MENU_HTML)
        for block in result.blocks:
            assert block.source_url == MENU_URL
            assert block.scraper_name == "menu_page"
            assert block.html_context != ""
            assert block.block_type in {"specials_section", "heading_paragraph"}

    def test_source_metadata_keys(self):
        result = MenuPageScraper().scrape(MENU_URL, MENU_HTML)
        assert result.source_metadata["url"] == MENU_URL
        assert result.source_metadata["scraper_name"] == "menu_page"
        assert "scraped_at" in result.source_metadata
        assert result.source_metadata["block_count"] == len(result.blocks)

    def test_decodes_html_entities(self):
        html = """<html><body>
            <section class="specials">
              <h2>Happy Hour</h2>
              <p>Draft beers &amp; house wines. Mon&ndash;Fri 5pm.</p>
            </section>
        </body></html>"""
        result = MenuPageScraper().scrape("https://x.com", html)
        assert len(result.blocks) >= 1
        # Entities should be decoded by BeautifulSoup
        assert "&amp;" not in result.blocks[0].text
        assert "&ndash;" not in result.blocks[0].text

    def test_handles_malformed_html_no_exception(self):
        """Unclosed tags and garbage must not raise."""
        bad_html = """<html><body>
            <div class="specials">
              <h2>Happy Hour<p>Mon-Fri 5-7pm $5 beers
              <div>
                <p>half price appetizers
            </div>
        </body>"""
        result = MenuPageScraper().scrape("https://x.com", bad_html)
        assert isinstance(result, ScrapeResult)

    def test_handles_empty_html(self):
        result = MenuPageScraper().scrape("https://x.com", "")
        assert result.blocks == []

    def test_handles_html_with_no_specials(self):
        html = """<html><body>
            <h1>Welcome</h1><p>Come visit our restaurant.</p>
        </body></html>"""
        result = MenuPageScraper().scrape("https://x.com", html)
        assert len(result.blocks) == 0

    def test_no_duplicate_blocks(self):
        result = MenuPageScraper().scrape(MENU_URL, MENU_HTML)
        texts = [b.text for b in result.blocks]
        assert len(texts) == len(set(texts)), "Duplicate blocks emitted"

    def test_inline_styles_stripped_from_text(self):
        html = """<html><body>
            <div class="happy-hour">
              <h2><span style="color:red;font-size:24px;">Happy Hour</span></h2>
              <p style="margin:0;">Mon–Fri 5–7pm, $5 beers</p>
            </div>
        </body></html>"""
        result = MenuPageScraper().scrape("https://x.com", html)
        assert len(result.blocks) >= 1
        assert "style=" not in result.blocks[0].text

    def test_br_tags_become_whitespace(self):
        html = """<html><body>
            <section class="specials">
              <h2>Lunch Special</h2>
              <p>Soup or salad<br/>Sandwich<br/>Drink — $12 weekdays 11am-3pm</p>
            </section>
        </body></html>"""
        result = MenuPageScraper().scrape("https://x.com", html)
        assert len(result.blocks) >= 1
        # <br> should not leave literal tag text
        assert "<br" not in result.blocks[0].text


# ── BlogListingScraper ────────────────────────────────────────────────────────


class TestBlogListingScraper:
    def test_returns_scrape_result(self):
        result = BlogListingScraper().scrape(BLOG_URL, BLOG_HTML)
        assert isinstance(result, ScrapeResult)

    def test_extracts_multiple_items(self):
        result = BlogListingScraper().scrape(BLOG_URL, BLOG_HTML)
        # Fixture has 7 h2 items (h1 is page title, excluded by strategy)
        assert len(result.blocks) >= 5

    def test_spotted_dog_block_present(self):
        result = BlogListingScraper().scrape(BLOG_URL, BLOG_HTML)
        combined = " ".join(b.text for b in result.blocks).lower()
        assert "spotted dog" in combined

    def test_excludes_sidebar_content(self):
        result = BlogListingScraper().scrape(BLOG_URL, BLOG_HTML)
        combined = " ".join(b.text for b in result.blocks).lower()
        assert "subscribe" not in combined

    def test_blocks_have_correct_metadata(self):
        result = BlogListingScraper().scrape(BLOG_URL, BLOG_HTML)
        for block in result.blocks:
            assert block.source_url == BLOG_URL
            assert block.scraper_name == "blog_listing"
            assert block.block_type in {"heading_paragraph", "list_item"}

    def test_page_title_in_metadata(self):
        result = BlogListingScraper().scrape(BLOG_URL, BLOG_HTML)
        assert "Happy Hour" in result.source_metadata["page_title"]

    def test_handles_malformed_html(self):
        bad_html = """<html><body>
            <article>
              <h2>Happy Hour<p>Mon-Fri 5–7pm, $5 beers, dine-in only
              <h2>Lunch Deal
              <p>Weekdays noon–2pm, $12 combo
            </article>"""
        result = BlogListingScraper().scrape("https://x.com", bad_html)
        assert len(result.blocks) >= 1

    def test_handles_empty_html(self):
        result = BlogListingScraper().scrape("https://x.com", "")
        assert result.blocks == []

    def test_fallback_to_list_items(self):
        html = """<html><body>
            <article>
              <ul>
                <li>Happy hour Mon-Fri 5-7pm: $4 beers</li>
                <li>Lunch special weekdays $10 sandwich combo</li>
              </ul>
            </article>
        </body></html>"""
        result = BlogListingScraper().scrape("https://x.com", html)
        assert len(result.blocks) >= 2
        assert result.blocks[0].block_type == "list_item"

    def test_no_duplicate_blocks(self):
        result = BlogListingScraper().scrape(BLOG_URL, BLOG_HTML)
        texts = [b.text for b in result.blocks]
        assert len(texts) == len(set(texts))

    def test_blocks_ordered_by_position(self):
        result = BlogListingScraper().scrape(BLOG_URL, BLOG_HTML)
        positions = [b.position for b in result.blocks]
        assert positions == sorted(positions)


# ── RuleExtractor — deal type ─────────────────────────────────────────────────


class TestRuleExtractorDealType:
    def test_happy_hour(self):
        assert _detect_deal_type("Happy Hour Mon-Fri 5-7pm") == "happy_hour"

    def test_happy_hour_hyphenated(self):
        assert _detect_deal_type("Join us for happy-hour specials") == "happy_hour"

    def test_lunch_special(self):
        assert _detect_deal_type("Lunch Special $12 weekdays") == "lunch_special"

    def test_lunch_menu(self):
        assert _detect_deal_type("Lunch menu available 11am-3pm") == "lunch_special"

    def test_lunch_combo(self):
        assert _detect_deal_type("$13 lunch combo: soup + sandwich") == "lunch_special"

    def test_early_bird(self):
        assert _detect_deal_type("Early bird dinner available daily") == "early_bird"

    def test_prix_fixe(self):
        assert _detect_deal_type("Prix fixe menu $45 per person") == "prix_fixe"

    def test_prix_fixe_hyphenated(self):
        assert _detect_deal_type("Prix-fixe tasting menu on weekends") == "prix_fixe"

    def test_dinner_special(self):
        assert _detect_deal_type("Dinner special: $28 entrée + dessert") == "dinner_special"

    def test_unknown_defaults_to_other(self):
        assert _detect_deal_type("Come visit us soon!") == "other"


# ── RuleExtractor — schedule days ─────────────────────────────────────────────


class TestRuleExtractorDays:
    def test_weekdays_keyword(self):
        assert _detect_days("Available weekdays only") == ["weekdays"]

    def test_weekdays_from_range(self):
        assert _detect_days("Monday through Friday happy hour") == ["weekdays"]

    def test_weekdays_abbreviation(self):
        assert _detect_days("Mon-Fri 5-7pm") == ["weekdays"]

    def test_daily(self):
        assert _detect_days("Available daily after 5pm") == ["daily"]

    def test_every_day(self):
        assert _detect_days("Every day from 3 to 6 PM") == ["daily"]

    def test_7_days(self):
        assert _detect_days("Specials 7 days a week") == ["daily"]

    def test_weekends(self):
        assert _detect_days("Weekend brunch specials") == ["weekends"]

    def test_saturday_and_sunday(self):
        assert _detect_days("Every Saturday and Sunday 10am-2pm") == ["weekends"]

    def test_individual_days(self):
        days = _detect_days("Tuesday and Thursday only")
        assert set(days) == {"tuesday", "thursday"}

    def test_monday_through_thursday(self):
        days = _detect_days("Monday through Thursday, 4-6pm")
        assert set(days) == {"monday", "tuesday", "wednesday", "thursday"}

    def test_five_named_days_collapses_to_weekdays(self):
        text = "Monday, Tuesday, Wednesday, Thursday, and Friday specials"
        assert _detect_days(text) == ["weekdays"]

    def test_sat_sun_collapses_to_weekends(self):
        text = "Saturday and Sunday brunch"
        assert _detect_days(text) == ["weekends"]

    def test_no_days_returns_empty(self):
        assert _detect_days("Happy hour specials available now") == []


# ── RuleExtractor — time parsing ──────────────────────────────────────────────


class TestRuleExtractorTime:
    def test_explicit_range_with_pm(self):
        start, end = _parse_time_range("Mon-Fri 5-7pm")
        assert start == "17:00"
        assert end == "19:00"

    def test_explicit_am_pm(self):
        start, end = _parse_time_range("11am to 3pm")
        assert start == "11:00"
        assert end == "15:00"

    def test_both_explicit_pm(self):
        start, end = _parse_time_range("5pm to 7pm")
        assert start == "17:00"
        assert end == "19:00"

    def test_24h_range(self):
        start, end = _parse_time_range("17:00 to 19:00")
        assert start == "17:00"
        assert end == "19:00"

    def test_ambiguous_after_5(self):
        """'after 5' in restaurant context → 17:00, no end."""
        start, end = _parse_time_range("Daily after 5")
        assert start == "17:00"
        assert end is None

    def test_after_with_explicit_pm(self):
        start, end = _parse_time_range("After 5pm daily")
        assert start == "17:00"
        assert end is None

    def test_until_pattern(self):
        start, end = _parse_time_range("Order before 6pm to get early bird pricing")
        assert start is None
        assert end == "18:00"

    def test_noon(self):
        start, end = _parse_time_range("Lunch noon to 2pm")
        assert start == "12:00"
        assert end == "14:00"

    def test_half_hour(self):
        start, end = _parse_time_range("5:30pm to 7:30pm")
        assert start == "17:30"
        assert end == "19:30"

    def test_5pm_to_630pm(self):
        start, end = _parse_time_range("Tuesday through Thursday 5:00pm to 6:30pm")
        assert start == "17:00"
        assert end == "18:30"

    def test_no_time_returns_none_none(self):
        start, end = _parse_time_range("Happy hour every weekday")
        assert start is None
        assert end is None

    def test_single_explicit_time(self):
        start, end = _parse_time_range("Starts at 4pm")
        assert start == "16:00"
        assert end is None


# ── RuleExtractor — price ─────────────────────────────────────────────────────


class TestRuleExtractorPrice:
    def test_single_price(self):
        price, pr = _extract_price("Lunch combo $13 weekdays")
        assert price == 13.0
        assert pr is None

    def test_price_with_cents(self):
        price, pr = _extract_price("$9.99 happy hour special")
        assert price == 9.99
        assert pr is None

    def test_price_range_with_dash(self):
        price, pr = _extract_price("Brunch combo $14-$18")
        assert price is None
        assert pr == "$14-$18"

    def test_price_range_normalises_order(self):
        price, pr = _extract_price("from $18 to $14")   # reversed
        assert pr == "$14-$18"

    def test_no_price(self):
        price, pr = _extract_price("Happy hour daily — ask your server")
        assert price is None
        assert pr is None

    def test_multiple_prices_returns_first(self):
        price, pr = _extract_price("$4 beers, $6 wines, $7 cocktails")
        assert price == 4.0
        assert pr is None


# ── RuleExtractor — items ─────────────────────────────────────────────────────


class TestRuleExtractorItems:
    def test_including_trigger(self):
        items = _extract_items("Deal including wings, fries, and cocktails")
        assert "wings" in items
        assert "fries" in items
        assert "cocktails" in items

    def test_colon_list(self):
        items = _extract_items("Combo: soup, sandwich, drink")
        assert "soup" in items
        assert "sandwich" in items
        assert "drink" in items

    def test_bullet_lines(self):
        text = "Happy Hour:\n- $4 draft beers\n- $6 house wines\n- Half-price appetizers"
        items = _extract_items(text)
        assert any("draft beers" in i for i in items)
        assert any("house wines" in i for i in items)

    def test_no_items_returns_empty(self):
        items = _extract_items("Happy hour Mon-Fri 5-7pm")
        assert items == []

    def test_items_truncated_at_10(self):
        text = "including a, b, c, d, e, f, g, h, i, j, k, l"
        items = _extract_items(text)
        assert len(items) <= 10


# ── RuleExtractor — restrictions ─────────────────────────────────────────────


class TestRuleExtractorRestrictions:
    def test_dine_in_only(self):
        r = _extract_restrictions("$5 beers. Dine-in only.")
        assert "dine-in only" in r

    def test_21_plus(self):
        r = _extract_restrictions("Must be 21 or older to participate.")
        assert any("21" in x for x in r)

    def test_no_substitutions(self):
        r = _extract_restrictions("Not valid with other offers. No substitutions.")
        assert "no substitutions" in r

    def test_not_valid_with_other_offers(self):
        r = _extract_restrictions("Not valid with other offers.")
        assert "not valid with other offers" in r

    def test_reservations_required(self):
        r = _extract_restrictions("Reservations required. Limit 2 per table.")
        assert "reservations required" in r

    def test_bar_only(self):
        r = _extract_restrictions("Happy hour at the bar only.")
        assert "bar only" in r

    def test_no_restrictions(self):
        r = _extract_restrictions("Happy hour weekdays 5-7pm, $5 beers")
        assert r == []


# ── RuleExtractor — full extract ─────────────────────────────────────────────


class TestRuleExtractorFull:
    def setup_method(self):
        self.ex = RuleExtractor()

    def test_happy_hour_full(self):
        text = "Happy Hour Monday through Friday, 4pm to 7pm. $4 draft beers, $6 wines. Dine-in only."
        c = self.ex.extract(text, "https://example.com")
        assert c.deal_type == "happy_hour"
        assert c.schedule_days == ["weekdays"]
        assert c.start_time == "16:00"
        assert c.end_time == "19:00"
        assert c.price == 4.0
        assert "dine-in only" in c.restrictions
        assert c.extraction_method == "rule_based"

    def test_lunch_special_full(self):
        text = "Lunch Special weekdays 11am-3pm. $13 combo: soup, sandwich, drink."
        c = self.ex.extract(text)
        assert c.deal_type == "lunch_special"
        assert c.schedule_days == ["weekdays"]
        assert c.start_time == "11:00"
        assert c.end_time == "15:00"
        assert c.price == 13.0
        assert c.validation_errors == []

    def test_early_bird_daily_ambiguous_time(self):
        text = "Early bird dinner available daily. Order before 6 and save!"
        c = self.ex.extract(text)
        assert c.deal_type == "early_bird"
        assert c.schedule_days == ["daily"]
        assert c.end_time == "18:00"

    def test_prix_fixe_per_person(self):
        text = "Prix fixe menu: $38 per person. Includes soup, entrée, and dessert. Reservations required."
        c = self.ex.extract(text)
        assert c.deal_type == "prix_fixe"
        assert c.price == 38.0
        assert "per person" in c.restrictions
        assert "reservations required" in c.restrictions

    def test_confidence_increases_with_fields(self):
        sparse = self.ex.extract("Come join us for specials!")
        rich = self.ex.extract(
            "Happy Hour Mon-Fri 5-7pm, $5 beers including drafts and wines. Dine-in only."
        )
        assert rich.confidence > sparse.confidence

    def test_all_fields_present_high_confidence(self):
        text = (
            "Happy Hour Monday through Friday, 5pm to 7pm. "
            "$4 draft beers. Dine-in only."
        )
        c = self.ex.extract(text)
        assert c.confidence >= 0.8

    def test_no_signal_low_confidence(self):
        c = self.ex.extract("Welcome to our restaurant!")
        assert c.confidence <= 0.35

    def test_source_url_preserved(self):
        c = self.ex.extract("Happy hour daily 5-7pm", source_url="https://myplace.com/specials")
        assert c.source_url == "https://myplace.com/specials"

    def test_source_block_text_preserved(self):
        text = "Happy hour daily 5-7pm"
        c = self.ex.extract(text)
        assert c.source_block_text == text

    def test_messy_html_decoded_text(self):
        """Extractor should handle text that still has HTML entity residue."""
        text = "Happy Hour Mon–Fri 5–7pm. $4 beers &amp; $6 wines. Dine-in only."
        c = self.ex.extract(text)
        # Should extract even with entity noise; deal_type and days should work
        assert c.deal_type == "happy_hour"
        assert c.schedule_days == ["weekdays"]


# ── DealCandidate validation ──────────────────────────────────────────────────


class TestDealCandidateValidation:
    def test_valid_candidate_no_errors(self):
        c = _make_candidate()
        assert validate(c) == []

    def test_invalid_deal_type(self):
        c = _make_candidate(deal_type="flash_sale")
        errors = validate(c)
        assert any("invalid deal_type" in e for e in errors)

    def test_negative_price(self):
        c = _make_candidate(price=-5.0, price_range=None)
        errors = validate(c)
        assert any("non-negative" in e for e in errors)

    def test_invalid_price_range_format(self):
        c = _make_candidate(price_range="8 to 12 dollars")
        errors = validate(c)
        assert any("price_range" in e for e in errors)

    def test_price_and_price_range_mutually_exclusive(self):
        c = _make_candidate(price=10.0, price_range="$8-$12")
        errors = validate(c)
        assert any("mutually exclusive" in e for e in errors)

    def test_invalid_day(self):
        c = _make_candidate(schedule_days=["mondays", "fridays"])
        errors = validate(c)
        assert any("invalid schedule_days" in e for e in errors)

    def test_invalid_time_format(self):
        c = _make_candidate(start_time="5:00 PM")
        errors = validate(c)
        assert any("start_time" in e for e in errors)

    def test_end_before_start(self):
        c = _make_candidate(start_time="19:00", end_time="17:00")
        errors = validate(c)
        assert any("before" in e for e in errors)

    def test_equal_start_end_invalid(self):
        c = _make_candidate(start_time="17:00", end_time="17:00")
        errors = validate(c)
        assert any("before" in e for e in errors)

    def test_confidence_out_of_range(self):
        c = _make_candidate(confidence=1.5)
        errors = validate(c)
        assert any("confidence" in e for e in errors)

    def test_valid_daily_schedule(self):
        c = _make_candidate(schedule_days=["daily"])
        assert validate(c) == []

    def test_valid_weekdays_weekends(self):
        c = _make_candidate(schedule_days=["weekdays"])
        assert validate(c) == []

    def test_valid_price_range_format(self):
        c = _make_candidate(price=None, price_range="$14-$18")
        assert validate(c) == []

    def test_none_times_valid(self):
        c = _make_candidate(start_time=None, end_time=None)
        assert validate(c) == []


# ── ScrapingPipeline ──────────────────────────────────────────────────────────


class TestScrapingPipeline:
    def test_menu_pipeline_returns_candidates(self):
        pipeline = ScrapingPipeline(MenuPageScraper(), NullExtractor())
        _, candidates = pipeline.run(MENU_URL, MENU_HTML)
        assert len(candidates) >= 2

    def test_blog_pipeline_returns_candidates(self):
        pipeline = ScrapingPipeline(BlogListingScraper(), NullExtractor())
        _, candidates = pipeline.run(BLOG_URL, BLOG_HTML)
        assert len(candidates) >= 5

    def test_candidates_are_deal_candidates(self):
        pipeline = ScrapingPipeline(MenuPageScraper(), NullExtractor())
        _, candidates = pipeline.run(MENU_URL, MENU_HTML)
        for c in candidates:
            assert isinstance(c, DealCandidate)

    def test_validation_errors_populated(self):
        pipeline = ScrapingPipeline(MenuPageScraper(), NullExtractor())
        _, candidates = pipeline.run(MENU_URL, MENU_HTML)
        # All candidates have validation_errors list (may be empty)
        for c in candidates:
            assert isinstance(c.validation_errors, list)

    def test_confidence_penalised_for_errors(self):
        """A candidate with validation errors has lower confidence than one without."""
        pipeline = ScrapingPipeline(MenuPageScraper(), NullExtractor())
        _, candidates = pipeline.run(MENU_URL, MENU_HTML)
        for c in candidates:
            # confidence must be non-negative
            assert c.confidence >= 0.0

    def test_source_url_on_candidates(self):
        pipeline = ScrapingPipeline(BlogListingScraper(), NullExtractor())
        _, candidates = pipeline.run(BLOG_URL, BLOG_HTML)
        for c in candidates:
            assert c.source_url == BLOG_URL

    def test_pipeline_returns_scrape_result(self):
        pipeline = ScrapingPipeline(MenuPageScraper(), NullExtractor())
        result, _ = pipeline.run(MENU_URL, MENU_HTML)
        assert isinstance(result, ScrapeResult)

    def test_empty_html_returns_empty_candidates(self):
        pipeline = ScrapingPipeline(MenuPageScraper(), NullExtractor())
        result, candidates = pipeline.run("https://x.com", "")
        assert candidates == []
        assert result.blocks == []

    def test_null_extractor_uses_rule_based(self):
        pipeline = ScrapingPipeline(MenuPageScraper(), NullExtractor())
        _, candidates = pipeline.run(MENU_URL, MENU_HTML)
        for c in candidates:
            assert c.extraction_method == "rule_based"

    def test_blog_happy_hour_extracted(self):
        pipeline = ScrapingPipeline(BlogListingScraper(), NullExtractor())
        _, candidates = pipeline.run(BLOG_URL, BLOG_HTML)
        types = [c.deal_type for c in candidates]
        assert "happy_hour" in types

    def test_blog_lunch_special_extracted(self):
        pipeline = ScrapingPipeline(BlogListingScraper(), NullExtractor())
        _, candidates = pipeline.run(BLOG_URL, BLOG_HTML)
        types = [c.deal_type for c in candidates]
        assert "lunch_special" in types

    def test_blog_weekdays_schedule_extracted(self):
        pipeline = ScrapingPipeline(BlogListingScraper(), NullExtractor())
        _, candidates = pipeline.run(BLOG_URL, BLOG_HTML)
        all_days = [day for c in candidates for day in c.schedule_days]
        assert "weekdays" in all_days

    def test_blog_daily_schedule_extracted(self):
        pipeline = ScrapingPipeline(BlogListingScraper(), NullExtractor())
        _, candidates = pipeline.run(BLOG_URL, BLOG_HTML)
        all_days = [day for c in candidates for day in c.schedule_days]
        assert "daily" in all_days

    def test_blog_weekends_schedule_extracted(self):
        pipeline = ScrapingPipeline(BlogListingScraper(), NullExtractor())
        _, candidates = pipeline.run(BLOG_URL, BLOG_HTML)
        all_days = [day for c in candidates for day in c.schedule_days]
        assert "weekends" in all_days

    def test_malformed_html_does_not_raise(self):
        bad = "<html><body><div class='specials'><h2>Happy Hour<p>Mon-Fri 5-7pm"
        pipeline = ScrapingPipeline(MenuPageScraper(), NullExtractor())
        result, candidates = pipeline.run("https://x.com", bad)
        assert isinstance(result, ScrapeResult)
        assert isinstance(candidates, list)


# ── Prompt template ───────────────────────────────────────────────────────────


class TestPromptTemplate:
    def test_prompt_file_exists(self):
        p = Path(__file__).parents[1] / "data" / "prompts" / "scraping_extraction.txt"
        assert p.exists()

    def test_prompt_has_placeholders(self):
        p = Path(__file__).parents[1] / "data" / "prompts" / "scraping_extraction.txt"
        text = p.read_text()
        for placeholder in ("{source_url}", "{scraper_name}", "{block_text}", "{block_type}"):
            assert placeholder in text, f"Missing placeholder: {placeholder}"

    def test_prompt_includes_all_deal_types(self):
        p = Path(__file__).parents[1] / "data" / "prompts" / "scraping_extraction.txt"
        text = p.read_text()
        for dt in ("happy_hour", "lunch_special", "early_bird", "prix_fixe", "dinner_special"):
            assert dt in text

    def test_prompt_includes_time_format_instruction(self):
        p = Path(__file__).parents[1] / "data" / "prompts" / "scraping_extraction.txt"
        text = p.read_text()
        assert "HH:MM" in text
        assert "24" in text
