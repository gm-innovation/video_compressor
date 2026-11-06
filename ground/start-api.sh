#!/usr/bin/env bash
# Sobe a API do produto carregando as credenciais locais (ground/.env.local, fora do git).
cd "$(dirname "$0")/.."
set -a; . ground/.env.local; set +a
exec python ground/api.py "${1:-8765}"
