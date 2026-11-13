#!/usr/bin/env bash
# Baixa o ffmpeg + ffprobe (build "essentials", Windows x64) para tools/ffmpeg/ e confere o SHA-256
# publicado pelo fornecedor. Eles vao EMBUTIDOS no instalador (extraResources): sem isso a maquina
# do cliente nao lista nem captura camera, porque a unica enumeracao de dispositivo e' o ffmpeg.
#
# O binario NAO entra no Git (tools/ffmpeg/ esta no .gitignore): ~90 MB de executavel no repositorio
# e' lixo permanente. Quem builda baixa; o build PARA se nao houver binario (nunca gera instalador
# sem o ffmpeg, porque ai o app instalado nasce incapaz de ver camera).
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$RAIZ/tools/ffmpeg"
URL="${LECSOR_FFMPEG_URL:-https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip}"

if [ -f "$DEST/ffmpeg.exe" ] && [ "${LECSOR_FFMPEG_FORCAR:-0}" != "1" ]; then
  echo "ja existe: $DEST/ffmpeg.exe ($(stat -c%s "$DEST/ffmpeg.exe") bytes)"
  exit 0
fi

echo "baixando $URL"
# O download acontece AO LADO do destino, nao em mktemp do /tmp: escrevendo no /tmp o curl morria
# com "client returned ERROR on write" (erro 23) e o binario nunca chegava.
WORK="$DEST/_baixando"
mkdir -p "$WORK"
trap 'rm -rf "$WORK"' EXIT
# SEM `-C -`: com retry o resume confunde o offset e o curl morre com "client returned ERROR on
# write" (erro 23). O --retry do proprio curl recomeca limpo e e' o que funciona nesta maquina.
curl -fsSL --retry 6 --retry-delay 3 --retry-connrefused --max-time 1800 -o "$WORK/ff.zip" "$URL"
curl -fsSL --retry 3 --max-time 120 -o "$WORK/ff.sha256" "$URL.sha256"

# O arquivo .sha256 publicado pode trazer "<hash>  <nome>" ou so' o hash: aceita os dois.
ESPERADO="$(awk '{print $1}' "$WORK/ff.sha256" | tr -d '\r' | head -1)"
case "$ESPERADO" in
  ""|*[!0-9a-fA-F]*) echo "ERRO: nao consegui ler um hash valido em $URL.sha256"; exit 1 ;;
esac
OBTIDO="$(sha256sum "$WORK/ff.zip" | awk '{print $1}')"
[ "$ESPERADO" = "$OBTIDO" ] || { echo "ERRO: o hash do pacote baixado NAO confere"; echo " esperado $ESPERADO"; echo " obtido   $OBTIDO"; exit 1; }
echo "hash conferido: $OBTIDO"

unzip -q -o "$WORK/ff.zip" -d "$WORK/x"
mkdir -p "$DEST"
for bin in ffmpeg.exe ffprobe.exe; do
  achado="$(find "$WORK/x" -name "$bin" -path '*bin*' | head -1)"
  [ -n "$achado" ] || { echo "ERRO: $bin nao esta no pacote baixado"; exit 1; }
  cp "$achado" "$DEST/$bin"
  echo "$bin: $(stat -c%s "$DEST/$bin") bytes"
done

"$DEST/ffmpeg.exe" -hide_banner -version | head -1
echo "ok: binarios em $DEST"
