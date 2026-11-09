# Supabase do pipeline de vídeo (projeto NOVO)

Não é o ARROW (`ykehegyguicjssxacyoe`) e não é o Dock Check (`qdscawiwjhzgiqroqkik`).

## O que já está pronto aqui
- `migrations/20261109140000_pipeline_telemetria.sql` — clientes, embarcações, câmeras, telemetria por
  minuto, amostras de link (RTT/capacidade/atraso/perda), views de produção e de disponibilidade de 30
  dias, RLS por cliente, retenção e o Cron horário de fechamento.
- `functions/telemetria-ingestao/index.ts` — Edge Function que o **servidor de bordo** chama para
  despejar o minuto fechado. A chave de serviço fica só no ambiente da função.

## Passos quando o projeto existir
```
supabase link --project-ref <ref-do-projeto>
supabase db push
supabase secrets set LECSOR_TOKEN_INGESTAO=<token-do-servidor-de-bordo>
supabase functions deploy telemetria-ingestao --no-verify-jwt
```
Depois, no lado da bancada/servidor de bordo:
```
export LECSOR_SUPABASE_URL=https://<ref>.supabase.co
export LECSOR_TOKEN_INGESTAO=<mesmo token>
python ground/publicar_telemetria.py            # envia o histórico fechado
python ground/publicar_telemetria.py --simular  # só mostra o que seria enviado
```

## Regra de credencial (não negociável)
- `SUPABASE_SERVICE_ROLE_KEY` **nunca** vai para cliente, repositório ou chat — só no ambiente da Edge Function.
- A chave anônima pode ir ao front; o banco é protegido por RLS.
- O endereço da câmera (IP/porta) é dado de operação: o papel `cliente` lê pela view
  `v_cameras_cliente`, que **não** devolve `ip`/`porta`.
