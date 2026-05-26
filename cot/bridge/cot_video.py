"""ATAK-compatible video feed CoT (b-i-v endpoint + __video link)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote, unquote, urlparse

import pytak

DEFAULT_VIDEO_COT_TYPE = "b-i-v"
DEFAULT_VIDEO_HOW = "m-g"

URL_FORMAT_EMBEDDED = "embedded"
URL_FORMAT_TAKX = "takx"
URL_FORMAT_CREDENTIAL_FREE = "credential_free"
URL_FORMAT_RAW = "raw"


def parse_rtsp_url(url: str) -> dict[str, Any]:
    """Parse RTSP URL into host, port, path, and optional credentials."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("rtsp", "rtsps"):
        raise ValueError(f"Expected rtsp URL, got scheme {parsed.scheme!r}")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("RTSP URL missing host")
    port = parsed.port or (8322 if parsed.scheme == "rtsps" else 8554)
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    user = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    return {
        "scheme": parsed.scheme,
        "host": host,
        "port": int(port),
        "path": path,
        "user": user,
        "password": password,
    }


def build_read_stream_url(
    *,
    public_host: str,
    rtsp_port: int = 8554,
    path: str,
    read_user: str,
    read_pass: str,
    scheme: str = "rtsp",
) -> str:
    """Build RTSP read URL for ATAK ConnectionEntry / __video url attribute."""
    path = path.strip().lstrip("/")
    user_q = quote(read_user, safe="")
    pass_q = quote(read_pass, safe="")
    return f"{scheme}://{user_q}:{pass_q}@{public_host}:{int(rtsp_port)}/{path}"


def resolve_read_stream_url(video_cfg: dict[str, Any]) -> str | None:
    """Resolve stream URL from video config (explicit or built from parts)."""
    explicit = (video_cfg.get("stream_url") or "").strip()
    if explicit:
        return explicit
    host = (video_cfg.get("public_host") or "").strip()
    path = (video_cfg.get("path") or "").strip()
    user = (video_cfg.get("read_user") or "").strip()
    password = (video_cfg.get("read_pass") or "").strip()
    if not host or not path or not user or not password:
        return None
    return build_read_stream_url(
        public_host=host,
        rtsp_port=int(video_cfg.get("rtsp_port", 8554)),
        path=path,
        read_user=user,
        read_pass=password,
        scheme=video_cfg.get("scheme", "rtsp"),
    )


def format_connection_path(path: str, *, style: str = "leading_slash") -> str:
    """Normalize RTSP path for ATAK clients (TAKX prefers leading slash)."""
    p = (path or "/").strip()
    if not p.startswith("/"):
        p = "/" + p
    if style == "no_slash":
        return p.lstrip("/")
    return p


def format_connection_address(
    parsed: dict[str, Any],
    *,
    embed_credentials: bool = True,
) -> str:
    """ATAK ConnectionEntry address: host only, or user:pass@host."""
    host = parsed["host"]
    if not embed_credentials:
        return host
    user = parsed.get("user")
    password = parsed.get("password")
    if not user:
        return host
    user_q = quote(user, safe="")
    if password:
        creds = f'{user_q}:{quote(password, safe="")}'
    else:
        creds = user_q
    return f"{creds}@{host}"


def build_credential_free_rtsp_url(parsed: dict[str, Any]) -> str:
    """rtsp://host:port/path without embedded credentials."""
    path = format_connection_path(parsed["path"], style="leading_slash")
    return f"{parsed['scheme']}://{parsed['host']}:{parsed['port']}{path}"


def build_connection_entry_attrs(
    parsed: dict[str, Any],
    *,
    uid: str,
    alias: str,
    stream_url: str | None = None,
    rtsp_reliable: int = 1,
    network_timeout_ms: int = 12000,
    path_style: str = "leading_slash",
    url_format: str = URL_FORMAT_TAKX,
) -> dict[str, str]:
    """ATAK ConnectionEntry attributes for __video detail."""
    if url_format == URL_FORMAT_RAW:
        if not stream_url:
            raise ValueError("raw url_format requires stream_url")
        return {
            "protocol": "raw",
            "address": stream_url,
            "port": "-1",
            "path": "",
            "uid": uid,
            "alias": alias[:200],
            "rtspReliable": str(int(rtsp_reliable)),
            "roverPort": "-1",
            "ignoreEmbeddedKLV": "false",
            "networkTimeout": str(int(network_timeout_ms)),
            "bufferTime": "-1",
        }
    embed_creds = url_format != URL_FORMAT_CREDENTIAL_FREE
    return {
        "protocol": "rtsp" if parsed["scheme"] == "rtsp" else "rtsps",
        "address": format_connection_address(parsed, embed_credentials=embed_creds),
        "port": str(parsed["port"]),
        "path": format_connection_path(parsed["path"], style=path_style),
        "uid": uid,
        "alias": alias[:200],
        "rtspReliable": str(int(rtsp_reliable)),
        "roverPort": "-1",
        "ignoreEmbeddedKLV": "False" if url_format == URL_FORMAT_TAKX else "false",
        "networkTimeout": str(int(network_timeout_ms)),
        "bufferTime": "-1",
    }


def sensor_video_link_url(
    parsed: dict[str, Any],
    *,
    url_format: str,
    stream_url: str | None = None,
) -> str | None:
    """URL for <__video uid=... url=.../> on the mapping sensor (if any)."""
    if url_format == URL_FORMAT_RAW:
        return stream_url
    if url_format == URL_FORMAT_EMBEDDED:
        return build_read_stream_url(
            public_host=parsed["host"],
            rtsp_port=parsed["port"],
            path=parsed["path"].lstrip("/"),
            read_user=parsed["user"] or "",
            read_pass=parsed["password"] or "",
            scheme=parsed["scheme"],
        )
    if url_format == URL_FORMAT_CREDENTIAL_FREE:
        return build_credential_free_rtsp_url(parsed)
    return None


def add_video_link_to_detail(
    detail: ET.Element,
    video_uid: str,
    *,
    stream_url: str | None = None,
) -> None:
    """Add <__video uid="..."/> (and optional url) to sensor detail."""
    attrs: dict[str, str] = {"uid": video_uid}
    if stream_url:
        attrs["url"] = stream_url
    ET.SubElement(detail, "__video", attrs)


def build_video_endpoint_event(
    *,
    video_uid: str,
    callsign: str,
    stream_url: str,
    lat: float = 0.0,
    lon: float = 0.0,
    hae: float = 0.0,
    stale_sec: int = 3600,
    rtsp_reliable: int = 1,
    cot_type: str = DEFAULT_VIDEO_COT_TYPE,
    url_format: str = URL_FORMAT_TAKX,
    path_style: str = "leading_slash",
) -> bytes:
    """Build b-i-v CoT with ConnectionEntry for ATAK video tool."""
    parsed = parse_rtsp_url(stream_url)
    now = pytak.cot_time()
    stale = pytak.cot_time(int(stale_sec))

    event = ET.Element(
        "event",
        {
            "version": "2.0",
            "type": cot_type,
            "uid": video_uid,
            "how": DEFAULT_VIDEO_HOW,
            "time": now,
            "start": now,
            "stale": stale,
        },
    )
    ET.SubElement(
        event,
        "point",
        {
            "lat": f"{float(lat):.6f}",
            "lon": f"{float(lon):.6f}",
            "hae": f"{float(hae):.1f}",
            "ce": "9999999.0",
            "le": "9999999.0",
        },
    )
    detail = ET.SubElement(event, "detail")
    ET.SubElement(detail, "contact", {"callsign": callsign[:200]})
    if url_format == URL_FORMAT_TAKX:
        ET.SubElement(
            detail,
            "precisionlocation",
            {"geopointsrc": "GPS", "altsrc": "GPS"},
        )
    video_attrs: dict[str, str] = {}
    if url_format == URL_FORMAT_RAW:
        video_attrs["uid"] = video_uid
        video_attrs["url"] = stream_url
    video_el = ET.SubElement(detail, "__video", video_attrs)
    conn_attrs = build_connection_entry_attrs(
        parsed,
        uid=video_uid,
        alias=callsign,
        stream_url=stream_url,
        rtsp_reliable=rtsp_reliable,
        url_format=url_format,
        path_style=path_style,
    )
    ET.SubElement(video_el, "ConnectionEntry", conn_attrs)

    return ET.tostring(event, encoding="utf-8")
