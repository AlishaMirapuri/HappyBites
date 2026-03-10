"""Geo utilities: Haversine distance, bounding box, schedule-aware deal filter."""

import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from happybites.db.models import Deal

EARTH_RADIUS_MILES = 3958.8


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in miles between two (lat, lon) points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def bounding_box(
    lat: float, lon: float, radius_miles: float
) -> tuple[float, float, float, float]:
    """Return (min_lat, max_lat, min_lon, max_lon) for a circular bounding box."""
    delta_lat = math.degrees(radius_miles / EARTH_RADIUS_MILES)
    delta_lon = math.degrees(
        radius_miles / (EARTH_RADIUS_MILES * math.cos(math.radians(lat)))
    )
    return lat - delta_lat, lat + delta_lat, lon - delta_lon, lon + delta_lon


def is_deal_active_at(deal: "Deal", check_time: datetime) -> bool:
    """Return True if deal has a matching schedule at check_time, or has no schedules.

    check_time is interpreted in UTC. DealSchedule.timezone is advisory for future
    localisation — this implementation uses UTC for simplicity.
    """
    if not deal.schedules:
        return True

    # Normalise to naive UTC for comparison
    ct = check_time.replace(tzinfo=None) if check_time.tzinfo else check_time

    for sched in deal.schedules:
        # Absolute date bounds
        if sched.valid_from:
            vf = sched.valid_from.replace(tzinfo=None) if sched.valid_from.tzinfo else sched.valid_from
            if ct < vf:
                continue
        if sched.valid_until:
            vu = sched.valid_until.replace(tzinfo=None) if sched.valid_until.tzinfo else sched.valid_until
            if ct > vu:
                continue

        # Day of week (0 = Monday … 6 = Sunday, matching Python's weekday())
        if sched.day_of_week is not None and sched.day_of_week != check_time.weekday():
            continue

        # Time window
        if sched.start_time and sched.end_time:
            hh_s, mm_s = map(int, sched.start_time.split(":"))
            hh_e, mm_e = map(int, sched.end_time.split(":"))
            current_min = check_time.hour * 60 + check_time.minute
            if not (hh_s * 60 + mm_s <= current_min <= hh_e * 60 + mm_e):
                continue

        return True

    return False
