"""Tests for field-lock boresight calibration helpers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.calibration_lock import compute_offsets, update_axis_ptz_env, update_waypoint_yaml
from lib.calibration_waypoints import get_waypoint, load_waypoints


def test_compute_offsets_from_observed_minus_model():
    off_az, off_el = compute_offsets(74.51, 1.6, 97.62, 3.33)
    assert abs(off_az - (-23.11)) < 0.02
    assert abs(off_el - (-1.73)) < 0.02


def test_commanded_angles_for_tracking_loop():
    """Rate-loop target = model rho/tau + boresight (same as initial slew)."""
    rho_model, tau_model = 97.62, 3.33
    off_az, off_el = compute_offsets(74.51, 1.6, rho_model, tau_model)
    rho_cmd = rho_model + off_az
    tau_cmd = tau_model + off_el
    assert abs(rho_cmd - 74.51) < 0.02
    assert abs(tau_cmd - 1.6) < 0.02
    # Camera at lock: zero tracking delta vs commanded angles
    camera_rho, camera_tau = 74.51, 1.6
    delta_rho = ((rho_cmd - camera_rho + 180) % 360) - 180
    delta_tau = tau_cmd - camera_tau
    assert abs(delta_rho) < 0.02
    assert abs(delta_tau) < 0.02


def test_update_axis_ptz_env_sets_boresight_keys(tmp_path):
    env_path = tmp_path / "axis-ptz-controller.env"
    env_path.write_text("USE_CAMERA=True\nBORESIGHT_OFFSET_AZ_DEG=0.0\n", encoding="utf-8")
    update_axis_ptz_env(env_path, -23.1149, -1.7297)
    text = env_path.read_text(encoding="utf-8")
    assert "BORESIGHT_OFFSET_AZ_DEG=-23.1149" in text
    assert "BORESIGHT_OFFSET_EL_DEG=-1.7297" in text


def test_update_waypoint_yaml_known_good_and_offsets(tmp_path):
    yaml_path = tmp_path / "calibration_waypoints.yaml"
    yaml_path.write_text(
        "waypoints:\n"
        "  - id: sutro_tower\n"
        "    label: Sutro\n"
        "    lat: 37.75525\n"
        "    lon: -122.45289\n"
        "    alt_m: 297\n"
        "    known_good: false\n",
        encoding="utf-8",
    )
    update_waypoint_yaml(
        yaml_path,
        "sutro_tower",
        offset_az=-23.1149,
        offset_el=-1.7297,
        osd_az=74.51,
        osd_el=1.6,
        rho_observed=74.51,
        tau_observed=1.6,
    )
    waypoint = get_waypoint(str(yaml_path), "sutro_tower")
    assert waypoint is not None
    assert waypoint["known_good"] is True
    assert waypoint["calibrated_boresight_az_deg"] == -23.1149
    assert waypoint["calibrated_boresight_el_deg"] == -1.7297
    assert "Field lock" in waypoint["notes"]
    assert len(load_waypoints(str(yaml_path))) == 1
