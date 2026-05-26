"""Compute ground-target pointing (bearing/elevation) from observer position."""

from __future__ import annotations

import math

from video.geo import haversine_m


def bearing_deg(
    observer_lat: float,
    observer_lon: float,
    target_lat: float,
    target_lon: float,
) -> float:
    """Forward azimuth from observer to target (0=north, clockwise)."""
    phi1 = math.radians(observer_lat)
    phi2 = math.radians(target_lat)
    dlon = math.radians(target_lon - observer_lon)
    x = math.sin(dlon) * math.cos(phi2)
    y = (
        math.cos(phi1) * math.sin(phi2)
        - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    )
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def elevation_deg(
    observer_lat: float,
    observer_lon: float,
    observer_alt_m: float,
    target_lat: float,
    target_lon: float,
    target_alt_m: float,
) -> float:
    """Elevation angle from observer to target in degrees."""
    horizontal_m = haversine_m(observer_lat, observer_lon, target_lat, target_lon)
    dalt = float(target_alt_m) - float(observer_alt_m)
    if horizontal_m <= 0.0:
        return 90.0 if dalt > 0 else 0.0
    return math.degrees(math.atan2(dalt, horizontal_m))


def target_az_el(observer: dict, target: dict) -> tuple[float, float]:
    """Return target bearing/elevation degrees for observer and target dicts."""
    o_lat = float(observer["latitude"])
    o_lon = float(observer["longitude"])
    o_alt = float(observer.get("altitude_m", observer.get("alt", 0.0)))
    t_lat = float(target["lat"])
    t_lon = float(target["lon"])
    t_alt = float(target.get("alt_m", target.get("altitude_m", 0.0)))
    return (
        bearing_deg(o_lat, o_lon, t_lat, t_lon),
        elevation_deg(o_lat, o_lon, o_alt, t_lat, t_lon, t_alt),
    )
