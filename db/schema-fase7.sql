-- LICENCA de ativacao do PC de captura (dono, 19/11/2026).
--
-- "quero apenas instalar o app no computador de captura, inserir a chave da licenca e assim fazer a
-- conexao com a empresa e embarcacao cadastradas, e a licenca pode ser configuravel por tempo ou
-- indeterminado".
--
-- Antes disto o PC de captura era preso a embarcacao NO BUILD (o `ambiente.json` copiado para dentro
-- do pacote): cada barco exigia outro instalador. Agora a chave e' que diz o barco.
--
-- Decisoes do dono que estao no desenho desta tabela:
--   * a licenca e' por EMBARCACAO (a empresa sai de `embarcacoes.cliente_id`);
--   * `validade_tipo` = 'indeterminada' (sem prazo) ou 'ate' (`validade_em` = AAAA-MM-DD);
--   * quantos PCs usam a mesma licenca e' AJUSTAVEL (`maquinas_max`), contado em `licenca_usos`;
--   * a chave fica RECUPERAVEL (o admin pode ver e copiar de novo — pedido do dono), e mesmo assim
--     nunca entra em log nem na auditoria: a auditoria guarda a PEGADA (sha256 curto), nao a chave;
--   * revogar e' um estado (`status`), nunca um DELETE: a trilha tem que continuar sabendo.
CREATE TABLE IF NOT EXISTS licencas (
  id            TEXT PRIMARY KEY,
  chave         TEXT NOT NULL UNIQUE,
  embarcacao_id TEXT NOT NULL REFERENCES embarcacoes(id),
  validade_tipo TEXT NOT NULL DEFAULT 'indeterminada'
                CHECK (validade_tipo IN ('indeterminada','ate')),
  validade_em   TEXT NOT NULL DEFAULT '',              -- AAAA-MM-DD quando `validade_tipo='ate'`
  maquinas_max  INTEGER NOT NULL DEFAULT 1,            -- ajustavel pelo admin (dono, 19/11/2026)
  status        TEXT NOT NULL DEFAULT 'ativa' CHECK (status IN ('ativa','revogada')),
  motivo        TEXT NOT NULL DEFAULT '',              -- por que foi revogada/alterada (trilha)
  criada_por    TEXT NOT NULL DEFAULT '',
  criada_em     TEXT NOT NULL DEFAULT (datetime('now')),
  alterada_em   TEXT NOT NULL DEFAULT '',
  revogada_em   TEXT NOT NULL DEFAULT '',
  ultimo_uso_em TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_licencas_embarcacao ON licencas(embarcacao_id);

-- Quais maquinas usaram cada licenca (contagem do `maquinas_max`). Guarda a IMPRESSAO da maquina
-- (`hostname-hash do MAC`), nunca a chave: e' o que permite dizer "esta licenca ja' esta' em 2 PCs".
CREATE TABLE IF NOT EXISTS licenca_usos (
  licenca_id  TEXT NOT NULL REFERENCES licencas(id),
  maquina     TEXT NOT NULL,
  primeiro_em TEXT NOT NULL DEFAULT (datetime('now')),
  ultimo_em   TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (licenca_id, maquina)
);
