# "As câmeras não religam — ffmpeg saiu com codigo 234: Error opening input files: Invalid argument" — 19/11/2026

Status: **plano para aprovação** (nada implementado)
Dono: Alexandre · Queixa: câmeras não religam, com `ERRO: ffmpeg saiu com codigo 234: Error opening input files: Invalid argument`

## Causa MEDIDA (base do lado terra + log do próprio ffmpeg)

| Evidência | O que diz |
|---|---|
| `ingestoes` id 186–191 (base do **lado terra**, VPS): `fluxo_id` `vivo-cam01-1811`/`vivo-cam02-1811`, `tipo=camera`, `resolucao=1920x1080`, `alvo=300k`, todos `estado=erro` | as tentativas de ligar rodaram **no lado terra**, uma atrás da outra, entre 11:52 e 11:53 UTC de hoje |
| `erro` gravado | `ffmpeg saiu com codigo 234: Error opening input files: Invalid argument` (exatamente a mensagem do dono) |
| `log` = `/opt/pipeline/app/ground/envios/log/vivo-cam02-1811-…log` (**caminho do VPS**) e o conteúdo do arquivo | `[in#0] Unknown input format: 'dshow'` + `Error opening input file video=@device_pnp_\\?\usb#vid_534d\&pid_2109…` + `Error opening input files: Invalid argument` |
| `auditoria_acesso` 4168–4172 | `admin@lecsor.test` → `camera_ligada` em `vivo-cam01-1811`/`vivo-cam02-1811` **6 vezes em 1 minuto** (IPs 191.190.36.254 e 189.1.136.122) |
| Código | `ground/api.py:2309-2322` (`/api/cameras/ligar` · `/api/cameras/desligar`) chama `ingestao.ligar_camera(cam_id)` **nesta máquina**, sem olhar se esta máquina é a de captura; o caminho que enfileira ordem (`enfileirar_ordem`, `api.py:2724`) só é usado no pedido do **cliente** |
| Código | `ground/ingestao.py:374-406` (`_motivo_da_falha`) **não** conhece `Unknown input format`/`dshow` → cai no genérico *"ffmpeg saiu com codigo N: <última linha>"*, e é por isso que a tela mostra a linha crua do ffmpeg |

**Leitura:** as câmeras são USB/dshow do PC de captura (`vid_534d&pid_2109`), e quem apertou "ligar" foi o **admin no lado terra** — que é Linux e não tem dshow. `234` é `−22` (EINVAL), igualzinho ao `Invalid argument`. Medido nas duas ffmpeg desta bancada (9.0.1 e a do produto, 9.0.2): falha de dshow no **Windows** dá **`I/O error`** — `Invalid argument` é a assinatura do **Linux sem dshow**. Não é defeito da câmera nem do PC de captura.

## Fase 1 — O lado terra para de tentar capturar (P0)

- P0 · `/api/cameras/ligar` e `/api/cameras/desligar`: se **esta máquina não é a de captura**, **não** chamar `ingestao.ligar_camera`; **enfileirar ordem** para o bordo (`iniciar`/`parar`) e responder à tela "ordem enviada ao bordo (aguardando o PC de captura)".
- P0 · Nunca executar ffmpeg de captura no lado terra (nem no `desligar`, que hoje também mexe em processo local).
- P1 · Mesmo critério que já existe em `/api/eu` (campo `local`) e nos botões: captura só existe onde a câmera está plugada.

## Fase 2 — A tela diz a verdade (P0 na mensagem, P1 no desenho)

- P0 · `_motivo_da_falha` ganha os casos `unknown input format` / `dshow` → *"esta máquina não é a de captura: esta câmera abre no PC de bordo — use 'enviar ao bordo'"*. Nunca mais a linha crua do ffmpeg como motivo principal (o log continua guardado).
- P1 · Na tela do lado terra, o botão da câmera passa a ser **"enviar ao bordo"** (não "ligar"), e o estado mostrado vem do que o bordo respondeu (`ordens_do_bordo`), não de um processo local.

## Fase 3 — Ordem e resposta com rastro (P1)

- P1 · `camera_ligada`/`camera_desligada` na auditoria passam a registrar **quem pediu, para qual bordo e com que ordem** (hoje registra como se a captura tivesse acontecido ali).
- P2 · `ordens_do_bordo` sem resposta do bordo ganha aviso na tela (a máquina 150/90 s já existe para ordens do cliente); conferir se vale o mesmo prazo aqui.

## Fase 4 — Provas (P1)

- P1 · Teste novo: **lado terra não abre dshow** — com uma base de lado terra (sem câmera), `/api/cameras/ligar` responde "ordem enviada" e **nenhum** processo de ffmpeg sobe nesta máquina.
- P1 · Teste novo: o **bordo** atende a ordem e liga a câmera (mesmo caminho do `e2e-envios`).
- P1 · Teste novo: `_motivo_da_falha` com o log real desta queixa devolve o recado de "máquina errada", não o genérico.
- P1 · Não regredir: `e2e-envios`, `test-app-unico-por-papel`, `e2e-tela-limpa-do-admin`, e a prova nova da grade (`test-grade-do-cliente-nao-corta-o-topo`).

## Fase 5 — Publicação (P1/P2)

- P1 · Commit/push, deploy do lado terra (`scp` de `ground/api.py` + `ground/ingestao.py`, `systemctl restart`), conferir `/api/saude`, `/admin/`, `/api/tempo-real`.
- P1 · App: se `admin/admin.js` mudar, sai versão nova (**0.6.10**) — o pacote embute a tela.
- P2 · Runbook no vault + `index.md` + push. As 6 tentativas de erro de hoje (ids 186–191) **ficam** na trilha (nada é apagado); o teste é que passa a falhar honestamente.

## O que NÃO muda

- Nada de vídeo, fps, banda, qualidade, cadastro, auditoria imutável ou do fluxo de transmissão pedida pelo cliente.

## Provas que fecham este plano

1. No lado terra: nenhum processo de captura sobe e a resposta é "ordem enviada".
2. No bordo: a ordem chega, a câmera liga e o vídeo aparece na tela do cliente.
3. Motivo na tela legível (sem linha crua de ffmpeg) para o caso medido hoje.
4. Bateria que já existe continua verde.
