"""Claude-powered deal normalization with regex fallback."""

import json
import re
from datetime import datetime, timezone

import structlog

from happybites.config import settings
from happybites.ingestion.base import RawDeal

logger = structlog.get_logger(__name__)

VALID_CATEGORIES = [
    "Electronics",
    "Food & Dining",
    "Fashion",
    "Home & Garden",
    "Travel",
    "Entertainment",
    "Health & Beauty",
    "Sports & Outdoors",
    "Automotive",
    "Other",
]

NORMALIZATION_PROMPT = """\
You are a deal data normalizer. Extract structured information from the deal below.

Return ONLY a valid JSON object with these exact fields (no explanation, no markdown):
{{
  "category": "<one of: {categories}>",
  "tags": ["<1-5 lowercase keyword strings>"],
  "merchant": "<store or brand name, or null>",
  "original_price": <float or null>,
  "deal_price": <float or null>,
  "expires_at": "<ISO 8601 UTC datetime string or null>",
  "quality_score": <float 0.0-1.0, where 1.0 means all fields are present and the deal is genuine>
}}

Deal title: {title}
Deal description: {description}
Deal URL: {url}
""".strip()


def _regex_normalize(raw: RawDeal) -> dict:
    """Best-effort regex extraction when Claude is unavailable."""
    price_re = re.compile(r"\$([0-9]+(?:\.[0-9]{1,2})?)")
    prices = [float(m) for m in price_re.findall(raw.title + " " + (raw.description or ""))]

    deal_price = raw.deal_price or (min(prices) if prices else None)
    original_price = raw.original_price or (max(prices) if len(prices) > 1 else None)

    # Rough category from keywords
    text = (raw.title + " " + (raw.description or "")).lower()
    category = "Other"
    kw_map = {
        "Electronics": ["laptop", "phone", "tv", "monitor", "headphone", "camera", "tablet"],
        "Food & Dining": ["food", "restaurant", "pizza", "burger", "coffee", "meal", "delivery"],
        "Fashion": ["shirt", "shoe", "dress", "jacket", "jeans", "clothing", "apparel"],
        "Home & Garden": ["furniture", "mattress", "kitchen", "garden", "home", "appliance"],
        "Travel": ["flight", "hotel", "airline", "vacation", "cruise", "airbnb"],
        "Health & Beauty": ["vitamin", "skincare", "gym", "fitness", "supplement", "beauty"],
        "Sports & Outdoors": ["bike", "hiking", "camping", "sport", "outdoor", "running"],
        "Entertainment": ["game", "movie", "streaming", "concert", "ticket", "book"],
    }
    for cat, keywords in kw_map.items():
        if any(kw in text for kw in keywords):
            category = cat
            break

    quality = 0.4  # base for regex fallback
    if deal_price:
        quality += 0.2
    if original_price:
        quality += 0.2
    if raw.description:
        quality += 0.1
    if raw.merchant:
        quality += 0.1

    return {
        "category": category,
        "tags": [],
        "merchant": raw.merchant,
        "original_price": original_price,
        "deal_price": deal_price,
        "expires_at": raw.expires_at.isoformat() if raw.expires_at else None,
        "quality_score": round(quality, 2),
    }


def _parse_response(text: str) -> dict | None:
    """Extract JSON from a Claude response string."""
    try:
        # Strip any accidental markdown fences
        clean = re.sub(r"```(?:json)?|```", "", text).strip()
        return json.loads(clean)
    except (json.JSONDecodeError, ValueError):
        return None


def _compute_discount(original: float | None, deal: float | None) -> float | None:
    if original and deal and original > 0 and deal < original:
        return round((original - deal) / original * 100, 2)
    return None


class Normalizer:
    """
    Normalizes RawDeal records into structured fields.

    Uses Claude when available; falls back to regex extraction.
    All calls are logged to NormalizationLog for auditability.
    """

    def __init__(self):
        self._client = None
        if settings.anthropic_api_key:
            try:
                import anthropic

                self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            except ImportError:
                logger.warning("anthropic_not_installed", fallback="regex")

    @property
    def ai_enabled(self) -> bool:
        return self._client is not None

    def normalize(self, raw: RawDeal) -> tuple[dict, bool]:
        """
        Returns (normalized_fields, fallback_used).

        normalized_fields keys: category, tags, merchant, original_price,
        deal_price, expires_at, quality_score, discount_pct
        """
        fallback_used = False

        if self.ai_enabled:
            result = self._normalize_with_claude(raw)
            if result is None:
                fallback_used = True
                result = _regex_normalize(raw)
        else:
            fallback_used = True
            result = _regex_normalize(raw)

        # Ensure prices from raw source are preferred if Claude returns null
        if not result.get("original_price") and raw.original_price:
            result["original_price"] = raw.original_price
        if not result.get("deal_price") and raw.deal_price:
            result["deal_price"] = raw.deal_price

        result["discount_pct"] = _compute_discount(
            result.get("original_price"), result.get("deal_price")
        )

        return result, fallback_used

    def _normalize_with_claude(self, raw: RawDeal) -> dict | None:
        log = logger.bind(source_deal_id=raw.source_deal_id)
        prompt = NORMALIZATION_PROMPT.format(
            categories=", ".join(VALID_CATEGORIES),
            title=raw.title,
            description=(raw.description or "")[:500],
            url=raw.url,
        )
        try:
            message = self._client.messages.create(
                model=settings.claude_model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            text = message.content[0].text
            result = _parse_response(text)
            if result is None:
                log.warning("claude_parse_failed", response_preview=text[:200])
                return None

            # Store token counts for provenance (attached by caller)
            result["_prompt_tokens"] = message.usage.input_tokens
            result["_completion_tokens"] = message.usage.output_tokens
            result["_model"] = settings.claude_model
            result["_raw_response"] = text

            return result

        except Exception as exc:
            log.error("claude_error", error=str(exc))
            return None
