"""Main entry point for the normalization layer.

Accepts RawDeal (from connectors) and DealCandidate (from scrapers) and
converts them into NormalizedDeal objects with canonical fields, confidence
scores, and dedup keys.

Usage::

    from happybites.normalization.normalizer import normalize_deals
    from happybites.normalization.schema import Provenance

    prov = Provenance(source="menu_page", ingest_run_id="run-001")
    deals = normalize_deals(raw_deals + candidates, prov)
"""

from __future__ import annotations

import hashlib

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
from happybites.normalization.deduplicator import deduplicate, make_deal_id, make_dedup_key
from happybites.normalization.schema import NormalizedDeal, Provenance
from happybites.scraping.schema import DealCandidate


def _content_hash(text: str) -> str:
    """Short hash used as source_deal_id when none is available."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _normalize_raw(raw: RawDeal, prov: Provenance) -> NormalizedDeal:
    """Normalize a RawDeal (from connectors) into a NormalizedDeal."""
    title = clean_text(raw.title) or raw.title
    description = clean_text(raw.description)
    merchant = clean_text(raw.merchant)

    deal_type = classify_deal_type(None, title, description)

    # Price: try to parse from description text, fall back to connector values
    combined_text = f"{title} {description or ''}"
    price, price_range, currency = parse_price_text(
        combined_text,
        existing_price=raw.deal_price,
        existing_original=raw.original_price,
    )
    # Use connector-provided price when text parsing found nothing
    if price is None and price_range is None and raw.deal_price is not None:
        price = raw.deal_price

    original_price = raw.original_price
    discount_pct = compute_discount(original_price, price)

    # Schedule: RawDeal has no structured schedule fields — try to parse from text
    from happybites.scraping.rule_extractor import _detect_days, _parse_time_range  # noqa: PLC0415

    days_list = _detect_days(combined_text)
    start_time, end_time = _parse_time_range(combined_text)

    # Expand canonical day names to integers
    days_int = expand_days(days_list)
    start_time = canonicalize_time(start_time)
    end_time = canonicalize_time(end_time)

    validation_issues: list[str] = []
    if price is not None and price_range is not None:
        validation_issues.append("both price and price_range set; using price")
        price_range = None

    confidence = compute_confidence(
        extraction_method="raw",
        existing_confidence=None,
        has_price=price is not None or price_range is not None,
        has_schedule=bool(days_int),
        has_time_window=bool(start_time or end_time),
        has_items=False,
        validation_issues=validation_issues,
    )
    quality = compute_quality(
        title=title,
        description=description,
        deal_type=deal_type,
        price=price,
        price_range=price_range,
        original_price=original_price,
        items=[],
        days=days_int,
        start_time=start_time,
        end_time=end_time,
        merchant=merchant,
    )

    source_deal_id = raw.source_deal_id
    deal_id = make_deal_id(prov.source, source_deal_id)
    slug = merchant_slug(merchant)
    dedup_key = make_dedup_key(slug, deal_type, days_int, start_time, end_time)

    return NormalizedDeal(
        deal_id=deal_id,
        source_deal_id=source_deal_id,
        title=title,
        description=description,
        deal_type=deal_type,
        merchant=merchant,
        currency=currency,
        price=price,
        price_range=price_range,
        original_price=original_price,
        discount_pct=discount_pct,
        days=days_int,
        start_time=start_time,
        end_time=end_time,
        items_included=[],
        restrictions=[],
        source=prov.source,
        source_url=raw.url,
        last_seen=prov.last_seen,
        ingest_run_id=prov.ingest_run_id,
        confidence=confidence,
        quality_score=quality,
        validation_issues=validation_issues,
        dedup_key=dedup_key,
    )


def _normalize_candidate(c: DealCandidate, prov: Provenance) -> NormalizedDeal:
    """Normalize a DealCandidate (from scrapers) into a NormalizedDeal."""
    title = clean_text(c.source_block_text)
    # Use first line as title, rest as description
    if title:
        lines = [l.strip() for l in title.splitlines() if l.strip()]
        title_str = lines[0] if lines else title
        description = "\n".join(lines[1:]) if len(lines) > 1 else None
    else:
        title_str = "(no title)"
        description = None

    merchant = extract_merchant_from_block(c.source_block_text)

    deal_type = classify_deal_type(c.deal_type, title_str, description)

    # Price from structured candidate fields
    price = c.price
    price_range = parse_price_range_str(c.price_range)
    if price is None and price_range is None:
        # Try to parse from block text as fallback
        p, pr, _ = parse_price_text(c.source_block_text)
        price, price_range = p, pr

    currency = detect_currency(c.source_block_text)
    original_price: float | None = None
    discount_pct = compute_discount(original_price, price)

    # Schedule: expand candidate's string days to int list
    days_int = expand_days(c.schedule_days)
    start_time = canonicalize_time(c.start_time)
    end_time = canonicalize_time(c.end_time)

    # Propagate candidate validation_errors as normalization issues
    validation_issues = list(c.validation_errors)

    confidence = compute_confidence(
        extraction_method=c.extraction_method,
        existing_confidence=c.confidence,
        has_price=price is not None or price_range is not None,
        has_schedule=bool(days_int),
        has_time_window=bool(start_time or end_time),
        has_items=bool(c.items_included),
        validation_issues=validation_issues,
    )
    quality = compute_quality(
        title=title_str,
        description=description,
        deal_type=deal_type,
        price=price,
        price_range=price_range,
        original_price=original_price,
        items=c.items_included,
        days=days_int,
        start_time=start_time,
        end_time=end_time,
        merchant=merchant,
    )

    source_deal_id = _content_hash(c.source_block_text)
    deal_id = make_deal_id(prov.source, source_deal_id)
    slug = merchant_slug(merchant)
    dedup_key = make_dedup_key(slug, deal_type, days_int, start_time, end_time)

    return NormalizedDeal(
        deal_id=deal_id,
        source_deal_id=source_deal_id,
        title=title_str,
        description=description,
        deal_type=deal_type,
        merchant=merchant,
        currency=currency,
        price=price,
        price_range=price_range,
        original_price=original_price,
        discount_pct=discount_pct,
        days=days_int,
        start_time=start_time,
        end_time=end_time,
        items_included=list(c.items_included),
        restrictions=list(c.restrictions),
        source=prov.source,
        source_url=c.source_url,
        last_seen=prov.last_seen,
        ingest_run_id=prov.ingest_run_id,
        confidence=confidence,
        quality_score=quality,
        validation_issues=validation_issues,
        dedup_key=dedup_key,
    )


def normalize_deals(
    raw_deals: list[RawDeal | DealCandidate],
    provenance: Provenance | None = None,
    *,
    dedup: bool = True,
) -> list[NormalizedDeal]:
    """Normalize a mixed list of RawDeal and DealCandidate objects.

    Args:
        raw_deals: Input deals from connectors or scrapers.
        provenance: Source metadata applied to all deals in this batch.
                    Defaults to Provenance(source="unknown").
        dedup: When True (default), collapse duplicates keeping the deal
               with highest confidence (ties broken by most-recent last_seen).

    Returns:
        List of NormalizedDeal objects, deduplicated when dedup=True.
    """
    prov = provenance or Provenance(source="unknown")
    results: list[NormalizedDeal] = []

    for item in raw_deals:
        if isinstance(item, RawDeal):
            results.append(_normalize_raw(item, prov))
        elif isinstance(item, DealCandidate):
            results.append(_normalize_candidate(item, prov))
        else:
            raise TypeError(f"Expected RawDeal or DealCandidate, got {type(item)!r}")

    if dedup:
        results = deduplicate(results)

    return results
