"""Parse EdgeTech / skyscan-c2 MQTT JSON (aligned with cot-bridge patterns)."""

from __future__ import annotations

import json
from typing import Any, Mapping


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


def parse_selected_object(payload: str) -> dict[str, Any] | None:
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
