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

PROTO_RAW="${MEDIAMTX_PUBLISH_PROTOCOL:-srt}"
PROTO="$(echo "${PROTO_RAW}" | tr '[:upper:]' '[:lower:]')"
case "${PROTO}" in
  rtsp|srt) ;;
  *)
    echo "WARN: MEDIAMTX_PUBLISH_PROTOCOL=${PROTO_RAW} unsupported; using srt"
    PROTO=srt
    ;;
esac

if [[ "${PROTO}" == "rtsp" ]]; then
  MTX_OUT=( -f rtsp -rtsp_transport tcp )
  echo "MediaMTX publish protocol: RTSP (port ${MEDIAMTX_RTSP_PORT:-8554})"
else
  MTX_OUT=( -f mpegts )
  echo "MediaMTX publish protocol: SRT (port ${MEDIAMTX_SRT_PORT:-8890})"
fi

_mtx_build_srt_url() {
  local host="$1" port="$2" rpath="$3" user="$4" pass="$5"
  [[ -z "${host}" || -z "${rpath}" || -z "${user}" || -z "${pass}" ]] && return 1
  echo "srt://${host}:${port}?streamid=#!::m=publish,r=${rpath},u=${user},s=${pass}&pkt_size=1316"
}

_mtx_build_rtsp_publish_url() {
  local host="$1" port="$2" rpath="$3" user="$4" pass="$5"
  [[ -z "${host}" || -z "${rpath}" || -z "${user}" || -z "${pass}" ]] && return 1
  # Path is URL path after host:port (slashes allowed for nested paths; default is skyscan_<deployment>_cam_*)
  echo "rtsp://${user}:${pass}@${host}:${port}/${rpath}"
}

_mh_pub() { echo "${MEDIAMTX_PUBLIC_HOST:-}"; }
_mu_pub() { echo "${MEDIAMTX_PUBLISH_USER:-}"; }
_mp_pub() { echo "${MEDIAMTX_PUBLISH_PASS:-}"; }
_mport_srt() { echo "${MEDIAMTX_SRT_PORT:-8890}"; }
_mport_rtsp_mtx() { echo "${MEDIAMTX_RTSP_PORT:-8554}"; }

DEST_HUD=""
if [[ "${HUD_EN}" == "true" || "${HUD_EN}" == "1" || "${HUD_EN}" == "yes" ]]; then
  if [[ "${PROTO}" == "rtsp" ]]; then
    DEST_HUD="${MEDIAMTX_RTSP_URL_HUD:-}"
    if [[ -z "${DEST_HUD}" ]]; then
      _pathh="${MEDIAMTX_PUBLISH_PATH_HUD:-}"
      if [[ -z "${_pathh}" && -n "${DEPLOYMENT:-}" ]]; then
        _pathh="skyscan_${DEPLOYMENT}_cam_hud"
      fi
      if [[ -n "$(_mh_pub)" && -n "$(_mu_pub)" && -n "$(_mp_pub)" && -n "${_pathh}" ]]; then
        DEST_HUD="$(_mtx_build_rtsp_publish_url "$(_mh_pub)" "$(_mport_rtsp_mtx)" "${_pathh}" "$(_mu_pub)" "$(_mp_pub)")"
        echo "Built RTSP HUD (video-only) URL from MEDIAMTX_* (path ${_pathh})"
      fi
    fi
  else
    DEST_HUD="${MEDIAMTX_SRT_URL_HUD:-${MEDIAMTX_SRT_URL_FIRIS:-}}"
    if [[ -z "${DEST_HUD}" ]]; then
      _pathh="${MEDIAMTX_PUBLISH_PATH_HUD:-}"
      if [[ -z "${_pathh}" && -n "${DEPLOYMENT:-}" ]]; then
        _pathh="skyscan_${DEPLOYMENT}_cam_hud"
      fi
      if [[ -n "$(_mh_pub)" && -n "$(_mu_pub)" && -n "$(_mp_pub)" && -n "${_pathh}" ]]; then
        DEST_HUD="$(_mtx_build_srt_url "$(_mh_pub)" "$(_mport_srt)" "${_pathh}" "$(_mu_pub)" "$(_mp_pub)")"
        echo "Built SRT HUD (video-only) URL from MEDIAMTX_* (path ${_pathh})"
      fi
    fi
  fi
fi

DEST_RAW=""
if [[ "${PROTO}" == "rtsp" ]]; then
  DEST_RAW="${MEDIAMTX_RTSP_URL_RAW:-}"
  if [[ -z "${DEST_RAW}" ]] && [[ "${RAW_EN}" == "true" || "${RAW_EN}" == "1" ]]; then
    _pr="${MEDIAMTX_PUBLISH_PATH_RAW:-}"
    if [[ -z "${_pr}" && -n "${DEPLOYMENT:-}" ]]; then
      _pr="skyscan_${DEPLOYMENT}_cam_raw"
    fi
    if [[ -n "${_pr}" && -n "$(_mh_pub)" && -n "$(_mu_pub)" && -n "$(_mp_pub)" ]]; then
      DEST_RAW="$(_mtx_build_rtsp_publish_url "$(_mh_pub)" "$(_mport_rtsp_mtx)" "${_pr}" "$(_mu_pub)" "$(_mp_pub)")"
      echo "Built RTSP RAW URL from MEDIAMTX_* (path ${_pr})"
    fi
  elif [[ -z "${DEST_RAW}" ]]; then
    _pr="${MEDIAMTX_PUBLISH_PATH_RAW:-}"
    if [[ -n "${_pr}" && -n "$(_mh_pub)" && -n "$(_mu_pub)" && -n "$(_mp_pub)" ]]; then
      DEST_RAW="$(_mtx_build_rtsp_publish_url "$(_mh_pub)" "$(_mport_rtsp_mtx)" "${_pr}" "$(_mu_pub)" "$(_mp_pub)")"
      echo "Built RTSP RAW URL from MEDIAMTX_* (path ${_pr})"
    fi
  fi
else
  DEST_RAW="${MEDIAMTX_SRT_URL_RAW:-}"
  if [[ -z "${DEST_RAW}" ]] && [[ "${RAW_EN}" == "true" || "${RAW_EN}" == "1" ]]; then
    _pr="${MEDIAMTX_PUBLISH_PATH_RAW:-}"
    if [[ -z "${_pr}" && -n "${DEPLOYMENT:-}" ]]; then
      _pr="skyscan_${DEPLOYMENT}_cam_raw"
    fi
    if [[ -n "${_pr}" && -n "$(_mh_pub)" && -n "$(_mu_pub)" && -n "$(_mp_pub)" ]]; then
      DEST_RAW="$(_mtx_build_srt_url "$(_mh_pub)" "$(_mport_srt)" "${_pr}" "$(_mu_pub)" "$(_mp_pub)")"
      echo "Built SRT RAW URL from MEDIAMTX_* (path ${_pr})"
    fi
  elif [[ -z "${DEST_RAW}" ]]; then
    _pr="${MEDIAMTX_PUBLISH_PATH_RAW:-}"
    if [[ -n "${_pr}" && -n "$(_mh_pub)" && -n "$(_mu_pub)" && -n "$(_mp_pub)" ]]; then
      DEST_RAW="$(_mtx_build_srt_url "$(_mh_pub)" "$(_mport_srt)" "${_pr}" "$(_mu_pub)" "$(_mp_pub)")"
      echo "Built SRT RAW URL from MEDIAMTX_* (path ${_pr})"
    fi
  fi
fi

DEST_HUD_KLV=""
if [[ "${HUD_EN}" == "true" || "${HUD_EN}" == "1" || "${HUD_EN}" == "yes" ]]; then
  if [[ "${KLV_EN}" == "true" || "${KLV_EN}" == "1" || "${KLV_EN}" == "yes" ]]; then
    if [[ "${PROTO}" == "rtsp" ]]; then
      DEST_HUD_KLV="${MEDIAMTX_RTSP_URL_HUD_KLV:-}"
      if [[ -z "${DEST_HUD_KLV}" ]]; then
        _pk="${MEDIAMTX_PUBLISH_PATH_HUD_KLV:-}"
        if [[ -z "${_pk}" && -n "${DEPLOYMENT:-}" ]]; then
          _pk="skyscan_${DEPLOYMENT}_cam_hud_klv"
        fi
        if [[ -n "${_pk}" && -n "$(_mh_pub)" && -n "$(_mu_pub)" && -n "$(_mp_pub)" ]]; then
          DEST_HUD_KLV="$(_mtx_build_rtsp_publish_url "$(_mh_pub)" "$(_mport_rtsp_mtx)" "${_pk}" "$(_mu_pub)" "$(_mp_pub)")"
          echo "Built RTSP HUD+KLV URL from MEDIAMTX_* (path ${_pk})"
        fi
      fi
    else
      DEST_HUD_KLV="${MEDIAMTX_SRT_URL_HUD_KLV:-}"
      if [[ -z "${DEST_HUD_KLV}" ]]; then
        _pk="${MEDIAMTX_PUBLISH_PATH_HUD_KLV:-}"
        if [[ -z "${_pk}" && -n "${DEPLOYMENT:-}" ]]; then
          _pk="skyscan_${DEPLOYMENT}_cam_hud_klv"
        fi
        if [[ -n "${_pk}" && -n "$(_mh_pub)" && -n "$(_mu_pub)" && -n "$(_mp_pub)" ]]; then
          DEST_HUD_KLV="$(_mtx_build_srt_url "$(_mh_pub)" "$(_mport_srt)" "${_pk}" "$(_mu_pub)" "$(_mp_pub)")"
          echo "Built SRT HUD+KLV URL from MEDIAMTX_* (path ${_pk})"
        fi
      fi
    fi
  fi
fi

_validate_mtx_srt_publish() {
  local label="$1" url="$2"
  [[ -z "${url}" ]] && return 0
  if [[ "${url}" == *"read%3A"* ]] || [[ "${url}" == *"streamid=read:"* ]] || [[ "${url}" == *"streamid=read%3A"* ]]; then
    echo "ERROR: ${label} is a MediaMTX SRT *read* URL, but this container must *publish*."
    echo "Use:  ...?streamid=#!::m=publish,r=your/mediamtx/path,u=USER,s=PASS&pkt_size=1316"
    echo "(Quote in .env; do not paste Play ISR / read:... / read%3A... strings into MEDIAMTX_SRT_URL_*.)"
    echo "Current value: ${url}"
    exit 1
  fi
}
if [[ "${PROTO}" == "srt" ]]; then
  _validate_mtx_srt_publish MEDIAMTX_SRT_URL_HUD "${DEST_HUD}"
  _validate_mtx_srt_publish MEDIAMTX_SRT_URL_RAW "${DEST_RAW}"
  _validate_mtx_srt_publish MEDIAMTX_SRT_URL_HUD_KLV "${DEST_HUD_KLV}"
fi

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
# split=2: ATAK + MediaMTX HUD (no KLV on video-only leg), or two HUD encodes when only two HUD legs needed.
FC_HUD_2OUT="[0:v:0]${VF},split=2[h1][h2]"
# split=3: ATAK+KLV, MediaMTX HUD video-only, MediaMTX HUD+KLV (three libx264 encodes).
FC_HUD_3OUT="[0:v:0]${VF},split=3[ha][hs][hk]"

_atak_tcp() {
  [[ "${VIDEO_ATAK_TS_TCP_ENABLE}" == "true" || "${VIDEO_ATAK_TS_TCP_ENABLE}" == "1" ]]
}

run_hud_noklv_mtx_maybe_atak() {
  if _atak_tcp; then
    echo "Starting HUD (no KLV): MediaMTX ${PROTO} (video-only) + ATAK tcp (two encodes)"
    run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
      -filter_complex "${FC_HUD_2OUT}" \
      -map "[h1]" "${ENC[@]}" -an -f mpegts "tcp://0.0.0.0:${VIDEO_ATAK_TS_TCP_PORT}?listen=1" \
      -map "[h2]" "${ENC[@]}" -an "${MTX_OUT[@]}" "${DEST_HUD}"
  else
    echo "Starting HUD MediaMTX ${PROTO} publish (H.264 only; KLV off)"
    run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
      -map 0:v:0 -vf "${VF}" "${ENC[@]}" -an "${MTX_OUT[@]}" "${DEST_HUD}"
  fi
}

# HUD + KLV: separate MediaMTX paths for video-only vs video+KLV; ATAK gets HUD+KLV.
run_hud_klv_multi_mtx_maybe_atak() {
  [[ -n "${DEST_HUD_KLV}" ]] || {
    echo "ERROR: VIDEO_KLV_ENABLE=true requires MEDIAMTX_*_URL_HUD_KLV or MEDIAMTX_PUBLISH_PATH_HUD_KLV or DEPLOYMENT for default ..._cam_hud_klv"
    exit 1
  }
  rm -f "${FIFO}"
  mkfifo "${FIFO}"
  if _atak_tcp; then
    echo "Starting HUD+KLV multi-path: ATAK tcp + MediaMTX ${PROTO} HUD (video-only) + ${PROTO} HUD+KLV (three libx264 encodes)"
    run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
      -f data -i "${FIFO}" \
      -filter_complex "${FC_HUD_3OUT}" \
      -map "[ha]" -map 1:0 "${ENC[@]}" -an -c:d copy \
      -metadata:s:d:0 "handler_name=MetadataHandler" \
      -f mpegts "tcp://0.0.0.0:${VIDEO_ATAK_TS_TCP_PORT}?listen=1" \
      -map "[hs]" "${ENC[@]}" -an "${MTX_OUT[@]}" "${DEST_HUD}" \
      -map "[hk]" -map 1:0 "${ENC[@]}" -an -c:d copy \
      -metadata:s:d:0 "handler_name=MetadataHandler" \
      "${MTX_OUT[@]}" "${DEST_HUD_KLV}"
  else
    echo "Starting HUD+KLV multi-path: MediaMTX ${PROTO} HUD (video-only) + ${PROTO} HUD+KLV (two encodes)"
    run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
      -f data -i "${FIFO}" \
      -filter_complex "[0:v:0]${VF},split=2[hs][hk]" \
      -map "[hs]" "${ENC[@]}" -an "${MTX_OUT[@]}" "${DEST_HUD}" \
      -map "[hk]" -map 1:0 "${ENC[@]}" -an -c:d copy \
      -metadata:s:d:0 "handler_name=MetadataHandler" \
      "${MTX_OUT[@]}" "${DEST_HUD_KLV}"
  fi
}

RAW_ACTIVE=0
if [[ "${RAW_EN}" == "true" || "${RAW_EN}" == "1" ]] && [[ -n "${DEST_RAW:-}" ]]; then
  RAW_ACTIVE=1
elif [[ "${RAW_EN}" == "true" || "${RAW_EN}" == "1" ]]; then
  echo "VIDEO_RAW_ENABLE true but MediaMTX raw publish URL empty; skip raw."
fi

HUD_ACTIVE=0
if [[ "${HUD_EN}" == "true" || "${HUD_EN}" == "1" ]] && [[ -n "${DEST_HUD}" ]]; then
  HUD_ACTIVE=1
elif [[ "${HUD_EN}" == "true" || "${HUD_EN}" == "1" ]]; then
  echo "VIDEO_HUD_ENABLE true but MediaMTX HUD publish URL empty; skip HUD publish."
fi

if [[ "${HUD_ACTIVE}" -eq 1 ]] && [[ "${KLV_EN}" == "true" || "${KLV_EN}" == "1" || "${KLV_EN}" == "yes" ]] && [[ -z "${DEST_HUD_KLV}" ]]; then
  echo "ERROR: VIDEO_KLV_ENABLE=true with HUD publish active requires MEDIAMTX_*_URL_HUD_KLV, MEDIAMTX_PUBLISH_PATH_HUD_KLV, or DEPLOYMENT for default skyscan_\${DEPLOYMENT}_cam_hud_klv (plus MEDIAMTX_PUBLIC_HOST and publish credentials)."
  exit 1
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
      echo "Starting combined: raw ${PROTO} + ATAK tcp + HUD ${PROTO} (video-only) + HUD+KLV ${PROTO} (three HUD encodes)"
      run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
        -f data -i "${FIFO}" \
        -filter_complex "${FC_HUD_3OUT}" \
        -map "[ha]" -map 1:0 "${ENC[@]}" -an -c:d copy \
        -metadata:s:d:0 "handler_name=MetadataHandler" \
        -f mpegts "tcp://0.0.0.0:${VIDEO_ATAK_TS_TCP_PORT}?listen=1" \
        -map 0:v:0 -an -c:v copy "${MTX_OUT[@]}" "${DEST_RAW}" \
        -map "[hs]" "${ENC[@]}" -an "${MTX_OUT[@]}" "${DEST_HUD}" \
        -map "[hk]" -map 1:0 "${ENC[@]}" -an -c:d copy \
        -metadata:s:d:0 "handler_name=MetadataHandler" \
        "${MTX_OUT[@]}" "${DEST_HUD_KLV}"
    else
      echo "Starting combined: raw ${PROTO} + HUD ${PROTO} (video-only) + HUD+KLV ${PROTO} (two HUD encodes)"
      run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
        -f data -i "${FIFO}" \
        -filter_complex "[0:v:0]${VF},split=2[hs][hk]" \
        -map 0:v:0 -an -c:v copy "${MTX_OUT[@]}" "${DEST_RAW}" \
        -map "[hs]" "${ENC[@]}" -an "${MTX_OUT[@]}" "${DEST_HUD}" \
        -map "[hk]" -map 1:0 "${ENC[@]}" -an -c:d copy \
        -metadata:s:d:0 "handler_name=MetadataHandler" \
        "${MTX_OUT[@]}" "${DEST_HUD_KLV}"
    fi
  else
    if _atak_tcp; then
      echo "Starting combined: raw ${PROTO} + HUD ${PROTO} + ATAK tcp (two encodes, no KLV)"
      run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
        -filter_complex "${FC_HUD_2OUT}" \
        -map "[h1]" "${ENC[@]}" -an -f mpegts "tcp://0.0.0.0:${VIDEO_ATAK_TS_TCP_PORT}?listen=1" \
        -map 0:v:0 -an -c:v copy "${MTX_OUT[@]}" "${DEST_RAW}" \
        -map "[h2]" "${ENC[@]}" -an "${MTX_OUT[@]}" "${DEST_HUD}"
    else
      echo "Starting combined MediaMTX ${PROTO} publish (single camera RTSP): raw copy + HUD (KLV off)"
      run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
        -map 0:v:0 -an -c:v copy "${MTX_OUT[@]}" "${DEST_RAW}" \
        -map 0:v:0 -vf "${VF}" "${ENC[@]}" -an "${MTX_OUT[@]}" "${DEST_HUD}"
    fi
  fi
elif [[ "${RAW_ACTIVE}" -eq 1 ]]; then
  echo "Starting raw MediaMTX ${PROTO} publish"
  run_ffmpeg_supervised "${RTSP_FLAGS[@]}" -thread_queue_size "${THREAD_Q}" -i "${RTSP}" \
    -map 0:v:0 -an \
    -c:v copy \
    "${MTX_OUT[@]}" "${DEST_RAW}"
elif [[ "${HUD_ACTIVE}" -eq 1 ]]; then
  if [[ "${KLV_EN}" == "true" || "${KLV_EN}" == "1" || "${KLV_EN}" == "yes" ]]; then
    run_hud_klv_multi_mtx_maybe_atak
  else
    run_hud_noklv_mtx_maybe_atak
  fi
fi

export PYTHONPATH="${PYTHONPATH:-/app}"
/opt/venv/bin/python3 -m video
