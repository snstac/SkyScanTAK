"""MQTT telemetry for HUD file + KLV FIFO producer."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from video.geo import slant_range_m
from video.hud import format_hud_text
from video.klv_builder import TelemetrySnapshot, build_uas_packet
from video.parse import (
    coerce_float,
    parse_camera_pointing,
    parse_selected_object,
    str_clean,
)

log = logging.getLogger(__name__)

HUD_PATH = os.environ.get("VIDEO_HUD_PATH", "/tmp/skyscan_hud.txt").strip()
KLV_FIFO = os.environ.get("VIDEO_KLV_FIFO", "/tmp/skyscan_klv.fifo").strip()
KLV_RATE_HZ = float(os.environ.get("VIDEO_KLV_RATE", "10"))
VIDEO_KLV_ENABLE = os.environ.get("VIDEO_KLV_ENABLE", "false").lower() in (
    "1",
    "true",
    "yes",
    "on",
)

DEPLOYMENT = os.environ.get("DEPLOYMENT", "skyscan").strip()
MISSION_ID = os.environ.get("VIDEO_MISSION_ID", "").strip() or DEPLOYMENT

TRIPOD_LAT = float(os.environ.get("TRIPOD_LATITUDE", "0"))
TRIPOD_LON = float(os.environ.get("TRIPOD_LONGITUDE", "0"))
TRIPOD_ALT = float(os.environ.get("TRIPOD_ALTITUDE", "0"))

LOGGER_TOPIC = os.environ.get("LOGGER_TOPIC", "").strip()
OBJECT_TOPIC = os.environ.get("OBJECT_TOPIC", "").strip()
MQTT_IP = os.environ.get("MQTT_IP", "mqtt")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

SENSOR_FOV_H_WIDE = float(
    os.environ.get("SENSOR_FOV_H_WIDE", os.environ.get("SENSOR_FOV_H", "55"))
)
SENSOR_FOV_H_TELE = float(
    os.environ.get("SENSOR_FOV_H_TELE", os.environ.get("SENSOR_FOV_H", "55"))
)

_state_lock = threading.Lock()
_rho: float | None = None
_tau: float | None = None
_zoom: int | None = None
_slant_logger: float | None = None
_obj: dict | None = None


def _fov_h(zoom: int | None) -> float | None:
    if SENSOR_FOV_H_WIDE == SENSOR_FOV_H_TELE:
        return SENSOR_FOV_H_WIDE
    if zoom is None:
        return SENSOR_FOV_H_WIDE
    t = max(0, min(9999, int(zoom))) / 9999.0
    return SENSOR_FOV_H_WIDE + (SENSOR_FOV_H_TELE - SENSOR_FOV_H_WIDE) * t


def _norm_az(d: float) -> float:
    x = float(d) % 360.0
    if x < 0:
        x += 360.0
    if x >= 360.0:
        x = 0.0
    return x


def _clamp_elev(d: float) -> float:
    return max(-90.0, min(90.0, float(d)))


def snapshot() -> TelemetrySnapshot:
    with _state_lock:
        rho, tau, zoom, dist_log, obj = _rho, _tau, _zoom, _slant_logger, (
            dict(_obj) if _obj else None
        )

    tgt_lat = tgt_lon = tgt_hae = None
    tgt_id = tgt_cs = None
    if obj:
        tgt_lat = coerce_float(obj.get("latitude"))
        tgt_lon = coerce_float(obj.get("longitude"))
        tgt_hae = coerce_float(obj.get("altitude"))
        oid = obj.get("object_id")
        if oid is not None:
            tgt_id = str(oid)
        tgt_cs = str_clean(obj.get("flight")) or None

    slant = dist_log
    if (
        slant is None
        and tgt_lat is not None
        and tgt_lon is not None
        and tgt_hae is not None
    ):
        slant = slant_range_m(
            TRIPOD_LAT, TRIPOD_LON, TRIPOD_ALT, tgt_lat, tgt_lon, tgt_hae
        )

    rho_k = _norm_az(rho) if rho is not None else None
    tau_k = _clamp_elev(tau) if tau is not None else None

    return TelemetrySnapshot(
        ts_utc=datetime.now(timezone.utc),
        deployment=DEPLOYMENT,
        mission_id=MISSION_ID,
        sensor_lat=TRIPOD_LAT,
        sensor_lon=TRIPOD_LON,
        sensor_hae_m=TRIPOD_ALT,
        rho_deg=rho_k,
        tau_deg=tau_k,
        hfov_deg=_fov_h(zoom),
        zoom=zoom,
        slant_range_m=slant,
        tgt_lat=tgt_lat,
        tgt_lon=tgt_lon,
        tgt_hae_m=tgt_hae,
        tgt_id=tgt_id,
        tgt_callsign=tgt_cs,
    )


def _write_hud() -> None:
    text = format_hud_text(snapshot())
    tmp = HUD_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, HUD_PATH)


def _on_message(_c: mqtt.Client, _u: object, msg: mqtt.MQTTMessage) -> None:
    global _rho, _tau, _zoom, _slant_logger, _obj
    if not msg.payload:
        return
    try:
        text = msg.payload.decode("utf-8")
    except UnicodeDecodeError:
        return

    if OBJECT_TOPIC and msg.topic == OBJECT_TOPIC:
        o = parse_selected_object(text)
        with _state_lock:
            _obj = o
        _write_hud()
        return

    cp = parse_camera_pointing(text)
    if not cp:
        return
    try:
        rho = float(cp["rho_c"])
        tau = float(cp["tau_c"])
    except (KeyError, TypeError, ValueError):
        return

    zoom_v: int | None = None
    raw_z = cp.get("zoom")
    if raw_z is not None:
        try:
            zoom_v = int(raw_z)
        except (TypeError, ValueError):
            zoom_v = None

    dist_m: float | None = None
    d_raw = cp.get("distance")
    if d_raw is not None:
        try:
            dv = float(d_raw)
            if dv >= 0:
                dist_m = dv
        except (TypeError, ValueError):
            pass

    with _state_lock:
        _rho = rho
        _tau = tau
        _zoom = zoom_v
        _slant_logger = dist_m
    _write_hud()


def _klv_loop(stop: threading.Event, fifo_path: str) -> None:
    log.info("KLV writer waiting for reader on %s", fifo_path)
    while not stop.is_set():
        try:
            fifo = open(fifo_path, "wb", buffering=0)
            break
        except OSError as e:
            log.warning("KLV fifo open failed (retry): %s", e)
            if stop.wait(0.5):
                return
    log.info("KLV fifo writer connected")
    period = 1.0 / KLV_RATE_HZ if KLV_RATE_HZ > 0 else 0.1
    try:
        while not stop.is_set():
            pkt = build_uas_packet(snapshot())
            try:
                fifo.write(pkt)
                fifo.flush()
            except BrokenPipeError:
                log.warning("KLV reader gone; will reconnect")
                break
            if stop.wait(period):
                break
    finally:
        try:
            fifo.close()
        except OSError:
            pass


def _klv_runner(stop: threading.Event, fifo_path: str) -> None:
    while not stop.is_set():
        _klv_loop(stop, fifo_path)


def hud_enabled() -> bool:
    """HUD pipeline on if VIDEO_HUD_ENABLE or legacy VIDEO_FIRIS_ENABLE is truthy."""
    v = os.environ.get("VIDEO_HUD_ENABLE")
    if v is None:
        v = os.environ.get("VIDEO_FIRIS_ENABLE", "true")
    return v.lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def run() -> None:
    hdir = os.path.dirname(HUD_PATH)
    if hdir:
        os.makedirs(hdir, exist_ok=True)
    _write_hud()

    stop_klv = threading.Event()
    if VIDEO_KLV_ENABLE and hud_enabled():
        threading.Thread(
            target=_klv_runner, args=(stop_klv, KLV_FIFO), daemon=True
        ).start()

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="skyscan-video-gateway",
    )

    def _connect(
        c: mqtt.Client,
        _u: object,
        _f: dict,
        rc: mqtt.ReasonCode,
        _p: mqtt.Properties | None,
    ) -> None:
        if rc.is_failure:
            log.error("MQTT connect failed: %s", rc)
            return
        if LOGGER_TOPIC:
            c.subscribe(LOGGER_TOPIC)
            log.info("Subscribed %s", LOGGER_TOPIC)
        if OBJECT_TOPIC:
            c.subscribe(OBJECT_TOPIC)
            log.info("Subscribed %s", OBJECT_TOPIC)

    client.on_connect = _connect
    client.on_message = _on_message

    log.info("Connecting MQTT %s:%s for video telemetry", MQTT_IP, MQTT_PORT)
    client.connect(MQTT_IP, MQTT_PORT, keepalive=60)

    try:
        client.loop_forever()
    finally:
        stop_klv.set()
