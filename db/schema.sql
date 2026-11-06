-- Schema do modulo de documentacao e acompanhamento (mesma forma do alvo Postgres).
-- Regra central: medicao sem valor+fonte+data+hardware_versao+comando NAO entra (NOT NULL).
CREATE TABLE IF NOT EXISTS fases (
  id              TEXT PRIMARY KEY,
  numero          INTEGER NOT NULL,
  nome            TEXT NOT NULL,
  prioridade      TEXT NOT NULL CHECK (prioridade IN ('P0','P1','P2')),
  status          TEXT NOT NULL CHECK (status IN ('pendente','em andamento','concluida','bloqueada')),
  criterio_aceite TEXT NOT NULL,
  evidencia       TEXT NOT NULL DEFAULT '',
  -- fase nao fecha sem evidencia anexada
  CHECK (status <> 'concluida' OR length(trim(evidencia)) > 0)
);

CREATE TABLE IF NOT EXISTS medicoes (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  valor           TEXT NOT NULL,
  fonte           TEXT NOT NULL,
  data            TEXT NOT NULL,
  hardware_versao TEXT NOT NULL,
  comando         TEXT NOT NULL,
  fase_id         TEXT REFERENCES fases(id),
  status          TEXT NOT NULL DEFAULT 'valida' CHECK (status IN ('valida','obsoleta')),
  criado_em       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS inventario_cameras (
  id              TEXT PRIMARY KEY,
  fabricante_modelo TEXT, ip TEXT, porta TEXT, protocolo TEXT, canal_gravador TEXT,
  resolucao TEXT, fps TEXT, codec_nativo TEXT,
  credencial_ref  TEXT,          -- referencia ao cofre/ambiente; o segredo nunca entra aqui
  local_instalacao TEXT, restricao_acesso TEXT
);

CREATE TABLE IF NOT EXISTS evidencias (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  fase_id   TEXT REFERENCES fases(id),
  caminho   TEXT NOT NULL,
  descricao TEXT NOT NULL,
  data      TEXT NOT NULL
);
