#!/usr/bin/env bash
# Simulador de link do satelite (somente Linux, exige root). Perfis do plano.
# uso: ./netem.sh aplicar 50 0.5 10   -> RTT 50ms, perda 0,5%, jitter 10ms
#      ./netem.sh limpar
set -euo pipefail
acao="${1:?uso: ./netem.sh aplicar <rtt_ms> <perda_%> <jitter_ms> | ./netem.sh limpar}"
iface="${IFACE:-eth0}"
case "$acao" in
  aplicar)
    rtt="${2:?rtt}"; perda="${3:?perda}"; jitter="${4:?jitter}"
    tc qdisc replace dev "$iface" root netem delay "${rtt}ms" "${jitter}ms" loss "${perda}%"
    echo "[ok] link simulado: RTT ${rtt}ms jitter ${jitter}ms perda ${perda}% em $iface" ;;
  limpar)
    tc qdisc del dev "$iface" root 2>/dev/null || true
    echo "[ok] link restaurado em $iface" ;;
  *) echo "acao invalida: $acao"; exit 2 ;;
esac
