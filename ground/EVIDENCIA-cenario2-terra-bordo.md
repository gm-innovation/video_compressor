# Cenário 2 — TV terra→bordo: medição do enlace (11/11/2026)

Primeira medição do **sentido inverso** do pipeline: a terra (VPS) publica e o **bordo** (bancada,
atrás do 4G) puxa e grava 60 s. Até aqui só havia medição bordo→terra.

## Montagem (o que rodou, onde)

| Papel | Onde | O que rodou |
|---|---|---|
| terra (publicador) | VPS 187.127.60.250, unidade transitória `terra-teste` | `ground/terra-teste.sh`: 4K `ground/medicoes-hd/c-4k-20000k.mp4` → 720p30, alvo 3000k, `-preset veryfast -tune zerolatency -g 30`, relógio queimado (drawtext `%{localtime:%T}`), publicado no mediamtx em `rtsp://127.0.0.1:8554/terra-teste` |
| bordo (receptor) | bancada, 4G (IP público 189.92.224.56) | `ffmpeg -i "srt://187.127.60.250:8890?streamid=read:terra-teste" -t 60 -c copy recebido.ts` |

O caminho bordo→terra do produto é o agente puxando; aqui a terra publica e o bordo **puxa** o
mesmo fluxo (o 4G da bancada não aceita conexão de entrada, então o receptor é quem chama).

## Resultado medido

| Medida | Valor | Como foi medido |
|---|---|---|
| **Taxa entregue em bordo** | **3,156 Mbps** (23.673.712 bytes em 60,03 s de vídeo) | `ffprobe`/`ffmpeg` no arquivo recebido |
| **Quadros / resolução** | 1.800 quadros = **30,0 fps**, 1280×720 | `ffprobe -show_entries stream=r_frame_rate,width,height` |
| **Latência ponta a ponta** | **≈2 s** (relógio queimado 20:12:43 UTC no último quadro recebido; 20:12:45 UTC no fim da captura em bordo) | quadro extraído do arquivo + relógio local de bordo; resolução de 1 s |
| **Qualidade do encode no ponto de operação** | **SSIM All 0,9989** (Y 0,99883) | `ffmpeg … ssim` na VPS, 4K de origem → 720p 3000k, 20 s |
| **Integridade no transporte** | 1 aviso de decodificação em 1.800 quadros; o quadro do fim do arquivo decodifica sem artefato visível | `ffmpeg -v error -i recebido.ts -f null -` + inspeção do quadro |
| RTT do enlace | **não medido** — o 4G da bancada descarta ICMP (4/4 pacotes perdidos) | `ping -c 4 189.92.224.56` |

## O que ainda não está medido (dito com todas as letras)

- Enlace **Starlink Maritime** de verdade: o teste atravessou o 4G da bancada.
- **N canais simultâneos** no mesmo enlace (a medição é de 1 fluxo de 3 Mbps).
- Latência com **cena real**: o insumo é o padrão de barras com relógio queimado (mesmo arquivo das
  medições do Cenário 1), que comprime muito bem — 20 s do mesmo encode deram 2.261 kbps de média.
- RTT e retransmissões da conexão SRT de leitura: a conexão fecha no fim da captura e sai da lista
  do mediamtx antes da consulta `/v3/srtconns/list`.

## Reproduzir

```bash
# terra (VPS)
systemd-run --unit=terra-teste --collect /bin/bash /opt/pipeline/app/ground/terra-teste.sh
systemctl stop terra-teste          # no fim, para não deixar publicando

# bordo (bancada)
ffmpeg -hide_banner -i "srt://187.127.60.250:8890?streamid=read:terra-teste" -t 60 -c copy recebido.ts
ffprobe -v error -show_entries stream=width,height,r_frame_rate -show_entries format=duration,bit_rate recebido.ts
```
