# Teste cego do Mbps: o download entrega o VÍDEO; a conferência do tamanho é feita à mão

**Status:** **aprovado ("prossiga", 16/11/2026) — implementado na 0.3.0** (commit `415716a`; VPS no ar)
**Resultado medido:** bancada `test-trecho-1-minuto`/`test-declarado`/`suite`/plug-and-play **rc=0**; VPS admin 10 s do
`vivo-cam-01` = **1.842.916 B / 9,7 s**, cabeçalhos só `Bytes`/`Duracao-S`/`Sha256`/`Trecho-Id` (**sem Kbps**);
atestado **admin 200** (medido 1.519,9 kbps) × **cliente 403**; cliente baixou **sem Kbps**; build **`BUILD_rc=0`** (4 instaladores 0.3.0).
**Autor:** Hermes (a pedido de Alexandre) · **Data:** 16/11/2026 09:07 — **substitui** o plano das 08:59
(`2026-11-16_085931-teste-cego-sem-comparativo-mbps.md`), que tinha ido longe demais.
**Pedido (verbatim, corrigindo o plano anterior):** *"não, o teste cego é apenas para o mbps, baixamos o
vídeo e observamos o tamanho dele e comparamos com o que está sendo exibido no admin/captura"*
**Repo:** `C:\Users\EngenhariaGoogleMari\lecsor-pipeline-video` (branch `main`, base **0.2.9**)

## O que o pedido quer dizer (e o que eu tinha entendido errado)

- **É só o Mbps.** O "cego" é: baixar o vídeo de teste, olhar o **tamanho do arquivo** (no Explorer, pelo
  próprio download, ou com o ffprobe) e comparar **à mão** com o Mbps exibido no **admin** e na
  **captura**. A conferência é feita por fora do app, sem o app dizer se bate ou não.
- **Não é** teste cego de qualidade (assistir A/B/C sem saber o alvo), **não é** esconder nome/origem do
  arquivo e **não é** mudar o que o admin/captura exibe. Isso tudo era o plano anterior e **sai inteiro**.

## O que muda — escopo pequeno

### Fase 1 — P0: fora o comparativo automático no download do vídeo de teste
1. No download de **vídeo de teste** sai o comparativo automático: nada de `declarado × medido`,
   `bate: sim|nao`, tolerância de 15%, compressão recalculada e SSIM na tela/na resposta. Entrega o
   arquivo e pronto.
2. A tela mostra apenas o que é do **próprio arquivo**: nome, tamanho e duração — que é justamente o que
   você vai olhar e conferir com o admin/captura. Nenhum veredito sobre o Mbps exibido.
3. **Admin e captura continuam exibindo o Mbps como hoje** (é o número que você compara à mão): nenhuma
   mudança no que eles mostram.

### Fase 2 — P0: nada de "gabarito", sorteio ou julgamento
4. Sem código anônimo, sem sorteio de ordem, sem tela de escolha A/B/C, sem botão de revelar.

### Fase 3 — P1: o comprovante do CLIENTE
5. O "Baixar 1 minuto" do **cliente** (prova da compressão do fluxo ao vivo, 0.2.8/0.2.9) **não é vídeo
   de teste** e fica como está; se você quiser que ele também saia, diga e eu tiro (trabalho pequeno, não
   mexe no resto).

### Fase 4 — P1: provas e entrega
6. Teste: o download do vídeo de teste devolve o arquivo sem comparativo/atestação (sem `bate`, sem
   compressão recalculada, sem SSIM na resposta) e o arquivo mede ~o tempo pedido; a auditoria de quem
   baixou continua registrada. Ajustar o teste existente do trecho (que hoje exige o comparativo) e a
   seção correspondente do plug-and-play.
7. Deploy do lado terra na VPS + release **0.3.0** (4 instaladores).

## O que NÃO muda (para não regredir)

- O Mbps medido no lado terra continua sendo calculado e guardado (auditoria/operação); só não vai mais
  empacotado no download de teste.
- O `POST /api/envios/anuncio` e o `GET /api/declarado` (o que a captura declara) continuam no ar: são o
  que o **admin/captura** mostra e o que você usa para comparar à mão.
- Nada de endereço, porta, protocolo ou credencial de câmera em resposta nenhuma.
