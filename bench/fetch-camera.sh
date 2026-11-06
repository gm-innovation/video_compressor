#!/usr/bin/env bash
# Fase 0-B: puxa um clipe real da câmera/DVR por RTSP, só por dentro da VPN.
# A senha vem SEMPRE do ambiente (.env carregado por quem chama). Nunca por argumento.
set -euo pipefail
: "${CAM_URL:?CAM_URL nao definido (copie .env.example para .env)}"
: "${CAM_USER:?CAM_USER nao definido - usar usuario dedicado somente-leitura}"
: "${CAM_PASS:?CAM_PASS nao definido - senha vem do cofre/ambiente, nunca do chat}"
segundos="${1:-30}"
saida="${2:-saida/camera-${CAM_ID:-camera}.mp4}"
mkdir -p "$(dirname "$saida")"
url="$(printf '%s' "$CAM_URL" | sed -E 's#^(rtsp://)#\1')"
# monta a URL com credencial em memoria, sem escrever em arquivo
full="${url%%://*}://${CAM_USER}:${CAM_PASS}@${url#*://}"
ffmpeg -hide_banner -loglevel warning -rtsp_transport tcp -i "$full" -t "$segundos" -c copy "$saida"
echo "[ok] clipe salvo em $saida"
