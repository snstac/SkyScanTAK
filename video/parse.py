"""Parse EdgeTech / skyscan-c2 MQTT JSON (aligned with cot-bridge patterns)."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

_HEX_RE = re.compile(r"[0-9a-fA-F]")


def extract_icao_hex(object_id: Any) -> str | None:
    """Mode-S / ICAO hex from object_id (e.g. cot-icao-a1c90e → A1C90E, else last 6 hex)."""
    if object_id is None:
        return None
    s = str(object_id).strip()
    if not s:
        return None
    low = s.lower()
    if low.startswith("cot-icao-"):
        part = s[9:].strip()
        return part.upper() if part else None
    if low.startswith("cot-"):
        return None
    hex_chars = _HEX_RE.findall(s)
    if len(hex_chars) >= 6:
        return "".join(hex_chars[-6:]).upper()
    if hex_chars:
        return "".join(hex_chars).upper()
    return None


def extract_logger_inner(outer: Mapping[str, Any]) -> dict[str, Any] | None:
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


def parse_camera_pointing(payload: str) -> dict[str, Any] | None:
    try:
        outer = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(outer, dict):
        return None
    inner = extract_logger_inner(outer)
    if not inner:
        return None
    cp = inner.get("camera-pointing")
    if not isinstance(cp, dict):
        return None
    return cp


def _parse_selected_object_inner(raw: Any) -> dict[str, Any] | None:
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
    else:
        return None
    if not isinstance(inner, dict) or not inner:
        return None
    return inner


def parse_selected_object(payload: str) -> dict[str, Any] | None:
    try:
        outer = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(outer, dict):
        return None
    inner: dict[str, Any] | None = None
    if outer.get("data_payload_type") == "Selected Object":
        inner = _parse_selected_object_inner(outer.get("data_payload"))
    if inner is None and "Selected Object" in outer:
        inner = _parse_selected_object_inner(outer["Selected Object"])
    if inner is None and "object_id" in outer and "latitude" in outer:
        inner = outer
    return inner


def coerce_float(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def str_clean(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return ""
    return s
