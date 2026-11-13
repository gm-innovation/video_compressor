# Instalador plug & play do PC de captura (servidor dentro do pacote)

**Status:** aprovado e executado em 2026-11-13 (versão **0.2.0**; fases 1, 2, 3 e a prova de
instalação limpa da fase 5 concluídas; o botão "Testar câmeras" e o aviso de `base` trocado da fase 4
ficam para a próxima rodada — P1)
**Pedido (verbatim):** "quando formos instalar isso no cliente, ele precisa instalar por completo, precisa ser plug & play,
não quero ter que ficar fazendo um monte de configurações manuais, isso que você falou já deve ir configurado no instalador!"
**Base:** `main` = `6b23b9f` · release publicada: v0.1.4

---

## 1. Estado de hoje (conferido, não é suposição)

| o que | hoje |
|---|---|
| conteúdo instalado | só o app: `chrome_*.pak`, `*.dll`, `LECSOR <face>.exe`, `resources/app.asar`, `resources/elevate.exe`, `resources/ffmpeg/{ffmpeg.exe,ffprobe.exe}` (instalação silenciosa da 0.1.4 feita na bancada) |
| `%APPDATA%\LECSOR Pipeline de Video\config.json` de fábrica | `base = http://187.127.60.250:8085`, `servidorLocal = {ligado: false, repo: "", portaApi: 8765}` |
| servidor local | `desktop/servidor.js:44-68` exige `servidorLocal.repo` existente e sobe `mediamtx.exe`, `ground/api.py` e `analytics/agente.py` por caminho relativo à pasta do repositório |
| Python | `pythonDe()` usa `repo/.venv/Scripts/python.exe` se existir, senão o `python` do PATH |
| erro | `servidor.subir()` devolve `{"erro": "informe a pasta do repositorio..."}` e `main.js:117` **descarta** o retorno (silêncio, estado segue "parado") |
| código do servidor | `ground/`: só biblioteca padrão no caminho da API (`http.server`, `subprocess`, `sqlite3`) — `markdown` e `supabase_auth` aparecem apenas em utilitários (`gerar-relatorio-cenario2.py`, `migrar-login-supabase.py`) |
| mediamtx | `tools/mediamtx/mediamtx.exe` (fora do Git, baixado por `tools/baixar-mediamtx.sh`) |

Conclusão: o que falta para plug & play é **levar o servidor no pacote** (código + mediamtx + Python) e **nascer configurado**.

---

## 2. Fases

### Fase 1 — P0 — O pacote leva o servidor dentro
1. `extraResources` passa a incluir **`servidor/`** com: `ground/`, `analytics/`, `board/`, `admin/`, `app/`, `tools/mediamtx/` (`mediamtx.exe` + `mediamtx.yml`).
2. Python portátil embutido (`python-3.12-embed-amd64.zip`, ~11 MB) em `servidor/python/`; `pythonDe()` passa a preferir, nesta ordem: `LECSOR_PYTHON` (variável do app) → `repo/.venv/...` (bancada) → `servidor/python/python.exe` → `python` do PATH.
3. `desktop/servidor.js` resolve o repositório nesta ordem: `config.servidorLocal.repo` (se existir) → **pasta embutida** `process.resourcesPath/servidor` → erro com mensagem.
4. Teste de build: sem `tools/mediamtx/mediamtx.exe` ou sem `ground/api.py`, o build **PARA** (mesma regra do ffmpeg: nunca instalador cego).

### Fase 2 — P0 — Nasce configurado (dois papéis, sem JSON na mão)
1. Dois artefatos com papéis explícitos no nome: **`LECSOR-Captura-x.y.z-x64.exe`** (PC de captura) e **`LECSOR-Terra-x.y.z-x64.exe`** (lado terra / VPS / servidor do cliente).
2. Config de fábrica do **Captura**: `base = http://127.0.0.1:8765`, `servidorLocal = {ligado: true, repo: (embutido), portaApi: 8765}`, `destinoSrt = <lado terra>`.
3. Config de fábrica do **Terra**: `base = <endereço do lado terra>`, `servidorLocal = {ligado: false}`, sem repasse.
4. Regra de atualização: **nunca** sobrescrever config existente do usuário; só semear na primeira execução (arquivo ausente). Mostrar na tela de estado qual `base` e qual `repo` estão em uso.
5. Depois do primeiro start, o app grava o config resolvido — o JSON deixa de ser etapa de instalação.

### Fase 3 — P0 — Sobe sozinho e falha em voz alta
1. `Servidor local` sobe automaticamente quando `ligado = true` (no boot: `main.js:141`) e o instalador de captura já deixa `ligado = true`.
2. Menu passa a **exibir** o retorno de `subir()` (hoje descartado em `main.js:117`): falha aparece com o motivo (pasta ausente, mediamtx ausente, porta ocupada, python ausente).
3. Log de abertura do app em `desktop-logs/` (já existe) + linha "servidor local: no ar/parado" no diálogo de estado.
4. (P1 dentro da fase) reinício automático do servidor local se um dos três processos cair, com registro no log.

### Fase 4 — P1 — Primeira execução sem nenhum ajuste
1. Se `repo`/`base` faltarem, o app resolve para a pasta embutida e para `127.0.0.1:8765` sozinho, e grava.
2. Tela de estado com botão **Testar câmeras**: chama `GET /api/dispositivos` na máquina local e mostra a lista (ou o motivo), sem depender de quem serve a página.
3. Aviso quando o navegador do cliente estiver olhando um `base` que não é esta máquina (situação que hoje confunde: a lista vem do outro lado).

### Fase 5 — P1/P2 — Prova de instalação limpa e desinstalação
1. (P1) Máquina sem Python, sem ffmpeg, sem repositório: instalar o `LECSOR-Captura`, abrir, ver `servidor local no ar (3 processos)`, as duas câmeras USB na lista, capturar e repassar para o lado terra; registrar comandos e saída.
2. (P1) Reinstalar por cima: config do usuário preservado, servidor volta no boot.
3. (P2) Desinstalação remove app, servidor embutido, atalhos e processos; deixa os vídeos/gravações do cliente.

---

## 3. Critério de aceite (o que será provado, não afirmado)
- Instalação limpa em máquina sem Python/ffmpeg/repo: zero edição de arquivo; câmeras listadas; captura e repasse no ar.
- `tests/` cobrindo: pacote contém `servidor/` (código + mediamtx + python), `pythonDe()` prefere o embutido, `subir()` sem `repo` usa a pasta embutida, erro do `subir()` chega à tela.
- Release publicada com os dois `.exe` e o passo a passo enxuto (1 página) para o técnico.

## 4. Riscos conhecidos
- Tamanho do instalador: +~40 MB (mediamtx ~20 MB, python embed ~11 MB, código ~1 MB) — hoje já são 131,5 MB por causa do ffmpeg.
- Antivírus/SmartScreen: binário portátil dentro do instalador pode gerar alerta; mitigação: assinar o instalador (certificado) — fora do escopo desta rodada.
- Dois instaladores × dois papéis: exige disciplina de nome/versão na página de Releases.

---

## 5. O que foi executado (2026-11-13) e o que ficou de fora

| fase | situação | evidência |
|---|---|---|
| 1 — P0 pacote leva o servidor | **concluída** | instalação limpa do `LECSOR-Captura-0.2.0-x64.exe` (171.461.179 B) tem `resources/servidor/{ground,admin,app,db,board,analytics,tools/mediamtx/python}` + `resources/ffmpeg/`; `servidor: 77 MB` (mediamtx 57.336.320 B, python 103.704 B) |
| 2 — P0 nasce configurado | **concluída** | 1ª abertura gravou sozinha `%APPDATA%\LECSOR Captura\config.json`: `base=http://127.0.0.1:8765`, `destinoSrt=187.127.60.250:8890`, `servidorLocal={ligado:true, repo:<resources/servidor>, portaApi:8765}`, `abrirComWindows:true`, `papel:captura` |
| 3 — P0 sobe sozinho e falha em voz alta | **concluída** | no 1º start o próprio app subiu mediamtx (SRT 127.0.0.1:8890, RTSP 8554, API 9997) e a api (`python.exe` **do pacote**), `api-erro.log` 0 byte; `curl /api/dispositivos` = `{"video":["ACER HD User Facing"],"maquina":"Engenharia01","ffmpeg":{"origem":"embutido no app"}}` — o item que falhava na 0.1.4; reinício automático com limite de 3 tentativas |
| 4 — P1 primeira execução sem ajuste | **parcial** | semear/`repoDe`/`pythonDe` prontos; **falta** o botão "Testar câmeras" na tela de estado e o aviso quando o `base` não é esta máquina |
| 5 — P1/P2 instalação limpa e desinstalação | **parcial** | instalação limpa provada (abaixo); reinstalar por cima e desinstalação (P2) pendentes |

### Defeitos achados na instalação limpa (corrigidos nesta rodada)
1. **Config de outro papel vencia o papel do build** — o instalador de captura abria apontado para o
   lado terra: a 0.1.x/e outros papéis gravam no **mesmo** `%APPDATA%\LECSOR Pipeline de Video\config.json`.
   Correção: `productName` próprio em cada pacote (`--config.extraMetadata.productName`) + o `papel`
   gravado no build vence config herdado (e config antigo sem `papel`).
2. **Build podia falhar em silêncio** — `electron-builder … | tail -4` mascarava o erro (o instalador
   de captura ficou velho sem ninguém ver). Correção: `set -e -o pipefail`.
3. **`analytics/detector.py` e `rastreador.py` não iam no pacote** e o agente subia em **loop de
   reinício** (`ModuleNotFoundError`). Correção: módulos no pacote + o agente só sobe se o Python tiver
   `numpy`/`onnxruntime` (o portátil não tem) e o motivo vai para o log; reinício com limite.
4. **Banco de instalação limpa sem as tabelas da ingestão** — `inicializar()` aplicava só
   `schema.sql`/`schema-fase4`/`schema-fase5`. Correção: aplica **todos** os `db/schema*.sql`
   (`schema.sql` primeiro). Medido em banco vazio: cria 21 tabelas, com `ingestoes` e `ingestoes_amostras`.
5. **Banco dentro da pasta de instalação** (apagado a cada versão nova). Correção: fonte única
   `ground/ferramentas.py:caminho_banco()` + `LECSOR_BANCO` (o app aponta para
   `%APPDATA%\<app>\pipeline.db`; a bancada segue no `db/` do repositório).

### Comandos da prova (bancada, instalação limpa)
```bash
rm -rf "$LOCALAPPDATA/Programs/LECSOR Captura" "$APPDATA/LECSOR Captura"
./desktop/dist/captura/LECSOR-Captura-0.2.0-x64.exe /S          # instalação silenciosa
"$LOCALAPPDATA/Programs/LECSOR Captura/LECSOR Captura.exe"      # 1ª abertura (semeia e sobe)
cat "$APPDATA/LECSOR Captura/config.json"
curl -s http://127.0.0.1:8765/api/dispositivos
curl -s http://127.0.0.1:9997/v3/paths/list
```
`tests/test-instalador-plug-and-play.py` (9 seções) e `tests/suite.py`: **OK**.
