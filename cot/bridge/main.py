#!/usr/bin/env python3
"""MQTT (EdgeTech Logger) to Cursor-on-Target UDP bridge for SkyScan PTZ sensor."""

from __future__ import annotations

import json
import logging
import math
import os
import socket
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import paho.mqtt.client as mqtt

LOGGER_TOPIC = os.environ.get("LOGGER_TOPIC", "")
OBJECT_TOPIC = os.environ.get("OBJECT_TOPIC", "").strip()
MQTT_IP = os.environ.get("MQTT_IP", "mqtt")

COT_UDP_HOST = os.environ.get("COT_UDP_HOST", "127.0.0.1")
COT_UDP_PORT = int(os.environ.get("COT_UDP_PORT", "4242"))
COT_MULTICAST_TTL = max(1, min(255, int(os.environ.get("COT_MULTICAST_TTL", "32"))))
COT_UID = os.environ.get("COT_UID", "SKYSCAN-CAM1")
COT_CALLSIGN = os.environ.get("COT_CALLSIGN", "").strip()
COT_STALE_SECONDS = float(os.environ.get("COT_STALE_SECONDS", "120"))
COT_HEARTBEAT_INTERVAL = float(os.environ.get("COT_HEARTBEAT_INTERVAL", "8"))
COT_MAX_SEND_RATE = float(os.environ.get("COT_MAX_SEND_RATE", "5.0"))

# Periodic connectivity ping (distinct CoT uid/type from sensor feed)
COT_PING_INTERVAL = float(os.environ.get("COT_PING_INTERVAL", "30"))
COT_PING_STALE_SECONDS = float(os.environ.get("COT_PING_STALE_SECONDS", "60"))
COT_PING_TYPE = os.environ.get("COT_PING_TYPE", "b-m-p-s-m").strip()

# Periodic friendly equipment / sensor CoT (2525-style type on <event>)
COT_EQUIP_INTERVAL = float(os.environ.get("COT_EQUIP_INTERVAL", "60"))
COT_EQUIP_TYPE = os.environ.get("COT_EQUIP_TYPE", "a-f-G-E-S-E").strip()

TRIPOD_LAT = float(os.environ.get("TRIPOD_LATITUDE", "0"))
TRIPOD_LON = float(os.environ.get("TRIPOD_LONGITUDE", "0"))
TRIPOD_ALT = float(os.environ.get("TRIPOD_ALTITUDE", "0"))
POINT_CE = float(os.environ.get("POINT_CE", "15"))
POINT_LE = float(os.environ.get("POINT_LE", "10"))

SENSOR_FOV_H = float(os.environ.get("SENSOR_FOV_H", "55"))
SENSOR_FOV_V = float(os.environ.get("SENSOR_FOV_V", "32"))
SENSOR_TYPE = os.environ.get("SENSOR_TYPE", "b-m-p-s-p-e").strip()
SENSOR_MODEL = os.environ.get("SENSOR_MODEL", "SkyScan Camera")
# Modality string on <sensor> (not the same as mapping event type); see cot/takcot-master/mitre/types.txt
SENSOR_MODALITY_TYPE = os.environ.get("SENSOR_MODALITY_TYPE", "r-e-z-c").strip()
SENSOR_FOV_H_WIDE = float(os.environ.get("SENSOR_FOV_H_WIDE", str(SENSOR_FOV_H)))
SENSOR_FOV_H_TELE = float(os.environ.get("SENSOR_FOV_H_TELE", str(SENSOR_FOV_H)))
SENSOR_FOV_V_WIDE = float(os.environ.get("SENSOR_FOV_V_WIDE", str(SENSOR_FOV_V)))
SENSOR_FOV_V_TELE = float(os.environ.get("SENSOR_FOV_V_TELE", str(SENSOR_FOV_V)))


def _env_float_optional(key: str) -> float | None:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


SENSOR_ROLL_ATTR = _env_float_optional("SENSOR_ROLL")
SENSOR_NORTH_ATTR = _env_float_optional("SENSOR_NORTH")

COT_PING_UID = os.environ.get("COT_PING_UID", "").strip() or f"{COT_UID}-ping"

# Aircraft position as mapping sensor point-of-interest (MITRE b-m-p-s-p-i) or spot marker (b-m-p-s-m)
_COT_AIR_RAW = os.environ.get("COT_AIR_ENABLE", "true").strip().lower()
COT_AIR_ENABLE = _COT_AIR_RAW in ("1", "true", "yes", "on")
COT_AIR_TYPE = os.environ.get("COT_AIR_TYPE", "b-m-p-s-p-i").strip()
COT_AIR_HOW = os.environ.get("COT_AIR_HOW", "m-g").strip()
COT_AIR_STALE_SECONDS = float(os.environ.get("COT_AIR_STALE_SECONDS", "45"))
COT_AIR_POINT_CE = float(os.environ.get("COT_AIR_POINT_CE", str(POINT_CE)))
COT_AIR_POINT_LE = float(os.environ.get("COT_AIR_POINT_LE", str(POINT_LE)))
COT_AIR_MAX_SEND_RATE = float(os.environ.get("COT_AIR_MAX_SEND_RATE", "3.0"))
COT_AIR_UID_PREFIX = os.environ.get("COT_AIR_UID_PREFIX", "").strip()
COT_AIR_LINK_SENSOR = os.environ.get("COT_AIR_LINK_SENSOR", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# Ground FOV polygon for TAK/TAKX (separate CoT from <sensor>; default TAK u-d-f drawing)
_COT_FOV_EN = os.environ.get("COT_FOV_ENABLE", "true").strip().lower()
COT_FOV_ENABLE = _COT_FOV_EN in ("1", "true", "yes", "on")
COT_FOV_FORMAT = os.environ.get("COT_FOV_FORMAT", "tak").strip().lower()
COT_FOV_DEFAULT_RANGE_M = float(os.environ.get("COT_FOV_DEFAULT_RANGE_M", "10000"))
COT_FOV_NEAR_MIN_M = float(os.environ.get("COT_FOV_NEAR_MIN_M", "10"))
COT_FOV_NEAR_FRAC = float(os.environ.get("COT_FOV_NEAR_FRAC", "0.01"))
COT_FOV_MIN_GROUND_M = float(os.environ.get("COT_FOV_MIN_GROUND_M", "50"))
_COT_FOV_STALE = os.environ.get("COT_FOV_STALE_SECONDS", "").strip()
COT_FOV_STALE_SECONDS = (
    float(_COT_FOV_STALE) if _COT_FOV_STALE else COT_STALE_SECONDS
)
COT_FOV_UID = os.environ.get("COT_FOV_UID", "").strip() or f"{COT_UID}-fov"
COT_FOV_HOW = os.environ.get("COT_FOV_HOW", "h-e").strip()
COT_FOV_POINT_CE_MARGIN = float(os.environ.get("COT_FOV_POINT_CE_MARGIN", "50"))
COT_FOV_CALLSIGN = os.environ.get("COT_FOV_CALLSIGN", "SkyScan FOV").strip()
COT_FOV_FILL_COLOR = os.environ.get("COT_FOV_FILL_COLOR", "-1761607681").strip()
COT_FOV_STROKE_COLOR = os.environ.get("COT_FOV_STROKE_COLOR", "-1").strip()
COT_FOV_STROKE_WEIGHT = os.environ.get("COT_FOV_STROKE_WEIGHT", "3.0").strip()

EARTH_RADIUS_M = 6371008.8

_state_lock = threading.Lock()
_last_azimuth = 0.0
_last_elevation = 0.0
_last_zoom: int | None = None
_last_distance: float | None = None
_last_object_id: str | None = None
_last_send_mon = 0.0
_min_send_period = (
    1.0 / COT_MAX_SEND_RATE if COT_MAX_SEND_RATE > 0 else 0.0
)
_last_air_send_mon = 0.0
_min_air_send_period = (
    1.0 / COT_AIR_MAX_SEND_RATE if COT_AIR_MAX_SEND_RATE > 0 else 0.0
)


def _utc_cot_time(dt: datetime) -> str:
    """CoT-style ISO8601 with milliseconds and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _norm_azimuth(deg: float) -> float:
    x = float(deg) % 360.0
    if x < 0:
        x += 360.0
    if x >= 360.0:
        x = 0.0
    return round(x, 5)


def _clamp_elevation(deg: float) -> float:
    return round(max(-90.0, min(90.0, float(deg))), 5)


def _clamp_fov_schema_deg(d: float) -> float:
    """MITRE CoT sensor fov/vfov: [0, 360) degrees (maxExclusive 360)."""
    x = max(0.0, float(d))
    if x >= 360.0:
        x = 359.99
    return round(x, 5)


def _fov_from_zoom(zoom: int | None) -> tuple[float, float]:
    """Linear FOV zoom→tele between SENSOR_FOV_*_WIDE at 0 and *_TELE at 9999."""
    t = 0.0 if zoom is None else max(0, min(9999, int(zoom))) / 9999.0
    h = SENSOR_FOV_H_WIDE + (SENSOR_FOV_H_TELE - SENSOR_FOV_H_WIDE) * t
    v = SENSOR_FOV_V_WIDE + (SENSOR_FOV_V_TELE - SENSOR_FOV_V_WIDE) * t
    return _clamp_fov_schema_deg(h), _clamp_fov_schema_deg(v)


def _norm_north_deg(deg: float) -> float:
    x = float(deg) % 360.0
    if x < 0:
        x += 360.0
    if x >= 360.0:
        x = 0.0
    return round(x, 5)


def _geodesic_direct(
    lat_deg: float, lon_deg: float, bearing_deg: float, distance_m: float
) -> tuple[float, float]:
    """Spherical Earth: destination given start, initial bearing (deg, CW from north), distance (m)."""
    if distance_m <= 0:
        return lat_deg, lon_deg
    φ1 = math.radians(lat_deg)
    λ1 = math.radians(lon_deg)
    θ = math.radians(_norm_azimuth(bearing_deg))
    dr = distance_m / EARTH_RADIUS_M
    sin_φ1, cos_φ1 = math.sin(φ1), math.cos(φ1)
    sin_dr, cos_dr = math.sin(dr), math.cos(dr)
    sin_φ2 = sin_φ1 * cos_dr + cos_φ1 * sin_dr * math.cos(θ)
    sin_φ2 = max(-1.0, min(1.0, sin_φ2))
    φ2 = math.asin(sin_φ2)
    y = math.sin(θ) * sin_dr * cos_φ1
    x = cos_dr - sin_φ1 * sin_φ2
    λ2 = λ1 + math.atan2(y, x)
    lat2 = math.degrees(φ2)
    lon2 = math.degrees(λ2)
    if lon2 > 180.0:
        lon2 -= 360.0
    if lon2 < -180.0:
        lon2 += 360.0
    return lat2, lon2


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance on spherical Earth (meters)."""
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


def _fov_quad_ground_vertices(
    rho_deg: float,
    tau_deg: float,
    hfov_deg: float,
    slant_range_m: float,
    lat0: float,
    lon0: float,
    hae_m: float,
) -> list[tuple[float, float, float]]:
    """Far/near wedge on ground: near_left, near_right, far_right, far_left (lat, lon, hae)."""
    tau_r = math.radians(float(tau_deg))
    d_far = abs(float(slant_range_m)) * max(0.0, math.cos(tau_r))
    d_far = max(COT_FOV_MIN_GROUND_M, d_far)
    d_near = max(
        COT_FOV_NEAR_MIN_M,
        COT_FOV_NEAR_FRAC * d_far,
    )
    half = max(0.1, float(hfov_deg) / 2.0)
    br_left = _norm_azimuth(rho_deg - half)
    br_right = _norm_azimuth(rho_deg + half)
    nl_lat, nl_lon = _geodesic_direct(lat0, lon0, br_left, d_near)
    nr_lat, nr_lon = _geodesic_direct(lat0, lon0, br_right, d_near)
    fr_lat, fr_lon = _geodesic_direct(lat0, lon0, br_right, d_far)
    fl_lat, fl_lon = _geodesic_direct(lat0, lon0, br_left, d_far)
    h = round(float(hae_m), 3)
    return [
        (round(nl_lat, 8), round(nl_lon, 8), h),
        (round(nr_lat, 8), round(nr_lon, 8), h),
        (round(fr_lat, 8), round(fr_lon, 8), h),
        (round(fl_lat, 8), round(fl_lon, 8), h),
    ]


def _fov_centroid_and_ce_le(
    verts: list[tuple[float, float, float]],
) -> tuple[float, float, float, float]:
    """Simple lat/lon centroid; ce/le = half max edge distance from centroid + margin."""
    n = len(verts)
    c_lat = sum(v[0] for v in verts) / n
    c_lon = sum(v[1] for v in verts) / n
    max_d = 0.0
    for lat, lon, _ in verts:
        max_d = max(max_d, _haversine_m(c_lat, c_lon, lat, lon))
    bound = max_d + COT_FOV_POINT_CE_MARGIN
    ce = max(POINT_CE, round(bound, 3))
    le = max(POINT_LE, round(bound, 3))
    return c_lat, c_lon, ce, le


def _sensor_attributes(
    azimuth: float,
    elevation: float,
    *,
    zoom: int | None,
    distance_m: float | None,
) -> dict[str, str]:
    """Attributes for MITRE <sensor> (azimuth, elevation, fov, vfov, model, type, optional range/roll/north)."""
    fov_h, fov_v = _fov_from_zoom(zoom)
    out: dict[str, str] = {
        "azimuth": str(_norm_azimuth(azimuth)),
        "elevation": str(_clamp_elevation(elevation)),
        "fov": str(fov_h),
        "vfov": str(fov_v),
        "model": SENSOR_MODEL,
        "type": SENSOR_MODALITY_TYPE,
    }
    if distance_m is not None and distance_m >= 0:
        out["range"] = str(round(float(distance_m), 3))
    if SENSOR_ROLL_ATTR is not None:
        r = max(-180.0 + 1e-9, min(180.0, SENSOR_ROLL_ATTR))
        out["roll"] = str(round(r, 5))
    if SENSOR_NORTH_ATTR is not None:
        out["north"] = str(_norm_north_deg(SENSOR_NORTH_ATTR))
    return out


def _extract_logger_inner(outer: Mapping[str, Any]) -> dict[str, Any] | None:
    """Support both EdgeTech envelope styles (see cot/bridge/README.md)."""
    inner_raw: Any = None
    if "Logger" in outer:
        inner_raw = outer["Logger"]
    elif outer.get("data_payload_type") == "Logger":
        inner_raw = outer.get("data_payload")

    if inner_raw is None:
        return None
    if isinstance(inner_raw, str):
        return json.loads(inner_raw)
    if isinstance(inner_raw, dict):
        return inner_raw
    return None


def _parse_camera_pointing(payload: str) -> dict[str, Any] | None:
    try:
        outer = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(outer, dict):
        return None
    inner = _extract_logger_inner(outer)
    if not inner:
        return None
    cp = inner.get("camera-pointing")
    if not isinstance(cp, dict):
        return None
    return cp


def _sanitize_uid_part(s: str) -> str:
    out = []
    for c in str(s).strip().lower():
        if c.isalnum() or c in ("-", "_"):
            out.append(c)
    return "".join(out) or "unknown"


def _parse_selected_object(payload: str) -> dict[str, Any] | None:
    """Parse skyscan-c2 Selected Object (EdgeTech envelope or raw dict)."""
    try:
        outer = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(outer, dict):
        return None
    inner: Any = None
    if outer.get("data_payload_type") == "Selected Object":
        raw = outer.get("data_payload")
        if isinstance(raw, str):
            rs = raw.strip()
            if not rs or rs == "{}":
                return None
            try:
                inner = json.loads(raw)
            except json.JSONDecodeError:
                return None
        elif isinstance(raw, dict):
            inner = raw if raw else None
    if inner is None and "object_id" in outer and "latitude" in outer:
        inner = outer
    if not isinstance(inner, dict) or not inner:
        return None
    return inner


def _coerce_float(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _str_clean(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return ""
    return s


def _build_air_remarks(obj: Mapping[str, Any]) -> str:
    parts: list[str] = ["ADS-B / SkyScan track"]
    flight = _str_clean(obj.get("flight"))
    if flight:
        parts.append(f"flight={flight}")
    oid = obj.get("object_id")
    if oid:
        parts.append(f"icao={oid}")
    trk = _coerce_float(obj.get("track"))
    if trk is not None:
        parts.append(f"track={trk:.1f}°")
    hvel = _coerce_float(obj.get("horizontal_velocity"))
    if hvel is not None:
        parts.append(f"gs={hvel:.1f}m/s")
    sq = _str_clean(obj.get("squawk"))
    if sq:
        parts.append(f"squawk={sq}")
    cat = _str_clean(obj.get("category"))
    if cat:
        parts.append(f"cat={cat}")
    rr = _coerce_float(obj.get("relative_distance"))
    if rr is not None:
        parts.append(f"slant_range≈{rr:.0f}m")
    return " ".join(parts)


def build_air_spi_cot(obj: Mapping[str, Any]) -> str | None:
    """Mapping SPI/SPOI-style marker at aircraft position (default type b-m-p-s-p-i)."""
    lat = _coerce_float(obj.get("latitude"))
    lon = _coerce_float(obj.get("longitude"))
    alt = _coerce_float(obj.get("altitude"))
    if lat is None or lon is None or alt is None:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None

    oid_raw = obj.get("object_id")
    oid = _sanitize_uid_part(str(oid_raw)) if oid_raw is not None else "unknown"
    if COT_AIR_UID_PREFIX:
        uid = f"{COT_AIR_UID_PREFIX}{oid}"
    else:
        uid = f"{COT_UID}-adsb-{oid}"

    flight_raw = obj.get("flight")
    callsign = _str_clean(flight_raw) or f"ADS-B-{oid}"

    now = datetime.now(timezone.utc)
    stale = now + timedelta(seconds=COT_AIR_STALE_SECONDS)

    event = ET.Element(
        "event",
        {
            "version": "2.0",
            "uid": uid,
            "type": COT_AIR_TYPE,
            "time": _utc_cot_time(now),
            "start": _utc_cot_time(now),
            "stale": _utc_cot_time(stale),
            "how": COT_AIR_HOW,
        },
    )

    ET.SubElement(
        event,
        "point",
        {
            "lat": f"{lat:.8f}",
            "lon": f"{lon:.8f}",
            "hae": f"{alt:.3f}",
            "ce": f"{COT_AIR_POINT_CE:.3f}",
            "le": f"{COT_AIR_POINT_LE:.3f}",
        },
    )

    detail = ET.SubElement(event, "detail")
    ET.SubElement(detail, "contact", {"callsign": callsign[:200]})
    if COT_AIR_LINK_SENSOR:
        ET.SubElement(
            detail,
            "link",
            {
                "uid": COT_UID,
                "type": SENSOR_TYPE,
                "relation": "p-p",
            },
        )
    ET.SubElement(detail, "remarks").text = _build_air_remarks(obj)[:2000]

    body = ET.tostring(event, encoding="unicode")
    return (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n" + body
    )


def build_sensor_cot(
    azimuth: float,
    elevation: float,
    *,
    remarks_extra: str = "",
    zoom: int | None = None,
    distance_m: float | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    stale = now + timedelta(seconds=COT_STALE_SECONDS)

    event = ET.Element(
        "event",
        {
            "version": "2.0",
            "uid": COT_UID,
            "type": SENSOR_TYPE,
            "time": _utc_cot_time(now),
            "start": _utc_cot_time(now),
            "stale": _utc_cot_time(stale),
            "how": "m-g",
        },
    )

    ET.SubElement(
        event,
        "point",
        {
            "lat": f"{TRIPOD_LAT:.8f}",
            "lon": f"{TRIPOD_LON:.8f}",
            "hae": f"{TRIPOD_ALT:.3f}",
            "ce": f"{POINT_CE:.3f}",
            "le": f"{POINT_LE:.3f}",
        },
    )

    detail = ET.SubElement(event, "detail")
    if COT_CALLSIGN:
        ET.SubElement(detail, "contact", {"callsign": COT_CALLSIGN})

    sensor_attrs = _sensor_attributes(
        azimuth, elevation, zoom=zoom, distance_m=distance_m
    )
    ET.SubElement(detail, "sensor", sensor_attrs)

    remarks_parts = [remarks_extra.strip()] if remarks_extra else []
    ET.SubElement(detail, "remarks").text = " ".join(p for p in remarks_parts if p) or "SkyScan PTZ"

    body = ET.tostring(event, encoding="unicode")
    return (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n" + body
    )


def build_ping_cot() -> str:
    """Small marker-style CoT for periodic UDP reachability checks (separate uid)."""
    now = datetime.now(timezone.utc)
    stale = now + timedelta(seconds=COT_PING_STALE_SECONDS)
    event = ET.Element(
        "event",
        {
            "version": "2.0",
            "uid": COT_PING_UID,
            "type": COT_PING_TYPE,
            "time": _utc_cot_time(now),
            "start": _utc_cot_time(now),
            "stale": _utc_cot_time(stale),
            "how": "h-g-i-g-o",
        },
    )
    ET.SubElement(
        event,
        "point",
        {
            "lat": f"{TRIPOD_LAT:.8f}",
            "lon": f"{TRIPOD_LON:.8f}",
            "hae": f"{TRIPOD_ALT:.3f}",
            "ce": f"{POINT_CE:.3f}",
            "le": f"{POINT_LE:.3f}",
        },
    )
    detail = ET.SubElement(event, "detail")
    ping_cs = (
        f"{COT_CALLSIGN} ping" if COT_CALLSIGN else "SkyScan ping"
    )
    ET.SubElement(detail, "contact", {"callsign": ping_cs})
    ET.SubElement(detail, "remarks").text = "SkyScan CoT connectivity ping"
    body = ET.tostring(event, encoding="unicode")
    return (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n" + body
    )


def build_equipment_sensor_cot(
    azimuth: float,
    elevation: float,
    *,
    remarks_extra: str = "",
    zoom: int | None = None,
    distance_m: float | None = None,
) -> str:
    """Friendly equipment sensor CoT (e.g. a-f-G-E-S-E) with MITRE <sensor> geometry."""
    now = datetime.now(timezone.utc)
    stale = now + timedelta(seconds=COT_STALE_SECONDS)

    event = ET.Element(
        "event",
        {
            "version": "2.0",
            "uid": COT_UID,
            "type": COT_EQUIP_TYPE,
            "time": _utc_cot_time(now),
            "start": _utc_cot_time(now),
            "stale": _utc_cot_time(stale),
            "how": "m-g",
        },
    )

    ET.SubElement(
        event,
        "point",
        {
            "lat": f"{TRIPOD_LAT:.8f}",
            "lon": f"{TRIPOD_LON:.8f}",
            "hae": f"{TRIPOD_ALT:.3f}",
            "ce": f"{POINT_CE:.3f}",
            "le": f"{POINT_LE:.3f}",
        },
    )

    detail = ET.SubElement(event, "detail")
    if COT_CALLSIGN:
        ET.SubElement(detail, "contact", {"callsign": COT_CALLSIGN})

    sensor_attrs = _sensor_attributes(
        azimuth, elevation, zoom=zoom, distance_m=distance_m
    )
    ET.SubElement(detail, "sensor", sensor_attrs)

    remarks_parts = [remarks_extra.strip()] if remarks_extra else []
    ET.SubElement(detail, "remarks").text = (
        " ".join(p for p in remarks_parts if p)
        or f"SkyScan PTZ ({COT_EQUIP_TYPE})"
    )

    body = ET.tostring(event, encoding="unicode")
    return (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n" + body
    )


def build_fov_polygon_cot(
    azimuth: float,
    elevation: float,
    *,
    zoom: int | None = None,
    distance_m: float | None = None,
) -> str | None:
    """Ground footprint of horizontal FOV as closed polygon (TAK u-d-f or MITRE shape/polyline)."""
    if not COT_FOV_ENABLE:
        return None
    r_slant = (
        float(distance_m)
        if distance_m is not None and float(distance_m) >= 0
        else COT_FOV_DEFAULT_RANGE_M
    )
    hfov, _ = _fov_from_zoom(zoom)
    verts = _fov_quad_ground_vertices(
        azimuth,
        elevation,
        hfov,
        r_slant,
        TRIPOD_LAT,
        TRIPOD_LON,
        TRIPOD_ALT,
    )
    if not verts:
        return None
    c_lat, c_lon, ce, le = _fov_centroid_and_ce_le(verts)
    now = datetime.now(timezone.utc)
    stale = now + timedelta(seconds=COT_FOV_STALE_SECONDS)

    event = ET.Element(
        "event",
        {
            "version": "2.0",
            "uid": COT_FOV_UID,
            "type": "u-d-f",
            "time": _utc_cot_time(now),
            "start": _utc_cot_time(now),
            "stale": _utc_cot_time(stale),
            "how": COT_FOV_HOW,
        },
    )
    ET.SubElement(
        event,
        "point",
        {
            "lat": f"{c_lat:.8f}",
            "lon": f"{c_lon:.8f}",
            "hae": f"{TRIPOD_ALT:.3f}",
            "ce": f"{ce:.3f}",
            "le": f"{le:.3f}",
        },
    )
    detail = ET.SubElement(event, "detail")
    fmt = COT_FOV_FORMAT
    if fmt in ("mitre", "shape", "polyline"):
        shape_el = ET.SubElement(detail, "shape")
        poly = ET.SubElement(shape_el, "polyline", {"closed": "true"})
        for lat_v, lon_v, hae_v in verts:
            ET.SubElement(
                poly,
                "vertex",
                {
                    "lat": f"{lat_v:.8f}",
                    "lon": f"{lon_v:.8f}",
                    "hae": f"{hae_v:.3f}",
                },
            )
    else:
        for lat_v, lon_v, _ in verts:
            ET.SubElement(detail, "link", {"point": f"{lat_v},{lon_v}"})
        v0 = verts[0]
        ET.SubElement(detail, "link", {"point": f"{v0[0]},{v0[1]}"})
    ET.SubElement(detail, "strokeColor", {"value": COT_FOV_STROKE_COLOR})
    ET.SubElement(detail, "strokeWeight", {"value": COT_FOV_STROKE_WEIGHT})
    ET.SubElement(detail, "fillColor", {"value": COT_FOV_FILL_COLOR})
    cs = COT_FOV_CALLSIGN or "SkyScan FOV"
    ET.SubElement(detail, "contact", {"callsign": cs[:200]})
    ET.SubElement(detail, "remarks").text = (
        "SkyScan horizontal FOV footprint on ground "
        f"(hfov={hfov:.2f}deg slant_R={r_slant:.0f}m)"
    )
    ET.SubElement(detail, "archive")
    ET.SubElement(detail, "labels_on", {"value": "false"})
    ET.SubElement(detail, "color", {"value": COT_FOV_STROKE_COLOR})
    ET.SubElement(detail, "precisionlocation", {"altsrc": "???"})
    body = ET.tostring(event, encoding="unicode")
    return (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n" + body
    )


def _is_multicast_ipv4(host: str) -> bool:
    try:
        octets = [int(x) for x in host.split(".")]
        if len(octets) != 4:
            return False
        first = octets[0]
        return 224 <= first <= 239
    except ValueError:
        return False


def _send_udp(xml: str) -> None:
    data = xml.encode("utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        if _is_multicast_ipv4(COT_UDP_HOST):
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, COT_MULTICAST_TTL)
        s.sendto(data, (COT_UDP_HOST, COT_UDP_PORT))
    logging.debug("Sent CoT (%d bytes) to %s:%s", len(data), COT_UDP_HOST, COT_UDP_PORT)


def _emit_pose(
    azimuth: float,
    elevation: float,
    *,
    remarks: str = "",
    force: bool = False,
    zoom: int | None = None,
    distance_m: float | None = None,
) -> None:
    global _last_send_mon
    with _state_lock:
        zm = _last_zoom if zoom is None else zoom
        dm = _last_distance if distance_m is None else distance_m
    now_m = time.monotonic()
    if not force and _min_send_period > 0:
        if (now_m - _last_send_mon) < _min_send_period:
            return
    _last_send_mon = now_m
    xml = build_sensor_cot(
        azimuth,
        elevation,
        remarks_extra=remarks,
        zoom=zm,
        distance_m=dm,
    )
    _send_udp(xml)
    if COT_FOV_ENABLE:
        try:
            fov_xml = build_fov_polygon_cot(
                azimuth,
                elevation,
                zoom=zm,
                distance_m=dm,
            )
            if fov_xml:
                _send_udp(fov_xml)
        except OSError as e:
            logging.error("UDP FOV polygon CoT send failed: %s", e)


def _emit_air_spi(obj: Mapping[str, Any]) -> None:
    global _last_air_send_mon
    now_m = time.monotonic()
    if _min_air_send_period > 0:
        if (now_m - _last_air_send_mon) < _min_air_send_period:
            return
    xml = build_air_spi_cot(obj)
    if not xml:
        return
    _last_air_send_mon = now_m
    try:
        _send_udp(xml)
    except OSError as e:
        logging.error("UDP air SPI send failed: %s", e)


def _on_logger_message(
    _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage
) -> None:
    global _last_azimuth, _last_elevation, _last_zoom, _last_distance, _last_object_id
    if not msg.payload:
        return
    try:
        text = msg.payload.decode("utf-8")
    except UnicodeDecodeError:
        return
    cp = _parse_camera_pointing(text)
    if not cp:
        return
    try:
        rho = float(cp["rho_c"])
        tau = float(cp["tau_c"])
    except (KeyError, TypeError, ValueError):
        logging.warning("Logger camera-pointing missing rho_c/tau_c: %s", cp.keys())
        return

    oid = cp.get("object_id")
    zoom = cp.get("zoom")
    dist_m: float | None = None
    d_raw = cp.get("distance")
    if d_raw is not None:
        try:
            d_val = float(d_raw)
            if d_val >= 0:
                dist_m = d_val
        except (TypeError, ValueError):
            pass
    remarks = ""
    if oid is not None:
        remarks = f"tracking {oid}"
    if zoom is not None:
        remarks = f"{remarks} zoom={zoom}".strip()

    with _state_lock:
        _last_azimuth = rho
        _last_elevation = tau
        _last_distance = dist_m
        if zoom is not None:
            try:
                _last_zoom = int(zoom)
            except (TypeError, ValueError):
                pass
        if isinstance(oid, str):
            _last_object_id = oid

    zm_emit: int | None = None
    if zoom is not None:
        try:
            zm_emit = int(zoom)
        except (TypeError, ValueError):
            zm_emit = None
    _emit_pose(
        rho, tau, remarks=remarks, force=False, zoom=zm_emit, distance_m=dist_m
    )


def _on_selected_object_message(msg: mqtt.MQTTMessage) -> None:
    if not COT_AIR_ENABLE:
        return
    if not msg.payload:
        return
    try:
        text = msg.payload.decode("utf-8")
    except UnicodeDecodeError:
        return
    obj = _parse_selected_object(text)
    if not obj:
        return
    _emit_air_spi(obj)


def _on_message(_client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
    if OBJECT_TOPIC and msg.topic == OBJECT_TOPIC:
        _on_selected_object_message(msg)
    else:
        _on_logger_message(_client, _userdata, msg)


def _heartbeat_loop(stop: threading.Event) -> None:
    while not stop.wait(timeout=COT_HEARTBEAT_INTERVAL):
        with _state_lock:
            rho, tau = _last_azimuth, _last_elevation
            oid = _last_object_id
            zm = _last_zoom
            dist = _last_distance
        rmk = ""
        if oid:
            rmk = f"last object {oid}"
        if zm is not None:
            rmk = f"{rmk} zoom={zm}".strip()
        try:
            _emit_pose(
                rho,
                tau,
                remarks=rmk,
                force=True,
                zoom=zm,
                distance_m=dist,
            )
        except OSError as e:
            logging.error("UDP send failed: %s", e)


def _ping_loop(stop: threading.Event) -> None:
    while not stop.wait(timeout=COT_PING_INTERVAL):
        try:
            _send_udp(build_ping_cot())
            logging.debug(
                "CoT ping uid=%s -> %s:%s",
                COT_PING_UID,
                COT_UDP_HOST,
                COT_UDP_PORT,
            )
        except OSError as e:
            logging.error("UDP ping send failed: %s", e)


def _equip_sensor_loop(stop: threading.Event) -> None:
    """Emit a-f-G-E-S-E (or COT_EQUIP_TYPE) with current camera pointing."""
    while not stop.wait(timeout=COT_EQUIP_INTERVAL):
        with _state_lock:
            rho, tau = _last_azimuth, _last_elevation
            oid = _last_object_id
            zm = _last_zoom
            dist = _last_distance
        rmk = ""
        if oid:
            rmk = f"last object {oid}"
        if zm is not None:
            rmk = f"{rmk} zoom={zm}".strip()
        try:
            _send_udp(
                build_equipment_sensor_cot(
                    rho,
                    tau,
                    remarks_extra=rmk,
                    zoom=zm,
                    distance_m=dist,
                )
            )
            logging.debug(
                "Equipment sensor CoT type=%s uid=%s -> %s:%s",
                COT_EQUIP_TYPE,
                COT_UID,
                COT_UDP_HOST,
                COT_UDP_PORT,
            )
        except OSError as e:
            logging.error("UDP equipment sensor CoT send failed: %s", e)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if not LOGGER_TOPIC:
        raise SystemExit("LOGGER_TOPIC is not set")

    if OBJECT_TOPIC and COT_AIR_ENABLE:
        logging.info(
            "Aircraft position -> CoT %s (SPI/SPOI-style) on same UDP as PTZ sensor",
            COT_AIR_TYPE,
        )
    if COT_FOV_ENABLE:
        logging.info(
            "FOV ground polygon -> CoT type u-d-f format=%s uid=%s (same UDP as sensor)",
            COT_FOV_FORMAT,
            COT_FOV_UID,
        )

    # Home pose until first Logger message
    _emit_pose(0.0, 0.0, remarks="SkyScan home", force=True)

    stop_hb = threading.Event()
    hb_thread = threading.Thread(
        target=_heartbeat_loop, args=(stop_hb,), daemon=True
    )
    hb_thread.start()

    stop_ping = threading.Event()
    if COT_PING_INTERVAL > 0:
        try:
            _send_udp(build_ping_cot())
            logging.info(
                "Initial CoT ping uid=%s -> %s:%s",
                COT_PING_UID,
                COT_UDP_HOST,
                COT_UDP_PORT,
            )
        except OSError as e:
            logging.error("UDP ping send failed: %s", e)
        ping_thread = threading.Thread(
            target=_ping_loop, args=(stop_ping,), daemon=True
        )
        ping_thread.start()

    stop_equip = threading.Event()
    if COT_EQUIP_INTERVAL > 0:
        try:
            _send_udp(build_equipment_sensor_cot(0.0, 0.0, remarks_extra="SkyScan home"))
            logging.info(
                "Initial equipment sensor CoT type=%s uid=%s -> %s:%s",
                COT_EQUIP_TYPE,
                COT_UID,
                COT_UDP_HOST,
                COT_UDP_PORT,
            )
        except OSError as e:
            logging.error("UDP equipment sensor CoT send failed: %s", e)
        equip_thread = threading.Thread(
            target=_equip_sensor_loop, args=(stop_equip,), daemon=True
        )
        equip_thread.start()

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="skyscan-cot-bridge",
    )

    def on_connect(
        client_: mqtt.Client,
        _userdata: Any,
        _flags: dict[str, Any],
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            logging.error("MQTT connect failed: %s", reason_code)
            return
        client_.subscribe(LOGGER_TOPIC)
        logging.info("Subscribed to %s", LOGGER_TOPIC)
        if OBJECT_TOPIC and COT_AIR_ENABLE:
            client_.subscribe(OBJECT_TOPIC)
            logging.info(
                "Subscribed to %s (aircraft marker CoT type=%s)",
                OBJECT_TOPIC,
                COT_AIR_TYPE,
            )

    client.on_connect = on_connect
    client.on_message = _on_message

    logging.info("Connecting to MQTT %s for CoT -> UDP %s:%s", MQTT_IP, COT_UDP_HOST, COT_UDP_PORT)
    client.connect(MQTT_IP, 1883, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
