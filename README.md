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

## PC de captura (câmeras ligadas direto no computador)
Passo a passo em `INSTALAR-PC-DE-CAPTURA.md`: as câmeras entram pela tela **Enviar vídeo**, o
sistema comprime na máquina e o vídeo comprimido sobe para o lado terra (`destinoSrt`).

## Instaladores prontos (Windows x64) — PLUG & PLAY desde a 0.2.0
Na página de releases: https://github.com/gm-innovation/video_compressor/releases
- `LECSOR-Captura-0.2.0-x64.exe` — **PC de captura**: nasce apontado para `127.0.0.1:8765`, com o
  servidor local ligado (sobe sozinho no boot) e repasse para o lado terra já configurado
- `LECSOR-Terra-0.2.0-x64.exe` — **lado terra**: apontado para o servidor (VPS ou local do cliente)
- `LECSOR-Cliente-0.2.0-x64.exe` / `LECSOR-Admin-0.2.0-x64.exe` — telas do cliente e admin/operação

A partir da **0.2.0** cada instalador leva **o pacote inteiro** dentro de `resources\`:
`ffmpeg/` (ffmpeg+ffprobe), `servidor/ground`, `servidor/admin`, `servidor/app`, `servidor/db`,
`servidor/board`, `servidor/analytics`, `servidor/tools/mediamtx/mediamtx.exe` e **Python portátil**
(`servidor/python/python.exe`). O servidor local sobe **dois** processos (`mediamtx` + `api`); a
análise local só entra se o Python tiver `numpy`/`onnxruntime` (o portátil não tem) e o app registra
no log a decisão. O banco local fica em `%APPDATA%\<nome>\pipeline.db` e o caminho é resolvido num
lugar só (`ground/ferramentas.py:caminho_banco()`, via `LECSOR_BANCO`); instalação limpa aplica todos
os `db/schema*.sql` (inclusive `schema-ingestao.sql`). Na máquina do cliente **não** se instala Python, não se copia
repositório e não se edita JSON: o papel de build (`desktop/papeis.json`) traz o `base`,
`destinoSrt` e `servidorLocal` de fábrica. Se o servidor local não subir, o app **diz o que falta**
em caixa de erro (antes a falha era silenciosa).

Quem builda roda `desktop/baixar-ffmpeg.sh` (download pelo Python, com SHA-256 conferido) e
`desktop/baixar-servidor.sh` (Python embeddable + mediamtx), que baixam para `tools/` — fora do git.

Cada instalador tem `productName` próprio (logo, `%APPDATA%\<nome do app>\config.json` próprio), e o
`papel` gravado no build vence um `config.json` herdado de outro papel ou das versões antigas.

Os `.exe` são construídos por `desktop/construir-instaladores.sh` e **não** entram no git
(`desktop/dist/` está no `.gitignore`): o pacote de download é a página de releases.

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
