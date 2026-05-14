"""Build MISB ST 0601 UAS Local Metadata Set packets (klvdata).

SkyScan uses the ``klvdata`` library for UAS Local Set encoding. For a
hand-packed 6DOF-style encoder used by the older SmartCam tooling under
``CTI/sc3d`` (``klv_6dof_encoder.py``, ``smartcam_stream.py``), compare
field layouts if you need bit-exact interop with a consumer tuned to that
binary format—do not assume packets match byte-for-byte.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from klvdata.common import ber_encode, datetime_to_bytes
from klvdata.misb0601 import (
    MissionID,
    PlatformHeadingAngle,
    PrecisionTimeStamp,
    SensorHorizontalFieldOfView,
    SensorLatitude,
    SensorLongitude,
    SensorRelativeAzimuthAngle,
    SensorRelativeElevationAngle,
    SensorTrueAltitude,
    SlantRange,
    TargetLocationElevation,
    TargetLocationLatitude,
    TargetLocationLongitude,
    UASLocalMetadataSet,
)

log = logging.getLogger(__name__)


@dataclass
class TelemetrySnapshot:
    """Single-frame-friendly telemetry for KLV + HUD."""

    ts_utc: datetime
    deployment: str
    mission_id: str
    sensor_lat: float
    sensor_lon: float
    sensor_hae_m: float
    rho_deg: float | None
    tau_deg: float | None
    hfov_deg: float | None
    zoom: int | None
    slant_range_m: float | None
    tgt_lat: float | None
    tgt_lon: float | None
    tgt_hae_m: float | None
    tgt_id: str | None
    tgt_callsign: str | None


def _bytes(el: Any) -> bytes:
    return bytes(el)


def build_uas_packet(snap: TelemetrySnapshot) -> bytes:
    """
    One complete UAS Datalink Local Set (16-byte UL + BER length + body).
    Omits optional checksum (tag 1); many demuxers still accept the UL + keys.
    """
    now = snap.ts_utc
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    parts: list[bytes] = [_bytes(PrecisionTimeStamp(datetime_to_bytes(now)))]

    mid = (snap.mission_id or snap.deployment or "SkyScan")[:127]
    if mid:
        parts.append(_bytes(MissionID(mid)))

    parts.append(_bytes(SensorLatitude(snap.sensor_lat)))
    parts.append(_bytes(SensorLongitude(snap.sensor_lon)))
    parts.append(_bytes(SensorTrueAltitude(snap.sensor_hae_m)))

    if snap.rho_deg is not None:
        try:
            parts.append(
                _bytes(SensorRelativeAzimuthAngle(float(snap.rho_deg)))
            )
        except Exception as e:
            log.debug("KLV skip SensorRelativeAzimuthAngle: %s", e)
    if snap.tau_deg is not None:
        try:
            parts.append(
                _bytes(SensorRelativeElevationAngle(float(snap.tau_deg)))
            )
        except Exception as e:
            log.debug("KLV skip SensorRelativeElevationAngle: %s", e)
    if snap.hfov_deg is not None:
        try:
            parts.append(
                _bytes(SensorHorizontalFieldOfView(float(snap.hfov_deg)))
            )
        except Exception as e:
            log.debug("KLV skip SensorHorizontalFieldOfView: %s", e)

    if snap.tgt_lat is not None:
        parts.append(_bytes(TargetLocationLatitude(float(snap.tgt_lat))))
    if snap.tgt_lon is not None:
        parts.append(_bytes(TargetLocationLongitude(float(snap.tgt_lon))))
    if snap.tgt_hae_m is not None:
        parts.append(_bytes(TargetLocationElevation(float(snap.tgt_hae_m))))

    if snap.slant_range_m is not None and snap.slant_range_m >= 0:
        sr = min(float(snap.slant_range_m), 5e6)
        parts.append(_bytes(SlantRange(sr)))

    if snap.rho_deg is not None:
        try:
            parts.append(_bytes(PlatformHeadingAngle(float(snap.rho_deg))))
        except Exception as e:
            log.debug("KLV skip PlatformHeadingAngle: %s", e)

    body = b"".join(parts)
    ul = UASLocalMetadataSet.key
    return ul + ber_encode(len(body)) + body
