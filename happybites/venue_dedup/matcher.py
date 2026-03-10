"""Venue matching logic for entity resolution / deduplication.

Two venues are candidate duplicates when they share enough evidence across
name, address, phone, and geo-proximity.  Each signal contributes (positively
or negatively) to a single match_score in [0.0, 1.0].

Scoring table
─────────────
Signal                              delta
Phone exact match (both present)   +0.40
Phone mismatch (both present)      –0.30  (strong negative: different venue)
Name token-sort ratio ≥ 90         +0.35
Name token-sort ratio 70–90        +0.20
Name token-sort ratio 55–70        +0.10
Street match ratio ≥ 85            +0.20
Street match ratio 70–85           +0.10
Geo distance < 0.05 mi (≈ 80 m)    +0.25  (same building)
Geo distance 0.05–0.2 mi           +0.10
Geo distance 0.2–0.5 mi            +0.00  (neutral)
Geo distance > 0.5 mi              –0.15  (likely different location)

Chain collision flag
────────────────────
If name ratio ≥ 85 but geo distance > 0.5 mi, the pair is flagged as a
chain collision (same brand, different location) rather than a true duplicate.
The merge endpoint will refuse to merge chain collisions unless forced.

Thresholds
──────────
score ≥ 0.70  →  HIGH confidence  (auto-suggest merge)
0.40 ≤ score < 0.70  →  REVIEW   (show to admin)
score < 0.40  →  no match        (excluded from results)
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field

from rapidfuzz import fuzz

# ── Constants ─────────────────────────────────────────────────────────────────

_HIGH_CONFIDENCE = 0.70
_REVIEW_THRESHOLD = 0.30

# Regex for stripping non-digit chars from phone numbers
_NON_DIGIT = re.compile(r"\D")

# Words that don't discriminate between chains vs standalone venues
_STOP_WORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "of", "at", "by", "in", "on",
        "restaurant", "bar", "grill", "cafe", "bistro", "kitchen",
        "eatery", "pub", "lounge", "tavern", "house", "place",
    }
)


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class MatchReason:
    """One signal that contributed to the overall match score."""

    field: str          # "phone" | "name" | "street" | "geo"
    description: str    # human-readable explanation
    score_delta: float  # contribution (positive or negative)


@dataclass
class VenueSnapshot:
    """Minimal venue info needed for matching (DB-agnostic)."""

    id: int
    name: str
    address: str | None = None
    phone: str | None = None
    lat: float | None = None
    lon: float | None = None
    city_id: int | None = None
    source_count: int = 1           # how many source mappings this venue has
    extra: dict = field(default_factory=dict)  # arbitrary caller data


@dataclass
class MatchResult:
    """Result of comparing two venue candidates."""

    venue_a: VenueSnapshot
    venue_b: VenueSnapshot
    match_score: float              # 0.0–1.0
    confidence: str                 # "high" | "review"
    reasons: list[MatchReason]
    fields_used: list[str]          # ordered list of fields that had signal
    is_chain_collision: bool = False  # same brand, different location


# ── Normalisation helpers ─────────────────────────────────────────────────────


def _normalize_phone(raw: str | None) -> str | None:
    """Reduce a phone string to the last 10 digits (US) or None."""
    if not raw:
        return None
    digits = _NON_DIGIT.sub("", raw)
    # Strip country code for US numbers
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) >= 7 else None


def _normalize_name(name: str) -> str:
    """Lowercase, NFD-normalize, strip punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFD", name.lower())
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _significant_tokens(name: str) -> set[str]:
    """Return name tokens minus common stop words (for chain detection)."""
    return {t for t in _normalize_name(name).split() if t not in _STOP_WORDS}


def _extract_street(address: str | None) -> str | None:
    """Return the street portion of an address (everything before the first comma)."""
    if not address:
        return None
    street = address.split(",")[0].strip()
    # Normalize street suffixes
    street = re.sub(r"\bSt\.?\b", "Street", street, flags=re.IGNORECASE)
    street = re.sub(r"\bAve\.?\b", "Avenue", street, flags=re.IGNORECASE)
    street = re.sub(r"\bBlvd\.?\b", "Boulevard", street, flags=re.IGNORECASE)
    street = re.sub(r"\bDr\.?\b", "Drive", street, flags=re.IGNORECASE)
    street = re.sub(r"\bRd\.?\b", "Road", street, flags=re.IGNORECASE)
    return street.lower().strip()


# ── Geo helpers ───────────────────────────────────────────────────────────────

_EARTH_RADIUS_MILES = 3_958.8


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points in miles."""
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return _EARTH_RADIUS_MILES * 2 * math.asin(math.sqrt(a))


# ── Core matcher ──────────────────────────────────────────────────────────────


def match_venues(a: VenueSnapshot, b: VenueSnapshot) -> MatchResult | None:
    """Compare two venue snapshots and return a MatchResult, or None if below threshold.

    Returns None when the computed score is below _REVIEW_THRESHOLD (0.40)
    so callers can quickly skip non-candidates.
    """
    score = 0.0
    reasons: list[MatchReason] = []
    fields_used: list[str] = []
    is_chain_collision = False

    # ── Phone signal ──────────────────────────────────────────────────────────
    phone_a = _normalize_phone(a.phone)
    phone_b = _normalize_phone(b.phone)

    if phone_a and phone_b:
        fields_used.append("phone")
        if phone_a == phone_b:
            delta = 0.40
            score += delta
            reasons.append(MatchReason("phone", f"Phone numbers match ({phone_a})", delta))
        else:
            delta = -0.30
            score += delta
            reasons.append(
                MatchReason(
                    "phone",
                    f"Phone numbers differ ({phone_a} vs {phone_b})",
                    delta,
                )
            )

    # ── Name signal ───────────────────────────────────────────────────────────
    name_a_norm = _normalize_name(a.name)
    name_b_norm = _normalize_name(b.name)

    # token_sort_ratio handles word-order variations ("Joe's Bar" vs "Bar Joe's")
    name_ratio = fuzz.token_sort_ratio(name_a_norm, name_b_norm)
    fields_used.append("name")

    if name_ratio >= 90:
        delta = 0.35
        score += delta
        reasons.append(
            MatchReason("name", f"Names nearly identical (similarity {name_ratio}%)", delta)
        )
    elif name_ratio >= 70:
        delta = 0.20
        score += delta
        reasons.append(
            MatchReason("name", f"Names are similar (similarity {name_ratio}%)", delta)
        )
    elif name_ratio >= 55:
        delta = 0.10
        score += delta
        reasons.append(
            MatchReason("name", f"Names share some tokens (similarity {name_ratio}%)", delta)
        )
    # Below 55: no signal (not a useful name match)

    # ── Street signal ─────────────────────────────────────────────────────────
    street_a = _extract_street(a.address)
    street_b = _extract_street(b.address)

    if street_a and street_b:
        fields_used.append("street")
        street_ratio = fuzz.ratio(street_a, street_b)
        if street_ratio >= 85:
            delta = 0.20
            score += delta
            reasons.append(
                MatchReason(
                    "street",
                    f"Street addresses match (similarity {street_ratio}%): "
                    f"'{street_a}' vs '{street_b}'",
                    delta,
                )
            )
        elif street_ratio >= 70:
            delta = 0.10
            score += delta
            reasons.append(
                MatchReason(
                    "street",
                    f"Street addresses similar (similarity {street_ratio}%)",
                    delta,
                )
            )

    # ── Geo signal ────────────────────────────────────────────────────────────
    geo_dist: float | None = None
    if a.lat and a.lon and b.lat and b.lon:
        fields_used.append("geo")
        geo_dist = _haversine_miles(a.lat, a.lon, b.lat, b.lon)

        if geo_dist < 0.05:
            delta = 0.25
            score += delta
            reasons.append(
                MatchReason(
                    "geo",
                    f"Venues are {geo_dist * 5280:.0f} ft apart (same building)",
                    delta,
                )
            )
        elif geo_dist < 0.2:
            delta = 0.10
            score += delta
            reasons.append(
                MatchReason(
                    "geo",
                    f"Venues are {geo_dist * 5280:.0f} ft apart (same block)",
                    delta,
                )
            )
        elif geo_dist > 0.5:
            delta = -0.15
            score += delta
            reasons.append(
                MatchReason(
                    "geo",
                    f"Venues are {geo_dist:.2f} mi apart (different locations)",
                    delta,
                )
            )

    # ── Chain collision detection ─────────────────────────────────────────────
    # High name similarity + distant locations = same chain, different branch
    if name_ratio >= 85 and geo_dist is not None and geo_dist > 0.5:
        is_chain_collision = True
        reasons.append(
            MatchReason(
                "chain",
                f"Possible chain collision: same brand name but {geo_dist:.2f} mi apart",
                0.0,  # no score change — just a flag
            )
        )

    # Clamp score
    score = round(max(0.0, min(1.0, score)), 3)

    if score < _REVIEW_THRESHOLD:
        return None

    confidence = "high" if score >= _HIGH_CONFIDENCE else "review"

    return MatchResult(
        venue_a=a,
        venue_b=b,
        match_score=score,
        confidence=confidence,
        reasons=reasons,
        fields_used=list(dict.fromkeys(fields_used)),  # deduplicated, ordered
        is_chain_collision=is_chain_collision,
    )
