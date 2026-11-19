# Transmitir do DVR só quando o cliente ativar no painel web — 19/11/2026

Status: **substituído** — o dono esclareceu (19/11/2026) que não lemos o DVR: o sinal é **dividido por um split** e a nossa máquina de captura lê a própria entrada. Plano válido: `2026-11-19-stand-by-com-sinal-dividido-no-pc-de-captura.md`.
Dono: Alexandre · Modelo do produto (palavras do dono): "as câmeras ficam filmando o tempo todo e conectadas ao
DVR e ao nosso sistema, o DVR fica gravando o tempo todo, o nosso sistema transmite apenas quando o cliente
ativar no painel web".

## Modelo

O DVR é quem captura e grava (sempre). O nosso sistema **não** segura câmera: no PC de captura ele fica
pronto (stand-by) e, quando o cliente ativa o canal no painel, abre **o fluxo do DVR**, comprime e sobe para o
lado terra; quando o cliente sai, para e volta ao stand-by. O DVR continua gravando por fora, indiferente.

## O que JÁ existe e o que FALTA (medido no código, 19/11/2026)

| Peça | Onde | Estado |
|---|---|---|
| Cadastro do canal por endereço | `cameras.ip`, `porta`, `protocolo` (padrão `rtsp`), `canal` — `ground/api.py:465`, `:2521` | pronto |
| Molde do endereço do canal | `rtsp://$USUARIO:$SENHA@<ip>:<porta>` — `ground/api.py:1800` (**sem credencial no código**) | pronto |
| Campo do segredo | `credencial_ref TEXT` — `db/schema.sql:31` ("referencia ao cofre/ambiente; o segredo nunca entra aqui") | **existe e ninguém lê** (medido: nenhuma referência no código) |
| Fonte viva aceita hoje | `ingestao.ao_vivo()` só aceita `camera` (dshow), `sintetica`, `radar` — **não há fonte RTSP/DVR** | **falta** |
| Ligar câmera por endereço | `ingestao.ligar_camera()` **recusa** câmera com `ip` ("precisa de credencial: use Enviar video") — `ground/ingestao.py:582-583` | **falta** |
| Ordens do cliente → bordo | `/api/transmissao/iniciar` → `enfileirar_ordem(..., "iniciar")` (`api.py:2677-2724`); agente `ground/agente_de_ordens.py` atende `iniciar`/`parar`, com teto de 2 h e estado em disco | pronto |
| Parar quando o cliente sai | `/batimento` + `SEGUNDOS_SEM_BATIMENTO` + auditoria `cliente_saiu_da_tela` | pronto |
| Agente sendo subido no PC de captura | `grep` por `agente_de_ordens` em `desktop/`, `admin/`, `ground/api.py` = **nenhuma referência** | **falta** |
| Lado terra ligando câmera localmente | `api.py:2309-2322` chama `ligar_camera()` nesta máquina (Linux, sem dshow) — a queixa de hoje | **defeituoso** |
| Leitores RTSP que já rodam | apontam só para o retransmissor local `rtsp://127.0.0.1:8554/<fluxo>` (`repasse.py`, `trecho.py`, `gravacao.py`) | pronto (outro papel) |

## Decisão aberta (P0, precisa do dono antes de implementar)

**Copiar ou recomprimir o canal do DVR?** O canal do DVR já sai comprimido (H.264/H.265). Copiar (`-c:v copy`)
não gasta CPU, mas **não reduz banda** — e a redução de banda é o produto. Recomprimir entrega o alvo de
300 kbps–1500 kbps com a qualidade que o cliente escolhe. Terceira via, se o DVR tiver: usar o **substream**
(segundo fluxo) do DVR. Não medido: quantos fluxos simultâneos o DVR/este modelo entrega, e se ele fala H.265.

## Fase 1 — O bordo abre o canal do DVR sob ordem (P0)

- P0 · Fonte viva nova (`dvr`/`rtsp`) no `ingestao.ao_vivo()` e no `_comando()`: endereço montado de
  `ip`+`porta`+`protocolo`+`canal`+credencial, com `-rtsp_transport tcp` (o transporte que os leitores do produto
  já usam) e reconexão se o canal cair.
- P0 · `ligar_camera()` deixa de recusar câmera com `ip`: monta o endereço do canal do DVR pela credencial
  referenciada e abre **sob ordem** (nunca por varredura nem em stand-by).
- P0 · Stand-by do canal **fechado**: em repouso o bordo **não** abre o RTSP do DVR (nem para "espiar"), só sabe
  que o canal existe e está pronto; abrir só quando o cliente ativa.
- P1 · Se o DVR aceitar poucas conexões, o produto **não** abre o mesmo canal duas vezes (registro de canal em uso,
  como já existe para a webcam).

## Fase 2 — Credencial do DVR (P0)

- P0 · `credencial_ref` passa a ser lida **só no ambiente/cofre da máquina de captura** (variável de ambiente ou
  arquivo de cofre fora do repositório); a URL com usuário e senha é montada em memória, **nunca** gravada no
  banco, **nunca** em log, **nunca** devolvida à tela nem ao lado terra.
- P0 · Aquisição dentro da VPN: o endereço do DVR não é publicado na internet; o PC de captura fala com o DVR
  pela rede interna (regra que já vale para a captura).
- P0 · Usuário dedicado **somente-leitura e temporário** no DVR, entrega por cofre/variável no servidor de
  captura, autorização escrita do cliente anexa a este plano, revogação no fim da fase — e o caminho de erro
  nunca imprime a credencial (teste que grepa a resposta e o log).
- P1 · Se a credencial faltar: recado claro ("o canal existe e a credencial do DVR não está configurada nesta
  máquina"), não um erro cru de ffmpeg.

## Fase 3 — Quem manda: lado terra só enfileira ordem (P0)

- P0 · `/api/cameras/ligar|desligar` no lado terra **não** executa captura: enfileira ordem ao bordo e responde
  "ordem enviada" (mesmo P0 do plano `2026-11-19-lado-terra-nao-liga-camera-dshow.md`).
- P0 · O app do PC de captura **sobe e mantém o agente de ordens** (hoje ninguém o sobe — medido), com reinício
  automático; sem agente vivo, o lado terra diz "o bordo não está escutando ordens".
- P1 · Estado do canal vindo do bordo: "pronto (stand-by)", "no ar (cliente X)", "canal ausente" — nunca inferido
  pelo lado terra.

## Fase 4 — Ligar e desligar com o cliente (P1)

- P1 · Cliente ativa o canal no painel → ordem `iniciar` → bordo abre o DVR, comprime no alvo e sobe → o vídeo
  aparece nas telas (cliente, Tempo real, Produção), sem cadastro pendente.
- P1 · Desligar por quatro caminhos: cliente saiu da tela, batimento parado, teto do bordo (2 h) e pedido do
  operador; em todos, a câmera volta ao stand-by e o DVR segue gravando por fora.
- P2 · Se o cliente voltar, nova ordem liga de novo (nada de sessão "presa").

## Fase 5 — Provas (P1)

- P1 · **DVR de prova**: um ffmpeg publicando um canal RTSP local (com usuário e senha) faz o papel do DVR; o
  teste prova, por **processo**: nenhum ffmpeg em stand-by; um ffmpeg depois da ativação do cliente; nenhum
  depois de sair/teto.
- P1 · Prova de segredo: a resposta da API, o log do envio e o banco **não** contêm a senha do DVR (grep no que foi
  gravado), e a tela do cliente nunca recebe endereço nem credencial.
- P1 · Prova de ordem: o lado terra **não** abre ffmpeg; a ordem chega ao bordo e o resultado volta ao lado terra.
- P1 · Não regredir: `tests/test-agente-de-ordens.py`, `e2e-envios.py`, `test-app-unico-por-papel.py`,
  `e2e-tela-limpa-do-admin.py`, `test-grade-do-cliente-nao-corta-o-topo.py`.

## Fase 6 — Publicação e limpeza (P1/P2)

- P1 · Commit/push; deploy do lado terra (`ground/api.py`, `ground/ingestao.py`, `admin/admin.js`) com reinício e
  conferência de `/api/saude`, `/api/ordens`, `/api/tempo-real`.
- P1 · App novo (**0.6.10**) levando o agente e o start automático (o pacote embute o servidor).
- P2 · Runbook no vault + `index.md` + push; as tentativas de erro de hoje (ingestoes 186–191) **ficam** na trilha
  (nada é apagado) e o que os testes de prova criarem é removido no fim.

## Riscos

- **Banda e CPU**: recomprimir o canal exige CPU no PC de captura (um processo por canal ativo) — medir quantos
  canais simultâneos a máquina aguenta.
- **DVR**: número de conexões simultâneas, codec e existência de substream — **não medido**; sem isso não dá para
  prometer quantos canais ao mesmo tempo.
- **Latência**: alvo do produto ≤ 3 s; o DVR adiciona o atraso dele (medir no primeiro canal real).

## O que NÃO muda

- O DVR continua gravando e guardando o que é dele; o "nada é apagado" nosso é a trilha de auditoria imutável.
- Nada muda em banda por qualidade escolhida, fps 30, cadastro pelo admin, Supabase (fora do ao vivo) e no
  "gravação só até o cliente sair" (a varredura segue apagando o que ninguém baixou após `LECSOR_MINUTOS_PARA_BAIXAR`).
