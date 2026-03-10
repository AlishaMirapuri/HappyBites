"""
Feature flags — simple dict-based for MVP.

Replace with LaunchDarkly / Unleash / GrowthBook when you need:
  - per-user/segment targeting
  - gradual rollouts
  - A/B experiment tracking

Usage:
    from happybites.experiments.flags import flag

    if flag("ai_normalization"):
        ...
"""

import structlog

logger = structlog.get_logger(__name__)

# Flags: name → enabled (bool)
# Mirrors the current intended state of each feature.
_FLAGS: dict[str, bool] = {
    "ai_normalization": True,         # Use Claude for normalization; False = regex-only
    "cross_source_dedup": True,       # Run URL-based cross-source dedup after ingestion
    "show_expiry_countdown": True,    # Show expiry countdown badges in frontend
    "reddit_connector": True,         # Include Reddit in scheduled ingestion
    "dealnews_connector": True,       # Include DealNews in scheduled ingestion
    "ranking_v2": False,              # Experimental: upvote-weighted ranking formula
    "admin_endpoints": True,          # Expose /admin/* routes
}


def flag(name: str, default: bool = False) -> bool:
    """Return the value of a feature flag. Logs a warning for unknown flags."""
    if name not in _FLAGS:
        logger.warning("unknown_flag", flag=name, returning=default)
        return default
    return _FLAGS[name]


def override(name: str, value: bool) -> None:
    """Override a flag at runtime (useful in tests)."""
    _FLAGS[name] = value


def all_flags() -> dict[str, bool]:
    """Return a copy of all current flag values."""
    return dict(_FLAGS)
