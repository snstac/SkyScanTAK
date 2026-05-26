"""Alt-az to equatorial (RA/Dec) transforms for HUD and CoT remarks."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def observer_from_dict(data: dict | None) -> dict:
    """Normalize observer fields from GPS metadata or tripod config."""
    if not data:
        return {}
    lat = data.get("latitude", data.get("lat"))
    lon = data.get("longitude", data.get("lon"))
    alt = data.get("altitude_m", data.get("alt", data.get("altitude", 0.0)))
    return {
        "latitude": float(lat) if lat is not None else None,
        "longitude": float(lon) if lon is not None else None,
        "altitude_m": float(alt) if alt is not None else 0.0,
        "gps_source": data.get("gps_source"),
        "recorded_at": data.get("recorded_at"),
    }


def altaz_to_radec(
    az_deg: float,
    el_deg: float,
    unix_time: float,
    observer: dict,
) -> tuple[float, float]:
    """Transform horizontal coordinates to ICRS RA/Dec (degrees)."""
    from astropy import units as u
    from astropy.coordinates import AltAz, EarthLocation, SkyCoord
    from astropy.time import Time

    lat = observer["latitude"]
    lon = observer["longitude"]
    alt_m = observer.get("altitude_m", 0.0)

    location = EarthLocation(
        lat=lat * u.deg,
        lon=lon * u.deg,
        height=alt_m * u.m,
    )
    obstime = Time(unix_time, format="unix", scale="utc")
    frame = AltAz(obstime=obstime, location=location)
    altaz = SkyCoord(
        az=az_deg * u.deg,
        alt=el_deg * u.deg,
        frame=frame,
    )
    icrs = altaz.transform_to("icrs")
    ra = float(icrs.ra.deg) % 360.0
    dec = float(icrs.dec.deg)
    return ra, dec


def boresight_equatorial(
    coordinates: dict | None,
    antenna_orientation: dict | None,
    timestamp: float | None,
    observer: dict | None = None,
) -> dict[str, float] | None:
    """
    Current line-of-sight RA/Dec and galactic l/b (degrees).

    ``coordinates`` / ``antenna_orientation`` use lat/lon/alt and azimuth/elevation
    keys (PaintWave ``/api/tak/sensor`` shape). SkyScan callers may pass tripod
    position as ``coordinates`` and ``rho``/``tau`` as az/el.
    """
    coords = coordinates or {}
    orient = antenna_orientation or {}
    az = orient.get("azimuth", orient.get("az"))
    el = orient.get("elevation", orient.get("el"))
    if az is None or el is None:
        return None

    obs = observer
    if obs is None:
        lat = coords.get("lat", coords.get("latitude"))
        lon = coords.get("lon", coords.get("longitude"))
        if lat is None or lon is None:
            return None
        obs = observer_from_dict(coords)
    elif obs.get("latitude") is None or obs.get("longitude") is None:
        return None

    ts = timestamp if timestamp is not None else time.time()

    try:
        ra, dec = altaz_to_radec(float(az), float(el), float(ts), obs)
        from astropy import units as u
        from astropy.coordinates import SkyCoord

        gal = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs").galactic
        l_deg = float(gal.l.deg)
        if l_deg > 180.0:
            l_deg -= 360.0
        return {
            "ra_deg": ra,
            "dec_deg": dec,
            "galactic_l_deg": l_deg,
            "galactic_b_deg": float(gal.b.deg),
        }
    except Exception as e:
        logger.warning("Boresight equatorial transform failed: %s", e)
        return None


def equatorial_from_tripod_los(
    *,
    lat: float,
    lon: float,
    alt_m: float,
    az_deg: float,
    el_deg: float,
    timestamp: float | None = None,
) -> dict[str, float] | None:
    """SkyScan helper: tripod LLA + camera az/el → equatorial block."""
    return boresight_equatorial(
        {"lat": lat, "lon": lon, "alt": alt_m},
        {"azimuth": az_deg, "elevation": el_deg},
        timestamp,
    )
