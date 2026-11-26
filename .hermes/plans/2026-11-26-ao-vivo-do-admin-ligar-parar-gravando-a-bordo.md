# Plano — Ao vivo do admin: ligar/parar a câmera, indicador "gravando a bordo" e fim da tela "Imagens gravadas a bordo"

- **Data:** 26/11/2026
- **Estado:** **APROVADO pelo dono (26/11/2026, "aprovado") e IMPLEMENTADO — entra como 0.23.0** (2.A + botão ligar/desligar + indicador).
- **Rodada prevista:** 0.23.0 (após a 0.22.0, `a96fcd1`, publicada)

## Pedido do dono (verbatim, 26/11/2026)

> "eu devo poder ligar e parar a câmera também, 'imagens gravadas a bordo' não faz sentido, só preciso no monitoramento saber se está sendo gravado a bordo, não preciso ver as imagens"

E, no mesmo fio:

> "mas não são as imagens gravadas, é ao vivo, preciso poder selecionar a empresa>embarcação>câmera"

Print anexado: tela **Ao vivo — Bancada de testes (própria) (0 de 4 no ar)**, com o aviso "somente leitura: aqui não se liga, não se para e não se grava", seletor Empresa/Embarcação, 4 câmeras marcadas e 4 células com "sem imagem: o bordo só transmite com alguém assistindo — nenhum cliente na sala".

## O que está no ar hoje (verificado no código)

1. **"Imagens gravadas a bordo"** (`admin/admin.js:302` legenda, `:390` despacho, `:3285` `telaHdDoBordo`): o admin escolhe a embarcação e lê o **catálogo do HD do bordo** pelas rotas `/api/hd/catalogo|pedir|baixar`. O catálogo é publicado **pelo bordo** (`ground/agente_de_ordens.py:376 publicar_catalogo`) e **só quando a gravação contínua está ligada** (`if not g or not g.ligada(): return`). As MESMAS rotas servem o **cliente** ("Radar de óleo (HD)", `app/app.js:1475`) e o **observador** (Petrobras/IBAMA).
2. **Ao vivo do admin** (`admin/admin.js:2148-2163` `abrirAoVivo`, caixa `#ao-vivo`): seletor **Empresa** (`#av-empresa`) → **Embarcação** (`#av-emb`) → câmeras daquela embarcação em **caixa de marcação** (`#av-cameras`), e a grade desenha as marcadas. É **somente leitura** — e `/api/transmissao/iniciar` devolve **403 "quem inicia a transmissao e' o cliente"** (`ground/api.py:4920-4925`).
3. **Ligar/parar hoje existe para:** (a) o **cliente**, por sessão viva (`iniciar`/`batimento`/`encerrar`, `app/app.js:1265`); e (b) a **operação**, só para **DESLIGAR na mão** (`desejo_camera.manual='parar'` vence a sessão do cliente; o `manual='ligar'` foi extinto na D3 — `ground/api.py:2018-2022`).
4. **"Gravando a bordo" NÃO está medido em terra:** a coluna existe (`estado_bordo.gravando`), a árvore do painel já a expõe (`ground/api.py:1209` → `estado.gravando`), **mas o agente do bordo não manda `gravando`** no `POST /api/estado-real` (`ground/agente_de_ordens.py:325-333` monta `reais` só com `estado`/`motivo`/`fluxo_id`/`desde`) → em terra o valor é sempre "0". Ou seja: **não medido**, e não "desligado".

## Fase 1 — P0 — Tirar "Imagens gravadas a bordo" da área do admin

- **1.1 (P0)** Remover a aba do admin: o item de menu, a legenda `hd_bordo` (`admin/admin.js:302`) e o despacho `hd_bordo: telaHdDoBordo` (`:390`); a função `telaHdDoBordo` (`:3285`) sai.
- **1.2 (P0)** **NÃO tocar nas rotas `/api/hd/*`** — são do cliente ("Radar de óleo (HD)") e do observador (Petrobras/IBAMA). Provar que continuam verdes.
- **1.3 (P1)** Tirar `hd_bordo` de `TELAS_DE_FORMULARIO` (`admin/admin.js:115`) e limpar o CSS órfão da tela.
- **Prova:** teste novo que abre o admin, varre o menu e **falha se "Imagens gravadas a bordo" voltar a existir**; o e2e do cliente/observador segue verde.

## Fase 2 — P0 — O admin liga e para a câmera no ao vivo — **DECIDIDO: 2.A**

- **Desenho escolhido pelo dono (26/11/2026): "2.A — o admin é plateia, como o cliente":** `/api/transmissao/iniciar` passa a aceitar admin/operador/tecnico; a sessão é **do admin** (com batimento e `encerrar`); ao fechar a tela, a câmera para — a mesma regra do cliente. Mantém viva a regra de ouro ("o bordo só transmite com alguém assistindo") e a auditoria (`transmissao_pedida`) registra quem ligou.
- **2.B (descartado):** devolver o `ligar` ao `desejo_camera.manual` para ligar mesmo sem plateia — muda a regra sem-plateia/D3; **não será feito**.
- **2.x (P0)** Na tela `#ao-vivo`, cada célula de câmera ganha **▶ ligar / ■ parar** (`data-papel`), com o estado vindo do que o bordo conta (nunca de suposição).
- **Prova:** e2e — o admin liga no ao vivo → `POST /api/transmissao/iniciar` **201** → o bordo conta `no_ar` → a célula mostra imagem; o admin para → sessão encerrada; a **Auditoria** mostra o e-mail do admin.

## Fase 3 — P0 — No monitoramento, SÓ o indicador "gravando a bordo"

- **3.1 (P0)** O bordo passa a contar `gravando` no `reais` (`ground/agente_de_ordens.py:325-333`): verdade = `gravacao_continua.resumo()["ligada"]` da câmera do radar + o gravador da própria sessão. **Sem leitura ⇒ não reporta** (o terra escreve "não medido", nunca "desligado").
- **3.2 (P0)** O terra guarda (`estado_bordo.gravando`, já existe) e o **cartão da frota** mostra o selo **"gravando a bordo"** por câmera (a árvore já entrega `estado.gravando`).
- **3.3 (P0)** Sem retrato do bordo ⇒ a tela escreve **"não medido"** (regra dura da casa: sem medida, nunca "OK").
- **Prova:** teste que injeta `POST /api/estado-real` com `gravando: true` e exige o selo no dashboard; e o caso "sem retrato" ⇒ "não medido".

## Fase 4 — P1 — **CONFIRMADO NO ESCOPO** — o admin liga/desliga a gravação contínua do radar (botão) **+** o indicador

Escolha do dono (26/11/2026): "sim, botão ligar/desligar + indicador". A chave `gravacao_continua` existe (`ground/api.py:906`), mas o `aplicar_config` do agente **só tem ramo `transmitir`** — a chave **não chega ao bordo**. Aqui: o **admin publica a chave** e o **bordo OLHA e aplica** (o terra nunca abre conexão para o bordo), com auditoria de quem ligou/desligou; o **indicador** é o da Fase 3.

## Fase 5 — P2 — Limpeza e publicação

`hd_bordo` fora de `TELAS_DE_FORMULARIO`/`RUIDO_TELA`; CSS órfão fora; regressão reconferida; runbook + bullet na vault; **bump 0.22.0 → 0.23.0**; release; deploy na VPS; verificação ao vivo (`/api/saude` 200, `/admin/` 200).

## O que foi feito (26/11/2026 — a rodada implementada)

1. **Fase 1** — `telaHdDoBordo`, o item de menu `hd_bordo`, a legenda e o `<option>`/aba do `admin/index.html` **saíram** (`tools/_tmp_0230_tira_hd.py`, idempotente). As rotas `/api/hd/*` **ficaram** (cliente e observador) — provado.
2. **Fase 2 (2.A)** — bloco do ao vivo trocado (`tools/_novo_ao_vivo.js` + `tools/_tmp_0230_ao_vivo.py`): `ligarCameraNoAdmin` abre a MESMA sessão do cliente (`/api/transmissao/iniciar` agora aceita admin/operador/tecnico), `pararCameraNoAdmin` encerra a sessão deste admin (ou o stand-by da operação), batimento a cada 10 s e `pagehide` → `encerrar {pendente:true}`; `/api/transmissao/iniciar` **não** bloqueia mais o admin no stand-by manual; a Auditoria grava `transmissao_pedida … — operacao`; o motivo do encerramento diz "pela operacao (admin)".
3. **Fase 3** — coluna `estado_bordo.gravando_medido` (schema + `ALTER TABLE` na migração), `gravando_medido` no INSERT/SELECT/árvore, `_gravando_a_bordo(cam)` no agente (o bordo só conta `gravando` quando MEDIU), `gravando_a_bordo`/`gravacao_medida` no resumo da frota e o selo no cartão da frota + na janela do ao vivo (**"não medido"** quando não houve medida).
4. **Fase 4** — `gravacao_continua` é chave **da embarcação** (recusa `camera_id`; valor 0/1); `aplicar_gravacao_continua()` no bordo escreve o DESEJO em `ligada.txt` do HD e garante/derruba o gravador; **botão no cartão da embarcação** com a nota do que o bordo aplicou.
5. **Fase 5** — bump 0.23.0 (`tools/_tmp_0230_bump.py`), release e deploy.

**Achado na prova de tela (corrigido):** um repintar da releitura de 5 s reconstruía a janela e oferecia **"ligar" de novo** mesmo com a sessão deste admin viva — clicando, abria-se uma **segunda sessão** para a mesma câmera. Agora `pintaGrade` consulta `SESSAO_AO_VIVO` e a célula continua **"■ parar"** com a nota "aguardando o bordo ligar a câmera — você já pediu".

**Testes antigos ajustados à verdade nova (não afrouxados):** `e2e-tamanho-fixo-dashboards-e-telemetria.py` (a tela do admin **deixou** de ser "somente leitura": agora cobra um ligar/parar por célula e nenhum controle de gravar) e `e2e-config-do-bordo-vinda-de-terra.py` (a recusa com motivo agora usa o caso real: a chave da gravação é aceita e o bordo explica que não há dispositivo de vídeo). `tests/e2e-hd-do-admin.py` **saiu** (a tela que ele media não existe mais).


## Decisões do dono (26/11/2026)

1. **Fase 2:** **2.A** — o admin é plateia, como o cliente (a câmera para quando ele fecha a tela).
2. **Fase 4:** **botão** de ligar/desligar a gravação contínua do radar **+** o indicador.

## Critério de pronto

Regressão + unittest + e2e novos **verdes**; admin **sem** a aba "Imagens gravadas a bordo"; ao vivo do admin **com ligar/parar**; selo **"gravando a bordo"** no monitoramento (ou "não medido"); VPS na versão nova; vault atualizada.
