# Stand-by no PC de captura com o sinal DIVIDIDO (split) — transmitir só quando o cliente ativar — 19/11/2026

Status: **implementado e provado** (0.6.10) — dono aprovou em 19/11/2026 ("aprovado").
Substitui `2026-11-19-transmitir-do-dvr-so-quando-o-cliente-ativar.md` (modelo errado: não lemos o DVR).

Dono (palavras dele): "os cabos das câmeras têm um split que divide o sinal e envia para o DVR e para o nosso
computador de captura" · "o DVR fica gravando o tempo todo, o nosso sistema transmite apenas quando o cliente
ativar no painel web".

## Causa-raiz medida (além da do plano)

O servidor local do PC de captura **encaminhava** ao lado terra tudo o que não fosse rota de captura, e
`/api/cameras/ligar|desligar` **não** estava na lista `ROTAS_CAPTURA` (`ground/api.py:42`). Resultado: o clique
de ligar no PC de captura (cujas telas vêm do servidor local) era repassado ao **lado terra**, que rodava
`ffmpeg -f dshow` no Linux → `Unknown input format: 'dshow'` / `codigo 234`. Essa é a origem exata da queixa
"as câmeras não religam" (medido 19/11/2026, `ingestoes` 186-191 na base do lado terra).

## Provas (medidas nesta implementação)

| Prova | O que mede | Resultado |
|---|---|---|
| `tests/test-lado-terra-nao-captura.py` | lado terra: ligar/desligar viram ordem; **nenhum** ffmpeg e **nenhum** envio nascem nele; trilha com `ordem_camera_ligada/desligada`; o bordo continua capturando | **11/11 OK** |
| `tests/test-stand-by-do-captura.py` | por **processo** (câmera real desta máquina + mediamtx de teste): zero ffmpeg em stand-by · um depois de ativar · zero depois de sair; `ausente` antes do clique; medir prontidão não abre câmera | **8/8 OK** |
| `tests/test-motivo-maquina-errada.py` | log real de 19/11 vira o recado "não é a de captura"; câmera ocupada mantém o recado antigo; log genérico não vira "máquina errada" | **3/3 OK** |
| `test-agente-de-ordens` · `test-camera-liga-desliga` · `test-transmissao-a-pedido` · `test-anuncio-do-cadastro` · `test-fluxo-sem-cadastro-na-tela` | não regressão do caminho ordem→bordo e do cadastro | **todos rc=0** |

## Arquitetura do sinal (falado pelo dono, 19/11/2026)

Cada câmera tem o sinal **dividido no cabo**: uma via vai para o **DVR** (que grava por conta dele) e a outra
chega ao **nosso PC de captura**. Não existe RTSP, credencial de câmera, VPN ou DVR no nosso caminho: nós lemos
a entrada que o split entrega (`dshow:<dispositivo>`), e essa é a lista que a prontidão consulta.

## Modelo (corrigido)

Cada câmera tem o sinal **dividido no cabo**: uma via vai para o **DVR** (que grava por conta dele, sem relação
com o nosso sistema) e a outra via chega ao **nosso PC de captura**, onde é lida pelo **nosso próprio
dispositivo de captura**. Não existe RTSP, credencial de câmera, VPN ou DVR no meio: nós lemos a entrada que o
split entrega. O que o produto faz é: ficar **pronto (stand-by)** com o dispositivo fechado e, quando o cliente
ativa o canal no painel web, abrir a entrada, comprimir e transmitir; quando ele sai, parar e voltar ao stand-by.

## Evidência medida (base do lado terra, hoje 11:52–11:53 UTC)

`ingestoes` 186–191: `vivo-cam01-1811` e `vivo-cam02-1811`, `tipo=camera`, `resolucao=1920x1080`, `alvo=300k`,
todas `estado=erro`; a `fonte` de cada uma é um dispositivo **USB do PC de captura** —
`dshow:@device_pnp_\\?\usb#vid_534d&pid_2109&mi_00#…` — e o `log` de cada tentativa está no **lado terra**
(`/opt/pipeline/app/ground/envios/log/…`) com `Unknown input format: 'dshow'`. Ou seja: o caminho do produto para
esse caso **é o dshow local** (o nosso dispositivo de captura), e o erro de hoje foi o lado terra tentando abrir
esse dispositivo — não o DVR e não a câmera.

## Fase 1 — Quem captura é a máquina de captura (P0)

- P0 · `/api/cameras/ligar|desligar` **no lado terra** deixa de chamar `ingestao.ligar_camera()` (captura nesta
  máquina): enfileira ordem ao bordo (`iniciar`/`parar`) e responde "ordem enviada ao bordo".
- P0 · O app do PC de captura **sobe e mantém o agente de ordens** com reinício automático — hoje nenhuma parte do
  app ou da API o sobe (medido: nenhuma referência a `agente_de_ordens` em `desktop/`, `admin/`, `ground/api.py`).
- P1 · Sem agente vivo, a tela do lado terra diz "o bordo não está escutando ordens" em vez de deixar o clique não
  fazer nada.
- P1 · Motivo de falha legível: `ground/ingestao.py:374-406` passa a reconhecer `unknown input format` / `dshow` e
  diz "esta máquina não é a de captura" — nunca mais a linha crua do ffmpeg como motivo.

## Fase 2 — Stand-by = dispositivo FECHADO (P0)

- P0 · Em repouso **nenhum ffmpeg roda** e o dispositivo de captura **não fica aberto** (ler a entrada sem
  transmitir só gasta recurso e ocupa o dispositivo; o sinal está lá o tempo todo, vindo do split).
- P0 · Estado do canal, por câmera e vindo do bordo: **pronta (stand-by)** · **no ar** · **ausente** — nunca
  inferido pelo lado terra.
- P1 · Checagem de prontidão barata: confirmar que o dispositivo existe na máquina (`-list_devices`, que **não**
  abre a câmera) e ler os formatos **uma vez** (cache já existe em `ingestao._FORMATOS`); se o dispositivo sumiu,
  "ausente" aparece **antes** de o cliente ativar.
- P2 · Aviso na tela do PC de captura quando o dispositivo estiver em uso por outro envio (a regra de "webcam só
  abre uma vez" já existe no produto).

## Fase 3 — Ligar e desligar com o cliente (P1)

- P1 · Cliente ativa no painel → ordem `iniciar` → bordo abre o **nosso dispositivo** (dshow, caminho que já
  existe: `ao_vivo(tipo="camera")`), comprime no alvo já fixado por câmera (300k–1500k) e sobe para o lado terra.
- P1 · Desligar por quatro caminhos, todos no bordo: cliente saiu da tela · batimento parou
  (`SEGUNDOS_SEM_BATIMENTO`) · teto do bordo (2 h, `LECSOR_TETO_DO_BORDO`) · pedido do operador — e em todos a
  entrada é fechada e a câmera volta ao stand-by.
- P1 · Nada de preview local no bordo (não pedir "espelhar" a imagem na máquina de captura).
- P2 · Cliente que volta depois de sair gera nova ordem (nada de sessão presa).

## Fase 4 — Provas (P1)

- P1 · Prova por **processo** (não por texto na tela): em stand-by, zero ffmpeg; depois da ativação do cliente, um
  ffmpeg; depois de sair/teto, zero — e o dispositivo volta a ficar livre.
- P1 · Prova de ordem: com um lado terra de prova, o clique do cliente **não** abre ffmpeg no lado terra e cria
  ordem; o agente de prova atende e a câmera liga no bordo (mesmo caminho do `e2e-envios.py`).
- P1 · Prova do motivo: com o log real de hoje, a tela mostra o recado de "máquina errada", não o genérico.
- P1 · Não regredir: `tests/test-agente-de-ordens.py`, `e2e-envios.py`, `test-app-unico-por-papel.py`,
  `e2e-tela-limpa-do-admin.py`, `test-grade-do-cliente-nao-corta-o-topo.py`.

## Fase 5 — Publicação e limpeza (P1/P2)

- P1 · Commit/push; deploy do lado terra (`ground/api.py`, `ground/ingestao.py`, `admin/admin.js`) com reinício e
  conferência de `/api/saude`, `/api/ordens`, `/api/tempo-real`.
- P1 · App novo (**0.6.10**): o pacote embute a tela e o servidor, e passa a levar o start automático do agente.
- P2 · Runbook no vault + `index.md` + push; o que os testes criarem é removido no fim (as 6 tentativas de erro de
  hoje, ingestoes 186–191, **ficam** — a trilha não é apagada).

## Riscos e o que não está medido

- Quantos dispositivos de captura a máquina de captura tem e quantos canais simultâneos ela aguenta (CPU por canal
  ativo) — **não medido**.
- O split entrega o mesmo sinal para o DVR e para nós: se o splitter enfraquecer o sinal, a imagem de entrada pode
  piorar — **não medido**.
- Nome/formato que cada dispositivo aceita (o produto já lê a lista real e escolhe o maior tamanho que cabe no
  pedido; medido nas provas de 17/11/2026).

## O que NÃO muda

- Nada de RTSP/DVR/credencial de câmera (não há): o caminho é o dispositivo local.
- Nada de fps 30, alvos de banda por qualidade, cadastro pelo admin, Supabase (fora do ao vivo) e no
  "gravação só até o cliente sair" com a varredura após `LECSOR_MINUTOS_PARA_BAIXAR`.
