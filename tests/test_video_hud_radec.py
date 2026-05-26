"""Tests for video HUD RA/Dec lines."""

from datetime import datetime, timezone

from video.hud import format_hud_text
from video.klv_builder import TelemetrySnapshot


def _snap(**kwargs) -> TelemetrySnapshot:
    base = dict(
        ts_utc=datetime(2024, 3, 10, 12, 0, 0, tzinfo=timezone.utc),
        deployment="roof_sf",
        mission_id="roof_sf",
        sensor_lat=37.76,
        sensor_lon=-122.4975,
        sensor_hae_m=65.0,
        rho_deg=304.0,
        tau_deg=3.0,
        hfov_deg=55.0,
        zoom=3000,
        slant_range_m=10000.0,
        tgt_lat=None,
        tgt_lon=None,
        tgt_hae_m=None,
        tgt_callsign=None,
        tgt_icao=None,
        tgt_track_deg=None,
        tgt_gs_mps=None,
        tgt_vs_mps=None,
        tgt_squawk=None,
        tgt_object_type=None,
        tgt_rel_dist_m=None,
        ra_deg=None,
        dec_deg=None,
        galactic_l_deg=None,
        galactic_b_deg=None,
    )
    base.update(kwargs)
    return TelemetrySnapshot(**base)


def test_format_hud_includes_radec_and_galactic():
    text = format_hud_text(
        _snap(
            ra_deg=123.45,
            dec_deg=12.34,
            galactic_l_deg=174.0,
            galactic_b_deg=-5.0,
        )
    )
    assert "RA  123.45 DEG" in text
    assert "DEC +12.34 DEG" in text
    assert "GAL L" in text
    assert "LOS AZ" in text


def test_format_hud_omits_radec_when_unset():
    text = format_hud_text(_snap())
    assert "RA " not in text
    assert "DEC " not in text
