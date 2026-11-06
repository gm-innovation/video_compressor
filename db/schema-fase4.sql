-- Fase 4: fronts do cliente (app/) e do admin (admin/) + preparacao da Fase 5 (analises).
-- Mesma forma do alvo Postgres: sessao por usuario, auditoria de acesso ao video e evento de analise.

CREATE TABLE IF NOT EXISTS clientes (
  id     TEXT PRIMARY KEY,
  nome   TEXT NOT NULL,
  ativo  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS embarcacoes (
  id         TEXT PRIMARY KEY,
  cliente_id TEXT NOT NULL REFERENCES clientes(id),
  nome       TEXT NOT NULL,
  imo        TEXT DEFAULT '',
  estado     TEXT NOT NULL DEFAULT 'em operacao'
);

-- camera do produto: aponta para o fluxo que o lado terra publica. NAO guarda segredo de camera.
CREATE TABLE IF NOT EXISTS cameras (
  id            TEXT PRIMARY KEY,
  embarcacao_id TEXT NOT NULL REFERENCES embarcacoes(id),
  rotulo        TEXT NOT NULL,
  fluxo_id      TEXT NOT NULL,
  local         TEXT DEFAULT '',
  ativo         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS usuarios (
  id         TEXT PRIMARY KEY,
  email      TEXT NOT NULL UNIQUE,
  nome       TEXT NOT NULL,
  papel      TEXT NOT NULL CHECK (papel IN ('cliente','operador','admin')),
  cliente_id TEXT REFERENCES clientes(id),   -- cliente so ve a propria empresa
  senha_hash TEXT NOT NULL,
  salt       TEXT NOT NULL,
  interacoes INTEGER NOT NULL DEFAULT 200000,
  ativo      INTEGER NOT NULL DEFAULT 1,
  criado_em  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessoes (
  token      TEXT PRIMARY KEY,
  usuario_id TEXT NOT NULL REFERENCES usuarios(id),
  criado_em  TEXT NOT NULL DEFAULT (datetime('now')),
  expira_em  TEXT NOT NULL,
  user_agent TEXT DEFAULT ''
);

-- quem viu qual camera, quando (LGPD: imagem de pessoa identificavel)
CREATE TABLE IF NOT EXISTS auditoria_acesso (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  usuario_id TEXT,
  email      TEXT,
  acao       TEXT NOT NULL,
  alvo       TEXT NOT NULL,
  em         TEXT NOT NULL DEFAULT (datetime('now')),
  ip         TEXT DEFAULT ''
);

-- modulo de acompanhamento: documento que o admin exporta pelo proprio sistema
CREATE TABLE IF NOT EXISTS documentos (
  slug         TEXT PRIMARY KEY,
  titulo       TEXT NOT NULL,
  caminho      TEXT NOT NULL,
  versao       TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'atual' CHECK (status IN ('atual','desatualizado','obsoleto')),
  atualizado_em TEXT NOT NULL
);

-- Fase 5: o agente de analise a bordo sobe EVENTO e CONTAGEM (nao o video)
CREATE TABLE IF NOT EXISTS analytics_eventos (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  camera_id  TEXT NOT NULL REFERENCES cameras(id),
  tipo       TEXT NOT NULL,                 -- ex.: contagem, zona_restrita, sem_epi
  inicio     TEXT NOT NULL,
  fim        TEXT,
  confianca  REAL,
  clipe      TEXT DEFAULT '',
  metadados  TEXT NOT NULL DEFAULT '{}',
  criado_em  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS analytics_contagens (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  camera_id    TEXT NOT NULL REFERENCES cameras(id),
  janela_inicio TEXT NOT NULL,
  janela_fim    TEXT NOT NULL,
  entrou       INTEGER NOT NULL DEFAULT 0,
  saiu         INTEGER NOT NULL DEFAULT 0,
  pico         INTEGER NOT NULL DEFAULT 0,
  fonte        TEXT NOT NULL DEFAULT '',   -- medicao/evidencia que sustenta o numero
  criado_em    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- decisoes (ADR) registradas pelo admin: o plano e o codigo consultam a mesma fonte
CREATE TABLE IF NOT EXISTS decisoes (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  data     TEXT NOT NULL,
  titulo   TEXT NOT NULL,
  texto    TEXT NOT NULL,
  autor    TEXT NOT NULL,
  fase_id  TEXT REFERENCES fases(id),
  criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
