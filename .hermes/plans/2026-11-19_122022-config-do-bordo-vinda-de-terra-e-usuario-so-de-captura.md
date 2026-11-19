# Cadastro no banco, configuração do bordo vinda de terra e usuário só de captura

**Status:** APROVADO pelo dono em 19/11/2026 — as 4 decisões pendentes ficam como propostas aceitas (dono: "você é o especialista")

**Situação (19/11/2026):** **Fase 1 implementada, provada e publicada** — commit `d4435e9`. Local:
`tests/e2e-cadastro-de-camera-salva-no-banco.py` **rc=0 (23/23)**; VPS com `api.py`/`supabase_escrita.py`/
`schema-transmissao.sql` de md5 idêntico ao local, `pipeline-api` ativa e `/api/saude` com
`supabase: {configurado: true, alcance: ok}`; Supabase `gscfcobpejxhtyzwfrjp`: `cameras` saiu de **1** para
**16** linhas (12 em "Bancada de testes (propria)" e 4 em "PSV Exemplo (demo)"). **Fase 2 implementada e
provada** — `config_bordo` + `config_aplicada_bordo` + `config_local` no SQLite, rotas
`GET /api/config-desejada` (bordo, 404 com `LECSOR_SEM_CONFIG=1`), `POST /api/config-aplicada` (bordo),
`GET/POST /api/config` (admin publica e vê desejada × aplicada) e `POST /api/config/aplicar` (rota **local**
do bordo, já em `ROTAS_CAPTURA`); no agente, `ler_config()`/`aplicar_config()`/`intervalo_da_config()`
(`LECSOR_ESPERA_DA_CONFIG`, padrão 15 s) aplicam **só a diferença** e confirmam — e `teto_do_bordo()` passa a
obedecer o que o admin publicou. Provado por `tests/e2e-config-do-bordo-vinda-de-terra.py` **rc=0 (21/21)**,
incluindo a recusa com motivo (`gravacao_continua` ainda não aplicável) sem derrubar o que já estava aplicado.
Fases 3–6 pendentes.
**Data:** 19/11/2026 · **Base:** 0.7.0 (`9ca021d` + plano `2d94e25`)
**Alvo:** 0.8.0 — o cadastro de câmera passa a ser salvo no banco (hoje só existe no SQLite local), o bordo
deixa de ter tela de configuração, passa a **buscar** o que terra publica e passa a **reportar a própria saúde**
ao admin

---

## O que o dono pediu (palavras dele)

> "estou pensando em utilizar no computador de captura apenas o usuário de captura, apenas para cadastrar as
> câmeras e radar de óleo, eu configuraria tudo pelo meu usuário admin, pela premissa de não enviar nada para
> bordo, o app a bordo precisa buscar o tempo todo as atualizações enviadas pelo cliente e pelo admin"

Contexto obrigatório (já decidido e implementado na 0.7.0, não se reabre aqui):

> "não podemos contar que o computador de captura a bordo terá porta aberta para receber comandos ou
> informações, a única certeza é de que ele poderá enviar"

> "parece que as câmeras não estão sendo salvas no banco de dados, analise isso para incluir também no plano"

---

## Achado de 19/11/2026 — o cadastro de câmera não está sendo salvo no banco (medido)

| Fato | Como foi verificado |
|---|---|
| Supabase (`gscfcobpejxhtyzwfrjp`) tem **1** câmera: `vps-webcam-bancada` (rotulo "Webcam da bancada") | `GET /rest/v1/cameras?select=id,embarcacao_id,rotulo,fluxo_id` na VPS — 1 linha |
| A tabela na tela do dono mostra exatamente essa 1 linha | imagem do Table Editor (`video_compressor`, `public.cameras`) |
| A VPS tem **16** câmeras no SQLite (`db/pipeline.db`) | consulta ao `pipeline.db` da VPS: `cam-01-demo`…`vivo-cam02-1811` |
| **Nada no código escreve `cameras` no Supabase** | `grep rest/v1/cameras` = 0 ocorrências; a única escrita é `ground/publicar_telemetria.py:84` (telemetria) |
| O Supabase só é **lido** em views (`v_producao_30d`, `v_disponibilidade_30d`) | `ground/supabase_leitura.py:46` (`resumo`) e `:30` (`_rest`) |
| O cadastro de câmera nasce no **SQLite** | `ground/api.py:3559` (`INSERT INTO cameras …`) e o anúncio `POST /api/cameras/anuncio` |
| Os tipos **não** batem: no Supabase `cameras.embarcacao_id` é **uuid**; no SQLite é texto (`'bancada'`) | linha do Supabase (`dedec7a2-…`) × `db/schema-fase4.sql:30` (`embarcacao_id TEXT`) |
| O Supabase tem 2 embarcações (`Bancada de testes (propria)`, `PSV Exemplo (demo)`) | `GET /rest/v1/embarcacoes` na VPS |
| `fluxos` **não existe** no Supabase (`404`) | `GET /rest/v1/fluxos` → HTTP 404 |

**Leitura:** o cadastro **é** salvo — mas só no banco **local** (SQLite do bordo e da VPS). O Supabase é a
única base que o dono enxerga, e ali `cameras` está congelada em 1 linha porque **nenhum caminho de código a
escreve**. Para o cadastro viver no banco de verdade falta **espelhar** o cadastro para o Supabase — o que
exige um **mapeamento estável** entre a embarcação de lá (uuid) e a de cá (texto).

---

## Evidência do resto do desenho (fato | como foi verificado)

| Fato | Como foi verificado |
|---|---|
| O bordo **já** vive de *polling*: lê a flag a cada 2 s (`LECSOR_ESPERA_DA_FLAG`, padrão 2.0) | `ground/agente_de_ordens.py:359` (`intervalo_da_flag`) |
| O bordo **já** devolve o que aplicou (fecha o ciclo desejo→realidade) | `ground/agente_de_ordens.py:222` (`aplicar_flag` → `POST /api/estado-real`) |
| **Não existe** nenhuma tabela de configuração do bordo | `db/schema-transmissao.sql`: só `transmissoes`, `ordens_do_bordo`, `configs_do_cliente`, `configs_do_produto`, `desejo_camera`, `estado_bordo`, `hd_catalogo`, `hd_pedidos`, `gravacoes` |
| `/api/transmissao/config` **não** é config do bordo — é o teto de tempo do cliente | `ground/api.py:3297` |
| `desejo_camera` e `estado_bordo` já têm `versao`/`versao_desejo` — o padrão de versionamento existe | `db/schema-transmissao.sql:77` e `:88` |
| O bordo liga câmera chamando a **API local** só com `camera_id`; quem resolve o **dispositivo físico** é a máquina de captura | `ground/agente_de_ordens.py:280` (`_chamar_local`) → `ground/api.py:42` (`ROTAS_CAPTURA`) |
| A câmera guarda `alvo` (bitrate) e `local` (dispositivo) — o vínculo físico mora no banco do **bordo** | `db/schema-fase4.sql:28` (`cameras`) |
| O papel do usuário de captura já existe e é `tecnico` | `db/schema-fase4.sql:44` (`usuarios.papel CHECK (… 'tecnico')`) |
| A tela local do bordo é mínima | `entrada/index.html` (45 linhas) + `entrada/entrada.js` (84 linhas) |
| A tela do admin é onde a configuração vive hoje | `admin/index.html` + `admin/admin.js` (1822 linhas) |
| O bordo **já** publica um retrato **parcial** de saúde (`anuncio`: token, lado terra, embarcação, última tentativa por fluxo) | `curl localhost:8085/api/saude` na VPS (2568 bytes) + `ground/api.py:1581` |
| Terra **já** tem onde pendurar a série de saúde: `estado_bordo` (por câmera) e `telemetria_minuto` (produção/banda/SSIM) | `db/schema-transmissao.sql:88`; `ground/producao.py` |

**Leitura disso:** a ideia do dono não é arquitetura nova — é **estender para a configuração** exatamente a
mecânica já provada para a flag (versionado, o bordo olha, aplica só na diferença, confirma o que aplicou).
O que **não** pode vir de terra é o que terra não conhece: o **dispositivo físico** (`dshow:<nome>`), a
**pasta do HD** e a **rede** da máquina — isso fica local, e é justamente o que o usuário de captura cadastra.

---

## Goal

O cadastro de câmera vive **no banco** (Supabase) e não só no SQLite de uma máquina; o usuário de captura a
bordo **só cadastra** (câmera + radar de óleo, apontando o dispositivo físico local);
o **admin** define de terra tudo o mais (quais câmeras transmitem, alvo de bitrate, teto de tempo, gravação
contínua do radar) e o bordo **busca** e aplica sozinho, sem porta aberta e sem ninguém digitando nada a bordo.

## Architecture

- **Cadastro:** o SQLite continua sendo o banco de operação (o ao vivo mora na VPS, não na nuvem), mas o
  cadastro passa a ser **espelhado** para o Supabase por `upsert` em `cameras` — quem publica é o lado terra,
  dono do `LECSOR_SUPABASE_SERVICE_KEY`; o SQLite fica como cache local e o Supabase como base de verdade.
- **Config:** duas fontes em terra, um só laço de leitura no bordo:

- `config_bordo` (nova) — chave→valor **versionado**, escopo por `embarcacao_id` e opcionalmente `camera_id`;
  é o que o admin publica. Reusa o padrão de `desejo_camera` (`versao` sobe a cada mudança).
- `desejo_camera` (existente) — continua sendo o liga/para. Não se funde com a config: desejo é estado
  transitório (muda a cada sessão), config é declaração (muda raramente).
- O bordo já olha a flag a cada 2 s; a config entra no **mesmo laço** com cadência própria
  (`LECSOR_ESPERA_DA_CONFIG`, padrão 15 s) e confirma com `POST /api/config-aplicada`.
- **Aplica só na diferença**, valida antes de aplicar, e **mantém a última boa** se a nova falhar — config
  que reinicia stream não pode derrubar vídeo em produção.

## Tech Stack

Python 3 + `sqlite3` + `http.server` (`ground/api.py`, `ground/agente_de_ordens.py`), SQLite
(`db/schema-transmissao.sql`), JS puro (`admin/admin.js`, `entrada/entrada.js`), Playwright para a prova de
tela, `tests/*.py` (padrão da casa: o teste sobe a API de verdade e fala HTTP com ela).

---

## Fase 1 — O cadastro de câmera passa a ser salvo no banco (Supabase)

**P0 — espelho do cadastro.** `ground/supabase_escrita.py` (novo, no servidor): `salvar_camera(…)` faz
`POST /rest/v1/cameras` com `Prefer: resolution=merge-duplicates` (upsert por `id`), usando
`LECSOR_SUPABASE_URL` + `LECSOR_SUPABASE_SERVICE_KEY`. Chamado por `ground/api.py` **no mesmo ponto** em que a
câmera é criada/alterada (`INSERT INTO cameras`, `ground/api.py:3559`) e pelo caminho do anúncio
(`POST /api/cameras/anuncio`). Sem chave no ambiente → falha **visível** (`/api/saude` e a tela), nunca
silenciosa — foi exatamente o erro da 0.6.7 que só aparecia em arquivo de log.

**P0 — mapeamento embarcação uuid ↔ texto.** O Supabase usa `uuid` (`dedec7a2-…`) e o nosso banco usa texto
(`'bancada'`). Criar a tabela de equivalência no SQLite (`embarcacoes_supabase(slug, uuid, nome)`) e uma
rotina `garantir_embarcacao(uuid)` que cria em terra a embarcação que só existe no Supabase — sem ela o
`upsert` de câmera **falha por chave estrangeira** (a câmera aponta para a embarcação). Câmera sem
equivalência = erro explícito, nunca linha órfã.

**P1 — o cadastro que já existe.** Publicar, uma vez, as câmeras que estão só no SQLite (as 16 da VPS),
marcando origem e idade — a tela do dono deixa de mostrar 1 linha e passa a mostrar o cadastro real. Nada é
apagado no Supabase; linha que já existe é atualizada.

**P2 — o cliente não vê endereço.** Manter a regra já provada na migração
`20261111130000_cameras_sem_endereco_para_cliente.sql`: `ip`/`porta` **nunca** sobem nem são legíveis pelo
papel `cliente` — o espelho grava só identidade (id, embarcação, rótulo, fluxo), não endereço de câmera.

**Critério de aceite (por comando):** `tests/e2e-cadastro-de-camera-salva-no-banco.py` — cadastra câmera pela
API; `GET /rest/v1/cameras` (na VPS) passa a devolver a nova linha com o `embarcacao_id` correto em uuid; e o
caso de falha (sem service key) **aparece** no `/api/saude` em vez de sumir. Fecha `rc=0`.

## Fase 2 — Configuração publicada por terra, buscada pelo bordo (o núcleo)

**P0 — tabela e rotas.**
`db/schema-transmissao.sql`: nova tabela

```sql
CREATE TABLE IF NOT EXISTS config_bordo (
  embarcacao_id  TEXT NOT NULL DEFAULT '',
  camera_id      TEXT NOT NULL DEFAULT '',   -- '' = vale para a embarcação inteira
  chave          TEXT NOT NULL,              -- ex.: 'transmitir', 'alvo_kbps', 'gravacao_continua'
  valor          TEXT NOT NULL DEFAULT '',
  versao         INTEGER NOT NULL DEFAULT 0, -- sobe a cada mudança (mesmo padrão de desejo_camera)
  origem         TEXT NOT NULL DEFAULT '',   -- e-mail de quem publicou (admin)
  atualizado_em  TEXT NOT NULL,
  PRIMARY KEY (embarcacao_id, camera_id, chave)
);
```

`ground/api.py`: `GET /api/config-desejada` (exige token do bordo, como `/api/estado-desejado`) devolve as
linhas da embarcação + a `versao` máxima; `POST /api/config-aplicada` (token do bordo) grava o que o bordo
aplicou e a versão aplicada, na trilha (`auditoria_acesso`). Migração automática na instalação que atualiza
(`CREATE TABLE IF NOT EXISTS`, sem passo manual no cliente — regra da casa).

**P0 — o laço do bordo.**
`ground/agente_de_ordens.py`: `ler_config()`, `aplicar_config()` e `intervalo_da_config()`
(`LECSOR_ESPERA_DA_CONFIG`, padrão 15,0 s), chamados em `uma_rodada()` **depois** da flag. Aplica só a
diferença; valida antes (alvo dentro da faixa, chaves conhecidas); se a nova config falhar, **mantém a
última boa** e conta o motivo em vez de fingir sucesso.

**P1 — visibilidade.** `admin/admin.js`: por câmera, mostrar **versão desejada × versão aplicada** e quando
aplicou — o admin vê que a config chegou ao bordo sem precisar de acesso ao bordo.

**P2 — retrocompatibilidade.** Bordo antigo (0.7.0) e terra novo (0.8.0) têm de conviver: terra sem
`config_bordo` responde 404 e o bordo segue só na flag — mesmo padrão de `LECSOR_SEM_FLAG=1` (`ground/api.py`).

**Critério de aceite (por comando):** `tests/e2e-config-do-bordo-vinda-de-terra.py` — terra publica config,
o bordo aplica na diferença, `POST /api/config-aplicada` fecha o ciclo; e o caso de falha (config inválida
**não** derruba o que está no ar). Fecha em `rc=0`.

## Fase 3 — Usuário de captura só cadastra; admin configura tudo

**P0 — reduzir a tela local.** `entrada/entrada.js` + `entrada/index.html`: a tela do bordo passa a ter
**apenas** o cadastro (câmera: rótulo + dispositivo local; radar de óleo: dispositivo + pasta do HD) e o
estado do que está no ar. Sai qualquer campo de tempo/qualidade/config — isso vem de terra.

**P0 — o admin assume a configuração.** `admin/admin.js` + `admin/index.html` ganham a publicação em
`config_bordo`: quais câmeras transmitem, `alvo` por câmera, teto de tempo, gravação contínua do radar
(ligada/desligada). As rotas novas exigem papel `admin` (`ground/api.py`).

**P1 — a fronteira declarada.** O que **não** vem de terra, por fato físico (terra não conhece e não
alcança): `dshow:<dispositivo>`, `LECSOR_HD_DIR`, endereço de rede da máquina. Fica local, cadastrado pelo
usuário de captura — e o plano declara isso em vez de prometer config total.

**P2 — matriz de permissões.** Documento curto + teste `tests/test-papeis-de-config.py`: quem pode publicar
config (admin), quem só cadastra (captura/tecnico), quem só vê (operador/cliente) — provado por HTTP, com
403 no papel errado.

**Critério de aceite (por comando):** `tests/e2e-tela-do-captura-so-cadastra.py` (Playwright) — a tela do
bordo **não** tem campo de config e **tem** o cadastro; `tests/test-papeis-de-config.py` — 403 em papel
errado. Ambos `rc=0`.

## Fase 4 — Prova de operação real (sem tocar produção)

**P0 — ciclo completo.** `tests/e2e-admin-configura-e-bordo-obedece.py`: o admin liga/desliga a transmissão
de uma câmera **e** muda o alvo de bitrate em terra → o bordo aplica → o estado volta ao admin. Não é teste
de unidade: sobe as duas APIs de verdade.

**P1 — o bordo se recupera sozinho.** Teste do caso sujo: config publicada enquanto o bordo transmite;
config que viola validação; bordo que reinicia no meio. O que está no ar **não cai** por config ruim.

**P2 — regressão completa.** A suite inteira da 0.7.0 (12 testes) continua verde, mais os novos.

**Critério de aceite (por comando):** log `regressao-080.log` com **todos** os `rc=0`, incluindo os 12 da
0.7.0.

## Fase 5 — Saúde do bordo no painel do admin

**P0 — o retrato de saúde nasce no bordo.** `ground/saude_do_bordo.py` (novo): `retrato()` devolve, sem
segredo nenhum, o que responde "está tudo okay ou tem algo para corrigir/acompanhar": CPU e memória
(`psutil` se houver, senão `/proc`+`os`), **disco livre** por volume (e, no HD do radar, livre + bloco mais
antigo — o anel), uptime, versão do app, `ffmpeg` presente, dispositivos de vídeo vistos, laço do agente
vivo (idade do último batimento), `mediamtx` no ar, última saída **bem-sucedida** para terra, pedidos do HD
pendentes e erros das últimas 24 h. Rota local `GET /api/saude-do-bordo` (mesma família de `/api/saude`,
que hoje já traz `anuncio`).

**P0 — o bordo envia, terra guarda.** `POST /api/saude-do-bordo` (token do bordo, o **mesmo caminho de
saída** já provado — nada de porta aberta) com cadência própria (`LECSOR_ESPERA_DA_SAUDE`, padrão 60 s), no
boot e **na mudança de estado**. Terra grava em `saude_bordo` (nova tabela: última linha por embarcação +
série por minuto) e o admin vê por embarcação.

**P1 — semáforo, não despejo de números.** `admin/admin.js`: cada sinal entra como **verde / amarelo /
vermelho** com limiar declarado (disco > 90% = vermelho; sem enviar há 3× a cadência = vermelho; laço morto,
câmera que não sobe, versão desatualizada = acompanhar). Cada vermelho traz o **que fazer**, e o "o que
fazer" aponta para a configuração da Fase 2 — não para acesso ao bordo.

**P1 — read-only de verdade.** O admin **lê** a saúde; o bordo segue sem porta aberta, e nada de terra
mandar comando por esse canal. Se o problema for de configuração, o conserto é publicar config (Fase 2).

**P2 — retenção e trilha.** Série com retenção declarada (30 dias) e registro na trilha
(`auditoria_acesso`) de quando um sinal virou vermelho e voltou.

**Critério de aceite (por comando):** `tests/e2e-saude-do-bordo-no-admin.py` — com a API de verdade, o bordo
envia o retrato, o admin mostra os sinais e o semáforo; e o caso sujo (disco acima do limiar / bordo mudo)
vira **vermelho** em vez de silêncio. Fecha `rc=0`.

## Fase 6 — Publicar (0.8.0)

**P0 — pacote e release.** `desktop/package.json` → `0.8.0`; `tools/publicar-releases.py`
(`VERSOES_PUBLICADAS` + `NOTAS["0.8.0"]`); `README.md` com a seção 0.8.0; build dos instaladores; release
no GitHub (só funciona com `export GH_TOKEN=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill | sed -n 's/^password=//p')`).

**P0 — subir para a VPS.** `scp` dos arquivos alterados + `systemctl restart pipeline-api.service`;
conferir `/api/saude` 200, `/app/` 200, `/api/config-desejada` 401 sem token do bordo.

**P1 — runbook no vault.** Nota em `~/.hermes/vault-arrow/20-runbooks/` + `index.md` + push
(`git push https://github.com/gm-innovation/vault-lecsor.git HEAD:master`).

**Critério de aceite (por comando):** release listada na API do GitHub com o sha256 do `.exe`; VPS com
`pipeline-api` ativa e as três respostas acima.

---

## Files likely to change

- `ground/supabase_escrita.py` (novo) — `salvar_camera()`, `garantir_embarcacao()`, `configurado()`
- `ground/saude_do_bordo.py` (novo) — `retrato()` (CPU, memória, disco, HD do radar, uptime, versão,
  `ffmpeg`, dispositivos, laço vivo, `mediamtx`, última saída, pedidos pendentes, erros de 24 h)
- `db/schema-transmissao.sql` — tabela `saude_bordo` (última por embarcação + série)
- `db/schema-transmissao.sql` — tabela `config_bordo` (+ comentário do modelo, junto do bloco da flag)
- `db/schema-fase4.sql` — tabela de equivalência `embarcacoes_supabase(slug, uuid, nome)`
- `ground/api.py` — `GET /api/config-desejada`, `POST /api/config-aplicada`, rotas de publicação do admin,
  404 de compatibilidade, registro na trilha (`auditar()` → `auditoria_acesso`)
- `ground/agente_de_ordens.py` — `ler_config()`, `aplicar_config()`, `intervalo_da_config()`,
  `uma_rodada()` (config depois da flag)
- `admin/admin.js`, `admin/index.html` — publicar config, ver desejada × aplicada e o painel de **saúde**
  (semáforo por embarcação, com o "o que fazer" em cada vermelho)
- `entrada/entrada.js`, `entrada/index.html` — encolher para só o cadastro
- `desktop/package.json`, `tools/publicar-releases.py`, `README.md` — 0.8.0
- `tests/e2e-config-do-bordo-vinda-de-terra.py`, `tests/e2e-tela-do-captura-so-cadastra.py`,
  `tests/test-papeis-de-config.py`, `tests/e2e-admin-configura-e-bordo-obedece.py`,
  `tests/e2e-saude-do-bordo-no-admin.py` (novos)

## Tests / validation

Todos no padrão da casa: o teste **sobe a API de verdade** e fala HTTP com ela (nada de mock), roda com
`python tests/<arquivo>.py` e fecha com `rc`; a prova de tela usa Playwright/Chromium. O teste do espelho
confere o resultado **lendo o Supabase** (`GET /rest/v1/cameras`), não a resposta da nossa própria API. Fecho da rodada com o
veredito ("funcionou 100%" / "com ressalvas" / "não funcionou") e log em `$LOCALAPPDATA/Temp/`.

## Riscos e limites (declarados)

- **A saúde não pode virar canal de comando.** É o bordo que **envia** (mesmo caminho de saída do token de
  ingestão); terra só lê e mostra. Se alguém pedir "reiniciar pelo painel", isso contraria a premissa do dono
  e sai deste plano.
- **Saúde sem segredo:** o retrato não carrega endereço de câmera, senha, chave nem IP interno — só números e
  estados; a série tem retenção declarada, senão vira depósito.
- **Espelho pode divergir do SQLite.** Mitigação: o SQLite segue sendo o banco de operação (o ao vivo não
  depende do Supabase — decisão já tomada); o espelho é só do cadastro, e falha de rede no Supabase **não**
  impede cadastrar na máquina — só fica visível como pendência.
- **Segredo:** a service key do Supabase fica **só** no servidor (variável de ambiente), nunca no repo, no
  instalador nem no chat; o cliente nunca recebe endereço de câmera (`ip`/`porta`).
- **Cadastro de câmera com `embarcacao_id` em uuid:** se a embarcação do Supabase não tiver equivalência
  local, o espelho **falha por chave estrangeira** — por isso a Fase 1 é P0 e vem antes de tudo.
- **Config remota pode derrubar vídeo.** Mitigação declarada: aplicar só na diferença, validar antes,
  manter a última boa, registrar na trilha. Ainda assim, a 0.8.0 **não** pode ser considerada provada em
  campo sem a medição de bancada pendente da 0.7.0 (30 fps / ≤3 s / ≥80%).
- **Fora de escopo desta rodada:** medição de bancada no PC de captura real (precisa da máquina física); o
  DVR (não operamos — o split é físico); trocar o `polling` por push (contraria a premissa do dono).
- **O que continuará não-medido:** taxa real de mudança de config em produção (para calibrar a cadência) e
  o comportamento com **mais de uma** embarcação publicando config ao mesmo tempo.
- O bordo depende de uma única saída (a mesma do token de ingestão): se o `LECSOR_TOKEN_INGESTAO` do lado
  terra e do bordo divergirem, `/api/config-desejada` responde 401 — já foi um achado medido em produção.

## Decisões do dono (aprovadas em 19/11/2026 — valem as propostas)

1. **Quem manda no cadastro de câmera: o Supabase ou o SQLite da VPS?** — aprovado: o SQLite opera, o
   Supabase é a base de verdade do cadastro e o local vira cache (o ao vivo não depende da nuvem).
2. **Quais chaves o admin configura de terra?** (proposta: `transmitir`, `alvo_kbps` por câmera, `teto_s`,
   `gravacao_continua`) — é isto ou falta alguma?
3. **Config publicada com o bordo transmitindo:** aplicar **já** (reinicia o stream afetado) ou **quando
   aquele stream parar naturalmente**? (proposta: já para `transmitir`, na parada natural para `alvo_kbps`).
4. **Quem cadastra câmera no bordo:** só o usuário de captura local, ou o admin de terra também publica o
   cadastro (o bordo continuaria dono do vínculo com o dispositivo físico)?
5. **Saúde: quais sinais o senhor quer ver, com que limiar, e onde o vermelho deve avisar?** (proposta:
   CPU, memória, disco livre, HD do radar no anel, uptime, versão, laço vivo, `mediamtx`, última saída para
   terra e erros de 24 h; limiares declarados na tela; aviso **no painel** e, se o senhor quiser, por e-mail —
   nada por WhatsApp sem o senhor definir).
