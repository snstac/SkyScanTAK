#!/usr/bin/env python3
"""Publish CalibrationWaypoint override messages for skyscan-c2."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import paho.mqtt.client as mqtt

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.calibration_waypoints import get_waypoint
from lib.ground_pointing import target_az_el
from video.geo import haversine_m, slant_range_m


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", dest="waypoint_id", default="")
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--mqtt-host", default=os.environ.get("MQTT_IP", "127.0.0.1"))
    parser.add_argument("--mqtt-port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    parser.add_argument(
        "--topic",
        default=os.environ.get(
            "MANUAL_OVERRIDE_TOPIC",
            "/skyscan/roof_sf/Manual_Override/skyscan-c2/JSON",
        ),
    )
    parser.add_argument(
        "--waypoints-file",
        default=os.environ.get(
            "CALIBRATION_WAYPOINTS_FILE",
            str(REPO_ROOT / "config" / "calibration_waypoints.yaml"),
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.clear:
        payload = {"CalibrationWaypoint": None}
    else:
        if not args.waypoint_id:
            parser.error("--id is required unless --clear is set")
        waypoint = get_waypoint(args.waypoints_file, args.waypoint_id)
        if waypoint is None:
            raise SystemExit(
                f"Waypoint '{args.waypoint_id}' not found in {args.waypoints_file}"
            )
        payload = {"CalibrationWaypoint": args.waypoint_id}

        dotenv = _read_dotenv(REPO_ROOT / ".env")
        observer = {
            "latitude": float(
                os.environ.get("TRIPOD_LATITUDE", dotenv.get("TRIPOD_LATITUDE", "0"))
            ),
            "longitude": float(
                os.environ.get("TRIPOD_LONGITUDE", dotenv.get("TRIPOD_LONGITUDE", "0"))
            ),
            "altitude_m": float(
                os.environ.get("TRIPOD_ALTITUDE", dotenv.get("TRIPOD_ALTITUDE", "0"))
            ),
        }
        tgt = {"lat": waypoint["lat"], "lon": waypoint["lon"], "alt_m": waypoint.get("alt_m", 0)}
        az, el = target_az_el(observer, tgt)
        horizontal_m = haversine_m(
            observer["latitude"], observer["longitude"], float(tgt["lat"]), float(tgt["lon"])
        )
        slant_m = slant_range_m(
            observer["latitude"],
            observer["longitude"],
            observer["altitude_m"],
            float(tgt["lat"]),
            float(tgt["lon"]),
            float(tgt["alt_m"]),
        )
        print(
            f"Waypoint {args.waypoint_id}: bearing={az:.2f} deg elevation={el:.2f} deg "
            f"horizontal={horizontal_m:.1f} m slant={slant_m:.1f} m"
        )

    print(f"Topic: {args.topic}")
    print(f"Payload: {payload}")
    if args.dry_run:
        return 0

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.connect(args.mqtt_host, args.mqtt_port, 60)
    result = client.publish(args.topic, json.dumps(payload), qos=0, retain=False)
    result.wait_for_publish()
    client.disconnect()
    print("Published.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
