"""Batch venue deduplication runner.

Takes a list of VenueSnapshot objects (typically all venues in a city) and
returns all candidate pairs sorted by match_score descending.

Algorithm: O(n²) pairwise comparison — practical for city-level venue counts
(< 10 000 venues per city).  Within a pair, the venue with more source
mappings is nominated as the "primary" (a) and the other as "secondary" (b),
so callers know which to keep when merging.
"""

from __future__ import annotations

from happybites.venue_dedup.matcher import MatchResult, VenueSnapshot, match_venues


def find_duplicate_candidates(
    venues: list[VenueSnapshot],
    *,
    same_city_only: bool = True,
) -> list[MatchResult]:
    """Compare every pair in `venues` and return candidate duplicates.

    Args:
        venues: All venue snapshots to evaluate.
        same_city_only: When True (default), only compare venues with the
                        same city_id. Skip if city_id is None on either side.

    Returns:
        MatchResult list sorted by match_score descending.  Pairs below the
        REVIEW_THRESHOLD (0.40) are excluded.
    """
    results: list[MatchResult] = []

    for i in range(len(venues)):
        for j in range(i + 1, len(venues)):
            a, b = venues[i], venues[j]

            if same_city_only:
                if a.city_id is None or b.city_id is None:
                    continue
                if a.city_id != b.city_id:
                    continue

            # Nominate the venue with more source mappings as "primary" (a)
            if b.source_count > a.source_count:
                a, b = b, a

            result = match_venues(a, b)
            if result is not None:
                results.append(result)

    results.sort(key=lambda r: r.match_score, reverse=True)
    return results
