> **SUBSTITUÍDO em 16/11/2026 09:07** — o dono corrigiu: *"o teste cego é apenas para o mbps"*. Escopo
> válido em `.hermes/plans/2026-11-16_090700-teste-cego-apenas-do-mbps.md`; o que está aqui (nome
> anônimo, gabarito, julgamento A/B/C) **não faz parte** do pedido.

# Teste cego nos vídeos de teste — sem comparativo de Mbps no momento do download

**Status:** aguardando aprovação (plano para o dono confirmar/corrigir)
**Autor:** Hermes (a pedido de Alexandre) · **Data:** 16/11/2026 08:59
**Pedido (verbatim):** *"não vamos mais fazer o comparativo mbps quando baixar os vídeos de teste, vamos
fazer um teste cego"*
**Repo:** `C:\Users\EngenhariaGoogleMari\lecsor-pipeline-video` (branch `main`, base **0.2.9**)

## O que muda (o que é "teste cego" aqui)

Hoje o download do trecho entrega, junto do arquivo, o kbps medido, o declarado, a compressão e o SSIM —
quem baixa já sabe o número antes de olhar a imagem, e o julgamento fica contaminado. No teste cego o
avaliador recebe **só a imagem**, com nome anônimo; o número vira **gabarito de operação** e só aparece
**depois** do veredito.

### Fase 1 — P0: download sem número nenhum
1. Nome do arquivo: código anônimo sorteado (`A-4f7c.mp4`, `B-91ae.mp4`, …) — **sem** kbps, %, SSIM,
   rótulo de câmera ou alvo; nunca `cam-01`/`vivo-cam-01`.
2. Fora do cabeçalho e do corpo da resposta: nenhum `X-Lecsor-Kbps`, nada de `bate`, compressão ou SSIM
   na tela do download. A tela mostra só "vídeo A/B/C pronto — assista e julgue".
3. O gabarito (qual código era qual fluxo/alvo/bitrate, e o kbps medido no arquivo) fica gravado na
   tabela de trechos, **visível só para operação/admin** (`GET /api/teste-cego` — operação).

### Fase 2 — P0: julgar às cegas e revelar depois
4. Tela de julgamento: escolher qual ficou melhor entre os vídeos anônimos (A/B/C) ou "empate", sem
   nenhum número na tela; a escolha é registrada à parte.
5. Botão **"revelar"** (operação/admin): mostra o gabarito — alvo/bitrate/SSIM/compressão de cada código
   — e cruza com a escolha (o avaliador preferiu o de maior ou menor bitrate?). O comparativo de Mbps
   deixa de existir no momento do download e passa a existir **só aqui**.

### Fase 3 — P1: valer para todos os vídeos de teste
6. Mesmo tratamento no conjunto comparativo de 3 alvos e nos vídeos de bancada (mesma cena, N alvos):
   entrega anônima e sorteada, gabarito em operação.
7. O comprovante de compressão do fluxo **do cliente** (o "Baixar 1 minuto" da 0.2.8/0.2.9, com
   declarado × medido) **fica como está** — ele não é vídeo de teste, é prova. Se você quiser que ele
   também saia, é só dizer (é meia hora de trabalho, não muda o resto).

### Fase 4 — P1: provas
8. Teste novo `tests/test-teste-cego.py`: o download anônimo **não** traz kbps/SSIM no nome, no cabeçalho
   nem no corpo; o gabarito existe só para operação (403 para o cliente); a escolha é registrada; a
   revelação mostra alvo/bitrate e cruza com a escolha. Seção nova no plug-and-play.
9. Deploy do lado terra na VPS + release 0.3.0 (4 instaladores).

## Duas coisas que preciso que você decida

- **A)** O "Baixar 1 minuto" do **cliente** (a prova da compressão) continua com o comparativo, ou sai
  também?
- **B)** O julgamento cego é feito **na tela** (você/operação, olhando os vídeos no app) ou precisa sair
  um **pacote** com os arquivos anônimos (zip/pasta + a folha de julgamento) para mandar a terceiros?

## Riscos e limites (declarados)

- Sem o número na hora, o avaliador **não consegue** julgar "está dentro do piso" — julgamento cego é
  preferência visual, e o piso (SSIM/compressão) continua sendo medido e guardado no gabarito.
- O download anônimo **não** some com a auditoria: quem baixou, quando e o que era cada código continuam
  registrados (operação), como hoje.
- Nada de endereço, porta, protocolo ou credencial de câmera entra em qualquer uma das respostas.
