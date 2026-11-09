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
