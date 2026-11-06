# Evidência — fluxo ponta a ponta na bancada (agente de bordo → SRT → lado terra → portal)

Data: 2026-11-06 · Máquina: bancada local (Windows 11) · sem dado de cliente, sem câmera real.

## O que foi executado
1. `python board/agent.py` — lê o perfil `board/perfis/bancada.json` (2 câmeras sintéticas 1280×720@30, uma a 1500k e outra a 800k), codifica com `libx264` e publica em SRT (`mode=caller`).
2. `python ground/receiver.py` — escuta SRT (`mode=listener`, portas 8891 e 8892), remuxa para HLS e grava `ground/status.json`.
3. `python ground/api.py 8765` — serve o portal e a API (`/api/resumo`, `/api/fluxos`).

## Resultado verificado por ferramenta
- `ground/status.json`: **cam-01 e cam-02 "no ar"** (`manifesto_existe: true`, 0 reinícios).
- `portal/streams/cam-01/index.m3u8` publicado com segmentos de 1 s sendo rotacionados (media sequence avançando).
- `curl http://127.0.0.1:8765/streams/cam-01/index.m3u8` → 200; segmento `seg048.ts` → 200.
- **`ffprobe` sobre o HLS servido pelo portal** retornou `h264 1280x720 30/1` em formato `hls` — prova de que a imagem codificada a bordo chega decodificável no lado terra.
- Telemetria do agente gravada no banco como medição da fase 2 (`fonte: board/agent.py`), com os 5 campos obrigatórios.

## Limites desta rodada (declarados)
1. O HLS tem buffer de ~6 s (não cumpre os ≤3 s exigidos) — a versão de produção do lado terra usa **WebRTC** (`mediamtx`), que ainda não foi instalado (sem Docker na bancada).
2. O vídeo renderizado na página do portal não foi confirmado por captura (player do Chrome headless fica preto); a prova de entrega é o `ffprobe` do HLS servido, não o quadro na tela.
3. Perfil e fontes são sintéticos; a validação de câmera real entra quando o servidor e os dados estiverem disponíveis.
