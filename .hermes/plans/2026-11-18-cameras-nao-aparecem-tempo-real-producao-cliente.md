# As câmeras não aparecem em "Tempo real", "Produção" e na tela do cliente — plano de correção

**Data:** 2026-11-18 · **Dono:** Alexandre · **Status:** aprovado e IMPLEMENTADO (0.6.8) — provas verdes; faltando build/release/runbook

## Provas da implementação (18/11/2026, medidas)

| prova | resultado |
|---|---|
| `tests/test-anuncio-do-cadastro.py` | **15/15 verde** (4 casos: sem token = falha visível; com token = chega ao lado terra e sobe sozinho no boot; **esta máquina É o lado terra = desnecessário, sem anunciar para si**) |
| `tests/test-fluxo-sem-cadastro-na-tela.py` (novo) | **11/11 verde** (fluxo vivo sem ingestão entra no "Tempo real" e na "Produção" marcado; totais não quebram; fluxo com cadastro não duplica) |
| `tests/test-ponte-do-lado-terra.py` | **8/8 verde** |
| `tests/test_captura_no_admin.py` / `test-config-endereco` / `test_captura_liberada_no_app` / `test-app-unico-por-papel` | verdes |
| `tests/e2e-tela-limpa-do-admin.py` / `e2e-operacao-cancela.py` | verdes |
| `tests/e2e-envios.py` | em apuração (rodada anterior: 72 ok / 0 falhas) |
| VPS `187.127.60.250:8085` (lado terra, 0.6.8) | `saude=200 admin=200 tempo-real=200 producao=200 publicacao=200`; `/api/tempo-real` lista `vivo-cam1-11-18` e `vivo-cam2-11-18` como `sem_cadastro: true`; `/api/producao` volta a ter cards |

## Correção de causa (o que era, de fato)

- **Ambiente não chegava ao Python:** o instalador grava `ground/ambiente.json` e o Python lia só a raiz →
  servidor do PC de captura subia **sem** `LECSOR_TOKEN_INGESTAO`/`LECSOR_EMBARCACAO` → anúncio do cadastro
  não saía, e em silêncio. Agora `carregar_ambiente()` lê as duas posições e o **build falha** se o pacote do
  PC de captura nascer sem ambiente.
- **Falha visível, não silenciosa:** `/api/saude` traz `anuncio{...}`; `/api/publicacao` (GET/POST) mostra por
  câmera publicado/não + motivo; Admin > Câmeras tem a caixa "No lado terra".
- **Telas não ficam vazias:** fluxo vivo sem linha de ingestão entra no "Tempo real" e na "Produção" marcado
  ⚠ sem cadastro (antes: `producao: []` com 3 fluxos no ar).
- **Ninguém encaminha para si mesmo:** `eh_esta_maquina` passou a olhar **IP e porta** (o `/admin/` do lado
  terra dava 502); no próprio lado terra o anúncio se declara desnecessário em vez de erro falso.


## O que o dono relatou

"Em enviar vídeo cadastrei as câmeras com seleção de qualidade e tudo mais, está no ar, correto. Porém, elas
não aparecem na tela 'Tempo real', 'Produção' e na tela de transmissão ao vivo do cliente na web."

## Causa medida (18/11/2026, nos dois lados)

| verificação | resultado |
|---|---|
| lado terra `/api/cameras` | 12 câmeras; **3 com `no_ar=true` e todas "sem cadastro"**: `fluxo:comp-1`, `fluxo:vivo-cam1-11-18`, `fluxo:vivo-cam2-11-18` |
| lado terra `/api/producao` | 200, **`producao: []`, 0 cards** |
| lado terra `/api/envios` e `/api/ingestoes` | **1** ingestão (`Webcam da bancada (prova)`, `erro`, de 17/11) |
| rotas de "Tempo real"/"Produção"/cliente | `/api/tempo-real`, `/api/producao`, `/api/cameras` **não** estão em `ROTAS_CAPTURA` → com captura local são **encaminhadas ao lado terra** |
| lado terra, `ground/envios/log/repasse-*.log` | `cam-01`…`cam-04`, `vivo-cam-01/02`, `vivo-webcam-da-bancada-prova`: **"sem lado terra/token de ingestao — cadastro desta camera nao foi publicado"** (18/11 19:04–19:05 UTC, de hora em hora) |
| servidor local desta máquina (`/api/envios`) | 8 ingestoes, todas `parado`/`erro`, nenhuma `no_ar` |
| `desktop/ambiente.json` (fora do git) | traz `LECSOR_TOKEN_INGESTAO`, `LECSOR_EMBARCACAO=bancada`, `LECSOR_LADO_TERRA_API` |

**Leitura:** o vídeo chega ao lado terra (os fluxos aparecem **no ar**), mas o **cadastro da câmera não é
publicado** — quem lista câmera (Tempo real, Produção e a tela do cliente) lista por cadastro, então mostra
nada. O caminho do cadastro é `repasse.publicar_cadastro()` → `POST /api/cameras/anuncio` com
`Authorization: Bearer $LECSOR_TOKEN_INGESTAO`; sem **token**, **lado terra** ou **embarcação** no ambiente do
processo que publica, ele falha **e hoje isso só aparece em arquivo de log** (`repasse-<fluxo>.log`) — não há
nada na tela, nem no `/api/saude`.

**Suspeito nº 1 (a confirmar no PC de captura):** o pacote/serviço que publica está sem
`LECSOR_TOKEN_INGESTAO` (o `ambiente.json` só entra no pacote quando o build roda com `leva_ambiente=1`; sem
ele o build apenas **avisa**) e/ou sem `LECSOR_EMBARCACAO`. A 0.6.7 passou só `LECSOR_LADO_TERRA_API` via
`desktop/servidor.js`; token e embarcação continuam vindo exclusivamente do `ambiente.json`.

## Como corrigir

### Fase 1 — o anúncio do cadastro passa a ser garantido e visível (P0)

- **P0-1 — medir no PC de captura (dono, 1 comando).** Pedir o fim de
  `%LOCALAPPDATA%\Programs\LECSOR\resources\servidor\ground\envios\log\repasse-*.log` (ou o resultado da
  checagem nova do P0-2). É o que confirma token/embarcação ausentes; sem isso o resto é palpite.
- **P0-2 — estado do anúncio exposto.** `/api/saude` (e uma caixa na tela do admin) mostra, sem segredo:
  `anuncio: { token: sim/não, lado_terra: endereço, embarcacao: valor, ultimo_envio, ultimo_erro }`. Hoje
  isso só existe em log de arquivo.
- **P0-3 — o ambiente do anúncio é montado pelo próprio app.** `desktop/servidor.js` passa **também**
  `LECSOR_TOKEN_INGESTAO`, `LECSOR_EMBARCACAO` e `LECSOR_LADO_TERRA_API` aos processos que publicam; se o
  `ambiente.json` faltar, o admin mostra o motivo na tela (não só no log) e o pacote **falha** no build em vez
  de avisar.
- **P0-4 — publicar em todos os caminhos, com retry.** O cadastro é publicado no cadastro da câmera, ao
  ligar/desligar a câmera, ao entrar "no ar" e no botão "Publicar câmeras no lado terra"; quando falhar, o
  motivo fica guardado por câmera e um reenvio periódico (enquanto o servidor estiver de pé) insiste até o
  lado terra confirmar — nada de publicar uma vez e esquecer.
- **P0-5 — a tela mostra o resultado por câmera.** Coluna "no lado terra: publicado / não (motivo)" na lista
  de câmeras e na tela de envios, com botão "publicar agora".

### Fase 2 — as telas passam a ver o que está no ar (P1)

- **P1-1 — "no ar, sem cadastro" deixa de ser invisível.** O lado terra casa `fluxo:<nome>` com a câmera
  anunciada; o que estiver no ar aparece na tela do cliente e no Tempo real (hoje sai da tela por não ter
  cadastro). *(Os 3 fluxos de hoje: `comp-1`, `vivo-cam1-11-18`, `vivo-cam2-11-18`.)*
- **P1-2 — "Produção" conta o que está no ar.** `/api/producao` passa a contar os fluxos anunciados/enviados
  (hoje devolve `[]` com 3 fluxos no ar).
- **P1-3 — "Tempo real" lista por câmera anunciada**, com "no ar / fora do ar" por câmera, em vez de só o que
  o lado terra conseguiu medir.

### Fase 3 — prova e regressão (P2)

- **P2-1 — `tests/test-anuncio-do-cadastro.py` (novo).** Lado terra falso + servidor local de verdade: sem
  token, o anúncio **falha** e o motivo aparece em `/api/saude`; com token, a câmera entra na lista do lado
  terra no cadastro, ao ligar a câmera e ao "no ar".
- **P2-2 — E2E do caminho inteiro.** Cadastrar câmera → ligar → exigir que a tela do cliente (e o Tempo real)
  liste a câmera; falha se depender de ação manual no meio.
- **P2-3 — o pacote não sai sem o ambiente.** `tests/test-instalador-plug-and-play.py` passa a **exigir**
  `ambiente.json` com token e embarcação (hoje o build só avisa).
- **P2-4 — instalação em 1 comando.** `INSTALAR-PC-DE-CAPTURA.md` ganha a checagem ("o anúncio está de pé?")
  e a linha de log certa para olhar quando a câmera não aparecer.

### Fase 4 — limpeza e fecho (P2)

- **P2-5 — varrer o lado terra.** Remover/realinhar os cadastros órfãos (`fluxo:*` sem câmera) e a ingestão
  velha de 17/11, depois recolocar as câmeras do dono e conferir Tempo real, Produção e a tela do cliente.
- **P2-6 — publicar** como **0.6.8** (bump, build, release, `ground/` na VPS) + runbook no vault.

## Fora de escopo (decidido nesta rodada)

- **Levar o ao vivo para o Supabase:** fica onde está. O cadastro/base do produto já está no Supabase
  (`gscfcobpejxhtyzwfrjp`, `disable_signup`), mas o ao vivo depende de processos contínuos — `mediamtx`
  (portas `8888/8889/8892`), um `ffmpeg` por fluxo e `ground/api.py` como serviço — que Postgres, Storage e
  Edge Functions do Supabase não hospedam.

## O que NÃO sei ainda

- Se no PC de captura falta token, embarcação ou os dois (só o log de lá responde — P0-1).
- Qual dos caminhos de hoje deixou de publicar (cadastro, ligar câmera, "no ar" ou o botão manual): o log de
  lá diz o nome do fluxo e a hora.
