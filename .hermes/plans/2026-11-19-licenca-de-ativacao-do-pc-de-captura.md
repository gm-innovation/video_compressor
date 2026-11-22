# Licença de ativação do PC de captura (chave digita o vínculo com empresa e embarcação)

Pedido do dono (19/11/2026, VERBATIM): *"vamos fazer assim então, quero apenas instalar o app no computador
de captura, inserir a chave da licença e assim fazer a conexão com a empresa e embarcação cadastradas, e a
licença pode ser configurável por tempo ou indeterminado"*.

**Estado:** APROVADA pelo dono ("prossiga", 19/11/2026) e IMPLEMENTADA nesta rodada (0.10.0).
As decisões dele estão na tabela D1–D5 do fim deste arquivo. O resultado, as provas e o que ficou aberto
estão no runbook `20-runbooks/2026-11-19-licenca-de-ativacao-do-pc-de-captura-0.10.0.md` do vault.

## O problema, medido (não suposto)

- Hoje o PC de captura é preso à embarcação **no build**: `desktop/ambiente.json` (chaves
  `LECSOR_SUPABASE_URL`, `LECSOR_SUPABASE_ANON_KEY`, `LECSOR_TOKEN_INGESTAO`, `LECSOR_EMBARCACAO`,
  `LECSOR_LADO_TERRA_API`) é copiado para `resources/servidor/ambiente.json` dentro do pacote. O log do app
  instalado comprova: *"embarcacao bancada · lado terra http://187.127.60.250:8085"*.
- O lado terra valida o token **comparando com a variável de ambiente dele** (`LECSOR_TOKEN_INGESTAO`,
  `ground/api.py`, várias rotas) — é **um token só** para todos os bordos, e **não existe** rota que cunhe
  token por barco, nem tela de token no painel do admin.
- Consequência prática que o dono sentiu: para cada barco novo é preciso **gerar um `ambiente.json` e
  construir outro instalador** — nada de "instalar e digitar uma chave".

## O que o dono quer

Instalar o **mesmo** instalador no PC de captura → **digitar a chave da licença** → o app se conecta à
**empresa e embarcação já cadastradas** no admin, sem build por barco. A licença tem **validade por tempo**
ou **indeterminada**.

## Desenho proposto

### A chave
- Formato **`XXXX-XXXX-XXXX-XXXX`** (4 grupos de 4), alfabeto **Crockford base32 sem ambíguos** (sem `0`, `O`,
  `1`, `I`, `L`) → 16 caracteres ≈ **80 bits** de entropia, digitável pelo dono e por telefone.
- No banco fica **hash** (sha256) + os **4 últimos** caracteres, nunca a chave inteira; a chave **não** entra
  em log, nem em auditoria, nem em resposta de listagem. (Mesma regra da credencial de câmera.)

### Tabela nova `licencas` (migration `db/schema-fase7.sql`)
| Coluna | Para quê |
|---|---|
| `id` | identificador |
| `chave_hash`, `chave_ultimos4` | a chave sem guardar a chave |
| `embarcacao_id` | o vínculo que o dono pediu (empresa sai de `embarcacoes.cliente_id`) |
| `validade_tipo` (`indeterminada` \| `ate`), `validade_em` | "por tempo ou indeterminado" (VERBATIM) |
| `maquinas_max` | quantos PCs daquele barco a licença libera |
| `status` (`ativa` \| `revogada`), `revogada_em`, `motivo` | revogação |
| `criada_por`, `criada_em`, `ultimo_uso_em`, `ultima_maquina` | quem emitiu e o que usou |

### Fluxo de ativação (app → terra, sempre no sentido que o dono fixou)
1. Instala o app (pacote **um só**, sem `ambiente.json` por barco).
2. No primeiro uso, a tela **"Chave da licença"** pede a chave.
3. `POST /api/licenca/ativar` (app → terra) com `{chave, maquina}`; `maquina` = impressão estável da máquina
   (hostname + hash do MAC), para contar máquinas sem identificar pessoa.
4. Terra responde `{ok, embarcacao_id, embarcacao_nome, cliente_nome, validade_em, maquinas_usadas}`.
5. O app grava isso no próprio `userData` e segue o fluxo normal (varredura, cadastro, saúde).
6. Revalidar no laço que já existe (o app já busca config e publica saúde): licença **expirada** ou
   **revogada** → o app para de transmitir e mostra o motivo; **máquina a mais** que o `maquinas_max` → recusa
   a ativação com o texto do que fazer.

### O que NÃO muda
- O `token` de ingestão continua sendo a credencial de transporte do bordo, e o bordo continua **só
  enviando** (nenhuma porta aberta em bordo).
- O admin continua criando **empresa** (`POST /api/clientes`) e **barco** (`POST /api/embarcacoes`).
- Instalações que já existem com `ambiente.json` continuam funcionando (a licença é **adicional**).

## Fases (P0/P1/P2 dentro de cada fase)

### Fase 1 — Banco e painel do admin (licença nasce e morre no controle do dono)
- **P0** `db/schema-fase7.sql` com `licencas` + trilha em `auditoria_acesso`; migração idempotente no
  `inicializar()` (banco novo já nasce certo e banco que atualiza se conserta sozinho).
- **P0** rotas `POST /api/licencas` (gera com validade indeterminada **ou** data), `GET /api/licencas`
  (lista com validade, uso, `maquinas_max` e a **chave inteira para o admin ver/copiar** — decisão D4),
  `POST /api/licencas/<id>/revogar`. **Só admin** (não-admin: 403, sem a chave).
- **P0** tela "Licenças" no `admin/admin.js`: gerar, copiar a chave **uma vez**, ver validade/uso, revogar.
- **P1** `POST /api/licencas/<id>/reemitir` (chave nova, mesmo vínculo) e prorrogar validade.
- **P2** filtro por barco e um resumo de licenças vencendo.
- **Aceite:** admin gera licença para uma embarcação e consegue **ver/copiar a chave inteira** depois; um
  não-admin recebe 403 e **nunca** recebe a chave; a chave **não** entra em log nem na auditoria.

### Fase 2 — Ativação no app de captura (o que o dono pediu: instalar e digitar a chave)
- **P0** `POST /api/licenca/ativar` no terra (valida existência, `status`, validade, `maquinas_max`) e grava
  `ultimo_uso_em`/`ultima_maquina`.
- **P0** tela "Chave da licença" no app (primeiro uso; e no menu para trocar/reativar), com máscara
  `XXXX-XXXX-XXXX-XXXX`, sem senha de ninguém e sem credencial de câmera.
- **P0** o app passa a tirar **embarcação** (e o que mais o terra devolver) **da licença**, guardado no
  `userData`; `LECSOR_EMBARCACAO` deixa de ser obrigatório no pacote.
- **P1** o pacote deixa de levar o `ambiente.json` por barco (fica só o endereço do lado terra + a chave
  pública do Supabase, que não é segredo) e o build para de exigir `desktop/ambiente.json`.
- **P2** tela de estado da licença (ativo, vence em X dias, revogada) e "trocar chave" sem reinstalar.
- **Aceite:** instalação limpa, sem nenhuma configuração de barco no pacote, ativa com a chave e aparece na
  tela do cliente com as câmeras daquele barco.

### Fase 3 — Validade, revogação e máquinas
- **P0** revalidação no laço do app: `indeterminada` nunca vence; `ate` vence na data; revogada corta.
  Vencida/revogada → o app **para de transmitir** e diz o motivo na tela (não fica mudo).
- **P0** contagem de máquinas por licença (`maquinas_max`), com recusa explicada quando estoura.
- **P1** aviso ao admin antes de vencer (X dias) no painel de licenças.
- **P2** tolerância a ficar sem internet (o bordo no mar não pode parar por 1 dia de Starlink — decisão D2).
- **Aceite:** licença com validade no passado não ativa; licença revogada corta a transmissão no ciclo
  seguinte; a 2ª máquina do mesmo barco ativa quando `maquinas_max ≥ 2`.

### Fase 4 — Provas
- **P0** `tests/test-licenca-de-ativacao.py` (HTTP de verdade): ativar com chave válida; chave errada → 404/422
  sem dizer se existe; licença vencida → recusa; licença revogada → recusa; `maquinas_max` estourado → recusa
  com o texto do que fazer; o **admin** recebe a chave inteira e um **não-admin não recebe**.
- **P0** `tests/e2e-licenca-no-admin.py` (Chromium): gerar, copiar uma vez, revogar, e o aviso de validade.
- **P0** `tests/e2e-app-ativado-por-licenca.py` (Chromium no app): tela da chave → ativa → o app mostra o
  barco certo e as câmeras daquele barco, sem `ambiente.json` de barco no pacote.
- **P1** `tests/test-licenca-nao-vaza.py`: varre arquivos de log gerados na rodada e falha se a chave
  aparecer em texto.
- **P2** isolar empresa: licença do barco A não enxerga câmera do barco B (nem de outra empresa).

### Fase 5 — Publicar
- **P0** versão **0.10.0** (`desktop/package.json`, `tools/publicar-releases.py`, `README.md`), build,
  publicação e conferência na fonte (tamanho + digest iguais + link 302) — o runbook já existe.
- **P0** deploy do lado terra na VPS (rotas novas + migração) e prova por rota viva.
- **P1** runbook no vault + `index.md` + nota no projeto (`10-projetos/pipeline-video.md`).
- **P2** texto pronto para o dono colar em campo (instalar → digitar a chave).

## Decisões que preciso do dono (posso decidir sozinho se você não quiser escolher)

| # | Pergunta | Resposta | Efeito no desenho |
|---|---|---|---|
| D1 | Quantos PCs por licença? | **AJUSTÁVEL** (dono, 19/11/2026) | `maquinas_max` é campo da licença, editável na tela do admin; **a licença é por EMBARCAÇÃO**, não por PC |
| D2 | Sem internet por muito tempo, o bordo para? | **MANTÉM TUDO NORMALMENTE** (dono, 19/11/2026) | **não** existe prazo de tolerância nem corte por falta de internet: o bordo segue capturando/gravando/enviando; o corte acontece só por **vencimento** ou **revogação**, e só quando o app consegue falar com o lado terra (sem internet ele nem sabe que venceu — e não para) |
| D3 | O token de ingestão continua único? | **CONTINUA ÚNICO** (dono, 19/11/2026) | a licença decide só o **barco**; o token de ingestão segue sendo a credencial de transporte que já existe (uma variável de ambiente no lado terra) |
| D4 | O admin vê a chave inteira depois? | **SIM, SEMPRE** (dono, 19/11/2026) | a chave fica **recuperável** para o **admin** (ver e copiar na tela quando quiser) — então o banco guarda a chave, não só o hash; mitigação: só o admin lê, nunca vai para log/auditoria, e revogar/reemitir corta na hora |
| D5 | Licença por barco ou por PC? | **RESOLVIDA por D1** | por **embarcação**, com número de PCs ajustável |

## Riscos

- **Chave fraca/colidida:** 80 bits; teste de chave errada não pode revelar se a chave existe.
- **Chave recuperável (D4):** como o admin pode ver a chave de novo, ela fica guardada no banco do lado terra
  — então (a) só o admin lê, (b) nunca vai para log/auditoria/resposta de não-admin, (c) revogar/reemitir
  corta na hora. É uma chave de **produto** revogável, não uma senha de câmera.
- **Bordo ficar sem falar por licença vencida:** precisa ser **visível** (tela) — bordo mudo é problema, regra
  já fixada na 0.8.0.
- **Segredo no pacote:** com a licença, o pacote deixa de levar `LECSOR_EMBARCACAO`/token por barco; o que
  sobrar precisa ser público (URL do terra + chave anon do Supabase).
- **Retrocompatibilidade:** instalação antiga com `ambiente.json` continua valendo (nada é apagado).

## Critério de aceite do dono

Instalar o app num PC de captura **sem nada configurado**, digitar a chave `XXXX-XXXX-XXXX-XXXX`, e o app
aparecer conectado à **empresa e embarcação certas**, com licença **por tempo** ou **indeterminada** — sem
gerar `ambiente.json` nem build por barco.

## Status da execução (rodada 0.10.0)

- **Código:** `ground/licenca.py` (chave `XXXX-XXXX-XXXX-XXXX`, Crockford base32 ~80 bits, sem `I`/`O`),
  `db/schema-fase7.sql` (`licencas` + `licenca_usos`, chave recuperável para o admin), `licenca/index.html`
  (a tela que o PC de captura mostra), rotas `/api/licenca`, `/api/licenca/ativar`, `/api/licencas` (admin)
  em `ground/api.py`, e o app abrindo a tela da chave quando ainda não há licença (`desktop/main.js`).
- **Provas novas (todas verdes):** `test-licenca-de-ativacao.py`, `test-licenca-do-bordo.py`,
  `test-licenca-nao-vaza.py`, `test-licenca-isola-embarcacao.py`, `e2e-licenca-no-admin.py`,
  `e2e-app-ativado-por-licenca.py`, e a prova viva no lado terra de produção
  (`tests/prova-viva-licenca-no-terra.py`, roda na VPS) — 11 verificações.
- **Regressão curada:** `tools/regressao-0100.py`.
- **Achado no caminho (corrigido):** o agente de ordens escreve o estado em `<raiz>/ordens/`, mas o módulo
  de saúde lia `<raiz>/ground/agente-vivo.json` — numa máquina trabalhando a tela do admin dizia "o agente
  nunca escreveu o estado". Agora a saúde pergunta o caminho ao próprio agente (`caminho_do_vivo()`), com
  prova em `tests/e2e-saude-do-bordo-no-admin.py`.
- **Aberto:** teste manual no PC de captura de verdade (instalar → digitar a chave → ver câmeras do barco);
  e a decisão D1 sobre o papel `tecnico` (não muda a licença).
