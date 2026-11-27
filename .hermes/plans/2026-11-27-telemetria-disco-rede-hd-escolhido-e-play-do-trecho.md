# Plano 0.28.0 — a telemetria evidente no admin, o HD escolhido e medido, o seletor de data/hora e o play do trecho

**Pedido do dono (27/11/2026, verbatim, com 3 prints):**

> "a telemetria do pc de captura precisa estar evidente no dashboard do admin, note que não tem disco e nem rede"
> "outra coisa, precisamos definir qual disco e quanto dele será utilizado para gravação."
> "preciso poder selecionar data e hora, não ter que digitar"
> "não aparece nada para dar play na gravação, eu deveria poder dar play e ver em tempo real com barra de linha do tempo"

**Prints:** (1) o cartão da embarcação no admin — `CPU 19,2% · memória 60,2% · HD do radar — · câmeras no ar 0 de 4`
· `gravando a bordo: não`; (2) a tela "Gravações" com dois campos `27/mm/aaaa --:--` / `dd/mm/aaaa --:--` e os
botões `filtrar` / `ver tudo`; (3) o bloco "Gravado a bordo · Radar de óleo (HD)" com as colunas
`Quando · Tamanho · Situação · Trecho` e a linha **"Carregando as imagens do radar…"**, sem nada para dar play.

---

## O que já foi MEDIDO (não é suposição)

1. **O retrato do PC de captura TEM os números.** Retrato da `bancada` na VPS, `2026-11-27T14:05:00Z`,
   `versao_app 0.27.1`, `estado ok`, `nao_medido {}` (o psutil está medindo tudo):
   - `discos`: `[{"nome": "aplicativo", "caminho": "C:\\Users\\HAVOX\\AppData\\Local\\Programs\\LECSOR\\resources\\servidor",
     "total_gb": 254.0, "livre_gb": 194.8, "usado_pct": 23.3}]`
   - `rede`: interfaces medidas, com `enviado_mbps`/`recebido_mbps` por interface e o total em `rede.total`
     (a `Ethernet` ia com 3067,1 MB enviados).
2. **O `api.py` já carrega isso na saúde da embarcação** (`api.py:1555-1580`: `discos` e `rede` entram no
   dicionário da `saude`), **mas o item da frota** (`api.py:1670-1682`) só publica `cpu_pct`, `memoria_pct`,
   `hd_radar_usado_pct`, `cameras` e `no_ar` — **disco livre e rede não chegam ao cartão**, e o cartão
   (`admin/admin.js:2576-2579`) só escreve "CPU · memória · HD do radar · câmeras no ar". **É por isso que
   o print não tem disco nem rede**: o dado existe a bordo, o transporte existe, a linha não mostra.
3. **`HD do radar —` é defeito, e é de régua.** `ground/saude_do_bordo.py::_discos()` só rotula um disco
   como **"hd do radar"** quando existe a variável `LECSOR_HD_DIR` — que **ninguém define** no app
   instalado (o gravador usa `gravacao_continua.diretorio()`, a pasta `ground/hd` do aplicativo). Sem esse
   rótulo o cartão mostra `—`. A régua do "HD do radar" tem de ser **o diretório de gravação de verdade**,
   a mesma fonte que o gravador usa.
4. **O que decide onde gravar é uma constante de código + uma env de bancada.** `diretorio()` =
   `LECSOR_HD_DIR` **ou** `RAIZ/ground/hd`; o anel (`manter_anel`) roda com `LECSOR_HD_RESERVA_MB`
   (padrão **512 MB**). **Não há escolha de disco nem de cota no admin** — e é isso que o dono quer definir.
5. **Data/hora hoje são `<input type="datetime-local">`** (`app/index.html:77-78`, lidos em
   `app/app.js:834-835`) — o navegador exige digitação e o print mostra exatamente isso. **Não há atalhos**
   ("últimos 30 min", "hoje") nem escolha pelo que existe.
6. **Não existe player nenhum.** O catálogo lista os blocos e o único caminho é o botão **`pedir`**
   (`app/app.js:869-898` → `pedirTrechoDoHd` → o bordo manda o arquivo → `guardar_trecho_do_hd`). Nada de
   `<video>`, nada de barra de linha do tempo: por isso "não aparece nada para dar play".
7. **A bancada tem UM disco só** (o do aplicativo, 254 GB / 194,8 GB livres). Um "HD do radar" dedicado
   (segundo disco) **não existe nesta máquina** — a escolha de disco tem de funcionar com 1 disco e com N.

---

## Decisões do dono (RESPONDIDAS em 27/11/2026)

- **D1 — a lista de discos vem MEDIDA do PC de captura** (o bordo propõe, o admin escolhe da lista; nada de
  digitar caminho no admin). ✅
- **D2 — a cota é em GB** ("use até 500 GB deste disco"). ✅
- **D3 — depende de quantos discos houver:** com **um disco só**, grava nele (não há escolha a fazer); com
  **dois ou mais**, o admin escolhe. Em nenhum caso o já gravado é movido. ✅
- **D4 — o play puxa DO BORDO em tempo real:** o trecho começa a tocar **enquanto chega** do PC de captura
  (o pedido continua partindo de terra pelo caminho que já existe; o terra nunca abre conexão para o bordo).
  ✅
- **D5 — linha do tempo CONTÍNUA:** os trechos emendam em sequência e o fim da linha é o "agora". ✅
- **D6 — seletor completo:** calendário + hora clicáveis, atalhos de período e o trecho clicável como
  seletor. ✅

**Limite honesto da D4 (o produto não pode prometer o que o link não fizer):** o tempo até o primeiro quadro
é o tempo do link (o pedido viaja terra→bordo, o bordo manda o trecho). Se o link não sustentar, a tela diz
**quanto já chegou e quanto falta** — nunca um player girando vazio.


---

## Fase 1 — A telemetria do PC de captura evidente no dashboard do admin

Objetivo: o cartão de cada embarcação mostra **CPU, memória, disco (livre/total do disco que grava) e rede
(enviado/recebido agora)** — os mesmos números que o bordo mede — e, quando algo não foi medido, diz
**"não medido" com o motivo** (nunca um traço mudo).

- **P0** — `api.py::frota_resumo` (item da embarcação): publicar `disco_livre_gb`, `disco_total_gb`,
  `disco_usado_pct`, `rede_envio_mbps`, `rede_recebimento_mbps` (e o `hd_radar_usado_pct` corrigido) a
  partir da `saude` da embarcação (fonte única: o retrato do bordo). Nada de número inventado: campo
  ausente = `nao_medido` com o motivo que o bordo mandou.
- **P0** — `admin/admin.js`: a linha do cartão passa a escrever **`CPU x% · memória y% · disco z GB livres de
  T GB (n%) · rede ↑a / ↓b Mbps`**, com o "não medido — <motivo>" quando for o caso.
- **P0** — `ground/saude_do_bordo.py::_discos()`: a régua do "hd do radar" passa a ser **o diretório de
  gravação real** (`gravacao_continua.diretorio()`), não a env `LECSOR_HD_DIR` — é o defeito que produz o
  `HD do radar —` do print.
- **P1** — semáforo/limiar por sinal (disco ≥ 90% usado = atenção; rede sem movimento = atenção) usando o
  mesmo `classificar_saude` e o "o que fazer" que o admin já mostra hoje.
- **P1** — a **gaveta por câmera/encoder** ganha disco e rede por fluxo (o `individual` já tem
  `disco_livre_gb`/`rede_mbps`; falta a coluna na gaveta).
- **P2** — histórico: a curva de disco e de rede por embarcação (o painel do bordo já tem as 4 curvas; o
  admin ganha a mesma leitura, uma vez que a série exista).

**Provado por:** prova nova do item da frota (o cartão recebe disco e rede com o retrato real da bancada e
diz "não medido" com motivo quando o retrato não tem o campo) + prova de tela no e2e do dashboard do admin.

## Fase 2 — Qual disco e quanto dele para a gravação

Objetivo: o dono escolhe, no admin, **em qual disco** o HD do radar grava e **quanto** desse disco pode ser
usado — o PC de captura mede e propõe, o admin decide, o bordo aplica.

- **P0** — o bordo passa a medir **todos os discos** (não só o do aplicativo) e a publicar em cada um:
  letra/caminho, `total_gb`, `livre_gb`, `usado_pct`, e qual dele é o **disco atual da gravação**.
- **P0** — o admin mostra essa lista medida e o dono escolhe **disco + cota em GB** (D1/D2) no cartão da
  embarcação, ao lado do botão da gravação contínua; **com um disco só a escolha não aparece** (grava nele,
  e a tela diz isso) e **com dois ou mais o seletor aparece** (D3).
- **P0** — o comando viaja pelo caminho que já existe (o mesmo do `gravacao_continua`/`alvo_kbps`): o
  admin publica, o bordo **aplica localmente** (`aplicar_config_local` → `ground/hd/config.json`) e
  **conta o que fez** — sem reabrir porta para o bordo e sem o terra abrir conexão.
- **P1** — o gravador passa a usar o disco escolhido e a **cota** como o anel de disco (hoje é uma reserva
  fixa de 512 MB): o anel apaga o trecho mais antigo **daquele disco** quando a cota aperta, e o disco do
  sistema operacional fica intocado.
- **P1** — trocar de disco **não apaga nem move** o que já existe (D3) e o catálogo passa a dizer de qual
  disco cada trecho veio (o cliente vê de onde aquele trecho saiu).
- **P1** — as duas telas (admin e bordo) dizem **qual disco e qual cota estão valendo agora**, com a
  origem ("escolha do admin" × "padrão da instalação") — como já é feito com o dispositivo do radar.
- **P2** — aviso quando o disco escolhido encher (o anel roda, mas a tela diz que está no limite) e aviso
  quando o disco escolhido **sumir** (desconectado): o gravador **para de gravar com o motivo escrito**, em
  vez de gravar em outro lugar sem ninguém saber.

**Provado por:** prova nova (o bordo respeita o disco + a cota publicados; a cota cheia apaga o mais antigo
e mantém o resto; o disco que sumiu gera o motivo nas duas telas) + a escolha aparecendo no admin.

## Fase 3 — Data e hora por seleção, nunca por digitação

Objetivo: o dono escolhe o período clicando (calendário + hora) ou clicando em um trecho que já existe.

- **P0** — a tela de Gravarações do app troca os dois `datetime-local` por um **seletor de verdade**
  (calendário + hora em passos clicáveis, D6) — sem digitar nada.
- **P0** — **atalhos de período**: "últimos 30 min", "últimas 2 h", "hoje", "ontem", "tudo" — um clique.
- **P1** — a **lista de trechos vira o seletor**: clicar num trecho já preenche o período (e abre o play,
  ver Fase 4), porque o que existe está ali na frente.
- **P1** — o período escolhido fica **na barra de endereço** (link) para o dono mandar para outra pessoa
  abrir no mesmo ponto — sem reconfigurar nada.
- **P2** — fuso: tudo é mostrado em **horário de Brasília** com a marcação explícita, sem converter o que o
  bordo gravou em UTC.

**Provado por:** prova de tela (Playwright): o período é escolhido **sem nenhum evento de digitação** (a
prova mede que não houve `keydown`/`input` de texto) e o filtro devolve os trechos certos.

## Fase 4 — Play do trecho com barra de linha do tempo

Objetivo: dar play e ver o trecho, com a barra de linha do tempo — o que hoje não existe.

- **P0** — **o play puxa do bordo (D4):** o dono escolhe o horário e o trecho **começa a tocar enquanto chega**
  do PC de captura, sem esperar o arquivo inteiro — com o pedido pelo caminho que já existe (terra pede, o
  bordo manda) e a tela dizendo **quanto já chegou e quanto falta**.
- **P0** — o trecho ganha **player** (`<video>` com controles próprios): play/pausa, barra de avanço, tempo
  decorrido/total e o horário real do trecho (ex.: `27/11 09:12 → 09:13`).
- **P0** — a barra é uma **linha do tempo do que existe (D5, contínua)**: os trechos gravados aparecem como
  segmentos no tempo (o cliente vê os buracos também), **emendam em sequência** (acabou um, a barra salta
  para o próximo e segue) e o fim da linha é o **agora** do radar.
- **P1** — pedir o próximo trecho **antecipadamente** enquanto o atual toca (o pedido já existe; falta
  pedir antes de acabar, para não haver espera).
- **P1** — se o link não sustentar o play enquanto chega, a barra mostra **o que já tem** e continua
  pedindo; a tela não trava nem fica girando vazio.
- **P2** — a barra do tempo aceita o **registro de eventos** (o que aconteceu no minuto: câmera ligada,
  transmissão, queda), no mesmo eixo de tempo do vídeo.

**Provado por:** prova de tela (o player existe, toca, a barra avança, o segundo trecho emenda no primeiro) e
prova de rota (o trecho pedido chega e é servido com o nome e o horário certos).

## Fase 5 — Provas, publicação e o que só o hardware resolve

- **P0** — todas as provas novas entram na regressão curada (`tools/regressao-0130.py`) e no
  `unittest discover`; nada de rodada sem número.
- **P0** — versão **0.28.0**: `VERSION` + `desktop/package.json` + nota em `tools/publicar-releases.py`;
  instalador, release e deploy na VPS (o caminho já provado nas 0.26/0.27).
- **P0** — nota do vault com os números medidos (commit, instalador, release, deploy).
- **P1** — o PC de captura real (HAVOX) **instala a 0.28.0**: só então as telas mostram disco/rede daquele
  PC e o HD do radar grava no disco escolhido — o app não se auto-atualiza.

---

## O que este plano NÃO faz (para não confundir)

- Não muda o desenho de segurança: **o terra continua sem abrir conexão para o bordo** e o cadastro de
  câmera continua **só no app de captura** (IP e senha nunca vão para terra).
- Não coloca vídeo do radar "ao vivo" no lugar do HD do bordo: o play é do **trecho gravado, puxado do
  bordo** (D4); o radar ao vivo continua sendo o fluxo do mediaMTX, e o terra continua **sem abrir conexão
  para o bordo** (o pedido vai na fila que o bordo já busca).
- Não apaga nada do histórico: trocar disco/cota não apaga trecho nenhum fora do anel do próprio disco, e
  toda ação continua na auditoria.

---

## Estado da implementação (27/11/2026)

**Fase 1 (telemetria evidente) — FEITA e MEDIDA.** O item da embarcação no resumo do admin passou a levar
`disco_nome`/`disco_livre_gb`/`disco_total_gb`/`disco_usado_pct`/`discos`/`rede_envio_mbps`/
`rede_recebimento_mbps` (`ground/api.py`) e o cartão do admin ganhou a linha do disco e da rede
(`admin/admin.js`: `linhaDoDisco()`, `linhaDaRede()`, `numeroDaFrota()`), aceitando os dois nomes da mesma
medida (o item da frota usa `disco_*`; o cartão usa `hd_radar_*`). A régua do "HD do radar" deixou de olhar
`LECSOR_HD_DIR` (que ninguém define) e passa a usar `gravacao_continua.diretorio()` — o diretório de
gravação de verdade (`ground/saude_do_bordo.py::_discos()`). **Medido** por
`tests/e2e-saude-do-bordo-no-admin.py` (seções 9 e 10): o cartão escreve
`disco do radar 400.0 GB livres de 931.5 GB (57.1% usado)` e `rede ↑3.1 / ↓0.4 Mbps agora`.

**Fase 2 (qual disco e quanto dele) — FEITA e MEDIDA.** A escolha mora em lugar FIXO
(`ground/hd/config.json`) — se morasse no disco escolhido, trocar de disco apagaria a própria escolha — e a
chave `hd_disco`/`hd_cota_gb` (da embarcação, sem `camera_id`) viaja pela config publicada, o MESMO caminho
da gravação continua (o terra nunca abre conexão para o bordo). O anel passou a ter **dois limites**: a
reserva de sistema e a **cota do admin** (`ground/gravacao_continua.py`). Com **um disco só** não há seletor
(a tela diz que grava nele); com **dois ou mais** aparece o `select` com os discos MEDIDOS pelo PC de
captura (+ "padrão da instalação"). Rota nova `/api/hd/escolher` (só admin, disco e cota na mesma chamada).
**Medido** por `tests/e2e-saude-do-bordo-no-admin.py` (seção 10) e
`tests/test-escolha-do-disco-e-cota-do-hd.py` (9 provas: padrão, escolha, disco inexistente recusado, cota
fora da faixa recusada, anel pela cota, anel pela reserva, `LECSOR_HD_DIR` vencendo, régua da saúde, resumo).

**Fase 3 (data e hora sem digitar) — FEITA e MEDIDA.** A faixa de período perdeu os dois
`<input type="datetime-local">` e ganhou: **dia** por calendário (`input type="date"`), **hora** e
**minuto** por lista (`select`), quatro **atalhos** ("últimos 30 min", "últimas 2 h", "hoje", "ontem") e
"ver tudo". **Medido** por `tests/e2e-play-do-trecho-e-seletor-sem-digitar.py`: **zero** campos de digitação
na faixa (`text`/`datetime-local`/`textarea`), 2 calendários + 4 listas, o clique em "ontem" preenchendo as
duas pontas.

**Fase 4 (play com linha do tempo) — FEITA e MEDIDA.** O bloco do bordo passou a sair **MP4
FRAGMENTADO**. Aqui há um achado que vale registrar: o `-movflags` antes do `-f segment` **não chega** ao
muxer mp4 — medido, o arquivo saía `ftyp,free,mdat,moov` (índice no fim) e o prefixo era **ilegível** para
o ffprobe; a forma que funciona é `-segment_format_options movflags=+frag_keyframe+empty_moov+...`, e então
o bloco sai `ftyp,moov,moof,mdat` e o ffprobe **lê 73 dos 120 quadros** do arquivo cortado em 60% (o que já
teria chegado do bordo). Rota nova `/api/hd/tocar` (serve o arquivo que CRESCE, com `Range` e
`parcial_bytes` no catálogo), coluna "ver" em toda linha, `player <video>` + **linha do tempo contínua**
(um segmento por bloco, buracos visíveis, fim = "agora", emenda no próximo trecho) e o `<video>` **não é
recriado** enquanto o trecho chega. **Medido** por `tests/e2e-play-do-trecho-e-seletor-sem-digitar.py`
(14 provas, incluindo 200 + tamanho exato, `Range` 206/100 B, o mesmo `<video>` após 6 s e o texto
"chegando do bordo em tempo real: já recebi 0.4 MB") e por `tests/test-escolha-do-disco-e-cota-do-hd.py`.

**Fase 5 — EM ANDAMENTO.** Provas na regressão curada: FEITO (`tools/regressao-0130.py` com o bloco
0.28.0). Falta: rodada completa da regressão, `unittest`, bump para 0.28.0, instalador, release, deploy na
VPS e nota do vault.

**Aberto (não é desta rodada):** instalar a 0.28.0 no PC de captura real (HAVOX, hoje 0.25.0) — só então
aparecem o disco e a rede daquele PC, e o HD do radar grava no disco escolhido. O app **não se
auto-atualiza**.

---

## 0.28.1 — a correção do achado na prova do deploy (27/11/2026)

**Achado (medido, não suposto).** A prova do deploy da 0.28.0 na VPS imprimiu o retrato que o bordo publica,
e ele trazia **DUAS linhas apontando para o MESMO volume**:

```
[{'nome': 'hd do radar', 'caminho': '/', 'livre_gb': 49.8, 'total_gb': 102.9, 'usado_pct': 51.6, 'cota_gb': None},
 {'nome': 'aplicativo',  'caminho': '/', 'livre_gb': 49.8, 'total_gb': 102.9, 'usado_pct': 51.6, 'cota_gb': None}]
```

**Causa:** a pasta de gravação (`ground/hd`) nasce quando o produto grava o primeiro bloco; **no Linux o
`os.stat` de um caminho que ainda não existe estoura** e `_mesmo_volume` respondia "volumes diferentes" — o
disco do aplicativo entrava como um segundo disco. No Windows o defeito não aparecia (a régua lá é a letra
da unidade), e por isso a bancada ficou verde. Consequência real: o admin via **dois discos iguais** na
lista de escolha.

**Correção:** a comparação passou a ser entre **volumes que existem** (`_caminho_para_medir` — o mesmo
caminho que já mede o disco), mantendo o comportamento do Windows.

**Prova:** `_discos()` na VPS antes (2 linhas) / depois (1 linha); seção 11 nova em
`tests/test-escolha-do-disco-e-cota-do-hd.py`; regressão curada **55/55**; `unittest` **22/22**.

**Fora do plano, mas dentro do pedido:** a VPS não tinha `psutil` no `python3` — o retrato do lado terra
dizia "sem psutil: rede não medida" (era o "nem rede" do dono, do lado de terra). Instalado
(`python3-psutil` 5.9.8, medido: `nao_medido = {}` e as interfaces com enviado/recebido). **No PC de
captura o psutil já viaja dentro do pacote**, desde a 0.27.0 — é ele que faz o disco e a rede aparecerem no
cartão do admin.
