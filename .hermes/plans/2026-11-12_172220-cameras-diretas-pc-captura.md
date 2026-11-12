# Câmeras ligadas direto no PC de captura → VPS (ou PC da rede)

**Status:** aprovado em 12/11/2026 · Fases 1 a 4 executadas · Fase 5 aguardando as câmeras no PC de captura

**Dono do pedido:** Alexandre — "nós recebemos as imagens, o sistema comprime e envia para a VPS ou outro computador na rede, esse computador descomprime os vídeos e roda. É nessa página de 'Enviar vídeo' que insiro as câmeras conectadas ao computador (é outro computador)."

**Objetivo:** no **computador de captura** (as câmeras ligadas nele por USB), a tela **Enviar vídeo** lista as câmeras daquele computador, captura e **comprime local**, e o vídeo comprimido chega à **VPS** (ou a outro computador da rede), que descomprime e mostra — mantendo a arquitetura fixada: credencial e endereço de câmera nunca no navegador.

---

## 1. Evidência (o que está no código hoje — verificado)

| fato | como foi verificado |
|---|---|
| A lista "Webcam / dispositivo" é lida **da máquina que roda a API** | `ground/api.py:678-685` → `ground/ingestao.py:listar_dispositivos()` roda o `ffmpeg -list_devices` **local**; executado nesta bancada agora: só `ACER HD User Facing` |
| O app apontado para a VPS listaria os dispositivos **da VPS** (servidor sem câmera) | mesma cadeia acima: a enumeração acontece onde a API roda |
| A captura ao vivo publica em SRT **local** | `ground/ingestao.py:568-570` (`srt_host="127.0.0.1"`, `srt_port=8890`); `ground/api.py:895-899` chama `ing_ao_vivo(...)` sem passar destino |
| O mediamtx local **não repassa** nada | `ground/mediamtx.yml:22-23` (`srtAddress: 127.0.0.1:8890`) e nenhuma regra `runOnReady`/relay no arquivo (grep vazio). Versão do binário: v1.21.3 (`mediamtx.exe --version`) |
| O único caminho que hoje mira a VPS é single-câmera e travado | `ground/enviar_para_vps.py:24-36` (usa `DISPOSITIVO_PADRAO` e trava de PID); `ground/ingestao.py:403-431` (`ligar_camera` reusa o último envio e cai em `187.127.60.250` por padrão) |
| O agente de bordo **não aceita câmera física** | `board/agent.py:29-30` fixa `-f lavfi -i <fonte>` (só fonte sintética) |
| O app sabe subir o lado terra **na própria máquina** | `desktop/servidor.js:9-28`: exige `servidorLocal.repo` com `tools/mediamtx/mediamtx.exe`, `ground/api.py` e `python` no PATH |

## 2. Como o sistema funciona hoje (onde cada coisa roda)

- **PC de captura (hoje):** com a API rodando nele, a tela *Enviar vídeo* → "webcam do notebook (ao vivo)" → escolhe o dispositivo → captura e comprime (`-f dshow` + libx264, `ground/ingestao.py:520-527`) → publica em `srt://127.0.0.1:8890`.
- **VPS (lado terra):** mediamtx recebe SRT e republica WebRTC/HLS/RTSP; a API serve `/app` e `/admin`.
- **Falta a ligação entre os dois:** o fluxo comprimido no PC de captura **não sai** para a VPS (item 4 da tabela acima).

## 3. Decisões que são suas (marcar antes de eu implementar)

- **D1 — Como o vídeo comprimido sai do PC de captura:** repasse no mediamtx local com `-c copy` (não reencoda: a compressão já foi feita no PC) **ou** captura publicando direto no destino. *Recomendo o repasse com `-c copy`* (mantém o custo no PC de captura e o destino só recebe bytes já comprimidos).
- **D2 — Destino na tela:** o destino (VPS **ou** IP de outro computador da rede) deve ser um campo na tela *Enviar vídeo*, ou fica na configuração da máquina (`config.json`/`.env` do PC de captura)? *Recomendo configuração da máquina* (um PC de captura tem um destino fixo na operação).

---

## 4. Fases

### Fase 1 — P0 · Repasse do PC de captura para a VPS (com `-c copy`)
- **O que muda:** `ground/mediamtx.yml` ganha `runOnReady` por path que sobe o fluxo recebido para `srt://187.127.60.250:8890?mode=caller&streamid=publish:$MTX_PATH` com `-c copy`; script `ground/repasse.sh` (alvo por variável `LECSOR_DESTINO_SRT`) para testar sem depender do YAML; `tests/test-repasse-mediamtx.py`.
- **Critério de aceite (comando):** publicar na bancada e, na VPS, `curl -s http://187.127.60.250:9997/v3/paths/list` mostrando o path com `ready: true`; o app apontado para a VPS mostrando a câmera "no ar".
- **Custo:** 1 sessão. **Dependência:** D1.
- **P1 (na mesma fase):** log do repasse em `desktop-logs/` para provar quando cai e volta.

### Fase 2 — P0 · Destino configurável + instalação limpa no outro computador
- **O que muda:** `LECSOR_DESTINO_SRT` (host:porta) lida em `ground/ingestao.py`/`ground/api.py` como padrão do `ao_vivo` quando o chamador é o PC de captura; `desktop/config.json` + `desktop/servidor.js` repassando a variável ao subir o servidor local; `INSTALAR-PC-DE-CAPTURA.md` (passo a passo em linguagem de leigo: instalar o `.exe` da release, clonar/baixar o repo, ter Python, menu *Servidor local* → pasta do repo, escolher a câmera).
- **Critério de aceite (comando):** em outra máquina, `python ground/api.py 8765` + `curl -s localhost:8765/api/dispositivos` listando as câmeras USB dela; `curl -s http://187.127.60.250:9997/v3/paths/list` na VPS mostrando o fluxo vindo dela.
- **Custo:** 1 sessão. **Dependência:** Fase 1 e D2.

### Fase 3 — P1 · Agente de bordo com N câmeras físicas (`dshow`)
- **O que muda:** `board/agent.py` aceita `entrada: "camera"` no perfil (usa `-f dshow -i video=<dispositivo>` de `board/perfis/*.json`), um processo por câmera, com a volta automática já valida em `ground/ingestao.py` (`garantir_schema`, supervisão); `board/perfis/duas-cameras.json` de exemplo; `tests/test-agente-dshow.py`.
- **Critério de aceite:** perfil com 2 câmeras → 2 processos `ffmpeg` com `dshow`, 2 fluxos no mediamtx; derrubar uma câmera (desconectar) e ela voltar sozinha em ≤30 s sem tocar em nada.
- **Custo:** 2 sessões. **Dependência:** as câmeras no PC (Fase 5).

### Fase 4 — P1 · Telas mostrando o PC de captura e o destino
- **O que muda:** `admin/admin.js` — em *Enviar vídeo* a fonte viva mostra o dispositivo e o destino em uso; em *Câmeras* a coluna "Como o agente pega" mostra `dshow:<dispositivo>` e o destino; `admin/admin.js`/`ground/api.py` sem exibir IP/credencial no `/api/cameras` (regra vigente mantida).
- **Critério de aceite:** `node harness-cameras.mjs` (harness jsdom já existente) passa e o admin mostra a origem e o destino de cada câmera.
- **Custo:** 1 sessão. **Dependência:** Fases 2 e 3.

### Fase 5 — P2 · Teste real com duas câmeras e medição registrada
- **O que muda:** nada de código de produto; `ground/EVIDENCIA-dercamento-pc-captura.md` com o que foi medido.
- **Critério de aceite:** duas câmeras ligadas no outro computador aparecendo "no ar" na VPS, com bitrate de saída, fps (30), latência ponta a ponta e SSIM registrados por comando, não por relato.
- **Dependência:** câmeras físicas + o outro computador.

## 5. Riscos e limites (declarados)

- A latência medida até hoje (≈2 s) foi em link 4G de bancada; **o enlace Starlink Maritime real não está medido** e a câmera física entra com latência própria de captura, que ainda não medi.
- Nenhum teste com **N canais simultâneos** reais (só 2 sintéticos).
- Se o PC de captura estiver atrás de NAT sem porta publicada, o repasse precisa sair dele (push) — é o que esta proposta faz; **o caminho inverso (terra puxar do bordo) não é suportado**.
- Áudio das câmeras não entra (o envio é `-an`): fica fora até você pedir.
- O `runOnReady` do mediamtx v1.21.3 será validado na Fase 1 — se o binário não suportar, o repasse vira script/serviço systemd no PC de captura (mesma entrega, outro veículo).

## 6. Executado (evidência de 12/11/2026)

| fase | entrega | evidência verificada |
|---|---|---|
| 1 P0 | `ground/repasse.py` + `runOnAvailable` no `ground/mediamtx.yml` (chave nova do mediamtx v1.21.3; `runOnReady` está descontinuado) | `tests/test-repasse-mediamtx.py` OK (2 instâncias isoladas; sem destino nada sobe; com destino chega sem reencodar: H264 640x360). Ponta a ponta real bancada→VPS: o fluxo `teste-repasse-vps` apareceu **na VPS** `ready`, H264 1280x720, com `-c copy` |
| 2 P0 | `destinoSrt` no `desktop/config.json`, `amb()`/`pythonDe()` no `desktop/servidor.js`, `INSTALAR-PC-DE-CAPTURA.md`, **instaladores republicados na release** (0.1.0 não conhecia o `destinoSrt`: o PC de captura instalado por ele não repassaria nada) | `node -e` sobre `servidor.js`: sem destino a variável é **removida** do ambiente dos filhos; com destino vira `LECSOR_DESTINO_SRT=187.127.60.250:8890`; `pythonDe` acha o `.venv` do repo |
| 3 P1 | `board/agent.py` com `"entrada": "camera"` (dshow) + `board/perfis/duas-cameras.json` | `tests/test-agente-dshow.py` OK — inclusive **com a webcam real** (`ACER HD User Facing`) publicando no mediamtx |
| 4 P1 | `/api/envios/destino` (só operação; **sem** a exceção de chamada local, para o cliente logado na mesma máquina também não receber endereço interno) + linha do destino na tela *Enviar vídeo* | API: admin 200, operação 200, cliente **403**, sem login **403**; harness jsdom `harness-destino.mjs` OK nos dois casos, `harness-cameras.mjs` sem regressão |
| 2 P0 (extra) | instaladores **0.1.1** publicados na release do repositório | `bash desktop/construir-instaladores.sh` OK; release `v0.1.1` com `LECSOR-Cliente-0.1.1-x64.exe` (81.699.581 B) e `LECSOR-Admin-0.1.1-x64.exe` (81.699.542 B) confirmados por leitura da API do GitHub; pacote conferido por dentro: `app.asar` contém `destinoSrt` (7 ocorrências) e `LECSOR_DESTINO_SRT` (2) |
| 5 P2 | medição com as duas câmeras reais | **pendente**: depende das câmeras no PC de captura |

## 7. Ordem de execução

Fase 1 → Fase 2 → Fase 3 → Fase 4 → Fase 5 (Fase 3 pode correr em paralelo com 1 e 2, porque mexe em arquivos diferentes).
