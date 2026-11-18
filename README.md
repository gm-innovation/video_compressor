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
Passo a passo em `INSTALAR-PC-DE-CAPTURA.md`: as câmeras entram pela tela **Enviar vídeo**, o
sistema comprime na máquina e o vídeo comprimido sobe para o lado terra (`destinoSrt`).

## Instaladores prontos (Windows x64) — PLUG & PLAY desde a 0.2.0
Na página de releases: https://github.com/gm-innovation/video_compressor/releases

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
