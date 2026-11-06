#!/usr/bin/env bash
# Fase 0-A: gera o clipe proprio e roda as medicoes de corte, VMAF e velocidade.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p saida
fonte="saida/fonte-1080p30.mp4"
if [ ! -f "$fonte" ]; then
  echo "[1/3] gerando clipe proprio 1080p30 10s (testsrc2 + movimento)"
  ffmpeg -y -hide_banner -loglevel error \
    -f lavfi -i "testsrc2=size=1920x1080:rate=30:duration=10" \
    -f lavfi -i "sine=frequency=440:duration=10" \
    -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -c:a aac -shortest "$fonte"
else
  echo "[1/3] clipe proprio ja existe: $fonte"
fi
echo "[2/3] conferindo ferramentas"
ffmpeg -hide_banner -filters  | grep -qi vmaf   && echo "  ok: libvmaf presente"   || echo "  ATENCAO: libvmaf ausente"
ffmpeg -hide_banner -encoders | grep -qi nvenc  && echo "  ok: NVENC presente"     || echo "  ATENCAO: NVENC ausente (roda so em CPU)"
echo "[3/3] medindo"
python measure.py --entrada "$fonte" --json saida/resultado-fase0.json --csv saida/medicoes.csv --pasta saida
