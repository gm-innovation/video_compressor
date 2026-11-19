-- Papel `observador` (Petrobras, tipo 4 do dono 19/11/2026): ve TODAS as embarcacoes de TODAS as
-- empresas, e SO' LEITURA (nenhuma rota de escrita/operacao aceita este papel — elas checam PAPEL_ADMIN).
--
-- SQLite nao altera um CHECK no lugar, entao a tabela e' recriada preservando TODAS as linhas e os
-- vinculos (sessoes.usuario_id, auditoria_acesso.usuario_id, usuario_embarcacoes.usuario_id). Rodado
-- pelo `inicializar()` da API quando ele ve' o CHECK antigo — toda instalacao que atualiza se conserta
-- sozinha, sem passo manual na casa do cliente. Rodar duas vezes nao faz mal.
PRAGMA foreign_keys = OFF;
BEGIN;
CREATE TABLE usuarios_novo (
  id         TEXT PRIMARY KEY,
  email      TEXT NOT NULL UNIQUE,
  nome       TEXT NOT NULL,
  papel      TEXT NOT NULL CHECK (papel IN ('cliente','operador','admin','tecnico','observador')),
  cliente_id TEXT REFERENCES clientes(id),
  senha_hash TEXT NOT NULL,
  salt       TEXT NOT NULL,
  interacoes INTEGER NOT NULL DEFAULT 200000,
  ativo      INTEGER NOT NULL DEFAULT 1,
  criado_em  TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO usuarios_novo (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo,criado_em)
  SELECT id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo,criado_em FROM usuarios;
DROP TABLE usuarios;
ALTER TABLE usuarios_novo RENAME TO usuarios;
COMMIT;
PRAGMA foreign_keys = ON;
