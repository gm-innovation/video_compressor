#!/usr/bin/env bash
# Baixa o mediamtx (lado terra da bancada) para tools/mediamtx.
# Versao fixada: v1.21.3 windows_amd64. O binario nao vai para o repositorio.
set -euo pipefail
raiz="$(cd "$(dirname "$0")/.." && pwd)"
versao="${1:-v1.21.3}"
arquivo="$raiz/tools/mediamtx.zip"
url="https://github.com/bluenviron/mediamtx/releases/download/$versao/mediamtx_${versao#v}_windows_amd64.zip"
[ -f "$arquivo" ] || curl -fL "$url" -o "$arquivo"
rm -rf "$raiz/tools/mediamtx" && mkdir -p "$raiz/tools/mediamtx"
unzip -oq "$arquivo" -d "$raiz/tools/mediamtx"
echo "[ok] mediamtx $versao em tools/mediamtx (mediamtx.exe)"
