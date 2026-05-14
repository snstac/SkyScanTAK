#!/usr/bin/env python3
"""Subscribe to object-ledger MQTT, merge live CoT tracks from PyTAK RX, publish merged ledger for skyscan-c2."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from configparser import ConfigParser
from datetime import datetime, timezone
from io import StringIO
from typing import Any

import pandas as pd
import paho.mqtt.client as mqtt
import pytak

_EVENT_RE = re.compile(r"<event\b[^>]*>.*?</event>", re.DOTALL | re.IGNORECASE)
_COT_LOG_TOKEN_RE = re.compile(r"([?&]token=)[^&]*", re.IGNORECASE)

MQTT_IP = os.environ.get("MQTT_IP", "mqtt")
SOURCE_LEDGER_TOPIC = os.environ.get(
    "SOURCE_LEDGER_TOPIC",
    os.environ.get("OBJECT_LEDGER_TOPIC", ""),
).strip()
MERGED_LEDGER_TOPIC = os.environ.get("MERGED_LEDGER_TOPIC", "").strip()

# Same env as cot-bridge (`COT_URL`); optional `COT_RX_URL` overrides RX only.
COT_RX_URL = os.environ.get("COT_RX_URL", "").strip()
COT_URL = os.environ.get("COT_URL", "").strip()
PYTAK_COT_URL = COT_RX_URL or COT_URL


def _mask_cot_url(url: str) -> str:
    return _COT_LOG_TOKEN_RE.sub(r"\1<redacted>", url)
COT_TRACK_TTL_SECONDS = float(os.environ.get("COT_TRACK_TTL_SECONDS", "30"))
ADS_B_PRIORITY = float(os.environ.get("ADS_B_PRIORITY", "0"))


def _load_priority_rules() -> list[tuple[str, float]]:
    raw = os.environ.get("SKYSCAN_COT_PRIORITY_RULES", "").strip()
    if not raw:
        return [
            ("a-*-A-M-H-Q", 1000.0),
            ("a-f-A-M-H-Q", 1000.0),
            ("a-f-A-C*", 50.0),
        ]
    try:
        data = json.loads(raw)
        out: list[tuple[str, float]] = []
        for pair in data:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                out.append((str(pair[0]), float(pair[1])))
        return out or [("a-*-A-M-H-Q", 1000.0)]
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logging.warning("SKYSCAN_COT_PRIORITY_RULES invalid JSON: %s; using defaults", e)
        return [("a-*-A-M-H-Q", 1000.0), ("a-f-A-C*", 50.0)]


PRIORITY_RULES = _load_priority_rules()


def _cot_priority_for_type(cot_type: str) -> float:
    t = (cot_type or "").strip()
    best = 0.0
    for pattern, pri in PRIORITY_RULES:
        if fnmatch.fnmatchcase(t, pattern):
            best = max(best, float(pri))
    return best


def _sanitize_uid_part(s: str) -> str:
    out = []
    for c in str(s).strip().lower():
        if c.isalnum() or c in ("-", "_"):
            out.append(c)
    return "".join(out) or "unknown"


def _parse_cot_time(s: str | None) -> float | None:
    if not s or not str(s).strip():
        return None
    txt = str(s).strip()
    try:
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        return datetime.fromisoformat(txt).timestamp()
    except ValueError:
        return None


def _extract_events(xml_blob: str) -> list[ET.Element]:
    found = _EVENT_RE.findall(xml_blob)
    out: list[ET.Element] = []
    for frag in found:
        try:
            out.append(ET.fromstring(frag))
        except ET.ParseError:
            continue
    return out


class CotTrackStore:
    """Thread-safe store of CoT-derived pseudo-ledger rows (key = cot object_id)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, dict[str, Any]] = {}

    def handle_cot_bytes(self, data: bytes) -> None:
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return
        now = time.time()
        for el in _extract_events(text):
            self._ingest_event(el, now)

    def _ingest_event(self, event: ET.Element, now: float) -> None:
        uid = (event.get("uid") or "").strip()
        if not uid:
            return
        cot_type = (event.get("type") or "").strip()
        stale_s = event.get("stale")
        stale_ts = _parse_cot_time(stale_s)
        if stale_ts is not None and stale_ts < now:
            with self._lock:
                oid = f"cot-{_sanitize_uid_part(uid)}"
                self._rows.pop(oid, None)
            return

        pt = event.find("point")
        if pt is None:
            return
        try:
            lat = float(pt.get("lat", "nan"))
            lon = float(pt.get("lon", "nan"))
            hae = float(pt.get("hae", "0"))
        except (TypeError, ValueError):
            return
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return

        ev_ts = _parse_cot_time(event.get("time")) or now

        track_deg = 0.0
        h_vel = 0.0
        v_vel = 0.0
        det = event.find("detail")
        if det is not None:
            tr = det.find("track")
            if tr is not None:
                try:
                    if tr.get("course"):
                        track_deg = float(tr.get("course", "0"))
                    if tr.get("speed"):
                        h_vel = float(tr.get("speed", "0"))
                except (TypeError, ValueError):
                    pass

        oid = f"cot-{_sanitize_uid_part(uid)}"
        cot_pri = _cot_priority_for_type(cot_type)
        row: dict[str, Any] = {
            "timestamp": float(ev_ts),
            "latitude": lat,
            "longitude": lon,
            "altitude": hae,
            "track": track_deg,
            "horizontal_velocity": h_vel,
            "vertical_velocity": v_vel,
            "object_type": "cot",
            "cot_event_type": cot_type,
            "flight": "",
            "squawk": "",
            "category": "",
            "emergency": "",
            "skyscan_priority": cot_pri,
            "_stale_ts": stale_ts,
            "_last_rx": now,
        }

        with self._lock:
            self._rows[oid] = row
            self._prune_unlocked(now)

    def _prune_unlocked(self, now: float) -> None:
        dead: list[str] = []
        for oid, row in self._rows.items():
            st = row.get("_stale_ts")
            if st is not None and st < now:
                dead.append(oid)
                continue
            if now - float(row.get("_last_rx", 0)) > COT_TRACK_TTL_SECONDS:
                dead.append(oid)
        for oid in dead:
            self._rows.pop(oid, None)

    def snapshot_dataframe(self) -> pd.DataFrame:
        with self._lock:
            self._prune_unlocked(time.time())
            if not self._rows:
                return pd.DataFrame()
            rows: list[pd.Series] = []
            for oid, raw in self._rows.items():
                cp = {k: v for k, v in raw.items() if not str(k).startswith("_")}
                rows.append(pd.Series(cp, name=oid))
        return pd.DataFrame(rows) if rows else pd.DataFrame()


class CotConsumerWorker(pytak.Worker):
    def __init__(
        self,
        queue: asyncio.Queue,
        config: Any,
        store: CotTrackStore,
    ) -> None:
        super().__init__(queue, config)
        self._store = store

    async def handle_data(self, data: bytes) -> None:
        self._store.handle_cot_bytes(data)


async def _pytak_rx_loop(
    store: CotTrackStore,
    ready: threading.Event,
    errors: list[Exception],
) -> None:
    if not PYTAK_COT_URL:
        logging.info(
            "COT_URL and COT_RX_URL unset; CoT RX disabled (ledger pass-through merge only)"
        )
        ready.set()
        return
    try:
        logging.info(
            "PyTAK CoT RX using %s (from %s)",
            _mask_cot_url(PYTAK_COT_URL),
            "COT_RX_URL" if COT_RX_URL else "COT_URL",
        )
        cp = ConfigParser()
        cp["rx"] = {
            "COT_URL": PYTAK_COT_URL,
            "PYTAK_NO_HELLO": "true",
            "TAK_PROTO": "0",
        }
        sec = cp["rx"]
        clitool = pytak.CLITool(sec)
        await clitool.setup()
        clitool.add_task(CotConsumerWorker(clitool.rx_queue, sec, store))
        ready.set()
        await clitool.run()
    except BaseException as exc:
        errors.append(exc)
        if not ready.is_set():
            ready.set()
        raise


def _start_pytak(store: CotTrackStore) -> None:
    if not PYTAK_COT_URL:
        return
    ready = threading.Event()
    err: list[Exception] = []

    def runner() -> None:
        asyncio.run(_pytak_rx_loop(store, ready, err))

    t = threading.Thread(target=runner, daemon=True, name="pytak-rx")
    t.start()
    if not ready.wait(timeout=90):
        raise RuntimeError("PyTAK RX did not become ready within 90s")
    if err:
        raise RuntimeError(f"PyTAK RX startup failed: {err[0]}") from err[0]


def _assign_adsb_priority(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if "object_type" in out.columns:
        is_cot = out["object_type"].astype(str) == "cot"
    else:
        is_cot = pd.Series(False, index=out.index)
    if "skyscan_priority" not in out.columns:
        out["skyscan_priority"] = 0.0
    out["skyscan_priority"] = pd.to_numeric(
        out["skyscan_priority"], errors="coerce"
    ).fillna(0.0)
    out.loc[~is_cot, "skyscan_priority"] = float(ADS_B_PRIORITY)
    if "cot_event_type" in out.columns:
        mask = is_cot & (out["skyscan_priority"] == 0.0)
        if mask.any():
            out.loc[mask, "skyscan_priority"] = out.loc[mask, "cot_event_type"].astype(str).map(
                _cot_priority_for_type
            )
    return out


class TrackFusion:
    def __init__(self) -> None:
        self._store = CotTrackStore()
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="skyscan-cot-track-fusion",
        )

    def _on_message(
        self,
        _c: mqtt.Client,
        _u: Any,
        msg: mqtt.MQTTMessage,
    ) -> None:
        if msg.topic != SOURCE_LEDGER_TOPIC or not msg.payload:
            return
        try:
            payload_dict = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            logging.warning("Ledger JSON decode failed: %s", e)
            return
        if "ObjectLedger" not in payload_dict:
            logging.debug("MQTT message missing ObjectLedger; skip")
            return
        ol_raw = payload_dict["ObjectLedger"]
        try:
            adsb_df = pd.read_json(
                StringIO(ol_raw) if isinstance(ol_raw, str) else StringIO(json.dumps(ol_raw)),
                convert_dates=False,
                convert_axes=False,
            )
        except (ValueError, TypeError) as e:
            logging.warning("ObjectLedger DataFrame parse failed: %s", e)
            return

        cot_df = self._store.snapshot_dataframe()
        merged = adsb_df
        if not cot_df.empty:
            merged = pd.concat([adsb_df, cot_df], axis=0, sort=False)
            merged = merged[~merged.index.duplicated(keep="last")]
        merged = _assign_adsb_priority(merged)
        payload_dict = dict(payload_dict)
        payload_dict["ObjectLedger"] = merged.to_json()
        body = json.dumps(payload_dict)
        try:
            self._client.publish(MERGED_LEDGER_TOPIC, body, qos=0)
        except Exception as e:
            logging.error("Publish merged ledger failed: %s", e)

    def _on_connect(
        self,
        client: mqtt.Client,
        _u: Any,
        _f: dict[str, Any],
        rc: mqtt.ReasonCode,
        _p: mqtt.Properties | None,
    ) -> None:
        if rc.is_failure:
            logging.error("MQTT connect failed: %s", rc)
            return
        client.subscribe(SOURCE_LEDGER_TOPIC)
        logging.info("Subscribed %s -> merge -> %s", SOURCE_LEDGER_TOPIC, MERGED_LEDGER_TOPIC)

    def run(self) -> None:
        _start_pytak(self._store)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        logging.info("Connecting MQTT %s for ledger fusion", MQTT_IP)
        self._client.connect(MQTT_IP, 1883, keepalive=60)
        self._client.loop_forever()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if not SOURCE_LEDGER_TOPIC:
        raise SystemExit("SOURCE_LEDGER_TOPIC or OBJECT_LEDGER_TOPIC is required")
    if not MERGED_LEDGER_TOPIC:
        raise SystemExit("MERGED_LEDGER_TOPIC is required")
    TrackFusion().run()


if __name__ == "__main__":
    main()
