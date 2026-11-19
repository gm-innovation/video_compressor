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
--  * o HISTORICO nunca e' apagado (dono, 18/11/2026): sempre se sabe quais acoes foram tomadas e por
--    quem. O que e' apagado e' o ARQUIVO de video, e so' quando o cliente saiu da tela (tabela
--    `gravacoes`: a LINHA fica, com a hora em que o arquivo saiu).

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

-- Teto do PRODUTO (quem define e' o administrador): nenhum cliente passa disso, por mais que a tela
-- dele ofereca mais. Uma linha so': chave = 'tempo_maximo_do_produto' (valor em segundos; ausente = sem
-- teto). O cliente ve a lista JA' cortada pelo teto, e o servidor corta de novo no pedido.
CREATE TABLE IF NOT EXISTS configs_do_produto (
  chave         TEXT PRIMARY KEY,
  valor         TEXT NOT NULL,
  atualizado_em TEXT NOT NULL
);

-- ---------------------------------------------------------------------------------------------
-- FLAG DE ESTADO (dono, 19/11/2026). O computador de captura a bordo NAO tem porta aberta: a unica
-- certeza e' de que ele PODE ENVIAR (sair). Entao a informacao nao vai de terra para bordo — o bordo
-- e' quem OLHA para terra, e quando a flag muda ele inicia ou para a transmissao.
--   `desejo_camera`  = o que TERRA quer (com versao: o bordo so' age quando a versao muda);
--   `estado_bordo`   = o que o BORDO conta que realmente esta' no ar (quem manda no "de verdade").
CREATE TABLE IF NOT EXISTS desejo_camera (
  camera_id      TEXT PRIMARY KEY,
  embarcacao_id  TEXT NOT NULL DEFAULT '',
  desejo         TEXT NOT NULL DEFAULT 'parar',   -- ligar | parar
  versao         INTEGER NOT NULL DEFAULT 0,      -- sobe a cada mudanca de desejo
  motivo         TEXT DEFAULT '',                 -- por que, em portugues (vai para a tela e a trilha)
  transmissao_id TEXT DEFAULT '',                 -- a sessao que sustenta o "ligar" (se houver)
  manual         TEXT NOT NULL DEFAULT '',        -- '' | 'ligar' | 'parar' (o operador ligou/desligou na mao)
  atualizado_em  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS estado_bordo (
  camera_id      TEXT PRIMARY KEY,
  embarcacao_id  TEXT NOT NULL DEFAULT '',
  estado         TEXT NOT NULL DEFAULT '',        -- no_ar | parado | erro | sem_entrada
  motivo         TEXT DEFAULT '',
  fluxo_id       TEXT DEFAULT '',
  desde          TEXT DEFAULT '',
  gravando       INTEGER NOT NULL DEFAULT 0,
  versao_desejo  INTEGER NOT NULL DEFAULT 0,      -- a versao do desejo que ele estava lendo
  atualizado_em  TEXT NOT NULL
);

-- HD do RADAR no PC de captura (dono, 19/11/2026): a gravacao continua mora no BORDO; terra guarda so' o
-- CATALOGO (o que existe, por horario) para o cliente pesquisar. O video so' sobe quando o cliente PEDE
-- um trecho — e quem envia e' o bordo (nunca terra alcancando o bordo).
CREATE TABLE IF NOT EXISTS hd_catalogo (
  embarcacao_id TEXT NOT NULL,
  camera_id     TEXT NOT NULL,
  resumo        TEXT DEFAULT '',                  -- JSON do resumo (blocos, bytes, primeiro, ultimo, livre)
  blocos        TEXT DEFAULT '',                  -- JSON da lista recente de blocos (arquivo/inicio/bytes)
  atualizado_em TEXT NOT NULL,
  PRIMARY KEY (embarcacao_id, camera_id)
);

CREATE TABLE IF NOT EXISTS hd_pedidos (
  id            TEXT PRIMARY KEY,
  embarcacao_id TEXT NOT NULL DEFAULT '',
  camera_id     TEXT NOT NULL DEFAULT '',
  arquivo       TEXT NOT NULL DEFAULT '',          -- o bloco pedido (nome no HD do bordo)
  usuario_email TEXT NOT NULL DEFAULT '',
  estado        TEXT NOT NULL DEFAULT 'pedido',   -- pedido | enviado | erro
  trecho        TEXT DEFAULT '',                   -- nome do arquivo que chegou em terra
  bytes         INTEGER NOT NULL DEFAULT 0,
  motivo        TEXT DEFAULT '',
  criado_em     TEXT NOT NULL,
  pronto_em     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_hd_pedidos_pendentes ON hd_pedidos(embarcacao_id, estado);



-- Ficha da GRAVACAO no lado terra (dono, 18/11/2026): a VPS mantem so' o arquivo que foi gravado, e so'
-- ate' o cliente baixar. O cliente e' AVISADO quando o arquivo fica pronto; quando ele sai da tela (ou
-- desliga o sistema), o arquivo e' apagado. A LINHA daqui NAO e' apagada: `apagada_em` diz quando o
-- arquivo saiu, e a auditoria guarda quem pediu, quem gravou, quem baixou e quem apagou (nada de
-- historico se perde — so' o video, que sai junto com o cliente).
CREATE TABLE IF NOT EXISTS gravacoes (
  transmissao_id TEXT PRIMARY KEY,
  embarcacao_id  TEXT NOT NULL,
  usuario_email  TEXT NOT NULL,
  camera_id      TEXT NOT NULL,
  comecou_em     TEXT NOT NULL,
  bytes          INTEGER NOT NULL DEFAULT 0,
  segundos       INTEGER NOT NULL DEFAULT 0,
  pronta_em      TEXT DEFAULT '',              -- quando o arquivo ficou pronto para o cliente baixar
  avisada_em     TEXT DEFAULT '',              -- quando o cliente foi avisado na tela
  baixada_em     TEXT DEFAULT '',              -- quando o cliente baixou
  apagada_em     TEXT DEFAULT ''               -- quando o ARQUIVO foi apagado (a linha fica)
);
CREATE INDEX IF NOT EXISTS ix_gravacoes_do_cliente ON gravacoes(usuario_email, apagada_em);

-- ---------------------------------------------------------------------------------------------
-- ESPELHO DO CADASTRO NO SUPABASE (dono, 19/11/2026). O dono abriu a tabela `cameras` da nuvem e viu
-- 1 linha enquanto a VPS tinha 16: o cadastro so' era gravado aqui. O lado terra (unico com a chave de
-- servico) passa a fazer upsert em `public.cameras`; o SQLite continua sendo o banco de OPERACAO (o ao
-- vivo nao depende da nuvem) e o Supabase a base de verdade do cadastro.
-- Esta tabela e' a PONTE: no Supabase a embarcacao e' uuid, aqui e' texto (`'bancada'`). Sem a ponte o
-- upsert da camera falharia por chave estrangeira (a camera aponta para a embarcacao).
CREATE TABLE IF NOT EXISTS embarcacoes_supabase (
  slug           TEXT PRIMARY KEY,      -- a embarcacao como esta' aqui (ex.: 'bancada')
  uuid           TEXT NOT NULL,         -- o id dela no Supabase
  nome           TEXT DEFAULT '',
  atualizado_em  TEXT NOT NULL
);
