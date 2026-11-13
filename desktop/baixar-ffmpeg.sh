#!/usr/bin/env bash
# Baixa o ffmpeg + ffprobe (Windows x64) para tools/ffmpeg/ e confere o SHA-256 de cada pacote
# contra um hash PINADO aqui. Eles vao EMBUTIDOS no instalador (extraResources): sem isso a maquina
# do cliente nao lista nem captura camera, porque a unica enumeracao de dispositivo e' o ffmpeg.
#
# O binario NAO entra no Git (tools/ffmpeg/ esta no .gitignore): ~200 MB de executavel no repositorio
# e' lixo permanente. Quem builda baixa; o build PARA se nao houver binario (nunca gera instalador
# sem o ffmpeg, porque ai o app instalado nasce incapaz de ver camera).
#
# DUAS FONTES, nesta ordem, porque o espelho do gyan.dev derruba o download de vez em quando. Medido
# em 13/11/2026: o `curl` desta maquina (MSYS 8.18) morre com `curl: (23) client returned ERROR on
# write` SEM criar o arquivo, em qualquer fonte e sem `-C -`; o mesmo arquivo veio inteiro pelo
# urllib do Python. O --retry do curl tambem nao cobre isso (erro de escrita e' erro de cliente).
# Por isso: download e extracao pelo Python quando existe (curl+unzip so como reserva), retentativa
# em loop, hash pinado por fonte e reserva para a segunda fonte.
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$RAIZ/tools/ffmpeg"

# nome|url|sha256 do .zip (pinado) | pasta dos binarios dentro do pacote
FONTES=(
  "essentials (gyan.dev)|https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip|60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba|bin"
  "github n8.1 (BtbN, tag fixa)|https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-11-13-12-43/ffmpeg-n8.1.3-35-gf1acb0a266-win64-gpl-8.1.zip|096d0596ba87ee534c6357797dc68882e714b53aac76859fca4be9c012a6a91c|bin"
)
PRIMEIRA="${FONTES[0]%%|*}"

if [ -f "$DEST/ffmpeg.exe" ] && [ "${LECSOR_FFMPEG_FORCAR:-0}" != "1" ]; then
  echo "ja existe: $DEST/ffmpeg.exe ($(stat -c%s "$DEST/ffmpeg.exe") bytes)"
  exit 0
fi

# O diretorio de trabalho fica FORA de tools/ffmpeg: o script apaga e recria DEST antes de copiar os
# binarios, e com o zip dentro dele o arquivo sumia no meio (medido em 13/11/2026).
WORK="$RAIZ/tools/.baixando"
rm -rf "$WORK"; mkdir -p "$WORK"
trap 'rm -rf "$WORK"' EXIT

PY=""
for cand in python python3 py; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done

nativo() {  # caminho do bash (MSYS: /c/...) -> caminho que o Python nativo do Windows entende (C:/...)
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

baixar_com_python() {  # $1=url  $2=destino
  [ -n "$PY" ] || return 1
  "$PY" - "$1" "$(nativo "$2")" <<'PYF'
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
}

baixar() {  # $1=url  $2=destino  -> 0 se o arquivo veio inteiro
  local tentativa
  for tentativa in 1 2 3 4; do
    rm -f "$2"
    if baixar_com_python "$1" "$2"; then return 0; fi
    if curl -fsSL --max-time 1800 -o "$2" "$1"; then return 0; fi
    echo "  tentativa $tentativa falhou; recomecando em 5s" >&2
    sleep 5
  done
  return 1
}

extrair_com_python() {  # $1=zip  $2=pasta de destino  -> 0 se os dois binarios sairam
  [ -n "$PY" ] || return 1
  "$PY" - "$(nativo "$1")" "$(nativo "$2")" <<'PYF'
import os, sys, zipfile
pacote, destino = sys.argv[1], sys.argv[2]
queridos = {"ffmpeg.exe": None, "ffprobe.exe": None}
with zipfile.ZipFile(pacote) as z:
    for info in z.infolist():
        base = os.path.basename(info.filename).lower()
        if base in queridos and queridos[base] is None and "/bin/" in info.filename.replace("\\", "/"):
            queridos[base] = info
    faltando = [b for b, i in queridos.items() if i is None]
    if faltando:
        print("nao estao no pacote: " + ", ".join(faltando))
        sys.exit(3)
    os.makedirs(destino, exist_ok=True)
    for base, info in sorted(queridos.items()):
        with z.open(info) as src, open(os.path.join(destino, base), "wb") as out:
            while True:
                bloco = src.read(1 << 20)
                if not bloco:
                    break
                out.write(bloco)
        print("%s: %d bytes" % (base, os.path.getsize(os.path.join(destino, base))))
PYF
}

ok=0
for fonte in "${FONTES[@]}"; do
  IFS='|' read -r nome url sha pasta <<<"$fonte"
  # LECSOR_FFMPEG_URL troca a PRIMEIRA fonte (serve para exercitar a reserva em teste).
  if [ "$nome" = "$PRIMEIRA" ] && [ -n "${LECSOR_FFMPEG_URL:-}" ]; then
    echo "fonte 1 trocada por LECSOR_FFMPEG_URL"; url="$LECSOR_FFMPEG_URL"; sha=""
  fi
  echo "baixando de $nome"
  echo "  $url"
  baixar "$url" "$WORK/ff.zip" || { echo "  nao baixou; tentando a proxima fonte" >&2; continue; }
  OBTIDO="$(sha256sum "$WORK/ff.zip" | awk '{print $1}')"
  if [ -n "$sha" ] && [ "$sha" != "$OBTIDO" ]; then
    echo "  ERRO: o hash nao confere (esperado $sha, obtido $OBTIDO); tentando a proxima fonte" >&2
    continue
  fi
  echo "  hash conferido: $OBTIDO"
  rm -rf "$DEST"; mkdir -p "$DEST"
  extraido=0
  if extrair_com_python "$WORK/ff.zip" "$DEST"; then
    extraido=1
  else
    rm -rf "$WORK/x"; mkdir -p "$WORK/x"
    if unzip -q -o "$WORK/ff.zip" -d "$WORK/x"; then
      for bin in ffmpeg.exe ffprobe.exe; do
        achado="$(find "$WORK/x" -name "$bin" -path "*$pasta*" | head -1)"
        [ -n "$achado" ] && cp "$achado" "$DEST/$bin"
      done
      [ -f "$DEST/ffmpeg.exe" ] && [ -f "$DEST/ffprobe.exe" ] && extraido=1
    fi
  fi
  if [ "$extraido" != "1" ]; then
    echo "  ERRO: nao consegui extrair ffmpeg.exe/ffprobe.exe do pacote de $nome; tentando a proxima fonte" >&2
    rm -rf "$DEST"
    continue
  fi
  ok=1
  echo "  binarios: ffmpeg.exe $(stat -c%s "$DEST/ffmpeg.exe") B, ffprobe.exe $(stat -c%s "$DEST/ffprobe.exe") B (fonte: $nome)"
  break
done

[ "$ok" = "1" ] || { echo "ERRO: nenhuma das fontes entregou os binarios"; exit 1; }

"$DEST/ffmpeg.exe" -hide_banner -version | head -1
echo "ok: binarios em $DEST"
