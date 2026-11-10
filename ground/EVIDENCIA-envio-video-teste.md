# Envio de vídeo para teste (arquivo ou link) — 09/11/2026

Prova de compressão e de streaming **antes de ter imagem real de embarcação**: o operador manda um
arquivo do computador ou cola um link http(s), o servidor codifica (libx264 → MPEG-TS → SRT no mediamtx)
e a tela mostra o que foi **medido**, não o que foi digitado.

## Onde fica na interface

| Superfície | Caminho | O que faz |
|---|---|---|
| Bancada (engenharia) | `/` | Painel "Enviar vídeo para testar" (aba arquivo / aba link) + tabela "Envios e medição de compressão" |
| Admin / operação | `/admin` → menu **Enviar vídeo** | O mesmo envio dentro do app instalado (`LECSOR Admin`) |
| Cliente | `/app` | O fluxo enviado aparece como câmera da embarcação demo e toca na grade |

Nenhuma credencial de câmera entra nesse caminho: a fonte é arquivo local ou link público; a chave de
análise (`X-Chave-Analytics`) não é usada aqui.

## Como o operador usa

1. Bancada (`/`) ou Admin → **Enviar vídeo**.
2. Aba **arquivo**: arrasta/escolhe o vídeo. Aba **link**: cola o endereço http(s).
3. Rótulo (aparece na tela do cliente), bitrate do encode (600 kbps … 5 Mbps), repetir em laço.
4. **Codificar e publicar** → aparece "no ar" e o fluxo entra na grade do cliente.
5. A tabela mostra: **entrada** (bitrate do vídeo), **saída** (o que o encode gera), **corte** (banda
   economizada; `↑` = a saída ficou maior que a entrada), **fps**, **tempo no ar**, **estado**.
6. **parar** encerra o encode; **remover** tira o fluxo da grade.

## Medições reais desta rodada (clipe `people-detection.mp4`, 768×432, 12 fps, **0,75 Mbps de entrada**)

| Alvo do encode | Bitrate de saída medido | Corte | fps entregue |
|---|---|---|---|
| **automático 400 kbps (metade da entrada)** | **444 kbps** | **↓ 41%** | 11,8 |
| automático 400 kbps, mantendo áudio 48 kbps | 446 kbps | ↓ 41% | 11,9 |
| 1,2 Mbps (alvo escolhido à mão, acima da entrada) | 1,65 Mbps | ↑ 119% | 12,0 |
| 2,5 Mbps (alvo à mão, acima da entrada) | 2,95 Mbps | ↑ 292% | 12,0 |

**Por que a saída ficou maior em parte das linhas antigas (dois erros meus, já corrigidos):**

1. **Alvo acima do material.** O clipe de teste já vem comprimido a 0,75 Mbps; pedir encode de 1,2 ou
   2,5 Mbps *gasta mais* do que o original. Agora o padrão da tela é **automático = metade da entrada**
   (ou 250 kbps de piso, 8 Mbps de teto) e a API avisa em texto quando o alvo escolhido é maior que a
   entrada.
2. **Áudio e contêiner entrando na conta.** O clipe tem faixa de áudio; o MPEG-TS reencodava em MP2 a
   ~224 kbps e o `-progress` do ffmpeg mede o **total do fluxo** (vídeo + áudio + TS). Por isso um alvo
   de 450 kbps aparecia como 889 kbps. Agora o padrão é **sem áudio** (o número medido é o do vídeo) e
   quem quiser mantém em **48 kbps mono**.

Contra fonte crua o corte é muito maior — é o caso da Fase 0-A: **746,5 Mbps crus → 5,51 Mbps (corte
99,26%)**. O teste aqui prova o caminho **arquivo/link → encode → SRT → navegador** e que a tela mostra
o número real.

## API (mesmo caminho que a tela usa)

| Método | Rota | Corpo |
|---|---|---|
| `GET` | `/api/ingestoes` | — (lista com medição viva) |
| `POST` | `/api/ingestao/arquivo?nome=&rotulo=&bitrate=&repetir=` | **bytes crus** do vídeo (sem multipart) |
| `POST` | `/api/ingestao/url` | `{"url":"https://…","rotulo":"…","bitrate":"1200k"}` |
| `POST` | `/api/ingestao/parar` | `{"id": 12, "remover": true}` |

Banco: `db/schema-ingestao.sql` → `ingestoes` (estado, bitrates, corte, fps, pid, log) e
`ingestoes_amostras` (histórico a cada ~10 s). Ao parar um envio que ficou ≥15 s no ar, o sistema
**grava sozinho uma medição** em `medicoes` (valor + fonte + data + hardware/versão + comando).

## Teste automatizado

`tests/e2e-envios.py` (Playwright, navegador de verdade) — 12 verificações, todas OK:

- envio por **arquivo** e por **link** aceitos pela tela;
- a tabela mostra entrada/saída/fps medidos (não digitados) e o envio aparece **no ar**;
- o fluxo enviado aparece na grade do **cliente** e o **vídeo toca** (`currentTime > 0,3`);
- detecção de IA com **9 s de idade não desenha caixa** (fim da marcação congelada) e o selo explica
  `✨ sem detecção nova há 9s (última: 1)`;
- nenhuma requisição do navegador contém `rtsp://`, `:8554`, `:8890`, `:9997`, `:8889`, `localhost`,
  `senha`, `password` ou `credencial`.

## Correções que o teste forçou

- **Caixa de IA congelada** (`pessoa 50%` presa na tela): leitura com mais de 3 s de idade não é
  desenhada; só o selo com a idade permanece (`fronts`/`app/app.js`).
- **API travando durante a ingestão**: cada quadro de progresso do ffmpeg escrevia no SQLite (dezenas
  por segundo) e a lista de envios perguntava processo por processo ao sistema. Agora grava no máximo
  1×/s, a checagem de processos é uma chamada única com cache curto e o banco está em **WAL**
  (`busy_timeout=30 s`). `GET /api/ingestoes` caiu para **1,28 s** com vários envios no ar.
- **UI da bancada**: página reescrita no tema VMS (cabeçalho, cartões, tabela de métricas, grade de
  vídeos com o mesmo player resiliente dos fronts) — antes era texto cru sem player funcionando.
- **Apps por papel**: operação e admin são a **mesma** área (o papel do login decide o que aparece),
  então o app duplicado `LECSOR Operacao` foi desinstalado; ficaram **LECSOR Cliente**, **LECSOR Admin**
  e **LECSOR Pipeline de Video** (bancada/engenharia), cada um com atalho no Menu Iniciar e na Área de
  Trabalho.

## As três etapas medidas separadamente (09/11/2026)

**Etapa 1 — compressão (arquivo inteiro, 30 fps travado).** Tela: Admin → Enviar vídeo → *Comprimir em arquivo*.
A API é `POST /api/ingestao/comprimir`; o arquivo comprimido fica em `ground/envios/comprimido/` e sai por
`GET /api/comprimido/<nome>` (download).

| Original | Comprimido | Corte | SSIM | Encode |
|---|---|---|---|---|
| `YTDown…Makito-X4-Decoder.mp4` — 28,19 MB, 1809 kbps, 1080p60 | 13,77 MB, 884 kbps, 1080p30 | ↓ 51,17% | 0,9569 | 11,65 s (10,7× o tempo real) |
| `clipe-do-dono.mp4` — 5,48 MB, 883 kbps, 768x432 | 2,88 MB, 464 kbps, 768x432, 30 fps | ↓ 47,46% | 0,9872 | 0,80 s (62× o tempo real) |

Download conferido byte a byte: o que a tela baixa é exatamente o que o registro diz (2.879.241 bytes).

**Etapa 2 — envio (SRT).** `GET /api/etapas/<fluxo>` lê o mediamtx: `cam-01` — RTT **0,0 ms** na bancada,
**1,652 Mbps** de média, 57 pacotes perdidos em 8.759 s (0,004%), 5 leitores. Numa bancada máquina-a-máquina
o trecho de rede não aparece; o número que vale é o da VPS/navio.

**Etapa 3 — descompressão.** `GET /api/etapas/<fluxo>?descompressao=1` abre o fluxo no navegador e mede o
primeiro quadro: WebRTC (WHEP) **2,296 s** (handshake ICE/DTLS), HLS **0,543 s**.

**Tudo em sequência — espera de ponta a ponta com relógio queimado no quadro.** Test pattern 720p30 a
800 kbps publicado em SRT; relógio local (ms) injetado na mesma tela do vídeo; leitura de duas capturas:
**0,308 s** e **0,255 s** (WebRTC, tudo na mesma máquina). O número anterior de 1,568 s incluía o caminho
da câmera analítica com o agente de IA junto.

> "No ar 300 s" na tela é **tempo no ar** (há quanto tempo o envio está publicado), não atraso. O atraso é
> o medido acima: ~0,3 s em WebRTC; em HLS ele soma o tamanho do segmento.

30 fps: o encode publica com `-r 30 -g 30` (menos que 30 fica ruim, 60 gasta banda sem ganho visível).

## Painel único do admin: comprimir → medir → publicar (09/11/2026, pedido do dono)

O dono pediu **uma estrutura só**, sem "alvo" e sem a coluna "no ar" sem sentido: queria saber
**em quanto tempo a compressão foi feita**, o **tamanho real de entrada e saída**, a **porcentagem de
compressão** e a **qualidade que sobra**. E o "alvo" passou a ser o que ele descreveu: **a maior
compressão possível sem perder qualidade**.

- **Um cartão, dois botões**: `1) Comprimir e medir` (arquivo do computador ou link) e
  `2) Publicar no ar (a última compressão)`. A tabela é a mesma para toda a operação.
- **Colunas**: `Entrada (original)` MB · kbps | `Saída (comprimido)` MB · kbps | `Compressão` % |
  `Tempo da compressão` s (e × o tempo real) | `Qualidade` SSIM | `fps` · CRF | `No ar` (tempo publicado
  + fps entregue + estado) | `Ações` (baixar · publicar/parar · remover).
- **Qualidade automática = busca de CRF**: amostra curta é codificada em CRF 26/28/30/32/34, mede-se o
  SSIM de cada uma contra a mesma amostra do original e escolhe-se **o CRF mais alto (menos banda) cuja
  qualidade fica dentro de 0,005 do melhor SSIM medido** — o ponto em que baixar mais a banda começaria a
  custar imagem. O preset do encode em arquivo é `medium` (o `ultrafast` é do ao vivo; para tamanho ele
  gasta banda à toa).
- **Medição (clipe do dono, 1080p60, pelo painel)**: 28,19 MB / 1809 kbps → **7,43 MB / 477 kbps**,
  **compressão ↓ 73,64%**, **qualidade 0,9733**, **tempo 22,8 s (5,46× o tempo real)**, CRF 34 escolhido
  pela busca. Clipe maior: 5,48 MB → 0,85 MB, ↓ 84,48%, SSIM 0,9834, 2,53 s, CRF 30.
- **Publicar no ar** continua do mesmo painel: cria o fluxo SRT e o cliente vê o vídeo comprimido
  tocando (conferido: `v-envio-ytdown-com-youtube-media-2xd0yog0kfo-s` 1920×1080 reproduzindo na grade).
- **SSIM**: a comparação agora roda **sem reescalar** e com o original normalizado para os mesmos fps do
  comprimido (antes o reescalonamento e a diferença de fase 60→30 fps achatavam o número).

## Piso travado pelo dono: ≥73% de compressão e qualidade ≥0,9733 (09/11/2026)

- `PISO_COMPRESSAO_PCT = 73.0` e `PISO_QUALIDADE_SSIM = 0.9733` em `ground/etapas.py`; a receita é
  codificar o **arquivo inteiro** e conferir os dois pisos (a amostra curta serve só de ponto de
  partida: no meio do vídeo ela mede 0,9885 e no começo 0,93 — nenhuma das duas representa a média).
- Se o arquivo inteiro não bate os dois pisos, o painel desce o CRF degrau a degrau (até 4 tentativas),
  fica com a primeira que passa e **apaga as outras**.
- Medição do clipe do dono (1080p60): CRF 36 → 78,11% / SSIM 0,9720 (reprova na qualidade); CRF 35 →
  75,97% / 0,9727 (reprova); **CRF 34 → 73,64% / SSIM 0,9733 → passa ✓**. Clipe menor: CRF 30 →
  84,48% / 0,9834 ✓.
- A linha da tabela ganha `✓` ou `✗ (abaixo do piso)`, o texto de progresso diz "PISO ✓ (≥73% e ≥0,9733)"
  e a legenda declara o piso. O banco guarda `passa_pisos`, `piso_comp` e `piso_ssim` por compressão.

## Margem nos pisos (09/11/2026, pedido do dono)

O dono mandou tratar 73% e 0,9733 como **mínimos com margem**: `0,9720` está a 0,0013 do nominal e não
justifica recusar uma compressão de 78,11%. Regra agora em `ground/etapas.py`:

- `PISO_COMPRESSAO_PCT = 73.0` — **piso firme** (banda é o que se quer economizar);
- `PISO_QUALIDADE_SSIM = 0.9733` com `MARGEM_QUALIDADE_SSIM = 0.002` → `PISO_QUALIDADE_ACEITO = 0.9713`;
- `passa_pisos(compressao_pct, ssim)` é o portão único usado pelo encode e pelos testes;
- medido: `passa_pisos(78.11, 0.9720)` → **passa** (antes reprovava e forçava o degrau CRF 36 → 34);
  `passa_pisos(60, 0.9713)` reprova (banda) e `passa_pisos(75, 0.9700)` reprova (qualidade).
- efeito prático: menos tentativas de encode (não desce mais um degrau por 0,0013 de SSIM) — o que também
  atende ao "não travar o envio das imagens".

## Tempo real: compressão, velocidade e banda, medidos pelo remetente (09/11/2026)

`GET /api/metricas` (só operação/admin) consolida o que está no ar AGORA. A fonte é o próprio ffmpeg que
envia: o `-progress` é lido pela ingestão e gravado 1×/s na linha da ingestão (`bitrate_saida_kbps`, `fps`,
`tamanho_mb`, `duracao_s`, `atualizado_em`). `atualizado_em` com menos de 6 s = envio vivo; mais que isso a
tela diz **sem sinal** (foi assim que o teste pegou um fluxo parado, em vez de mostrar número velho).

Exemplo real medido na bancada (clipe do dono publicado com `-c:v copy`, laço):

    entrada (original)  0,883 Mbps
    saida (na rede)     0,193 Mbps   compressao agora 78,14%
    banda economizada   0,691 Mbps   enviado 0,4 MB   fps 31,2

Observação honesta: a "compressão agora" (por trecho, medida na taxa do envio) difere da compressão do
arquivo inteiro (73,64% no mesmo material) porque o material tem trechos fáceis e difíceis; as duas colunas
existem para não confundir medição de arquivo com medição de streaming.

A tela **Tempo real** do admin (`button[data-tela='tempo']`) atualiza a cada 2 s e mostra, por fluxo e no
total: entrada, saída, compressão agora, banda economizada, taxa agora, total enviado, fps, perdidos,
espectadores e tempo no ar.

## Câmera: IP e porta (09/11/2026)

O formulário pedia cinco campos e não tinha o endereço. Agora pede o essencial: **rótulo**, **fluxo
publicado**, **IP** e **porta** (canal do gravador é opcional); o identificador é derivado do fluxo. O
endereço fica **só do lado da operação**: `GET /api/cameras` (o que o app do cliente consome) continua sem
IP, porta ou comando de captura; `GET /api/cameras/detalhe` (operação/admin) devolve `ip`, `porta`,
`protocolo`, `canal` e o comando de captura com a **senha como variável** (`rtsp://$USUARIO:$SENHA@ip:porta`),
nunca o valor. O teste `tests/e2e-envios.py` verifica os dois lados.

## Produção em cards, link ao vivo e histórico (09/11/2026)

O dono avisou: em produção é streaming contínuo, exibir envio por envio não se acompanha. Entrou a
tela **Produção** (`button[data-tela='producao']`), que agrupa **embarcação → câmera** e mostra, com
filtro de período (1/7/15/30/90 dias) e de embarcação:

    estado (enviando/parado) · média de compressão · banda utilizada · banda economizada
    horas de streaming · disponibilidade (%) · MB enviados no período

Medido na bancada: 14 cards, "0,36 h no ar", "agora: 1 enviando de 1 no ar".

### Onde cada número nasce
- **enviando/parado**: `ingestoes.estado` + `atualizado_em` (< 6 s = enviando), o mesmo critério do
  painel de tempo real.
- **histórico**: `ground/producao.py` fecha **minuto a minuto** o que foi medido (`telemetria_minuto`),
  agregando `ingestoes_amostras` (1 amostra/s). É idempotente (`UNIQUE(fluxo_id, minuto)`), roda no
  próprio `ground/api.py` a cada 60 s e tem **retenção** (`LECSOR_RETENCAO_DIAS`, padrão 30).
- **disponibilidade (%)**: minutos com medição / minutos da janela, por câmera. Com o histórico de
  hoje isso dá 0,002% (é honesto: 30 dias × 1 minuto no ar); cresce conforme o sistema roda.
- **banda utilizada/economizada**: MB × 8 / segundos no ar, contra o bitrate da **fonte original**
  (do registro de compressão quando o fluxo saiu de um arquivo comprimido, senão da linha de ingestão).

### Link e atraso, em tempo real
`GET /api/link` (só operação) e o painel Tempo real agora mostram:

    internet local (ping):   23 ms   (média de 4 pacotes; cai para tempo de conexão TCP se o ping for bloqueado)
    link (SRT, do mediamtx): RTT 0 ms · capacidade 0,33 Mbps · atraso do buffer 120 ms · perda 0%

O RTT e a capacidade de link são estimativas do **próprio SRT** (`msRTT`, `mbpsLinkCapacity`); o
atraso é o buffer de latência do SRT (`msSendTsbPdDelay`). A medição ponta a ponta (relógio queimado)
continua sendo rodada à mão (`etapas.latencia_ponta_a_ponta()`) e agora fica **registrada**
(`latencia_medicoes`) para aparecer junto com o buffer.

## Supabase (projeto novo) e GitHub — pronto para receber as credenciais

Sem ARROW e sem Dock Check, como o dono decidiu. O que já está escrito no repositório:

- `supabase/migrations/20261109140000_pipeline_telemetria.sql`: clientes, embarcações, perfis,
  câmeras, `telemetria_minuto`, `link_amostras`, views `v_producao_30d` e `v_disponibilidade_30d`,
  RLS por cliente (o papel `cliente` **não** lê `ip`/`porta` — sai pela view `v_cameras_cliente`),
  função de retenção e **Cron** horário (`cron.schedule`).
- `supabase/functions/telemetria-ingestao/index.ts`: Edge Function (Deno) que o servidor de bordo
  chama com o token da embarcação; a chave de serviço fica só no ambiente da função.
- `ground/publicar_telemetria.py`: envia o histórico fechado para a Edge Function. Dry-run verificado
  na bancada (`--simular`): 270 minutos de histórico montados com o link e o ping dentro.
- GitHub: o repo está em `master` com 31 commits e **sem remote**; falta criar o repositório e apontar
  o remote quando o dono passar os dados.

## Correção dos cards de produção (09/11/2026, achado do dono)

O dono apontou dois números mentirosos no card (`comp-11`, "Banda economizada 0 Mbps",
"Disponibilidade 0,146%"):

1. **Banda economizada saía 0** mesmo com 77,23% de compressão. Causa: o card lia a entrada na
   **linha de ingestão**, que para um arquivo já comprimido publicado é o próprio comprimido
   (137 kbps) — menor que a saída (201 kbps) → economia zero. Agora a entrada vem do **minuto
   fechado** (`entrada_kbps`), que o rollup já corrige pelo registro da compressão: medido
   `comp-11` entrada 0,883 → saída 0,201 = **0,682 Mbps economizados**.
2. **Disponibilidade dividia por 30 dias cheios** mesmo com o sistema rodando desde hoje
   (0,146%). Agora o denominador é a **janela efetiva**: do primeiro minuto de histórico até agora,
   cortada pelo período pedido. Medido: janela de **228 min** (desde 2026-11-09 10:30) →
   `comp-11` **62,72% (143 de 228 min)**, `comp-10` 0,88% (2 de 228 min). O card mostra a conta
   ("143 de 228 min") e o resumo explica que a janela não é de 30 dias cheios.

Erro de base encontrado no caminho: `strftime('%Y-%m-%dT%H:%M', a.em)` no SQLite **converte o
horário com fuso para UTC**, empurrando os minutos 3 h para frente e estourando a janela; trocado por
`substr(a.em, 1, 16)`, que preserva o horário local.

O servidor de API precisa ser **reiniciado** depois de mexer em `ground/producao.py` (o módulo é
importado uma vez), senão o painel continua mostrando os números antigos com o código novo na tela.

## Testar compressão e streaming SEM câmera de embarcação (09/11/2026)

O dono pediu para testar o caminho inteiro sem câmera conectada. Entraram duas fontes novas no
painel **Enviar vídeo** → "De onde vem o vídeo":

- **webcam do notebook (ao vivo)** — `dshow` do Windows; `GET /api/dispositivos` lista o que o
  ffmpeg enxerga (nesta bancada: `ACER HD User Facing` + `Microphone Array (AMD Audio Device)`);
- **teste sintético** — `testsrc2` a 1080p30, sem hardware nenhum.

As duas passam pelo **mesmo caminho do produto**: captura de N segundos → compressão com medição
(corte e SSIM) → publicação em SRT. `POST /api/ingestao/capturar` grava o clipe em
`ground/envios/originais/` e `POST /api/ingestao/comprimir` aceita `{"arquivo": "<clipe capturado>"}`.

Medido nesta bancada, pela tela, sem câmera de embarcação:

    webcam do notebook:  720p30 · captura 15,95 MB (12.812 kbps) → 0,57 MB · ↓ 96,44% · SSIM 0,9806 · CRF 30 · 0,94 s · PISO ✓
    fonte sintética:     1080p30 · captura 9,97 MB (19.941 kbps) → 1,53 MB · ↓ 84,62% · SSIM 0,9879 · PISO ✓
    publicado em SRT:    comp-13 no ar (MPEG-TS/HEVC-copy), métricas ao vivo em /api/metricas

Erro de base corrigido no caminho: `registrar_compressao()` montava o INSERT com **18 colunas e 17
valores** (`17 values for 18 columns`) e a exceção era engolida por um `try/except` — a compressão
media certo mas **não ia para o banco** (id vinha `None` e "publicar" respondia
"compressao nao encontrada"). Corrigido o placeholder que faltava.

## Envio CONTÍNUO de fonte viva, rótulo visível e filtros na Produção (09/11/2026)

O dono cortou o meio-caminho: "Comprimir e medir"/"Publicar no ar" **não valem para streaming** —
ele quer envio **contínuo, como na operação**, e a **imagem real** da webcam. Também cobrou: o
**rótulo** criado ao definir a fonte não aparecia em lugar nenhum, e a tela **Produção** precisava
de filtro por câmera e de "só as que estão enviando".

- `POST /api/ingestao/ao-vivo` (`ingestao.ao_vivo()`) liga o envio **sem duração determinada**: o
  ffmpeg lê a webcam (`-f dshow`) ou o gerador (`testsrc2`) e publica em SRT **até alguém parar** —
  sem `-re`, sem `-stream_loop`, sem `-t`. A fonte vai para o banco como `dshow:<dispositivo>`.
- No painel **Enviar vídeo**, escolhendo webcam/sintético o botão passa a ser **"Transmitir ao vivo
  (contínuo)"** (o campo de segundos desaparece e "Publicar no ar" sai da tela); a legenda diz que a
  imagem é a real da câmera e que o envio só para quando o dono mandar.
- `Produção` ganhou os filtros **Câmera** e **Mostrar (todas / só as que estão enviando)** e o resumo
  declara o filtro em vigor. Fonte que está enviando **agora** aparece como card mesmo sem minuto
  fechado (marcada "enviando agora (sem minuto fechado ainda)") — era por isso que o rótulo sumia.
- `tempo_real()` passou a informar o `tipo` da fonte (camera/sintetica/arquivo/url).

Medido agora, pela tela, com a webcam do notebook no ar de forma contínua:

    fluxo                vivo-webcam-bancada-ao-vivo · rótulo "Webcam bancada (ao vivo)" · dshow:ACER HD User Facing
    envio contínuo       30,1 fps · 1,594 Mbps · 12,37 MB enviados · sem duração determinada
    imagem que CHEGA     YAVG 141,9 · YMIN 23 · YMAX 248 (tela preta daria YAVG ~16) — imagem real, não preta
    Produção (só enviando) 1 card: embarcação PSV Exemplo (demo) · câmera "Webcam bancada (ao vivo)" · 3,36% (12 de 357 min)
    app do cliente       janela "Webcam bancada (ao vivo)" tocando a imagem real da sala

## Aviso de erro e "webcam ocupada" — o envio do dono não carregava em silêncio (09/11/2026)

O relato: *"apenas a que você inseriu está aparecendo, mas está vinculada ao plsv, não à bancada de testes,
ou seja, a que eu inseri não está carregando… mas deveria aparecer algum aviso de erro ou algo assim"*.

Causa: a webcam do Windows (dshow) **só abre uma vez**. O envio do dono começou enquanto o da bancada
ainda segurava o dispositivo; o `ffmpeg` falhou com `Error during demuxing: I/O error` / `Output file is
empty, nothing was encoded` e **saiu com código 0** — então o fluxo ficava com estado `fim` e **sem motivo**,
e a tela só pintava um quadro preto, sem dizer nada.

O que mudou:
1. **Recusa com recado**: `ao_vivo()` confere se a mesma webcam já está num envio vivo (instância viva =
   `atualizado_em` com menos de 12 s) e devolve **422** com o nome do fluxo que a está usando, em vez de
   deixar o segundo envio nascer e morrer preto.
2. **Erro com motivo**: `_motivo_da_falha()` lê o log e o próprio registro (nenhum kbps medido = nenhum
   quadro saiu) e marca `estado='erro'` com uma frase curta, mesmo quando o ffmpeg sai com código 0.
3. **Aviso na tela**: a grade do cliente e o Tempo real mostram `⚠ <motivo>` na janela, em vez de silêncio;
   `GET /api/cameras` passou a devolver `motivo`, e o Tempo real lista por 10 min o envio que **falhou**.
4. **Bancada de testes**: fonte viva de teste é registrada na **"Bancada de testes (propria)"** (não no
   "PSV Exemplo (demo)"); o card da Produção segue a embarcação **atual** da câmera, não a do histórico.

Medido: 2º envio da mesma webcam → `422 a webcam "ACER HD User Facing" ja esta em uso pelo fluxo
"Webcam bancada (ao vivo)" (id 143). Pare esse envio antes de transmitir de novo.`; fonte que não abre →
`estado='erro'` com motivo; card vivo → `Bancada de testes (propria)` / `enviando` / 1,596 Mbps.
Suíte `e2e-envios` verde com os 4 checks novos (bloco 11 = 87 verificações, todas ok).

## Entrada, compressão e banda economizada de uma fonte CRUA (09/11/2026)

O dono perguntou: *"onde estão as informações de entrada, compressão e banda economizada?"* — na tela Tempo
real, o fluxo vivo mostrava **Entrada 0 Mbps**, **Compressão agora —** e **Banda economizada 0 Mbps**.

Causa: a entrada só era lida do registro de compressão (arquivo) ou da linha de ingestão. Um **arquivo**
tem bitrate medido; uma **webcam (dshow)/`testsrc2` não tem** — a captura é crua, sem fluxo comprimido de
entrada — então `entrada = 0`, e sem entrada não há compressão nem economia para calcular. Além disso a
resolução do fluxo vivo era gravada como **o nome do dispositivo** no lugar de "1280x720".

O que mudou (módulo novo `ground/entrada.py`):
1. **`entrada_teorica_kbps(resolucao, fps)`** — a banda bruta equivalente da fonte crua pela regra do
   projeto: `W x H x fps x 12 bits/pixel / 1000` (4:2:0 8 bits; 1080p30 = 746,5 Mbps; 720p30 = 331,8 Mbps).
2. **A resolução real é sondada** depois que a fonte publica (`ffprobe` no caminho do mediamtx): a linha
   passou a guardar `1280x720@30` em vez de `ACER HD User Facing`.
3. **Entrada medida tem prioridade**: quando existe medição (arquivo comprimido, câmera H.264), vale a
   medição; o bruto só entra quando não existe fonte comprimida.
4. **A tela diz de onde veio cada número** — coluna Entrada com "(bruto)" e o rótulo
   `bruto teorico 1280x720@30 (4:2:0 8 bits)` / `medida na fonte`, para ninguém ler 331 Mbps como banda
   que passou no link.
5. **O histórico (`fechar_minutos`) usa a mesma regra**, e os 45 minutos fechados antes desta correção
   foram recompletados com a entrada do próprio fluxo.

Medido agora (fluxo `vivo-webcam-bancada-ao-vivo`): entrada **331,776 Mbps (bruto 1280x720@30)** → saída
**1,609 Mbps** = **99,52%** de compressão · banda economizada **330,167 Mbps** · 4,9 MB enviados ·
0 perdidos · 30 fps. Card da Produção: "Banda economizada 330,178 Mbps (entrada 331,776 Mbps, bruto
teórico da captura)".

**O que este número é e o que não é:** é o bruto da captura, não banda que trafegou. Numa câmera de bordo
que já entrega H.264 (RTSP do DVR), a entrada será o bitrate medido do próprio stream (ex.: 4 Mbps) e a
economia será a do re-encode — que é o número do produto, comparável ao alvo de ≥73% de corte.

## TESTE REAL ponta-a-ponta: bancada → VPS → app do cliente (09/11/2026, 20:32–20:39 UTC)

Pedido do dono: *"precisamos fazer um teste real com o vídeo comprimido indo pra vps, sendo descomprimido,
ou sendo enviado para o app do cliente e sendo descomprimido pelo player local"* — agora **tudo no lado
terra roda na VPS** (`187.127.60.250`), não mais na bancada.

### O que ficou de pé na VPS (durável: sobe sozinho)

| Peça | Como roda | Porta |
|---|---|---|
| mediamtx (recebe SRT, publica WebRTC/HLS) | container `mediamtx`, `--restart always`, config em `/opt/pipeline/conf/mediamtx.yml` | SRT 8890/udp, WebRTC 8889/tcp + ICE 8189/udp, HLS 8888/tcp, API 9997 |
| API + fronts do produto (`/app`, `/admin`) | systemd `pipeline-api` (`enable --now`), `LECSOR_BIND=0.0.0.0`, `Restart=always` | 8085 |
| fonte de vídeo da própria VPS (relógio queimado) | systemd `pipeline-fonte-vps` (ffmpeg testsrc2 720p30 + drawtext) publicando em `srt://127.0.0.1:8890` | — |
| ffmpeg/ffprobe | apt (6.1.1) | — |

O código foi copiado para `/opt/pipeline/app` (73 MB) e a API ganhou `LECSOR_BIND` porque antes ela só
escutava em `127.0.0.1` (o navegador do cliente não alcançava).

### Medições reais (não calculadas)

- **O fluxo atravessou a internet:** a bancada publicou a webcam comprimida (H.264, 720p30) em
  `srt://187.127.60.250:8890?streamid=publish:vps-webcam-bancada`; o mediamtx da VPS mostrou o caminho
  `ready`, `tracks: [H264]`, `bytesReceived` crescendo.
- **Banda real no link (medida na VPS, `/proc/net/dev`, 10 s):** `eth0` recebendo **1,725 Mbps** — que é o
  vídeo comprimido (≈1,59 Mbps) mais o overhead do SRT/MPEG-TS. **Esse** é o número honesto de banda
  consumida, não o bruto teórico de 331,8 Mbps.
- **O app do cliente decodificou:** abrindo `http://187.127.60.250:8085/app` com o player (Chrome, H.264),
  as janelas ficaram `videoWidth 1280 x 720` com `currentTime` avançando (12,13 s) e `paused: false` para
  `vps-webcam-bancada` (a webcam daqui, vinda pela VPS) e `vps-sintetica` (fonte da VPS).
- **Atraso ponta-a-ponta (leitura do relógio queimado):** o quadro da fonte da VPS marcava `17:39:00` no
  instante da captura às `17:39:00,36–0,42` locais → **abaixo de 1 s** (o relógio queimado tem passo de 1 s,
  então é uma medida grosseira).
- **Caminhos sem fonte mostram aviso**: as câmeras de demonstração (`cam-01`, `cam-02`, `cam-conves`) deram
  `502` no `/whep` porque não têm fluxo na VPS e a tela escreveu "⚠ nenhum envio registrado para esta
  câmera" — o aviso de erro funcionando no lado terra.

### O que ainda NÃO está pronto

- A **captura/encode da webcam roda nesta bancada** (a câmera é física aqui) — o processo de envio morre se
  esta máquina desligar; a VPS segue no ar com a fonte sintética própria.
- **Falta** a coluna "banda no link" na tela (medição da VPS por minuto) e o atraso ponta-a-ponta medido
  com relógio de precisão (ms), não de 1 s.

## A compressão funcionou? Quanto e com que qualidade (09/11/2026, 18:2x)

Pergunta do dono: *"a compressão funcionou? quanto comprimiu e qual a qualidade?"*

- **No ar agora:** `vps-webcam-bancada` recebendo na VPS **1,508 Mbps** (medido por delta do
  `inboundBytes` do mediamtx em 10 s) — não é estimativa, é o que atravessou o link.
- **Mesmo ajuste do fluxo vivo** (`libx264`, `-b:v 1500k`, 30 fps, yuv420p) aplicado a um clipe real de
  webcam desta bancada (`captura-webcam-do-notebook-ao-vivo-160137.mp4`, 720p30, 10 s):
  **15,95 MB / 12.759 kbps → 1,88 MB / 1.503 kbps = 88,22% menos bytes**, com
  **SSIM All 0,9859** (Y 0,9853 · U 0,9885 · V 0,9856) — acima do piso nominal 0,9733 e da margem 0,9713.
- Ou seja: **sim, comprimiu, e a qualidade medida ficou acima do piso do dono.**
- Comando do SSIM: `ffmpeg -i <comprimido> -i <original> -lavfi ssim=stats_file=- -f null -`.

**Atenção ao número:** o "bruto teórico" de 331,8 Mbps é o equivalente do sensor cru (720p30 4:2:0) e não é
o que a câmera gera — o que a webcam realmente escreve é ~12,8 Mbps. Contra ESSE valor, a compressão real
do fluxo vivo é **≈88%** (12,8 → 1,5 Mbps), que é o número comparável ao piso de 73% fixado pelo dono.

## Prova de que o video sai da bancada e chega na VPS (10/11/2026, 09:38-09:44 UTC)

Teste de "desligar a fonte": com o app do cliente tocando o fluxo, o envio da bancada foi derrubado e a VPS mediu o efeito.

| momento | conexao SRT na VPS | recebido na VPS | enviado ao player | app do cliente |
|---|---|---|---|---|
| com o envio ligado | `publish vps-webcam-bancada` de **189.1.136.122** (IP publico desta bancada), RTT 29,4 ms | **1,494 Mbps** | **2,988 Mbps** em 2 sessoes WebRTC | `videoWidth 1280`, tocando |
| 15 s depois de matar o ffmpeg da bancada | **nenhuma** | **0** | **0**, zero leitores | **todos os videos w=0 e pausados** |
| 35 s depois de religar o envio | de **189.1.136.122:53280**, RTT 23,1 ms, perda 0 | **1,513 Mbps** | — | apos recarregar: **1280, currentTime 23,1 s, tocando** |

Linha de comando do ffmpeg que publica nesta bancada:
`srt://187.127.60.250:8890?mode=caller&latency=200&pkt_size=1316&streamid=publish:vps-webcam-bancada` (dshow `video=ACER HD User Facing`, `-video_size 1280x720`, libx264 `-b:v 1500k`).

Contabilidade cruzada: 189.632.100 bytes recebidos na VPS (~189,6 MB) contra 184,1 MB contados pelo ffmpeg na bancada na mesma janela — diferenca compativel com o overhead de MPEG-TS/SRT.

## Qualidade do video: agora medida, no cartao de Producao e no Tempo real (10/11/2026, 09:45-09:58 UTC)

O dono cobrou: "nao vejo no card de producao nem em tempo real qual a qualidade do video". Antes o SSIM
so existia para clipe comprimido (`compressoes`): fluxo vivo nao tinha numero nenhum.

**Como a medida passou a ser feita** (`ground/qualidade.py`): o SSIM precisa do original e do comprimido
lado a lado, e a webcam (dshow) so abre UMA vez — entao a medicao abre a fonte uma vez e divide os
quadros com o filtro `split`:

- ramo A: o MESMO ajuste que vai para a rede (`libx264 -b:v <ajuste>`);
- ramo B: o original reconstruido SEM PERDA (`libx264 -qp 0`).

Depois mede o SSIM entre B e A. Roda com a fonte livre (antes de publicar, dentro do `ao_vivo`, ou pelo
botao "medir agora"); o resultado fica em `medicoes_qualidade` com hora e ajuste, e as telas mostram o
numero com a idade ("medida 2 min atras") porque SSIM sem data nao diz se ainda vale.

**Achado que muda o ajuste do fluxo vivo na bancada** (webcam ACER 1280x720@30, amostras de 8 s):

| ajuste | SSIM medido | compressao vs original sem perda | piso aceito 0,9713 |
|---|---|---|---|
| 1500k | 0,9577 - 0,9719 | 98,0 - 98,4% | **falha** |
| 2000k | 0,9612 | 97,8% | falha |
| 2500k | 0,9704 | 97,0% | falha (quase) |
| **3000k** | **0,9739** | **96,4%** | **passa** |

O fluxo vivo da bancada passou a publicar em **3000k** (antes 1500k, abaixo do piso do dono). Medido na
VPS depois da troca: recebendo **3,0-3,1 Mbps**, com SSIM **0,9739** e compressao de **96,4%** contra o
original sem perda (99,06% contra o bruto equivalente da captura).

Provas de tela (janelas reais, via CDP): no Tempo real a coluna "Qualidade do video (SSIM)" mostra
`0,9739 (piso 0,9713) - medida 2 min atras - ajuste 3000k` e um botao "medir agora"; no cartao de
Producao a linha "Qualidade do video (SSIM)" mostra o mesmo numero; o resumo das duas telas traz
"qualidade minima (SSIM): 0,9739".
