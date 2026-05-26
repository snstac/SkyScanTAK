# Calibration Waypoints

This workflow lets you slew the camera to a known landmark (for example `sutro_tower`) using the same C2 `Selected Object` pipeline used for live tracking.

## Files and settings

- Waypoints catalog: `config/calibration_waypoints.yaml`
- C2 env: `skyscan-c2.env` (`CALIBRATION_WAYPOINTS_FILE=/config/calibration_waypoints.yaml`)
- Controller optional offsets: `axis-ptz-controller.env` (`BORESIGHT_OFFSET_AZ_DEG`, `BORESIGHT_OFFSET_EL_DEG`)
- MQTT topic: `MANUAL_OVERRIDE_TOPIC`

## Field lock (OSD dead-on)

When the landmark is centered manually, record the Axis OSD pan/tilt and derive controller boresight offsets (the PTZ controller slews on `Object` **rho/tau**, not geodesic bearing).

1. Aim at the landmark and note OSD values (for example Sutro: **74.51° / 1.6°**).
2. Preview offsets (read-only; runs inside the controller container):

```bash
python3 scripts/calibrate_from_camera_lock.py \
  --waypoint sutro_tower --osd-az 74.51 --osd-el 1.6
```

3. Apply offsets to `axis-ptz-controller.env` and audit fields in `config/calibration_waypoints.yaml`:

```bash
python3 scripts/calibrate_from_camera_lock.py \
  --waypoint sutro_tower --osd-az 74.51 --osd-el 1.6 --write
```

4. Recreate the controller so `env_file` and the patched `axis_ptz_controller.py` are loaded (a plain `restart` does not reload env):

```bash
docker compose build controller
docker compose up -d controller
```

5. Enable calibration and confirm auto-slew returns to the lock pose (~74.51° / ~1.6° for Sutro):

```bash
python scripts/slew_calibration_waypoint.py --id sutro_tower --mqtt-host 127.0.0.1
```

Controller logs should show `Absolute move to pan: ~74.51` (model rho ~97.6° plus `BORESIGHT_OFFSET_AZ_DEG` ~ -23.1°).

**Verified (roof_sf, 2026-05-26):** field lock OSD 74.51/1.6 → offsets AZ -23.1149°, EL -1.7297°; `CalibrationWaypoint: sutro_tower` slews dead-on without manual pan.

## Plane tracking

Aircraft follow uses the same controller path: C2 publishes `Selected Object` with lat/lon/alt; the controller runs `Object.recompute_location()` and slews on **rho/tau plus boresight**.

- **Controller offsets:** `BORESIGHT_OFFSET_AZ_DEG` / `BORESIGHT_OFFSET_EL_DEG` in `axis-ptz-controller.env` (required for tracking). YAML `calibrated_boresight_*` is audit/C2 metadata only.
- **Rate loop:** Boresight must apply to both the initial absolute slew and the continuous tracking loop (`_commanded_rho_tau()` in `axis_ptz_controller.py`). Without that, the camera drifts toward uncorrected model angles after acquisition.
- **Deploy:** After changing offsets or controller code, run `docker compose build controller && docker compose up -d controller` (not `restart` alone).
- **Enable tracking:** `docker compose start skyscan-c2`, clear calibration (`CalibrationWaypoint: null`), and let C2 select a ledger target.

## Field procedure (iterative TRIPOD_YAW)

1. Start calibration mode:

```bash
python scripts/slew_calibration_waypoint.py --id sutro_tower --mqtt-host 127.0.0.1
```

2. Verify the stream: open the video feed and check whether Sutro Tower is centered.
3. Adjust `TRIPOD_YAW` in `.env` in small steps (typically 0.5 to 2.0 degrees).
4. Restart the relevant services:

```bash
docker compose restart controller skyscan-c2
```

5. Repeat until the landmark is centered.
6. Optional fine tuning:
   - Set global controller offsets in `axis-ptz-controller.env`.
   - Or add per-waypoint `calibrated_boresight_az_deg` / `calibrated_boresight_el_deg` in `config/calibration_waypoints.yaml`.
7. Exit calibration mode:

```bash
python scripts/slew_calibration_waypoint.py --clear --mqtt-host 127.0.0.1
```

## Manual MQTT examples

Enable waypoint mode:

```bash
mosquitto_pub -h 127.0.0.1 -t "/skyscan/roof_sf/Manual_Override/skyscan-c2/JSON" -m '{"CalibrationWaypoint":"sutro_tower"}'
```

Disable waypoint mode:

```bash
mosquitto_pub -h 127.0.0.1 -t "/skyscan/roof_sf/Manual_Override/skyscan-c2/JSON" -m '{"CalibrationWaypoint":null}'
```
