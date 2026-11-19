# Tela do cliente corta as câmeras de cima — 18/11/2026

Status: **implementado e provado** (18/11/2026) — aguardando publicação do app (build 0.6.9)
Dono: Alexandre · Pedido: "na tela do cliente está cortando as câmeras de cima" (print `image_bb48e1.png`, 1708×176 px)
Bordo/terra: mesma tela (`/app`, papel `cliente`), servida pelo lado terra (`http://187.127.60.250:8085/app/`) e pelo app do PC (papel `unico`), com o **mesmo** `fronts/vms.css` (md5 igual: `d964f4b1…b9b85`).

## O que foi MEDIDO (reprodução em navegador real, 1920×1080, grade de 3 com 6 câmeras)

Sonda: `%LOCALAPPDATA%\Temp\scratch-grade-cliente\sonda-prova-corte.py` (api temporária + 6 câmeras + Playwright/Chrome).
Evidência visual: `prova-corte-topo.png` (recorte do topo da grade).

| Medida | Valor | Leitura |
|---|---|---|
| `padding` do palco (`#palco`) | `0px 18px 8px` | **zero em cima**, 8 px embaixo → grade colada no cabeçalho e **assimétrica** |
| topo do palco × topo da 1ª janela | 67,0 × 67,4 | folga de **0,4 px** — a primeira fileira encosta no cabeçalho |
| contorno da janela selecionada (`outline:2px` + `offset:1px`) | começa em 64,4 | **2,6 px acima** do topo do palco |
| `overflow` do palco | `hidden` | os 2,6 px do contorno **são cortados** (foi o que o print mostra: a moldura azul da 1ª fileira some em cima) |
| `align-content` da grade | `stretch` (linha 54 sobrescreve o `center` da linha 48) | em janela alta a fileira centraliza sozinha → comportamento muda com o tamanho da janela |

Conclusão medida: não é o vídeo que é cortado (o `<video>` usa `object-fit:contain`); é a **primeira fileira de janelas que fica colada no cabeçalho e tem o topo comido pelo `overflow:hidden` do palco** (moldura/borda de seleção cortadas) — e o palco tem folga só embaixo.

## Fase 1 — Correção do corte (P0)

- P0 · `fronts/vms.css`, regra `.palco`: `padding:0 18px 8px` → `padding:12px 18px 8px` (folga simétrica no topo; ≥ 3 px garante o contorno `2px + offset 1px` inteiro).
- P0 · Confirmar que a folga vale em 3 tamanhos de janela (1920×1080, 1536×780, 1366×768) e nas grades 2×2, 3×3 e 4×4 — a medida passa a ser "contorno inteiro dentro do palco" e "folga ≥ 3 px".
- P1 · `align-content`: manter `stretch` (a grade preenche a altura, como VMS) e conferir que a folga não vira buraco em janela alta (se virar, trocar por `align-items:stretch` + `justify-content` no eixo certo).
- P1 · Mesmo tratamento na tela de destaque/tela cheia (`.destaque .grade-vms`) — já tem `padding-top:10px`, medir para garantir.

## Fase 2 — Outras telas com o mesmo defeito (P1)

- P1 · Varrer quem usa `.palco`/`.grade-vms`/`.janela` (cliente `/app`, destaque, e telas equivalentes do admin/operação) e aplicar a mesma folga onde o topo encosta.
- P2 · Registrar no código (comentário curto) por que a folga do topo é obrigatória (contorno de seleção + `overflow:hidden`), para não ser removida depois.

## Fase 3 — Prova (P1)

- P1 · Teste em `tests/` (padrão do repo): mede `padding-top` do palco, folga da 1ª janela e "contorno inteiro dentro do palco" na grade de 3 e na de 4; falha se voltar a encostar.
- P1 · Sonda Playwright com print antes/depois (`prova-corte-topo.png` já é o "antes") para anexar ao runbook.
- P2 · Rodar a bateria que já existe (`test-app-unico-por-papel`, `e2e-tela-limpa-do-admin`) para garantir que nada regrediu.

## Fase 4 — Publicação (P1)

- P1 · Commit na `main` (mensagem: causa medida + correção) e push.
- P1 · Lado terra: `scp` de `fronts/vms.css` para `/opt/pipeline/app/fronts/` e conferir `/app/` no ar (1920×1080, grade de 3, uma câmera selecionada).
- P1 · **App do PC**: o pacote carrega a própria cópia de `fronts/vms.css` (`resources/servidor/fronts/vms.css`, md5 igual ao repo) → a correção **só chega ao app com versão nova**: `0.6.9` (bump `desktop/package.json`, `tools/publicar-releases.py`, `README.md`, build, `LECSOR-0.6.9-x64.exe`, release `v0.6.9`).
- P2 · Runbook no vault (`20-runbooks/2026-11-18-...`) + `index.md` + push.

## Fase 5 — Fechamento (P2)

- P2 · Medir no ar (lado terra e app 0.6.9) e fechar com veredito explícito.
- P2 · Deixar registrado o que **não** foi mexido (sem tocar em vídeo, fps, banda, cadastro, auditoria).

## Riscos e o que NÃO muda

- Mudança de 12 px de folga no topo: nenhuma alteração de comportamento, de vídeo, de banda, de fps, de ordem de transmissão, de cadastro ou de auditoria.
- Se o dono preferir, a mesma correção pode ir em qualquer versão (é uma linha de CSS), mas o app instalado continua com o defeito até sair build novo.

## Provas que fecham este plano

| Prova | Resultado medido |
|---|---|
| `tests/test-grade-do-cliente-nao-corta-o-topo.py` (novo) | **9/9 verde** — padding-top 12 px, folga da 1ª fileira 12,0 px, contorno **+9,0 px dentro** do palco (3 tamanhos × grades 2/3/4) |
| O mesmo teste com o CSS antigo (stash) | **36 falhas** — *"contorno da janela cortado em 3.0 px"* e *"padding-top do palco = 0"* → a prova pega o defeito |
| Sonda `prova-corte-topo.py` antes/depois | antes: contorno **−2,6 px** (cortado); depois: **+9 px** dentro do palco |
| `tests/test-app-unico-por-papel.py` | OK (não regrediu) |
| `tests/e2e-tela-limpa-do-admin.py` | E2E-TELA-LIMPA_OK (não regrediu) |
| Lado terra (`/opt/pipeline/app/fronts/vms.css`) | scp feito + md5 conferido = repo |
| Lado terra no ar (Playwright em `187.127.60.250:8085/app/`, 1920×1080, grades 2/3/4) | `padding=12px 18px 8px`, folga **12 px**, contorno **+9 px dentro** do palco em todas as grades (print `no-ar-topo.png`: moldura azul completa) |
| `LECSOR-0.6.9-x64.exe` | publicado como `v0.6.9` (`latest`), 171.555.122 B, sha256 `c3c5d201…6004a1` conferido na API do GitHub; CSS **dentro do pacote** = md5 do repo |

Varredura da Fase 2 (feita): `admin/` usa `fronts/vms.css` mas **não** usa `.palco/.grade-vms/.janela` (só texto);
`portal/index.html` tem grade própria (`auto-fill 340px`) em fluxo normal dentro do cartão, sem `overflow:hidden`
acima — nada a corrigir lá.

