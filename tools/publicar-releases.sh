#!/usr/bin/env bash
# Publica as releases com a credencial que o git usa (GCM). Nada de segredo na linha de comando:
# o valor vai por variavel de ambiente, lido do git credential fill.
cd "C:/Users/EngenhariaGoogleMari/lecsor-pipeline-video" || exit 1
export GITHUB_TOKEN_FOR_RELEASES
GITHUB_TOKEN_FOR_RELEASES=$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill | sed -n 's/^password=//p')
[ -n "$GITHUB_TOKEN_FOR_RELEASES" ] || { echo "sem credencial do git (GCM)"; exit 2; }
python tools/publicar-releases.py
echo "PUBLICACAO_rc=$?"
