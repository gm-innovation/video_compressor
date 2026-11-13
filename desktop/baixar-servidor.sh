#!/usr/bin/env bash
# Baixa o que o instalador leva DENTRO dele para o cliente nao precisar instalar nada:
#   - Python portatil (embeddable, ~11 MB) -> tools/python/
#   - mediamtx (ja' usado na bancada)      -> tools/mediamtx/mediamtx.exe
# Nada aqui e' versionado: binario grande em repositorio e' lixo permanente.
#
# O download e' pelo Python (urllib) porque o curl desta maquina morre no arquivo grande com
# `curl: (23) client returned ERROR on write` (medido 13/11/2026). O curl fica como reserva.
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
PY_URL="https://www.python.org/ftp/python/3.12.7/python-3.12.7-embed-amd64.zip"
PY_SHA="0d57bb6cb078b74d23dbfe91f77d6780d45bed328911609f1f7ee2ba1606bf44"

PY=""
for cand in python python3 py; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done

nativo() {  # caminho MSYS (/c/...) -> caminho que o Python nativo do Windows entende (C:/...)
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

baixar() {  # $1=url  $2=destino  -> 0 se o arquivo chegou inteiro
  local t
  for t in 1 2 3 4; do
    rm -f "$2"
    if [ -n "$PY" ]; then
      "$PY" - "$1" "$(nativo "$2")" <<'PYF' && return 0
import sys, urllib.request
url, destino = sys.argv[1], sys.argv[2]
req = urllib.request.Request(url, headers={"User-Agent": "lecsor-build"})
with urllib.request.urlopen(req, timeout=1800) as r, open(destino, "wb") as f:
    while True:
        bloco = r.read(1 << 20)
        if not bloco:
            break
        f.write(bloco)
PYF
    fi
    if curl -fsSL --max-time 1800 -o "$2" "$1"; then return 0; fi
    echo "  tentativa $t falhou; recomecando em 5s" >&2
    sleep 5
  done
  return 1
}

# ---- Python portatil -----------------------------------------------------------------------
if [ ! -f "$RAIZ/tools/python/python.exe" ]; then
  WORK="$RAIZ/tools/.baixando"; rm -rf "$WORK"; mkdir -p "$WORK"; trap 'rm -rf "$WORK"' EXIT
  echo "baixando o Python portatil (embeddable 3.12.7)"
  baixar "$PY_URL" "$WORK/python.zip" || { echo "ERRO: nao consegui baixar $PY_URL"; exit 1; }
  OBTIDO="$(sha256sum "$WORK/python.zip" | awk '{print $1}')"
  [ "$OBTIDO" = "$PY_SHA" ] || { echo "ERRO: hash do Python nao confere (esperado $PY_SHA, obtido $OBTIDO)"; exit 1; }
  rm -rf "$RAIZ/tools/python"; mkdir -p "$RAIZ/tools/python"
  "$PY" - "$(nativo "$WORK/python.zip")" "$(nativo "$RAIZ/tools/python")" <<'PYF'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    z.extractall(sys.argv[2])
PYF
  echo "python portatil: $("$RAIZ/tools/python/python.exe" --version)"
else
  echo "python portatil ja existe: $("$RAIZ/tools/python/python.exe" --version)"
fi

# ---- mediamtx ------------------------------------------------------------------------------
if [ ! -f "$RAIZ/tools/mediamtx/mediamtx.exe" ]; then
  echo "baixando o mediamtx (v1.21.3)"
  WORK="$RAIZ/tools/.baixando"; mkdir -p "$WORK"
  MTX_URL="https://github.com/bluenviron/mediamtx/releases/download/v1.21.3/mediamtx_1.21.3_windows_amd64.zip"
  baixar "$MTX_URL" "$WORK/mediamtx.zip" || { echo "ERRO: nao consegui baixar $MTX_URL"; exit 1; }
  rm -rf "$RAIZ/tools/mediamtx"; mkdir -p "$RAIZ/tools/mediamtx"
  "$PY" - "$(nativo "$WORK/mediamtx.zip")" "$(nativo "$RAIZ/tools/mediamtx")" <<'PYF'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    z.extractall(sys.argv[2])
PYF
else
  echo "mediamtx ja existe: $(stat -c%s "$RAIZ/tools/mediamtx/mediamtx.exe") bytes"
fi

# ---- codigo do servidor --------------------------------------------------------------------
for f in ground/api.py ground/ingestao.py ground/mediamtx.yml ground/repasse.py ground/ferramentas.py admin/admin.js app/index.html db/schema.sql; do
  [ -s "$RAIZ/$f" ] || { echo "ERRO: falta $f (o instalador leva o servidor dentro: sem ele nao ha plug & play)"; exit 1; }
done
echo "ok: servidor pronto para empacotar (python $(stat -c%s "$RAIZ/tools/python/python.exe") B, mediamtx $(stat -c%s "$RAIZ/tools/mediamtx/mediamtx.exe") B)"
