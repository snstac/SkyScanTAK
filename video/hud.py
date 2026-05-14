"""HUD overlay text for FFmpeg drawtext textfile (MQTT-driven fields).

Layout and palette are tuned to match public FIRIS stills (e.g. wildfire FMV):
neon green monospace, no panel, corner-cluster style copy — see news stills
linked from operator references. ``:`` and ``'`` must survive FFmpeg drawtext
parsing (colons escaped below).
"""

from __future__ import annotations

import math
from datetime import timezone

from video.klv_builder import TelemetrySnapshot

_M_TO_FT = 3.280839895
_M_TO_NM = 0.000539956803


def _lat_dm(dec: float) -> str:
    hemi = "N" if dec >= 0 else "S"
    a = abs(float(dec))
    deg = int(math.floor(a))
    minutes = (a - deg) * 60.0
    return f"{deg}°{minutes:07.4f}' {hemi}"


def _lon_dm(dec: float) -> str:
    hemi = "E" if dec >= 0 else "W"
    a = abs(float(dec))
    deg = int(math.floor(a))
    minutes = (a - deg) * 60.0
    return f"{deg}°{minutes:07.4f}' {hemi}"


def format_hud_text(s: TelemetrySnapshot) -> str:
    """Build multiline OSD text (FIRIS-style clusters). Escape ``:`` for drawtext."""
    tu = s.ts_utc.astimezone(timezone.utc)
    date_time = tu.strftime("%m/%d/%y %H:%M:%S") + " Z"

    lines: list[str] = [
        f"SKYSCAN  {s.deployment.upper()}",
        date_time,
        "",
        _lat_dm(s.sensor_lat),
        _lon_dm(s.sensor_lon),
        f"ALT {s.sensor_hae_m * _M_TO_FT:.0f} FT",
    ]

    if s.tgt_lat is not None and s.tgt_lon is not None:
        lines.append("")
        lines.append("LRF TARGET")
        lines.append(_lat_dm(s.tgt_lat))
        lines.append(_lon_dm(s.tgt_lon))
        if s.tgt_hae_m is not None:
            lines.append(f"ELV {s.tgt_hae_m * _M_TO_FT:.0f} FT")
        if s.slant_range_m is not None:
            lines.append(f"SLT {s.slant_range_m * _M_TO_NM:.1f} NM")
    elif s.slant_range_m is not None:
        lines.append("")
        lines.append(f"SLT {s.slant_range_m * _M_TO_NM:.1f} NM")

    if s.tgt_callsign or s.tgt_id:
        cs = (s.tgt_callsign or "").strip().upper()
        tid = (s.tgt_id or "").strip().upper()
        tag = f"{cs} {tid}".strip()
        if tag:
            lines.append("")
            lines.append(f"TRACK {tag}")

    if s.rho_deg is not None and s.tau_deg is not None:
        lines.append("")
        lines.append(f"LOS AZ {s.rho_deg:6.1f}  EL {s.tau_deg:+5.1f} DEG")

    if s.hfov_deg is not None:
        lines.append(f"HFOV {s.hfov_deg:4.1f} DEG")

    if s.zoom is not None:
        lines.append(f"ZOOM {s.zoom}")

    raw = "\n".join(lines) + "\n"
    return raw.replace(":", "\\:")
