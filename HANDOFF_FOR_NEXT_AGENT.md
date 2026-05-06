# Handoff: SkyScan fork — CoT bridge, TAKX, deployment tweaks

This note is for the **next agent or maintainer** working in this repository. It summarizes what changed, where to look, and sensible follow-ups.

## Quick start

1. Copy [`skyscan.env`](skyscan.env) → `.env` and fill deployment, tripod lat/lon/alt, **`TRIPOD_YAW` / `TRIPOD_PITCH` / `TRIPOD_ROLL`** (required by `iqtlabs/edgetech-axis-ptz-controller:v2.0`; do not use `YAW`/`PITCH`/`ROLL`).
2. Tune module env files: [`axis-ptz-controller.env`](axis-ptz-controller.env), [`dump1090-json.env`](dump1090-json.env), [`cot-bridge.env`](cot-bridge.env), etc.
3. `docker compose pull && docker compose up -d`  
   Rebuild local CoT image after Python edits: `docker compose build cot-bridge && docker compose up -d cot-bridge --force-recreate`

**MQTT on host:** compose maps **1884→1883** and **9002→9001** when default ports conflict.

## `cot-bridge` service (Cursor on Target)

- **Source:** [`cot/bridge/main.py`](cot/bridge/main.py) (Docker build context [`cot/bridge`](cot/bridge)).
- **Docs:** [`cot/bridge/README.md`](cot/bridge/README.md) — Logger envelope, sensor FOV, aircraft SPI, **FOV polygon**.
- **Compose:** [`docker-compose.yaml`](docker-compose.yaml) service `cot-bridge`; `env_file`: `.env`, [`cot-bridge.env`](cot-bridge.env).

### UDP outputs (same `COT_UDP_HOST` / `COT_UDP_PORT`)

| Stream | Stable `uid` (typical) | Notes |
|--------|------------------------|--------|
| PTZ sensor | `COT_UID` | Mapping sensor event; `<sensor>` with az/el/fov/range |
| Equipment | same as `COT_UID` | `COT_EQUIP_TYPE` (e.g. `a-f-G-E-S-E`), periodic |
| Aircraft | `{COT_UID}-adsb-{icao}` | From `OBJECT_TOPIC` / Selected Object; `COT_AIR_TYPE` default `b-m-p-s-p-i` |
| FOV polygon | `COT_FOV_UID` default `{COT_UID}-fov` | TAK **`u-d-f`** + `<link point="lat,lon">` by default; **`COT_FOV_FORMAT=mitre`** → `<shape><polyline closed="true">` |

TAKX may ignore `<sensor>` FOV attributes; the **FOV polygon** is the TAK-friendly footprint.

### Geometry note

FOV quad uses spherical-Earth geodesics, horizontal FOV vs zoom, `distance` from Logger when present, else `COT_FOV_DEFAULT_RANGE_M`.

## Reference material under `cot/`

[`cot/takcot-master/`](cot/takcot-master/) holds MITRE CoT XSDs and examples (large tree ~tens of MB). It is reference-only for schema alignment, not runtime for the bridge.

## Deployment assumptions in this fork

- **PiAware** may be absent from compose; **dump1090-json** can target external **tar1090** / `aircraft.json` (see [`dump1090-json.env`](dump1090-json.env)).
- Prior debugging used **multicast** vs **unicast** CoT targets; [`cot-bridge.env`](cot-bridge.env) is the single place to set destination and optional `COT_MULTICAST_TTL`.

## Git / save state

After edits, maintainers should commit with a clear message, e.g.  
`Add CoT bridge with TAK FOV polygon, aircraft SPI, compose and env updates`

**Do not commit `.env`** (gitignored); keep secrets only in local `.env`.

## Open follow-ups (optional)

- Confirm TAKX renders both **`tak`** (`u-d-f`) and **`mitre`** FOV formats in your build; adjust defaults if only one works.
- **Delete / stale** behavior when C2 sends empty Selected Object (air marker may age out via `stale` only).
- If `cot/takcot-master` is too heavy for the main repo, consider a submodule or download script instead of vendoring.
