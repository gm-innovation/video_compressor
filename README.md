# Pipeline de vídeo bordo→terra — Lecsor Technology

Repositório base do pipeline (ver planos 1, 2 e 3 do projeto). Fase 0-A executada e
o caminho completo **bordo → terra → tela** rodando na bancada com vídeo próprio.

## Estrutura
- `bench/`  — scripts de medição (corte de banda, VMAF, latência, benchmark de encode)
- `board/`  — agente de bordo: codifica N câmeras, publica em SRT, watchdog e telemetria
- `ground/` — lado terra: mediamtx (SRT → WebRTC/HLS/RTSP) + API/banco do acompanhamento
- `portal/` — front do operador (fluxos ao vivo por WebRTC/WHEP) + módulo de acompanhamento
- `db/`     — schema/migrations e o banco local da bancada (SQLite)
- `tests/`  — testes automatizados
- `tools/`  — binários de bancada (mediamtx v1.21.3 windows_amd64)

## PC de captura (câmeras ligadas direto no computador)

**O PC de captura é autônomo** (dono, 23/11/2026): instala o app, **digita a chave de licença e pronto** —
não há login nessa máquina. Dali em diante, sozinho, ele varre as câmeras locais, cadastra e publica o
cadastro no lado terra, olha as flags do lado terra e obedece (liga/desliga câmera, aplica o alvo, manda a
saúde). A tela do app nessa máquina é o **Painel do Bordo** (`/bordo`, servido pelo próprio bordo, sem
login), que só informa: embarcação/empresa da chave, situação da licença, token do instalador
(presente/ausente), lado terra, agente de ordens no ar, o que está no ar, a última varredura/publicação e a
saúde do bordo. **Quem configura é o admin e quem assiste é o cliente — no lado terra, pelo navegador.**
Passo a passo em `INSTALAR-PC-DE-CAPTURA.md`: as câmeras entram pela tela **Enviar vídeo**, o sistema
comprime na máquina e o vídeo comprimido sobe para o lado terra (`destinoSrt`).

## Instaladores prontos (Windows x64) — PLUG & PLAY desde a 0.2.0
Na página de releases: https://github.com/gm-innovation/video_compressor/releases

### 0.11.0 — **o PC de captura ficou autônomo: chave, painel do bordo e mais nada** (dono, 23/11/2026)
- **O que o dono relatou:** *"inseri a chave de acesso no app no computador de captura, depois me pede email e
  senha, mas não aceita nenhum que já tenho. após o reconhecimento da licença não deveria precisar fazer mais
  nada no app de captura, ele já deveria fazer a varredura e enviar as informações"* e *"no pc de captura
  ninguém precisa abrir nada, tudo deve ser feito no admin e cliente, o app de captura deve ser autônomo"*.
- **O defeito:** ativada a chave, o app ainda abria a **tela de login** (a mesma do lado terra) e o login do
  servidor local daquela máquina só aceita quem está no cadastro **dela** — vinha *"esta conta nao esta
  cadastrada nesta instalacao"*, que é o "não aceita nenhum que já tenho".
- **Agora:** com a chave digitada, a entrada do app é o **Painel do Bordo** (`/bordo`, servido pelo próprio
  bordo, **sem login**): embarcação/empresa da chave, situação da licença, **token do instalador
  presente/ausente**, lado terra, **agente de ordens no ar** (com a última batida), o que está no ar por ordem
  do cliente/admin, a **última varredura** (o que viu, cadastrou, publicou e o que falhou) e a **saúde do
  bordo**. Nada de segredo: a chave só nos últimos 4 dígitos, o token só como presente/ausente.
- **Publica sozinho:** a varredura local roda no boot e de tempo em tempo, o cadastro é publicado ao lado terra
  com reenvio enquanto falhar, e a própria tela da chave pede a varredura e vai para o painel — sem ninguém
  clicar em nada. O pacote de captura passa a subir junto com o Windows.
- **O agente de ordens espera a chave em vez de morrer** (a embarcação vem da licença; o token continua vindo
  no instalador). A varredura sem sessão vale **só** para a própria máquina (loopback + o app declarando a
  captura + licença): de fora nada mudou e o cliente continua sem poder varrer.
- **Provas:** `tests/test-bordo-sem-login-e-autonomo.py` (novo), `tests/e2e-app-ativado-por-licenca.py`,
  `tests/e2e-varredura-do-bordo.py`, `tests/test-config-endereco.py`, `tests/test-app-unico-por-papel.py`,
  `tests/test_captura_liberada_no_app.py`, `tests/test-instalador-plug-and-play.py`,
  `tests/test-agente-de-ordens.py` e `tools/regressao-0100.py` (20 provas).

### 0.10.1 — **os consertos que os testes de ponta a ponta acharam dentro do produto** (23/11/2026)
- **O alvo de banda que o admin publica chegava ao ffmpeg com a unidade errada:** o campo `alvo` é o valor cru
  do `-b:v` e a convenção do produto é `NNNNk` (milhares de bits) — o admin publicava `800` e o ffmpeg lia
  **800 bits/s** (0,0 Mbps, 0 quadro), ou seja a câmera não subia. Agora o valor publicado carrega o `k` e a
  validação aceita `800` ou `800k` (os testes antigos exigiam `"800"` e deixavam o defeito passar: foram
  atualizados).
- **A licença revogada não cortava sozinha:** o agente de ordens só conferia a licença quando alguém abria a
  tela no barco, e a memória do agente dizia que a câmera estava no ar. Agora o agente confere a licença
  **antes** de ler a flag, o "está ligado?" é respondido pelo **estado gravado** (não pela memória) e a única
  porta que liga câmera (`ligar_camera`) respeita `licenca_bloqueia_captura()` — o pedido do cliente não
  desfaz o que a licença proibiu. **Medido: a transmissão morre em 2,3 s**, sem ninguém abrir tela no barco.
- **A auditoria do corte passou a ser escrita na transição:** antes ela repetia a mesma linha
  `captura_parada_por_licenca` 8 vezes em ~40 s.
- **Provas:** `python tools/smoke/ponta-a-ponta.py --jornadas 7,8,9,10` → `SMOKE: 4/4 OK` (J7 3,9 s · J8 73,4 s
  · J9 195,7 s · J10 58,7 s), `tools/regressao-smoke.py --completo` (J1 a J10), `tests/test-licenca-do-bordo.py`
  e `tools/regressao-0100.py` (20 provas).

### 0.10.0 — **a chave de licença: instalar o app no PC de captura e digitar a chave** (dono, 19/11/2026)
- **O que o dono pediu:** *"quero apenas instalar o app no computador de captura, inserir a chave da licença e
  assim fazer a conexão com a empresa e embarcação cadastradas, e a licença pode ser configurável por tempo ou
  indeterminado"*. Antes disso o PC ficava preso pelo `ambiente.json` copiado no build (um instalador por barco).
- **A chave:** `XXXX-XXXX-XXXX-XXXX` (Crockford base32, ~80 bits, **sem `I` nem `O`** para não confundir com
  `1`/`0`) — o formato vive num módulo só, `ground/licenca.py`. Ela **decide o barco**: ativando, a máquina
  passa a capturar as câmeras daquela embarcação e daquela empresa. O **token de ingestão continua único** e a
  licença vale para **uma embarcação** (dono, via `clarify`).
- **Quem gera é o admin** e ele **vê e copia a chave inteira sempre** (dono, via `clarify`): a chave é
  recuperável no banco (`db/schema-fase7.sql`), só o admin lê, e ela **nunca** entra em log nem na auditoria —
  a trilha guarda a **pegada** (sha256 curto). Revogar é **estado** (`status`), nunca `DELETE`; reemitir troca a
  chave na hora e zera a contagem de PCs.
- **Quantos PCs por licença é ajustável** (`maquinas_max`), com a lista de quais PCs usaram; licença pode ser
  **indeterminada** ou **até uma data**.
- **Sem internet o bordo mantém tudo normalmente** (dono, via `clarify`): nada de tolerância de dias nem corte
  por falta de rede. O corte é só **vencimento** ou **revogação** — e chega ao bordo porque **é o bordo que
  pergunta** (a arquitetura de comando de 19/11/2026: *"a única certeza é de que ele poderá enviar"*); ao
  perceber a revogação, ele **para a transmissão** das câmeras daquela máquina e diz o motivo na tela.
- **Telas:** no PC de captura o app abre a **tela da chave** (`GET /licenca`, servida pelo **próprio bordo**,
  abre sem internet); no painel, o menu **Licenças** gera, mostra/copia a chave de novo, muda prazo e nº de PCs,
  revoga, reativa e reemite — e **só o admin** vê isso (o operador recebe o aviso e nenhuma rota entrega chave).
- **Provas novas (4):** `tests/test-licenca-de-ativacao.py` (lado terra: gerar, ler/copiar, prazo,
  nº de PCs ajustável, vencida/revogada cortam, nada de chave em log/auditoria), `tests/test-licenca-do-bordo.py`
  (lado bordo: ativar, `licenca.embarcacao()` passa a valer na varredura/repasse, **sem rede nada para**,
  revogação para a transmissão), `tests/e2e-licenca-no-admin.py` e `tests/e2e-app-ativado-por-licenca.py`
  (as duas telas em Chromium). Regressão curada: `tools/regressao-0100.py`.

### 0.9.1 — **o aplicativo instalado abre** (correção que veio do campo)
- **Sintoma:** instalado em dois computadores, **nenhum** abria. **Causa medida no pacote:** em
  `desktop/servidor.js` a função que sobe o servidor local devolvia `hd` (a gravação contínua do radar) mas
  nascia **dentro** do `try` → `ReferenceError: hd is not defined` em toda chamada; como o único chamador é
  o arranque do aplicativo, nada depois dele rodava e a janela nunca abria. `node --check` não pega (escopo,
  não sintaxe) e a prova de tela de bancada não pegava porque nela o servidor local fica desligado.
- **Conserto:** `hd` nasce fora do `try`. **Prova nova:**
  `tests/test-app-sobe-o-servidor-local.py` chama `subir()` como o pacote chama e **reprova a versão com o
  defeito** (`hd is not defined`), então o defeito não volta sem o teste acusar.

### 0.9.0 — **os 4 escopos de cliente, o app de captura que se cadastra sozinho e a visão da Petrobras**
- **Os 4 tipos de cliente** (dono, 19/11/2026): (1) uma embarcação, (2) algumas, (3) a empresa inteira,
  (4) **Petrobras** — todas as embarcações de todas as empresas. Os tipos 1 e 2 são **vínculo explícito**
  (`usuario_embarcacoes`, concedido pelo admin, com trilha); o tipo 3 é o de sempre (sem vínculo = todas as da
  empresa); o tipo 4 é o papel **`observador`**: vê o **radar de óleo** de todo mundo e **nada mais** — sem
  câmera, sem analytics, sem botão.
- **O app de captura se cadastra sozinho** (Fase 2): no boot, e de tempo em tempo, o app **varre os
  dispositivos desta máquina** e cadastra o que achar — **sem endereço de câmera e sem credencial** passando
  pela tela. O id nasce do **seletor único** (`@device_pnp_…`), o que separa duas câmeras de mesmo nome; a
  **placa de radar (HDMI) não vira câmera** (radar é por embarcação). Terra **não manda lista**: o bordo
  descobre, cadastra e **publica**; terra só decide depois (`transmitir`, alvo, teto).
- **O cadastro do bordo não se perde** (Fase 3, defeito medido): `POST /api/cameras` na **própria máquina de
  captura** nasce **no banco do bordo** (com o dispositivo em `config_local`) e é publicado — a sessão do
  usuário de captura é atendida **no bordo** (`/api/entrar`, `/api/eu`, `/api/sair` são locais), sem o que a
  câmera ia só para terra.
- **Saúde do bordo** (0.8.0): o bordo envia CPU/memória/disco/dispositivos e **o resultado da varredura**
  (sem segredo); o admin vê semáforo e **bordo mudo = problema**, com retenção de 30 dias auditada.
- **Configuração do bordo** (0.8.0): terra **publica** (`config_bordo` com versão), o bordo **olha**,
  aplica só a diferença e confirma; `POST /api/config/aplicar` é **local**.
- Provas novas: `tests/test-escopos-de-acesso.py`, `tests/e2e-escopo-no-admin.py`,
  `tests/e2e-varredura-do-bordo.py`, `tests/test-fluxo-no-lado-terra.py`,
  `tests/e2e-observador-do-radar.py` — mais a regressão curada em `tools/regressao-090.py`.

### 0.7.0 — **terra publica o desejo, o PC de captura obedece; e o radar de óleo grava full time no HD do barco**
- Arquitetura (dono, 19/11/2026): o computador de captura a bordo **não tem porta aberta** — a informação
  **não sai de terra para o bordo**. **Terra publica o desejo** por câmera (com versão), o **bordo olha**
  (`GET /api/estado-desejado`) e age só na diferença, e o **bordo conta o real** (`POST /api/estado-real`).
- **Para quando não há ninguém assistindo** — e só então: fechou a tela / desligou o PC / caiu a conexão, o
  lado terra derruba **só a sessão de quem saiu**; com outro cliente assistindo, a transmissão continua.
- **HD do radar de óleo gravando full time** no PC de captura (imagens que chegam **por HDMI**, como
  qualquer câmera): blocos de **60 s** + `indice.sqlite`, **retenção = anel de disco** (sobrepõe o mais
  antigo e nunca para; trilha `bloco_sobreposto`). Nasce **desligada** — o admin liga com
  `LECSOR_GRAVACAO_CONTINUA=1` + `LECSOR_HD_DISPOSITIVO` + `LECSOR_HD_DIR`.
- **O cliente acessa as imagens quando quiser:** tela **Radar de óleo (HD)** com **filtro por data e hora**,
  **PEDIR** o trecho (o bordo lê o pedido e envia o bloco) e **BAIXAR** em terra.
- **Configuração só do administrador:** com o tempo de transmissão fixado pelo admin, a caixa sai da tela do
  cliente e `/api/transmissao/config` responde **403**.
- Provas: `tests/e2e-flag-de-estado-liga-a-camera.py`, `tests/e2e-dois-clientes-um-sai.py`,
  `tests/test-gravacao-continua-do-radar.py`, `tests/e2e-hd-do-radar-cliente-pede-trecho.py`,
  `tests/e2e-tela-do-radar-hd-do-cliente.py` (tela real).

### 0.6.10 — **as câmeras ficam em stand-by no PC de captura e só transmitem quando o cliente ativa**
- Arquitetura (dono, 19/11/2026): o sinal de cada câmera é **dividido por um split** e chega à nossa
  máquina de captura; o DVR grava por conta dele. O nosso sistema **não abre câmera em repouso**.
- **A captura nunca mais é pedida na máquina errada:** ligar/desligar é da máquina de captura; no lado
  terra o clique virou **ordem** (`iniciar`/`parar`) e o agente de ordens agora sobe junto com o servidor
  local (com reinício automático). Antes o clique era encaminhado ao lado terra, que tentava `-f dshow` no
  Linux e devolvia `codigo 234 / Unknown input format: 'dshow'` (`ingestoes` 186-191).
- **Stand-by de verdade:** em repouso nenhum ffmpeg roda e o dispositivo fica fechado. A tela do admin
  mostra por câmera **pronta (stand-by)** / **no ar** / **em uso** / **AUSENTE (cabo/USB fora do split)**.
- Provas: `tests/test-lado-terra-nao-captura.py`, `tests/test-stand-by-do-captura.py`,
  `tests/test-motivo-maquina-errada.py`.

### 0.6.9 — **a linha de cima da grade do cliente não é mais cortada**
- **`LECSOR-0.6.9-x64.exe`** — queixa: "na tela do cliente está cortando as câmeras de cima" (print de
  18/11/2026: na grade de 3 a moldura azul da primeira fileira aparecia sem o traço de cima).
- **Causa medida** (navegador real, 1920x1080, 6 câmeras, grade 3): o `padding` do palco era
  `0px 18px 8px` — **zero em cima** e 8 px embaixo — então a primeira fileira ficava com **0,4 px** de folga
  sob o cabeçalho e o `overflow:hidden` do palco comia **2,6 px** do contorno da janela selecionada
  (`outline:2px` + `outline-offset:1px` ocupam 3 px acima do topo da janela). Não era o vídeo: o `<video>`
  usa `object-fit:contain`.
- **Correção:** `.palco` com folga igual em cima e embaixo (`padding:12px 18px 8px`), o mesmo no telefone, e
  o motivo comentado no CSS para a folga não ser removida depois.
- **Prova nova:** `tests/test-grade-do-cliente-nao-corta-o-topo.py` mede `padding-top` do palco, folga da
  primeira fileira e contorno inteiro dentro do palco em 3 tamanhos de janela x grades 2x2/3x3/4x4 —
  **9/9 verde**; com o CSS antigo o mesmo teste acusa **36 falhas**.

### 0.6.8 — **o cadastro das câmeras chega ao lado terra e as telas mostram o que está no ar (com ou sem cadastro)**
- **`LECSOR-0.6.8-x64.exe`** — queixa: "cadastrei as câmeras com seleção de qualidade e tudo mais, está no
  ar, mas elas não aparecem na tela Tempo real, Produção e na transmissão ao vivo do cliente". Medido
  (18/11/2026): o lado terra recebia **três fluxos no ar sem cadastro** (`comp-1`, `vivo-cam1-11-18`,
  `vivo-cam2-11-18`), a Produção vinha **vazia** e o log do repasse dizia *"sem lado terra/token de ingestão"*.
- **Causa:** o servidor do PC de captura subia **sem** `LECSOR_TOKEN_INGESTAO`/`LECSOR_EMBARCACAO` — o Python
  lia o `ambiente.json` na raiz e o instalador grava em `ground/ambiente.json`. Sem token o anúncio do
  cadastro não saía, e em silêncio. Agora o **Python lê o ambiente nas duas posições**, sem sobrepor o que
  veio por variável de ambiente.
- **O build FALHA** se o pacote do PC de captura nascer sem ambiente (antes só avisava): pacote sem ambiente
  é pacote que não anuncia.
- **Anúncio visível:** `/api/saude` responde `anuncio` (tem token? tem lado terra? qual embarcação? último
  erro) e há `/api/publicacao` (ver e republicar) com o resultado **por câmera** — publicado/não e o motivo
  escrito; caixa "Lado terra" no Admin > Câmeras. **República no boot e continua tentando.**
- **"Tempo real" e "Produção" mostram o fluxo no ar mesmo sem cadastro**, marcado ⚠ **sem cadastro** em vez
  de sumir da tela; fluxo sem medida não derruba mais a tela (conta 0, não vazio).
- **O lado terra não encaminha mais para si mesmo** — "é esta máquina?" passa a olhar **IP e porta** (o
  `/admin/` do lado terra respondia 502 depois de ligar a leitura do ambiente no boot).
- **Provas:** `tests/test-anuncio-do-cadastro.py` **12/12**; `tests/test-fluxo-sem-cadastro-na-tela.py`
  **11/11**; `tests/test-ponte-do-lado-terra.py` **8/8**; `tests/e2e-envios.py` **72 ok / 0 falhas**.

### 0.6.7 — **a tela do app passa a ser servida pela própria máquina (é o que faz o Admin listar as câmeras)**
- **`LECSOR-0.6.7-x64.exe`** — queixa: "continua não listando as câmeras no app admin no computador de
  captura". Medido (18/11/2026): a câmera aparecia no `curl` do servidor local, a ponte do app entregava o
  endereço certo e o CORS estava certo — mas a página, vinda do lado terra (IP público), **não conseguia
  falar com `http://127.0.0.1:8765`**: o Chromium bloqueia pedido de página pública para loopback
  (`Failed to fetch`). Numa página servida pelo **próprio servidor local**, o mesmo pedido responde 200.
- **O servidor local serve a TELA e encaminha ao lado terra tudo o que não é captura** (páginas, css, login,
  cadastro, usuários, gravações) — caminho, método, cookies, corpo e status como vieram; download de vídeo
  não passa pela memória. `/api/eu` volta com `local: true` (botões de câmera liberados aqui). Se o servidor
  local não responder, as telas abrem no lado terra.
- **`tests/test-ponte-do-lado-terra.py`** (novo): lado terra falso + servidor local de verdade — **8/8 verde**.

### 0.6.6 — **o redesenho da tela não apaga mais o que o operador escolheu, e o teste do envio está verde**
- **`LECSOR-0.6.6-x64.exe`** — a tela do admin se repinta sozinha quando os dados mudam; ao repintar ela
  **recriava os campos do formulário de envio** e o arquivo já escolhido / o texto digitado se perdiam.
  Medido (18/11/2026): "Comprimir e medir" respondia *escolha o arquivo de vídeo* com o arquivo já escolhido,
  e a tabela de compressões da operação aparecia **sem as colunas**.
- **A tela de envio não é repintada enquanto você está preenchendo** (arquivo escolhido ou texto digitado);
  as listas seguem atualizando pelo timer delas e trocar de tela pelo menu continua funcionando.
- **Falha ao montar a tabela de compressões agora diz o motivo na tela**, em vez de deixar a área vazia.
- **`tests/e2e-envios.py` não depende mais da máquina**: sobe a própria bancada (`api.py --semear-demo`, banco
  temporário), o servidor de mídia local, e lê a senha de bancada de uma fonte só (`ground/.env.local`).
  Medido: **72 checagens ok, 0 falhas** (antes: 69 ok + 3 falhas na tabela de compressões).

### 0.6.5 — **a webcam não é arrancada do envio que já está no ar**
- **`LECSOR-0.6.5-x64.exe`** — dois defeitos achados ao destravar o teste de ponta a ponta (18/11/2026):
- **Segundo envio da MESMA webcam**: a limpeza de "câmera presa" rodava antes de perguntar se havia um
  envio **vivo** segurando a câmera — matava o ffmpeg do envio que estava no ar e aceitava o segundo, que
  ficava em quadro preto **sem avisar**. Agora a ordem é: envio vivo → **recusa com o recado** (*a webcam
  já está em uso pelo fluxo …*); só limpa processo preso de execução anterior quando não há envio vivo.
- **Formulário de envio**: o redesenho periódico da tela recriava o campo e o foco se perdia no meio da
  digitação (o rótulo digitado sumia). O foco e o cursor voltam para o mesmo campo depois do redesenho.

### 0.6.4 — **tela do admin limpa + a banda do vídeo ao vivo (1500 a 300 kbps)**
- **`LECSOR-0.6.4-x64.exe`** — pedido do dono (18/11/2026): o admin não tem "Transmissões pedidas pelos
  clientes" (é do canal do cliente; a **operação** mantém a dela, que cancela) nem os **testes de vídeo**
  da bancada ("Comprimir e medir", "Publicar no ar", "Qualidade por câmera").
- A tela do admin passa a ter: **Transmitir ao vivo** (câmera desta máquina / teste sintético / radar),
  o **No ar agora** (com "parar", para encerrar o envio contínuo), o **Teto do produto** e a trilha de
  **Gravações**.
- **Qualidade do ao vivo = banda**: lista fechada de **1500/1200/1000/800/500/300 kbps** (+ padrão da
  tela), escolhida na tela e **enviada na API** (`bitrate`); a caixa antiga de CRF fica só no caminho de
  arquivo/link (bancada), onde qualidade é compressão.
- **Câmera desta máquina**: a lista de dispositivos **tenta de novo** enquanto o servidor local sobe e,
  se não vier, **mostra o motivo**; o aplicativo **espera o servidor local responder antes de abrir as
  telas de captura** (o "Failed to fetch" e a caixa vazia silenciosa saíram).
- Provas: `tests/e2e-tela-limpa-do-admin.py` (navegadores de verdade: administrador × operação),
  `tests/test_captura_no_admin.py`, `tests/test-config-endereco.py` (seção 7).

### 0.6.3 — **o app se organiza pelo usuário: a entrada não vem mais de um servidor local vazio**
- **`LECSOR-0.6.3-x64.exe`** — corrige o relato de 18/11/2026: com a captura liberada nesta máquina, a
  tela de **entrada** era servida pelo servidor **local** (`127.0.0.1`), cujo banco não tem usuário
  nenhum → o login batia num banco vazio mesmo com a senha certa ("esta instalação ainda não tem usuário
  nenhum").
- Agora o app **mede** antes de abrir a janela: servidor local **sem** usuário e lado terra respondendo →
  a entrada vem do **lado terra** (onde estão as contas); bordo **sem internet** → segue no servidor
  local (primeiro acesso criado na própria máquina); servidor local **com** cadastro próprio → a entrada
  é a dele. A escolha aparece no relatório (`enderecoEntrada=...`).
- Provado no app de verdade (`tests/test_captura_liberada_no_app.py`: `base` e `enderecoEntrada` no lado
  terra, `enderecoCaptura` em `127.0.0.1`) e em 4 casos de `tests/test-config-endereco.py` (seção 6).

### 0.6.2 — **plug & play: o admin já nasce com tudo liberado**
- **`LECSOR-0.6.2-x64.exe`** — mesmo aplicativo único, sem etapa manual depois de instalar.
- O pacote nasce no papel `unico` **com o servidor local e as funções de captura ligados**; o item de
  menu virou *"Subir o servidor local nesta maquina (captura — as telas e o login continuam no lado
  terra)"* e **não troca mais o endereço da tela** (era ele que jogava o login no banco local vazio e
  devolvia "e-mail ou senha invalidos" com a senha certa).
- Config antigo (endereço em `127.0.0.1`, captura desligada) é **corrigido sozinho ao abrir**.
- Entrada numa instalação **sem usuário nenhum** diz o que falta e abre o cadastro do primeiro
  administrador, em vez de acusar a senha; a tela de erro distingue o servidor **local** do **lado
  terra** e informa qual é o lado terra desta instalação.
- Provas: `tests/test-entrada-instalacao-vazia.py` (novo), seção 5 do `tests/test-config-endereco.py`
  e `tests/test-instalador-plug-and-play.py` (105 checagens).

### 0.6.1 — **a transmissão ao vivo pela câmera do PC de captura funciona**
- **`LECSOR-0.6.1-x64.exe`** — mesmo aplicativo único da 0.6.0, com a captura corrigida.
- O defeito: o envio pedia `1920x1080` (o padrão) e a webcam do PC só aceita 1280x720/640x480/640x360 →
  o ffmpeg respondia `Could not set video options` e a tela dizia "a camera nao abriu". Agora o produto
  lê a lista **real** da câmera (`-list_options`) e pede o maior tamanho suportado que caiba no pedido;
  se a lista não vier, **não fixa** tamanho (o ffmpeg negocia) em vez de derrubar a captura.
- O **seletor PnP não era o culpado** — ele abre a câmera normalmente (o teste é que passava errado).
- Provado de ponta a ponta com a webcam real: `no_ar` em 1280x720 a 30 fps, 1596 kbps, o cliente exibindo
  o vídeo e a qualidade (SSIM 0,9803) publicada no lado terra. Regressão: `tests/test-camera-tamanho-suportado.py`.

### 0.6.0 — **UM aplicativo só** (a tela é a do papel do usuário)
- **`LECSOR-0.6.0-x64.exe`** — o aplicativo. Ele abre a tela de **entrada** (`/entrada`), entra e manda
  cada um para a **sua** tela: **cliente** → `/app`, **operação/administrador** → `/admin`, **técnico**
  → `/` ("Enviar vídeo"). O papel vem do servidor, não da interface.
- Quem captura é a **máquina**: menu *Servidor local → "Liberar as funções de captura nesta máquina (sem
  trocar de app)"*. O mesmo pacote serve para todas as máquinas.
- **Quem cadastra usuário é o administrador** (tela Usuários do console): não existe cadastro pelo
  próprio usuário — o login não cria conta nenhuma, e o Supabase do produto tem de estar com o cadastro
  público desligado (`python tools/conferir-signup.py` confere).
- Papéis: `cliente`, `operador`, `admin` e **`tecnico`** (bordo, só "Enviar vídeo"). A base do produto
  (bancada/VPS) atualiza sozinha no boot: a migração do papel `tecnico` roda na subida da API.

**Migração de quem já tem os pacotes antigos (0.2.x–0.5.0):** desinstale os quatro e instale este — o
aplicativo unico tem identidade própria e convive com os antigos. O **lado terra** (VPS/cliente) também
precisa desta versão, porque é ele que serve as telas.

### Pacotes antigos (linha 0.2.x–0.5.0, um por papel)
- `LECSOR-Captura-0.2.0-x64.exe` — **PC de captura**: nasce apontado para `127.0.0.1:8765`, com o
  servidor local ligado (sobe sozinho no boot) e repasse para o lado terra já configurado
- `LECSOR-Terra-0.2.0-x64.exe` — **lado terra**: apontado para o servidor (VPS ou local do cliente)
- `LECSOR-Cliente-0.2.0-x64.exe` / `LECSOR-Admin-0.2.0-x64.exe` — telas do cliente e admin/operação

A partir da **0.2.0** cada instalador leva **o pacote inteiro** dentro de `resources\`:
`ffmpeg/` (ffmpeg+ffprobe), `servidor/ground`, `servidor/admin`, `servidor/app`, `servidor/db`,
`servidor/board`, `servidor/analytics`, `servidor/tools/mediamtx/mediamtx.exe` e **Python portátil**
(`servidor/python/python.exe`). O servidor local sobe **dois** processos (`mediamtx` + `api`); a
análise local só entra se o Python tiver `numpy`/`onnxruntime` (o portátil não tem) e o app registra
no log a decisão. O banco local fica em `%APPDATA%\<nome>\pipeline.db` e o caminho é resolvido num
lugar só (`ground/ferramentas.py:caminho_banco()`, via `LECSOR_BANCO`); instalação limpa aplica todos
os `db/schema*.sql` (inclusive `schema-ingestao.sql`). Na máquina do cliente **não** se instala Python, não se copia
repositório e não se edita JSON: o papel de build (`desktop/papeis.json`) traz o `base`,
`destinoSrt` e `servidorLocal` de fábrica. Se o servidor local não subir, o app **diz o que falta**
em caixa de erro (antes a falha era silenciosa).

Quem builda roda `desktop/baixar-ffmpeg.sh` (download pelo Python, com SHA-256 conferido) e
`desktop/baixar-servidor.sh` (Python embeddable + mediamtx), que baixam para `tools/` — fora do git.

Cada instalador tem `productName` próprio (logo, `%APPDATA%\<nome do app>\config.json` próprio), e o
`papel` gravado no build vence um `config.json` herdado de outro papel ou das versões antigas.

Os `.exe` são construídos por `desktop/construir-instaladores.sh` e **não** entram no git
(`desktop/dist/` está no `.gitignore`): o pacote de download é a página de releases.

## Transmissão a pedido do cliente (e a gravação)
O **cliente** abre a transmissão pela web (computador ou telefone), **sem instalar nada**: `/app` →
*Transmitir* → *Iniciar transmissão*. A ordem nasce no **lado terra** e chega ao bordo pelo agente
(`ground/agente_de_ordens.py`), que **não abre porta nenhuma**. O vídeo gravado fica no **lado terra**
(`-c copy` do que já chegou) e a VPS **mantém só o arquivo gravado**: ao fim da gravação a tela **avisa
o cliente para baixar** e, quando ele **sai da tela ou desliga o sistema**, o arquivo é **apagado** — a
**trilha de auditoria nunca é apagada** (pedido, gravação, aviso, download e apagamento ficam com autor
e data). Passo a passo, diagnóstico e a parte da operação/admin: `docs/instalacao-transmissao-a-pedido.md`.

## Como rodar na bancada
```
# 1. lado terra (mediamtx): recebe SRT e publica WebRTC/HLS/RTSP
./ground/start-mediamtx.sh

# 2. agente de bordo: 2 câmeras sintéticas 720p30 publicando em SRT
python board/agent.py                    # perfil: board/perfis/bancada.json

# 3. portal + API + banco
python ground/api.py 8765                # http://127.0.0.1:8765/
```
Saída da medição de banda/VMAF: `bench/saida/resultado-fase0.json` e `medicoes.csv`.

## Smoke de ponta a ponta (bordo → terra → tela)

```bash
export LECSOR_SENHA_DEMO=...                    # senha dos usuários de demonstração do lado terra
python tools/regressao-smoke.py --rapido        # medidor + J1+J2 (~2 min) — antes de commitar
python tools/regressao-smoke.py                 # medidor + J1..J6 (o dia a dia) (~8 min)
python tools/regressao-smoke.py --completo      # medidor + J1..J10 (a bancada toda) (~12 min)
```

Cada jornada tem **ação de usuário em navegador real**, **comando real de mídia** (ffmpeg/SRT/mediamtx)
e **medida com número**; o relatório sai em `smoke/saida/<data>/`. Regra dura: **sem medida, a jornada
não é "OK"** — é "NÃO MEDIDA". Detalhes, vereditos e limites em [`docs/smoke.md`](docs/smoke.md).

Rodada de 23/11/2026 (bancada, fluxo `cam-01`): **`SMOKE: 6/6 OK`** (J1–J6) e **`SMOKE: 4/4 OK`**
(J7–J10, Fase 3 fechada em `main` = `64a9a0f`): os 4 escopos de cliente, o admin mandando e o bordo
obedecendo (**a banda cai de 3,187 para 0,773 Mbps** com o vídeo de pé), o **ffmpeg fora do bordo** virando
"problema" no painel em **1,0 s** e a **licença revogada cortando a transmissão em 2,3 s** — a bancada achou
**dois defeitos reais de produto** nessa fase (o formato do `alvo`, que o ffmpeg lia como **800 bits/s**, e a
revogação que **não cortava sozinha**; detalhes em [`docs/smoke.md`](docs/smoke.md)).
A rodada **completa** (J1–J10) nesta máquina dá **`9/10 OK`**: só a **J2** falha, medindo **26,4 fps**
(piso 27) com o host ocupado — **isolada, a J2 mede 30,0 fps**, então o que falta é máquina ociosa, não
produto (a J2 sob carga é um aviso de bancada; o número de campo é do PC de captura). Cada rodada escreve também `smoke/saida/<data>/qualidade.json` — os três
números do produto (fps, latência e redução de banda) com o comando, o commit e a máquina carimbados:
`--rapido` de 23/11/2026 = **30,0 fps · 0,201 s · 99,57 %** contra 746.496 kbps de bruto teórico (regra do
`ground/entrada.py`).
**J2**: 30,0 fps · 3,182 Mbps · latência 0,217 s · imagem 1920×1080 decodificada no cliente · arranque 15,3 s.
**J5** (gravação): **2.358.516 B em 7,0 s** de gravação, baixados iguais (**h264 1920×1080**, lido pelo
ffprobe), **o arquivo apagado 0,5 s depois de o cliente sair** e a linha + as 15 ações de auditoria
preservadas. **J6** (radar de óleo): o HD gravou sozinho → catálogo no terra → o cliente viu os trechos →
PEDIR 201 → **o bordo enviou** → o cliente baixou.

## Medições feitas na bancada (nada digitado à mão)

| medição | resultado | onde |
|---|---|---|
| corte de banda (x264 CRF23, 1080p30) | 5,51 Mbps · VMAF 94,87 · 9,5× tempo real | `bench/EVIDENCIA-fase0a.md` |
| fluxo ponta a ponta (agente → SRT → portal) | cam-01/cam-02 no ar, 0 reinícios, HLS 1280×720 30 fps | `ground/EVIDENCIA-fluxo-ponta-a-ponta.md` |
| latência ao vivo (RTSP, mesmo transporte do WebRTC) | **1,568 s** (2 amostras) | `ground/EVIDENCIA-latencia-ponta-a-ponta.md` |
| latência HLS (pull por segmento) | 2,596 a 3,087 s | idem |

Medição de latência: `python bench/medir-latencia.py <url> --n 300` carimba a chegada
de cada quadro e salva o quadro pedido em imagem; o relógio queimado no quadro é lido
nela e a conta fecha com `--calcular ... --postar` (grava no banco do sistema).

## Regras do projeto
1. Nenhum segredo no repositório — credencial só por variável de ambiente/cofre.
2. Toda medição grava valor, fonte, data, hardware/versão e comando.
3. Acesso a câmera só por dentro da VPN; porta RTSP nunca publicada na internet.
4. Todo socket do lado terra escuta em `127.0.0.1` (o servidor não expõe porta de vídeo).
