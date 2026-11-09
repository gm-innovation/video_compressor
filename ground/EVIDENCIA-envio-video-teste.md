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
