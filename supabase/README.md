# Supabase do pipeline de vídeo — projeto `video_compressor` (organização Lecsor Technology)

Não é o ARROW (`ykehegyguicjssxacyoe`) e não é o Dock Check (`qdscawiwjhzgiqroqkik`).

**Ref:** `gscfcobpejxhtyzwfrjp` · **URL:** `https://gscfcobpejxhtyzwfrjp.supabase.co` · região `us-east-1`
· PostgreSQL 17.11 · projeto **ACTIVE_HEALTHY**.

## Estado em 11/11/2026 (verificado com ferramenta)

| Item | Estado |
|---|---|
| Schema | aplicado: 6 tabelas, 3 views, 6 políticas, RLS ligada nas 6, `fechar_janela()` criada |
| Cron | `pg_cron` habilitado; job `pipeline-fechar-janela` ativo (`7 * * * *`) |
| Edge Function | `telemetria-ingestao` **ACTIVE v1** (`verify_jwt: false`) |
| Secret | `LECSOR_TOKEN_INGESTAO` criado no projeto |
| Ingestão real | bancada → EF → banco: `{"ok":true,"minutos_gravados":344,"link":true}` |
| Leitura no produto | `ground/supabase_leitura.py` + `GET /api/supabase`; painel "Supabase" na tela Produção do admin |

## Arquivos

- `migrations/20261109140000_pipeline_telemetria.sql` — clientes, embarcações, perfis, câmeras,
  telemetria por minuto, amostras de link (RTT/capacidade/atraso/perda), views de produção e de
  disponibilidade de 30 dias, RLS por cliente, retenção e o Cron horário de fechamento.
- `migrations/20261111130000_cameras_sem_endereco_para_cliente.sql` — tira do papel `authenticated` o
  privilégio de coluna em `cameras.ip` / `cameras.porta`.
- `functions/telemetria-ingestao/index.ts` — Edge Function que o **servidor de bordo** chama para
  despejar o minuto fechado. A chave de serviço fica só no ambiente da função.

## Como aplicar mudanças (sem CLI e sem senha do banco)

O projeto é alcançado pela **API de gerenciamento** com um PAT (`sbp_...`); a CLI `supabase` só é
necessária para publicar a função (`--use-api` dispensa Docker). Nenhum segredo entra no repositório:

```
# SQL (migração, consulta, verificação de RLS)
POST https://api.supabase.com/v1/projects/gscfcobpejxhtyzwfrjp/database/query   {"query": "..."}

# função
supabase functions deploy telemetria-ingestao --project-ref gscfcobpejxhtyzwfrjp --no-verify-jwt --use-api --yes

# secret
POST /v1/projects/gscfcobpejxhtyzwfrjp/secrets  [{"name":"LECSOR_TOKEN_INGESTAO","value":"..."}]
```

Depois, no servidor em terra (bancada ou VPS):
```
export LECSOR_SUPABASE_URL=https://gscfcobpejxhtyzwfrjp.supabase.co
export LECSOR_TOKEN_INGESTAO=<mesmo token do secret>
python ground/publicar_telemetria.py            # envia o histórico fechado
python ground/publicar_telemetria.py --simular  # só mostra o que seria enviado
```

Para o produto **ler** a nuvem, o servidor em terra precisa também de:
```
export LECSOR_SUPABASE_SERVICE_KEY=<chave de serviço do projeto>
```

## Regra de credencial (não negociável)

- `SUPABASE_SERVICE_ROLE_KEY` **nunca** vai para cliente, repositório ou chat — vive no ambiente do
  servidor em terra (leitura das views) e da Edge Function (escrita).
- A chave anônima pode ir ao front; o banco é protegido por RLS.
- O endereço da câmera (IP/porta) é dado de operação: o papel `authenticated` **não tem** privilégio de
  coluna em `cameras.ip` / `cameras.porta`; o cliente lê a view `v_cameras_cliente`, que não devolve
  endereço.
- Nenhum valor de chave entra em arquivo versionado: na bancada ficam em `ground/.env.local` (ignorado
  pelo git) e, fora do repositório, em `~/.hermes/credenciais/supabase-video_compressor.env`.
