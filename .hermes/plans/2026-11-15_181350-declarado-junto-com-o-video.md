# O que o PC de captura declara tem de chegar JUNTO com o vídeo (declarado × medido no atestado)

**Status:** aprovado (15/11/2026, "prossiga") — implementado na **0.2.9**
**Autor:** Hermes (a pedido de Alexandre) · **Data:** 15/11/2026 18:13
**Repo:** `C:\Users\EngenhariaGoogleMari\lecsor-pipeline-video` (branch `main`, base **0.2.8**)

## O que o dono pediu

*"precisamos ter esses comparativos, precisamos de todas as informações, e até onde eu sei, já fizemos as
alterações no app de captura pra ele enviar as informações junto com o vídeo"* — com a tela da CAM 02
mostrando `declarado pelo PC de captura: não informado` e `a compressão não fecha a conta`.

## O que foi MEDIDO agora (não é suposição)

| o que | como foi medido | resultado |
|---|---|---|
| Chegou declaração do bordo? | `SELECT COUNT(*)` em `ingestoes` e `medicoes_qualidade` no banco do lado terra (`/opt/pipeline/app/db/pipeline.db`) | **0 linha em cada** |
| O caminho bordo→terra funciona? | linhas de câmera na VPS criadas pelo anúncio do bordo | **sim**: `vivo-cam-01`/`vivo-cam-02` existem com `local='bordo'` — mesmo token, mesma URL, mesma rede |
| De onde o atestado tira o "declarado"? | `ground/trecho.py` → `ingestoes` (kbps entrada/saída, alvo, corte, codec, resolução, fps) e `medicoes_qualidade` (ssim, mb_alvo, mb_original, compressão) **do lado terra** | a tabela `ingestoes` **existe só no bordo** e **nada no sistema escreve esses números no lado terra** → o lado declarado do kbps nunca existiu |
| Quando a declaração de qualidade sai? | `ground/qualidade.py:146-155` (chamada de `publicar_qualidade`) e `ingestao.py:757` | só de dentro de `qualidade.medir()`; `medir_se_preciso(validade_s=600)` **reaproveita** a medição recente e nesse caso **não publica**; se a medição falha, também não publica |
| Onde se vê que falhou? | log da máquina de captura (`print`/`_log`) | **só lá** — o lado terra não registra tentativa, e a tela do Captura mostra o recado `lado_terra` só quando alguém olha |

**Conclusão medida:** o comparativo não aparece por **dois** motivos independentes —
(1) **nada publica os números do transporte** (é a tabela `ingestoes`, que mora no bordo) para o lado
terra, e (2) a publicação do SSIM depende de a medição rodar naquele instante, e o resultado disso não é
visível de fora.

## Fases

### Fase 1 — P0: o bordo publica os números do ENVIO junto com o vídeo

1. `ground/repasse.py`: `publicar_envio(envio)` → `POST /api/envios/anuncio` (token de ingestão) com os
   números que o bordo já calcula: `fluxo_id`, `bitrate_entrada_kbps`, `bitrate_saida_kbps`, `corte_pct`,
   `alvo`, `codec`, `resolucao`, `fps`, `estado`, `tipo`, `carimbo` (ISO). Nada de endereço, porta,
   protocolo ou credencial de câmera.
2. `ground/ingestao.py`: publicar (a) quando o envio entra no ar, (b) **a cada 30 s** enquanto envia
   (thread leve que só publica se o número mudou ou a última publicação tem mais de 30 s), (c) de novo
   quando o envio para. Best-effort: publicar nunca derruba o envio.
3. `ground/qualidade.py`: publicar a medição **também quando ela é reaproveitada do cache** (hoje o
   `pulado=True` corta a publicação) e publicar o recado do lado terra no resultado da medição.

### Fase 2 — P0: o lado terra guarda e mostra o DECLARADO

4. `ground/api.py`: rota `POST /api/envios/anuncio` (token de ingestão, mesmo `hmac.compare_digest` do
   anúncio de qualidade) gravando/atualizando `ingestoes` do lado terra (`atualizado_em` = carimbo do
   bordo, `fonte` = máquina que declarou). `garantir_tabela` no boot, como as outras.
5. `ground/trecho.py`: o atestado passa a mostrar o declarado **com origem e hora**
   (`declarado em 18:07 por <fluxo>@bordo`), a comparar **kbps de saída declarado × kbps medidos no
   arquivo** (é a comparação que o dono quer ver) e a fechar a conta da compressão com
   `entrada declarada × saída declarada` **e** com `entrada declarada × arquivo`; quando não houver
   declaração, dizer "o bordo não declarou (última tentativa: nunca)".
6. `app/app.js` + `admin/admin.js`: a coluna/tela de qualidade mostra **declarado × medido** lado a lado
   (kbps, corte %, compressão e SSIM com a hora), em vez de só o medido.

### Fase 3 — P0: falha visível, sem ssh no barco

7. `GET /api/envios` (operação/admin): por fluxo, a **última declaração recebida** (quando, de qual
   máquina, quais números) e a idade — é o que mostra em 1 segundo se o barco está falando com terra.
8. O lado terra **registra toda tentativa** de anúncio (aceita/recusada, com motivo e IP) no log do
   serviço e em `auditoria_acesso`; a tela do Captura passa a mostrar o resultado da publicação
   (`medicao publicada no lado terra` / `o lado terra ainda NAO tem esta medicao (...)`) no envio ao vivo.
9. Aviso honesto na tela do cliente quando não há declaração: "sem declaração do PC de captura desde
   <hora>" — em vez de só `não informado`.

### Fase 4 — P1: o mesmo para o SSIM e para o corte

10. Publicar também `corte_pct` (compressão do transporte medida no bordo) e a resolução/fps que o
    mediamtx **realmente** publicou (não só o ajuste pedido).
11. Reaproveitar a mesma rota para o cenário 2 (terra→bordo) quando o fluxo rodar nessa direção.

### Fase 5 — P1: testes, deploy e release

12. Teste novo `tests/test-declarado-chega-ao-lado-terra.py`: com API e mediamtx de verdade, o bordo
    publica o envio → a linha aparece em `ingestoes` do lado terra → o atestado mostra
    `declarado × medido` com `bate: true`; declaração errada → `bate: false`; nada declarado →
    `não informado`. E a prova do cache: medição reaproveitada **também** publica.
13. Seção nova no plug-and-play + `suite.py`; deploy na VPS; **release 0.2.9** (4 instaladores).
14. No fecho: rodar o botão "Baixar 1 minuto" na VPS e anexar o comprovante com o comparativo
    preenchido (é a prova que o dono pediu).

## Resultado medido (implementado na 0.2.9)

| o que foi medido | onde | resultado |
|---|---|---|
| rota nova existe e exige token | VPS, `POST /api/envios/anuncio` | **401** sem token, **201** com token |
| quadro do declarado e' de operacao | VPS, `GET /api/declarado` | **403** sem sessao (o cliente nao recebe o que o bordo declara) |
| fluxo real ANTES da declaracao | VPS, trecho de 10 s do `vivo-cam-01` | medido **1505,3 kbps**; declarado: "nada declarado (nenhuma declaracao deste fluxo chegou ao lado terra)" |
| declarado × medido (1.500k de 6.000k) | VPS, trecho de 10 s do `vivo-cam-01` | arquivo **1503,0 kbps** × declarado **1500,0 kbps** → `bate: true` (dif **0,2%**); compressao recalculada **74,95%** |
| declaracao ERRADA (3.000k) | VPS, trecho de 10 s do `vivo-cam-01` | arquivo **1502,8 kbps** × declarado **3000,0 kbps** → `bate: false` (dif **-49,9%**) |
| medicao reaproveitada publica? | bancada (`tests/`) | `pulado=True` **e** `publicar_qualidade` chamado com os numeros do cache |
| limpeza | VPS | as linhas da simulacao foram apagadas: `ingestoes=0`, `anuncios_recebidos=0` (estado anterior) |

Testes: `test-declarado-chega-ao-lado-terra.py` **PASSOU** (28 verificacoes); `test-trecho-1-minuto.py`
**PASSOU**; `suite.py` **OK / SUITE_rc=0**; plug-and-play **OK / PNP_rc=0 (25 secoes)**.

**As duas linhas declaradas na VPS foram SIMULADAS** (a Captura do barco ainda roda 0.2.8): serviram
para provar o caminho ponta a ponta e foram apagadas em seguida. Os numeros reais so' passam a chegar
quando a **Captura 0.2.9** estiver instalada na maquina do barco.

## Riscos e limites (declarados)

- **O número declarado é do bordo, não do lado terra.** O atestado continua deixando claro de onde veio;
  a comparação é entre o que o bordo diz e o que o arquivo prova, com tolerância declarada (±15%).
- **A cena do trecho não é a mesma do instante declarado** (o minuto baixado varia): a tolerância existe
  para isso, não para esconder diferença.
- **Publicar a cada 30 s** custa uma requisição HTTP pequena por fluxo; se o lado terra estiver fora, o
  bordo segue enviando vídeo (publicar é informação, não pode parar a operação).
- Não muda o que **sai** da máquina: nada de endereço, porta, protocolo, credencial ou `alvo` no cadastro
  publicado ao cliente.
- O SSIM continua sendo medido **no bordo** (o lado terra não tem a fonte crua) — o que muda é que o
  número passa a chegar de forma confiável e datada.
