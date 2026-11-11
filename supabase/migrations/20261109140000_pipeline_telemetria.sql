-- Pipeline de vídeo de bordo — telemetria, produção e disponibilidade
-- Projeto: NOVO (não é ARROW, não é Dock Check). Rodar com a CLI:
--   supabase link --project-ref <ref>
--   supabase db push
--
-- O que este arquivo cria:
--   clientes / embarcacoes / cameras           -> multi-tenant (cliente vê só o dele)
--   (não existe tabela 'fluxos': o fluxo_id é texto livre em telemetria_minuto; a câmera vem de public.cameras)
--   telemetria_minuto                          -> o minuto fechado (média de compressão, MB, segundos no ar)
--   link_amostras                              -> RTT, capacidade do link, atraso do buffer SRT, perda
--   v_producao_30d / v_disponibilidade_30d     -> os números dos cards
--   fechar_janela()                            -> retenção e re-fechamento (chamado pelo Cron)
--
-- Regra de segurança: nada de chave no cliente. O servidor de bordo escreve via Edge Function
-- (service role fica só no ambiente da função) e o navegador lê o que a RLS permitir.

create extension if not exists pgcrypto;
create extension if not exists pg_cron;      -- disponível no Supabase (Dashboard > Integrations > Cron)

-- ------------------------------------------------------------------ multi-tenant
create table if not exists public.clientes (
  id          uuid primary key default gen_random_uuid(),
  nome        text not null,
  criado_em   timestamptz not null default now()
);

create table if not exists public.embarcacoes (
  id          uuid primary key default gen_random_uuid(),
  cliente_id  uuid not null references public.clientes(id) on delete cascade,
  nome        text not null,
  imo         text,
  criado_em   timestamptz not null default now()
);

create table if not exists public.perfis (
  id          uuid primary key references auth.users(id) on delete cascade,
  cliente_id  uuid references public.clientes(id) on delete set null,
  papel       text not null check (papel in ('cliente', 'operacao', 'admin')),
  criado_em   timestamptz not null default now()
);

create table if not exists public.cameras (
  id             text primary key,              -- derivado do fluxo (ex.: cam-01)
  embarcacao_id  uuid not null references public.embarcacoes(id) on delete cascade,
  rotulo         text not null,
  fluxo_id       text not null,
  -- endereço da câmera: dado de operação. A RLS abaixo NÃO deixa o papel 'cliente' ler isto.
  ip             text,
  porta          text,
  protocolo      text default 'rtsp',
  canal          text,
  ativo          boolean not null default true,
  criado_em      timestamptz not null default now()
);

-- ------------------------------------------------------------------ medições
create table if not exists public.telemetria_minuto (
  id                 bigserial primary key,
  fluxo_id           text not null,
  camera_id          text,
  embarcacao_id      uuid,
  minuto             timestamptz not null,
  entrada_kbps       numeric,
  saida_kbps         numeric,
  compressao_pct     numeric,
  mb_enviados        numeric,
  segundos_no_ar     integer,
  criado_em          timestamptz not null default now(),
  unique (fluxo_id, minuto)
);
create index if not exists idx_telemetria_minuto_minuto on public.telemetria_minuto (minuto desc);

create table if not exists public.link_amostras (
  id                bigserial primary key,
  fluxo_id          text,
  em                timestamptz not null default now(),
  rtt_ms            numeric,          -- do SRT (mediamtx: msRTT)
  capacidade_mbps   numeric,          -- mbpsLinkCapacity
  taxa_envio_mbps   numeric,
  atraso_buffer_ms  numeric,          -- msSendTsbPdDelay / msReceiveTsbPdDelay
  perda_pct         numeric,
  latencia_internet_ms numeric,       -- ping do servidor de bordo
  fonte             text
);
create index if not exists idx_link_amostras_em on public.link_amostras (em desc);

-- ------------------------------------------------------------------ cards
create or replace view public.v_producao_30d as
select e.cliente_id,
       e.nome                                   as embarcacao,
       c.rotulo                                 as camera,
       t.fluxo_id,
       round(avg(t.compressao_pct)::numeric, 2) as compressao_medio_pct,
       round(sum(t.mb_enviados)::numeric, 2)    as mb_enviados,
       round((sum(t.segundos_no_ar) / 3600.0)::numeric, 2) as horas_streaming,
       round((sum(t.mb_enviados) * 8 / nullif(sum(t.segundos_no_ar), 0))::numeric, 3) as banda_utilizada_mbps,
       round(avg(t.entrada_kbps)::numeric / 1000, 3) as entrada_mbps,
       max(t.minuto)                            as ultimo_minuto
  from public.telemetria_minuto t
  left join public.cameras c on c.id = t.camera_id or c.fluxo_id = t.fluxo_id
  left join public.embarcacoes e on e.id = coalesce(t.embarcacao_id, c.embarcacao_id)
 where t.minuto >= now() - interval '30 days'
 group by e.cliente_id, e.nome, c.rotulo, t.fluxo_id;

-- Disponibilidade (%) = minutos com medição / minutos da janela (30 dias), por câmera.
create or replace view public.v_disponibilidade_30d as
select t.fluxo_id,
       t.camera_id,
       count(*)                                                   as minutos_no_ar,
       (30 * 24 * 60)                                             as minutos_janela,
       round((count(*)::numeric / (30 * 24 * 60)) * 100, 3)       as disponibilidade_pct
  from public.telemetria_minuto t
 where t.minuto >= now() - interval '30 days'
 group by t.fluxo_id, t.camera_id;

-- ------------------------------------------------------------------ retenção + fechamento
create or replace function public.fechar_janela(p_retencao_dias integer default 30)
returns table (minutos_apagados integer, em timestamptz)
language plpgsql
security definer
set search_path = public
as $$
declare apagados integer;
begin
  delete from public.telemetria_minuto where minuto < now() - (p_retencao_dias || ' days')::interval;
  get diagnostics apagados = row_count;
  delete from public.link_amostras where em < now() - interval '7 days';
  return query select apagados, now();
end $$;

-- ------------------------------------------------------------------ RLS
alter table public.clientes          enable row level security;
alter table public.embarcacoes       enable row level security;
alter table public.perfis            enable row level security;
alter table public.cameras           enable row level security;
alter table public.telemetria_minuto enable row level security;
alter table public.link_amostras     enable row level security;

-- ajuda: papel e cliente de quem está logado
create or replace function public.papel_do_usuario() returns text
language sql stable security definer set search_path = public as $$
  select coalesce((select papel from public.perfis where id = auth.uid()), 'cliente')
$$;

create or replace function public.cliente_do_usuario() returns uuid
language sql stable security definer set search_path = public as $$
  select (select cliente_id from public.perfis where id = auth.uid())
$$;

-- operação/admin veem tudo; cliente vê só o que é dele
drop policy if exists clientes_leitura on public.clientes;
create policy clientes_leitura on public.clientes for select
  using (public.papel_do_usuario() in ('operacao','admin') or id = public.cliente_do_usuario());

drop policy if exists embarcacoes_leitura on public.embarcacoes;
create policy embarcacoes_leitura on public.embarcacoes for select
  using (public.papel_do_usuario() in ('operacao','admin') or cliente_id = public.cliente_do_usuario());

drop policy if exists perfis_leitura on public.perfis;
create policy perfis_leitura on public.perfis for select
  using (id = auth.uid() or public.papel_do_usuario() in ('operacao','admin'));

-- câmera: o cliente NÃO pode ler ip/porta. A coluna é protegida por uma view de operação.
drop policy if exists cameras_leitura on public.cameras;
create policy cameras_leitura on public.cameras for select
  using (
    public.papel_do_usuario() in ('operacao','admin')
    or embarcacao_id in (
      select id from public.embarcacoes where cliente_id = public.cliente_do_usuario())
  );

drop policy if exists telemetria_leitura on public.telemetria_minuto;
create policy telemetria_leitura on public.telemetria_minuto for select
  using (
    public.papel_do_usuario() in ('operacao','admin')
    or embarcacao_id in (
      select id from public.embarcacoes where cliente_id = public.cliente_do_usuario())
    or fluxo_id in (
      select c.fluxo_id from public.cameras c join public.embarcacoes e on e.id = c.embarcacao_id
       where e.cliente_id = public.cliente_do_usuario())
  );

drop policy if exists link_leitura on public.link_amostras;
create policy link_leitura on public.link_amostras for select
  using (public.papel_do_usuario() in ('operacao','admin'));

-- Escrita: só pela Edge Function (service role ignora RLS). Nada de insert pelo navegador.
revoke insert, update, delete on public.telemetria_minuto, public.link_amostras from anon, authenticated;

-- A câmera, para o cliente, sai por esta view sem endereço nem credencial.
create or replace view public.v_cameras_cliente
with (security_invoker = true) as
select c.id, c.rotulo, c.fluxo_id, c.embarcacao_id, c.ativo
  from public.cameras c;

grant select on public.v_cameras_cliente to authenticated;

-- ------------------------------------------------------------------ Cron (30 dias)
-- Fecha/reprocessa a janela e aplica a retenção. Roda a cada hora (Supabase Cron, pg_cron).
select cron.schedule(
  'pipeline-fechar-janela',
  '7 * * * *',
  $$select public.fechar_janela(30)$$
);
