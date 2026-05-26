"""Tests for ground target pointing helpers."""

from lib.ground_pointing import bearing_deg, elevation_deg, target_az_el


def test_roof_sf_to_sutro_bearing_and_elevation():
    az = bearing_deg(37.76, -122.4975, 37.75525, -122.45289)
    el = elevation_deg(37.76, -122.4975, 65.0, 37.75525, -122.45289, 297.0)
    assert 90.0 < az < 110.0
    assert 0.0 < el < 10.0


def test_target_az_el_dict_input():
    az, el = target_az_el(
        {"latitude": 37.76, "longitude": -122.4975, "altitude_m": 65.0},
        {"lat": 37.75525, "lon": -122.45289, "alt_m": 297.0},
    )
    assert 90.0 < az < 110.0
    assert 0.0 < el < 10.0
