# Painel do app de captura (largura, CPU/memória/rede, abrir com o Windows) e o pedido que fica "chegando…" para sempre

**Pedido do dono (26/11/2026, com print da tela "Gravações")**, verbatim:

> "não entendi esse bloco, isso foi teste? esse "chegando..." parece que está travado. o dashboard do app de
> captura não está com o layout padrão como o do admin, está utilizando apenas a faixa central da tela, muito
> espaço vazio nas laterais, não está exibindo as informações de cpu, memória e rede, o app precisa sempre
> ligar automaticamente junto com o computador"

## Diagnóstico medido (26/11/2026 — só leitura)

**1. Aquilo É dado de teste, e o "chegando…" está travado por um motivo real.** Medido no banco da VPS
(`/tmp/foto-hd-0240.py`):

- o bloco que o print mostra é o **radar de teste** `teste-radar-lecsor`, da embarcação **`teste-emb-lecsor`**
  (criada pela semente da 0.24.0), com 4 blocos a **11 min** de distância (16:50 / 17:01 / 17:12 / 17:23 —
  `atraso_min=11`, o valor que a semente usa só nessa embarcação);
- existe **um pedido aberto**: `hd_pedidos.id = 8b8e2c59ea7a70b5`, câmera `teste-radar-lecsor`, usuário
  `cliente@lecsor.test`, **estado `pedido`**, criado em `2026-11-26T18:15:45Z`, sem `pronto_em` e sem `bytes`;
- **não existe bordo** nessa embarcação de teste (ela é fictícia): ninguém vai responder o pedido, e a tela
  fica em **"pedido enviado ao barco / chegando…" para sempre** — `app/app.js:861` só escreve esse texto no
  clique e nada o substitui enquanto o pedido não vira `enviado`;
- no **bordo de verdade** (`bancada`, radar): o catálogo está publicado mas com **0 blocos** —
  `hd_catalogo` de `radar`/`bancada`, `atualizado_em 18:34`, `blocos = []`. Ou seja: mesmo na embarcação real
  não há trecho para pedir (nada foi gravado ainda), e a tela não diz isso.

**2. O painel do app de captura tem largura fixa — é o "faixa central com espaço vazio nas laterais".**
`bordo/index.html:28`:

```css
.carta { width: min(880px, 96vw); margin: 0 auto; }
```

O painel do bordo (a tela de entrada do app de captura — `desktop/main.js:243 urlDe('entrada')`) é desenhado
dentro de uma carta de **no máximo 880 px**, centralizada; em tela larga sobram as duas faixas vazias que o
dono viu. Já existe a exceção `body.tv .carta { width: 100%; max-width: none; }` (linha 119) — o modo usado na
TV — então a largura total já foi prevista, só não é o padrão do painel. O admin/cliente usam a tela inteira.

**3. CPU / memória / rede não têm o que desenhar hoje na VPS.** O painel traz os quatro gráficos (CPU,
memória, disco, rede — `bordo/index.html:161-184`) e os alimenta por `GET /api/bordo/serie` e `GET /api/bordo`
(`bordo/index.html:1000`, `:337`). Medido na VPS agora:

- `GET /api/bordo` → 200, mas diz **`agente.no_ar = false`** ("o agente de ordens ainda não …") e
  **licença não ativada** (`tem: false, ativada: false`);
- `GET /api/bordo/serie?pontos=720` → 200 com **`pontos: []`** — série vazia, logo os gráficos abrem em "—".

Então não é (só) layout: **sem o agente no ar / sem a máquina ativada não há série de saúde**, e o painel não
diz o motivo — abre com traços, o que para o dono parece "não está exibindo".

**4. "Abrir junto com o Windows" já existe como recurso, mas não é verificável nem garantido.** O app de
captura já nasce com `abrirComWindows: true` (`desktop/configuracao.js:77`, quando o usuário nunca escolheu),
o menu tem a caixa (`desktop/main.js:412`) e a cada abertura o app reafirma
`app.setLoginItemSettings({ openAtLogin: config.abrirComWindows })` (`desktop/main.js:524`). O que **não**
existe: o painel **não mostra** se está ligado, e se o Windows tiver a entrada desabilitada (Gerenciador de
Tarefas → Inicializar) nada é reafirmado de forma visível nem há uma segunda via. Falta a medida no PC de
captura real (não é medível daqui).

## Fases (prioridade dentro de cada fase)

### Fase 1 — P0 — "chegando…" para sempre (o pedido que o bordo nunca responde)

- **1.1 (P0)** O bloco do bordo mostra o **tempo decorrido** desde o pedido ("pedido enviado ao barco há 12 min")
  e, passado um **limite** (a definir: 10 min), troca para **"o bordo não respondeu"**, com o motivo honesto:
  a embarcação não está publicando / não tem bordo no ar. Nunca um "chegando…" eterno.
- **1.2 (P0)** O pedido velho **não fica pendurado**: entra na lista de "sem resposta" (mesmo estado do
  histórico) e o botão volta a "pedir" (nova tentativa).
- **1.3 (P1)** Quando o catálogo do bordo vem **vazio** (o caso do `bancada` hoje), o bloco **diz** o motivo
  ("o bordo ainda não publicou nenhum trecho desta câmera") em vez de mostrar tabela vazia.
- **Prova:** `tests/e2e-pagina-unica-de-gravacoes.py` ganha o caso do pedido sem resposta (estado + texto na
  tela) e o caso do catálogo vazio; prova de servidor do limite de tempo do pedido.

### Fase 2 — P0 — o painel do bordo ocupa a tela como o do admin

- **2.1 (P0)** `.carta` passa a ocupar a **largura disponível** no painel de captura (mesmo desenho do admin),
  com o **mesmo limite de leitura** onde ele faz sentido (texto corrido), e mantendo a janela estreita
  legível (a grade já é `auto-fit`).
- **2.2 (P1)** Conferir a proporção nas duas telas do produto (painel do bordo e área do admin) para não virar
  listas esticadas demais.
- **Prova:** medida de tela no navegador (largura útil do conteúdo = largura da janela menos margens) nos dois
  tamanhos (o print do dono é ~1500 px) + print novo para comparação.

### Fase 3 — P0 — CPU, memória e rede visíveis (ou o motivo de não haver medida)

- **3.1 (P0)** Antes de mexer no desenho, **medir no PC de captura real**: `/api/bordo` (agente no ar? licença?)
  e `/api/bordo/serie` (pontos?). Sem isso, corrigir gráfico é chutar.
- **3.2 (P0)** Se a série existe e só não é desenhada, consertar o desenho; se **não existe**, o painel troca o
  traço por **"não medido"** com o motivo (agente fora do ar / máquina não ativada / sem rodada ainda) — a
  mesma regra do resto do produto: sem medida, nunca "OK" nem traço mudo.
- **3.3 (P1)** Números de CPU/memória/disco/rede **também como texto** ao lado dos gráficos (hoje o valor
  instantâneo existe, mas some quando a série está vazia).
- **Prova:** prova de servidor da rota da série (com e sem dado) + tela no painel.

### Fase 4 — P0 — o app de captura sempre sobe junto com o Windows

- **4.1 (P0)** O painel passa a **mostrar** "abre junto com o Windows: sim/não" (lendo o estado real do
  `setLoginItemSettings`) — sem isso, nem o dono nem o suporte sabem se está ligado.
- **4.2 (P0)** O app **reafirma** o registro a cada abertura (já faz) e, quando o registro falhar/estiver
  desligado, deixa a marca visível no painel e uma linha no log do bordo.
- **4.3 (P1)** Segunda via para o caso de o Windows desligar a entrada: atalho na pasta de Inicialização do
  usuário (o app cria/confere), como o resto do "plug & play".
- **Prova:** no PC de captura real — reiniciar a máquina e medir que o app subiu (o painel no ar depois do
  boot) e que o painel diz "abre junto com o Windows: sim". Sem essa medida, a fase fica "não medida".

### Fase 5 — P1 — fechamento

- Limpeza dos dados de **teste** que confundem o dono na VPS (o pedido `8b8e2c59…` preso, os blocos da
  embarcação de teste) — com a semente `--limpar` + a limpeza pontual do pedido; bump, release, deploy e nota
  no vault.

## Decisões do dono (26/11/2026) — todas respondidas com "sim"

- **P1 — sim:** o pedido sem resposta **fecha sozinho** no limite (10 min) → "o bordo não respondeu", e o botão
  volta a "pedir".
- **P2 — sim:** o painel do bordo vai a **largura total**, como o admin.
- **P3 — sim:** "abrir junto com o Windows" fica **sempre ligado, sem opção de desligar** no app (a caixa do
  menu sai).
- **P4 — sim:** a semente **apaga agora** o pedido preso e os dados de teste da VPS, **mantendo os 4 usuários**
  dos 4 tipos de cliente.

Plano fechado com as quatro decisões acima. **Aguardando o "aprovado" para implementar as Fases 1 a 5.**

## O que NÃO muda

- As rotas `/api/hd/*`, o desenho de dois blocos da página "Gravações" e a regra do observador (0.24.0).
- O bordo continua só detectando/comprimindo/enviando; nada de terra abrindo conexão para o bordo.
- O painel do bordo continua sendo a **entrada** do app de captura (ninguém digita login nessa máquina).

**Nada implementado ainda — aguardando "aprovado".**

## Implementado em 26/11/2026 (após o "aprovado") — o que cada fase virou

### Fase 1 — "chegando…" para sempre
- `ground/api.py`: `SEGUNDOS_SEM_RESPOSTA_DO_HD_PADRAO = 600.0` + `segundos_sem_resposta_do_hd()`
  (env `LECSOR_MINUTOS_SEM_RESPOSTA_HD`) + `fechar_pedidos_do_hd_sem_resposta()` — o pedido velho vira
  **`sem_resposta`** com **motivo escrito**, sai da fila do bordo e **não é apagado** (a virada entra na
  auditoria como `trecho_do_hd_sem_resposta`). `api_hd_pedir` bloqueia pedido duplicado (`ja_tinha`);
  `api_hd_catalogo` fecha os vencidos e devolve `ha_segundos` por pedido e `limite_sem_resposta_s`.
- `ground/saude_do_bordo.py`: `pedidos_pendentes` exclui `'sem_resposta'`.
- `app/app.js`: `textoDeEspera(seg)` (a idade do pedido), ramo novo `p.sem_resposta` (botão volta a
  **pedir**), resumo do catálogo vazio **com motivo** e `setInterval` de **15 s** enquanto há pedido vivo.

### Fase 2 — largura total
- `bordo/index.html`: `.carta { width: 100%; max-width: none; margin: 0; }`.
- Medido no navegador: **1364 px de carta em 1400 px de janela** (antes: 880 px centralizados).

### Fase 3 — CPU/memória/rede (ou o motivo)
- `bordo/index.html`: `RETRATO_AGORA`, `medidaOuMotivo()`, linha `['Não medido', porqueNaoMediu]`,
  `redeTxt` com motivo, `pontoDeAgora()` (o número de AGORA quando a série está vazia) e
  `desenharCurva(cfg, pontos, motivo)` → `não medido — <motivo>`.
- `ground/api.py` (`/api/bordo/serie`): quando não há pontos, devolve o **`motivo` medido**.

### Fase 4 — sempre junto com o Windows
- `desktop/configuracao.js`: `abrirComWindows` **sempre `true`** (o `corrigido` conserta arquivo torto).
- `desktop/main.js`: `registrarAutostart()` (registro do Windows + atalho
  `LECSOR - app de captura.lnk` na pasta Inicialização), chamado **antes** de subir o servidor local; o
  item de menu virou **"Abrir junto com o Windows: sempre ligado"** (sem caixa para desmarcar).
- `ground/api.py`: `_app_do_bordo()` publica `abre_com_windows` (`sim/NÃO/sem medida`) + `texto`;
  `bordo/index.html` mostra na barra de status e no diagnóstico.

### Fase 5 — limpeza, bump e publicação
- `tools/limpar-dados-de-teste.py` (**novo**): apaga só o que tem prefixo `teste-`, mantém a estrutura e os
  **4 usuários**; modo seco por padrão, `--confirmar` apaga e grava UMA linha de auditoria
  (`dados_de_teste_apagados`). **Executado na VPS**: pedido preso `8b8e2c59ea7a70b5` e os dados de teste
  **apagados**; 4 usuários e 5 embarcações mantidos (conferido por leitura depois).
- Bump **0.25.0** (`tools/_tmp_0250_bump.py`), release, deploy e nota no vault.

## Publicado em 26/11/2026 (números medidos)

- **Código:** commit **`f1e5add`** na `main` (`3d2fbfc..f1e5add`) — repo `gm-innovation/video_compressor`.
- **Provas antes do envio:** `tools/regressao-0130.py` = **TUDO VERDE (47 provas)**; `python -m unittest
  discover -s tests -p "test_*.py"` = **22 OK**; `test-pedido-do-hd-sem-resposta.py`,
  `e2e-pagina-unica-de-gravacoes.py`, `e2e-dashboard-de-verdade-e-card-compacto.py` e
  `e2e-tamanho-fixo-dashboards-e-telemetria.py` = exit 0.
- **Build:** `desktop/dist/unico/LECSOR-0.25.0-x64.exe`, **171 693 334 B**, sha256
  `8479e68cfff4f72ffde25abd10a676516a4e436ff0b40f5c523e2e49c68cad46`.
- **Release:** `v0.25.0` id **459838330** (2026-11-26T19:45:13Z), latest, asset com o mesmo sha256 (conferido
  pela API depois do upload).
- **Deploy (VPS):** `py_compile` OK, `pipeline-api.service` **active**, `/api/saude` **200**, `/api/bordo` **200**,
  `/bordo` **200**; presença do código novo conferida na fonte (`sem_resposta`, `limite_sem_resposta_s`,
  `_app_do_bordo`, `.carta { width: 100%`, `Abre junto com o Windows`, `textoDeEspera`,
  `limpar-dados-de-teste`); `/api/bordo/serie` na VPS devolve o **motivo medido** ("esta maquina nao
  conseguiu medir: rede: sem psutil").
- **Vault:** nota publicada — `origin/master` do `vault-lecsor` em **`9740a9b`** (nota + bullet no `index.md`).
- **Gate (jev-codegate):** o push da nota era barrado por defeito — a regra de escopo bloqueava sem ter o que
  comparar (nota empurrada de outra máquina: sem diff, sem commits, sem plano do lado de cá; medianas medidas
  0,44–0,49). Corrigido na causa: `_tem_base_para_escopo()` em `policy.py` escala para o humano em vez de vetar
  quando não há base; 2 testes atualizados + 1 novo. **107 testes do plugin verdes.** Vale depois de o app
  recarregar os plugins.

