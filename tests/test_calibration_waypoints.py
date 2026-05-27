"""Tests for calibration waypoint loading and C2 synthetic payloads."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skyscan-c2"))

from c2_pub_sub import C2PubSub
from lib.calibration_waypoints import get_waypoint, waypoint_offsets


WAYPOINTS_FILE = (
    Path(__file__).resolve().parents[1] / "config" / "calibration_waypoints.yaml"
)


def test_get_sutro_waypoint():
    waypoint = get_waypoint(str(WAYPOINTS_FILE), "sutro_tower")
    assert waypoint is not None
    assert float(waypoint["lat"]) == 37.75525
    assert float(waypoint["lon"]) == -122.45289


def test_get_mill_valley_qmv_waypoint():
    waypoint = get_waypoint(str(WAYPOINTS_FILE), "mill_valley_qmv")
    assert waypoint is not None
    assert float(waypoint["lat"]) == 37.92397
    assert float(waypoint["lon"]) == -122.59718
    assert float(waypoint["alt_m"]) == 723


def test_waypoint_offsets_default_to_zero():
    waypoint = {"id": "sutro_tower"}
    az, el = waypoint_offsets(waypoint)
    assert az == 0.0
    assert el == 0.0


def test_build_calibration_selected_object_shape():
    c2 = C2PubSub.__new__(C2PubSub)
    c2.device_latitude = 37.76
    c2.device_longitude = -122.4975
    c2._calculate_camera_angles = lambda _data: (98.0, 3.0, 4500.0)
    c2._relative_distance_meters = lambda *_args: 4420.0
    waypoint = {
        "id": "sutro_tower",
        "label": "Sutro Tower (San Francisco)",
        "lat": 37.75525,
        "lon": -122.45289,
        "alt_m": 297.0,
        "calibrated_boresight_az_deg": 1.5,
        "calibrated_boresight_el_deg": -0.5,
    }
    payload = c2._build_calibration_selected_object(waypoint)
    assert payload is not None
    assert payload["object_id"] == "cal-sutro_tower"
    assert payload["object_type"] == "calibration_waypoint"
    assert payload["camera_pan"] == 99.5
    assert payload["camera_tilt"] == 2.5
    assert payload["horizontal_velocity"] == 0.0
    assert payload["vertical_velocity"] == 0.0
