#!/usr/bin/env bash
# Gera os instaladores do produto. Cada um nasce com um PAPEL (papeis.json), que decide o que vem
# configurado de fabrica: o PC de captura nasce apontado para si mesmo (127.0.0.1:8765) e com o
# servidor local ligado; o lado terra nasce apontado para o servidor. O cliente nao edita JSON.
#
# Tudo o que o app precisa roda DENTRO do pacote: ffmpeg, mediamtx, Python portatil e o codigo do
# servidor (resources/servidor). Sem qualquer um deles o build PARA — instalador pela metade e'
# instalador quebrado na casa do cliente.
set -e -o pipefail
cd "$(dirname "$0")"
VERSAO=$(node -p "require('./package.json').version")

bash ./baixar-ffmpeg.sh
bash ./baixar-servidor.sh
for b in ../tools/ffmpeg/ffmpeg.exe ../tools/ffmpeg/ffprobe.exe ../tools/python/python.exe \
         ../tools/mediamtx/mediamtx.exe ../ground/api.py ../ground/repasse.py ../admin/admin.js \
         ../fronts/vms.css ../fronts/admin.css ../fronts/video.js; do
  [ -s "$b" ] || { echo "ERRO: $b ausente — o instalador precisa dele dentro do pacote"; exit 1; }
done

construir() {
  nome="$1"; superficie="$2"; papel="$3"; id="$4"; leva_ambiente="$5"
  echo "== instalador: $nome (superficie $superficie, papel $papel)"
  # O ambiente (Supabase + token de ingestao + embarcacao) vai DENTRO do pacote do PC de captura,
  # que precisa nascer configurado; nos papeis que so' mostram tela ele sai, para nao distribuir
  # segredo sem necessidade. O arquivo fica fora do git (desktop/ambiente.json).
  if [ "$leva_ambiente" = "1" ] && [ -s ./ambiente.json ]; then
    cp ./ambiente.json ../ground/ambiente.json
  else
    rm -f ../ground/ambiente.json
    [ "$leva_ambiente" = "1" ] && echo "AVISO: desktop/ambiente.json ausente — o pacote vai SEM Supabase/token de ingestao"
  fi
  npx electron-builder --win nsis \
    --config.productName="$nome" \
    --config.appId="br.com.lecsor.pipelinevideo.$id" \
    --config.extraMetadata.superficie="$superficie" \
    --config.extraMetadata.papel="$papel" \
    --config.extraMetadata.productName="$nome" \
    --config.nsis.shortcutName="$nome" \
    --config.directories.output="dist/$id" \
    --config.win.artifactName="${nome// /-}-${VERSAO}-x64.exe" 2>&1 | tail -6
  rm -f ../ground/ambiente.json
}

# PC de captura: camaras ligadas nesta maquina, servidor local no ar, repassa para o lado terra.
construir "LECSOR Captura" admin captura captura 1
# Lado terra: recebe e mostra (servidor em nuvem ou na rede do cliente).
construir "LECSOR Terra" cliente terra terra 0
# Bancada/engenharia e os dois papeis de tela antigos (mesmo pacote, papel do lado terra).
construir "LECSOR Admin" admin terra admin 0
construir "LECSOR Cliente" cliente terra cliente 0
echo "== pronto:"; ls -la dist/*/*.exe 2>/dev/null | grep -v uninstaller
