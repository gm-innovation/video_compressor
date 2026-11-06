# Pipeline de vídeo bordo→terra — Lecsor Technology

Repositório base do pipeline (ver planos 1, 2 e 3 do projeto). Fase 0-A executada e
o caminho completo **bordo → terra → tela** rodando na bancada com vídeo próprio.

## Estrutura
- `bench/`  — scripts de medição (corte de banda, VMAF, latência, benchmark de encode)
- `board/`  — agente de bordo: codifica N câmeras, publica em SRT, watchdog e telemetria
- `ground/` — lado terra: mediamtx (SRT → WebRTC/HLS/RTSP) + API/banco do acompanhamento
- `portal/` — front do operador (fluxos ao vivo por WebRTC/WHEP) + módulo de acompanhamento
- `db/`     — schema/migrations e o banco local da bancada (SQLite)
- `tests/`  — testes automatizados
- `tools/`  — binários de bancada (mediamtx v1.21.3 windows_amd64)

## Como rodar na bancada
```
# 1. lado terra (mediamtx): recebe SRT e publica WebRTC/HLS/RTSP
./ground/start-mediamtx.sh

# 2. agente de bordo: 2 câmeras sintéticas 720p30 publicando em SRT
python board/agent.py                    # perfil: board/perfis/bancada.json

# 3. portal + API + banco
python ground/api.py 8765                # http://127.0.0.1:8765/
```
Saída da medição de banda/VMAF: `bench/saida/resultado-fase0.json` e `medicoes.csv`.

## Medições feitas na bancada (nada digitado à mão)

| medição | resultado | onde |
|---|---|---|
| corte de banda (x264 CRF23, 1080p30) | 5,51 Mbps · VMAF 94,87 · 9,5× tempo real | `bench/EVIDENCIA-fase0a.md` |
| fluxo ponta a ponta (agente → SRT → portal) | cam-01/cam-02 no ar, 0 reinícios, HLS 1280×720 30 fps | `ground/EVIDENCIA-fluxo-ponta-a-ponta.md` |
| latência ao vivo (RTSP, mesmo transporte do WebRTC) | **1,568 s** (2 amostras) | `ground/EVIDENCIA-latencia-ponta-a-ponta.md` |
| latência HLS (pull por segmento) | 2,596 a 3,087 s | idem |

Medição de latência: `python bench/medir-latencia.py <url> --n 300` carimba a chegada
de cada quadro e salva o quadro pedido em imagem; o relógio queimado no quadro é lido
nela e a conta fecha com `--calcular ... --postar` (grava no banco do sistema).

## Regras do projeto
1. Nenhum segredo no repositório — credencial só por variável de ambiente/cofre.
2. Toda medição grava valor, fonte, data, hardware/versão e comando.
3. Acesso a câmera só por dentro da VPN; porta RTSP nunca publicada na internet.
4. Todo socket do lado terra escuta em `127.0.0.1` (o servidor não expõe porta de vídeo).
