# Integração do sistema ao Supabase — projeto `video_compressor`

**Status:** aprovado em 11/11/2026 — fases 1 a 4-P0 executadas e verificadas neste dia; ficam pendentes a 4-P1 (decisão de login) e a publicação na VPS (5-P1)
**Data:** 11/11/2026 · **Repo:** `C:\Users\EngenhariaGoogleMari\lecsor-pipeline-video` (branch `main`) · **GitHub:** `gm-innovation/video_compressor`

**Goal:** o pipeline de bordo passa a gravar telemetria, produção e disponibilidade no Supabase do projeto
`video_compressor` (organização **Lecsor Technology**) e o produto passa a ler esses números de lá.

**Arquitetura (mantém a regra de segurança atual):** o servidor de bordo escreve **por Edge Function**
(a `SUPABASE_SERVICE_ROLE_KEY` fica só no ambiente da função); o navegador **nunca** recebe credencial de
banco nem endereço interno — a leitura no produto continua entrando pela nossa API em terra.

## O que já existe no repositório (evidência, não proposta)

| Arquivo | Estado |
|---|---|
| `supabase/migrations/20261109140000_pipeline_telemetria.sql` | escrito — `clientes`, `embarcacoes`, `perfis`, `cameras`, `fluxos`, `telemetria_minuto`, `link_amostras`, views `v_producao_30d` / `v_disponibilidade_30d`, `fechar_janela()`, `pg_cron` |
| `supabase/functions/telemetria-ingestao/index.ts` | escrito — recebe o minuto fechado do servidor de bordo, autenticação por token próprio |
| `ground/publicar_telemetria.py` | escrito — lê `LECSOR_SUPABASE_URL` e `LECSOR_TOKEN_INGESTAO` do ambiente, nada embutido |
| `supabase/README.md` | escrito — os passos de `link` / `db push` / `secrets set` / `functions deploy` |

## Acesso ao projeto (levantado hoje, com ferramenta)

| Fato | Verificação |
|---|---|
| Projeto | `video_compressor` — organização **Lecsor Technology** (`mkiezdzkbtbiquikidcj`), região `us-east-1`, PostgreSQL **17.11**, status `ACTIVE_HEALTHY` |
| Ref | **`gscfcobpejxhtyzwfrjp`** → `https://gscfcobpejxhtyzwfrjp.supabase.co` |
| Credencial em uso | PAT do arquivo `Desktop\video_compressor\credenciais.txt` (entregue **por arquivo**); o PAT antigo de `~/.hermes/vps-deploy/supabase.token` segue inválido |
| Permissão do PAT | lê projeto, chaves de API, funções e secrets; **nega** `organizations_read` (403 "Missing required permission(s)") |
| Rota de DDL | `POST /v1/projects/{ref}/database/query` respondeu a consultas — aplica a migração **sem CLI e sem senha do banco** |
| Estado do banco | schema `public` **vazio** (nenhuma tabela); `pgcrypto` presente; **`pg_cron` ausente** |
| Estado do projeto | **nenhuma função publicada** e **nenhum secret** |
| CLI `supabase` | não instalada (`which supabase` → nada); deixou de ser bloqueio pela rota acima |

## Evidências do que foi executado (11/11/2026, tudo com ferramenta)

| Passo | Resultado verificado |
|---|---|
| Schema aplicado pelo `POST /database/query` (sem CLI, sem senha do banco) | 6 tabelas (`clientes`, `embarcacoes`, `perfis`, `cameras`, `telemetria_minuto`, `link_amostras`), 3 views, 6 políticas, RLS ligada nas 6, `fechar_janela()` criada |
| Cron | `pg_cron` habilitado e job `pipeline-fechar-janela` ativo (`7 * * * *`) |
| Edge Function | `telemetria-ingestao` **ACTIVE v1** (`verify_jwt: false`) e secret `LECSOR_TOKEN_INGESTAO` criado |
| Ingestão real da bancada | `publicar_telemetria.py --desde-dias 1` → HTTP **200** `{"ok":true,"minutos_gravados":344,"link":true}` |
| O que ficou gravado | 344 minutos (compressão média **99,06%**), 1 amostra de link; `v_producao_30d` = 774,95 MB / 3,126 Mbps; `v_disponibilidade_30d` = 344 min |
| Achado de segurança | `has_column_privilege('authenticated','cameras','ip')` era **true** — contra a regra da própria migração |
| Correção aplicada | nova migração `20261111130000_cameras_sem_endereco_para_cliente.sql`: agora `ip`/`porta` = **false** e o SELECT como `authenticated` devolve `permission denied for table cameras`; cliente sem perfil vê **0** linhas de telemetria |
| Leitura no produto | `ground/supabase_leitura.py` + `GET /api/supabase` (curl devolveu os números da nuvem) e painel "Supabase" na tela Produção do admin |
| Testes | `tests/test-supabase-leitura.py` rc 0 (sem config / com config / cache / erro de rede); suíte `unittest` OK; `node --check` OK |
| Onde vivem as chaves | `~/.hermes/credenciais/supabase-video_compressor.env` e `ground/.env.local` — fora do git; nada no repositório |

**Achado de documentação:** o cabeçalho da migração promete uma tabela `fluxos` que o DDL não cria (o
`fluxo_id` é texto livre) — comentário corrigido nesta rodada.

## Fase 1 — Acesso e vínculo do projeto (resolvida em 11/11/2026)

**1-A — feito (com ferramenta)**
- **P0** — PAT recebido por arquivo e testado: `GET /v1/projects` devolve `video_compressor`.
- **P1** — ref identificado: `gscfcobpejxhtyzwfrjp`; a rota de DDL foi provada com consulta real.
- **P2** — estado do projeto levantado: `public` vazio, sem função publicada, sem secret, `pg_cron` ausente.

**1-B — decidido a partir da 1-A**
- **P0** — **não usar a CLI**: aplicar migração e deploy pela API de gerenciamento (`/database/query` e `/functions`), que já responderam com o PAT do arquivo.
- **P1** — gravar em `.env` local (no `.gitignore`): `LECSOR_SUPABASE_URL=https://gscfcobpejxhtyzwfrjp.supabase.co`.
- **P2** — habilitar `pg_cron` no Dashboard (Integrations → Cron / Database → Extensions) antes da Fase 2-P2.
- **Aceite:** `.env` com a URL do projeto e `pg_cron` listado em `pg_extension`.

## Fase 2 — Schema no ar

- **P0** — `supabase db push` da migração já escrita.
- **P1** — conferir por SQL: as 7 tabelas, as 2 views, a função `fechar_janela()` e as políticas de RLS criadas.
- **P2** — ativar o Cron horário de fechamento (`pg_cron` precisa estar habilitado no Dashboard → Integrations → Cron).
- **Aceite:** consulta de catálogo lista os objetos; teste de RLS confirma que o papel `cliente` **não** lê `cameras.ip` / `cameras.porta`.

## Fase 3 — Ingestão de bordo (o dado real entrando)

- **P0** — `supabase secrets set LECSOR_TOKEN_INGESTAO=<token>` e `supabase functions deploy telemetria-ingestao --no-verify-jwt`.
- **P1** — rodar `ground/publicar_telemetria.py` de verdade a partir da bancada/VPS e contar as linhas gravadas em `telemetria_minuto` e `link_amostras`.
- **P2** — agendar o envio de minuto em minuto (VPS: timer systemd; bancada Windows: tarefa agendada).
- **Aceite:** um minuto real fechado na bancada aparece no Supabase, conferido por `select count(*)` antes e depois.

## Fase 4 — Leitura no produto

- **P0** — a API em terra passa a ler produção/disponibilidade do Supabase (chave de serviço só no servidor) e os cards do admin passam a mostrar esse número.
- **P1** — decidir o login: **Supabase Auth** para as contas do produto, ou manter a autenticação atual e usar o Supabase só como banco/telemetria.
- **P2** — teste de RLS por papel (`cliente`, `operacao`, `admin`) provando o que cada um lê.
- **Aceite:** card do admin com número vindo do Supabase e teste de RLS com resultado negativo para o que não deve passar.

## Fase 5 — Fechamento

- **P0** — teste de fumaça ponta a ponta (bancada → EF → Supabase → admin).
- **P1** — atualizar `supabase/README.md` com o ref e os passos que realmente funcionaram + nota no vault (`10-projetos/`).
- **P2** — commit e push (gate `plan-gate` lê esta linha de status).

## Decisão aberta (do Alexandre)

Login do produto: **migrar para Supabase Auth** (contas, senha e sessão no Supabase) ou **manter a autenticação atual** e usar o Supabase apenas como banco de telemetria? A resposta muda a Fase 4-P1 e o desenho de RLS.

## Arquivos que devem mudar

- `supabase/migrations/20261109140000_pipeline_telemetria.sql` (só se a conferência exigir ajuste)
- `ground/publicar_telemetria.py` (parametrização/agendamento)
- `ground/api.py` + `admin/admin.js` (Fase 4: ler do Supabase)
- `supabase/README.md`, `.env.example`, `.gitignore`
- novo: `.hermes/plans/` (este plano), nota no vault

## Riscos e limites (declarados)

- **Acesso:** sem o ref e sem PAT válido, as fases 1-B a 5 não começam — hoje é o único bloqueio real.
- **Credencial:** o PAT e a `service_role` não circulam em chat nem no repositório; a `service_role` vive só no ambiente da Edge Function.
- **`pg_cron`:** pode exigir habilitação manual no Dashboard; sem ele o fechamento roda só quando chamado.
- **Medição:** o teste da Fase 3 é de bancada (um fluxo, um minuto fechado); produção contínua com várias câmeras continua não medida.
- **Escopo intocado:** o Supabase continua sendo banco/realtime/funções/storage — **não** é servidor de mídia; o vídeo continua saindo pelo mediamtx.
