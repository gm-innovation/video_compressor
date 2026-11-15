# Botão no app do cliente — baixar 1 minuto do vídeo que chega na VPS (prova da compressão)

**Status:** aprovado (2026-11-15) — implementado na 0.2.8
**Autor:** Hermes (a pedido de Alexandre) · **Data:** 15/11/2026 17:03
**Repo:** `C:\Users\EngenhariaGoogleMari\lecsor-pipeline-video` (branch `main`, base 0.2.7)

## Objetivo

O cliente clica em **Baixar 1 minuto** na câmera que ele já vê, e recebe um arquivo **MP4 com 60 s do
vídeo exatamente como ele chegou na VPS** (o lado terra), mais um **comprovante** com os números
medidos. Com o arquivo na mão dá para conferir por fora (ffprobe, tamanho em disco) se o Mbps e a
porcentagem de compressão que o Admin/Captura informam são reais.

**O que isso prova:** que os bits que chegaram em terra, num minuto, batem com o bitrate declarado
(kbps) — logo a economia de banda informada existe de fato.
**O que isso NÃO prova:** que a imagem ficou bonita. Semelhança de imagem é o SSIM, que é medido no
PC de captura (número já publicado ao lado terra pela 0.2.7).

## Onde entra (arquitetura que já está fixada)

- O navegador do cliente **nunca** fala com o Supabase nem recebe endereço/porta/credencial: tudo
  passa pela API do lado terra (`ground/api.py`, atrás do papel do usuário).
- O lado terra **já tem** o fluxo ao vivo no mediamtx (`vivo-cam-01`, `vivo-cam-02`); o trecho é
  lido de lá por um **leitor a mais** (RTSP `127.0.0.1:8554/<fluxo>`, `-c copy`) — não toca no PC de
  captura, não derruba o envio e não reencoda nada. `-c copy` é essencial: o arquivo baixado tem de
  ser **os bits que chegaram**, não uma nova compressão.
- O custo de um clique é 1 leitor de 60 s. Com N cliques simultâneos, N leitores; entra teto.

## Fases

### Fase 1 — P0: o trecho existe e é baixável (lado terra)

1. `ground/trecho.py` (novo): `gravar_trecho(fluxo_id, segundos=60, pasta=None)` chama o ffmpeg do
   pacote com `-rtsp_transport tcp -i rtsp://127.0.0.1:<porta-rtsp>/<fluxo> -t 60 -c copy -movflags
   +faststart` e devolve caminho, bytes, duração real, kbps medidos e `sha256` do arquivo.
2. Rota **`GET /api/fluxos/<fluxo_id>/trecho?segundos=60`** em `ground/api.py`:
   - só para sessão de **cliente** (e admin), e **só para fluxo que aparece na lista daquele
     cliente** (mesma regra da lista de câmeras — nada de fluxo de outro armador);
   - `fluxo_id` sanitizado (`[^a-zA-Z0-9_\-]` → `-`), `segundos` limitado a 10..60 (default 60);
   - **1 gravação por vez por fluxo** (trava em memória): dois cliques no mesmo fluxo não viram dois
     ffmpeg brigando pelo mesmo caminho;
   - timeout duro (90 s) e remoção do arquivo depois de servido/TTL;
   - resposta: o MP4 (`Content-Disposition: attachment`) **ou** `202` + `{id}` e a rota de download,
     dependendo do tamanho (decidir na implementação: um minuto de 1,5 Mbps ≈ 11 MB, cabe inline).
3. Nome do arquivo: `<fluxo>-<AAAAMMDD-HHMM>-1min.mp4`.
4. Guardar toda gravação em `trechos` (tabela nova): fluxo, quando, segundos, bytes, kbps medidos,
   sha256, quem pediu — para o dono auditar depois sem depender do navegador.

### Fase 2 — P0: o comprovante (o número deixa de ser palavra)

5. **`GET /api/fluxos/<fluxo_id>/trecho/atestado`** (mesmo id da gravação) devolve um JSON/PDF curto:
   - `bytes_baixados`, `segundos_reais`, `kbps_medidos` (bytes×8/segundos);
   - **`kbps_declarados`** do envio no PC de captura (`ingestoes.bitrate_saida_kbps`) e
     **`kbps_entrada`** (`bitrate_entrada_kbps`), lado a lado com o medido;
   - `alvo` usado, `ajuste` (ex.: `1500k`), `perfil` (High), resolução, fps;
   - **`compressao_pct_calculada = 1 - (bytes_do_trecho / bytes_do_original_no_mesmo_tempo)`** —
     calculada com os dois números na mesma tela, em vez de só repetir a porcentagem do bordo;
   - **`bate: sim|nao`** comparando `kbps_medidos` × `kbps_declarados` com tolerância explícita
     (proposta: ±15%, porque o minuto amostrado não é idêntico ao momento medido no bordo);
   - `sha256` do arquivo, para o cliente conferir que o arquivo que ele baixou é o mesmo do atestado.
6. Se o número **não** bater, a tela diz isso em voz alta (nada de esconder diferença): é justamente
   a prova que o dono quer poder contestar.

### Fase 3 — P1: o botão no app do cliente

7. Em `app/` (tela do cliente), ao lado da câmera: botão **Baixar 1 minuto** com estado honesto
   (`gravando 60 s…`, barra de progresso pelo tempo, `baixar (11,2 MB)`), e **Baixar comprovante**.
8. Avisos de borda: câmera fora do ar, gravação já em curso, pedido acima do teto, erro de rede —
   cada um com uma frase, sem travar a tela de vídeo (o vídeo continua tocando).
9. Enquanto grava, mostrar em tempo real os bytes que estão entrando, para o dono ver o número
   subir (e comparar com o Mbps do Admin).

### Fase 4 — P1: teto de uso e não virar gravador

10. Limite por cliente e por janela (ex.: 3 trechos por 10 min) e no máximo 2 gravações simultâneas
    no lado terra; recusa com frase clara ao passar.
11. Nada de trecho de fluxo inativo; TTL de 1 h para os arquivos em disco; sem acumular disco na VPS.
12. Registrar cada pedido em `trechos` (quem, quando, tamanho) — auditoria simples.

### Fase 5 — P2: teste que prova a conta

13. `tests/test-trecho-1-minuto.py`: sobe a API do lado terra de verdade (banco temporário) com um
    fluxo sintético publicado no mediamtx local, pede 60 s, e exige:
    (a) o arquivo baixado tem **60 s ±2 s** e é MP4 legível por `ffprobe`;
    (b) `bytes×8/segundos` do arquivo bate com o bitrate declarado da fonte dentro da tolerância;
    (c) a `compressao_pct_calculada` bate com `1 - tamanho/original` calculado por fora, no teste;
    (d) `sha256` do arquivo baixado é igual ao do atestado;
    (e) fluxo de outro cliente dá 403/404 e `segundos` fora de 10..60 dá 422.
14. Registro como seção nova do `tests/test-instalador-plug-and-play.py` + `tests/suite.py`.

## O que muda no cliente quanto a reinstalação

O botão mora na tela servida pelo lado terra (VPS): **o app do cliente só precisa ser reaberto**, não
reinstalado — mesma regra da lista de câmeras. Só o **lado terra** recebe código novo nesta mudança.

## Riscos e limites (declarados)

- **1 clique = 1 leitor de 60 s.** Ler em `-c copy` do mediamtx não afeta o envio (o caminho do
  mediamtx suporta vários leitores), mas consome banda da VPS para o cliente que baixou.
- **O minuto baixado não é o mesmo minuto medido no bordo:** o atestado compara médias, com tolerância
  explícita. Quem quiser igualdade exata tem de medir no mesmo instante nos dois lados.
- **Compressão só fecha a conta com o original no mesmo intervalo.** O original cru existe só no PC de
  captura; o atestado usa o `bitrate_entrada_kbps` informado pelo bordo e mostra que está usando esse
  número — sem inventar referência que o lado terra não tem.
- **Sem gravação contínua:** o trecho é sob demanda; não é histórico, não é VOD.
- Se o cliente exigir o trecho em qualquer ponto do passado, isso é outra coisa (gravação contínua) e
  precisa de outra decisão (disco e custo) — não está nesta entrega.

## Resultado medido por fase (implementado na 0.2.8)

**Fase 1 e 2 — o trecho e o atestado (provado por teste automatizado).** `-c copy` do mediamtx do lado
terra; arquivo de **59,9 s**, `h264 High`, 1280×720, 30 fps, **11.296.109 bytes = 1.503,9 kbps** medidos
pelo próprio arquivo; `sha256` do arquivo baixado é o mesmo do atestado. Com o bordo **declarando
1.522,7 kbps** e chegando **1.512,4 kbps**, o atestado escreve `bate: true` (diferença **-0,68%**,
tolerância ±15%) e **recalcula a compressão aqui** (`compressao_pct_calculada` 80,13% × 80% informada).
Com o bordo declarando **3.000 kbps** e chegando ~1.500 kbps, o atestado responde `bate: false` e a
leitura diz **"FORA da tolerância"** — é o caso que o dono quer poder contestar.

**Fase 3 — o botão no app do cliente (provado em navegador de verdade).** Chromium headless, perfil
temporário, login `cliente@lecsor.test`: o botão aparece, o clique grava 60 s e a tela mostra
`gravando N s… X MB recebidos (K kbps agora)` subindo, depois
`baixado: cam-01-20261115-1720-60s.mp4 · 11,3 MB em 60 s = 1.503,9 kbps` e o comprovante na própria
janela. O navegador salvou o arquivo: `ffprobe` por fora = **59,9 s / 1.503.854 bps**. Foi preciso
corrigir o CSS: os botões ficavam **em cima** do rótulo da câmera (agora são linhas separadas) e o
comprovante passou a fechar com um clique.

**Fase 4 — teto e auditoria.** O quarto trecho do mesmo usuário na janela de 10 min recebe **429**;
`trechos` guarda quem baixou (`admin@lecsor.test`, `cliente@lecsor.test`) e **não tem coluna de
endereço/credencial**; TTL de 1 h; no máximo 2 gravações simultâneas.

**Fase 5 — o teste.** `tests/test-trecho-1-minuto.py` (**30 verificações**, mediamtx + publicador + API
de verdade, portas livres, banco temporário) e seção **24** do `tests/test-instalador-plug-and-play.py`.
`tests/suite.py` **OK (181 s)**; plug-and-play **OK nas 24 seções**.

**Cliente de outro armador:** pedindo o trecho de câmera de outro cliente → **403**; da câmera dele →
200. A prova de isolamento exige entrar pela rede (o Windows normaliza qualquer `127.x` para
`127.0.0.1`, e a API trata loopback como bancada).

## Desvios do plano (declarados)

1. `segundos` fora de 10..60 **recusa com 422** em vez de arredondar calado (pedir 1 hora e receber 60 s
   seria mentira).
2. O nome do arquivo termina em `-60s.mp4` (diz o tempo real pedido), não `-1min.mp4`.
3. **Duas correções de causa fora do escopo do plano**, necessárias para o botão funcionar de verdade:
   `trecho.py` não derruba mais a conexão quando as tabelas do bordo (`ingestoes`, `medicoes_qualidade`)
   ainda não existem no lado terra (antes: `no such table` e a rota morria); e `ground/mediamtx.yml`
   passou a subir **só com RTSP/TCP** (`rtspTransports: [tcp]`) com `metricsAddress`/`pprofAddress`/
   `playbackAddress` presos no loopback — o mediamtx **recusava subir** se `:8000` (RTP/RTCP) estivesse
   ocupada, o que quebraria o plug & play na máquina do cliente (foi assim que o teste falhou duas vezes).
