"""Minimal geodesy (same spherical model as cot-bridge)."""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6371008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(min(1.0, a)))
    return EARTH_RADIUS_M * c


def slant_range_m(
    sensor_lat: float,
    sensor_lon: float,
    sensor_hae_m: float,
    tgt_lat: float,
    tgt_lon: float,
    tgt_hae_m: float,
) -> float:
    """Straight-line distance sensor → target (WGS84 heights as HAE)."""
    g = haversine_m(sensor_lat, sensor_lon, tgt_lat, tgt_lon)
    dh = float(tgt_hae_m) - float(sensor_hae_m)
    return math.sqrt(g * g + dh * dh)
