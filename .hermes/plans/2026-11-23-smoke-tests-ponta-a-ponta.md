**Status:** aprovado (dono, "prossiga", 23/11/2026) — implementando por fase; decisões S1/S2/S3 adotadas como
adotado (b), (a) e (a): o smoke convive com a lista curada por rodada, pode criar/apagar dado próprio
`smoke-<data>` no terra de produção (com limpeza automática; a trilha permanece) e a rodada longa da Fase 4
roda nesta máquina, com o número de campo ficando para o PC de captura real.

**Progresso (23/11/2026):** **Fase 1 fechada** (medidor, ambiente, atendedor de bancada, relatório, comando
único, J1–J4, `docs/smoke.md` — ver §9) e **Fase 2 FECHADA** (J3, J4, J5 e J6): a gravação do cliente
(baixa e some quando ele sai) e o HD do radar de óleo (vê, pede e baixa) medidos na tela — ver §10.
**Fases 3–5 não iniciadas.**

# Smoke tests de ponta a ponta do pipeline bordo → terra → tela

> **Para o Hermes:** este plano é para o dono aprovar antes de existir código. Ele não implementa nada:
> descreve as jornadas que provam que o sistema FUNCIONA (ação de usuário → comando real → efeito
> medido), onde cada jornada roda e como se sabe que passou.

**Goal:** dar ao dono **um comando** que responda, com números medidos, se o produto realmente funciona
ponta a ponta — instalar, o cliente pedir, a câmera subir, o vídeo chegar na tela, a gravação existir, o
HD do radar entregar o trecho e a licença cortar — em vez de provar só que as telas abrem e não quebram.

**Architecture:** um **medidor único** (`tools/smoke/ponta-a-ponta.py`) que sobe o ambiente, executa
**jornadas** (ações de usuário em navegador de verdade + comandos reais de mídia: ffmpeg, mediamtx, SRT),
**mede** o que o produto promete (fps, latência, banda/peso, tempo de subida, tempo de parada) e escreve um
**relatório com veredito por jornada**. O smoke **não reescreve** o que já existe: ele **orquestra** as
provas de nível de efeito que a rodada já tem (`tests/e2e-*.py` que publicam mídia de verdade) e cobre as
jornadas que ainda não têm prova, com **uma regra dura**: *sem número medido e sem arquivo de evidência,
a jornada é "não medida" — nunca "OK"*.

**Tech Stack:** Python 3.12/3.14 (stdlib + `urllib`), Playwright/Chromium (ações de usuário reais),
ffmpeg + mediamtx (mídia real), SRT/HLS/WebRTC, SQLite (bordo e terra), VPS 187.127.60.250 (lado terra de
produção), Supabase `gscfcobpejxhtyzwfrjp` (quando a jornada for de produção controlada).

---

## 1. Evidência de hoje (o que existe, medido — não relatado)

| Fato | Como foi verificado |
|---|---|
| O repositório tem **89 arquivos** em `tests/`, um runner (`tests/suite.py`) e uma regressão curada por rodada (`tools/regressao-0100.py`, hoje `TUDO VERDE (20 provas) RC=0`) | `ls tests/ | wc -l` = 89; execução do `tools/regressao-0100.py` nesta sessão |
| **Não existe nenhum smoke test** no projeto | `grep -rli smoke --include=*.py --include=*.md --include=*.sh .` só retorna arquivos do `numpy` dentro de `.venv/` |
| Existem provas de **efeito real** (não só tela) — ex.: `tests/e2e-gravacao-baixar-e-sair.py` publica mídia com mediamtx+ffmpeg, baixa o arquivo pelo navegador e confere o **apagamento no disco** | docstring e corpo do próprio teste (343 linhas) |
| A suíte **não roda inteira** e ninguém percebe: `tests/e2e-fase3-4.py` falha hoje com `Playwright: Page.goto: net::ERR_CONNECTION_REFUSED at http://127.0.0.1:8765/app` (depende de bancada externa ligada) | execução do teste nesta sessão |
| Há **defeito real** escondido na suíte: `tests/e2e-hd-do-radar-cliente-pede-trecho.py` → `FALHA o cliente VE o catalogo do HD na tela (0 bloco(s), primeiro )` e em seguida `IndexError: list index out of range` (linha 215: `blocos[0]["arquivo"]`) | execução do teste nesta sessão |
| O produto **promete números** e já tem como medi-los: latência RTSP **1,568 s**, HLS **2,596–3,087 s**, banda **5,51 Mbps** com VMAF 94,87 (1080p30), HLS 1280×720 **30 fps** | tabela "Medições feitas na bancada" do `README.md` (linhas 296–307) |
| Existem as ferramentas de medição, mas nenhuma delas está amarrada ao teste do produto: `ground/producao.py` (`link_srt`, `latencia_internet`, `atraso_stream`, `_qualidade_por_fluxo`, `resumo_producao`), `bench/medir-latencia.py`, `tests/medir-aceleracao.py` | leitura dos módulos |
| A bancada tem receita pronta (3 comandos) e fontes sintéticas de vídeo | `README.md` §"Como rodar na bancada" (linhas 283–293): `./ground/start-mediamtx.sh`, `python board/agent.py`, `python ground/api.py 8765` |
| O lado terra de produção está no ar e é acessível | `systemctl is-active pipeline-api.service` = **active**; `/api/saude` = **200** (VPS 187.127.60.250:8085) |
| Existem as rotas que as jornadas precisam | `ground/api.py`: `/api/licenca`, `/api/licenca/ativar`, `/api/licencas`, `/api/varredura`, `/api/cameras` (`/ligar`, `/desligar`, `/prontidao`), `/api/estado-desejado`, `/api/estado-real`, `/api/config-desejada`, `/api/config/aplicar`, `/api/config-aplicada`, `/api/transmissao/{iniciar,sair,pedidos,config}`, `/api/ordens`, `/api/hd/{catalogo,pedir,trecho,baixar}`, `/api/gravacoes/`, `/api/saude-do-bordo`, `/api/tempo-real`, `/api/qualidade/medir` |

**Leitura do conjunto:** o projeto tem profundidade (as provas de efeito existem), mas **não tem um
veredito**: 89 arquivos, dois quebrados, nenhum comando único que diga "o produto funciona hoje" — e a
frase "os testes passaram" hoje se refere a uma lista curada por rodada, não ao produto inteiro.

## 2. O que é (e o que não é) prova de ponta a ponta aqui

**É prova de ponta a ponta** quando a jornada tem as cinco partes:

1. **Ação de usuário real** — clique/digitação em navegador (cliente, admin, operador) ou a ação do
   operador na máquina de captura; nada de chamar função interna no lugar do usuário.
2. **Comando real disparado pelo produto** — `ffmpeg` sobe o canal, `mediamtx` publica, `srt` transporta,
   o arquivo é escrito no disco, a chave é gravada no `licenca.json`. Nada de dublê no caminho de mídia.
3. **Efeito observável do outro lado** — o quadro aparece na tela do cliente, o caminho existe no
   `mediamtx`, o bloco aparece no HD, o apagamento acontece no disco, a trilha de auditoria ganha a linha.
4. **Medida com número** — fps recebido, latência (s), banda de subida (Mbps), peso do bloco, tempo de
   subida (s) e de parada (s), CPU/memória do bordo. **Sem medida, a jornada é "não medida".**
5. **Evidência arquivada** — `smoke/saida/<data>/<jornada>/{resultado.json, qa.md, tela-*.png, log*.txt}`.

**Não é** — e não serve mais como critério de aceite: "a tela abriu", "a rota respondeu 200", "o botão
existe", "não deu erro de JavaScript", "a resposta JSON tem o campo". Isso continua sendo prova de
integridade (útil, mas é piso, não teto).

## 3. Onde roda (dois modos, ambos obrigatórios)

| Modo | Ambiente | Para que serve | Como |
|---|---|---|---|
| **A — bancada** (`--modo bancada`) | máquina de engenharia: API+banco temporário, mediamtx local, câmeras **sintéticas** (`board/agent.py`, 720p30) | roda em minutos, a cada mudança; é o smoke de rotina | mediamtx + agente + `api.py --semear-demo` em banco novo |
| **B — produção controlada** (`--modo producao`) | VPS 187.127.60.250 (lado terra de produção, `pipeline-api.service`) + **PC de captura de verdade** + Supabase | prova que o que ficou publicado funciona no ambiente real | credenciais por variável de ambiente/cofre; **nenhuma credencial de câmera circula em chat, e-mail ou repositório** |

Regras de convivência: cada jornada do modo B **cria o próprio dado** (empresa/embarcação/usuário/licença
com prefixo `smoke-<data>`) e **remove no fim** — o que a campanha inseriu é apagado, a **trilha de
auditoria permanece** (decisão do dono: nada é apagado da trilha). Jornada que grava mídia apaga os
arquivos temporários ao fim.

## 4. As jornadas (o que o smoke prova)

| # | Jornada | Ação do usuário | Comando / efeito real | Medida que fecha o "OK" |
|---|---|---|---|---|
| **J1** | **Instalar e vincular** | instala o app no PC de captura, abre, digita a chave `XXXX-XXXX-XXXX-XXXX` | o bordo grava `licenca.json`, roda a varredura e publica o cadastro no terra | `LICENCA.tem=1`, a embarcação da chave, `>=1` câmera cadastrada no admin |
| **J2** | **O cliente pede e a câmera sobe** | cliente entra na web (`/app`), clica **Iniciar transmissão** | terra publica o desejo → o **agente do bordo olha** → `ffmpeg` liga a câmera → `mediamtx` publica → a tela sintoniza | **fps recebidos ≥30**, **latência ≤3 s**, **Mbps de subida** e **% de redução** vs. bruto, tempo de subida (s) |
| **J3** | **O cliente sai e a banda volta** | cliente fecha a tela | o terra marca a saída → o bordo **para** a câmera (`/api/cameras/desligar`) → o caminho sai do mediamtx | transmissão `parada`, caminho ausente, **subida ≈0 Mbps** em ≤15 s |
| **J4** | **Dois clientes, um sai** | A entra, B entra, A sai (e B continua) | a transmissão **não pode parar** enquanto houver alguém; para só quando o último sai | sessão viva após a saída de A; parada só na saída de B (prova em `tests/e2e-dois-clientes-um-sai.py`) |
| **J5** | **Gravação, download e apagamento** | operador grava; o cliente **baixa** o vídeo; o cliente **sai** | mídia real gravada no terra, download pelo navegador, **arquivo apagado no disco** ao sair | arquivo baixado com tamanho > 0 e abre; arquivo ausente do disco ao sair; **trilha** com pedido/aviso/download/apagamento |
| **J6** | **Radar de óleo e o HD** | admin escolhe o radar; cliente pede um **trecho** do passado | HD grava **full time** (mesmo sem ninguém pedindo) → catálogo → bloco entregue → cliente baixa | bloco gravado sem pedido; **catálogo visível ao cliente** (hoje FALHA — ver §1); trecho baixado íntegro; observador vê só o radar |
| **J7** | **Quem vê o quê** | cliente tipo 1/2/3 e observador entram | escopos 1 (1 barco), 2 (N), 3 (empresa), 4 (observador = radar de todas as empresas) | cada um vê o que deve **e não vê o do vizinho** (prova HTTP + tela) |
| **J8** | **O admin manda, o bordo obedece** | admin muda qualidade / ativa-desativa câmera | terra publica a config → o bordo aplica e **conta o que aplicou** | `config-aplicada` = o que foi mandado; a tela do cliente reflete a mudança |
| **J9** | **Defeito de verdade no bordo** | (nenhuma ação: o defeito é injetado) mata o ffmpeg / estoura a CPU / remove a rede do bordo | o bordo reporta a saúde; o **silêncio** tem de virar problema | semáforo do admin muda em ≤2 ciclos; "nunca reportou" ≠ verde; o aviso diz o que fazer |
| **J10** | **Licença revogada corta** | admin revoga a chave do barco | o bordo consulta o terra e **para** o que estava no ar | transmissões paradas em ≤1 ciclo; o bordo informa a licença caída na tela |

## 5. Fases

Ordem de execução: **1 → 2 → 3 → 4 → 5**. As fases 1–3 rodam em bancada; a 5 é a produção controlada.
Cada fase só começa quando a anterior fecha com o critério de aceite cumprido.

### Fase 1 — O medidor e o núcleo (J1 + J2)
- **P0** — `tools/smoke/ponta-a-ponta.py`: `--modo bancada`, `--jornadas 1,2`, `--saida smoke/saida/<data>`.
  Sobe o ambiente (mediamtx + agente sintético + API com banco temporário), roda as jornadas e escreve
  `resultado.json` + `qa.md` com o veredito **OK / FALHA / NÃO MEDIDA** por jornada.
- **P0** — **J1** (licença + varredura) e **J2** (cliente pede → câmera sobe → vídeo na tela) com atores
  reais: Chromium para o cliente, HTTP real para o bordo, `ffmpeg`+`mediamtx` de verdade na mídia.
- **P0** — o **medidor de qualidade**: fps recebido e latência com `bench/medir-latencia.py` / `atraso_stream`,
  banda de subida com `producao.link_srt()`, % de redução contra o bruto declarado.
- **P1** — limpeza automática do que a rodada sujar (processos, portas, banco temporário, arquivos de mídia).
- **P2** — `--rapido` (só J1+J2, alvo ≤4 min) para rodar antes de cada commit.
- **Custo:** 1 dia. **Dependência:** nenhuma (bancada local).
- **Critério de aceite (comando):** `python tools/smoke/ponta-a-ponta.py --modo bancada --jornadas 1,2`
  termina com `SMOKE: 2/2 OK` e `smoke/saida/<data>/j2/resultado.json` traz **fps, latência, Mbps e o
  tempo de subida** — e falha de propósito quando eu corto o mediamtx à mão (prova de que o medidor mede).

### Fase 2 — O que o cliente manda e o sistema responde (J3, J4, J5, J6)
- **P0** — **J3** (sai → para, banda volta) e **J4** (dois clientes) — o J4 já tem motor em
  `tests/e2e-dois-clientes-um-sai.py`, aqui entra com mídia real e medida de banda.
- **P1** — **J5** (gravação → download → apagamento) reusando o motor de `tests/e2e-gravacao-baixar-e-sair.py`
  e acrescentando a medida de peso/bitrate do arquivo gravado.
- **P2** — **J6** (radar + HD full time + trecho) — **inclui consertar o defeito medido** (`o cliente VE o
  catalogo do HD na tela (0 bloco(s))`, §1): a jornada só passa quando o catálogo chega ao cliente.
- **Custo:** 1,5 dia. **Dependência:** fase 1.
- **Critério de aceite:** `--jornadas 3,4,5,6` → `SMOKE: 4/4 OK`, com a **subida em ≈0 Mbps** na J3, o
  **tempo de parada** medido, o **peso do arquivo baixado** e o **bloco do HD** entregue ao cliente.

### Fase 3 — Escopo, comando do admin e defeito real (J7, J8, J9, J10)
- **P0** — **J7** (os 4 escopos, incluindo "não enxerga o vizinho") e **J8** (admin manda, bordo obedece).
- **P1** — **J9** (defeito injetado: processo morto, CPU no teto, rede fora) — o smoke **injeta** a falha e
  exige a reação da saúde; é a jornada que prova que "bordo mudo é problema".
- **P2** — **J10** (licença revogada corta o que está no ar).
- **Custo:** 1 dia. **Dependência:** fase 1.
- **Critério de aceite:** `--jornadas 7,8,9,10` → `SMOKE: 4/4 OK`, com o **tempo de reação** da saúde
  medido e o isolamento entre barcos/empresas provado nos dois sentidos.

### Fase 4 — Os números do produto (o que ele promete ao cliente)
- **P0** — medir, no mesmo relatório, **≥30 fps**, **≤3 s** de latência ponta a ponta e **≥80 % de redução
  de banda** vs. o bruto, com o comando e o hardware carimbados (regra 2 do README).
- **P1** — **4 câmeras simultâneas + radar**: medir CPU, memória, banda somada e queda de fps por canal
  (o teto real da máquina, não o desejado).
- **P2** — rodada longa (mín. 2 h; alvo 8 h) com o relatório de estabilidade: reinícios, quadros
  perdidos, pico de memória, reconexões do SRT.
- **Custo:** 1 dia (+ a rodada longa, no relógio). **Dependência:** fases 1–3; P1/P2 dependem do PC de
  captura real (4 câmeras + radar por HDMI).
- **Critério de aceite:** `smoke/saida/<data>/qualidade.json` com os três números (fps, latência, redução),
  o comando de origem e o hardware — **abaixo do alvo o veredito é "funcionou com ressalvas", nunca "OK"**.

### Fase 5 — Produção controlada e entrega
- **P0** — `--modo producao`: rodar J1→J10 contra a **VPS de produção** e o **PC de captura real**,
  criando dado próprio (`smoke-<data>`) e removendo no fim (trilha permanece).
- **P0** — relatório de entrega: `smoke/saida/<data>/RELATORIO.md` — jornada por jornada, veredito, os
  números, o que **não** foi medido e por quê, e o que ficou diferente da bancada.
- **P1** — runbook no vault + `index.md` + nota em `10-projetos/pipeline-video.md` (o fato durável vai para
  o vault, não para a conversa).
- **P2** — agendar o modo bancada (`--rapido`) após cada publicação de release e alarmar quando uma jornada
  sair de OK.
- **Custo:** 1 dia. **Dependência:** o **PC de captura real com as 4 câmeras e o radar** — que hoje não
  está nesta máquina; sem ele, a P0 roda contra a VPS + um bordo de bancada e o relatório diz isso.
- **Critério de aceite:** `smoke/saida/<data>/RELATORIO.md` existe, cita o commit, o instalador usado
  (nome + sha256) e o ambiente, e cada jornada tem veredito com número ou a palavra **"não medida"**.

## 6. Arquivos que devem nascer

| Arquivo | Papel |
|---|---|
| `tools/smoke/ponta-a-ponta.py` | o comando único (modos, jornadas, `--rapido`, `--saida`) |
| `tools/smoke/jornadas/j1_vinculo.py` … `j10_licenca.py` | uma jornada por arquivo, cada uma com ação → efeito → medida |
| `tools/smoke/medidor.py` | fps, latência, Mbps, peso, tempos — em cima de `ground/producao.py` e `bench/medir-latencia.py` |
| `tools/smoke/relatorio.py` | `resultado.json` + `qa.md` + o agregado do relatório de entrega |
| `tests/smoke-*.py` | provas de bancada que o smoke orquestra (uma por jornada quando o motor já existe) |
| `docs/smoke.md` | como rodar nos dois modos, o que significa cada veredito, como ler a evidência |
| `README.md` | seção nova "Smoke de ponta a ponta" ao lado de "Como rodar na bancada" |

## 7. Riscos e limites (declarados)

- **O que continua não medido por este smoke:** o link **Starlink Maritime real** (RTT, perda, queda de
  chuva), o hardware definitivo de 4 câmeras + radar por HDMI, e o comportamento com **cliente externo de
  verdade** (hoje quem pede a transmissão no smoke é uma conta de teste criada na hora).
- **Custo de rodar o modo produção:** cada rodada cria e apaga dado real no terra de produção e usa banda
  real da embarcação — por isso o modo B é manual, não agendado (o agendado é o `--rapido` de bancada).
- **Latência medida ≠ latência percebida:** a medida de fps/latência é de mídia no caminho interno; se um
  dia o cliente reclamar de atraso na tela, a medição tem de ser refeita no navegador dele (HLS por
  segmento tem 2,6–3,1 s no README, contra 1,568 s do RTSP).
- **O smoke não substitui a prova de campo** (instalar no computador de captura do cliente, atrás da
  VPN/roteador dele): ele reduz o que sobra para o teste de campo, não elimina.
- **Dois testes já quebrados hoje** (`e2e-fase3-4.py`, `e2e-hd-do-radar-cliente-pede-trecho.py`) são
  dívida da suíte atual: a Fase 2 P2 conserta o segundo (é defeito do produto); o primeiro ou vira jornada
  de smoke ou sai da suíte — teste que depende de bancada externa ligada não pode continuar contando como
  prova do produto.

## 8. Decisões que preciso do dono

| # | Pergunta | Opções | O que muda |
|---|---|---|---|
| S1 | O smoke roda **substituindo** a lista curada por rodada (`tools/regressao-01xx.py`) ou ao lado dela? | (a) o smoke é o portão de publicação e a lista curada vira história; (b) os dois convivem | define se a Fase 1 já troca o gate das publicações |
| S2 | No modo produção, o smoke pode **criar e apagar dado próprio** (`smoke-<data>`) no terra de produção? | (a) sim, com prefixo e limpeza automática; (b) só leitura no terra de produção | define o que a Fase 5 consegue provar |
| S3 | A rodada longa da Fase 4 (`2 h`/`8 h`) roda **nesta máquina** ou no **PC de captura real**? | (a) nesta; (b) no PC de captura | em (a) o número não vale como medição de campo |

## 9. Diário da implementação (Fase 1, 23/11/2026)

**Fase 1 fechada com número.** Comando único `tools/regressao-smoke.py` → **RC=0**: medidor
(`tests/smoke-medidor-detecta-falha.py`, 11 checagens) + **J1–J4 4/4 OK** em 70 s.

Medida de J2 (cliente clica → imagem na tela, fluxo `cam-01` pelo caminho inteiro):
**30,0 fps de mídia · 241 quadros · 3,176 Mbps · latência 0,199 s · tempo_real ✓ · imagem 1920×1080
decodificada com o tempo andando (0,56 → 6,56 s) · arranque 12,7 s do clique até "no ar"**.

### Defeitos e armadilhas encontrados pela bancada (todos medidos)

| # | O que era | Onde estava | Conserto |
|---|---|---|---|
| A | A fonte **sintética** (`testsrc2`, sem `-re`) produz **mais rápido que o tempo real** (238 quadros em 0,38 s): o mediamtx enche o buffer e a **latência do caminho vira número negativo** | `ground/ingestao.py` (ramo `tipo == "sintetica"`) | `-re` no ramo sintético (a webcam já entrega em tempo real) |
| B | O medidor devolvia **0,0 Mbps sempre**: `-f null` **não conta byte nenhum** | `tools/smoke/medidor.py` | a mídia sai por um cano (`-c copy -f mpegts pipe:1`) e os bytes que **chegam** são contados |
| C | O medidor **travava para sempre** com a fonte morta: `for linha in p.stderr` bloqueia e o `terminate()` do `finally` nunca rodava (o ffmpeg ficou pendurado e o `regressao-smoke` só morreu no tempo-limite) | `tools/smoke/medidor.py` | o erro padrão é lido em **fio separado**; o laço tem **tempo-limite** e o `terminate()` sempre roda |
| D | `-rw_timeout` e `-timeout` **quebram a conexão RTSP** nesta compilação do ffmpeg (`Connection to tcp://… failed: Error number -138`, 0 quadros com a fonte **no ar**) | tentativa de conserto do item C | **não usar** flag de tempo no ffmpeg; o limite é do lado do Python |
| E | `tests/smoke-medidor-detecta-falha.py` dava o veredito e **não saía** (filho preso segurava o processo) | `tests/smoke-medidor-detecta-falha.py` | `os._exit(codigo)` depois de esvaziar a saída |
| F | J2 e J4 só passavam **depois** do J1: sem o J1 a câmera do bordo não estava semeada e o bordo respondia *"esta camera nunca foi transmitida daqui"* | `jornadas/j2_ao_vivo.py`, `jornadas/j4_dois_clientes.py` | cada jornada semeia a própria câmera (idempotente) |

### Onde o medidor ainda não é o produto

- A **compresão** (≥80% de redução) e o **SSIM** não são medidos por este smoke: o número do caminho ao
  vivo é o bitrate que o bordo **escolheu** (3,176 Mbps aqui). Entram na Fase 4 ("os números do produto").
- A latência de **0,199 s** é do caminho interno (SRT local + mediamtx local); não é a latência percebida
  num cliente externo (o README já registra 1,568 s no RTSP e 2,6–3,1 s no HLS por segmento).
- **Nesta máquina há webcam de verdade** (`ACER HD User Facing`, `ingestao.maquina_de_captura()` = `true`)
  — o atendedor de bancada continua existindo para a rodada **não depender de a webcam estar livre**, mas
  a próxima rodada pode medir também com a câmera física. Declarado em `docs/smoke.md`.

## 10. Diário da implementação (Fase 2, 23/11/2026)

**Fase 2 FECHADA (P0, P1 e P2) com número.** `python tools/regressao-smoke.py` → **RC=0**: medidor
(11 checagens) + **J1–J6 → `SMOKE: 6/6 OK`** em 108 s (J1 · J2 24,2 s · J3 · J4 · **J5 18,2 s** ·
**J6 16,8 s**).

**Medida de J5 (a gravação, regra do dono "só até o cliente sair"):** o cliente põe a transmissão no ar
(fluxo real do bordo), clica em GRAVAR → a tela diz *Parar gravação* → **2.358.516 B em 7,0 s** de
gravação → o aviso *"gravação pronta — baixe agora / o arquivo é apagado quando você sair da tela ou
desligar o computador"* → **o cliente baixa os mesmos 2.358.516 B, e o ffprobe confirma `h264 1920x1080`
(vídeo de verdade)** → ao sair, **o arquivo é apagado em 0,5 s** e **a linha + as 15 ações de auditoria
ficam** (`gravacao_iniciada`, `gravacao_parada`, `gravacao_avisada`, `gravacao_baixada`,
`gravacoes_apagadas`).

Medida de J6 (o radar de óleo, o caminho inteiro): **o HD gravou 1 bloco sem ninguém pedir (0,7 s)** →
**o agente publicou o catálogo no terra (3 blocos em 4,3 s)** → **o cliente viu 5 trechos na tela** →
**PEDIR → HTTP 201** (fila do bordo) → **o BORDO enviou o bloco (261 B)** → **o cliente baixou 261 B**.
O bloco tem 261 B porque **o dispositivo desta máquina não entrega quadros** (a webcam abre e não produz
frame — medido com `ffmpeg -f dshow -i "ACER HD User Facing" -t 3`: 0 quadro). **O que a J6 prova é a
cadeia** (gravação contínua → catálogo → pedido → envio pelo bordo → download), não a imagem do radar —
que só existe com o radar de verdade no HDMI.

### Defeitos e armadilhas encontrados na Fase 2 (todos medidos)

| # | O que era | Onde estava | Conserto |
|---|---|---|---|
| G | **O defeito do HD não era do produto.** O teste lia o catálogo **uma vez**, logo depois de o primeiro bloco nascer, e o agente publica o catálogo **a cada rodada**: a leitura pegava o catálogo de **antes** do bloco (`resumo.blocos = 0`) e o `IndexError` era consequência | `tests/e2e-hd-do-radar-cliente-pede-trecho.py` (passo 2) | a prova **espera** o catálogo alcançar o disco (como os passos 1 e 4 do mesmo teste já faziam) |
| H | **O laço caseiro do bordo de bancada** reimplementava a rodada e **deixava de fora o catálogo do HD e os pedidos de trecho**: o próprio smoke escondia o defeito que a J6 existe para pegar | `tools/smoke/bordo_de_bancada.py` | o laço passou a chamar **`agente_de_ordens.uma_rodada`** (a rodada do produto); a única substituição continua sendo **quem atende o POST local** |
| I | O agente **só publica o catálogo** se o ambiente do HD estiver nele (`LECSOR_GRAVACAO_CONTINUA=1`) e, na bancada, ele sobe **antes** do HD | `tools/smoke/ambiente.py` | `reiniciar_agente()`: a J6 sobe o agente **com o ambiente do HD** (defeito da bancada, não do produto) |
| J | A tabela do HD nasce com uma linha de **"carregando"**: contar linha **não provava nada** (a primeira rodada deu *5 linhas* de cabeçalho e 1 linha falsa de dado) | `jornadas/j6_radar_hd.py` | a checagem exige o resumo do app (`N trecho(s)`) — ele só é escrito **depois** de o catálogo chegar |
| K | A tela do HD **não se atualiza sozinha**: com o trecho já `enviado`, o botão continuava `pedir` | `jornadas/j6_radar_hd.py` | a J6 **reabre a tela** (o gesto que o cliente faria) até aparecer o BAIXAR |
| L | O botão de gravar passa por **"gravando…"** antes de virar **"Parar gravação"**: esperar o primeiro texto não-vazio lia o **meio do caminho** e reprovava a jornada certa | `jornadas/j5_gravacao_baixa_e_apaga.py` | a espera passou a aguardar o texto **"parar"** no botão |
| M | **Uma leitura da tela derrubava a jornada inteira:** `tela_do_cliente` faz `pagina.evaluate(...)` e numa rodada a leitura voltou **string** → `AttributeError: 'str' object has no attribute 'get'` **matou a J2** (13 checagens OK e o resto perdido) | `tools/smoke/medidor.py` | a leitura virou **tolerante**: leitura que não é dicionário vira `erro` na medida e o veredito diz "sem imagem" com o motivo, em vez de explodir |
| N | O laço do smoke **engolia a pilha** da jornada que explodia (`ERRO AttributeError: ...` sem o lugar) — meia-prova na hora de consertar | `tools/smoke/ponta-a-ponta.py` | o `except` imprime o **traceback** no log |

### O que a Fase 2 ainda não mede

- **O conteúdo de imagem do HD do radar:** depende do radar de verdade entrando por HDMI. Nesta bancada o
  anel de blocos é provado (gravou, girou, catalogou, entregou, baixou), o **quadro** não. (Na J5, que usa
  a fonte sintética, o vídeo gravado/baixado **é** imagem de verdade — `h264 1920x1080` lido pelo ffprobe.)
- **O apagamento com o cliente DESLIGANDO o computador** (o batimento de 10 s): a J5 prova a saída pela
  tela (`pagehide`, 0,5 s); a queda do computador é coberta pelo batimento e fica para a Fase 3.

## 11. Diário da implementação (Fase 3, 23/11/2026) — **FECHADA**

**Comando do critério de aceite:** `python tools/smoke/ponta-a-ponta.py --jornadas 7,8,9,10`
→ **`SMOKE: 4/4 OK · 0 FALHA · 0 com ressalvas · 0 NÃO MEDIDA`** (RC=0).

| Jornada | Medida que fechou o OK | Tempo |
|---|---|---|
| **J7** — os 4 escopos | o painel diz o escopo de cada um (tipo 1/2/3/4), cada cliente vê **só** os barcos dele (1/2/2/4) e o do vizinho é negado nos dois sentidos (HTTP 403/422) | 3,9 s |
| **J8** — o admin manda | o cliente publica config → **403**; o admin publica `alvo_kbps=500` → o bordo grava `cameras.alvo='500k'`, confirma no terra e a banda **cai de 3,187 para 0,773 Mbps** com o vídeo de pé (28,26 fps); o admin publica `teto_s=1800` → o bordo grava; o admin **desliga** a câmera → o bordo desliga e o fluxo sai do mediamtx | 73,4 s |
| **J9** — o defeito de verdade | o bordo reporta a saúde (9 sinais, sem segredo, com `nao_medido`); **com o ffmpeg fora do bordo o painel vira "problema" em 1,0 s**; 25 erros de envio viram "atenção"; o pedido pendente vira "atenção"; o bordo mudo vira "atenção" em **179,3 s** (limiar 180 s); a série preserva os 5 retratos | 195,7 s |
| **J10** — licença revogada | o admin revoga → **o bordo consulta o terra sozinho e a transmissão morre em 2,3 s** (ciclo da bancada 5 s) → o fluxo sai do mediamtx, a tela diz o motivo, a trilha registra **1** `captura_parada_por_licenca`, o vínculo **não** é apagado e a reativação devolve o barco ao ar | 58,7 s |

### Defeitos e armadilhas encontrados na Fase 3 (todos medidos)

| # | O que era | Onde estava | Conserto |
|---|---|---|---|
| **O** | **DEFEITO REAL DO PRODUTO — o formato do `alvo`.** O admin publicava `alvo_kbps` e o valor gravado em `cameras.alvo` ia **cru** para o `-b:v` do ffmpeg: `800` é lido como **800 BITS/s** (0,0 Mbps, **0 quadro**). A convenção do produto é `"NNNNk"` (milhares de bits — ver `ingestao.alvo_automatico` e a lista da tela da câmera) | `ground/api.py` (validação do `alvo_kbps`) | a validação passou a aceitar `"800"` **e** `"800k"` (`valor.rstrip("kK") not in VALORES_DE_ALVO`) e o valor gravado carrega o `k`. **Os dois testes e2e que passavam com o defeito** (`"800"` → `"800k"`) foram atualizados — o teste antigo **deixava passar** o defeito medido |
| **P** | O atendedor da bancada recusava `teto_s` com **422 "informe a camera"**: a trava de câmera valia também para a rota de configuração, que é da **embarcação** e vem **sem** câmera | `tools/smoke/bordo_de_bancada.py` | a trava passou a valer **só** nas rotas de câmera (`/api/cameras/ligar|desligar`) |
| **Q** | A **J10 não subia navegador**: o medidor só lançava Chromium para `{2,3,4,5,6,8}` e a J10 exige navegador | `tools/smoke/ponta-a-ponta.py` | o conjunto passou a `{2,3,4,5,6,8,10}` |
| **R** | **DEFEITO REAL DO PRODUTO — a revogação não cortava sozinha.** A rota local `/api/licenca` era quem sabia da revogação (ela pergunta ao terra e para a captura), **mas só era lida quando alguém abria a tela da licença naquela máquina**. Com o barco em operação e ninguém olhando o PC de captura, a chave revogada **continuava transmitindo** — a J10 mediu o envio de pé **120 s** depois da revogação (limite do teste) | `ground/agente_de_ordens.py` + `ground/ingestao.py` | (1) o laço de captura passou a **conferir a licença sozinho** (`conferir_licenca`, a cada `LECSOR_ESPERA_DA_LICENCA`, padrão 300 s — o mesmo em que o produto já confere), **antes** da flag: o pedido do cliente já encontra a captura bloqueada; (2) `ingestao.ligar_camera` passou a **recusar** o que a licença proíbe (`licenca_bloqueia_captura`) — assim o pedido do cliente (a flag) não desfaz o corte por nenhuma porta; (3) o miolo da rota virou `api.conferir_licenca_do_terra`, reusado pelo laço **e** pela bancada |
| **S** | **A "memória" do agente prendia a câmera.** `agente_de_ordens._ligado` respondia pelo que o **agente lembrava** (arquivo `ligados`), não pelo que estava no ar: se algo **de fora** parasse a câmera (a licença, por exemplo), o pedido do cliente não a levantava de novo e o estado contado era mentira | `ground/agente_de_ordens.py` | `_ligado` passou a conferir o **estado GRAVADO** (`ingestoes`, quem escreve é o produto ao parar/ligar): memória que não bate com o banco é corrigida e a câmera volta a obedecer |
| **T** | A trilha **repetia**: com a chave caída, cada conferência do laço "parava" câmeras já paradas e escrevia **outra** linha `captura_parada_por_licenca` com o mesmo conteúdo (**8 linhas iguais em ~40 s**) | `ground/api.py` (`parar_por_licenca`) | o corte acontece na **transição** (liberada → bloqueada): uma vez, com a trilha registrando o corte; nas conferências seguintes não há o que cortar |
| **U** | **A J2 caiu inteira com `AttributeError: 'str' object has no attribute 'get'`** na leitura da tela: o `|| vs[0]` devolvia o **elemento de vídeo** (que o navegador não serializa) e a leitura voltava string. O mesmo defeito já tinha aparecido na Fase 2 (achado M) e **não** tinha sido fechado na raiz | `tools/smoke/medidor.py` (`tela_do_cliente`) | todo caminho do JS monta um **objeto simples** e o Python **confere o formato** do que voltou (`leitura inesperada do video: str`) em vez de explodir |
| **V** | **Duas cópias de ffmpeg no PATH** desta máquina (Hermes e WinGet): a J9 tirava só a primeira pasta do `which` e o ffmpeg voltava pela segunda | `tools/smoke/jornadas/j9_defeito_e_saude.py` | `_path_sem_ffmpeg()` remove **todas** as pastas com ffmpeg |
| **W** | A J9 pedia um ciclo de saúde **menor que o do produto**: `agente_de_ordens.intervalo_da_saude` **clampa** em ≥10 s (a bancada não consegue pedir menos) | `tools/smoke/jornadas/j9_defeito_e_saude.py` | `CICLO_DA_BANCADA_S = 10` |

### O que a Fase 3 ainda não mede

- **O ffmpeg sem sinal de rede** (a J9 prova o ffmpeg ausente; rede fora fica para a Fase 4, com o link real).
- **A latência real da revogação no produto**: a bancada encurta o ciclo (5 s) para caber no relógio e o
  produto confere a cada 300 s — o que a J10 prova é o **caminho** (o bordo pergunta sozinho e corta), não o
  número de campo.
- **A rodada completa (J1–J10) num host ocioso:** na rodada completa desta máquina, com o app de trabalho
  aberto, a **J2 mediu 26,39 fps** (piso de 27) e falhou **por carga do host**, não pelo produto — isolada,
  a J2 mede **30,0 fps**. O número de campo é do PC de captura (declarado desde a Fase 1).
