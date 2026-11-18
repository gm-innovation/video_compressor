# Tela limpa do admin + qualidade do vídeo ao vivo (18/11/2026)

Pedido do dono (18/11/2026, verbatim):

> 1. não vejo motivo pra "Transmissões pedidas pelos clientes" existir no admin, esse tipo de informação
>    é irrelevante pra mim, precisa estar apenas no canal do cliente
> 2. por que esses testes de vídeo estão na minha tela? isso não é necessário e ainda dá o aspecto de
>    bagunçado
> 3. não está reconhecendo câmeras na máquina e diferente dos testes de vídeo, não consigo escolher a
>    qualidade do vídeo, continua com a caixa de seleção antiga, sem a seleção de 1500 a 300 kbps

## O que foi medido antes de escrever este plano

- Os três assuntos estão na **mesma tela**: `admin/admin.js` → `telaEnvios()` (linhas 1015–1624), a tela
  "📥 Enviar vídeo" do menu (`admin/index.html:72`). Nada disso existe em outra tela do admin.
- **Bloco 1 (a tirar):** "Transmissões pedidas pelos clientes" — `#env-pedidos` (linhas 1021–1027,
  tabela em 1098–1117) + "Teto do produto" (1029–1055) + trilha de "Gravações" (1057–1065).
- **Bloco 2 (a tirar):** "Teste de vídeo (bancada): comprimir, medir e publicar" (1121–1122) com a
  lista de compressões (1461–1503) e "Qualidade por câmera (lista fechada)" — `#env-qualidade-camera`
  (1135–1176).
- **O canal do cliente já tem a função**: `app/app.js` tem *transmissão a pedido* (pedir a partir de
  771, lista em 861) — tirar do admin não tira a função de ninguém.
- **A câmera desta máquina É reconhecida pelo servidor local** — medido agora:
  `GET http://127.0.0.1:8765/api/dispositivos` → **200** com `ACER HD User Facing`
  (`pedido_de: "esta_maquina"`, ffmpeg **embutido no app**, `seletor: @device_pnp_...`).
- O que quebra a lista é o caminho até ele: `admin.js` manda as rotas de captura para o servidor local
  (`LECSOR_CAPTURA_BASE`, `urlDeCaptura()`, linha 20) e, se ele não estiver no ar naquele instante,
  `fetchCaptura()` **lança** `TypeError: Failed to fetch`; `preencherDispositivos()` (1384–1438) **não
  tem catch** — a caixa fica vazia **sem dizer o motivo** (é o "não está reconhecendo câmeras"). Foi
  visto na própria tela: a linha do destino mostrou *"não consegui falar com o servidor: Failed to fetch"*.
- É a **mesma classe** do defeito do login corrigido na 0.6.3: a janela resolvia o endereço **antes** de
  o servidor local responder. Na 0.6.2 as janelas abriam **antes** de `servidor.subir()` (a 0.6.3 já
  inverteu isso para a entrada; falta valer para a captura).
- **A qualidade do vivo é CRF**, não banda: `#env-qualidade` tem `auto/crf26/crf30/crf34` (1205–1211) e o
  caminho ao vivo (`/api/ingestao/ao-vivo`, 1570–1572) **não manda alvo nenhum**; a lista fechada
  `1500k…300k` só existia na bancada (`LISTA_ALVO`, linha 1142) e no radar (1262).

## Fase 1 — tirar do admin o que não é do admin (P0)

- P0: remover o bloco **"Transmissões pedidas pelos clientes"** da tela do admin (`caixaPedidos`: título,
  lista e botão "atualizar lista"). A operação **continua** com ele (ver "Pergunta aberta"); o **cliente**
  já tem o dele em `app/app.js`.
- P0: remover o **"Teste de vídeo (bancada)"** e a tabela de compressões da tela do admin; o download/
  publicar/parar/remover saem junto com ela.
- P0: remover **"Qualidade por câmera (lista fechada)"** da tela do admin — a escolha de banda passa a ser
  **uma só**, na transmissão ao vivo (Fase 2).
- P1: manter na tela apenas o que é do admin/operação: **Transmitir ao vivo**, **Teto do produto** e a
  **trilha de Gravações** (esta última o dono pediu em 18/11 e continua sendo o histórico do que foi gravado).
- P2: tirar a "legenda" longa de medições (linhas 1360–1369) da vista do admin — ela é da bancada.
- P2: conferir que nenhuma rota da API ficou órfã (as rotas continuam existindo para a bancada e os testes;
  só a **tela** muda).

## Fase 2 — a qualidade do vídeo ao vivo é a lista fechada de 1500 a 300 kbps (P0)

- P0: `#env-qualidade` (modo **câmera** e **radar**) passa a ser a **mesma lista fechada** já usada no
  alvo por câmera e no radar: `1500k, 1200k, 1000k, 800k, 500k, 300k` (+ "padrão da tela"), com o rótulo
  em `kbps` — fim da caixa antiga de CRF.
- P0: o caminho ao vivo passa a **mandar o alvo** (`alvo`/`bitrate`) para `/api/ingestao/ao-vivo`, como o
  radar já faz (`bitrate: radarAlvo.value`, linha 1555); a tela mostra o alvo no recado de "NO AR".
- P1: modo **arquivo/link** (bancada) mantém a caixa de CRF — ali "qualidade" é compressão, não banda.
- P1: gravar a escolha do dono: a banda escolhida no vivo fica **guardada na tela** (como o resto do
  formulário, `A.envioForm`) para não voltar ao padrão a cada redesenho.
- P2: o "Teto do produto" (admin) continua valendo só para o **cliente**; a banda do dono na própria
  máquina não é cortada por ele (confirmar no código e provar com teste).

## Fase 3 — a máquina reconhecer as câmeras dela, sempre (P0)

- P0: `preencherDispositivos()` ganha **tentativa de novo** (algumas vezes, com espera) e **catch**: quando
  a lista não vier, a tela **diz o motivo** (servidor local fora do ar x sem câmera x ffmpeg ausente) em
  vez de ficar em branco.
- P0: o aplicativo passa a **esperar o servidor local responder** antes de abrir as janelas que usam captura
  (mesma ordem já aplicada à entrada na 0.6.3) e só então fixa `LECSOR_CAPTURA_BASE`; se o servidor local
  não subir, a tela abre dizendo isso — nada de "Failed to fetch" silencioso.
- P1: quando a tela estiver vinda do **lado terra** (app aberto no lado terra sem captura local), o aviso
  da lista de câmeras explica em uma frase que câmera desta máquina só aparece com o servidor local no ar.
- P2: o menu já tem "Testar câmeras desta máquina" — conferir que ele usa o mesmo caminho e mostra a
  câmera encontrada.

## Fase 4 — provas (P0)

- P0: testes novos/atualizados em `tests/`: a tela do admin **não tem** `#env-pedidos`, não tem
  "Teste de vídeo (bancada)" nem `#env-qualidade-camera`; tem `#env-qualidade` com os 6 degraus de banda.
- P0: teste do vivo: `POST /api/ingestao/ao-vivo` com `alvo` (ex.: `500k`) é aceito e o alvo volta na
  resposta; sem alvo continua valendo o padrão (não quebra quem chama sem o campo).
- P0: atualizar os testes que hoje **exigem** os blocos na tela do admin
  (`tests/test_captura_no_admin.py:280,286`) e o `tests/e2e-operacao-cancela.py` (usa `#env-pedidos` na
  tela da **operação** — ver pergunta aberta).
- P0: prova no **aplicativo de verdade** (relatório do app + tela): com o servidor local no ar, a lista de
  câmeras traz `ACER HD User Facing`; com o servidor local fora, a tela diz o motivo.
- P1: prova de tela no painel de preview (tela do admin limpa + caixa de banda 1500→300 kbps).

## Fase 5 — publicar (P0)

- P0: versão **0.6.4**, notas da release e changelog; commit no `main`, build e publicação da release
  (mesmo caminho da 0.6.3: `tools/publicar-releases.sh`, sha256 conferido contra o asset).
- P1: nota no vault (runbook) + `index.md`.
- P2: caderno de diagnóstico no `INSTALAR-PC-DE-CAPTURA.md` ("não reconhece câmera" = servidor local fora
  do ar ou ffmpeg ausente; a tela agora diz qual dos dois).

## Estado da implementação (18/11/2026 — "aprovado" pelo dono)

- **Fase 1 FEITA:** "Transmissões pedidas pelos clientes" saiu da tela do admin (`if (ehOperador)`); o
  **Teto do produto** e a trilha de **Gravações** ganharam caixa própria (`#env-operacao`); o "Teste de
  vídeo (bancada)", a lista de compressões, os botões de publicar e a legenda de medições ficaram só
  com a **operação**; a "Qualidade por câmera (lista fechada)" saiu para os dois (uma escolha só, no vivo).
- **Fase 2 FEITA:** `#env-qualidade` é a lista fechada **1500k…300k** ("padrão da tela" = vazio) nas
  fontes vivas e CRF só em arquivo/link; o caminho ao vivo manda `bitrate` e a tela mostra o alvo;
  a escolha fica guardada na tela (`A.envioForm`).
- **Fase 3 FEITA:** `preencherDispositivos()` tenta de novo (6× 1,5 s) e, quando não vem, **diz o
  motivo** em vez de ficar em branco; `esperarServidorLocal()` no app espera o servidor local responder
  antes de abrir as janelas e ao recarregar as telas. **Falta:** aviso específico para "tela vinda do
  lado terra sem captura local" (P1) — a mensagem atual já cobre o caso.
- **Fase 4 FEITA:** `tests/e2e-tela-limpa-do-admin.py` (**novo**, 2 navegadores de verdade: admin sem os
  blocos e com a banda 1500→300 kbps chegando na API; operação com pedidos e bancada),
  `tests/test_captura_no_admin.py` atualizado (21 testes OK), `tests/test-config-endereco.py` seção 7.
- **Fase 5 FEITA:** versão **0.6.4** publicada (notas + changelog), commit no `main`, build e release.

## Pergunta aberta (só uma)

**A operação** (papel `operador`) continua vendo "Transmissões pedidas pelos clientes" para poder
**cancelar** um pedido do cliente? Recomendo **sim** (tirar só do admin, como você pediu — "irrelevante pra
**mim**"), porque o cancelamento pela operação é o que o `e2e-operacao-cancela.py` prova e o cliente não
tem como cancelar o pedido de outra pessoa. Se você quiser que **desapareça de todo mundo** e o pedido só
se encerre pelo tempo, eu tiro da operação também e ajusto o teste.

## Fora de escopo (não mexer agora)

- Gravação só até o cliente sair (já publicado) e a trilha imutável de auditoria.
- Radar: fonte/modo/taxa continuam como estão.
- O que o cliente vê (`app/app.js`) fora do que a Fase 1 precisar.

— Aprovar assim ou mudar algo? ("aprovado" = executo as 5 fases e publico a 0.6.4; "corrija X" = ajusto o plano antes.)
