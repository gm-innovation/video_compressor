**Status:** aguardando aprovação (o dono disse, 24/11/2026: *"continua diminuindo as telas quando
reconecta principalmente, e as telas ainda estão pequenas, elas precisam ser mais responsivas e utilizar
o maior espaço possível"*, com 2 prints da tela do cliente). **Nada é implementado sem "aprovado".**

# A grade do cliente: telas maiores, card que não come a imagem e nada de encolher no reconecta

Dono, verbatim (24/11/2026), com dois prints da tela **do cliente** (`/app/` → "Transmissões ao vivo"):

> continua diminuindo as telas quando reconecta principalmente, e as telas ainda estão pequenas, elas
> precisam ser mais responsivas e utilizar o maior espaço possível

Nos prints: 3 câmeras, grade 2×2, cada imagem em ~460×230 com o card do controle abaixo; muita área
vazia à direita e embaixo. No 1º print as duas janelas da mesma linha estão **desalinhadas** (uma mais
alta e deslocada para cima, as alturas diferentes).

## O que já foi MEDIDO nesta máquina (sonda, não palpite)

Sonda `sonda-tamanho.py` (Chromium de verdade, API local, 3 câmeras com vídeo 1280×720 real, grade 2×2):

| Janela | palco disponível | imagem de cada janela | card | observação |
|---|---|---|---|---|
| 1600×900 | 1348×791 | 558×314 | 78 px | sobra **227 px** de largura sem uso |
| 1920×1080 | 1668×971 | 718×404 | 78 px | sobra **228 px** |
| 1366×768 | 1114×659 | 440×247 | 78 px | |
| 1280×720 | 1028×582 | 372×209 | 78 px | |

Fatos que saem da sonda (e do código):

1. **A ALTURA é o que limita o tamanho, e quem come a altura é o CARD.** O cálculo é
   `largura = min((aw-(cols-1)*5)/cols, r*(ah-(linhas-1)*5-linhas*cardH)/linhas)` (`app/app.js:217`).
   Com o card de 78 px a imagem para em 558 px de largura; **com o card de ~110 px (o dos prints, com
   os rótulos longos: "Baixar 1 minuto", "Gravar (no lado terra)", "Parar transmissão") ela cai para
   ~460 px**, que é exatamente o que o dono está vendo. O card está ocupando **2 a 3 linhas** dentro
   de uma janela de 460-560 px.
2. **A largura que sobra nunca é usada.** Em 1600×900 sobram ~227 px (17 %) e em 1920×1080 os mesmos
   ~228 px: como a altura manda, a coluna para de crescer e a sobra vira margem — o dono chama isso
   de *"utilizar o maior espaço possível"*.
3. **O número de colunas é fixo por heurística** (`porPagina()`: ≤4 câmeras → 2), nunca pela área
   disponível. Com card compacto, 2 colunas = 631 px por imagem contra 3 colunas = 449 px: a escolha
   certa hoje não é a escolha certa sempre, e ninguém recalcula isso pela área.
4. **Só o `window.resize` recalcula** (`app/app.js:1423`). Abrir/fechar a barra lateral, o "Tela
   cheia" e o "Destaque" **não** disparam `ajustarGrade()` — a grade fica com o tamanho da janela
   anterior (é a parte "não é responsiva").
5. **As alturas das janelas da mesma linha divergem** (`grid-auto-rows:auto` + `align-items:center`):
   duas imagens na mesma linha com cards de alturas diferentes ficam desalinhadas — é o 1º print.
6. **O card muda de altura conforme o estado**: `montarControle()` troca o TEXTO dos botões
   ("Iniciar transmissão" ↔ "Reconectar", o aviso do último minuto entra) — e o `ajustarGrade()` roda
   no `resize` do `<video>` e no `loadedmetadata`. **É isto o "diminui quando reconecta"**: ao
   reconectar, o texto/aviso muda a altura do card e a próxima medida encolhe a imagem.
   (A sonda não reproduziu o encolhimento porque o card dela já estava com 78 px e estável; a causa é
   a **variação** da altura do card entre estados, medida no item 1.)

## Fase 1 — O card vira UMA linha (P0)

- **P0** O card do controle passa a ter **uma linha só**: ponto de estado + rótulo curto da câmera +
  os botões **em ícone** (`⤓` baixar 1 minuto, `⤢` destaque, `▶` iniciar / `⟳` reconectar, `⏺`
  gravar, `⏹` parar), cada um com `title` e `aria-label` com o texto de hoje. Sem perder nenhuma
  ação: só o rótulo visível encolhe.
- **P0** Emoji/ícone não pode ser a única pista: `title` + `aria-label` + a classe do botão mantêm o
  significado para quem passa o mouse e para o leitor de tela.
- **P1** `<div class="caixas">` e o aviso do último minuto continuam **dentro da área da imagem**
  (não empurram mais o card).
- Prova: a altura do card medida ≤ **40 px** com qualquer estado (parado, no ar, contagem no último
  minuto, "Reconectar").

## Fase 2 — Usar o maior espaço possível (P0)

- **P0** O número de colunas deixa de ser heurística fixa: o `ajustarGrade()` **testa as colunas
  possíveis (1..4) e escolhe a que dá a MAIOR imagem** para a área disponível (mesma conta de hoje,
  uma vez por hipótese). Os botões `2×2 / 3×3 / 4×4` continuam mandando quando o modo **não** é
  "Automático".
- **P0** A janela passa a ocupar a célula inteira (`width:100%` na coluna calculada) — nada de imagem
  centralizada com margem morta dentro da própria célula.
- **P1** Com a altura sobrando depois de o card encolher (Fase 1), a imagem cresce até a largura
  disponível — medido de novo na prova.
- Prova: a imagem de cada janela **cresce** em relação à medida de hoje nos 4 tamanhos de janela da
  tabela (não é meta: o número medido na prova tem de ser maior que 558×314 em 1600×900).

## Fase 3 — Responsiva de verdade (P0)

- **P0** `ResizeObserver` no `.palco` (um só, observando o elemento) no lugar de depender do
  `window.resize` — pega a barra lateral abrindo/fechando, o "Tela cheia", o "Destaque" e a janela do
  navegador redimensionada.
- **P0** Recalcular ao trocar tela (`Visualizar` ↔ `Transmitir`), ao trocar de página e ao trocar o
  layout (`Automático`/`2×2`/`3×3`/`4×4`).
- **P1** Recalcular no `loadedmetadata` continua como está (a proporção real da câmera é o que define
  a área da imagem).
- Prova: com a barra lateral aberta e fechada, a grade ocupa a mesma fração da área disponível; nenhum
  caminho deixa a grade com medida antiga.

## Fase 4 — Nada de diminuir no reconecta (P0)

- **P0** A altura do card é **fixa na linha única** (Fase 1): reconectar, contar o último minuto ou
  mudar o texto do botão **não muda mais a altura** — e, como o tamanho da imagem sai da altura, o
  tamanho para de mudar.
- **P0** A proporção por câmera (`S.proporcao`) **sobrevive** ao ciclo de reconexão: o que já foi
  medido não volta para 16/9 enquanto o `<video>` estiver sem metadado (hoje `proporcaoDaGrade()` usa a
  MENOR das conhecidas — o que é correto — mas a janela nova/remontada cai no 16/9 do CSS antes de
  receber o metadado).
- **P1** As janelas da MESMA linha com a mesma altura (`align-items:stretch` + card de altura fixa):
  acaba o desalinhamento do 1º print.
- Prova: medir a imagem antes e depois de um "reconecta" (recarregar o metadado do `<video>`) **e**
  depois de alternar o estado do card (parado → no ar → aviso do último minuto) e exigir a **MESMA**
  medida, como já se faz desde a 0.14.0 para o redesenho de 5 em 5 s.

## Fase 5 — Prova, publicação e nota (P0)

- **P0** Prova nova `tests/e2e-grade-responsiva-e-card-compacto.py`: com 3 câmeras de vídeo real mede,
  em 4 tamanhos de janela, (a) a altura do card ≤ 40 px; (b) a imagem maior que a medida de hoje;
  (c) o tamanho idêntico depois de reconectar e de trocar o estado do card; (d) as janelas da mesma
  linha com a mesma altura; (e) a barra lateral abrindo/fechando sem deixar medida velha.
- **P0** `tools/regressao-0130.py` (as provas de hoje continuam passando: a imagem não pode voltar a
  cortar nem a mudar de tamanho no redesenho).
- **P0** Commit/push, release com o instalador, deploy do terra na VPS e nota no vault — o fluxo das
  rodadas anteriores.
- **P1** Instalar a versão nova no PC de captura real (depende do dono).

## Fase 6 — O bordo morre e a transmissão continua no ar (P0, pedido de 24/11/2026)

Dono, verbatim: *"acabei de desinstalar o app de captura para instalar a v0.14.0 e a transmissão continua,
como continua transmitindo se eu desinstalei o app?"*

**Medido na VPS (24/11/2026 17:24, `db/pipeline.db`):** não está chegando vídeo — o que continua é o
**estado da sessão**:

- `saude_bordo` da embarcação `bancada`: último contato **17:20:40**, máquina `DESKTOP-78DSH57` (o app
  parou de reportar);
- as 3 transmissões estão `no_ar` com `batimento_em` = **17:24:46** — o batimento é do **cliente**
  (`cliente@lecsor.test`), não do bordo;
- **nenhum** arquivo de mídia (`*.m3u8`/`*.ts`/`*.mp4`) foi escrito nos 10 minutos anteriores: o
  navegador mostra o último trecho/quadro que já estava no terra;
- no código, quem encerra a sessão é o batimento do cliente (`SEGUNDOS_SEM_BATIMENTO = 60`,
  `ground/api.py:1278`) ou o `termina_em` da sessão. O silêncio do bordo **só** mexe na saúde
  (`LIMIARES_DE_SAUDE["mudo_s"]` = atenção 180 s / problema 600 s) — nunca encerra nada.

- **P0** Bordo mudo além do limite (o mesmo `mudo_s`, 600 s configurável) **encerra** as sessões abertas
  daquela embarcação: `estado` da transmissão vai para um estado terminal (ex. `caiu`) e o lado terra
  para de mandar `desejo`.
- **P0** A tela do cliente mostra o motivo real **na hora**: "a captura da embarcação parou de responder
  há N min" (com o botão de reconectar só quando o bordo voltar), em vez de "no ar" com imagem parada.
- **P0** O painel do admin mostra a mesma queda (a saúde já é lida; hoje ela não derruba a sessão).
- **P1** Enquanto o bordo está mudo, o `desejo` não é reenviado e a sessão não é renovada pelo
  `termina_em` (não faz sentido renovar o que não tem captura).
- **P1** O bordo que volta (o mesmo `embarcacao_id`) **não** ressuscita a sessão antiga: o cliente
  reconecta de propósito.
- Prova: `tests/e2e-bordo-mudo-encerra-transmissao.py` — com uma sessão `no_ar` e a saúde do bordo
  atrasada além do limite, a sessão termina, a tela mostra o motivo e o `desejo` da câmera vai a
  "parar"; com a saúde voltando, a sessão **não** volta sozinha.

## Fase 7 — Dashboard de verdade no PC de captura (P0, pedido de 24/11/2026)

Dono, verbatim: *"você chama aquilo que você fez de dashboard? preciso de um dashboard real no pc de
captura, só tem um monte de cards, mas eu quero um dashboard de verdade!"*

**Medido em `bordo/index.html` (547 linhas):** a página tem **7 blocos de `h2` com texto** ("O que está
acontecendo agora", "Licença", "Envio para o lado terra", "Agente de ordens", "Varredura", "Saúde e
desempenho", "Como esta máquina se configurou sozinha") e, na primeira dobra, o `.painel` que eu chamei
de dashboard: **4 cartões de número** (CPU, memória, disco, rede) + a lista individual. Não há gráfico,
série no tempo, medidor nem modo TV — é texto e número. **A série existe no banco** (`receber_saude_do_bordo`
grava "última + série" e há a tabela `telemetria_minuto`), mas nenhuma tela a mostra.

- **P0** Tela única, **sem rolagem**, pensada para o monitor do PC de captura: faixa de números grandes
  (CPU, memória, disco, rede) com o semáforo de sempre no topo.
- **P0** **Gráficos de linha no tempo** de CPU, memória, disco e rede (janelas de 30 min / 6 h / 24 h)
  sobre a série que já está no banco — endpoint novo que expõe a série (hoje `GET /api/bordo` só devolve
  o retrato).
- **P0** **Por câmera/encoder**, uma linha viva: kbps, fps, CPU, memória, estado (streaming / gravando /
  ambos / parado) e a miniatura do último quadro — não uma lista de texto.
- **P0** **Modo TV**: tela cheia, sem menu, auto-atualizado, para deixar aberto no monitor do PC de
  captura (o dono não fica clicando nessa máquina).
- **P1** Os 7 blocos de hoje **não somem**: viram os cartões de detalhe (expansão) do dashboard, com
  licença, envio ao terra, agente de ordens, varredura e config local.
- Prova: `tests/e2e-dashboard-do-bordo-de-verdade.py` — os gráficos existem e desenham (canvas com
  pontos), os números batem com a série do banco, o modo TV é tela cheia e o que não foi medido continua
  saindo declarado.

## O que NÃO entra nesta rodada

- O vídeo ao vivo do admin e a telemetria (entregues na 0.14.0).
- Mudança de servidor/API **fora da Fase 6**: as Fases 1 a 5 são só a **tela do cliente** (HTML/CSS/JS).
- A "IA · Análises" e o radar de óleo.
