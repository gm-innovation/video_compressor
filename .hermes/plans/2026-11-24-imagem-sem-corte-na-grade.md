**Status:** APROVADO E IMPLEMENTADO em 0.13.2 (24/11/2026) — o dono escolheu **E-A/E-B** ("não cortar ...
preciso das imagens inteiras"); a linha do tempo fica assim: E-A/E-B (imagem inteira) + **Fase 2-bis**
(rodapé baixo com só a linha de direitos). Decisão do dono em 24/11/2026, via pergunta direta: o rodapé que
muda é o da **tela do cliente (`/app/`)**, e o conteúdo passa a ser **só** a linha
`Lecsor - Todos os direitos reservados - <ano>` (saíram "Ver todos os alertas", "Relatórios" e
"Limpar seleção").

# A imagem da grade não pode ser cortada nem ter faixa preta — a área da imagem passa a ter a proporção da câmera

## O que o dono pediu (verbatim)

> agora com o card abaixo das imagens e a remoção das faixas pretas laterais, as imagens estão sendo cortadas

Antecedente (o mesmo dia): *"a imagem da câmera deve ocupar todo o espaço destinado a ela, removendo as faixas
pretas laterais"*. O dono autorizou, junto, a decisão **D-D** (`object-fit:cover`) e agora aponta o efeito dela.

## Evidência (fato | como foi verificado)

| Fato | Como foi verificado |
|---|---|
| A imagem é cortada porque o CSS usa `object-fit:cover` | `curl -s http://187.127.60.250:8085/fronts/vms.css` → `.janela video{width:100%;height:100%;object-fit:cover}` (linha 70 do CSS no ar) |
| A área da imagem **não** tem a proporção da câmera — ela é a fração da tela que sobra | CSS no ar: `.grade-vms{height:100%}`, `.g3{grid-template-rows:repeat(3,1fr)}`, `.g4{grid-template-rows:repeat(4,1fr)}`, `.janela{height:100%}`, `.img-cam{flex:1 1 auto}` — a altura de cada célula é `1/N` da **tela** (depende do tamanho da janela do navegador, do menu lateral e do cabeçalho), não da câmera |
| O vídeo de referência é 1920×1080 (16:9) | Medido no smoke `J2` (`20-runbooks/2026-11-23-smoke-de-ponta-a-ponta-fase-1.md`): "imagem 1920×1080 decodificada no cliente" |
| O `aspect-ratio:16/9` da `.janela` foi removido na 0.13.1 | `git show 827aec8:fronts/vms.css` (antes) × `git show d1c828e:fronts/vms.css` (depois) |

**Por que corta:** `object-fit:cover` **sempre** preenche a área — se a área não tiver a proporção do vídeo, ele
**corta o que sobra** (nas laterais, no topo ou embaixo, conforme o caso). Foi exatamente o que o D-D comprou:
acabaram as faixas pretas **porque** a imagem passou a ser cortada. As duas coisas (encher a área e não cortar)
só coexistem se **a área tiver a proporção do vídeo**.

## Decisões (uma linha cada; o dono confirma ou troca)

- **E-A (recomendada):** a área da imagem (`.img-cam`) passa a ter **a proporção do vídeo**, lida do próprio
  vídeo (`videoWidth/videoHeight` no `loadedmetadata` do `<video>`), e o `<video>` usa `object-fit:contain`
  (ou `cover`, tanto faz: com a área na proporção certa os dois dão o mesmo resultado). Sem corte, sem faixa.
- **E-B:** a grade deixa de esticar para `1fr` da tela e passa a **dimensionar as linhas pela altura da área da
  imagem** (`grid-auto-rows:auto`, `align-content:center`); a sobra da tela vira margem — não vira faixa preta
  (o fundo da célula é o da página, não um retângulo preto).
- **E-C:** a proporção é por câmera e cai para **16:9** enquanto o vídeo não tem metadado (nada pisca nem
  "pula" ao abrir a tela).
- **E-D:** o **destaque** (tela cheia da câmera) segue a mesma regra — com a proporção da câmera, sem corte.

Se o dono preferir o desenho antigo, a alternativa é **E-Z**: manter `cover` e a área esticada (a imagem
**com** corte) — é o que está no ar hoje.

## Fase 1 — Área da imagem com a proporção da câmera (P0 + P1)

- **P0** `fronts/vms.css`: `.img-cam{aspect-ratio:16/9}` por padrão; `flex:0 0 auto` (não cresce mais que a
  proporção); `.janela{height:auto}`; `.grade-vms` com `grid-auto-rows:auto` e `align-content:center`.
- **P0** `app/app.js`: no `v.onloadedmetadata` de cada `<video>`, ler `videoWidth/videoHeight` e gravar
  `img.style.aspectRatio = w + ' / ' + h`; se o metadado mudar (a câmera troca de resolução), atualiza.
- **P1** `app/app.js`: a mesma leitura no **destaque** (`app.js:343`, segundo ponto que monta `.img-cam`).
- **P1** `fronts/vms.css`: no destaque, a área da imagem ocupa a altura disponível sem cortar
  (`max-height:100%; object-fit:contain`).

## Fase 2 — Fim das faixas pretas de verdade (P0 + P1)

- **P0** tirar o `background:#000` da `.janela`/`.img-cam` e usar o fundo do painel: sem a área esticada, o
  preto que sobrar deixa de ser um retângulo (é o que o dono chama de "faixa preta").
- **P1** `.janela video{object-fit:contain}` com a área na proporção da câmera — nenhum pixel cortado.
- **P1** conferir com o card abaixo que o **nome/estado e os botões** seguem no card e a imagem não os cobre.

## Fase 2-bis — O rodapé baixo, só com a linha de direitos (P0) — pedido do dono

> "diminua o rodapé para dar mais espaço na tela, mantenha apenas 'Lecsor - Todos os direitos reservados - 20##'"

- **P0** `app/index.html`: o `<footer class="rodape">` perde os três controles ("Ver todos os alertas",
  "Relatórios", "Limpar seleção") e fica **só** com a linha `Lecsor - Todos os direitos reservados - <ano>`
  (o ano vem do relógio da máquina, em `app.js`, para nunca envelhecer).
- **P0** `app/app.js`: os listeners desses três controles passam a ser ligados **só se o elemento existir**
  (sem isso o boot quebra com `null.addEventListener`), e `atualizarRodape()` deixa de exigir
  `#contagem-selecao`.
- **P0** `fronts/vms.css`: `.rodape` de `padding:10px 18px 12px` + botões de 13px para **uma linha centrada**
  (`padding:3px 12px`, `font-size:11px`) — o que sobra de altura vai para as imagens.
- **P1** as três telas continuam alcançáveis pela lateral esquerda (alertas e relatórios não somem do app).

## Fase 3 — Prova (P0 + P1)

- **P0** estender `tests/e2e-janela-ao-sair-da-tela.py` (ou um `tests/e2e-imagem-da-grade-nao-corta.py` novo):
  em navegador real, medir `video.videoWidth/videoHeight` × a caixa renderizada do `<video>` e provar que a
  imagem **não perde pixel** (mesma proporção, folga ≤ 1 px) — e que a área **não** tem a proporção errada com
  o vídeo de teste (1280×720 e 640×480, para os dois casos).
- **P0** rodar a suíte inteira (`tools/regressao-0130.py`) apontando para a prova nova.
- **P1** medir o caso do **2 câmeras** (o que produzia as faixas laterais) e o de **4 câmeras**.

## Fase 4 — Publicar (P0)

- **P0** commit + push (branch e merge no `main`), bump **0.13.2**, release no GitHub.
- **P0** deploy do terra na VPS (`app/app.js`, `fronts/vms.css` do git, LF, `py_compile` desnecessário para
  front) + serviço active + `/app/` 200.
- **P0** nota no vault + bullet no `index.md` + push confirmado no `master`.

## Arquivos que vão mudar

- `fronts/vms.css` (`.grade-vms`, `.g1..g4`, `.janela`, `.img-cam`, `.janela video`).
- `app/app.js` (leitura de `videoWidth/videoHeight` nos dois pontos que montam a imagem: grade e destaque).
- `tests/e2e-imagem-da-grade-nao-corta.py` (novo) e `tools/regressao-0130.py` (aponta para a prova).
- `desktop/package.json` + `tools/publicar-releases.py` (versão 0.13.2).

## Riscos e limites (declarados)

- **Não existe** desenho que ocupe exatamente a tela toda, sem faixa e sem corte, quando a proporção da câmera
  é diferente da proporção da célula — é geometria. A escolha do plano é **não cortar** (E-A/E-B) e deixar a
  sobra como margem do painel.
- A proporção lida do vídeo só vale **depois** do primeiro quadro; até lá a área fica 16:9 (E-C).
- Câmera que muda de resolução no meio da sessão só é corrigida se o evento de metadado for disparado de novo
  (o `loadedmetadata` dispara; fica o aviso de que a troca a quente não é o caso medido nesta rodada).
