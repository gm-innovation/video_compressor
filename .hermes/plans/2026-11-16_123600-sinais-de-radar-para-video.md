# Sinais de radar → vídeo comprimido (bordo → terra) — plano

**Status:** decisões do dono incorporadas (16/11/2026): fonte plugável por embarcação; modos **PPI e quadro cru**, os dois; taxas **1 imagem por volta e 30 fps**, as duas; PPI **1.024×1.024**; roda onde a embarcação definir — **aprovado em 16/11/2026; Fases 1 e 2 implementadas e provadas**

## Pedido do dono (16/11/2026, verbatim)

"vamos receber também sinais de radar que teremos que enviar como vídeo, veja como fizemos a conversão com
a sessão \"SeaDarQ\" vamos receber os sinais diretamente do radar, mas precisamos também testar com arquivo
extraído do radar que são sinais, não vídeo, mas precisaremos converter para vídeo e comprimir, vou te
fornecer um arquivo de exemplo". Arquivo dado: `work/replicacao/seadarq/sim/fixtures/drq/20261106164423.drq`
(2,533,844,224 B = 2,36 GiB).

## O que já existe (medido, não suposto)

Medido hoje neste arquivo (sonda própria, leitura direta por deslocamento):

| Medida | Valor |
|---|---|
| Tamanho | 2.533.844.224 B = 2,36 GiB |
| Cabeçalho do arquivo | **1.024 B** (`+4 = 1`, `+128 = 3.539.456`, `+132 = 4096`) |
| Quadro | **2.240 B** (`tipo=3` em `+0`, `passo=2240` em `+4`) |
| Quantidade | **1.131.180 quadros**, resto **0** (1024 + N×2240 = tamanho) |
| Miolo | 2.048 B em `+192` = **1.024 amostras u16** (12 bits de amplitude + 4 de flag) |
| Tempo do quadro | **FILETIME** em `+24`/`+28` → de **2026-11-06 16:44:27.390 UTC** a **16:51:09.854 UTC** = **402 s** de gravação (~2.810 quadros/s, 0,355 ms/quadro) |
| Azimute | **por quadro**, em `+40` (graus inteiros) e `+44` (fino 0..4095, 4.096 passos/volta); avança ~1 passo/quadro no início e ~0,59 no quadro 1000 (taxa não constante) |

No clone do SeaDarQ (`work/replicacao/seadarq`) já existe: leitura **por índice** acima de 2 GiB
(`electron/drq-open.js`, IPC `drq:janela`), leitura do formato real (`src/drq.js` — `cabecalhoDoQuadro`,
`filetimeParaMs`, `indexarQuadros`), `src/framesplayer.js` (cursor por fonte), `PPI.draw` na tela e
**snapshot PNG do canvas** (`src/app.js:1622`). **Não existe** nenhum caminho de vídeo lá (busca por
`ffmpeg`/`mp4` no repositório: **zero**).

Na pipeline de vídeo (`lecsor-pipeline-video`) já existe: `tools/ffmpeg/ffmpeg.exe` no pacote, a tela
**"Enviar arquivo" / "Colar link"** (`portal/index.html`) que reencoda por ffmpeg com **alvo de bitrate por
câmera** (1500k/1200k/1000k/800k/500k/300k), publica por SRT no mediamtx e o lado terra descomprime e mostra.

**Não existe hoje:** conversão de sinal de radar para vídeo, em nenhum dos dois repositórios.

## Desenho proposto (a aprovar)

Um quadro do `.drq` **é um radial** (1.024 amostras) com azimute e hora próprios — é isso que permite virar
imagem: agrupar os quadros por **volta do azimute** e desenhar a **PPI** (imagem de radar) de cada volta.
A cadeia fica:

1. **Conectores de fonte** (um por tipo de infra): arquivo `.drq` (percorre por deslocamento, nunca carrega
   2,4 GiB) e sinal ao vivo do radar (TCP/RIU do cliente; azimute do próprio fluxo ou do NMEA). Todos
   entregam a MESMA saída: quadros (amostras 1.024 × u16 + azimute `+40`/`+44` + hora).
2. **Desenhador com dois modos** (por embarcação): **PPI** — monta a imagem da volta (centro no radar,
   raio = amostra, 12 bits de amplitude → cinza) — ou **quadro cru** (o radial como veio). Em ambos, duas
   taxas: **1 imagem por volta** ou **30 fps**. Saída em PNG (ou cru, se der para ir direto ao ffmpeg).
3. **Codificador**: `ffmpeg` (o do próprio produto) junta os PNGs em **H.264** no alvo escolhido pela tela
   de qualidade, 30 fps, mesmo ajuste do resto do produto (`veryfast -tune zerolatency -profile:v high`).
4. **Transporte**: o vídeo entra na cadeia que já funciona (SRT → mediamtx → lado terra), aparecendo como
   mais uma "câmera" na tela — sem caminho novo de rede.

**Ao vivo** (sinais direto do radar) o mesmo desenhador roda sem arquivo: recebe do radar e desenha, com o
ffmpeg lendo por `pipe`. O clone já tem um simulador de hardware (`simh`, RIU TCP 47001 + NMEA TCP 47002)
que pode servir de banco de provas antes do hardware real.

## Decisões do dono (16/11/2026) — valem para o desenho inteiro

- **A. Fonte: preparar para TODAS.** "cada embarcação pode ter a sua própria infra" — a entrada de sinal é
  **plugável e configurável por embarcação** (arquivo `.drq`, RIU/servidor TCP do radar, NMEA para o azimute,
  e o que cada cliente tiver). Nada de assumir uma fonte só: cada uma vira um **conector** com a mesma saída
  (amostras + azimute + hora), escolhido na configuração daquela embarcação.
- **B. Imagem: preparar para AMBAS.** "cada cliente pode definir, ambas também" — o desenhador tem **dois
  modos** (**PPI** = imagem de radar desenhada; **quadro cru** = o que o radar manda, sem desenho) e o cliente
  escolhe; os dois podem coexistir na mesma embarcação.
- **Taxa: as duas.** "1 imagem por volta e 30fps" — **uma imagem por volta** (mais leve) e **30 fps** (mais
  fluido) são opções; a escolha é por embarcação, como o modo de imagem.
- Consequência de projeto: fonte, modo de imagem e taxa são **três seleções por embarcação**, do mesmo jeito
  que o alvo de bitrate é por câmera — e o alvo de bitrate continua por fluxo, com os níveis já da 0.4.0.

## Fechado pelo dono (16/11/2026, segunda rodada)

- **Resolução da PPI: 1.024×1.024** — o número de amostras por radial (medido no arquivo: `+188 = 1024`).
- **Taxa padrão de fábrica: os DOIS** (1 imagem por volta e 30 fps), escolhidos por embarcação — mesma regra
  da fonte e do modo de imagem.
- **Onde roda:** aceita os dois (mesmo PC de captura ou máquina própria do radar), decidido por embarcação
  na configuração — é o que "cada embarcação pode ter a sua própria infra" exige.

## Fases (com prioridade)

- **Fase 1 — P0:** conector de **arquivo `.drq`** + desenhador nos **dois modos** (PPI e quadro cru) e nas
  **duas taxas** (1 imagem por volta / 30 fps), gravando PNG. Prova: abrir o arquivo do dono e sair 1 volta
  em PPI **e** em quadro cru, com azimute e hora do quadro impressos, nas duas taxas.
- **Fase 2 — P0:** PNG → mp4 com o ffmpeg do produto (alvo 1500k, 30 fps) e medição de tamanho/kbps; comparar
  com o que a tela de qualidade mostra.
- **Fase 3 — P1:** entrar na cadeia real (SRT → mediamtx → lado terra) como uma "câmera" do radar, com alvo
  de bitrate selecionável como as câmeras de vídeo.
- **Fase 4 — P1:** provar o Starlink/banda: quanto pesa 1 min de radar na PPI escolhida, em cada alvo.
- **Fase 5 — P2:** **conector ao vivo** (a infra de cada embarcação) + teste com o simulador do clone
  (`simh`: RIU TCP 47001 + NMEA TCP 47002) antes do hardware real.
- **Fase 6 — P2:** **seleção por embarcação** na tela: fonte, modo de imagem (PPI/cru, ambos) e taxa
  (por volta/30 fps), gravada na configuração daquela embarcação — como o alvo por câmera da 0.4.0.

## Estado por fase (17/11/2026) — fases 3 a 6

- **Fase 3 — FEITA E PROVADA.** `tests/test-radar-na-cadeia.py` (277 linhas, 29 verificações, exit 0):
  radar na MESMA cadeia da câmera (SRT → mediamtx → lado terra), `tracks: ['H264']`, caminho online por
  `srtConn`, **1.151 kbps medidos com alvo 1200k**; alvo obedecido; tamanho do quadro 1.048.576 B
  (1024×1024 cinza); cadência real PPI/30 fps ≈ 25–29 q/s; "por volta" = 1 imagem por volta; SSIM não é
  medido no radar (é SINAL, não vídeo) e o log diz isso em voz alta; parada limpa; pedido inválido recusado.
- **Fase 4 — TESTE ESCRITO E VERDE.** `tests/test-radar-banda-1-minuto.py` (140 linhas, exit 0): 1 min de
  radar cru (PPI 1024×1024 cinza @30 fps) pesa **251,7 Mbps** na fonte; codificado com o ajuste do produto
  (`veryfast` + `zerolatency` + `-bf 0` + `-g 30`), cada alvo fecha dentro de 12% do pedido, cresce com o
  alvo e respeita o piso de ≥73% de economia.
- **Fase 5 — FEITA E PROVADA.** Fonte do radar agora é PLUGÁVEL (decisão A do dono): arquivo `.drq` **ou**
  `tcp://host:porta` (`es_fonte_tcp`/`partir_fonte_tcp`/`quadros_ao_vivo_tcp`/`gerador_da_fonte` em
  `radar_drq.py`; bancada `ground/radar_tcp.py`, 114 linhas, serve o `.drq` no formato de fio medido —
  2.240 B/quadro, `tipo=3`). `tests/test-radar-ao-vivo-tcp.py` (322 linhas, exit 0): radar entra pela rede
  no lugar do arquivo na mesma cadeia; radar fora do ar **não** vira "no ar" mentiroso e o recado fala do
  radar (não de câmera); parada limpa; a placa do dono (arquivo) segue funcionando.
- **Fase 6 — BACKEND + TELA FEITOS, TESTE VERDE.** `ground/api.py`: `ALVOS_DE_QUALIDADE`, `MODOS_DE_RADAR`
  (`ppi`/`cru`), `TAXAS_DE_RADAR` (`30fps`/`volta`), `_radar_da_embarcacao` e `_validar_radar`, rotas
  **GET/POST `/api/embarcacoes/radar`** (por embarcação; nunca devolve segredo) e o envio ao vivo que usa o
  que ficou GRAVADO como padrão (a tela só manda o que mudou). Banco: colunas `radar_fonte/radar_modo/
  radar_taxa/radar_alvo` em `embarcacoes` — a instalação que ATUALIZA ganha as colunas sozinha. Tela:
  `admin/admin.js` com a opção "radar da embarcação", a linha de escolha (embarcação, fonte, imagem, taxa,
  alvo) e o botão "Transmitir o radar ao vivo". `tests/test-radar-por-embarcacao.py` (24 verificações,
  exit 0): coluna criada em banco antigo, opções fechadas, pedido torto recusado (modo/taxa/alvo/fonte/
  embarcação), config POR EMBARCAÇÃO mantida em paralelo, envio usando o gravado e a sobreposição na hora.

## Estado da implementação (16/11/2026)

- `ground/radar_drq.py`: lê `.drq` em sequência (nada de carregar 2,36 GiB), monta PPI e quadro cru em
  1.024×1.024, nas taxas 1 imagem/volta e 30 fps, grava PNG (zlib+struct, sem Pillow) e codifica mp4 no
  ffmpeg do produto, medindo kbps do arquivo.
- Medido no arquivo do dono (168.639 quadros = 60 s de gravação): **PPI/volta: 26 imagens em 8,7 s**;
  **PPI/30 fps: 1.795 imagens (59,8 s de vídeo) em 84 s** (dominado pela codificação). Janela de
  amplitude medida: 1.512..4.092 (12 bits baixos de cada amostra).
- Desenho da PPI (declarado, não escondido): cada direção recebe a última radial daquela direção na volta
  (353 direções desenhadas de 6.719 radiais por volta) — o JSON de cada imagem traz `radiais_da_volta` e
  `radiais_desenhadas`. Na taxa 30 fps a tela é mantida entre imagens (persistência de uma volta).
- Prova executável: `python tests/test-radar-drq-para-video.py` → `RADAR_DRQ_OK` (formato, duas taxas,
  dois modos, mp4 com kbps medido e o arquivo real do dono).

## Incógnitas declaradas (não medidas)

- Semântica dos 4 bits de flag de cada amostra (medido antes, no clone: não medida).
- Taxa de varredura real do radar desta gravação (o azimute fino não avança linearmente no arquivo).
- Se a gravação do radar real trará todos os tipos de quadro (`tipo=3` só apareceu neste arquivo).
