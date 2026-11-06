#!/usr/bin/env bash
# Publica o video de bancada das analises como cam-03 dentro do mediamtx (fluxo interno, nao e
# a camera de verdade): e o mesmo caminho que o agente de bordo vai ler na embarcacao.
set -e
BASE="$(cd "$(dirname "$0")/.." && pwd)"
BASE="$(cygpath -m "$BASE" 2>/dev/null || echo "$BASE")"   # o ffmpeg e nativo: precisa de caminho Windows
FFMPEG="${FFMPEG:-$HOME/AppData/Local/hermes/tools/ffmpeg-9.0.1-win32-x64/bin/ffmpeg.exe}"
exec "$FFMPEG" -hide_banner -loglevel warning -re -stream_loop -1 \
  -i "$BASE/analytics/midia/people-detection.mp4" -c:v copy -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam-03
