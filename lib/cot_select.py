"""CoT / ledger row filters for SkyScan target selection."""

from __future__ import annotations

import fnmatch
import os


def _parse_allow_type_globs() -> tuple[str, ...]:
    """Optional extra allow patterns (fnmatch on full type). Unset = MITRE token check only."""
    raw = os.environ.get("SKYSCAN_COT_ALLOW_TYPE_GLOBS", "").strip()
    if not raw:
        return ()
    return tuple(x.strip() for x in raw.split(",") if x.strip())


def cot_event_type_selectable(cot_event_type: str | None) -> bool:
    """True when CoT MITRE SIDC 3rd token is air (A) or surface (S)."""
    t = (cot_event_type or "").strip()
    if not t:
        return False
    parts = t.split("-")
    if len(parts) >= 3 and parts[2] in ("A", "S"):
        return True
    for pat in _parse_allow_type_globs():
        if pat and fnmatch.fnmatchcase(t, pat):
            return True
    return False


def ledger_row_selectable(
    object_type: str | None,
    cot_event_type: str | None = None,
) -> bool:
    """ADS-B / non-CoT rows are selectable; CoT rows only if air or surface type."""
    ot = (object_type or "").strip().lower()
    if ot != "cot":
        return True
    return cot_event_type_selectable(cot_event_type)
