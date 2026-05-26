"""Tests for lib.equatorial (RA/Dec boresight)."""

from lib.equatorial import altaz_to_radec, boresight_equatorial, equatorial_from_tripod_los

OBSERVER = {
    "latitude": 37.7749,
    "longitude": -122.4194,
    "altitude_m": 0.0,
}


def test_altaz_to_radec_south_horizon():
    ra, dec = altaz_to_radec(180.0, 0.0, 1_700_000_000.0, OBSERVER)
    assert 0 <= ra < 360
    assert -90 <= dec <= 90


def test_boresight_equatorial_returns_galactic():
    eq = boresight_equatorial(
        {"lat": OBSERVER["latitude"], "lon": OBSERVER["longitude"], "alt": 0},
        {"azimuth": 174.0, "elevation": 23.0},
        1_700_000_000.0,
    )
    assert eq is not None
    assert "ra_deg" in eq
    assert "dec_deg" in eq
    assert "galactic_l_deg" in eq
    assert "galactic_b_deg" in eq


def test_boresight_equatorial_missing_gps():
    assert (
        boresight_equatorial(
            {},
            {"azimuth": 90.0, "elevation": 10.0},
            1_700_000_000.0,
        )
        is None
    )


def test_equatorial_from_tripod_los():
    eq = equatorial_from_tripod_los(
        lat=37.7749,
        lon=-122.4194,
        alt_m=65.0,
        az_deg=90.0,
        el_deg=5.0,
        timestamp=1_700_000_000.0,
    )
    assert eq is not None
    assert abs(eq["dec_deg"]) < 90
