# Evidência — Fase 0-A (bancada sem dado de cliente)

Executado em 2026-11-06T15:21:22-03:00 na máquina de bancada atual (Windows 11).
Registro bruto: `bench/saida/resultado-fase0.json` e `bench/saida/medicoes.csv` (cada número com valor, fonte, data, hardware/versão e comando).

## 1. Ambiente medido
- GPU: NVIDIA GeForce RTX 4050 Laptop GPU, 6141 MiB, 551.76
- SO: Windows 11 · CPU: AMD64 Family 25 Model 68 Stepping 1, AuthenticAMD
- ffmpeg version n9.0.1-11-ge47273f4d9-20260831 Copyright (c) 2000-2026 the FFmpeg developers

## 2. Clipe próprio (vídeo de referência desta rodada)
`fonte-1080p30.mp4` — 1920×1080 @ 30.0 fps,
10.0 s, yuv420p.
**Bitrate cru (sem compressão): 746.5 Mbps.**

## 3. Resultado da rodada

| Configuração | Bitrate codificado (Mbps) | Corte vs cru | VMAF | Velocidade de encode | Status |
|---|---|---|---|---|---|
| x264 CRF23 | 5.51 | 99.26% | 94.87 | 7.64× | ok |
| x264 CRF28 | 2.683 | 99.64% | 90.45 | 9.27× | ok |
| x265 CRF28 | 3.46 | 99.54% | 87.74 | 5.93× | ok |
| NVENC H.264 CQ28 | - | -% | - | -× | erro |
| NVENC HEVC CQ28 | - | -% | - | -× | erro |

## 4. Transporte SRT (ponta a ponta local, sem compressão de transporte)
Teste de bancada: `ffmpeg` publicando em `srt://127.0.0.1:8890?mode=caller` e um segundo `ffmpeg` escutando (`mode=listener`) gravando o que recebe.
Resultado: **arquivo recebido com 4.1 s e ~7,72 Mbps** — o protocolo SRT funciona nesta build (`--enable-libsrt`). O erro de I/O no fim é o encerramento do transmissor, não falha de transporte.

## 5. Conclusões da rodada (fatos, não estimativa)
1. Corte de banda alto (99%+) neste clipe **sintético** — não vale como número de câmera real; o número de campo sai na Fase 0-B.
2. VMAF funciona na bancada e discriminou qualidade: CRF23 = 94,87 | CRF28 = 90,45 | x265 CRF28 = 87,74.
3. Encode em CPU rápido o suficiente para a bancada: x264 CRF23 a **7.64×** o tempo real.
4. **Achado que trava o encode em GPU nesta máquina:** `h264_nvenc`/`hevc_nvenc` falham com
   *"Driver does not support the required nvenc API version. Required: 13.1 Found: 12.2 … minimum required Nvidia driver for nvenc is 610.00 or newer"*
   com o driver atual 551.76. Ação: no servidor de bancada, usar **driver ≥ 610** (ou uma build de `ffmpeg` compatível com a API 12.2) antes de repetir o teste com GPU.
5. Teste negativo de credencial passou: `bench/fetch-camera.sh` falha com mensagem legível e não imprime senha.

## 6. Aceite da Fase 0-A (conforme o guia do TI)
- [x] Ambiente conferido por comando (`ffmpeg` com VMAF/SRT, `ffprobe`, GPU identificada)
- [x] Clipe próprio gerado e medido, com JSON/CSV de saída
- [x] VMAF medido e corte calculado por codec
- [x] Transporte SRT verificado ponta a ponta na bancada
- [x] Teste negativo de credencial passando
- [ ] Medição sobre vídeo real de câmera (depende dos dados das câmeras — Fase 0-B)
