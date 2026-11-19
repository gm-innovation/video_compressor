# Câmeras em stand-by no PC de captura, transmitindo só quando o cliente liga na web — 19/11/2026

Status: **plano para aprovação** (nada implementado)
Dono: Alexandre · Pedido: "precisamos pensar em uma forma de as câmeras ficarem de stand by no
computador de captura e transmitirem apenas quando o cliente ligar na web"

## O que JÁ existe (medido no código, 19/11/2026)

| Peça | Onde | Estado |
|---|---|---|
| Agente que obedece o cliente no bordo | `ground/agente_de_ordens.py` — pergunta `GET /api/ordens?embarcacao_id=…&espera=…`, executa `iniciar` (chama `/api/cameras/ligar` **local**) e `parar`, e devolve o resultado por `POST /api/ordens/<id>/resultado` | pronto |
| Ordem nasce no lado terra quando o **cliente** abre a transmissão | `ground/api.py:2677` (`/api/transmissao/iniciar`) → `enfileirar_ordem(..., "iniciar")` (linha 2724) | pronto |
| Batimento ("estou aqui") e fechamento quando o cliente sai | `/api/transmissao/<id>/batimento`; auditoria `cliente_saiu_da_tela` (visto hoje: 11:59) | pronto |
| Rede de segurança do envio órfão | agente corta sozinho depois de `LECSOR_TETO_DO_BORDO` (padrão 2 h) e guarda o que ligou em `ground/ordens/ligados.json` | pronto |
| Botão "ligar/desligar câmera" no lado terra | `ground/api.py:2309-2322` chama `ingestao.ligar_camera()` **nesta máquina** | **defeituoso** (é a queixa de hoje: lado terra Linux tentando abrir dshow) |

**Ninguém sobe o agente**: `grep` por `agente_de_ordens` em `desktop/*.js`, `desktop/*.sh`, `admin/admin.js` e
`ground/api.py` **não acha nenhuma referência** — hoje ele só roda se alguém chamar na mão. É esse o buraco
entre "existe o mecanismo" e "as câmeras ficam de stand-by".

## Desenho proposto — stand-by = agente vivo, dispositivo FECHADO

- O PC de captura fica com **o servidor local + o agente de ordens no ar**, e as câmeras **cadastradas e ociosas**
  (nenhum ffmpeg rodando, nenhum dispositivo aberto). "Stand-by" **não** é preview local: abrir a webcam mantém o
  LED aceso e o dispositivo ocupado — o dono quer transmitir **só quando o cliente ligar**.
- Cliente abre a transmissão na web → o lado terra enfileira a ordem → o agente (no bordo) chama o `/api/cameras/ligar`
  **local** → a câmera entra no ar e o vídeo sobe; o cliente sai/para de bater o batimento → `parar` → a câmera volta
  ao stand-by; teto de 2 h como rede de segurança.
- O lado terra **nunca** abre câmera: só enfileira ordem e mostra o que o bordo respondeu.

## Fase 1 — O bordo fica pronto, sozinho (P0)

- P0 · O app de captura **sobe e mantém o agente de ordens** (junto do servidor local), com reinício automático se ele
  cair; sem agente vivo a câmera não liga quando o cliente pede — e hoje ninguém o sobe (medido).
- P0 · Lado terra **para de executar captura**: `/api/cameras/ligar|desligar` enfileira ordem (`iniciar`/`parar`) e
  responde "ordem enviada ao bordo" (mesmo P0 do plano `2026-11-19-lado-terra-nao-liga-camera-dshow.md`).
- P1 · Embarque: se o agente não estiver vivo, a tela do lado terra diz **"o bordo não está escutando ordens"** em vez
  de deixar o cliente clicar e nada acontecer.

## Fase 2 — Stand-by visível (P1)

- P1 · Cada câmera mostra o estado **"em stand-by (pronta)"** quando o agente está vivo e nenhum ffmpeg roda para ela —
  vindo do que o bordo informa, não de suposição do lado terra.
- P1 · A checagem de prontidão é **barata**: conferir que o dispositivo existe e ler os formatos **uma vez** (cache),
  sem abrir a câmera em stand-by (não acender o LED, não segurar o dispositivo).
- P2 · Se a câmera sumiu (USB desconectado), o stand-by diz "câmera ausente" e o cliente vê isso **antes** de pedir.

## Fase 3 — Ligar e desligar com o cliente (P1)

- P1 · Ligar: ordem `iniciar` → agente → `/api/cameras/ligar` local, com o ajuste já fixado por câmera (alvo/qualidade).
- P1 · Desligar por três caminhos, todos medidos no bordo: cliente saiu da tela / batimento parou (`SEGUNDOS_SEM_BATIMENTO`),
  teto do bordo (2 h); e um quarto manual (operador pede "parar").
- P2 · Volta ao stand-by sempre que a transmissão terminar — inclusive quando o **cliente cai** sem avisar.

## Fase 4 — Provas (P1)

- P1 · Teste novo: com o lado terra de prova, um pedido de transmissão do cliente **não abre ffmpeg nenhum no lado terra**
  e cria ordem; o agente de prova atende e a câmera liga no bordo (mesmo caminho do `e2e-envios`).
- P1 · Teste novo: câmera em stand-by → nenhum processo de captura rodando; depois da ordem → um processo; depois do
  `parar`/teto → nenhum (medido por processo, não por texto na tela).
- P1 · Teste novo: cliente abre, o batimento para, o bordo para sozinho e a câmera volta ao stand-by.
- P1 · Não regredir: `tests/test-agente-de-ordens.py`, `e2e-envios.py`, `test-app-unico-por-papel.py`,
  `e2e-tela-limpa-do-admin.py` e `test-grade-do-cliente-nao-corta-o-topo.py`.

## Fase 5 — Publicação (P1/P2)

- P1 · Commit/push; deploy do lado terra (`ground/api.py`, `admin/admin.js`) com reinício do serviço e conferência de
  `/api/saude`, `/api/ordens`, `/api/tempo-real`.
- P1 · App novo (**0.6.10**) levando o agente no pacote e o start automático (o pacote embute o servidor e a tela).
- P2 · Runbook no vault + `index.md` + push.

## Riscos e decisões abertas

- **Stand-by com o dispositivo fechado** é a proposta; manter preview local no bordo gastaria CPU e manteria o LED aceso —
  não é o pedido do dono.
- **Quem pode ligar**: hoje só o cliente pede (regra do produto). O botão do admin no lado terra passa a ser "enviar ao
  bordo" em vez de ligar localmente.
- **Um agente por embarcação**: a ordem é da embarcação (`LECSOR_EMBARCACAO`); duas embarcações = um agente por PC.

## O que NÃO muda

- Nada de vídeo/fps/banda/qualidade, cadastro, auditoria imutável, cotas do Supabase, nem o "nada é apagado" da trilha.
