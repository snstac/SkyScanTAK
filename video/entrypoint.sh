#!/bin/bash
set -euo pipefail

cleanup() {
  for j in $(jobs -p 2>/dev/null || true); do
    kill "${j}" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

VIDEO_ENABLE="${VIDEO_ENABLE:-true}"
if [[ "${VIDEO_ENABLE}" != "true" && "${VIDEO_ENABLE}" != "1" && "${VIDEO_ENABLE}" != "yes" ]]; then
  echo "VIDEO_ENABLE is off; sleeping."
  exec sleep infinity
fi

RTSP="${CAMERA_RTSP_URL:-}"
if [[ -z "${RTSP}" ]]; then
  IP="${CAMERA_IP:?CAMERA_IP or CAMERA_RTSP_URL required}"
  U="${CAMERA_USER:-root}"
  P="${CAMERA_PASSWORD:?CAMERA_PASSWORD required when CAMERA_RTSP_URL unset}"
  RTSP="rtsp://${U}:${P}@${IP}/axis-media/media.amp?videocodec=h264"
fi

FFMPEG_LOG="${VIDEO_FFMPEG_LOGLEVEL:-warning}"
RTSP_FLAGS=( -hide_banner -loglevel "${FFMPEG_LOG}" -fflags +genpts -rtsp_transport tcp )
KLV_EN="${VIDEO_KLV_ENABLE:-false}"

RAW_EN="${VIDEO_RAW_ENABLE:-false}"
HUD_EN="${VIDEO_HUD_ENABLE:-${VIDEO_FIRIS_ENABLE:-true}}"
SRT_HUD="${MEDIAMTX_SRT_URL_HUD:-${MEDIAMTX_SRT_URL_FIRIS:-}}"

_validate_mtx_srt_publish() {
  local label="$1" url="$2"
  [[ -z "${url}" ]] && return 0
  if [[ "${url}" == *"read%3A"* ]] || [[ "${url}" == *"streamid=read:"* ]] || [[ "${url}" == *"streamid=read%3A"* ]]; then
    echo "ERROR: ${label} is a MediaMTX SRT *read* URL, but this container must *publish*."
    echo "Use:  ...?streamid=#!::m=publish,r=live/your_path,u=USER,s=PASS&pkt_size=1316"
    echo "(Quote in .env; do not paste Play ISR / read:... / read%3A... strings into MEDIAMTX_SRT_URL_*.)"
    echo "Current value: ${url}"
    exit 1
  fi
}
_validate_mtx_srt_publish MEDIAMTX_SRT_URL_HUD "${SRT_HUD}"
_validate_mtx_srt_publish MEDIAMTX_SRT_URL_RAW "${MEDIAMTX_SRT_URL_RAW:-}"
PRESET="${VIDEO_PRESET:-veryfast}"
TUNE="${VIDEO_TUNE:-zerolatency}"
BR="${VIDEO_BITRATE:-4M}"
GOP="${VIDEO_GOP:-30}"
HUD="${VIDEO_HUD_PATH:-/tmp/skyscan_hud.txt}"
FIFO="${VIDEO_KLV_FIFO:-/tmp/skyscan_klv.fifo}"
FONT="${VIDEO_FONTFILE:-/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf}"
SIZE="${VIDEO_HUD_FONTSIZE:-26}"
HUD_X="${VIDEO_HUD_X:-24}"
HUD_Y="${VIDEO_HUD_Y:-20}"
HUD_FC="${VIDEO_HUD_FONTCOLOR:-#39FF14}"
HUD_BW="${VIDEO_HUD_BORDERW:-1}"
HUD_BC="${VIDEO_HUD_BORDERCOLOR:-black}"
HUD_LS="${VIDEO_HUD_LINE_SPACING:-4}"
HUD_BOX="${VIDEO_HUD_BOX:-0}"
HUD_BOXC="${VIDEO_HUD_BOXCOLOR:-black@0.42}"
HUD_BOXBW="${VIDEO_HUD_BOXBORDERW:-12}"
HUD_SHX="${VIDEO_HUD_SHADOWX:-0}"
HUD_SHY="${VIDEO_HUD_SHADOWY:-0}"
HUD_SHC="${VIDEO_HUD_SHADOWCOLOR:-black@0.75}"
THREAD_Q="${VIDEO_RTSP_THREAD_QUEUE:-4096}"
RESTART_EN="${VIDEO_FFMPEG_RESTART:-true}"
RESTART_DELAY="${VIDEO_FFMPEG_RESTART_DELAY_SEC:-5}"
VIDEO_ATAK_TS_TCP_ENABLE="${VIDEO_ATAK_TS_TCP_ENABLE:-true}"
VIDEO_ATAK_TS_TCP_PORT="${VIDEO_ATAK_TS_TCP_PORT:-8556}"

run_ffmpeg_supervised() {
  if [[ "${RESTART_EN}" != "true" && "${RESTART_EN}" != "1" && "${RESTART_EN}" != "yes" ]]; then
    ffmpeg "$@" &
    return
  fi
  (
    set +e
    while true; do
      echo "ffmpeg: publish start $(date -Iseconds)"
      ffmpeg "$@"
      code=$?
      echo "ffmpeg: stopped (exit ${code}), retry in ${RESTART_DELAY}s"
      sleep "${RESTART_DELAY}"
    done
  ) &
}

_buf() {
  case "${BR}" in
    *M|*m) local n="${BR%[Mm]}"; echo $(( n * 2000000 )) ;;
    *K|*k) local n="${BR%[Kk]}"; echo $(( n * 2000 )) ;;
    *) echo 8000000 ;;
  esac
}
BUFSIZE=$(_buf)

X264_PROFILE=()
if [[ -n "${VIDEO_X264_PROFILE:-}" ]]; then
  X264_PROFILE=( -profile:v "${VIDEO_X264_PROFILE}" )
fi
ENC_EXTRA=( -bf 0 "${X264_PROFILE[@]}" )

ENC=(
  -c:v libx264 -preset "${PRESET}" -tune "${TUNE}" -b:v "${BR}" -maxrate "${BR}" -bufsize "${BUFSIZE}"
  -g "${GOP}" -keyint_min "${GOP}" -sc_threshold 0 -pix_fmt yuv420p "${ENC_EXTRA[@]}"
)
VF="drawtext=fontfile=${FONT}:textfile=${HUD}:reload=1:fontsize=${SIZE}:fontcolor=${HUD_FC}:line_spacing=${HUD_LS}:borderw=${HUD_BW}:bordercolor=${HUD_BC}:box=${HUD_BOX}:boxcolor=${HUD_BOXC}:boxborderw=${HUD_BOXBW}:shadowx=${HUD_SHX}:shadowy=${HUD_SHY}:shadowcolor=${HUD_SHC}:x=${HUD_X}:y=${HUD_Y}"
# Two outputs need distinct filter pads; split duplicates frames to two libx264 encodes (MediaMTX SRT + ATAK tcp listen).
FC_HUD_2OUT="[0:v:0]${VF},split=2[h1][h2]"

# ATAK / UAS: MPEG-TS over tcp://0.0.0.0:VIDEO_ATAK_TS_TCP_PORT?listen=1 (H.264 + KLV) alongside SRT. Connect ATAK soon after start; until a client connects, FFmpeg may log TCP mux errors that clear once the stream is pulled.
_atak_tcp() {
  [[ "${VIDEO_ATAK_TS_TCP_ENABLE}" == "true" || "${VIDEO_ATAK_TS_TCP_ENABLE}" == "1" ]]
}

run_hud_klv_srt_maybe_atak() {
  if _atak_tcp; then
    echo "Starting HUD + KLV: SRT (MediaMTX) + ATAK tcp://0.0.0.0:${VIDEO_ATAK_TS_TCP_PORT}?listen=1 (two encodes)"
    run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
      -f data -i "${FIFO}" \
      -filter_complex "${FC_HUD_2OUT}" \
      -map "[h1]" -map 1:0 "${ENC[@]}" -an -c:d copy \
      -metadata:s:d:0 "handler_name=MetadataHandler" \
      -f mpegts "tcp://0.0.0.0:${VIDEO_ATAK_TS_TCP_PORT}?listen=1" \
      -map "[h2]" -map 1:0 "${ENC[@]}" -an -c:d copy \
      -metadata:s:d:0 "handler_name=MetadataHandler" \
      -f mpegts "${SRT_HUD}"
  else
    echo "Starting HUD + KLV SRT publish (VIDEO_ATAK_TS_TCP_ENABLE=false)"
    run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
      -f data -i "${FIFO}" \
      -map 0:v:0 -map 1:0 -vf "${VF}" "${ENC[@]}" -an -c:d copy \
      -metadata:s:d:0 "handler_name=MetadataHandler" \
      -f mpegts "${SRT_HUD}"
  fi
}

run_hud_noklv_srt_maybe_atak() {
  if _atak_tcp; then
    echo "Starting HUD (no KLV): SRT + ATAK tcp (two encodes)"
    run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
      -filter_complex "${FC_HUD_2OUT}" \
      -map "[h1]" "${ENC[@]}" -an -f mpegts "tcp://0.0.0.0:${VIDEO_ATAK_TS_TCP_PORT}?listen=1" \
      -map "[h2]" "${ENC[@]}" -an -f mpegts "${SRT_HUD}"
  else
    echo "Starting HUD SRT publish (H.264 only; KLV off)"
    run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
      -map 0:v:0 -vf "${VF}" "${ENC[@]}" -an -f mpegts "${SRT_HUD}"
  fi
}

RAW_ACTIVE=0
if [[ "${RAW_EN}" == "true" || "${RAW_EN}" == "1" ]] && [[ -n "${MEDIAMTX_SRT_URL_RAW:-}" ]]; then
  RAW_ACTIVE=1
elif [[ "${RAW_EN}" == "true" || "${RAW_EN}" == "1" ]]; then
  echo "VIDEO_RAW_ENABLE true but MEDIAMTX_SRT_URL_RAW empty; skip raw."
fi

HUD_ACTIVE=0
if [[ "${HUD_EN}" == "true" || "${HUD_EN}" == "1" ]] && [[ -n "${SRT_HUD}" ]]; then
  HUD_ACTIVE=1
elif [[ "${HUD_EN}" == "true" || "${HUD_EN}" == "1" ]]; then
  echo "VIDEO_HUD_ENABLE true but MEDIAMTX_SRT_URL_HUD empty; skip HUD SRT publish."
fi

# drawtext textfile must exist and be non-empty before ffmpeg starts (Python writes HUD later).
if [[ "${HUD_ACTIVE}" -eq 1 ]]; then
  printf '%s\n' ' ' > "${HUD}"
fi

if [[ "${RAW_ACTIVE}" -eq 1 && "${HUD_ACTIVE}" -eq 1 ]]; then
  if [[ "${KLV_EN}" == "true" || "${KLV_EN}" == "1" || "${KLV_EN}" == "yes" ]]; then
    rm -f "${FIFO}"
    mkfifo "${FIFO}"
    if _atak_tcp; then
      echo "Starting combined: raw SRT + HUD+KLV SRT + ATAK tcp (two encodes on HUD leg)"
      run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
        -f data -i "${FIFO}" \
        -filter_complex "${FC_HUD_2OUT}" \
        -map "[h1]" -map 1:0 "${ENC[@]}" -an -c:d copy \
        -metadata:s:d:0 "handler_name=MetadataHandler" \
        -f mpegts "tcp://0.0.0.0:${VIDEO_ATAK_TS_TCP_PORT}?listen=1" \
        -map 0:v:0 -an -c:v copy -f mpegts "${MEDIAMTX_SRT_URL_RAW}" \
        -map "[h2]" -map 1:0 "${ENC[@]}" -an -c:d copy \
        -metadata:s:d:0 "handler_name=MetadataHandler" \
        -f mpegts "${SRT_HUD}"
    else
      echo "Starting combined SRT publish (single RTSP): raw copy + HUD+KLV"
      run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
        -f data -i "${FIFO}" \
        -map 0:v:0 -an -c:v copy -f mpegts "${MEDIAMTX_SRT_URL_RAW}" \
        -map 0:v:0 -map 1:0 -vf "${VF}" "${ENC[@]}" -an -c:d copy \
        -metadata:s:d:0 "handler_name=MetadataHandler" \
        -f mpegts "${SRT_HUD}"
    fi
  else
    if _atak_tcp; then
      echo "Starting combined: raw SRT + HUD SRT + ATAK tcp (two encodes, no KLV)"
      run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
        -filter_complex "${FC_HUD_2OUT}" \
        -map "[h1]" "${ENC[@]}" -an -f mpegts "tcp://0.0.0.0:${VIDEO_ATAK_TS_TCP_PORT}?listen=1" \
        -map 0:v:0 -an -c:v copy -f mpegts "${MEDIAMTX_SRT_URL_RAW}" \
        -map "[h2]" "${ENC[@]}" -an -f mpegts "${SRT_HUD}"
    else
      echo "Starting combined SRT publish (single RTSP): raw copy + HUD (KLV off)"
      run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
        -map 0:v:0 -an -c:v copy -f mpegts "${MEDIAMTX_SRT_URL_RAW}" \
        -map 0:v:0 -vf "${VF}" "${ENC[@]}" -an -f mpegts "${SRT_HUD}"
    fi
  fi
elif [[ "${RAW_ACTIVE}" -eq 1 ]]; then
  echo "Starting raw SRT publish"
  run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
    -map 0:v:0 -an \
    -c:v copy \
    -f mpegts "${MEDIAMTX_SRT_URL_RAW}"
elif [[ "${HUD_ACTIVE}" -eq 1 ]]; then
  if [[ "${KLV_EN}" == "true" || "${KLV_EN}" == "1" || "${KLV_EN}" == "yes" ]]; then
    rm -f "${FIFO}"
    mkfifo "${FIFO}"
    run_hud_klv_srt_maybe_atak
  else
    run_hud_noklv_srt_maybe_atak
  fi
fi

export PYTHONPATH="${PYTHONPATH:-/app}"
/opt/venv/bin/python3 -m video
