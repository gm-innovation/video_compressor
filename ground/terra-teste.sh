#!/bin/bash
# Publica a fonte "terra" no mediamtx, com relogio queimado, para medir o sentido terra->bordo.
# 4K de origem -> 720p30 a 3000k, que e o ponto de operacao do produto (Cenario 2).
#
#   systemd-run --unit=terra-teste --collect /bin/bash /opt/pipeline/app/ground/terra-teste.sh
#   systemctl stop terra-teste      # no fim, para nao deixar publicando
#
# O bordo (receptor) puxa com:
#   ffmpeg -i "srt://<ip-da-vps>:8890?streamid=read:terra-teste" -t 60 -c copy recebido.ts
cd /opt/pipeline/app || exit 1
exec ffmpeg -hide_banner -loglevel warning -re -stream_loop -1 -i ground/medicoes-hd/c-4k-20000k.mp4 \
  -vf "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='%{localtime\:%T}':x=24:y=24:fontsize=56:fontcolor=white:box=1:boxcolor=black@0.7,scale=1280:-2" \
  -c:v libx264 -preset veryfast -tune zerolatency -b:v 3000k -maxrate 3300k -bufsize 1500k \
  -g 30 -r 30 -an -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/terra-teste
