"""Field calibration: observed camera lock vs model pointing offsets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.calibration_waypoints import get_waypoint, load_waypoints


@dataclass
class CalibrationResult:
    waypoint_id: str
    rho_observed: float
    tau_observed: float
    az_observed: float
    el_observed: float
    rho_calc: float
    tau_calc: float
    offset_az_deg: float
    offset_el_deg: float
    geodesic_bearing_deg: float
    geodesic_elevation_deg: float
    zoom: int | None = None
    focus: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "waypoint_id": self.waypoint_id,
            "rho_observed": self.rho_observed,
            "tau_observed": self.tau_observed,
            "az_observed": self.az_observed,
            "el_observed": self.el_observed,
            "rho_calc": self.rho_calc,
            "tau_calc": self.tau_calc,
            "offset_az_deg": self.offset_az_deg,
            "offset_el_deg": self.offset_el_deg,
            "geodesic_bearing_deg": self.geodesic_bearing_deg,
            "geodesic_elevation_deg": self.geodesic_elevation_deg,
            "zoom": self.zoom,
            "focus": self.focus,
        }


def compute_offsets(
    rho_observed: float,
    tau_observed: float,
    rho_calc: float,
    tau_calc: float,
) -> tuple[float, float]:
    """Boresight offsets applied after Object.recompute_location (degrees)."""
    return (float(rho_observed) - float(rho_calc), float(tau_observed) - float(tau_calc))


def _set_env_value(text: str, key: str, value: float) -> str:
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    line = f"{key}={value:.4f}"
    if pattern.search(text):
        return pattern.sub(line, text, count=1)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + line + "\n"


def update_axis_ptz_env(path: Path, offset_az: float, offset_el: float) -> None:
    text = path.read_text(encoding="utf-8")
    text = _set_env_value(text, "BORESIGHT_OFFSET_AZ_DEG", offset_az)
    text = _set_env_value(text, "BORESIGHT_OFFSET_EL_DEG", offset_el)
    path.write_text(text, encoding="utf-8")


def update_waypoint_yaml(
    path: Path,
    waypoint_id: str,
    *,
    offset_az: float,
    offset_el: float,
    osd_az: float,
    osd_el: float,
    rho_observed: float,
    tau_observed: float,
    notes: str | None = None,
) -> None:
    """Update or append waypoint calibration audit fields in YAML."""
    waypoints = load_waypoints(str(path))
    found = False
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    note = notes or (
        f"Field lock {stamp} OSD {osd_az:.2f}/{osd_el:.2f} "
        f"rho/tau {rho_observed:.2f}/{tau_observed:.2f}; "
        f"offsets in axis-ptz-controller.env"
    )
    for wp in waypoints:
        if str(wp.get("id", "")).strip() == waypoint_id:
            wp["known_good"] = True
            wp["calibrated_boresight_az_deg"] = round(offset_az, 4)
            wp["calibrated_boresight_el_deg"] = round(offset_el, 4)
            wp["notes"] = note
            found = True
            break
    if not found:
        raise ValueError(f"Waypoint {waypoint_id!r} not found in {path}")

    lines = ["waypoints:"]
    for wp in waypoints:
        lines.append(f"  - id: {wp['id']}")
        for key, val in wp.items():
            if key == "id":
                continue
            if isinstance(val, bool):
                lines.append(f"    {key}: {'true' if val else 'false'}")
            elif isinstance(val, (int, float)):
                lines.append(f"    {key}: {val}")
            else:
                lines.append(f"    {key}: {val}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def build_result(
    waypoint_id: str,
    waypoint: dict[str, Any],
    observer: dict[str, float],
    *,
    pan_obs: float,
    tilt_obs: float,
    zoom: int | None,
    focus: int | None,
    rho_calc: float,
    tau_calc: float,
) -> CalibrationResult:
    from lib.ground_pointing import target_az_el

    tgt = {
        "lat": float(waypoint["lat"]),
        "lon": float(waypoint["lon"]),
        "alt_m": float(waypoint.get("alt_m", 0.0)),
    }
    geo_az, geo_el = target_az_el(observer, tgt)
    off_az, off_el = compute_offsets(pan_obs, tilt_obs, rho_calc, tau_calc)
    return CalibrationResult(
        waypoint_id=waypoint_id,
        rho_observed=pan_obs,
        tau_observed=tilt_obs,
        az_observed=pan_obs,
        el_observed=tilt_obs,
        rho_calc=rho_calc,
        tau_calc=tau_calc,
        offset_az_deg=off_az,
        offset_el_deg=off_el,
        geodesic_bearing_deg=geo_az,
        geodesic_elevation_deg=geo_el,
        zoom=zoom,
        focus=focus,
    )
