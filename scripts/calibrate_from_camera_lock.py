#!/usr/bin/env python3
"""Field calibration: lock camera on a waypoint, compute boresight offsets, optional --write."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.calibration_lock import (  # noqa: E402
    build_result,
    update_axis_ptz_env,
    update_waypoint_yaml,
)
from lib.calibration_waypoints import get_waypoint  # noqa: E402

CONTAINER_SCRIPT = r'''
import json
import os
import sys
import time

from camera import Camera
from camera_control import CameraControl
from object import Object

def main():
    args = json.loads(sys.argv[1])
    waypoint_id = args["waypoint_id"]
    osd_az = args.get("osd_az")
    osd_el = args.get("osd_el")
    waypoints_file = args["waypoints_file"]

    # load waypoint coords from env-mounted path or baked defaults
    lat = float(args.get("lat", 37.75525))
    lon = float(args.get("lon", -122.45289))
    alt_m = float(args.get("alt_m", 297))

    tripod_lat = float(os.environ["TRIPOD_LATITUDE"])
    tripod_lon = float(os.environ["TRIPOD_LONGITUDE"])
    tripod_alt = float(os.environ["TRIPOD_ALTITUDE"])
    yaw = float(os.environ.get("TRIPOD_YAW", 0))
    pitch = float(os.environ.get("TRIPOD_PITCH", 0))
    roll = float(os.environ.get("TRIPOD_ROLL", 0))

    cc = CameraControl(
        os.environ["CAMERA_IP"],
        os.environ["CAMERA_USER"],
        os.environ["CAMERA_PASSWORD"],
    )
    pan, tilt, zoom, focus = cc.get_ptz()

    if osd_az is not None:
        pan = float(osd_az)
    if osd_el is not None:
        tilt = float(osd_el)

    cam = Camera(
        camera_ip=os.environ["CAMERA_IP"],
        camera_user=os.environ["CAMERA_USER"],
        camera_password=os.environ["CAMERA_PASSWORD"],
        tripod_longitude=tripod_lon,
        tripod_latitude=tripod_lat,
        tripod_altitude=tripod_alt,
        tripod_yaw=yaw,
        tripod_pitch=pitch,
        tripod_roll=roll,
        use_camera=False,
    )
    obj = Object(f"cal-{waypoint_id}", cam)
    obj.update_from_msg(
        {
            "object_id": f"cal-{waypoint_id}",
            "object_type": "calibration_waypoint",
            "timestamp": time.time(),
            "latitude": lat,
            "longitude": lon,
            "altitude": alt_m,
            "track": 0.0,
            "horizontal_velocity": 0.0,
            "vertical_velocity": 0.0,
        }
    )
    obj.recompute_location()

    out = {
        "waypoint_id": waypoint_id,
        "pan_observed": pan,
        "tilt_observed": tilt,
        "zoom": int(zoom),
        "focus": int(focus),
        "rho_calc": float(obj.rho),
        "tau_calc": float(obj.tau),
        "tripod_lat": tripod_lat,
        "tripod_lon": tripod_lon,
        "tripod_alt": tripod_alt,
        "waypoints_file": waypoints_file,
    }
    print(json.dumps(out))

if __name__ == "__main__":
    main()
'''


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.split("#", 1)[0].strip()
    return values


def _run_in_controller(
    container: str,
    waypoint: dict,
    waypoint_id: str,
    waypoints_file: str,
    osd_az: float | None,
    osd_el: float | None,
) -> dict:
    payload = {
        "waypoint_id": waypoint_id,
        "lat": float(waypoint["lat"]),
        "lon": float(waypoint["lon"]),
        "alt_m": float(waypoint.get("alt_m", 0.0)),
        "osd_az": osd_az,
        "osd_el": osd_el,
        "waypoints_file": waypoints_file,
    }
    proc = subprocess.run(
        ["docker", "exec", container, "python3", "-c", CONTAINER_SCRIPT, json.dumps(payload)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"Controller calibration failed:\n{proc.stderr}\n{proc.stdout}"
        )
    line = proc.stdout.strip().splitlines()[-1]
    return json.loads(line)


def _print_report(result) -> None:
    print(f"Waypoint: {result.waypoint_id}")
    print(
        f"  Geodesic (reference): bearing={result.geodesic_bearing_deg:.2f}° "
        f"elevation={result.geodesic_elevation_deg:.2f}°"
    )
    print(
        f"  Observed (camera):    pan/rho={result.rho_observed:.2f}° "
        f"tilt/tau={result.tau_observed:.2f}°"
    )
    if result.zoom is not None:
        print(f"  Zoom/focus:           {result.zoom} / {result.focus}")
    print(
        f"  Model (no offset):    rho={result.rho_calc:.2f}° tau={result.tau_calc:.2f}°"
    )
    print(
        f"  Boresight offsets:    AZ={result.offset_az_deg:+.4f}° EL={result.offset_el_deg:+.4f}°"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Field calibration from camera lock")
    parser.add_argument("--waypoint", default="sutro_tower")
    parser.add_argument("--osd-az", type=float, default=None, help="OSD pan/az lock (deg)")
    parser.add_argument("--osd-el", type=float, default=None, help="OSD tilt/el lock (deg)")
    parser.add_argument(
        "--waypoints-file",
        default=str(REPO_ROOT / "config" / "calibration_waypoints.yaml"),
    )
    parser.add_argument("--container", default="skyscan-controller-1")
    parser.add_argument("--write", action="store_true", help="Update env + waypoint YAML")
    parser.add_argument(
        "--axis-env",
        default=str(REPO_ROOT / "axis-ptz-controller.env"),
    )
    args = parser.parse_args()

    wp_path = Path(args.waypoints_file)
    waypoint = get_waypoint(str(wp_path), args.waypoint)
    if waypoint is None:
        raise SystemExit(f"Waypoint {args.waypoint!r} not found in {wp_path}")

    raw = _run_in_controller(
        args.container,
        waypoint,
        args.waypoint,
        str(wp_path),
        args.osd_az,
        args.osd_el,
    )

    dotenv = _read_dotenv(REPO_ROOT / ".env")
    observer = {
        "latitude": float(raw["tripod_lat"]),
        "longitude": float(raw["tripod_lon"]),
        "altitude_m": float(raw["tripod_alt"]),
    }

    result = build_result(
        args.waypoint,
        waypoint,
        observer,
        pan_obs=float(raw["pan_observed"]),
        tilt_obs=float(raw["tilt_observed"]),
        zoom=int(raw.get("zoom", 0)) or None,
        focus=int(raw.get("focus", 0)) or None,
        rho_calc=float(raw["rho_calc"]),
        tau_calc=float(raw["tau_calc"]),
    )

    _print_report(result)

    if args.write:
        axis_env = Path(args.axis_env)
        update_axis_ptz_env(
            axis_env, result.offset_az_deg, result.offset_el_deg
        )
        update_waypoint_yaml(
            wp_path,
            args.waypoint,
            offset_az=result.offset_az_deg,
            offset_el=result.offset_el_deg,
            osd_az=result.az_observed,
            osd_el=result.el_observed,
            rho_observed=result.rho_observed,
            tau_observed=result.tau_observed,
        )
        print(f"\nWrote {axis_env} and {wp_path}")
        print(
            "Reload controller: docker compose build controller && "
            "docker compose up -d controller"
        )
    else:
        print("\nDry run (no files changed). Re-run with --write to persist.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
