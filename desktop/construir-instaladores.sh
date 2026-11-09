#!/usr/bin/env bash
# Gera um instalador por superficie: cliente, operacao (usuario LECSOR) e admin.
# Cada um abre so a sua superficie, com sessao e configuracao separadas.
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
    --config.win.artifactName="${nome// /-}-${VERSAO}-x64.exe" 2>&1 | tail -6
}
construir "LECSOR Cliente" cliente cliente
construir "LECSOR Operacao" admin operacao
construir "LECSOR Admin" admin admin
echo "== pronto:"; ls -la dist/*/*.exe
