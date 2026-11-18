# Plano — câmeras não listam no admin do PC de captura (medido 18/11/2026)

**Status:** **aprovado pelo dono em 18/11/2026** — escolheu a "Opção A" e mandou fazer ("então faça o que você
precisa fazer"). Implementado e provado nesta data; ver "Implementado (medido)" no fim.

**Queixa:** "continua não listando as câmeras no app admin no computador de captura".

## Causa medida (não é o servidor, não é a ponte, não é a câmera)

Medições de hoje, nesta máquina (`Engenharia01`, o PC de captura):

| verificação | resultado |
|---|---|
| `curl http://127.0.0.1:8765/api/dispositivos` | **200** — `ACER HD User Facing` (câmera listada; servidor local no ar) |
| `curl -H "Origin: http://187.127.60.250:8085" ...` | 200 com `Access-Control-Allow-Origin` correto |
| app 0.6.6 (`--verificar`) | `enderecoCaptura=http://127.0.0.1:8765`, `captura_servidor=ok`, janela `ponte=object`, `captura=http://127.0.0.1:8765` |
| **página do lado terra → `fetch('http://127.0.0.1:8765/api/dispositivos')`** | **`FALHOU: Failed to fetch`** |
| **página servida pelo servidor local → mesmo fetch** | **`200` com `ACER HD User Facing`** |
| `fetch('http://127.0.0.1:8791/')` de sonda própria, com e sem `Access-Control-Allow-Private-Network` | `FALHOU: Failed to fetch` nos dois |

**Conclusão:** a tela do admin é carregada do lado terra (`http://187.127.60.250:8085/...`). O Chromium do
app **bloqueia** pedidos de uma página em IP público para endereço de loopback (`127.0.0.1`) — *Private
Network Access*. A ponte `window.lecsorApp` está certa e o endereço da captura está certo; o pedido é barrado
**antes de sair do navegador**. O mesmo bloqueio derruba a compressão (`POST /api/ingestao/comprimir`) e o
vídeo do "No ar agora" quando a tela vem do lado terra. Por isso a câmera aparece no `curl` e nunca na tela.

Instalado no PC de captura: app **0.6.3** (asar de 18/11 12:16) — anterior a 0.6.4/0.6.5/0.6.6. Não é a causa
(o bloqueio vale para as três), mas precisa reinstalar para receber as correções.

## Como corrigir — **Opção A escolhida pelo dono (18/11/2026): a tela de captura passa a ser servida pelo servidor local**

Ideia: com a captura ligada nesta máquina, **todas as telas do app passam a ser abertas na origem do servidor
local** (`http://127.0.0.1:8765/...`) e o servidor local **encaminha para o lado terra** tudo o que não é rota
de captura. Assim tela e rotas de captura ficam **na mesma origem** (loopback → loopback, medido funcionando:
`200` com `ACER HD User Facing`), e o bloqueio de rede privada do Chromium deixa de existir — sem desligar
`webSecurity` e sem depender do cabeçalho `Access-Control-Allow-Private-Network` (medido: não resolve).

### Fase 1 (P0) — encaminhador no servidor local

- `ground/api.py`: rota **catch-all** que encaminha para `config.base` (o lado terra) tudo o que **não** é rota
  de captura: mesmo método, cabeçalhos de sessão/cookie repassados, corpo repassado, resposta devolvida
  inteira (status, cabeçalhos, bytes) — inclusive páginas, `/fronts/*.css`, `/fronts/video.js`, `/app/app.js`,
  `/api/entrar`, `/api/cadastro`, `/api/cameras`, uploads e downloads.
- **Só** `127.0.0.1` (o servidor já nasce assim) e **só** para `config.base`: nada de encaminhar host arbitrário.
- Rotas de captura (`/api/dispositivos`, `/api/ingestao*`, `/api/compressoes`, `/api/envios`, `/api/medicoes`,
  `/api/trecho`, `/api/captura`, `/api/embarcacoes`, `/api/saude`) continuam sendo atendidas **localmente** —
  nenhuma delas pode ser encaminhada (senão a captura volta a depender do lado terra).
- Prova: `curl http://127.0.0.1:8765/api/saude` local; `curl http://127.0.0.1:8765/` devolve a página do lado
  terra; `curl http://127.0.0.1:8765/api/cameras` (rota do lado terra) devolve o mesmo JSON do lado terra.

### Fase 2 (P0) — as janelas do app abrem na origem local quando há captura

- `desktop/main.js`: quando `config.capturaLocal && config.servidorLocal.ligado`, as telas (`entrada`,
  `admin`, `cliente`) são abertas em `http://127.0.0.1:<portaApi>/...` em vez de `config.base`; sem captura
  local, tudo continua como hoje (direto no lado terra).
- A ponte `window.lecsorApp.enderecoDaCaptura()` deixa de ser necessária para a lista de câmeras (mesma
  origem), mas fica no lugar para não quebrar o que já existe.
- Prova: `LECSOR.exe --verificar` mostrando as janelas com `http://127.0.0.1:8765/...` e o `select` de câmeras
  preenchido (a sonda lê a página).

### Fase 3 (P1) — sessão e login no caminho novo

- O formulário de entrada, agora servido por `127.0.0.1:8765`, publica em `/api/entrar` → encaminhado ao lado
  terra → o cookie de sessão passa a ser da origem local e é repassado em cada encaminhamento.
- Conferir: entrar com um usuário do lado terra pela tela local, abrir `/admin` local, ver Painel/Usuários
  (dados do lado terra) **e** a lista de câmeras (dados locais) na mesma tela.
- CORS deixa de ser necessário para a captura (mesma origem); o bloco `_cors` permanece para o caso de alguém
  abrir a página pelo lado terra (endereço de loopback direto não funciona — isso fica documentado).

### Fase 4 (P1) — provas no PC de captura e nos testes

1. Sonda (a mesma que mediu a causa): página na origem local + `fetch('/api/dispositivos')` → **200 com a
   câmera**.
2. `LECSOR.exe --verificar`: janelas na origem local, `select` com `ACER HD User Facing`.
3. Compressão de bancada de ponta a ponta na tela local (`tests/e2e-envios.py`, hoje verde, continua verde).
4. `tests/e2e-tela-limpa-do-admin.py`, `tests/e2e-operacao-cancela.py`, `tests/test_captura_no_admin.py`,
   `tests/test_captura_liberada_no_app.py` e `tests/test-app-unico-por-papel.py` atualizados/verdes.

### Fase 5 (P2) — entrega

- Bump **0.6.7** (`desktop/package.json`, `tools/publicar-releases.py`, `README.md`), build, release, e
  **reinstalação no PC de captura** (hoje ele roda 0.6.3).
- Runbook no vault + linha no `index.md`.

## Riscos e o que não pode acontecer

- O encaminhador não pode virar uma porta aberta para o lado terra: escuta só em `127.0.0.1` e só fala com
  `config.base` — nenhum destino vindo do pedido.
- A trilha de auditoria continua no lado terra (o encaminhamento preserva o usuário da sessão); nada de
  auditoria local paralela.
- Streaming continua direto (`destinoSrt`/mediamtx), sem passar pelo encaminhador.


## Implementado (medido 18/11/2026)

- `ground/api.py`: `_base_do_lado_terra()` + `_encaminhar(metodo)`. `do_GET`/`do_POST` só seguem locais nas
  rotas de captura (e em `/api/saude`); todo o resto vai ao lado terra com método, cookies, corpo e status
  repassados, corpo em blocos (download não passa pela memória). `/api/eu` volta do lado terra com
  `local: true` (a captura é desta máquina — é o que libera os botões de câmera).
- `desktop/servidor.js`: passa `LECSOR_LADO_TERRA_API = config.base` ao servidor local.
- `desktop/main.js`: `baseLocalDaCaptura` (preenchida por `esperarServidorLocal()`) e `urlDe()` — com captura
  local, **todas** as telas abrem na origem do servidor local; se ele não responder, as telas voltam ao lado
  terra (nunca abrir em endereço que não atende).
- `tests/test-ponte-do-lado-terra.py` (novo): lado terra falso em porta própria + `api.py` de verdade →
  8/8 verde (`PONTE_DO_LADO_TERRA_OK`).

Provas:
- `curl http://127.0.0.1:8795/api/saude` → 200 local; `/` e `/admin/` → 200 com a página do lado terra;
  `/fronts/vms.css` → 200 text/css; `/api/cameras` → 401 (resposta do lado terra);
  `/api/dispositivos` → 200 com `ACER HD User Facing`.
- login pela ponte: `POST /api/entrar` → `{"ok": true, "papel": "admin"}`; `GET /api/eu` →
  `{"autenticado": true, ..., "local": true}`.
- sonda no Chromium do app com a página na origem local: `titulo=Admin do projeto e do sistema — LECSOR`,
  `fetch('/api/dispositivos')` → **200 com a câmera** (antes, da página do lado terra: `Failed to fetch`).
- app de verdade (`npx electron . --verificar`): janela → `http://127.0.0.1:8795/admin`, `captura_servidor=ok`.
- testes existentes: `test-config-endereco` OK, `test_captura_no_admin` 21 OK, `test_captura_liberada_no_app`
  OK, `test-app-unico-por-papel` OK, `e2e-tela-limpa-do-admin` OK, `e2e-operacao-cancela` OK.
