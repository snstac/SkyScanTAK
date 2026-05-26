"""Calibration waypoint catalog helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _parse_scalar(value: str) -> Any:
    text = value.strip()
    if not text:
        return ""
    low = text.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none"):
        return None
    if text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def _parse_simple_waypoints_yaml(text: str) -> list[dict[str, Any]]:
    """Parse the narrow waypoints YAML shape used by this repository."""
    waypoints: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped == "waypoints:":
            continue
        if stripped.startswith("- "):
            if current:
                waypoints.append(current)
            current = {}
            remainder = stripped[2:].strip()
            if remainder:
                key, _, value = remainder.partition(":")
                current[key.strip()] = _parse_scalar(value)
            continue
        if current is None or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        current[key.strip()] = _parse_scalar(value)
    if current:
        waypoints.append(current)
    return waypoints


def load_waypoints(path: str) -> list[dict[str, Any]]:
    """Load waypoints from YAML using PyYAML when present, else fallback parser."""
    p = Path(path)
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text) or {}
        waypoints = loaded.get("waypoints", [])
        if isinstance(waypoints, list):
            return [wp for wp in waypoints if isinstance(wp, dict)]
    except Exception:
        pass
    return _parse_simple_waypoints_yaml(text)


def get_waypoint(path: str, waypoint_id: str) -> dict[str, Any] | None:
    """Return a single waypoint by id from the waypoint file."""
    wanted = (waypoint_id or "").strip()
    if not wanted:
        return None
    for wp in load_waypoints(path):
        if str(wp.get("id", "")).strip() == wanted:
            return wp
    return None


def waypoint_offsets(waypoint: dict[str, Any]) -> tuple[float, float]:
    """Return per-waypoint boresight offsets (az, el) in degrees."""
    az = waypoint.get("calibrated_boresight_az_deg", 0.0)
    el = waypoint.get("calibrated_boresight_el_deg", 0.0)
    return float(az or 0.0), float(el or 0.0)
