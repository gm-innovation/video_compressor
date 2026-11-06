#!/usr/bin/env bash
# Teste negativo (Fase 0-A): o script de captura tem de falhar com erro legivel
# quando falta credencial, e nunca imprimir a senha.
set -uo pipefail
cd "$(dirname "$0")/.."
saida=$(env -u CAM_URL -u CAM_USER -u CAM_PASS bash bench/fetch-camera.sh 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 0 ]; then echo "[FALHA] fetch-camera.sh deveria falhar sem credencial"; exit 1; fi
echo "[ok] falhou como esperado (rc=$rc)"
echo "$saida" | grep -q "CAM_URL nao definido" && echo "[ok] mensagem legivel" || { echo "[FALHA] mensagem inesperada: $saida"; exit 1; }
echo "$saida" | grep -qi "senha" && { echo "[FALHA] saida menciona senha"; exit 1; } || echo "[ok] nenhuma senha na saida"
