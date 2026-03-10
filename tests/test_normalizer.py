"""Tests for deal normalization — Claude mocked, regex fallback exercised."""

from unittest.mock import MagicMock, patch

import pytest

from happybites.ingestion.base import RawDeal
from happybites.ingestion.normalizer import Normalizer, _compute_discount, _regex_normalize


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_raw(
    title="Apple AirPods Pro - $189.99 (was $249.99)",
    description="Great headphones on sale.",
    url="https://example.com/deal/1",
    **kwargs,
) -> RawDeal:
    return RawDeal(
        source_deal_id="test-001",
        title=title,
        url=url,
        description=description,
        **kwargs,
    )


# ── Discount computation ──────────────────────────────────────────────────────


def test_compute_discount_basic():
    assert _compute_discount(100.0, 75.0) == 25.0


def test_compute_discount_none_inputs():
    assert _compute_discount(None, 50.0) is None
    assert _compute_discount(100.0, None) is None


def test_compute_discount_deal_higher_than_original():
    # Deal price higher than original — no discount
    assert _compute_discount(50.0, 80.0) is None


# ── Regex fallback ────────────────────────────────────────────────────────────


def test_regex_normalize_extracts_prices():
    raw = make_raw(
        title="Sony WH-1000XM5 - $279.99 (was $399.99)",
        original_price=399.99,
        deal_price=279.99,
    )
    result = _regex_normalize(raw)
    assert result["deal_price"] == 279.99
    assert result["original_price"] == 399.99


def test_regex_normalize_assigns_category():
    raw = make_raw(title="MacBook Pro 14-inch laptop on sale")
    result = _regex_normalize(raw)
    assert result["category"] == "Electronics"


def test_regex_normalize_food_category():
    raw = make_raw(title="$5 off pizza delivery at Domino's")
    result = _regex_normalize(raw)
    assert result["category"] == "Food & Dining"


def test_regex_normalize_quality_score_range():
    raw = make_raw()
    result = _regex_normalize(raw)
    assert 0.0 <= result["quality_score"] <= 1.0


# ── Normalizer with mocked Claude ────────────────────────────────────────────


def _mock_claude_response(json_text: str):
    """Build a fake Anthropic messages.create response."""
    msg = MagicMock()
    msg.content = [MagicMock(text=json_text)]
    msg.usage.input_tokens = 120
    msg.usage.output_tokens = 80
    return msg


MOCK_CLAUDE_FIELDS = {
    "category": "Electronics",
    "tags": ["headphones", "apple", "wireless"],
    "merchant": "Amazon",
    "original_price": 249.99,
    "deal_price": 189.99,
    "expires_at": None,
    "quality_score": 0.92,
}


def test_normalizer_uses_claude_when_available():
    import json

    with patch("happybites.ingestion.normalizer.settings") as mock_settings:
        mock_settings.anthropic_api_key = "sk-test"
        mock_settings.claude_model = "claude-sonnet-4-6"
        with patch("anthropic.Anthropic") as MockAnthropicCls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _mock_claude_response(
                json.dumps(MOCK_CLAUDE_FIELDS)
            )
            MockAnthropicCls.return_value = mock_client

            normalizer = Normalizer()
            normalizer._client = mock_client

            raw = make_raw()
            fields, fallback_used = normalizer.normalize(raw)

    assert not fallback_used
    assert fields["category"] == "Electronics"
    assert fields["quality_score"] == 0.92
    assert fields["discount_pct"] is not None


def test_normalizer_falls_back_on_claude_error():
    normalizer = Normalizer()
    normalizer._client = MagicMock()
    normalizer._client.messages.create.side_effect = Exception("API unavailable")

    raw = make_raw()
    fields, fallback_used = normalizer.normalize(raw)

    assert fallback_used
    assert "category" in fields
    assert 0.0 <= fields["quality_score"] <= 1.0


def test_normalizer_no_api_key_uses_regex():
    with patch("happybites.ingestion.normalizer.settings") as mock_settings:
        mock_settings.anthropic_api_key = ""
        normalizer = Normalizer()

    raw = make_raw()
    fields, fallback_used = normalizer.normalize(raw)

    assert fallback_used
    assert "category" in fields
