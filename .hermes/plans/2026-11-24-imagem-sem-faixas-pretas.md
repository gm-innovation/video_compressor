# Plano — a imagem deixa de ter faixa preta lateral (e fica maior) — 0.16.0

**Pedido do dono (verbatim, 24/11/2026, com print de 1908x841):**

> deve haver outra forma de exibir as imagens sem ficar com essas faixas laterais pretas, sem cortar as
> imagens e sem deixar os vídeos pequenos na tela

Três exigências ao mesmo tempo: **(1)** nada de faixa preta, **(2)** **sem cortar**, **(3)** vídeo grande.
Status: **aguardando "aprovado"**.

---

## 1. Diagnóstico (medido, não deduzido)

Sonda: `sonda-2.py` (arranjo de `tests/e2e-grade-usa-todo-o-palco-e-menu.py`: 4 câmeras 16:9, menu
**recolhido** — o estado do print —, janela 1908x841 = o tamanho do print). Números em CSS px:

| janela | palco útil | célula | imagem desenhada | **faixa preta (cada lado)** | card |
|---|---|---|---|---|---|
| **1908x841** (o print) | 1872x732 | 934x364 | 582x328 | **176 px = 38% da célula** | 34 px |
| 1536x700 | 1500x591 | 748x293 | 457x257 | 145 px | 34 px |
| 1920x1080 | 1884x971 | 940x483 | 798x449 | 72 px | 34 px |

**As duas causas, separadas:**

1. **A célula não tem a forma do vídeo.** Quem decide o tamanho da imagem é a **altura** da linha (2 linhas
   dividem a altura do palco): a imagem entra com 328 px de altura e a célula tem 934 px de largura. Como o
   vídeo é 16:9 (1,78) e a célula é 2,57:1, sobram **176 px de preto de cada lado**. Foi o efeito colateral
   da Fase 8 da 0.15.0: a grade passou a ocupar o palco inteiro (o que era a queixa anterior) e a sobra da
   largura virou faixa **dentro** de cada célula.
2. **O card come 34 px da altura.** O `.card-cam` (a faixa com nome, estado e botões) fica **abaixo** da
   imagem, dentro da célula: a imagem perde 34 px de altura × 1,78 = **60 px de largura**. A `cabeca` do
   que o dono chama de "vídeo pequeno" está aqui e nas faixas.

**A varredura de colunas (1 a 6) confirma**: para 4 câmeras a melhor coluna continua sendo **2** nas três
janelas (ganho de 1,2% sobre a escolha atual) — o arranjo `2x2` está certo; **o defeito é a forma da
célula e o card**, não o número de colunas.

**O que é impossível (e vai dito, para não prometer o que não existe):** com 4 vídeos 16:9 num palco de
2,56:1, **nenhum** arranjo sem cortar usa 100% da largura — o vídeo 16:9 não é tão largo quanto o palco.
O máximo honesto é: **a imagem ser a maior que cabe na altura disponível e o preto sobrar como margem do
palco (fora das células), não como faixa entre a imagem e a borda**. Isso é o que o desenho novo faz, e
de quebra **aumenta a imagem** (o card sai de dentro da conta):

| janela | imagem HOJE | imagem PROPOSTA | ganho de área |
|---|---|---|---|
| **1908x841** (o print) | 582x328 | **646x364** | **+23,1%** |
| 1536x700 | 457x257 | **521x293** | **+29,9%** |
| 1920x1080 | 798x449 | **859x483** | **+16,7%** |

E **zero faixa preta dentro da célula** nas três (a célula passa a medir exatamente a imagem).

---

## 2. Desenho proposto

- A **célula** (`.janela`) passa a ter a **proporção do vídeo** — quem manda na forma é o vídeo, não o
  palco. A **imagem** ocupa a célula inteira: **nenhum pixel preto dentro dela**.
- O **card** (nome, estado, botões, relógio) sai de baixo da imagem e vai **sobre a imagem** (faixa
  translúcida no rodapé, sempre visível, com gradiente para não atrapalhar a leitura) — é isso que devolve
  os 34 px de altura à imagem.
- A **grade** centra o conjunto no palco (`justify-content/align-content: center`, altura cheia): a sobra
  vira margem simétrica do palco — o conjunto parece um **painel de vídeo**, e não 4 caixas com tarja.
- O **aviso do último minuto** ("Continuar conectado") continua **por cima de tudo** (é a correção da
  0.15.0 que não pode regredir: foi exatamente esse clique que já quebrou uma vez).

---

## 3. Fases (P0/P1/P2 dentro de cada fase)

### Fase 1 — Medir antes (P0)
- **P0** Transformar a sonda em prova versionada (`tests/e2e-imagem-sem-faixa-preta.py`) que, em Chromium
  real com 4 câmeras 16:9, mede em 1908x841, 1536x700 e 1920x1080: a célula, a **imagem desenhada**, a
  **faixa de cada lado** e a **área da imagem**. O "antes" fica registrado no cabeçalho do arquivo.
- **P1** Registrar os números do "antes" no `.hermes/plans/` (tabela acima) para o "depois" comparar.

### Fase 2 — A célula abraça o vídeo (P0)
- **P0** `.janela` com a proporção do vídeo (a proporção real do fluxo, publicada pelo lado terra junto do
  resto da janela — nada de assumir 16:9).
- **P0** `.img-cam`/`<video>` preenchendo a célula exata (`object-fit: fill` no lugar de `contain`, agora
  que a caixa já tem a forma do vídeo) → **faixa de cada lado = 0 px**.
- **P1** Quando o vídeo real não for 16:9 (câmera 4:3, radar), a célula acompanha **cada** fluxo — a grade
  usa a proporção da janela.
- **P2** Sem metadado ainda (`videoWidth=0` no primeiro quadro): manter a 1ª forma medida e reaplicar
  quando o fluxo abrir (nada de piscar/encolher).

### Fase 3 — O card sai de baixo da imagem (P0)
- **P0** `.card-cam` **absoluto** sobre o rodapé da imagem (gradiente translúcido); a imagem passa a ter a
  altura cheia da linha → **+16% a +30% de área** (medido).
- **P0** O clique continua: nome, estado, botões (`▶ ⏺ ⏹ ⟳ ⤓ ⤢`) e o **alerta do "Continuar conectado"**
  com `z-index` acima do card e alvo de toque ≥ 34 px — **o bug de clique da 0.15.0 não pode voltar**.
- **P1** Legibilidade: o gradiente escurece o suficiente para o texto sobre imagem clara (conferir com
  imagem de prova clara e escura).
- **P2** Com o mouse parado sobre a imagem por alguns segundos, o card pode esmaecer (opcional; ligar só
  se o dono quiser).

### Fase 4 — O palco inteiro, agora sem tarja (P0)
- **P0** Grade centrada nos dois eixos, ocupando a altura cheia do palco; margem simétrica.
- **P0** O estado de **menu recolhido** continua sendo respeitado e continua devolvendo largura (a sobra
  vira margem, e a grade ganha altura).
- **P1** Em tela muito larga/baixa, o limite é a altura: a imagem não pode ser cortada — o card e o
  cabeçalho não crescem.

### Fase 5 — Provar e publicar (P0)
- **P0** `tests/e2e-imagem-sem-faixa-preta.py` (**novo**) verde nas três janelas: faixa de cada lado
  **≤ 2 px**, proporção da imagem = a do vídeo (±0,02), **imagem maior que hoje** em cada janela, e
  **nenhuma** imagem cortada.
- **P0** Atualizar os testes que mediam o **contrato antigo** (a grade ocupando 95% da largura do palco —
  métrica-proxy da 0.15.0 que **causava** a tarja): a métrica passa a ser **área da imagem ÷ área do
  palco** + **faixa interna = 0**. Ajustar `tests/e2e-grade-usa-todo-o-palco-e-menu.py`,
  `tests/e2e-imagem-da-grade-nao-corta.py` e `tests/e2e-tamanho-fixo-dashboards-e-telemetria.py`.
- **P0** `python tools/regressao-0130.py` **tudo verde** (30 testes + o novo) e nenhum teste antigo
  "consertado" por baixo (se um teste antigo cair, a mudança de contrato tem de estar justificada aqui).
- **P0** Provar o clique de novo: e2e que força o aviso do último minuto e **clica em "Continuar
  conectado"** nas duas câmeras (o teste que pegou o bug da 0.15.0 tem de continuar verde).
- **P1** Publicar: versão **0.16.0**, instalador, release no GitHub, deploy do lado terra na VPS e nota no
  vault — mesmo rito da 0.15.0.
- **P2** Levar o print "antes/depois" ao dono na mesma resposta.

---

## 4. O que este plano NÃO faz (dito de propósito)

- **Não corta** imagem (nada de `object-fit: cover`) — foi vetado na 0.13.2.
- **Não promete** usar 100% da largura do palco: é geométrico — 4 vídeos 16:9 não preenchem um palco
  2,56:1 sem cortar. O que muda é que a sobra deixa de ser **tarja em cada célula** e passa a ser **margem
  do palco**, com a imagem **maior**.
- **Não mexe** no número de colunas (a varredura mostrou que 2 continua sendo o melhor para 4 câmeras).
- **Não altera** o bordo, o lado terra, telemetria ou gravação — é tela (CSS/JS do cliente + a prova).

---

## 5. Aceite

1. No print de 1908x841, **nenhuma** faixa preta lateral dentro das células, imagem **646x364** contra os
   **582x328** de hoje (+23,1%), sem corte.
2. Os três e2e de grade (2 ajustados + 1 novo) e a suíte completa **verdes**.
3. O clique do "Continuar conectado" segue funcionando (prova automatizada).
4. 0.16.0 publicada (instalador + release + VPS + vault) **ou** o dono dizer que o desenho não é o que
   queria (o que também é aceite: melhor descobrir no papel).

---

## 6. RESULTADO (medido, 24/11/2026 — o que ficou de fato)

Todas as fases foram feitas. O que a prova mede, com o número ao lado:

| janela (menu recolhido) | antes: imagem / faixa | depois: imagem / faixa | ganho de área |
|---|---|---|---|
| **1908x841** (o print do dono) | 582x328 / **176 px de cada lado (38%)** | **643x362** / **1,8 px** (a borda de 1 px) | **+21,8 %** |
| 1536x700 | 457x257 / 145 px | 507x285 / 1,8 px | +22,8 % |
| 1920x1080 | 798x449 / 72 px | 921x518 / 1,8 px | +33,3 % |

- A célula passou a **646x364** (a forma do vídeo) — a "faixa preta dentro da célula" deixou de existir; o
  que sobra é a **margem simétrica do palco** (medida: palco útil 1872, painel 1292, margem 290 de cada
  lado), que é preto do palco e não tarja de cada imagem.
- O card (34 px, uma linha) **flutua sobre o rodapé da imagem** — não come mais altura.
- **4:3 provado**: com um vídeo 640x480 de verdade a célula vira **485x364** e a imagem desenhada
  482x362 (razão 1,33) — a célula segue o **fluxo**, não um 16:9 chumbado.
- **Clique provado com DUAS câmeras no ar**: o aviso do último minuto aparece nas duas e o
  "Continuar conectado" foi clicado **nas duas** (medido no banco: 26 s → 896 s na 1ª, 23 s → 894 s na
  2ª). Era a queixa da 0.15.0.

### Contratos trocados de propósito (e por quê)

1. **O card deixa de ficar ABAIXO da imagem.** `tests/e2e-imagem-da-grade-nao-corta.py` e
   `tests/e2e-janela-ao-sair-da-tela.py` mediam "o card começa onde a imagem termina" — era o contrato
   que **causava** o vídeo pequeno (o card comia 34 px de altura = 60 px de largura). Agora medem o card
   **sobre** a imagem. O que se preserva: o card continua sendo o dono do controle de transmissão.
2. **A métrica da grade deixa de ser "a grade ocupa 95 % da largura do palco".** Era métrica-proxy da
   0.15.0 — e era ela que **premiava** a tarja dentro da célula. A métrica passou a ser **face interna
   = 0 + painel centrado + imagem maior**, em `tests/e2e-grade-usa-todo-o-palco-e-menu.py`.
3. **`object-fit` continua `contain`** (o plano citava `fill`): com a célula já na forma do vídeo o
   resultado é o mesmo, e o `contain` não estica nada no primeiro quadro, antes do metadado do fluxo
   chegar. Desvio consciente, não esquecimento.
4. **A entrada/cadastro deixam de aceitar CORS.** Achado da suíte: `eh_rota_de_captura` respondia às
   duas perguntas ao mesmo tempo (de quem é a rota **e** quem de fora pode chamá-la). Como
   `/api/entrar`, `/api/eu` e `/api/cameras` são desta máquina (roteamento, dono 19/11), elas ganharam
   CORS sem precisar. Agora há duas listas: `eh_rota_de_captura` (roteamento) e
   `eh_rota_de_captura_cors` (CORS só nas rotas da tela "Enviar vídeo"). `tests/test_captura_no_admin.py`
   voltou a provar as provas 04 e 05.

### Provas

- `tests/e2e-imagem-sem-faixa-preta.py` — **novo**, 68 verificações verdes, nas 3 janelas + 4:3 + o
  clique nas duas câmeras. Está dentro de `tools/regressao-0130.py` (**31 provas**).
- `python tools/regressao-0130.py` → **TUDO VERDE (31 provas)**, rc=0.
- `python -m unittest discover -s tests -p "test_*.py"` → **OK (22 testes)**.
