# SkyScan CoT sensor bridge

Subscribes to the Axis PTZ controller **Logger** MQTT topic (`LOGGER_TOPIC` from `.env`), reads **camera-pointing** `rho_c` / `tau_c` (degrees), and emits **Cursor on Target** XML via **[PyTAK](https://github.com/snstac/pytak)** ([docs](https://pytak.readthedocs.io/)) for TAK/ATAK-style clients.

**Transport:** By default the bridge uses **`udp+wo://COT_UDP_HOST:COT_UDP_PORT`** (write-only UDP to your existing unicast or multicast address). Set **`COT_URL`** in [`cot-bridge.env`](../../cot-bridge.env) to use any PyTAK-supported scheme instead (for example **`tcp://tak.example.com:8087`**, **`tls://…`**, **`marti://…`**). Multicast TTL is taken from **`COT_MULTICAST_TTL`** and passed to PyTAK as **`PYTAK_MULTICAST_TTL`**. The bridge sets **`PYTAK_NO_HELLO=true`** so PyTAK does not inject its default hello marker (behavior matches the pre-PyTAK bridge). CoT remains **XML** (`TAK_PROTO=0`); use protobuf only if you add `takproto` and change that deliberately.

**PTZ updates:** By default the bridge sends **two** CoT events per pose (same PyTAK destination): a **mapping-sensor** event (`SENSOR_TYPE`, `<sensor>` attributes) and a **ground FOV polygon** (`u-d-f` or mitre polyline). That supports clients that only understand one representation (e.g. WinTAK vs TAKX). Toggle with **`COT_SENSOR_ENABLE`** / **`COT_FOV_ENABLE`** in [`cot-bridge.env`](../../cot-bridge.env).

## Aircraft SPI / SPOI CoT

When **`OBJECT_TOPIC`** is set (skyscan-c2 **Selected Object** topic from `.env`), the bridge emits an additional CoT whose **`point`** is the aircraft **lat/lon/hae** from that message.

| Env | Meaning |
|-----|---------|
| **`COT_AIR_TYPE`** | Default **`b-m-p-s-p-i`** (MITRE mapping / sensor / point / *interest*, i.e. SPI-style). Use **`b-m-p-s-m`** for spot-map style. |
| **`COT_AIR_ENABLE`** | `false` disables aircraft CoT (default on when `OBJECT_TOPIC` is non-empty). |
| **`COT_AIR_STALE_SECONDS`** | `stale` offset for the air marker (default 45). |
| **`COT_AIR_MAX_SEND_RATE`** | Max air CoT sends per second (default 3). |
| **`COT_AIR_UID_PREFIX`** | If set, air CoT **`uid`** is `{prefix}{icao}`; else `{COT_UID}-adsb-{icao}`. |
| **`COT_AIR_LINK_SENSOR`** | If true (default), adds **`<link uid="COT_UID" type="SENSOR_TYPE" relation="p-p"/>`** to the PTZ sensor. |

Payload: EdgeTech wrapper with **`data_payload_type`: `"Selected Object"`** and JSON **`data_payload`** (see [edgetech-skyscan-c2](https://github.com/IQTLabs/edgetech-skyscan-c2)). Empty selection (`{}`) produces no air CoT.

## FOV polygon (TAK / TAKX)

Clients such as **TAKX** may not render **`<sensor fov="..." vfov="...">`**. The bridge can send a **second** CoT (stable **`COT_FOV_UID`**, default `<COT_UID>-fov`) for the **horizontal** FOV footprint on the ground: a closed quadrilateral (near arc + far arc from the tripod), on the **same** PyTAK destination as the mapping-sensor event.

| Env | Meaning |
|-----|---------|
| **`COT_SENSOR_ENABLE`** | `false` disables the mapping-sensor CoT (`SENSOR_TYPE` with `<sensor>`). Default **`true`** (WinTAK-friendly). |
| **`COT_FOV_ENABLE`** | `false` disables the extra polygon. Default **`true`** (TAK/TAKX drawing-friendly). |
| **`COT_FOV_FORMAT`** | **`tak`** (default): TAK-style **`u-d-f`** with **`<link point="lat,lon"/>`** vertices (first point repeated to close). **`mitre`**: **`<shape><polyline closed="true"><vertex lat lon hae/>`** per MITRE shape schema. |
| **`COT_FOV_DEFAULT_RANGE_M`** | Slant range (m) when Logger **`distance`** is absent (default 10000). |
| **`COT_FOV_STALE_SECONDS`** | If unset, uses **`COT_STALE_SECONDS`**. |
| **`COT_FOV_*`** styling | **`COT_FOV_CALLSIGN`**, **`COT_FOV_FILL_COLOR`**, **`COT_FOV_STROKE_COLOR`**, **`COT_FOV_STROKE_WEIGHT`**, **`COT_FOV_HOW`** (default `h-e`). |

Geometry uses spherical-Earth geodesics from **`TRIPOD_LATITUDE` / `TRIPOD_LONGITUDE` / `TRIPOD_ALTITUDE`** and the same **`zoom`→horizontal FOV** interpolation as the sensor CoT.

## Periodic ping

A lightweight marker CoT (default type `b-m-p-s-m`, `how=h-g-i-g-o`) is sent every **`COT_PING_INTERVAL`** seconds to the same PyTAK destination, using a **separate uid** (`COT_PING_UID`, default `<COT_UID>-ping`). Set **`COT_PING_INTERVAL=0`** to disable.

## Periodic equipment sensor (`a-f-G-E-S-E`)

Every **`COT_EQUIP_INTERVAL`** seconds (default 60), the bridge sends a second CoT using **`COT_EQUIP_TYPE`** (default **`a-f-G-E-S-E`**, friendly ground equipment / sensor / electro-optical) with the **same `COT_UID`** as the mapping-sensor stream, Tripod **`point`**, and a **`<sensor>`** block with current `rho_c`/`tau_c`-equivalent azimuth/elevation, the same FOV/range/modality rules as the mapping feed. One initial event is sent at startup. Set **`COT_EQUIP_INTERVAL=0`** to disable.

## EdgeTech Logger payload

The axis-ptz-controller publishes when `LOG_TO_MQTT=True` ([`axis-ptz-controller.env`](../../axis-ptz-controller.env)). Messages are JSON with an outer EdgeTech wrapper and an inner **`camera-pointing`** object.

The bridge accepts either envelope style:

1. Top-level key **`Logger`** whose value is a JSON string (or object) containing `camera-pointing`.
2. Top-level **`data_payload_type": "Logger"`** and **`data_payload`** as a JSON string with the same inner structure.

Inner shape (simplified):

```json
{
  "camera-pointing": {
    "rho_c": 114.77,
    "tau_c": 22.91,
    "zoom": 3000,
    "object_id": "a0cb1c",
    "distance": 18500.5,
    ...
  }
}
```

`rho_c` maps to CoT `<sensor azimuth="..."/>` (true north, normalized to `[0,360)`). `tau_c` maps to `<sensor elevation="..."/>` (clamped to `[-90,90]`).

### `<sensor>` FOV and related fields

Both the mapping stream (`SENSOR_TYPE` on `<event>`, e.g. `b-m-p-s-p-e`) and the equipment stream (`COT_EQUIP_TYPE`, e.g. `a-f-G-E-S-E`) use the same **`<sensor>`** attribute set, aligned with the public-release **MITRE CoT Sensor Schema** (obtain the XSD from official TAK / MITRE CoT packages; it is not vendored in this repository):

| Attribute | Source |
|-----------|--------|
| `fov`, `vfov` | Interpolated from Logger **`zoom`** using **`SENSOR_FOV_*_WIDE`** at zoom 0 and **`SENSOR_FOV_*_TELE`** at zoom 9999 (defaults: constant **`SENSOR_FOV_H`** / **`SENSOR_FOV_V`**). Values clamped to `[0, 360)`. |
| `type` | **`SENSOR_MODALITY_TYPE`** (default `r-e-z-c`, raster EO zoom continuous), not the same as the mapping **event** type. |
| `model` | **`SENSOR_MODEL`** |
| `range` | Logger **`distance`** (meters to tracked object), when present and non-negative |
| `roll`, `north` | Optional env **`SENSOR_ROLL`**, **`SENSOR_NORTH`** (degrees) |

## Validate with MQTT

While SkyScan is tracking, capture one line:

```bash
mosquitto_sub -h 127.0.0.1 -p 1884 -t '/skyscan/roof_sf/Logger/edgetech-axis-ptz-controller/JSON' -C 1
```

(Use your `.env` `DEPLOYMENT` in the topic path; if MQTT is not published on the host, run `mosquitto_sub` inside the `mqtt` network or from a container on `skyscan`.)

Confirm the payload contains `camera-pointing` with `rho_c` / `tau_c`.

## Validate CoT (default UDP)

With the default **`udp+wo://…`** URL, CoT is still one XML event per **UDP datagram**. Listen (example):

```bash
nc -u -l 4242
```

Point `COT_UDP_HOST` / `COT_UDP_PORT` in [`cot-bridge.env`](../../cot-bridge.env) at the machine running that listener (or set **`COT_URL`** to match your test setup). From **inside Docker**, `127.0.0.1` is the bridge container itself—use the **host LAN IP**, `host.docker.internal` (where supported), or attach the bridge to `network_mode: host` if you must send to localhost on the host.

For **`tcp://`**, **`tls://`**, or **`marti://`**, use a TAK client or PyTAK-compatible listener instead of raw UDP `nc`.

## CoT schema reference

MITRE XSDs and sample `.cot` files are **not** stored in this repo (keeps the fork small). Use the **CoT Sensor** and **CoT Shape** public-release schemas from a TAK / ATAK distribution or [MITRE’s Cursor on Target publication hub](https://www.mitre.org/news-insights/publication/cursor-target). TAK-style drawing examples (e.g. free-form / spot markers) ship with ATAK / TAK developer materials.
