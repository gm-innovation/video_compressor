# Transmissão a pedido do cliente (navegador, com tempo máximo e corte ao fechar) — 17/11/2026

**Pedido do dono (verbatim, 17/11/2026):**
1. "o cliente deve poder acessar via web, sem necessidade de instalar app"
2. "o cliente define quando inicia o streaming"
3. "pode definir um tempo máximo de streaming"
4. "quando fecha a tela, ou desliga o computador, interrompe o streaming"

Hoje **quem inicia é a operação/técnico, na máquina de captura** (menu "Enviar vídeo" → `/api/ingestao/ao-vivo`).
Não existe canal do lado terra para o bordo: a embarcação só **publica** para a VPS (anúncio/declaração);
nada hoje manda ordem de terra para a máquina de captura.

## O que já existe hoje (lido no código, não estimado)

- **A tela do cliente já é web.** `/app/` é servida pela VPS (`app/index.html` + `app/app.js` + `/fronts/video.js`),
  com **WebRTC (WHEP em `/whep/<fluxo>`) e HLS de reserva (`/hls/<fluxo>/index.m3u8`)** — nada disso exige o
  aplicativo instalado; o aplicativo existe para a **captura** (webcam/dshow desta máquina).
- **Quem inicia hoje:** `POST /api/ingestao/ao-vivo` e `/api/envios/ao-vivo` — rotas de **captura** (exigem
  operação/admin ou chamada local). O cliente **não** tem por onde pedir.
- **A tela do cliente tem botões de ligar/desligar câmera** (`app/app.js` → `/api/cameras/ligar|desligar`), mas
  essa rota, quando chamada no lado terra, roda a captura **na própria VPS** (não na embarcação) e a própria
  rota diz "quem manda é a operação (o cliente só olha)" — ou seja, o botão do cliente hoje é mentiroso.
- **Não existe** tempo máximo, sessão de quem assiste, nem batimento da tela do cliente. O envio ao vivo roda
  "até alguém parar".
- **A embarcação pergunta alguma coisa para a VPS?** Não. Os únicos relógios existentes são na tela do Admin
  (`atualizar` a cada 15 s, envios a cada 5 s). O canal bordo→terra existe (repasse/declarado); o terra→bordo, não.

## Fases (prioridade marcada dentro de cada fase)

### Fase 1 — Cliente pela web, sem instalar nada (P0)
- **P0 — Provar de ponta a ponta no navegador (é a prova que o dono cobra):** abrir `/app` num navegador de
  verdade (sem Electron), entrar com a conta do cliente, ver a imagem ao vivo (WHEP e, derrubando o WebRTC, a
  reserva HLS) e o "Baixar 1 minuto". Registrar o medido (tempo até a imagem, resolução/fps, se caiu para HLS).
- **P0 — Arrancar o botão mentiroso:** tirar do cliente (ou transformar em pedido, Fase 2) o ligar/desligar que
  hoje bate numa rota de captura do lado terra.
- **P1 — Atalho para o cliente:** o lado terra passa a avisar o endereço da tela (`/app`) no pacote de entrega
  e na entrada, para o cliente só abrir o link (sem manual).
- **P1 — Abrir no celular:** conferir largura/rolagem em tela de celular (a mesma tela, sem PWA por enquanto).
- **P2 — Instalável opcional (PWA/manifest)** — só se o dono quiser ícone na tela inicial; o produto **não**
  depende disso.

### Fase 2 — O cliente define quando inicia (P0)
- **P0 — A ordem nasce em terra e vai até o bordo (decisão do dono, 17/11/2026: "a ação vai de terra para
  bordo").** Nova tabela no lado terra (`pedidos_de_transmissao`: embarcação, quem pediu, câmeras, alvo, tempo
  máximo, estado, criado/entregue/atendeu/expirou) e a entrega da ordem **pelo canal que o bordo já mantém
  aberto com o lado terra** (o bordo continua sem abrir porta nenhuma — é o lado terra que fala, por cima da
  ligação que o bordo abriu). O bordo obedece direto, sem confirmação de ninguém (D5) e responde o resultado
  (ligou/não ligou e por quê).
- **P0 — A tela do cliente ganha "Iniciar transmissão" / "Parar"** por embarcação, com o estado honesto:
  *pedido enviado* → *máquina não está on-line* → *no ar* → *parado por você / pelo tempo / sem sinal*.
- **P0 — Quem pode pedir (decisão do dono: "apenas o cliente"):** só o cliente **daquela** embarcação. Cliente
  de outra embarcação recebe recusa explícita — testar no negativo (é a regra que mais pode vazar). As funções
  de captura da operação **continuam como estão** (a operação não perde nada); este fluxo novo é do cliente.
- **P1 — A operação vê e pode cancelar** o pedido. **Não existe técnico a bordo** (decisão do dono): o app de
  captura obedece direto, sem ninguém confirmar na embarcação.
- **P1 — Estado no banco de verdade:** o pedido não pode "ligar" se a máquina estiver fora do ar; a tela diz
  isso em vez de girar para sempre.
- **P2 — Fila/janela de horário** (ex.: só dentro de um horário permitido) — só se o dono pedir.

### Fase 3 — Tempo máximo em tela de configuração (P1)
- **P0 — Tela de configuração do cliente** (decisão do dono: "uma tela de configuração onde pode determinar o
  tempo"): o tempo máximo de cada transmissão é definido ali e vale para os pedidos seguintes.
- **P0 — Ao estourar o tempo, a transmissão é encerrada e o cliente reinicia (decisão do dono, 17/11/2026:
  "o cliente reinicia")** — nada de reinício automático. Exceção: se estiver **gravando**, o corte não acontece,
  para não picar a gravação.
- **P0 — Trava nos dois lados:** a máquina de captura **não** transmite além do teto (ela mesma corta) e o lado
  terra também corta; se um lado falhar, o outro cumpre.
- **P1 — Tempo restante na tela** do cliente (e o motivo, em voz alta: "o tempo acabou — inicie de novo" /
  "seguindo porque está gravando").
- **P2 — Teto máximo do produto**, definido pelo admin (o cliente não pode passar disso).

### Fase 4 — Fechar a tela ou desligar o computador para o streaming (P0)
- **P0 — Batimento da tela:** a tela do cliente manda um "estou aqui" a cada ~10 s (com a sessão do pedido);
  sem batimento por ~60 s o lado terra considera a sessão morta e manda **parar**.
- **P0 — Ao fechar a aba/navegador** (`visibilitychange`/`pagehide` + `navigator.sendBeacon`) o aviso de parada
  sai na hora — o batimento é a rede de segurança para quando a máquina desliga ou a rede cai.
- **P0 — Desligar o computador** = mesma coisa: sem batimento, para em até ~60 s (medir de verdade: matar o
  navegador e contar o tempo até o envio cair).
- **P0 — O corte é por sessão (decisão do dono: "pra quem fechou, se outro está vendo é porque também é
  cliente"):** fechar a tela/desligar derruba **a sessão de quem fechou**; se outro cliente está vendo, a
  transmissão continua para ele. A transmissão só para de vez quando **não houver nenhuma sessão viva**.
- **P1 — Fim da linha para o bordo:** a parada tem de chegar mesmo se o pedido tiver sido atendido por outra
  sessão; e um envio órfão (sem pedido vivo) é cortado pelo próprio bordo depois do teto.

### Fase 5 — Histórico de tudo que for feito (P0) e gravação
- **P0 — Histórico completo (decisão do dono: "tudo que for feito deve permanecer no histórico"):** toda
  sessão entra no histórico — quem pediu, de qual embarcação, quando iniciou, quando terminou, quanto durou,
  **por que terminou** (o cliente parou / fechou a tela / o tempo estourou / a máquina caiu / sem sinal) e se
  houve gravação. Nada de apagar: o histórico é a prova do que foi transmitido.
- **P0 — O que hoje já existe vira histórico:** os avisos já registrados pelo lado terra (auditoria) passam a
  incluir o início/fim de cada transmissão pedida pelo cliente, com o mesmo formato e no mesmo lugar.
- **P0 — O cliente vê o histórico da embarcação dele** (lista simples: quando, quanto tempo, o que foi feito).
- **P1 — Gravação no lado terra (decisão do dono, 17/11/2026):** grava-se o vídeo que já chegou pela rede, na
  VPS — não no bordo (não gasta banda do link da embarcação). É a gravação em andamento que faz o corte por
  tempo ser pulado.
- **P1 — Exportar/baixar a gravação** do histórico (o "Baixar 1 minuto" de hoje é o embrião disso).
- **P2 — Retenção e limpeza** de gravações antigas (com aviso, nunca às escondidas).

### Fase 6 — Provar tudo junto, sem regredir (P1)
- **P0 — Suíte completa** (hoje `Ran 1 test in 608,445s`, OK) mais os testes novos das fases 1–5 verdes.
- **P0 — Prova de TELA** das duas pontas: cliente no navegador (iniciar, ver, tempo restante, fechar → parou) e
  a máquina de captura obedecendo o pedido (incluindo o pedido de parada e a máquina fora do ar).
- **P1 — Nada que já está testado pode regredir:** captura pela webcam, radar (fases 3–6), 0.6.x, alvo por
  câmera, qualidade/SSIM, login/cadastro pelo administrador.
- **P2 — Documento de instalação** (o que muda no PC de captura e o link que o cliente abre).

## Decisões do dono (17/11/2026) — fechadas

- **D1 — Quem pode iniciar:** "apenas o cliente".
- **D2 — Caminho da ordem:** "a ação vai de terra para bordo" — a ordem nasce no lado terra e é entregue ao
  bordo pelo canal que o bordo abre (o bordo não abre porta).
- **D3 — Fechou a tela e outro está vendo:** "pra quem fechou, se outro está vendo é porque também é cliente" —
  derruba só a sessão de quem fechou; a transmissão continua para o outro.
- **D4 — Tempo máximo:** "uma tela de configuração onde pode determinar o tempo, ao estourar, precisa reiniciar a
  transmissão, a menos que esteja gravando, tudo que for feito deve permanecer no histórico".
- **D5 — Técnico a bordo:** "não tem técnico, é direto com o app de captura, a máquina obedece direto".

## Pontos que estavam ambíguos — fechados pelo dono (17/11/2026)

- **Ao estourar o tempo:** "o cliente reinicia" — a transmissão é encerrada e o cliente inicia de novo. A exceção
  "a menos que esteja gravando" segue valendo: gravando, não corta.
- **Onde fica a gravação:** "lado terra" — o vídeo que chegou pela rede, na VPS.


## Estado da execução (17/11/2026 — o que já está feito e provado)

- **Banco:** `db/schema-transmissao.sql` — `transmissoes` (histórico, nada apagado), `ordens_do_bordo`
  (ordem nasce em terra e é entregue ao bordo), `configs_do_cliente` (tempo por cliente).
- **Lado terra (`ground/api.py`):** GET `/api/transmissao` (no ar + histórico + tempo), POST
  `/api/transmissao/iniciar` (**só cliente**), `/api/transmissao/<id>/batimento`, `/encerrar`,
  `/gravando` (gravação **no lado terra**), GET `/api/gravacoes/<id>` (baixar), GET `/api/ordens`
  (o bordo pergunta e obedece) e `/api/ordens/<id>/resultado`; vigia `vigiar_transmissoes`
  (sem batimento 60 s, tempo máximo, entrega lenta 90 s).
- **Bordo:** `ground/agente_de_ordens.py` — pergunta o lado terra e executa direto (`iniciar`→ligar,
  `parar`→desligar); não abre porta; API local fora do ar **nunca** vira "atendida".
- **Gravação (`ground/gravacao.py`):** grava o que **já chegou** pela rede (`-c copy`), arquivo
  fragmentado durante a gravação (sobrevive a queda da máquina) e remontado em mp4 normal ao parar.
- **Tela (`app/index.html`, `app/app.js`, `fronts/vms.css`):** grupo "Transmissão" (Transmitir) +
  "Tempo de transmissão"; tempo restante, quem está assistindo, botão de gravar, histórico com
  "baixar (X MB)".
- **Provas (todas verdes):** `tests/test-transmissao-a-pedido.py` (**58 checagens**),
  `tests/test-agente-de-ordens.py`, `tests/test-gravacao-no-lado-terra.py` (**mediamtx + ffmpeg +
  ffprobe reais**: gravação com faixa h264 de ~3,5 s lida pelo ffprobe), `tests/e2e-transmissao-na-tela.py`
  (navegador real).

- **Fase 6 (provar sem regredir) — FEITO:** suíte completa `python -m unittest discover -s tests -p 'suite.py' -t .`
  → **`Ran 1 test in 518,464s` / OK / rc=0** (todo `tests/test-*.py` do projeto verde, radar e webcam inclusos);
  prova de tela em navegador real (`e2e-transmissao-na-tela.py`) → **23 checagens, rc=0**.

### Fechamento da rodada (17/11/2026, depois das provas)

- **Publicado:** repo `origin/main` = `574a284` (`git push origin main`, rc=0); nota do vault publicada.
- **Lado terra na VPS:** `scp` de `ground/{api,agente_de_ordens,gravacao,ingestao,radar_drq,radar_tcp}.py`,
  `app/{app.js,index.html}`, `fronts/vms.css`, `db/{schema-transmissao,schema-fase4}.sql` para
  `/opt/pipeline/app` (md5 conferido igual ao local) e `systemctl restart pipeline-api.service`.
  Conferido no ar: serviço **ativo**, `/api/saude` 200, tabelas `transmissoes`/`ordens_do_bordo`/
  `configs_do_cliente` criadas no banco da VPS, `GET /api/transmissao` → 401 (rota existe), tela `/app/`
  serve "Transmitir" e "Tempo de transmissão".
- **Agente contra o lado terra real, pela internet:** rodado neste PC apontando para
  `http://187.127.60.250:8085` → o lado terra respondeu **401 token de ingestão inválido** e o agente
  **avisou** (não inventou sucesso): o caminho bordo→terra está ligado ponta a ponta; falta só a máquina de
  captura do cliente, que traz o token dele.
- **Fase 1 (celular) — FEITO e provado:** a tela do cliente **não cabia** num telefone de 390 px (o navegador
  alargava a janela para 551–583 px: menu, barra de seleção e linha da câmera estouravam). Corrigido com um
  bloco `@media (max-width: 720px)` em `fronts/vms.css` (vale só em tela estreita; a tela larga não muda).
  Prova nova `tests/test-app-no-celular.py` (Chromium com janela de telefone e toque): **8 checagens, rc=0** —
  cabe na largura, alvo de dedo de 40 px, e o **toque** no iniciar manda o pedido ao bordo.
- **Fase 6 (documento de instalação) — FEITO:** `docs/instalacao-transmissao-a-pedido.md` — o que o cliente
  faz, o que instala na máquina de captura (o agente de ordens + variáveis), onde ficam as gravações, a regra
  de credencial e a tabela "como saber, na hora, que está funcionando".
- **Não feito de propósito:** *retenção/limpeza das gravações* (fase 5, P2) — o dono fixou que **nada é
  apagado** do histórico; apagar por tempo contraria isso. Fica para decisão dele.

### Defeitos REAIS que as provas pegaram (todos corrigidos na causa)

1. `_json` não retorna → um cliente **encerrava a sessão de outro**; agora `_transmissao_da_tela` devolve
   `(linha, erro, codigo)` e quem chama tem de checar o código.
2. A tela de tempo se redesenha a cada 5 s e **apagava a escolha do cliente** (gravava 900 em vez de 300);
   agora a escolha dele vence o redesenho.
3. Sem fluxo no ar o ffmpeg ficava **vivo e vazio** e a tela dizia "gravando"; agora é recusado com o motivo
   ("o fluxo X não mandou imagem nenhuma em 5 s").
4. Um `taskkill` no meio da gravação deixava **mp4 sem índice (imprestável)**; agora grava fragmentado e
   remonta o mp4 final ao parar.
5. GET `/api/gravacoes/<id>` estava dentro do `do_POST` → **download sempre 404**; movido para o `do_GET`.
6. As sessões "no ar" não traziam o estado da gravação (só o histórico trazia).

## O que NÃO vou fazer

- Não vou abrir porta na embarcação nem publicar RTSP na internet (regra que já vale no projeto).
- Não vou transformar a tela do cliente em app instalável obrigatório — o pedido é o contrário.
- Não vou mexer no que já está testado e funcionando (captura pela webcam, radar fases 3–6, 0.6.x, alvo por
  câmera, qualidade) sem prova de que não regrediu.
