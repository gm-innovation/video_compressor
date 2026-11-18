# Gravação só até o cliente sair: avisa para baixar e apaga o arquivo quando ele sai

Dono, 18/11/2026 (VERBATIM): *"só mantém na vps o que for gravado, ao final da gravação, precisa
avisar ao cliente para ele fazer o download do vídeo, quando ele desligar o sistema ou sair da tela
os arquivos serão apagados"*.

Lido junto com o que o dono já fixou antes: o **"nada é apagado" é a trilha de auditoria** (sempre
saber quais ações foram tomadas e por quem) — ela **não é apagada nunca**. O que se apaga é o
**arquivo de vídeo**.

## O que já existe hoje (conferido no código, 18/11/2026)

- `ground/gravacao.py` grava no **lado terra** o que já chegou (`-c copy`), em
  `ground/gravacoes/<id>.mp4` (fragmentado enquanto grava, remontado ao parar), com ficha
  `<id>.json`. `LECSOR_GRAVACOES_DIR` tira do repositório em produção.
- `GET /api/gravacoes/<id>` baixa o arquivo (só o dono da sessão ou a operação) e registra
  `gravacao_baixada` na auditoria.
- Histórico: tabela `transmissoes` + `auditoria` — **nada apagado** (`transmissao_pedida`,
  `transmissao_encerrada`, `transmissao_cancelada`, `gravacao_iniciada`, `gravacao_parada`,
  `gravacao_baixada`).
- **O que NÃO existe:** nenhum aviso ao cliente no fim da gravação, nenhuma limpeza por saída do
  cliente, nenhuma varredura de sobras. Hoje o arquivo fica na VPS para sempre — é o que muda aqui.

## Fase 1 — Avisar o cliente no fim da gravação · P0

1. Quando a gravação para (`parar`, corte por tempo com gravação, ou fim da sessão), o lado terra
   sabe que o arquivo está **pronto**: `GET /api/transmissao` passa a devolver, por sessão,
   `gravacoes_prontas: [{transmissao_id, camera_rotulo, bytes, segundos, baixar_em}]`.
2. Na tela do cliente (`app/app.js`), a sessão que tem gravação pronta mostra **faixa fixa**:
   *"Gravação pronta — baixe agora: ela é apagada quando você sair da tela"*, com o botão de
   download e o tamanho em MB. O aviso fica enquanto o cliente estiver na tela.
3. Aviso **por ação do cliente também**: se ele tentar fechar/atualizar a tela com gravação pronta
   e ainda não baixada (e não marcada como "já baixei"), o navegador pede confirmação
   (`beforeunload`) — a última chamada antes de a tela sumir.
4. Auditoria: `gravacao_avisada` (o aviso apareceu) — para sempre saber que ele foi avisado.

## Fase 2 — Apagar os arquivos quando o cliente sai · P0

1. Rota nova `POST /api/transmissao/sair` (só o cliente dono da sessão, e só as sessões dele): o
   navegador chama por `navigator.sendBeacon`/`fetch(keepalive)` no `pagehide`/`unload` e no
   **Sair** do menu (logout).
2. Efeito: **apaga os arquivos** das gravações daquele cliente (`<id>.mp4`, `<id>.json`, sobras
   `<id>.parcial.mp4`) e marca a sessão como encerrada. **A auditoria e o histórico ficam**:
   grava-se `gravacoes_apagadas` com quem, quando, quantos bytes e quais transmissões.
3. **Download em curso não é cortado:** se houver download daquele arquivo em andamento, o
   arquivamento é adiado até ele terminar (curto), e só então o arquivo sai. Sem isso o cliente
   baixaria um arquivo pela metade.
4. Logout (`/api/sessao/sair`) também dispara a limpeza dos arquivos do cliente.
5. Rota irmã da operação, para o caso de a tela do cliente fechar sem avisar (queda de energia,
   navegador travado): o lado terra varre a cada ciclo (`vigiar_transmissoes`) e apaga a gravação de
   sessão **encerrada sem download** depois de uma janela curta (`LECSOR_MINUTOS_PARA_BAIXAR`,
   padrão 15 min) — o mesmo prazo que a tela mostra ao cliente no aviso.

## Fase 3 — Só o que foi gravado fica na VPS · P1

1. A VPS guarda **apenas** o arquivo da gravação e a ficha, e só durante a janela acima — nada de
   cópia, transcode, sobra de teste ou fragmento esquecido.
2. Varredura no start (já existe `limpar_orfas`, que só marcava): passa a **remontar** o fragmento
   bom em mp4 final e **apagar** fragmento imprestável e ficha de processo morto, registrando
   `gravacao_sobra_limpa` na auditoria.
3. Se o disco estiver apertado, o lado terra registra `gravacao_sem_espaco` e **não começa** a
   gravação (melhor avisar do que gravar picado).

## Fase 4 — A tela e o documento · P1

1. Tela do cliente: o botão de download mostra o tamanho, o prazo que resta da janela e um
   *"já baixei"*; ao marcar, o aviso some e o arquivo pode ser apagado na hora.
2. Operação (`/admin`, "Enviar vídeo"): coluna *"gravações"* mostrando, por sessão, se o arquivo
   ainda existe, o tamanho e **quando foi apagado** (nunca o conteúdo — a trilha).
3. `docs/instalacao-transmissao-a-pedido.md`: seção nova — o aviso ao cliente, o prazo, o que é
   apagado, o que **nunca** é apagado (a auditoria).

## Fase 5 — Provas · P0 (junto de cada fase, não no fim)

1. `tests/test-gravacao-no-lado-terra.py` (159 linhas, existe): ganha os casos
   *"o aviso aparece quando o arquivo fica pronto"*, *"sair apaga o arquivo e a auditoria fica"*,
   *"download em curso não é cortado no meio"* e *"a sobra é limpa no start"*.
2. Prova de tela (novo `tests/e2e-gravacao-baixar-e-sair.py`): cliente grava, vê o aviso, baixa o
   arquivo de verdade, sai da tela → o arquivo **não está mais** em disco, e a auditoria mostra o
   pedido, a gravação, o aviso, o download e o apagamento, com autor e data.
3. `tests/test-transmissao-a-pedido.py`: o cliente não consegue apagar gravação de outro cliente
   (403) nem apagar sem ser o dono da sessão.

## Estado da implementação (18/11/2026 — aprovado pelo dono)

- **Fase 1 (P0) — feito:** `GET /api/transmissao` devolve `gravacoes_prontas` ao cliente (com tamanho,
  tempo, `baixar_em` e `baixar_ate`); a tela mostra a faixa fixa `#aviso-gravacao` ("Gravação pronta —
  baixe agora", "é apagado quando você sair da tela"), com **Baixar** e **"Já baixei — pode apagar"**;
  o navegador avisa antes de fechar (`beforeunload`) quando há gravação pronta não baixada; a primeira
  exibição grava `gravacao_avisada` na auditoria.
- **Fase 2 (P0) — feito:** `POST /api/transmissao/sair` (chamado por `sendBeacon` no `pagehide` e no
  botão Sair) encerra as sessões do cliente e **apaga os arquivos**; `/api/sair` faz o mesmo no logout;
  download em andamento **não é cortado** (`gravacao.abrir_para_baixar`/`apagar` devolve `adiado`); a
  varredura do vigia (`apagar_gravacoes_vencidas`) apaga o que ninguém baixou depois de
  `LECSOR_MINUTOS_PARA_BAIXAR` (padrão 15 min); tudo com `gravacoes_apagadas` na auditoria.
- **Fase 3 (P1) — feito:** `apagar()` remove mp4 + `.parcial.mp4` + ficha + log; `limpar_orfas()`
  **remonta** o fragmento bom em mp4 final (a máquina caiu gravando) e apaga a sobra.
- **Fase 4 (P1) — feito:** botão com tamanho/prazo/"já baixei"; a operação vê a trilha
  (`#env-gravacoes` em "Enviar vídeo" e `gravacoes` em `GET /api/transmissao/pedidos`), com tamanho,
  quem gravou, se baixou e **quando o arquivo saiu**; `docs/instalacao-transmissao-a-pedido.md` §3.1.
- **Fase 5 (P0) — provado:** `tests/test-gravacao-no-lado-terra.py` (18 checagens: adiamento no
  download, apagamento real, sobra remontada com ffprobe), `tests/test-transmissao-a-pedido.py`
  (bloco 13 — aviso, trilha, 403 de outro cliente, sair apaga, linha do histórico fica) e
  `tests/e2e-gravacao-baixar-e-sair.py` (**21 checagens**: grava de verdade, avisa, o cliente baixa
  523 KB de vídeo real, sai da tela → arquivo apagado no disco, histórico e auditoria intactos).

## Fora de escopo (não pedido)

- Guardar a gravação em nuvem/terceiro, reter por dias, ou mandar o vídeo por e-mail.
- Mexer em qualquer coisa do bordo (a gravação é no lado terra, decisão já fixada).

## Riscos conhecidos

- **Cliente fecha no meio do download** → a Fase 2.3 cobre (espera o download terminar antes de
  apagar).
- **Navegador não entrega o `beacon`** (rede caiu) → a varredura da Fase 2.5 apaga sozinha depois
  da janela; o arquivo nunca fica para sempre.
- **Cliente quer o arquivo depois de sair** → não tem: por decisão do dono, sai da tela, o arquivo
  sai. O que fica é o registro de que existiu (tamanho, tempo, autor).
