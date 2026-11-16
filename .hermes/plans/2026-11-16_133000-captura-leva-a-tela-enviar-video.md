# 0.4.1 — a Captura leva a tela "Enviar video" (com a taxa por camera)

Status: corrigido em 16/11/2026 (ordem direta do dono: "precisamos corrigir isso imediatamente").

## Problema (medido)
- `desktop/package.json` (extraResources) copiava ground, fronts, admin, app, board, db, analytics —
  **sem `portal/`** (removido no commit f7f360d, 0.2.1). O servidor serve o site pela raiz:
  `ground/api.py:486` -> `directory=RAIZ/"portal"`. Sem `portal/` no pacote, `/` no PC de captura
  nao entrega a tela "Enviar video" (onde esta a selecao de taxa por camera: `class="qualidade"`).
- O instalador do PC de captura nascia com `superficie="admin"`: o tecnico via o console do operador,
  nao a tela de envio.
- Prova do lado terra: `/` responde 200 com md5 `b42bf6dd...` = `portal/index.html` do repo (tem
  "Enviar video" e `class="qualidade"`); `/portal` e `/portal/index.html` dao 404.
- Prova do pacote, agora com o portal: servidor do pacote serve `/` = 19.205 B, "Enviar video" 1,
  `class="qualidade"` 1; `/admin` continua 200.

## Correcao
1. `desktop/package.json`: `{from: "../portal", to: "servidor/portal"}` em extraResources.
2. `desktop/construir-instaladores.sh`: instalador do PC de captura passa a nascer na superficie
   `bancada` (rota `/` = tela "Enviar video"), nao em `admin`.
3. `tests/test-instalador-plug-and-play.py`: secao 10 passa a EXIGIR `portal/` no pacote; secao 11
   copia `portal/` e checa que a raiz `/` serve "Enviar video" com `class="qualidade"`.
4. Versao 0.4.0 -> 0.4.1 e novo instalador publicado para o PC de captura dos tecnicos.

## Fora do escopo
- Nada muda no lado terra (a raiz dele ja entrega o portal 0.4.0).
- O Admin continua sendo onde se cadastra camera (coluna "Alvo"), e segue levando o ambiente.
