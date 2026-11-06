#!/usr/bin/env bash
# Sobe o lado terra na bancada: mediamtx recebendo SRT e publicando WebRTC/HLS.
# Argumento opcional: caminho do config (padrao grounds/mediamtx.yml).
set -euo pipefail
raiz="$(cd "$(dirname "$0")/.." && pwd)"
bin="$raiz/tools/mediamtx/mediamtx.exe"
[ -x "$bin" ] || { echo "mediamtx nao encontrado em $bin (baixe o release windows_amd64)" >&2; exit 2; }
cfg="${1:-$raiz/ground/mediamtx.yml}"
echo "[ground] mediamtx com $cfg"
exec "$bin" "$cfg"
