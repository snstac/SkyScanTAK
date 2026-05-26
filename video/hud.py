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
_MPS_TO_KTS = 1.943844492
_MPS_TO_FPM = 196.850394


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


def _has_target(s: TelemetrySnapshot) -> bool:
    return any(
        (
            s.tgt_icao,
            s.tgt_callsign,
            s.tgt_lat is not None and s.tgt_lon is not None,
            s.tgt_hae_m is not None,
            s.tgt_track_deg is not None,
            s.tgt_gs_mps is not None,
            s.tgt_squawk,
            s.tgt_object_type,
            s.tgt_rel_dist_m is not None,
            s.slant_range_m is not None,
        )
    )


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

    if _has_target(s):
        lines.append("")
        lines.append("TARGET")
        if s.tgt_icao:
            lines.append(f"ICAO {s.tgt_icao}")
        tail = (s.tgt_callsign or "").strip().upper()
        if tail:
            lines.append(f"TAIL/CS {tail}")
        if s.tgt_hae_m is not None:
            lines.append(f"ALT {s.tgt_hae_m * _M_TO_FT:.0f} FT")
        if s.tgt_track_deg is not None:
            lines.append(f"BRG {s.tgt_track_deg:03.0f} T")
        if s.tgt_gs_mps is not None:
            lines.append(f"GS {s.tgt_gs_mps * _MPS_TO_KTS:.0f} KT")
        if s.tgt_vs_mps is not None and abs(s.tgt_vs_mps) >= 0.5:
            lines.append(f"VS {s.tgt_vs_mps * _MPS_TO_FPM:+.0f} FPM")
        if s.tgt_squawk:
            lines.append(f"SQK {s.tgt_squawk.strip().upper()}")
        rng_m = s.tgt_rel_dist_m
        if rng_m is None:
            rng_m = s.slant_range_m
        if rng_m is not None:
            lines.append(f"RNG {rng_m * _M_TO_NM:.1f} NM")
        if s.tgt_object_type:
            lines.append(f"TYP {s.tgt_object_type.strip().upper()}")
        if s.tgt_lat is not None and s.tgt_lon is not None:
            lines.append("")
            lines.append("TGT POS")
            lines.append(_lat_dm(s.tgt_lat))
            lines.append(_lon_dm(s.tgt_lon))
    elif s.slant_range_m is not None:
        lines.append("")
        lines.append(f"SLT {s.slant_range_m * _M_TO_NM:.1f} NM")

    if s.rho_deg is not None and s.tau_deg is not None:
        lines.append("")
        lines.append(f"LOS AZ {s.rho_deg:6.1f}  EL {s.tau_deg:+5.1f} DEG")

    if s.ra_deg is not None and s.dec_deg is not None:
        lines.append(f"RA {s.ra_deg:7.2f} DEG")
        lines.append(f"DEC {s.dec_deg:+6.2f} DEG")
        if s.galactic_l_deg is not None and s.galactic_b_deg is not None:
            gl = float(s.galactic_l_deg)
            gb = float(s.galactic_b_deg)
            gl_sign = "+" if gl >= 0 else ""
            gb_sign = "+" if gb >= 0 else ""
            lines.append(
                f"GAL L {gl_sign}{abs(gl):5.0f} B {gb_sign}{abs(gb):4.0f}"
            )

    if s.hfov_deg is not None:
        lines.append(f"HFOV {s.hfov_deg:4.1f} DEG")

    if s.zoom is not None:
        lines.append(f"ZOOM {s.zoom}")

    raw = "\n".join(lines) + "\n"
    return raw.replace(":", "\\:")
