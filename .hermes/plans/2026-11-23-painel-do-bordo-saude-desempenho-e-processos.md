# Painel do Bordo: configuração autônoma, saúde e DESEMPENHO, e os processos em andamento

Pedido do dono (23/11/2026, verbatim):

> okay, após a validação da chave de acesso, o app inicia a sua configuração local autônoma e exibe as
> informações de saúde e desempenho na tela, bem como os processos em andamento, como stremming, salvando
> vídeo, ambos, etc...

Isto é o passo seguinte do bordo autônomo já publicado (**0.11.0**). O painel `/bordo` de hoje já é sem
login e já traz licença/token/lado terra/agente/varredura/publicação/saúde — falta o que ele pede agora:
**desempenho** e **os processos em andamento** (streaming, gravando full-time, os dois).

## Estado de hoje (medido no código, não suposto)

- `/bordo` + `/api/bordo` existem e são servidos pelo próprio bordo, sem login (`ground/api.py`:
  `_resumo_do_bordo`), e a tela é `bordo/index.html`.
- Já entram no resumo: `licenca` (só 4 dígitos), `token` (presente/ausente), `lado_terra`, `agente`,
  `varredura` + `publicadas`, `no_ar` (de `ordens/ligados.json`) e `saude` (`saude_do_bordo.retrato()`).
- **`no_ar` hoje só diz que um fluxo foi ligado** — não distingue *transmitindo* de *gravando*, nem
  mostra "os dois".
- Desempenho **não** aparece: existe medido, mas em outro lugar — `telemetria_minuto`
  (`entrada_kbps`, `saida_kbps`, `compressao_pct`, `mb_enviados`, `segundos_no_ar`, por fluxo e por minuto,
  lidos por `ground/publicar_telemetria.py`) e o link SRT (`producao.obter_link()`:
  `rtt_ms`, capacidade, taxa de envio, atraso de buffer, perda %) + latência de internet
  (`producao.latencia_internet()`).
- Gravação full-time do radar **existe** (`ground/gravacao_continua.py`, com `--estado`), nasce DESLIGADA
  e é ligada pelo admin (`LECSOR_GRAVACAO_CONTINUA=1` + dispositivo).

## Fase 1 (P0) — Os processos em andamento, com o nome certo

Acrescentar ao `_resumo_do_bordo()` um bloco `processos`: uma lista por fluxo, com **o que está acontecendo
agora**, vinda das fontes reais:

- `TRANSMITINDO` — o fluxo está em `ordens/ligados.json` (ordem do cliente/admin, com `desde` e `ordem`);
- `GRAVANDO` — a gravação full-time está ligada e o fluxo é o do radar (`gravacao_continua`), com o
  diretório/HD e há quantos blocos/minutos grava;
- `TRANSMITINDO + GRAVANDO` — o caso "ambos" (o dono quer ver isso explícito);
- `PARADO` — nem um nem outro (com o motivo quando houver: licença bloqueou, sem dispositivo, etc.).

## Fase 2 (P0) — Desempenho (só o que é medido; o resto é "sem medida")

Bloco `desempenho` por fluxo, do último minuto em `telemetria_minuto`:

- entrada (kbps) × saída (kbps) e **% de redução** (`compressao_pct`);
- MB enviados e segundos no ar no minuto;
- link: RTT (ms), capacidade do link, taxa de envio, atraso de buffer e perda %, + latência de internet;
- **`fps` não tem fonte local hoje** (o `telemetria_minuto` não guarda quadros): a tela diz
  **"sem medida"** — não invento número. Se o dono quiser fps no painel, é item à parte (medir no ffmpeg).

## Fase 3 (P1) — A configuração local autônoma que ele iniciou

Um bloco `configuracao` ("o que este bordo já se configurou sozinho"): token do pacote em uso, lado terra
que ele observa, a varredura local (quando rodou, o que achou/publicou) e a saúde — juntando o que hoje
está espalhado em `lado_terra`/`varredura`/`saude`, na ordem em que aconteceu.

## Fase 4 (P1) — Saúde e desempenho juntos na tela

Reagrupar a tela em três cartões, na língua do dono: **"O que está acontecendo agora"** (Fase 1),
**"Saúde e desempenho"** (Fase 2 + a saúde que já existe) e **"Como esta máquina se configurou sozinha"**
(Fase 3). Nada de segredo novo: a chave continua só nos 4 últimos dígitos.

## Fase 5 (P2) — Prova

- `tests/test-bordo-sem-login-e-autonomo.py`: casos novos — (a) gravando (com o `gravacao_continua` ligado)
  aparece como `GRAVANDO`; (b) transmitindo **e** gravando aparece como "os dois"; (c) uma linha de
  `telemetria_minuto` aparece como desempenho (entrada × saída e a % de redução); (d) sem medida, o painel
  diz "sem medida" e **não** inventa número; (e) nada de senha/segredo na tela.
- Regressão inteira (`tools/regressao-0100.py`, 20 provas) + `node --check` + `py_compile`.

## Entrega

Versão nova do app (**0.11.1**): commit no `main`, build do instalador, release (`latest`), deploy do lado
terra na VPS (o `api.py` é compartilhado) e nota no vault.

## O que NÃO entra

- Medir fps no bordo (exigiria abrir a medição no ffmpeg) — só se o dono pedir.
- Qualquer ação na tela do bordo (ela continua **só informando**; quem liga/desliga é o admin/cliente).
