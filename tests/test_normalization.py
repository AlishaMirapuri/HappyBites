"""Tests for the normalization layer.

Covers:
  - canons.py: price parsing, day expansion, deal type classification, text cleanup
  - confidence.py: confidence and quality scoring
  - deduplicator.py: dedup key construction, dedup logic
  - normalizer.py: end-to-end RawDeal → NormalizedDeal and DealCandidate → NormalizedDeal
  - Golden tests: JSON snapshot regression
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from happybites.ingestion.base import RawDeal
from happybites.normalization.canons import (
    canonicalize_time,
    classify_deal_type,
    clean_text,
    compute_discount,
    detect_currency,
    expand_days,
    extract_merchant_from_block,
    merchant_slug,
    parse_price_range_str,
    parse_price_text,
)
from happybites.normalization.confidence import compute_confidence, compute_quality
from happybites.normalization.deduplicator import (
    deduplicate,
    make_deal_id,
    make_dedup_key,
)
from happybites.normalization.normalizer import normalize_deals
from happybites.normalization.schema import NormalizedDeal, Provenance
from happybites.scraping.schema import DealCandidate

# ── Fixtures ──────────────────────────────────────────────────────────────────

FIXED_TS = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
GOLDEN_PATH = Path(__file__).parent.parent / "data" / "golden" / "normalized_deals.json"


def make_provenance(source: str = "test_source") -> Provenance:
    return Provenance(source=source, ingest_run_id="run-test", last_seen=FIXED_TS)


def make_raw(
    source_deal_id: str = "deal-001",
    title: str = "Happy Hour at The Spotted Dog",
    url: str = "https://example.com/deal/1",
    description: str | None = "Mon-Fri 5-7pm. $6 drafts.",
    merchant: str | None = "The Spotted Dog",
    deal_price: float | None = None,
    original_price: float | None = None,
) -> RawDeal:
    return RawDeal(
        source_deal_id=source_deal_id,
        title=title,
        url=url,
        description=description,
        merchant=merchant,
        deal_price=deal_price,
        original_price=original_price,
    )


def make_candidate(
    deal_type: str = "happy_hour",
    price: float | None = None,
    price_range: str | None = None,
    items_included: list[str] | None = None,
    schedule_days: list[str] | None = None,
    start_time: str | None = "17:00",
    end_time: str | None = "19:00",
    restrictions: list[str] | None = None,
    confidence: float = 0.70,
    source_url: str = "https://example.com/blog",
    source_block_text: str = "The Rusty Anchor\nHappy hour Mon-Fri 5-7pm. $6 drafts.",
    extraction_method: str = "rule_based",
) -> DealCandidate:
    return DealCandidate(
        deal_type=deal_type,
        price=price,
        price_range=price_range,
        items_included=items_included or [],
        schedule_days=schedule_days or ["weekdays"],
        start_time=start_time,
        end_time=end_time,
        restrictions=restrictions or [],
        confidence=confidence,
        validation_errors=[],
        source_url=source_url,
        source_block_text=source_block_text,
        extraction_method=extraction_method,
    )


# ── canons: detect_currency ───────────────────────────────────────────────────


class TestDetectCurrency:
    def test_dollar_sign(self):
        assert detect_currency("$8 drinks") == "USD"

    def test_euro_sign(self):
        assert detect_currency("€12 wine") == "EUR"

    def test_pound_sign(self):
        assert detect_currency("£5 pints") == "GBP"

    def test_yen_sign(self):
        assert detect_currency("¥500 sake") == "JPY"

    def test_no_symbol_defaults_usd(self):
        assert detect_currency("8 dollars off") == "USD"

    def test_first_symbol_wins(self):
        assert detect_currency("$8 or €10") == "USD"


# ── canons: parse_price_text ──────────────────────────────────────────────────


class TestParsePriceText:
    def test_dollar_symbol(self):
        price, rng, currency = parse_price_text("$8 drafts")
        assert price == 8.0
        assert rng is None

    def test_dollar_with_cents(self):
        price, _, _ = parse_price_text("$8.50 per person")
        assert price == 8.50

    def test_word_dollars(self):
        price, _, _ = parse_price_text("8 dollars off")
        assert price == 8.0

    def test_word_bucks(self):
        price, _, _ = parse_price_text("only 12 bucks")
        assert price == 12.0

    def test_dollar_range(self):
        _, rng, _ = parse_price_text("$8-$12 per plate")
        assert rng == (8.0, 12.0)

    def test_dollar_range_swaps_order(self):
        _, rng, _ = parse_price_text("$12-$8 per plate")
        assert rng == (8.0, 12.0)

    def test_word_range(self):
        _, rng, _ = parse_price_text("8 to 12 dollars per person")
        assert rng == (8.0, 12.0)

    def test_under_prefix(self):
        _, rng, _ = parse_price_text("under $10 for happy hour")
        assert rng == (0.0, 10.0)

    def test_less_than_prefix(self):
        _, rng, _ = parse_price_text("less than $15 for the combo")
        assert rng == (0.0, 15.0)

    def test_free(self):
        price, rng, _ = parse_price_text("complimentary welcome drink")
        assert price == 0.0
        assert rng is None

    def test_free_keyword(self):
        price, _, _ = parse_price_text("Free appetizer with entree")
        assert price == 0.0

    def test_no_price_returns_none(self):
        price, rng, _ = parse_price_text("Happy hour on weekdays")
        assert price is None
        assert rng is None

    def test_time_range_not_mistaken_for_price(self):
        # "5-7pm" must not be parsed as a $5–$7 range
        price, rng, _ = parse_price_text("Open 5-7pm daily")
        assert rng is None

    def test_existing_price_fallback(self):
        price, rng, _ = parse_price_text("Happy hour", existing_price=9.99)
        assert price == 9.99
        assert rng is None

    def test_comma_thousands(self):
        price, _, _ = parse_price_text("$1,200 prix-fixe dinner")
        assert price == 1200.0


# ── canons: parse_price_range_str ────────────────────────────────────────────


class TestParsePriceRangeStr:
    def test_valid_range(self):
        assert parse_price_range_str("$8-$12") == (8.0, 12.0)

    def test_float_range(self):
        assert parse_price_range_str("$8.50-$12.75") == (8.50, 12.75)

    def test_swaps_order(self):
        assert parse_price_range_str("$12-$8") == (8.0, 12.0)

    def test_none_input(self):
        assert parse_price_range_str(None) is None

    def test_bad_format_returns_none(self):
        assert parse_price_range_str("8 to 12 dollars") is None

    def test_whitespace_stripped(self):
        assert parse_price_range_str("  $8-$12  ") == (8.0, 12.0)


# ── canons: compute_discount ─────────────────────────────────────────────────


class TestComputeDiscount:
    def test_basic(self):
        assert compute_discount(100.0, 75.0) == 25.0

    def test_none_original(self):
        assert compute_discount(None, 75.0) is None

    def test_none_deal(self):
        assert compute_discount(100.0, None) is None

    def test_deal_higher_than_original(self):
        assert compute_discount(50.0, 80.0) is None

    def test_zero_original(self):
        assert compute_discount(0.0, 0.0) is None

    def test_free_deal(self):
        assert compute_discount(20.0, 0.0) == 100.0


# ── canons: expand_days ───────────────────────────────────────────────────────


class TestExpandDays:
    def test_weekdays(self):
        assert expand_days(["weekdays"]) == [0, 1, 2, 3, 4]

    def test_weekends(self):
        assert expand_days(["weekends"]) == [5, 6]

    def test_daily(self):
        assert expand_days(["daily"]) == [0, 1, 2, 3, 4, 5, 6]

    def test_named_days(self):
        assert expand_days(["monday", "wednesday"]) == [0, 2]

    def test_mixed(self):
        assert expand_days(["weekdays", "saturday"]) == [0, 1, 2, 3, 4, 5]

    def test_empty(self):
        assert expand_days([]) == []

    def test_deduplication(self):
        # weekdays + monday → still [0,1,2,3,4]
        assert expand_days(["weekdays", "monday"]) == [0, 1, 2, 3, 4]

    def test_sorted(self):
        assert expand_days(["friday", "monday"]) == [0, 4]

    def test_case_insensitive(self):
        assert expand_days(["Monday", "FRIDAY"]) == [0, 4]


# ── canons: canonicalize_time ─────────────────────────────────────────────────


class TestCanonicalizeTime:
    def test_valid_time(self):
        assert canonicalize_time("17:00") == "17:00"

    def test_midnight(self):
        assert canonicalize_time("00:00") == "00:00"

    def test_invalid_format_returns_none(self):
        assert canonicalize_time("5pm") is None

    def test_none_returns_none(self):
        assert canonicalize_time(None) is None

    def test_partial_time_returns_none(self):
        assert canonicalize_time("17") is None


# ── canons: classify_deal_type ────────────────────────────────────────────────


class TestClassifyDealType:
    def test_existing_valid(self):
        assert classify_deal_type("happy_hour", "anything") == "happy_hour"

    def test_existing_invalid_falls_back(self):
        assert classify_deal_type("unknown_type", "Happy Hour special") == "happy_hour"

    def test_happy_hour_from_title(self):
        assert classify_deal_type(None, "Happy Hour 5-7pm") == "happy_hour"

    def test_lunch_special_from_title(self):
        assert classify_deal_type(None, "Lunch special available weekdays") == "lunch_special"

    def test_midday_special(self):
        assert classify_deal_type(None, "Midday special combo") == "lunch_special"

    def test_early_bird_from_title(self):
        assert classify_deal_type(None, "Early bird dinner") == "early_bird"

    def test_prix_fixe(self):
        assert classify_deal_type(None, "Prix-fixe tasting menu") == "prix_fixe"

    def test_dinner_special(self):
        assert classify_deal_type(None, "Dinner special every night") == "dinner_special"

    def test_falls_back_to_other(self):
        assert classify_deal_type(None, "Something random") == "other"

    def test_description_used_when_title_ambiguous(self):
        assert classify_deal_type(None, "Great deals", "Happy hour every evening") == "happy_hour"


# ── canons: clean_text ────────────────────────────────────────────────────────


class TestCleanText:
    def test_html_entities(self):
        assert clean_text("&amp;") == "&"

    def test_nbsp(self):
        result = clean_text("before\u00a0after")
        assert result == "before after"

    def test_unicode_dashes(self):
        result = clean_text("Mon\u2013Fri")  # en dash
        assert result == "Mon-Fri"

    def test_em_dash(self):
        result = clean_text("5\u20147pm")  # em dash
        assert " - " in result

    def test_strip_html_tags(self):
        result = clean_text("<b>Happy Hour</b>")
        assert "<b>" not in result
        assert "Happy Hour" in result

    def test_collapse_whitespace(self):
        result = clean_text("Happy   Hour   Deals")
        assert result == "Happy Hour Deals"

    def test_footnote_asterisks(self):
        result = clean_text("Drinks*  \n*see restrictions")
        assert result is not None
        assert "**" not in result

    def test_none_returns_none(self):
        assert clean_text(None) is None

    def test_empty_returns_none(self):
        assert clean_text("") is None

    def test_whitespace_only_returns_none(self):
        assert clean_text("   ") is None

    def test_unicode_quotes(self):
        result = clean_text("\u201cspecial\u201d")
        assert result == '"special"'


# ── canons: merchant_slug ─────────────────────────────────────────────────────


class TestMerchantSlug:
    def test_basic(self):
        assert merchant_slug("The Spotted Dog") == "the-spotted-dog"

    def test_special_chars(self):
        assert merchant_slug("O'Malley's Bar & Grill") == "o-malley-s-bar-grill"

    def test_empty_returns_empty(self):
        assert merchant_slug("") == ""

    def test_none_returns_empty(self):
        assert merchant_slug(None) == ""

    def test_leading_trailing_dashes_stripped(self):
        slug = merchant_slug(" - Foo - ")
        assert not slug.startswith("-")
        assert not slug.endswith("-")


# ── canons: extract_merchant_from_block ───────────────────────────────────────


class TestExtractMerchantFromBlock:
    def test_numbered_heading(self):
        result = extract_merchant_from_block("1. The Spotted Dog — Tribeca\nHappy hour 5-7pm")
        assert result == "The Spotted Dog"

    def test_bare_heading(self):
        result = extract_merchant_from_block("The Rusty Anchor\nHappy hour daily")
        assert result == "The Rusty Anchor"

    def test_no_number_with_neighbourhood(self):
        result = extract_merchant_from_block("Sullivan Street Bakery — SoHo\nLunch special")
        assert result is not None

    def test_too_short_returns_none(self):
        result = extract_merchant_from_block("Foo\nsome text")
        assert result is None

    def test_digit_leading_line_uses_regex(self):
        result = extract_merchant_from_block("3. Blue Smoke — Midtown\nDinner specials")
        assert result == "Blue Smoke"


# ── confidence: compute_confidence ───────────────────────────────────────────


class TestComputeConfidence:
    def test_raw_base(self):
        score = compute_confidence(
            "raw", None,
            has_price=False, has_schedule=False, has_time_window=False,
            has_items=False, validation_issues=[],
        )
        assert score == 0.5

    def test_llm_base_higher(self):
        score = compute_confidence(
            "llm", None,
            has_price=False, has_schedule=False, has_time_window=False,
            has_items=False, validation_issues=[],
        )
        assert score > 0.5

    def test_bonuses_add_up(self):
        base = compute_confidence(
            "raw", None,
            has_price=False, has_schedule=False, has_time_window=False,
            has_items=False, validation_issues=[],
        )
        full = compute_confidence(
            "raw", None,
            has_price=True, has_schedule=True, has_time_window=True,
            has_items=True, validation_issues=[],
        )
        assert full > base

    def test_issue_penalty(self):
        no_issues = compute_confidence(
            "rule_based", None,
            has_price=True, has_schedule=True, has_time_window=True,
            has_items=False, validation_issues=[],
        )
        with_issues = compute_confidence(
            "rule_based", None,
            has_price=True, has_schedule=True, has_time_window=True,
            has_items=False, validation_issues=["bad field", "another issue"],
        )
        assert with_issues < no_issues

    def test_clamped_to_one(self):
        score = compute_confidence(
            "llm", 1.0,
            has_price=True, has_schedule=True, has_time_window=True,
            has_items=True, validation_issues=[],
        )
        assert score <= 1.0

    def test_clamped_to_zero(self):
        score = compute_confidence(
            "raw", None,
            has_price=False, has_schedule=False, has_time_window=False,
            has_items=False, validation_issues=["x"] * 20,
        )
        assert score >= 0.0


# ── confidence: compute_quality ───────────────────────────────────────────────


class TestComputeQuality:
    def test_empty_deal(self):
        score = compute_quality(
            title=None, description=None, deal_type="other",
            price=None, price_range=None, original_price=None,
            items=[], days=[], start_time=None, end_time=None, merchant=None,
        )
        assert score == 0.0

    def test_full_deal(self):
        score = compute_quality(
            title="Happy Hour at The Spotted Dog",
            description="Drinks and snacks",
            deal_type="happy_hour",
            price=6.0,
            price_range=None,
            original_price=None,
            items=["draft beer", "wine"],
            days=[0, 1, 2, 3, 4],
            start_time="17:00",
            end_time="19:00",
            merchant="The Spotted Dog",
        )
        assert score > 0.8

    def test_partial_time(self):
        only_start = compute_quality(
            title="Deal title here", description=None, deal_type="other",
            price=None, price_range=None, original_price=None,
            items=[], days=[], start_time="17:00", end_time=None, merchant=None,
        )
        full_time = compute_quality(
            title="Deal title here", description=None, deal_type="other",
            price=None, price_range=None, original_price=None,
            items=[], days=[], start_time="17:00", end_time="19:00", merchant=None,
        )
        assert full_time > only_start

    def test_clamped_to_one(self):
        score = compute_quality(
            title="Happy Hour at The Spotted Dog Restaurant",
            description="Best deals in town",
            deal_type="happy_hour",
            price=6.0,
            price_range=None,
            original_price=10.0,
            items=["beer", "wine"],
            days=[0, 1, 2, 3, 4],
            start_time="17:00",
            end_time="19:00",
            merchant="The Spotted Dog",
        )
        assert score <= 1.0


# ── deduplicator: make_dedup_key ──────────────────────────────────────────────


class TestMakeDedupKey:
    def test_basic(self):
        key = make_dedup_key("spotted-dog", "happy_hour", [0, 1, 2, 3, 4], "17:00", "19:00")
        assert key == "spotted-dog|happy_hour|01234|17:00|19:00"

    def test_days_sorted(self):
        key1 = make_dedup_key("bar", "happy_hour", [4, 0, 2], "17:00", "19:00")
        key2 = make_dedup_key("bar", "happy_hour", [0, 2, 4], "17:00", "19:00")
        assert key1 == key2

    def test_none_times(self):
        key = make_dedup_key("bar", "other", [], None, None)
        assert key.endswith("||")

    def test_empty_merchant(self):
        key = make_dedup_key("", "other", [], None, None)
        assert key.startswith("|")


# ── deduplicator: deduplicate ─────────────────────────────────────────────────


def _make_normalized(
    deal_id: str = "abc",
    dedup_key: str = "spot|happy_hour|01234|17:00|19:00",
    confidence: float = 0.7,
    last_seen: datetime = FIXED_TS,
) -> NormalizedDeal:
    return NormalizedDeal(
        deal_id=deal_id,
        source_deal_id="src-001",
        title="Happy Hour",
        description=None,
        deal_type="happy_hour",
        merchant="Spot",
        currency="USD",
        price=6.0,
        price_range=None,
        original_price=None,
        discount_pct=None,
        days=[0, 1, 2, 3, 4],
        start_time="17:00",
        end_time="19:00",
        items_included=[],
        restrictions=[],
        source="test",
        source_url="https://example.com",
        last_seen=last_seen,
        ingest_run_id=None,
        confidence=confidence,
        quality_score=0.7,
        validation_issues=[],
        dedup_key=dedup_key,
    )


class TestDeduplicate:
    def test_no_duplicates_preserved(self):
        a = _make_normalized("a", "key1", 0.7)
        b = _make_normalized("b", "key2", 0.7)
        result = deduplicate([a, b])
        assert len(result) == 2

    def test_higher_confidence_wins(self):
        low = _make_normalized("low", "key1", 0.5)
        high = _make_normalized("high", "key1", 0.9)
        result = deduplicate([low, high])
        assert len(result) == 1
        assert result[0].deal_id == "high"

    def test_fresher_wins_on_tie(self):
        old = _make_normalized("old", "key1", 0.7, datetime(2024, 1, 1, tzinfo=timezone.utc))
        new = _make_normalized("new", "key1", 0.7, datetime(2024, 6, 1, tzinfo=timezone.utc))
        result = deduplicate([old, new])
        assert len(result) == 1
        assert result[0].deal_id == "new"

    def test_insertion_order_preserved(self):
        a = _make_normalized("a", "key1", 0.9)
        b = _make_normalized("b", "key2", 0.9)
        c = _make_normalized("c", "key3", 0.9)
        result = deduplicate([a, b, c])
        assert [r.deal_id for r in result] == ["a", "b", "c"]

    def test_empty_list(self):
        assert deduplicate([]) == []

    def test_three_way_dedup(self):
        a = _make_normalized("a", "key1", 0.5)
        b = _make_normalized("b", "key1", 0.9)
        c = _make_normalized("c", "key1", 0.7)
        result = deduplicate([a, b, c])
        assert len(result) == 1
        assert result[0].deal_id == "b"


# ── deduplicator: make_deal_id ────────────────────────────────────────────────


class TestMakeDealId:
    def test_length(self):
        assert len(make_deal_id("source", "deal-001")) == 16

    def test_hex_chars(self):
        did = make_deal_id("source", "deal-001")
        assert all(c in "0123456789abcdef" for c in did)

    def test_deterministic(self):
        assert make_deal_id("src", "id") == make_deal_id("src", "id")

    def test_different_inputs_differ(self):
        assert make_deal_id("src1", "id") != make_deal_id("src2", "id")


# ── normalizer: normalize_deals with RawDeal ─────────────────────────────────


class TestNormalizeRawDeal:
    def test_basic_happy_hour(self):
        raw = make_raw(description="Mon-Fri 5-7pm. $6 drafts.")
        prov = make_provenance("test_source")
        deals = normalize_deals([raw], prov)
        assert len(deals) == 1
        d = deals[0]
        assert d.deal_type == "happy_hour"
        assert d.days == [0, 1, 2, 3, 4]
        assert d.start_time == "17:00"
        assert d.end_time == "19:00"
        assert d.price == 6.0
        assert d.source == "test_source"
        assert d.merchant == "The Spotted Dog"

    def test_provenance_applied(self):
        raw = make_raw()
        prov = make_provenance("my_source")
        deals = normalize_deals([raw], prov)
        d = deals[0]
        assert d.source == "my_source"
        assert d.ingest_run_id == "run-test"
        assert d.last_seen == FIXED_TS

    def test_deal_id_is_hex16(self):
        raw = make_raw()
        prov = make_provenance()
        deals = normalize_deals([raw], prov)
        did = deals[0].deal_id
        assert len(did) == 16
        assert all(c in "0123456789abcdef" for c in did)

    def test_dedup_key_set(self):
        raw = make_raw()
        prov = make_provenance()
        deals = normalize_deals([raw], prov)
        assert "|" in deals[0].dedup_key

    def test_confidence_in_range(self):
        raw = make_raw()
        prov = make_provenance()
        deals = normalize_deals([raw], prov)
        assert 0.0 <= deals[0].confidence <= 1.0

    def test_quality_in_range(self):
        raw = make_raw()
        prov = make_provenance()
        deals = normalize_deals([raw], prov)
        assert 0.0 <= deals[0].quality_score <= 1.0

    def test_url_preserved(self):
        raw = make_raw(url="https://example.com/my-deal")
        prov = make_provenance()
        deals = normalize_deals([raw], prov)
        assert deals[0].source_url == "https://example.com/my-deal"

    def test_price_from_connector_field(self):
        # When text parsing finds nothing, fall back to deal_price
        raw = make_raw(title="Specials available", description=None, deal_price=9.99)
        prov = make_provenance()
        deals = normalize_deals([raw], prov)
        assert deals[0].price == 9.99

    def test_discount_computed(self):
        raw = make_raw(description="$8 drafts", deal_price=8.0, original_price=12.0)
        prov = make_provenance()
        deals = normalize_deals([raw], prov)
        d = deals[0]
        assert d.discount_pct is not None
        assert d.discount_pct > 0

    def test_text_cleaned(self):
        raw = make_raw(title="Happy &amp; Hour")
        prov = make_provenance()
        deals = normalize_deals([raw], prov)
        assert "&amp;" not in deals[0].title
        assert "&" in deals[0].title

    def test_default_provenance(self):
        raw = make_raw()
        deals = normalize_deals([raw])
        assert deals[0].source == "unknown"

    def test_dedup_collapses_duplicates(self):
        # Two identical deals (same merchant+type+schedule) → one output
        raw1 = make_raw(source_deal_id="d1", description="Mon-Fri 5-7pm. $6 drafts.")
        raw2 = make_raw(source_deal_id="d2", description="Mon-Fri 5-7pm. $6 drafts.")
        prov = make_provenance()
        deals = normalize_deals([raw1, raw2], prov)
        assert len(deals) == 1

    def test_dedup_false_keeps_all(self):
        raw1 = make_raw(source_deal_id="d1", description="Mon-Fri 5-7pm. $6 drafts.")
        raw2 = make_raw(source_deal_id="d2", description="Mon-Fri 5-7pm. $6 drafts.")
        prov = make_provenance()
        deals = normalize_deals([raw1, raw2], prov, dedup=False)
        assert len(deals) == 2

    def test_invalid_type_raises(self):
        with pytest.raises(TypeError):
            normalize_deals(["not-a-deal"])  # type: ignore[list-item]


# ── normalizer: normalize_deals with DealCandidate ────────────────────────────


class TestNormalizeCandidate:
    def test_basic_candidate(self):
        c = make_candidate()
        prov = make_provenance("blog_source")
        deals = normalize_deals([c], prov)
        assert len(deals) == 1
        d = deals[0]
        assert d.deal_type == "happy_hour"
        assert d.days == [0, 1, 2, 3, 4]
        assert d.start_time == "17:00"
        assert d.end_time == "19:00"

    def test_price_range_parsed(self):
        c = make_candidate(price_range="$8-$12", start_time=None, end_time=None)
        prov = make_provenance()
        deals = normalize_deals([c], prov)
        d = deals[0]
        assert d.price_range == (8.0, 12.0)
        assert d.price is None

    def test_items_preserved(self):
        c = make_candidate(items_included=["draft beer", "well drinks"])
        prov = make_provenance()
        deals = normalize_deals([c], prov)
        assert deals[0].items_included == ["draft beer", "well drinks"]

    def test_restrictions_preserved(self):
        c = make_candidate(restrictions=["dine-in only"])
        prov = make_provenance()
        deals = normalize_deals([c], prov)
        assert deals[0].restrictions == ["dine-in only"]

    def test_merchant_extracted_from_block(self):
        c = make_candidate(
            source_block_text="1. The Blue Moon — Tribeca\nHappy hour Mon-Fri 5-7pm"
        )
        prov = make_provenance()
        deals = normalize_deals([c], prov)
        assert deals[0].merchant == "The Blue Moon"

    def test_llm_extraction_method(self):
        c = make_candidate(extraction_method="llm", confidence=0.90)
        prov = make_provenance()
        deals = normalize_deals([c], prov)
        d = deals[0]
        # LLM base is 0.80; with high existing confidence, score should be reasonable
        assert d.confidence > 0.5

    def test_validation_errors_propagated(self):
        c = make_candidate()
        c.validation_errors = ["start_time missing"]
        prov = make_provenance()
        deals = normalize_deals([c], prov)
        assert "start_time missing" in deals[0].validation_issues

    def test_weekend_days(self):
        c = make_candidate(schedule_days=["weekends"], start_time=None, end_time=None)
        prov = make_provenance()
        deals = normalize_deals([c], prov)
        assert deals[0].days == [5, 6]

    def test_daily_days(self):
        c = make_candidate(schedule_days=["daily"], start_time=None, end_time=None)
        prov = make_provenance()
        deals = normalize_deals([c], prov)
        assert deals[0].days == [0, 1, 2, 3, 4, 5, 6]

    def test_to_dict_serializable(self):
        c = make_candidate()
        prov = make_provenance()
        deals = normalize_deals([c], prov)
        d_dict = deals[0].to_dict()
        # Should be JSON-serializable
        json.dumps(d_dict)
        assert d_dict["price_range"] is None or isinstance(d_dict["price_range"], list)

    def test_to_dict_with_price_range(self):
        c = make_candidate(price_range="$8-$12", start_time=None, end_time=None)
        prov = make_provenance()
        deals = normalize_deals([c], prov)
        d_dict = deals[0].to_dict()
        assert isinstance(d_dict["price_range"], list)
        assert len(d_dict["price_range"]) == 2


# ── normalizer: mixed input list ──────────────────────────────────────────────


class TestNormalizeMixed:
    def test_mixed_raw_and_candidate(self):
        raw = make_raw(source_deal_id="raw-001", description="Lunch special weekdays")
        cand = make_candidate(deal_type="lunch_special", schedule_days=["weekdays"])
        prov = make_provenance()
        deals = normalize_deals([raw, cand], prov, dedup=False)
        assert len(deals) == 2
        types = {d.deal_type for d in deals}
        assert "lunch_special" in types


# ── Golden tests ──────────────────────────────────────────────────────────────


def _build_golden_input() -> tuple[list[RawDeal | DealCandidate], Provenance]:
    """Canonical set of inputs used for golden snapshot."""
    prov = Provenance(
        source="golden_test",
        ingest_run_id="run-golden",
        last_seen=FIXED_TS,
    )
    raw1 = RawDeal(
        source_deal_id="raw-g01",
        title="Happy Hour at Blue Smoke",
        url="https://example.com/blue-smoke",
        description="Mon-Fri 5-7pm. $6 draft beer.",
        merchant="Blue Smoke",
    )
    raw2 = RawDeal(
        source_deal_id="raw-g02",
        title="Lunch Special",
        url="https://example.com/lunch",
        description="Weekdays 11am-3pm. Under $15.",
        merchant="Café Central",
    )
    cand1 = DealCandidate(
        deal_type="early_bird",
        price=29.0,
        price_range=None,
        items_included=["soup", "salad", "entree"],
        schedule_days=["daily"],
        start_time="17:00",
        end_time="18:30",
        restrictions=["dine-in only"],
        confidence=0.80,
        validation_errors=[],
        source_url="https://example.com/menu",
        source_block_text="The Anchor — Tribeca\nEarly bird daily 5-6:30pm. $29 prix-fixe.",
        extraction_method="rule_based",
    )
    return [raw1, raw2, cand1], prov


class TestGolden:
    def test_golden_snapshot(self):
        """Compare normalized output to committed golden snapshot.

        Re-generate with: REGEN_GOLDEN=1 pytest tests/test_normalization.py::TestGolden
        """
        inputs, prov = _build_golden_input()
        deals = normalize_deals(inputs, prov, dedup=True)
        actual = [d.to_dict() for d in deals]

        if os.environ.get("REGEN_GOLDEN"):
            GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN_PATH.write_text(json.dumps(actual, indent=2, default=str))
            pytest.skip("Golden file regenerated — rerun tests to validate")

        if not GOLDEN_PATH.exists():
            pytest.skip(
                f"Golden file not found at {GOLDEN_PATH}. "
                "Run with REGEN_GOLDEN=1 to generate it."
            )

        expected = json.loads(GOLDEN_PATH.read_text())
        assert actual == expected, (
            "Normalized output does not match golden snapshot. "
            "If this change is intentional, regenerate with REGEN_GOLDEN=1."
        )
