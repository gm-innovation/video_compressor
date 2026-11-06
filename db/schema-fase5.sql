-- Fase 5: analises de video. O agente de bordo sobe EVENTO, CONTAGEM e o estado do proprio agente.
-- Nada aqui guarda video nem credencial de camera: so numero, evento e metadado.

-- estado do agente de analise que roda a bordo (uma linha por camera analisada)
CREATE TABLE IF NOT EXISTS analytics_agentes (
  camera_id   TEXT PRIMARY KEY REFERENCES cameras(id),
  nome        TEXT NOT NULL DEFAULT '',      -- identificacao do agente (ex.: agente-bordo-01)
  modelo      TEXT NOT NULL DEFAULT '',      -- modelo usado (ex.: yolov10n.onnx)
  fonte       TEXT NOT NULL DEFAULT '',      -- de onde ele le (fluxo publicado na embarcacao)
  fps         REAL NOT NULL DEFAULT 0,       -- quadros analisados por segundo
  quadros     INTEGER NOT NULL DEFAULT 0,    -- quadros analisados no total
  estado      TEXT NOT NULL DEFAULT 'iniciando' CHECK (estado IN ('iniciando','no ar','sem sinal','parado')),
  caixas      TEXT NOT NULL DEFAULT '[]',    -- ultimas caixas detectadas (JSON) para desenhar na tela
  linhas      TEXT NOT NULL DEFAULT '[]',    -- marcas configuradas (JSON)
  erros       INTEGER NOT NULL DEFAULT 0,
  ultimo_visto TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_analytics_eventos_camera ON analytics_eventos(camera_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_contagens_camera ON analytics_contagens(camera_id, id DESC);
