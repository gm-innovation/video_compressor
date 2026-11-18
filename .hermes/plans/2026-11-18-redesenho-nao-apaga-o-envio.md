# Plano aprovado — 0.6.6: o redesenho da tela não apaga o envio em preenchimento (e o `e2e-envios` fecha verde)

**Aprovado pelo dono em 18/11/2026** ("prossiga" depois de "o que mais precisa corrigir?"), na mesma
leva da tela limpa do admin (0.6.4) e da webcam no ar (0.6.5).

**Goal:** fechar as três checagens que sobravam vermelhas em `tests/e2e-envios.py` — `Entrada (original)`,
`Saída (comprimido)` e `Tempo da compressão`, na **tabela de compressões da tela da operação** — corrigindo
a **causa** medida, não o sintoma do teste.

## Contexto medido (18/11/2026)

A tela do admin se repinta sozinha quando a assinatura dos dados muda (`atualizar()` → `desenhar()` em
`admin/admin.js`). O `desenhar()` **limpa** a tela (`limpar(tela)`) e a redesenha — inclusive os campos do
formulário da tela de envio (`#env-arquivo`, `#env-rotulo`, `#env-url`). Quando o repintar caía no meio do
preenchimento do operador:

- o arquivo já escolhido no `#env-arquivo` se perdia → "Comprimir e medir" respondia
  `progresso: escolha o arquivo de vídeo` com o arquivo escolhido (medido no `t-envios-v7.log`);
- a **tabela de compressões** da operação aparecia **sem as colunas** quando o repintar caía no meio da
  montagem (as 3 falhas do `t-envios-v5.log`);
- o texto digitado no rótulo sumia (já tratado na 0.6.5 restaurando o foco/cursor).

A falha era **intermitente** e por isso confundia: `t-envios-v5.log` = 69 ok + 3 falhas (tabela de
compressões); `t-envios-v6.log` = 72 ok + 0 falhas (mesmo código, sem correção); `t-envios-v7.log` = 67 ok +
5 falhas (morreu em `escolha o arquivo de vídeo`).

## Escopo (o que entra)

**`admin/admin.js`** — `envioEmAndamento()` (há arquivo escolhido ou texto digitado na tela de envio?),
`desenhar(forcado)` que **não** repinta enquanto há envio em andamento (as listas continuam se atualizando
pelo timer delas, `carregar()` a cada 5 s; trocar de tela pelo menu chama `desenhar(true)` e sempre
redesenha), `try/catch` na montagem da tabela de compressões que **diz o motivo na tela**
("não consegui montar a tabela de compressões: …") em vez de deixar a área vazia, e `id="env-compressoes"`
na lista (a tela e o teste olham direto para ela).

**`tests/e2e-envios.py`** — diagnóstico no ponto da tabela (status/corpo de `/api/compressoes`, a caixa
`#env-compressoes`, os erros de script da página e o recado da tabela quando ela falha) e, mantido da 0.6.5,
o teste que **não depende da máquina**: sobe a própria bancada (`ground/api.py <porta> --semear-demo`, banco
temporário), o servidor de mídia local (`:8123`) e lê a senha de bancada de uma fonte só
(`ground/.env.local`).

**Versão 0.6.6:** `desktop/package.json`, `tools/publicar-releases.py` (`VERSOES_PUBLICADAS` + `NOTAS`) e
`README.md` (changelog).

## Verificação (medida)

`python tests/e2e-envios.py` → `rc=0`, `TUDO OK`, **72 checagens ok / 0 falhas** (`t-envios-v8.log`), com a
compressão medindo `5.48 MB → 0.56 MB · ↓ 89.85% · qualidade 0.9774 · 2.13 s · CRF 34 · PISO ✓ (≥73% e
≥0,9713 · nominal 0,9733)` e a tabela da operação com as colunas **Entrada (original)**, **Saída
(comprimido)**, **Compressão** e **Tempo da compressão**. `node -e new Function(...)` em `admin/admin.js` =
`JS_OK`; `ast.parse` em `tests/e2e-envios.py` = `PY_OK`.

## Escopo (o que NÃO entra)

Nada de mudança de banda/qualidade do vivo (0.6.4), nada de captura/câmera (0.6.5), nada no lado terra da
VPS além de subir o `admin/admin.js` corrigido depois de publicado, e nenhuma migração de banco.
