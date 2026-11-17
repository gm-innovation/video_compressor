-- Transmissao a pedido do cliente (17/11/2026).
-- Plano: .hermes/plans/2026-11-17-transmissao-a-pedido-do-cliente.md
--
-- Regras que este banco sustenta:
--  * quem pede e' APENAS o cliente (dono da embarcacao), pela tela web (/app) — sem app instalado;
--  * a ORDEM NASCE no lado terra e vai ate' o bordo (o bordo nao abre porta nenhuma: ele e' quem
--    mantem a ligacao e recebe a ordem);
--  * o corte e' POR SESSAO: fechar a tela/desligar derruba a sessao de quem fechou; se outro cliente
--    esta' vendo, a transmissao continua para ele;
--  * ao estourar o tempo maximo a transmissao PARA e o cliente inicia de novo — a menos que esteja
--    GRAVANDO (a gravacao mora no lado terra, do video que ja' chegou pela rede);
--  * NADA e' apagado: `transmissoes` e' o historico de tudo que foi feito.

CREATE TABLE IF NOT EXISTS transmissoes (
  id            TEXT PRIMARY KEY,
  seq           INTEGER NOT NULL DEFAULT 0,
  embarcacao_id TEXT NOT NULL,
  camera_id     TEXT NOT NULL,
  fluxo_id      TEXT DEFAULT '',
  usuario_email TEXT DEFAULT '',
  segundos_max  INTEGER NOT NULL DEFAULT 0,     -- teto escolhido na tela de configuracao (0 = sem teto)
  criada_em     TEXT NOT NULL,
  batimento_em  TEXT NOT NULL,                  -- ultimo "estou aqui" da tela do cliente
  termina_em    TEXT DEFAULT '',                -- criada_em + segundos_max
  encerrada_em  TEXT DEFAULT '',
  -- pedida -> no_ar -> (encerrada | expirada | sem_sinal | erro)
  estado        TEXT NOT NULL DEFAULT 'pedida',
  motivo        TEXT DEFAULT '',                -- por que terminou, em portugues, para o historico
  gravando      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_transmissoes_ativas ON transmissoes(embarcacao_id, estado);
CREATE INDEX IF NOT EXISTS ix_transmissoes_hist   ON transmissoes(embarcacao_id, criada_em);

-- Fila de ordens do lado terra para o bordo (o agente do bordo pergunta e obedece direto: nao ha
-- tecnico confirmando nada na embarcacao).
CREATE TABLE IF NOT EXISTS ordens_do_bordo (
  id             TEXT PRIMARY KEY,
  seq            INTEGER NOT NULL,
  embarcacao_id  TEXT NOT NULL,
  camera_id      TEXT NOT NULL,
  fluxo_id       TEXT DEFAULT '',
  acao           TEXT NOT NULL,                 -- iniciar | parar
  transmissao_id TEXT DEFAULT '',
  motivo         TEXT DEFAULT '',
  criado_em      TEXT NOT NULL,
  entregue_em    TEXT DEFAULT '',
  atendida_em    TEXT DEFAULT '',
  estado         TEXT NOT NULL DEFAULT 'pedido',-- pedido | entregue | atendida | erro
  resultado      TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_ordens_do_bordo ON ordens_do_bordo(embarcacao_id, seq);

-- Tela de configuracao do cliente: quanto tempo cada transmissao pode durar.
CREATE TABLE IF NOT EXISTS configs_do_cliente (
  usuario_id     TEXT PRIMARY KEY,
  tempo_maximo_s INTEGER NOT NULL DEFAULT 900,
  atualizado_em  TEXT NOT NULL
);
