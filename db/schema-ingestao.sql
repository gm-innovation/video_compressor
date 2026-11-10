-- Fase 5/7 — ingestao de video de teste (arquivo enviado ou link)
-- Permite provar compressao e streaming antes de ter imagem real de embarcacao.
CREATE TABLE IF NOT EXISTS ingestoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fluxo_id TEXT NOT NULL,            -- caminho no mediamtx (SRT)
  camera_id TEXT,                    -- id na tabela cameras (para aparecer nas telas)
  rotulo TEXT NOT NULL,
  fonte TEXT NOT NULL,               -- arquivo em disco ou endereco http(s)
  tipo TEXT NOT NULL,                -- 'arquivo' | 'url'
  repetir INTEGER DEFAULT 1,         -- 1 = fica em repeticao (parece ao vivo)
  codec TEXT DEFAULT 'libx264',
  bitrate_alvo TEXT,
  resolucao TEXT, fps_nativo REAL,
  bitrate_entrada_kbps REAL, bitrate_saida_kbps REAL, corte_pct REAL,
  fps REAL, velocidade REAL, tamanho_mb REAL, duracao_s REAL,
  estado TEXT DEFAULT 'iniciando',   -- iniciando | no_ar | parado | erro
  pid INTEGER, erro TEXT, log TEXT,
  srt_host TEXT,                     -- onde o fluxo foi publicado (127.0.0.1 = esta maquina; IP = lado terra)
  criado_em TEXT, atualizado_em TEXT, parado_em TEXT
);
CREATE TABLE IF NOT EXISTS ingestoes_amostras (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ingestao_id INTEGER NOT NULL,
  em TEXT NOT NULL,
  taxa_saida_kbps REAL, fps REAL, velocidade REAL, tamanho_mb REAL, corte_pct REAL
);
