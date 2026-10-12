"""Straight-line geography helpers.

No routing service and no network: the dispatcher ranks collectors by
great-circle (haversine) distance from the swarm site.
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two WGS-84 points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def within_radius_km(
    lat: float, lon: float, centre_lat: float, centre_lon: float, radius_km: float
) -> bool:
    """True when a point sits inside *radius_km* of a centre point."""
    return haversine_km(lat, lon, centre_lat, centre_lon) <= radius_km


def format_km(distance_km: float) -> str:
    """Human-readable distance for tables and confirmations."""
    if distance_km < 10:
        return f"{distance_km:.1f} km"
    return f"{distance_km:.0f} km"
