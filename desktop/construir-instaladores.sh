#!/usr/bin/env bash
# Gera um instalador por superficie. Operacao e admin sao a MESMA area (o papel do login
# decide o que aparece), entao existe um unico app "LECSOR Admin" para os dois.
set -e
cd "$(dirname "$0")"
VERSAO=$(node -p "require('./package.json').version")
construir() {
  nome="$1"; superficie="$2"; id="$3"
  echo "== instalador: $nome ($superficie)"
  npx electron-builder --win nsis \
    --config.productName="$nome" \
    --config.appId="br.com.lecsor.pipelinevideo.$id" \
    --config.extraMetadata.superficie="$superficie" \
    --config.nsis.shortcutName="$nome" \
    --config.directories.output="dist/$id" \
    --config.win.artifactName="${nome// /-}-${VERSAO}-x64.exe" 2>&1 | tail -4
}
construir "LECSOR Cliente" cliente cliente
construir "LECSOR Admin" admin admin
echo "== pronto:"; ls -la dist/*/*.exe 2>/dev/null | grep -v uninstaller
