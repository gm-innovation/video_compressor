-- Escopos de acesso do cliente (dono, 19/11/2026): "cliente que pode ver apenas uma embarcacao da
-- empresa / algumas embarcacoes da empresa / todas da empresa / todas de todas as empresas (Petrobras)".
--
-- Este e' o vinculo EXPLICITO por embarcacao. Regra unica (ver `pode_ver_embarcacao` no api.py):
--   * com vinculo aqui -> o cliente ve EXATAMENTE as embarcacoes listadas (tipos 1 e 2);
--   * sem vinculo nenhum -> ve todas as embarcacoes do proprio `cliente_id` (tipo 3, o comportamento
--     que ja' existia — instalacao antiga NAO perde acesso);
--   * papel `observador` (Petrobras) -> ve tudo, so' leitura (tipo 4).
CREATE TABLE IF NOT EXISTS usuario_embarcacoes (
  usuario_id    TEXT NOT NULL REFERENCES usuarios(id),
  embarcacao_id TEXT NOT NULL REFERENCES embarcacoes(id),
  concedido_em  TEXT NOT NULL DEFAULT (datetime('now')),
  concedido_por TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (usuario_id, embarcacao_id)
);

CREATE INDEX IF NOT EXISTS idx_usuario_embarcacoes_usuario ON usuario_embarcacoes(usuario_id);
