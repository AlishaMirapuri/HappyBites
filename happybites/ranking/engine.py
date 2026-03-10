"""
Ranking engine for HappyBites deals.

Each deal is scored across 7 features:

  Feature              Weight   Signal
  ─────────────────────────────────────────────────────────────────────────────
  deal_value           0.25     discount_pct / 100  (linear, capped at 1.0)
  open_now             0.20     1.0 open / 0.5 unknown / 0.0 closed
  freshness            0.15     exp(-age_hours / halflife_hours)
  distance             0.20     exp(-distance_miles / decay_miles) or 0.5 if unknown
  confidence           0.10     max(quality_score, confidence) normalised to 0–1
  venue_popularity     0.05     log1p(source_count) / log1p(10)
  preference_boost     0.05     1.0 if category/deal_type in user prefs, else 0.0

  Final score = Σ weight_i × feature_i   (always in [0, 1])

Top reasons are generated from the 3 highest-contributing features (after
weighting) and returned alongside a per-feature debug dict.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ── Config ─────────────────────────────────────────────────────────────────────


@dataclass
class RankingConfig:
    """Tunable weights and decay parameters."""

    # Weights (must sum to 1.0 for interpretable scores, but not enforced)
    w_deal_value: float = 0.25
    w_open_now: float = 0.20
    w_freshness: float = 0.15
    w_distance: float = 0.20
    w_confidence: float = 0.10
    w_venue_popularity: float = 0.05
    w_preference_boost: float = 0.05

    # Decay parameters
    freshness_halflife_hours: float = 48.0   # exp(-age/48) → 50% at 2 days
    distance_decay_miles: float = 2.0        # exp(-d/2) → 50% at ~1.4 mi


# Singleton default config — callers can override
DEFAULT_CONFIG = RankingConfig()


# ── Inputs ─────────────────────────────────────────────────────────────────────


@dataclass
class ScoreInput:
    """All inputs required to score one deal. Pure data — no DB access."""

    deal_id: int
    discount_pct: float | None
    fetched_at: datetime
    last_seen_at: datetime | None = None
    quality_score: float | None = None
    confidence: float | None = None
    category: str | None = None
    deal_type: str | None = None
    is_open_now: bool | None = None          # pre-computed; None = unknown
    distance_miles: float | None = None      # None = no location data
    venue_source_count: int = 1              # proxy for venue popularity
    preferred_categories: list[str] = field(default_factory=list)
    preferred_deal_types: list[str] = field(default_factory=list)
    now: datetime | None = None              # override for testing


# ── Output ─────────────────────────────────────────────────────────────────────


@dataclass
class RankResult:
    """Scored result for one deal."""

    deal_id: int
    score: float                  # 0.0–1.0
    reasons: list[str]            # top 3 human-readable explanations
    debug: dict[str, float]       # per-feature weighted contributions


# ── Core scorer ────────────────────────────────────────────────────────────────


def score_deal(inp: ScoreInput, config: RankingConfig = DEFAULT_CONFIG) -> RankResult:
    """Pure function — score a single deal against a user context.

    All inputs must be provided by the caller (no DB access).
    Pass `inp.now` in tests to freeze time.
    """
    now = inp.now or datetime.now(timezone.utc)

    # ── Feature: deal_value ───────────────────────────────────────────────────
    deal_value = min((inp.discount_pct or 0.0) / 100.0, 1.0)

    # ── Feature: open_now ─────────────────────────────────────────────────────
    if inp.is_open_now is True:
        open_now = 1.0
    elif inp.is_open_now is False:
        open_now = 0.0
    else:
        open_now = 0.5   # no schedule info → neutral

    # ── Feature: freshness ────────────────────────────────────────────────────
    reference_time = inp.last_seen_at or inp.fetched_at
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - reference_time).total_seconds() / 3600)
    freshness = math.exp(-age_hours / config.freshness_halflife_hours)

    # ── Feature: distance ─────────────────────────────────────────────────────
    if inp.distance_miles is not None:
        distance = math.exp(-inp.distance_miles / config.distance_decay_miles)
    else:
        distance = 0.5   # no location data → neutral

    # ── Feature: confidence ───────────────────────────────────────────────────
    confidence_score = max(
        inp.quality_score if inp.quality_score is not None else 0.0,
        inp.confidence if inp.confidence is not None else 0.0,
    )

    # ── Feature: venue_popularity ─────────────────────────────────────────────
    # log1p scale: 1 source→0, 2→0.43, 5→0.78, 10→1.0 (capped)
    venue_pop = min(math.log1p(inp.venue_source_count) / math.log1p(10), 1.0)

    # ── Feature: preference_boost ─────────────────────────────────────────────
    pref = 0.0
    if inp.category and inp.preferred_categories:
        if inp.category.lower() in [c.lower() for c in inp.preferred_categories]:
            pref = 1.0
    if pref == 0.0 and inp.deal_type and inp.preferred_deal_types:
        if inp.deal_type.lower() in [d.lower() for d in inp.preferred_deal_types]:
            pref = 1.0

    # ── Weighted sum ──────────────────────────────────────────────────────────
    weighted: dict[str, float] = {
        "deal_value":        config.w_deal_value * deal_value,
        "open_now":          config.w_open_now * open_now,
        "freshness":         config.w_freshness * freshness,
        "distance":          config.w_distance * distance,
        "confidence":        config.w_confidence * confidence_score,
        "venue_popularity":  config.w_venue_popularity * venue_pop,
        "preference_boost":  config.w_preference_boost * pref,
    }
    score = round(min(sum(weighted.values()), 1.0), 4)

    # ── Reason generation ─────────────────────────────────────────────────────
    raw: dict[str, tuple[float, float]] = {
        "deal_value":       (deal_value, config.w_deal_value),
        "open_now":         (open_now, config.w_open_now),
        "freshness":        (freshness, config.w_freshness),
        "distance":         (distance, config.w_distance),
        "confidence":       (confidence_score, config.w_confidence),
        "venue_popularity": (venue_pop, config.w_venue_popularity),
        "preference_boost": (pref, config.w_preference_boost),
    }
    # Sort by weighted contribution descending; pick top 3 with meaningful signal
    top = sorted(weighted.items(), key=lambda kv: kv[1], reverse=True)
    reasons: list[str] = []
    for feat, contrib in top:
        feat_val, _ = raw[feat]
        msg = _reason_text(feat, feat_val, inp)
        if msg:
            reasons.append(msg)
        if len(reasons) == 3:
            break

    return RankResult(deal_id=inp.deal_id, score=score, reasons=reasons, debug=weighted)


# ── Reason text helpers ────────────────────────────────────────────────────────


def _reason_text(feature: str, value: float, inp: ScoreInput) -> str | None:
    """Return a human-readable reason string, or None if the signal is neutral."""
    if feature == "deal_value":
        if inp.discount_pct and inp.discount_pct >= 10:
            return f"{inp.discount_pct:.0f}% discount"
        return None

    if feature == "open_now":
        if value == 1.0:
            return "Open now"
        if value == 0.0:
            return None  # closed deals shouldn't appear as positive reasons
        return None  # unknown — skip

    if feature == "freshness":
        if value >= 0.9:
            return "Posted in the last few hours"
        if value >= 0.5:
            return "Posted recently"
        if value < 0.25:
            return None  # stale — not a positive reason
        return "Posted this week"

    if feature == "distance":
        if inp.distance_miles is None:
            return None
        if inp.distance_miles < 0.25:
            return f"{inp.distance_miles * 5280:.0f} ft away"
        return f"{inp.distance_miles:.1f} mi away"

    if feature == "confidence":
        if value >= 0.8:
            return "High quality listing"
        return None

    if feature == "venue_popularity":
        if inp.venue_source_count >= 3:
            return f"Listed on {inp.venue_source_count} sources"
        return None

    if feature == "preference_boost":
        if value == 1.0:
            if inp.category:
                return f"Matches your preference: {inp.category}"
            if inp.deal_type:
                return f"Matches your preference: {inp.deal_type}"
        return None

    return None
