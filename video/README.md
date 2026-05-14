# SkyScan video-gateway

Sidecar container that:

1. Pulls **live H.264** from the Axis camera (**RTSP**).
2. Publishes **MPEG-TS over SRT** to [MediaMTX](https://github.com/bluenviron/mediamtx) (or any SRT listener). The **primary** path is the **HUD** leg (`VIDEO_HUD_ENABLE`): decode → **overlay** (`drawtext` + `textfile`) → transcode **libx264**. Optional **MISB ST 0601** KLV is multiplexed as a **binary data** stream (`-c:d copy`) when `VIDEO_KLV_ENABLE` is on (Python writes UAS Local Set packets to a FIFO at `VIDEO_KLV_RATE` Hz).

**Optional raw passthrough** — set `VIDEO_RAW_ENABLE=true` and populate `MEDIAMTX_SRT_URL_RAW` for a second `-c:v copy` SRT output. When **both** raw and HUD are on, **one `ffmpeg`** pulls **one** RTSP session and writes **two** SRT outputs (avoids Axis firmware that allows only one RTSP client, which would hide the second MediaMTX path).

Telemetry for HUD + KLV comes from the same MQTT topics as the rest of SkyScan: `LOGGER_TOPIC` (camera-pointing / `rho_c`, `tau_c`, `zoom`, `distance`) and `OBJECT_TOPIC` (skyscan-c2 selected object: `flight`, `object_id`, lat/lon/alt). Tripod position for slant range and KLV “sensor” fields is taken from `TRIPOD_LATITUDE`, `TRIPOD_LONGITUDE`, `TRIPOD_ALTITUDE`.

**HUD appearance:** Reference stills (e.g. [KDRV](https://bloximages.newyork1.vip.townnews.com/kdrv.com/content/tncms/assets/v3/editorial/6/3b/63bb3a85-9cb2-5761-beb0-92730a1315fa/627aa64a1049c.image.jpg), [KRCR FIRIS2](https://krcrtv.com/resources/media2/16x9/723/986/1x0/90/432c80bc-639f-4bd4-aad2-7266b16d8235-FIRIS2.PNG)) show **phosphor / neon green** symbology (`#39FF14`-class), **all-caps monospace**, **no translucent panel** (text painted on the picture), corner-cluster copy (platform LLA, **LRF TARGET** block with coordinates, **SLT** in **NM**, **ALT/ELV** in **FT**), plus red **ARMED** alerts on some aircraft systems—we only render telemetry we have (no fake ARMED). Tunables are in **[`video-gateway.env`](../video-gateway.env)** (`VIDEO_HUD_*`; **[`entrypoint.sh`](./entrypoint.sh)** builds the `drawtext` filter).

## ATAK-CIV / UAS Tool (video + MISB ST 0601 KLV)

MediaMTX commonly **drops the KLV / data PID** when ingesting your SRT publish (`skipping track 2`), so **WinTAK/ATAK** may see **video only** on `rtsp://…/live/…` paths.

This gateway also exposes **MPEG-TS over TCP** on the host (H.264 + HUD + KLV) without relying on MediaMTX to preserve the metadata PID:

| Setting | Default |
|---------|---------|
| `VIDEO_ATAK_TS_TCP_ENABLE` | `true` |
| `VIDEO_ATAK_TS_TCP_PORT` | `8556` |

With ATAK enabled, FFmpeg runs **a second x264 encode** of the HUD (via `split=2`) so one mux goes to **`tcp://0.0.0.0:VIDEO_ATAK_TS_TCP_PORT?listen=1`** (listed **first** in the command line) and one to MediaMTX (SRT). Connect your viewer after both encoders have started; FFmpeg may log transient TCP mux errors until a client attaches.

`docker compose` publishes **`8556:8556`** on **video-gateway** by default.

**URL for tools that accept raw MPEG-TS over TCP** ([ffplay](https://ffmpeg.org/ffplay.html), [VLC](https://www.videolan.org/), lab scripts):

`ffplay -fflags nobuffer tcp://SKYSCAN_HOST:8556`

`ffprobe -show_streams tcp://SKYSCAN_HOST:8556` — expect **two** streams (video + data) when `VIDEO_KLV_ENABLE=true`.

ATAK devices must **route to the host** (VPN/LAN or port forward). Android often cannot use a raw `tcp://` URL in stock UI — use the **UAS / external video** flow your plugin documents, or **WinTAK** on a machine that can open the TCP TS stream.

See [ATAK-CIV](https://github.com/TAK-Product-Center/atak-civ) and CivTAK UAS documentation for supported stream types; add a local relay (e.g. FFmpeg → RTSP) against `tcp://HOST:8556` if your build requires it.

## Configure

| Variable | Purpose |
|----------|---------|
| `MEDIAMTX_SRT_URL_HUD` | SRT output for HUD / overlay TS (quoted if `&` in URL). Legacy: `MEDIAMTX_SRT_URL_FIRIS` |
| `MEDIAMTX_SRT_URL_RAW` | Optional; only used when `VIDEO_RAW_ENABLE=true` (unquoted empty = raw off) |
| `CAMERA_RTSP_URL` | Optional; if unset, built from `CAMERA_USER`, `CAMERA_PASSWORD`, `CAMERA_IP` |

MediaMTX **publish** URLs are installation-specific. Typical form:

`srt://stream.example.com:8890?streamid=publish:path/cam_hud&pkt_size=1316`

Use your server’s port, **`streamid`**, passphrase, and path naming. HLS consumers read from MediaMTX; the gateway does not publish HLS itself.

### MediaMTX internal auth (common gotcha)

If `authInternalUsers` only grants **`publish`** to `user: any` with **`ips: [127.0.0.1]`**, remote publishers get **`authentication failed`** in MediaMTX logs. Do one of the following:

1. **Recommended:** Add a dedicated user with **`action: publish`** (optionally `path: live/...`) and use MediaMTX’s **standard SRT stream ID** so FFmpeg sends credentials:

```yaml
authInternalUsers:
  - user: skyscan_pub
    pass: "choose_a_long_random_secret"
    ips: []
    permissions:
      - action: publish
        path: live/skyscan_roof_sf_cam_hud
      # Optional second path if VIDEO_RAW_ENABLE and MEDIAMTX_SRT_URL_RAW are set:
      # - action: publish
      #   path: live/skyscan_roof_sf_cam_raw
```

URL (must be **quoted** in `video-gateway.env` so `#` is not a comment):

`srt://stream.snstak.com:8890?streamid=#!::m=publish,r=live/skyscan_roof_sf_cam_hud,u=skyscan_pub,s=choose_a_long_random_secret&pkt_size=1316`

(Field **`m`** = `publish`, **`r`** = path, **`u`** / **`s`** = user / pass — see [SRT-specific features](https://mediamtx.org/docs/features/srt-specific-features).)

The shorthand `streamid=publish:mypath` does **not** include credentials; it only works when the server allows anonymous publish from your IP.

2. Loosen **`authInternalUsers`** so your edge IP (or `ips: []`) may publish on those paths (less ideal).

If you use a **`live/...` path** with **`runOnReady`** relaying to `rtsp://localhost:8554/<name>`**, keep **`r=live/<name>`** in the streamid so the hook runs.

### SRT **read** (viewers: Haivision Play ISR, VLC, etc.)

Publishers use the **`#!::m=publish,r=...,u=...,s=...`** form (see above). **Readers** use MediaMTX’s **custom** streamid grammar (`action:pathname:user:pass`):

| Part | Value |
|------|--------|
| action | **`read`** (not `request`) |
| pathname | e.g. `skyscan_roof_sf_cam_hud` or `live/skyscan_roof_sf_cam_hud` |
| user / pass | include if internal auth requires **read** credentials |

Example **Stream ID** (paste **decoded** — real **colons**, never the literal string `read%3A`):

`read:live/skyscan_roof_sf_cam_hud:SkyScanTAK:SkyScanTAK1234`

Some players accept a single URL; they must **URL-decode** the `streamid` query value before the SRT handshake. If they forward **`read%3A...`** unchanged, MediaMTX logs **`invalid stream ID 'read%3A...'`** — that is always a **reader** bug or mispaste, **not** the SkyScan publisher (which uses `#!::m=publish,...`). Confirmed via `docker exec skyscan-video-gateway-1 printenv MEDIAMTX_SRT_URL_HUD`.

**Do not** put **`read:`** / **`read%3A`** URLs in **`MEDIAMTX_SRT_URL_*`** (publish). Search the edge network for configs still using the old percent-encoded read URL (CloudTAK, ISR Play bookmarks, scripts):

`grep -R 'read%3A\|stream.snstak.com' ...`

**`authInternalUsers`** must include **`action: read`** for that path (or global read for that user). **Publish** alone is not enough to play back.

**Path:** readers should usually use **`live/skyscan_roof_sf_cam_hud`** (the SRT publish path). The short relay name **`skyscan_roof_sf_cam_hud`** only has media when **`runOnReady`** is running; otherwise you get *no stream is available*.

If the player shows **connected / 1 track H264** but **black picture**:

1. **Transcode** — try **`VIDEO_X264_PROFILE=baseline`** in **[video-gateway.env](../video-gateway.env)**. If you still run **raw** alongside HUD, compare `read:live/skyscan_roof_sf_cam_raw:...` vs the HUD path in the same player to see whether the issue is x264 vs the player.
2. **SRT latency** — append **`&latency=1500`** (or **`2000`**) to the reader URL; some receivers need a larger receive buffer.
3. **VLC** — open the same SRT URL or **`rtsp://stream.snstak.com:8554/live/skyscan_roof_sf_cam_hud?tcp`** to see if the problem is **Play ISR–specific**.
4. **MediaMTX** — confirm the path still has an active **publisher** (SkyScan **video-gateway** running) when you read.

### RTSP MPEG-TS demux (`rtspDemuxMpegts`) and HLS

Tactical / ATAK-style feeds often deliver **H.264 + KLV inside MPEG-TS over RTSP**. MediaMTX cannot serve **HLS** from that wrapped TS as-is; from **v1.17.0** you can set **`pathDefaults.rtspDemuxMpegts: true`** (or per-path **`rtspDemuxMpegts`**) so RTSP publishers are **demuxed** to elementary streams (e.g. H.264, AAC). **HLS** then gets the video/audio tracks; **KLV / metadata** is typically **omitted from HLS** but remains available to **RTSP** readers that want the data PID.

**SkyScan video-gateway** publishes **MPEG-TS over SRT**, not RTSP to MediaMTX, so this setting does not apply to that leg unless you **re-ingest** the same TS over **RTSP** (e.g. after an FFmpeg relay). Use **`rtspDemuxMpegts`** for paths where **publishers connect via RTSP** with TS-wrapped content (TAKICU, ATAK UAS Tool, ISR cameras, etc.).

### What healthy MediaMTX logs look like (and common warnings)

After auth and SRT publish succeed you should see **`live/skyscan_roof_sf_cam_hud`** online with **one H264 track** (or two tracks if the server ingests the KLV PID). If raw is enabled, **`live/skyscan_roof_sf_cam_raw`** appears as a second publisher path.

- **`skipping track 2 (unsupported codec)`** — FFmpeg muxes KLV as an extra **MPEG-TS PID / data** stream. MediaMTX often **ingests only the H.264** track on that path and **drops** the metadata track today. **HUD text is burned into the video**, so clients still see symbology; **ST 0601 sidecar** through this path may be unavailable until the server accepts that stream type or you deliver KLV another way (e.g. separate UDP/CoT or a dedicated archival pipeline).

- **`method SETUP failed: 461 Unsupported Transport`** on **`runOnReady`** `ffmpeg` — the hook’s FFmpeg defaults to **UDP** RTSP; MediaMTX may answer **461** then fall back to **TCP** (you still see `is reading from path ... with TCP`). To avoid the warning, force TCP on both legs, for example:

  `runOnReady: ffmpeg -rtsp_transport tcp -i rtsp://127.0.0.1:8554/live/$G1 -c copy -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/$G1`

  (`$G1` is the capture group from **`~^live/(.+)$`**; change if your path regex differs.)

- **`RTP packets are too big ... remuxing`** — informational; MediaMTX is splitting oversized RTP for MTU.

## KLV notes

- **Default encoder:** Packets are **UAS Datalink Local Set** built with [klvdata](https://pypi.org/project/klvdata/) in [`klv_builder.py`](./klv_builder.py) (keys include precision time stamp, mission id, sensor lat/lon/alt, relative az/el, HFOV, target lat/lon/elev, slant range, platform heading). Enable with **`VIDEO_KLV_ENABLE=true`** and the matching FFmpeg branch in [`entrypoint.sh`](./entrypoint.sh) (FIFO + `-f data`).
- **Legacy / SmartCam-style encoder:** A separate hand-rolled ST 0601–style packer and FIFO+FFmpeg mux (including **`-c:v copy`** from Axis, no HUD) lives under **`work/CTI/sc3d`** on the same machine (relative to this repo: **`../../CTI/sc3d`** from the `SkyScan` checkout) — e.g. `smartcam_stream.py` with `bak.smartcam_stream.py` as an alternate reference copy. Use that stack when you need the same binary layout as that tooling; **validate with `ffprobe`, demux to `klv.bin`, or your target ISR player** — not only MediaMTX, which may still surface **one H.264 track** and drop or ignore the data PID.
- **FFmpeg (KLV on):** The entrypoint adds **`-fflags +genpts`** on the RTSP input and **`-metadata:s:d:0 handler_name=MetadataHandler`** on the muxed data stream, aligned with the legacy SmartCam streamer’s MPEG-TS metadata. UDP multicast variants in that tool also used **`-mpegts_flags +initial_discontinuity`**, **`-mpegts_copyts 1`**, **`-muxrate`** — add manually if you republish to UDP instead of SRT.
- FFmpeg logs may show **unset timestamps** on the data stream; KLV sync is **payload time**–based (Precision Time Stamp), not tight MPEG-TS PTS locking. For stricter interop, plan a GStreamer / custom mux follow-up.
- `ffprobe` may report the data track as `bin_data` rather than by name; demux with `ffmpeg -i input.ts -map 0:d -c copy -f data klv.bin` to verify.

## Networking

The container must **route to the camera** (`CAMERA_IP`) and to the **SRT peer**. Bridge mode usually works on-LAN; if RTSP fails from inside Docker, use `network_mode: host` for this service only (compose comment in your override).

## Image

Built from [Dockerfile](./Dockerfile) (FFmpeg 6.1 + Python 3 venv).

```bash
docker compose build video-gateway
docker compose up -d video-gateway
```

If both URLs are empty, FFmpeg is not started; the Python process still runs (subscribe only). When URLs are set without a reachable camera, the container will **exit** when FFmpeg fails—use `restart: unless-stopped` or fix connectivity.

## Axis RTSP URL

Default pattern:

`rtsp://USER:PASS@CAMERA_IP/axis-media/media.amp?videocodec=h264`

Passwords with reserved characters should use a fully escaped `CAMERA_RTSP_URL` instead of the auto-built URL.
