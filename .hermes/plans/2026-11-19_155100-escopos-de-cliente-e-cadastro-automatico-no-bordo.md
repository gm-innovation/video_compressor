**Status:** aprovado (19/11/2026) — as 5 fases autorizadas; em implementação.

# Escopos de cliente (1/2/3/4) e cadastro automático das câmeras pelo app de captura

**Goal:** o app de captura, ao subir, varre os dispositivos plugados naquela máquina, cadastra cada
câmera/radar localmente na embarcação que ele já traz de fábrica e publica esse cadastro no lado terra; e
o acesso do cliente passa a ter os quatro escopos pedidos pelo dono (uma embarcação, algumas, todas da
empresa, todas de todas as empresas — Petrobras).

**Base:** 0.8.0 (`d679ade` Fase 5, `509e700` regressões, `9f952af` plano) · **Data:** 19/11/2026
**Dono (19/11/2026):** "cada app já deve ter seu id cadastrado no banco com o nome da empresa e
embarcação, quando instalado em um computador de captura em nosso laboratório, assim, quando ele
reconhecer as câmeras/radar, ele envia essas informações das câmeras para o banco que já tem id, empresa e
embarcação, nós fazemos a configuração e o cadastro dos usuários" · "o app a bordo pode carregar já com o
início do sistema, faz a varredura das câmeras e radar, cadastra internamente, envia as informações pro
admin, o admin configura e o cliente passa a acessar na web" · "tudo bem, pode criar o que precisa no banco"

---

## Evidência (fato | como foi verificado)

| Fato | Como foi verificado |
| --- | --- |
| Não há escopo por embarcação: `usuarios` só tem `papel` + `cliente_id` | `db/schema-fase4.sql:44` e `pragma table_info(usuarios)` no `db/pipeline.db` |
| O cliente vê tudo da empresa ou nada — **tipo 3**, e só ele | `pode_ver_camera()` (`ground/api.py:138`): `PAPEL_ADMIN` vê tudo; senão compara `embarcacoes.cliente_id == usuario.cliente_id` |
| Não existe vínculo usuário↔embarcação em nenhum esquema | `grep "CREATE TABLE IF NOT EXISTS" db/schema*.sql` filtrado por usuario/embarca/acesso/escopo/permissão → só `auditoria_acesso`, `embarcacoes`, `usuarios`, `embarcacoes_supabase` |
| **Tipo 4** hoje só é alcançável por `operador`/`admin` — que também operam e configuram | `PAPEL_ADMIN` em `ground/api.py` e o roteamento por papel (`cliente→/app`, `operador\|admin→/admin`) |
| O papel é fixo no banco por `CHECK`: `('cliente','operador','admin','tecnico')` | `db/migracao-tecnico.sql` (precedente de como se acrescenta papel: recria a tabela preservando linhas e vínculos) |
| O app **já sai de fábrica com a embarcação e o token** | `ambiente.json` da VPS: `LECSOR_EMBARCACAO=bancada`, `LECSOR_LADO_TERRA_API`, `LECSOR_TOKEN_INGESTAO` |
| O bordo **já publica** o cadastro das câmeras no boot | `_publicar_cadastro_no_boot()` (`ground/api.py:4333`), já chamado em thread no `principal()` |
| **Não existe** varredura→cadastro no boot | `listar_dispositivos()` (`ground/ingestao.py:712`) só é chamado pelas rotas de envio/dispositivos, por `prontidao_das_cameras()` e por `saude_do_bordo.py`; medido `grep` em `ground/*.py` |
| O cadastro feito na máquina de captura **é encaminhado** para terra e a linha não fica no bordo | medido com duas APIs reais: `bordo.db` sem `cam-nova`, `pipeline.db` (terra) com ela; o motivo `lado_terra.ok=false` saía do lado terra |
| Ligar o cadastro como rota local **sozinho dá 401** | medido: `/api/entrar` também é encaminhado, então a sessão do usuário de captura não existe no banco do bordo |
| O seletor de dispositivo é estável por porta USB (duas câmeras iguais convivem) | `_normalizar_dispositivo()` + comentário em `ground/ingestao.py` (`@device_pnp_...`) |
| O radar por embarcação já tem onde pendurar | `embarcacoes.radar_fonte/radar_modo/radar_taxa/radar_alvo` e `hd_catalogo` (blocos por horário, 0.7.0) |

---

## Decisões já tomadas (não se reabre)

- O bordo **não tem porta aberta**: ele só **envia** e **olha** terra (0.7.0/0.8.0).
- Quem **configura** e **dispara** é o admin e o cliente; o bordo detecta, comprime, grava o radar e
  obedece (dono, 19/11/2026).
- O app de captura carrega a identidade (empresa/embarcação) de fábrica, no `ambiente.json`.
- Nada de credencial de câmera circulando; o cadastro publicado leva só identidade (nunca `ip`/`porta`).

---

## Fase 1 — Escopos de acesso no banco (tipos 1, 2, 3 e 4)

**P0 — esquema.** `db/schema-fase6.sql` (novo) com:

    CREATE TABLE IF NOT EXISTS usuario_embarcacoes (
      usuario_id    TEXT NOT NULL REFERENCES usuarios(id),
      embarcacao_id TEXT NOT NULL REFERENCES embarcacoes(id),
      concedido_em  TEXT NOT NULL DEFAULT (datetime('now')),
      concedido_por TEXT DEFAULT '',
      PRIMARY KEY (usuario_id, embarcacao_id)
    );

e o papel de leitura global: `usuarios.papel` passa a aceitar `observador` (Petrobras), pela mesma receita
do `db/migracao-tecnico.sql` (recria a tabela preservando linhas e vínculos; roda no `inicializar()` quando
o `CHECK` antigo é visto, idempotente).

**P0 — regra única.** Em `ground/api.py`, `pode_ver_camera()` passa a ser uma só leitura de escopo:
`operador|admin` → tudo; `observador` → tudo, **só leitura** (nenhuma rota de escrita/operação aceita esse
papel); `cliente` → as embarcações concedidas em `usuario_embarcacoes`; **sem vínculo nenhum** → todas as
embarcações do próprio `cliente_id` (**tipo 3**, comportamento de hoje preservado — instalação existente
não pode perder acesso).

**P0 — tipo 4 restrito ao que o dono pediu.** `observador` (Petrobras) enxerga **radar de óleo** (catálogo
do HD e o radar ao vivo); câmera e analytics de desvio de SMS entram depois, com item próprio — **fora
deste escopo**.

**P1 — tela.** Em `admin/admin.js`/`admin/index.html`, na tela de usuários: conceder/revogar embarcações
por usuário (checkbox por embarcação, com o que está implícito pelo `cliente_id` mostrado como herdado) e o
papel `observador` como opção com aviso do que ele vê.

**P1 — trilha.** Concessão e revogação entram em `auditoria_acesso` (`escopo_concedido`/`escopo_revogado`).

**P2 — Supabase.** Espelhar `usuario_embarcacoes` no projeto do produto (migração em
`supabase/migrations/`) e na ponte de embarcações, para o Supabase não divergir do SQLite.

**Critério de aceite (por comando):** `tests/test-escopos-de-acesso.py` (novo) — matriz por HTTP: tipo 1
vê 1 embarcação e recebe 403 na outra; tipo 2 vê as concedidas; tipo 3 (sem vínculo) vê todas do
`cliente_id`; tipo 4 vê radar de duas empresas diferentes e recebe 403/405 em qualquer escrita; `rc=0`.

---

## Fase 2 — Varredura e cadastro automático no boot do bordo

**P0 — o módulo da varredura.** `ground/varredura_do_bordo.py` (novo): `varrer()` usa
`ingestao.listar_dispositivos()` (nunca inventa dispositivo: sem câmera devolve vazio com motivo), deriva o
**id** do fluxo pelo seletor estável (`@device_pnp_...`, o mesmo que permite duas câmeras iguais), separa
**câmera** de **radar** e grava a linha em `cameras` na embarcação de `LECSOR_EMBARCACAO` —
criando quando não existe e **atualizando só o que muda** (rótulo/dispositivo), sem apagar nem desativar
nada que o admin já configurou (`alvo`, `ativo`, `transmitir`). Radar: se `embarcacoes.radar_fonte` já
estiver declarado, a varredura casa com o dispositivo de captura correspondente; sem declaração, ela só
**relata** o que viu e não inventa fonte.

**P0 — gancho no boot.** Em `principal()` (`ground/api.py`), thread ao lado da
`_publicar_cadastro_no_boot`: varre → grava → publica (a publicação já existe e está provada). Nada disso
pode atrasar o boot nem derrubar a API: falha de varredura vira aviso no log e no `/api/saude`.

**P1 — re-varredura.** Repetir de tempo em tempo (mesma cadência do agente, `LECSOR_ESPERA_DA_VARREDURA`,
padrão 300 s), para pegar cabo/USB que entrou depois — sem nunca mexer no que o admin configurou.

**P1 — a tela do bordo.** `portal/index.html`: o usuário de captura passa a **ver** o que a varredura
achou (rótulo, dispositivo, embarcação) e o botão "varrer agora"; o cadastro manual continua existindo para
o que a varredura não pega.

**P2 — o relato ao admin.** O retrato da saúde (`ground/saude_do_bordo.py`, Fase 5) ganha um campo com a
varredura: quantos dispositivos vistos, quantos cadastrados, o que ficou sem cadastro e por quê.

**Critério de aceite (por comando):** `tests/e2e-varredura-do-bordo.py` (novo) — com dispositivos
simulados (`ffmpeg` de mentira na frente, o mesmo truque já usado nas provas de dshow): a API sobe, a linha
aparece em `cameras` na embarcação do `ambiente.json`, o cadastro chega ao lado terra (`lado_terra.ok`), e
**configuração do admin não é sobrescrita** por uma segunda varredura; `rc=0`.

---

## Fase 3 — O cadastro do bordo não se perde (defeito medido)

**P0 — o cadastro é da máquina de captura.** `POST /api/cameras` deixa de ser encaminhado quando o pedido
vem da **própria máquina** e quem pede é o usuário de captura: a linha nasce no banco do bordo (com o
dispositivo em `config_local`) e a publicação para terra é a que já existe. `operador|admin` remoto segue
como hoje.

**P0 — a sessão do usuário de captura existe no bordo.** `/api/entrar`, `/api/eu` e `/api/sair` passam a
ser atendidos **localmente** na máquina de captura (é a máquina onde o usuário está sentado), com os
usuários que o admin já criou para ela — sem isso, a rota local responde 401 (medido) e o app do bordo não
tem como autenticar ninguém.

**P1 — publicar continua obrigatório.** Depois de cadastrar localmente, a publicação para terra é tentada
e o resultado aparece na tela e na saúde do bordo — cadastro local sem publicação é câmera invisível para
o cliente, e isso precisa ser dito, não escondido.

**P2 — pendência declarada no plano da 0.8.0.** Ao fechar esta fase, a "Pendência medida em 19/11/2026" do
plano `2026-11-19_122022-...` é atualizada com o que passou a valer.

**Critério de aceite (por comando):** `tests/test-fluxo-no-lado-terra.py` (existente, hoje verde) mais um
caso novo no mesmo arquivo: câmera **nova** cadastrada na máquina de captura existe **no bordo E em terra**
(`bordo.db=1`, `pipeline.db=1`); `rc=0`.

---

## Fase 4 — Petrobras: radar de óleo das duas empresas (tipo 4 de ponta a ponta)

**P0 — leitura global só do radar.** Com o papel `observador`, o acesso do tipo 4 enxerga o catálogo do HD
do radar e o radar ao vivo de **todas** as embarcações, de todas as empresas, e nada mais (câmera e
analytics ficam fora até o dono pedir).

**P0 — a tela do observador.** `app/` ganha a visão de observador: lista de embarcações → radar (ao vivo e
os blocos por horário do `hd_catalogo`), com o mesmo caminho de pedido de trecho já provado na 0.7.0 e sem
nenhum botão de configuração ou transmissão.

**P1 — prova com duas empresas.** O teste da Fase 1 cobre o caso Petrobras; esta fase acrescenta a prova de
tela (Chromium): o observador vê radar de duas empresas e **não** vê câmera nenhuma.

**P2 — futuro declarado (fora deste escopo).** Câmeras com analytics de desvio de SMS para o observador
entram como fase própria quando o dono pedir.

**Critério de aceite (por comando):** `tests/e2e-observador-do-radar.py` (novo) `rc=0`, mais a matriz de
permissões atualizada em `docs/matriz-de-permissoes-0.8.0.md`.

---

## Fase 5 — Publicar

**P0 — pacote e release:** `desktop/package.json` → `0.9.0`, `tools/publicar-releases.py`
(`VERSOES_PUBLICADAS` + `NOTAS`), `README.md`, build dos instaladores, release no GitHub (só funciona com
`export GH_TOKEN=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill | sed -n 's/^password=//p')`).

**P0 — subir para a VPS:** `scp` dos arquivos alterados + `systemctl restart pipeline-api.service`; conferir
`/api/saude` 200, `/app/` 200, `/api/cameras` 401 sem sessão e a criação de `usuario_embarcacoes`.

**P1 — runbook no vault:** nota em `~/.hermes/vault-arrow/20-runbooks/` + `index.md` + push
(`git push https://github.com/gm-innovation/vault-lecsor.git HEAD:master`).

**Critério de aceite (por comando):** regressão da suíte com todos os `rc=0` na lista curada (as provas da
0.7.0/0.8.0 mais as novas), release listada na API do GitHub com o sha256 do `.exe`, VPS ativa.

---

## Files likely to change

- `db/schema-fase6.sql` (novo) — `usuario_embarcacoes` + papel `observador`
- `db/migracao-observador.sql` (novo) — recriação de `usuarios` preservando linhas (receita do `migracao-tecnico.sql`)
- `ground/varredura_do_bordo.py` (novo) — `varrer()`, casamento de dispositivo, missão do radar
- `ground/api.py` — `pode_ver_camera()` por escopo; rotas locais de `/api/entrar`, `/api/eu`, `/api/sair`;
  `POST /api/cameras` local para quem está na máquina; gancho da varredura no `principal()`; rotas do
  observador
- `ground/ingestao.py` — reaproveitar `listar_dispositivos()`/`_normalizar_dispositivo()` (sem reescrever)
- `ground/saude_do_bordo.py` — o campo da varredura no retrato
- `admin/admin.js`, `admin/index.html` — conceder/revogar embarcação por usuário; papel `observador`
- `portal/index.html` — "varrer agora" e a lista do que a varredura achou
- `app/app.js`, `app/index.html` — visão do observador (radar das duas empresas)
- `tests/test-escopos-de-acesso.py`, `tests/e2e-varredura-do-bordo.py`, `tests/e2e-observador-do-radar.py`
  (novos); `tests/test-fluxo-no-lado-terra.py` (caso novo)
- `docs/matriz-de-permissoes-0.8.0.md` → `docs/matriz-de-permissoes-0.9.0.md`
- `.hermes/plans/2026-11-19_122022-config-do-bordo-vinda-de-terra-e-usuario-so-de-captura.md` — pendência
  medida passa a "resolvida na Fase 3"

## Riscos e limites (declarados)

- **`usuario_embarcacoes` vazia = tudo da empresa** (tipo 3). É o que protege a instalação que já existe;
  se o dono preferir "vazia = nada", isso é decisão dele e muda a Fase 1.
- **Papel novo mexe no `CHECK` da tabela `usuarios`** — a recriação preserva linhas e vínculos, mas é
  migração de banco: roda com o serviço parado e fica provada no `inicializar()`.
- **Varredura automática não pode brigar com o que o admin configurou**: ela só cria e atualiza
  rótulo/dispositivo; `alvo`, `ativo` e `transmitir` nunca são tocados por ela.
- **Dispositivo `@device_pnp_` muda de sufixo se a câmera trocar de porta USB** — o id derivado cai e a
  câmera aparece como nova; tratar como caso conhecido (a tela mostra o que ficou sem cadastro).
- **Tipo 4 hoje é só radar**: câmera e analytics de desvio de SMS para a Petrobras **não** entram aqui.
- **Não medido**: se o Supabase do produto tem (ou terá) noção de escopo por embarcação — não verifiquei;
  a Fase 1 P2 espelha o que o SQLite decidir.
- **Não medido**: comportamento da varredura no PC de captura real (bancada de laboratório não tem as
  quatro câmeras nem o radar); a prova é com dispositivo simulado, como nas fases anteriores.
