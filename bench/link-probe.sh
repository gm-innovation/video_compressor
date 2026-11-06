#!/usr/bin/env bash
# Fase 0-B: mede RTT/jitter/perda do link ate o host do lado terra.
# Linux: tc netem simula o link. Windows: usar Clumsy (jagt.github.io/clumsy) com os mesmos valores.
# RTT de referencia do Starlink (spec oficial): 25-50 ms. Buffer SRT = 4-5x RTT.
set -euo pipefail
alvo="${1:?uso: ./link-probe.sh <host-do-lado-terra> [janelas]}"
janelas="${2:-20}"
ping -n 1 "$alvo" >/dev/null 2>&1 || true
if command -v ping >/dev/null && ping -c 1 -W 2 "$alvo" >/dev/null 2>&1; then
  ping -c "$janelas" "$alvo" | tail -3
else
  # Windows (MSYS): -n e -w em ms
  ping -n "$janelas" -w 2000 "$alvo" | tail -5
fi
