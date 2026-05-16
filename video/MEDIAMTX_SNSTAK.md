# MediaMTX at stream.snstak.com (TAKWERX)

SkyScan **video-gateway** can publish to MediaMTX at **`stream.snstak.com`** using either **RTSP publish** (port **8554**, same contract as simple camera relays) or **SRT + MPEG-TS** (port **8890**, MediaMTX stream ID form). Choose with **`MEDIAMTX_PUBLISH_PROTOCOL`** (`rtsp` or `srt`). On [snstac](https://github.com/snstac)-operated edges, paths and **`authInternalUsers`** are usually managed from **TAKWERX Console** (generated `mediamtx.yml`).

## Path naming and server hooks

Many TAKWERX configs still use a **`live/`** prefix and a regex similar to:

```yaml
paths:
  ~^live/(.+)$:
    runOnReady: ffmpeg -i rtsp://localhost:8554/live/$G1 -c copy -f rtsp rtsp://localhost:8554/$G1
```

SkyScan **defaults** (when **`DEPLOYMENT`** is set and you do not override **`MEDIAMTX_PUBLISH_PATH_*`**) publish to **`skyscan_<deployment>_cam_*`** with **no** `live/` prefix (e.g. `skyscan_roof_sf_cam_hud`), matching simple top-level path names like other RTSP relays.

**If your server only allows or hooks `live/...` paths**, set paths explicitly, for example **`MEDIAMTX_PUBLISH_PATH_HUD=live/skyscan_roof_sf_cam_hud`**.

For **SRT**, the **`r=`** value must equal the MediaMTX path string (e.g. `r=skyscan_roof_sf_cam_hud` or `r=live/skyscan_roof_sf_cam_hud` if you chose the latter). For **RTSP publish**, the URL path after the host must match the same string (e.g. `rtsp://user:pass@stream.snstak.com:8554/skyscan_roof_sf_cam_hud`). Readers follow your server’s published path; see your MediaMTX / proxy docs.

### Multi-path publishing (SkyScan video-gateway)

When **`VIDEO_HUD_ENABLE`** is on, **`entrypoint.sh`** publishes a **HUD** leg that is **video-only** (no KLV data PID). When **`VIDEO_KLV_ENABLE`** is also on, it publishes a **second** HUD leg (**HUD+KLV**) so metadata consumers keep a MediaMTX path with ST0601. Optionally **`VIDEO_RAW_ENABLE=true`** adds a **raw** camera copy leg. The same three paths apply for **both** RTSP and SRT; only the URL shape and FFmpeg **`-f`** differ.

| Leg | Typical path (with `DEPLOYMENT`) | FFmpeg output |
|-----|----------------------------------|---------------|
| Raw | `skyscan_${DEPLOYMENT}_cam_raw` | `-c:v copy`, no overlay |
| HUD (video only) | `skyscan_${DEPLOYMENT}_cam_hud` | libx264 + drawtext, **no** `-map` of KLV |
| HUD + KLV | `skyscan_${DEPLOYMENT}_cam_hud_klv` | libx264 + drawtext + data PID |

**Breaking change:** Previously, a single HUD publish URL could carry **both** video and KLV. Now the **HUD-only** path is **video-only**. Clients that need KLV through MediaMTX must use **`..._cam_hud_klv`** (or **`MEDIAMTX_RTSP_URL_HUD_KLV`** / **`MEDIAMTX_SRT_URL_HUD_KLV`**). ATAK TCP (**`VIDEO_ATAK_TS_TCP_*`**) still receives HUD+KLV in one MPEG-TS stream.

## Server ↔ repository env vars

| TAKWERX / MediaMTX | video-gateway |
|--------------------|---------------|
| `rtspAddress` / RTSP **publish** listener (often `:8554`) | **`MEDIAMTX_PUBLISH_PROTOCOL=rtsp`** and **`MEDIAMTX_RTSP_PORT`** (default `8554`), or full **`MEDIAMTX_RTSP_URL_*`** |
| `srtAddress` (e.g. `:8890`) | **`MEDIAMTX_PUBLISH_PROTOCOL=srt`** and **`MEDIAMTX_SRT_PORT`** (default `8890`) when using the SRT URL builder |
| Public hostname (e.g. `stream.snstak.com`) | **`MEDIAMTX_PUBLIC_HOST`** or full **`MEDIAMTX_RTSP_URL_*`** / **`MEDIAMTX_SRT_URL_*`** |
| `authInternalUsers` user with **`publish`** on your path | RTSP: **`rtsp://USER:PASS@host:port/path`**. SRT: **`u=` / `s=`** in the streamid or **`MEDIAMTX_PUBLISH_USER`** / **`MEDIAMTX_PUBLISH_PASS`** for the builder |

Do **not** commit real passwords. Use placeholders in **[`video-gateway.env`](../video-gateway.env)** and set secrets in **[`.env`](../.env)** (gitignored) or a private overlay file.

**Compose `env_file` order:** [`docker-compose.yaml`](../docker-compose.yaml) loads **`video-gateway.env`** first, then **`.env`**, so variables set in `.env` **override** the tracked defaults (including `MEDIAMTX_SRT_URL_HUD`).

### Optional `video-gateway.local.env`

For a third layer (e.g. machine-specific overrides), create **`video-gateway.local.env`** in the repo root (gitignored) and add it **after** `.env` under `video-gateway` → `env_file`. Docker Compose requires the file to exist on disk before `up` (use comments-only if needed).

### `pathDefaults.rtspDemuxMpegts`

That setting applies when a **publisher** connects with **RTSP** and the payload is **MPEG-TS inside RTSP**. SkyScan’s **RTSP publish** output is elementary **H.264** (and optional **data** for KLV) muxed by FFmpeg’s RTSP muxer, not necessarily TS-wrapped like some cameras. **SRT** mode sends **MPEG-TS**; demux settings are mainly for other tools (e.g. ATAK UAS RTSP, third-party cameras).

## Publisher URL (SkyScan → MediaMTX)

### RTSP publish (default in `video-gateway.env`)

Matches other relays: **FFmpeg** publishes with **`-f rtsp -rtsp_transport tcp`** to:

```text
rtsp://PUBLISH_USER:PUBLISH_PASS@stream.snstak.com:8554/your_stream_name
```

Set **`MEDIAMTX_PUBLISH_PROTOCOL=rtsp`**, **`MEDIAMTX_PUBLIC_HOST`**, **`MEDIAMTX_RTSP_PORT`** (default `8554`), **`MEDIAMTX_PUBLISH_USER`**, **`MEDIAMTX_PUBLISH_PASS`**, and either **`MEDIAMTX_PUBLISH_PATH_*`** or full **`MEDIAMTX_RTSP_URL_*`**. Quote URLs in `.env` if passwords contain **`#`** or other shell-significant characters.

### SRT publish (optional)

Use MediaMTX’s **standard** stream ID form so credentials are sent (required for non-loopback **`authInternalUsers`** in many setups). Quote the whole URL in `.env` so `#` is not treated as a comment:

```bash
MEDIAMTX_SRT_URL_HUD="srt://stream.snstak.com:8890?streamid=#!::m=publish,r=your_stream_name,u=YourUser,s=YourPass&pkt_size=1316"
```

Set **`MEDIAMTX_PUBLISH_PROTOCOL=srt`** so **`entrypoint.sh`** uses **`-f mpegts`** to these URLs instead of RTSP.

Optional **raw** leg (camera H.264 **copy**), when **`VIDEO_RAW_ENABLE=true`** — RTSP:

```bash
MEDIAMTX_RTSP_URL_RAW="rtsp://YourUser:YourPass@stream.snstak.com:8554/your_stream_raw"
```

SRT:

```bash
MEDIAMTX_SRT_URL_RAW="srt://stream.snstak.com:8890?streamid=#!::m=publish,r=your_stream_raw,u=YourUser,s=YourPass&pkt_size=1316"
```

When **`VIDEO_KLV_ENABLE=true`**, optional **HUD+KLV** — RTSP:

```bash
MEDIAMTX_RTSP_URL_HUD_KLV="rtsp://YourUser:YourPass@stream.snstak.com:8554/your_stream_hud_klv"
```

SRT:

```bash
MEDIAMTX_SRT_URL_HUD_KLV="srt://stream.snstak.com:8890?streamid=#!::m=publish,r=your_stream_hud_klv,u=YourUser,s=YourPass&pkt_size=1316"
```

Or use the **builder** (see below) instead of pasting full URLs.

### URL builder (optional)

**RTSP mode** (`MEDIAMTX_PUBLISH_PROTOCOL=rtsp`): if **`MEDIAMTX_RTSP_URL_HUD`** is empty, **`entrypoint.sh`** builds `rtsp://USER:PASS@HOST:PORT/PATH` when **`MEDIAMTX_PUBLIC_HOST`**, **`MEDIAMTX_PUBLISH_USER`**, **`MEDIAMTX_PUBLISH_PASS`**, and path (**`MEDIAMTX_PUBLISH_PATH_HUD`** or default **`skyscan_${DEPLOYMENT}_cam_hud`**) are set. Optional **`MEDIAMTX_RTSP_PORT`** (default `8554`).

**SRT mode** (`MEDIAMTX_PUBLISH_PROTOCOL=srt`): if **`MEDIAMTX_SRT_URL_HUD`** is empty, the entrypoint builds the SRT URL when the same host/credentials are set and path is resolved as before.

For **HUD+KLV**, if **`VIDEO_KLV_ENABLE=true`** and the protocol-specific full URL is empty, the entrypoint builds from **`MEDIAMTX_PUBLISH_PATH_HUD_KLV`** or default **`skyscan_${DEPLOYMENT}_cam_hud_klv`**.

For **raw**, if **`VIDEO_RAW_ENABLE=true`** and the protocol-specific full URL is empty, the entrypoint builds from **`MEDIAMTX_PUBLISH_PATH_RAW`** or default **`skyscan_${DEPLOYMENT}_cam_raw`**.

Avoid **`&`**, **`#`**, and spaces in **`MEDIAMTX_PUBLISH_PASS`** unless you know how your shell and FFmpeg escape them; prefer strong passwords without shell-metacharacters.

## Reader URLs (viewers, not the gateway)

**SRT publish:** use `m=publish` in the `streamid` query (what **`entrypoint.sh`** validates when **`MEDIAMTX_PUBLISH_PROTOCOL=srt`**). **Readers** use a different stream ID grammar (`read:...`). Do **not** paste **`read:`** or **`read%3A`** strings into **`MEDIAMTX_SRT_URL_*`** — the container exits with an error (see **[`entrypoint.sh`](./entrypoint.sh)**).

For RTSP playback, clients often use the same path the publisher used, for example:

`rtsp://stream.snstak.com:8554/skyscan_roof_sf_cam_hud`

(or `.../live/skyscan_roof_sf_cam_hud` if you configured a `live/...` publish path).

See also **[`README.md`](./README.md)** (SRT read vs publish, HLS, baseline profile).

## Troubleshooting: no publisher on MediaMTX

1. **Hostname must match TAKWERX / MediaMTX ingest.** Confirm with `getent hosts` / `dig` from the SkyScan **host** and from inside the **video-gateway** container that **`stream.snstak.com`** resolves to the address your console expects. Set **`MEDIAMTX_PUBLIC_HOST`** or full publish URLs to the **exact** hostname the console documents (**RTSP** ingest is usually **TCP/8554**; **SRT** is often **UDP/8890**).

2. **Transport:** With **`MEDIAMTX_PUBLISH_PROTOCOL=rtsp`**, FFmpeg uses **RTSP over TCP** to **8554** (firewall-friendly). With **`MEDIAMTX_PUBLISH_PROTOCOL=srt`**, outbound **UDP/8890** must be allowed (FFmpeg `libsrt`). Plain TCP checks to port 8890 are **not** a reliable test for SRT.

3. **Auth:** Wrong user/pass yields handshake failure; set **`MEDIAMTX_PUBLISH_PASS`** in gitignored **`.env`** (see [`video-gateway.env`](../video-gateway.env)).

4. **More FFmpeg detail:** set **`VIDEO_FFMPEG_LOGLEVEL=info`** (or **`verbose`**) in [`video-gateway.env`](../video-gateway.env), recreate **`video-gateway`**, and watch `docker compose logs -f video-gateway` for RTSP **401** / **ANNOUNCE** or SRT handshake errors.

## Verification

1. `docker compose logs -f video-gateway` — FFmpeg **publish start**, no repeated **authentication failed** from MediaMTX.
2. On the server, confirm a publisher is present on your configured **path** (e.g. **`skyscan_roof_sf_cam_hud`**) and any **`runOnReady`** relay is healthy.
