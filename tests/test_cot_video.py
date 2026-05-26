"""Tests for ATAK video feed CoT (b-i-v + __video link)."""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cot" / "bridge"))

from cot_video import (
    URL_FORMAT_TAKX,
    build_connection_entry_attrs,
    build_credential_free_rtsp_url,
    build_read_stream_url,
    build_video_endpoint_event,
    format_connection_address,
    parse_rtsp_url,
    resolve_read_stream_url,
)

STREAM = (
    "rtsp://SkyScanTAK:SkyScanTAK1234@stream.snstak.com:8554/skyscan_roof_sf_cam_hud"
)


def test_parse_rtsp_url():
    p = parse_rtsp_url(STREAM)
    assert p["host"] == "stream.snstak.com"
    assert p["port"] == 8554
    assert p["path"] == "/skyscan_roof_sf_cam_hud"
    assert p["user"] == "SkyScanTAK"
    assert p["password"] == "SkyScanTAK1234"


def test_build_read_stream_url():
    url = build_read_stream_url(
        public_host="stream.snstak.com",
        rtsp_port=8554,
        path="skyscan_test_cam_hud",
        read_user="u",
        read_pass="p",
    )
    assert "stream.snstak.com:8554/skyscan_test_cam_hud" in url


def test_takx_connection_entry():
    parsed = parse_rtsp_url(STREAM)
    attrs = build_connection_entry_attrs(
        parsed,
        uid="sensor-1-video",
        alias="SkyScan HUD",
        rtsp_reliable=1,
        url_format=URL_FORMAT_TAKX,
    )
    assert attrs["protocol"] == "rtsp"
    assert attrs["address"] == "SkyScanTAK:SkyScanTAK1234@stream.snstak.com"
    assert attrs["port"] == "8554"
    assert attrs["path"] == "/skyscan_roof_sf_cam_hud"
    assert attrs["rtspReliable"] == "1"
    assert attrs["ignoreEmbeddedKLV"] == "False"


def test_format_connection_address_credential_free():
    parsed = parse_rtsp_url(STREAM)
    assert format_connection_address(parsed, embed_credentials=False) == (
        "stream.snstak.com"
    )


def test_credential_free_url():
    parsed = parse_rtsp_url(STREAM)
    assert build_credential_free_rtsp_url(parsed) == (
        "rtsp://stream.snstak.com:8554/skyscan_roof_sf_cam_hud"
    )


def test_build_video_endpoint_event_takx():
    xml = build_video_endpoint_event(
        video_uid="skyscan-1-video",
        callsign="SkyScan HUD",
        stream_url=STREAM,
        lat=37.76,
        lon=-122.4975,
        hae=65.0,
        url_format=URL_FORMAT_TAKX,
    )
    root = ET.fromstring(xml)
    assert root.get("type") == "b-i-v"
    conn = root.find("./detail/__video/ConnectionEntry")
    assert conn is not None
    assert conn.get("address") == "SkyScanTAK:SkyScanTAK1234@stream.snstak.com"
    assert conn.get("path") == "/skyscan_roof_sf_cam_hud"
    assert root.find("./detail/precisionlocation") is not None


def test_resolve_read_stream_url_from_parts():
    url = resolve_read_stream_url(
        {
            "stream_url": "",
            "public_host": "stream.snstak.com",
            "path": "skyscan_roof_sf_cam_hud",
            "read_user": "u",
            "read_pass": "p",
            "rtsp_port": 8554,
            "scheme": "rtsp",
        }
    )
    assert url is not None
    assert "skyscan_roof_sf_cam_hud" in url
