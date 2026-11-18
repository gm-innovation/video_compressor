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
    # Nao e' aviso: pacote de PC de captura SEM ambiente nasce mudo — o anuncio do cadastro ao lado
    # terra falha em silencio e a camera nao aparece na tela do cliente (medido 18/11/2026). Falha
    # o build, que e' barato, em vez de descobrir em campo.
    if [ "$leva_ambiente" = "1" ]; then
      echo "ERRO: desktop/ambiente.json ausente — o pacote $nome nasceria SEM Supabase/token de ingestao/embarcacao."
      echo "      Coloque o ambiente.json (fora do git) em desktop/ e rode de novo."
      return 1
    fi
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

# APLICATIVO UNICO (dono, 17/11/2026): "vamos empacotar em um app apenas, o tipo de app e' definido
# pela role do usuario". O pacote nasce no papel `unico` e abre a tela de ENTRADA (/entrada), que
# entra e manda para a tela do papel de quem entrou (cliente -> /app, operacao/admin -> /admin,
# tecnico -> / = "Enviar video"). Leva o ambiente (Supabase + token de ingestao): e' o MESMO pacote
# que pode capturar, pela opcao "Liberar as funcoes de captura nesta maquina".
#
# Os quatro instaladores antigos (Captura/Terra/Admin/Cliente) sairam de linha: um pacote so' os
# substitui, e o papel da INSTALACAO deixou de decidir o que aparece na tela — quem decide e' a role
# do usuario que entra. `construir` continua aceitando os papeis antigos para a bancada de engenharia.
construir "LECSOR" entrada unico unico 1
echo "== pronto:"; ls -la dist/*/*.exe 2>/dev/null | grep -v uninstaller
