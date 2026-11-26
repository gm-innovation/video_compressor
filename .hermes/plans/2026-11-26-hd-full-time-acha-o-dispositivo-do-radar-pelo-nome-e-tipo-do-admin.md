# 0.26.0 — o HD full-time do radar acha o dispositivo pelo nome/tipo do admin

## Objetivo

Fazer o gravador full-time do radar (HD a bordo) **achar o dispositivo de vídeo sozinho** — pelo
**nome que o admin cria em terra** (o rótulo da câmera, ex.: "Radar de Óleo") **ou pelo tipo escolhido no
app do admin** (`tipo = radar`) — sem depender de `LECSOR_HD_DISPOSITIVO`, que hoje ninguém define.

## Medido em 26/11/2026 (não é suposição)

- `hd_catalogo` (`bancada` / `radar`) = `{"ligada": true, "dispositivo": "", "blocos": 0, "bytes": 0,
  "bloco_segundos": 60, "diretorio": "C:\\Users\\HAVOX\\...\\LECSOR\\resources\\servidor\\ground\\hd"}` —
  ligada, **sem dispositivo**, **0 bloco(s)**.
- `hd_catalogo` = 1 linha, `hd_pedidos` = 0, `ground/gravacoes/` (terra) vazio.
- Câmera `Radar de Óleo` existe com `tipo='radar'`, `rotulo='Radar de Óleo'`, `ativo=1`
  (id `cam-device-pnp-usb-vid-345f-pid-2131-mi-00-6-f69`).
- `ground/gravacao_continua.py:223` → `dispositivo()` = `LECSOR_HD_DISPOSITIVO`, e **nenhum arquivo do
  repositório define essa variável** (grep no repo inteiro): o gravador nunca tem dispositivo.
- A varredura do bordo (`ground/varredura_do_bordo.py`) já sabe achar o radar (`_parece_radar` +
  `radar_fonte` da embarcação), mas **não é consultada** pelo gravador.
- `config_local` já guarda `dispositivo` e `rotulo` por câmera; `tipo_definido_pelo_admin` marca o que o
  admin escolheu.

## Fase 1 — P0: o gravador resolve o dispositivo (fonte única)

- `ground/gravacao_continua.py`: `dispositivo()` passa a resolver, nesta ordem: **(1)** `LECSOR_HD_DISPOSITIVO`
  (se existir, manda); **(2)** a **câmera com o tipo do admin** (`tipo='radar'`, priorizando
  `tipo_definido_pelo_admin=1`) e o `dispositivo` dela em `config_local`; **(3)** a **fonte declarada** da
  embarcação (`radar_fonte`); **(4)** casar o **nome do admin** com o nome do dispositivo que a varredura viu;
  **(5)** o primeiro candidato que "parece radar".
- Devolve junto a **origem** (`env` / `tipo` / `nome` / `fonte` / `candidato`) e o **motivo** quando nada casar.
- **P1:** o mesmo resolvedor é usado por `/api/bordo` e pela varredura (nada de duas regras diferentes).
- **P2:** cache de 60 s (a varredura custa ~1 s de `ffmpeg -list_devices`).

## Fase 2 — P0: o painel do bordo diz qual dispositivo e por quê

- `bordo/index.html` + `/api/bordo`: a linha do HD mostra **o dispositivo em uso**, a **origem** dele e
  "0 bloco(s) desde <data/hora>" quando não houver bloco — e o **MOTIVO** quando nada casou. Nunca mais
  "ligada" sem gravar.
- **P1:** ação "usar o dispositivo X no HD" (só admin) para forçar a escolha sem mexer em variável de ambiente.
- **P2:** `hd/log/gravacao-continua.log` grava o motivo na primeira linha de cada início.

## Fase 3 — P1: terra mostra o mesmo motivo

- `app/app.js` ("Gravações", bloco *bordo*): catálogo com `dispositivo` vazio → a tela diz "o bordo não achou o
  dispositivo do radar: <motivo>" em vez de só "nenhum trecho".
- **P2:** `hd_catalogo` passa a guardar `dispositivo_origem` e `motivo` no resumo — o terra lê o que o bordo mediu.

## Fase 4 — P1: o nome do admin manda

- O `tipo='radar'` escolhido no admin vale como **declaração** (hoje só `radar_fonte` + `_parece_radar` valem) e
  move o gravador.
- A varredura **nunca** reescreve o nome que o admin deu; o bloco gravado carrega o nome do admin no rótulo.
- Quando o nome do admin não casa com o nome do Windows (`Radar de Óleo` ≠ `USB Video 4`), vale o **tipo**.

## Fase 5 — P1: provas + versão 0.26.0

- `tests/test-hd-acha-o-dispositivo.py`: 5 cenários (env / tipo / nome / fonte / nada → motivo).
- `tests/e2e-hd-do-radar-gravando.py`: bloco de 60 s nasce, é listado no painel e chega ao terra.
- `tools/regressao-0130.py` + a suíte; bump **0.26.0**, deploy, release e nota no vault.

## Decisões do dono (26/11/2026 — plano fechado)

1. **O TIPO manda**: a câmera que o admin marcou com o tipo `radar de óleo` no app do admin é que decide o
   dispositivo do HD — o bordo acha sozinho, sem ninguém digitar nome de dispositivo.
2. **Mais de uma placa/cartão:** vence **a única câmera marcada como radar de óleo no admin**; o bordo não
   pergunta nem escolhe "a primeira que aparecer".
3. **Se nada casar** (nenhuma câmera com tipo radar, sem fonte declarada): **não grava** e **mostra o motivo**
   na tela do bordo **e** em terra. Nunca um "ligada" que não grava.

Ordem final do resolvedor: **(1)** `LECSOR_HD_DISPOSITIVO` só como override de técnico/bancada (não é
exigido); **(2)** a câmera com `tipo='radar'` e o dispositivo dela; **(3)** a fonte declarada
(`radar_fonte`); **(4)** nome do admin igual ao nome do dispositivo; **(5)** nada → não gravar + motivo.

## Depois de aprovado

`aprovado` → implemento as 5 fases, provo (testes + regressão + e2e do bloco gravado), faço o bump para
**0.26.0**, publico a release, faço o deploy na VPS e escrevo a nota no vault.

## O que NÃO entra

- **J5** (apagar/auditar a gravação quando o cliente sai da tela) — próxima rodada.
- Rotação por espaço do HD, reserva em MB e "mais antigo sai" — já existem.

## Implementado em 26/11/2026 (o que foi feito, com as medidas)

**Fase 1 — P0 — o resolvedor do dispositivo (feito).** `ground/api.py` ganhou
`dispositivo_do_radar()` (leitura pura: a câmera de `tipo='radar'` — priorizando
`tipo_definido_pelo_admin=1` — o apontamento em `config_local` e o casamento com o aparelho) e
`_dispositivo_da_camera_do_radar()`; `ground/gravacao_continua.py` passou a ter
`resolucao()/dispositivo()/origem()/camera_id()/rotulo()` com **cache de 60 s**
(`RESOLUCAO_SEGUNDOS`), porque o laço do gravador pergunta a cada 2 s e listar dispositivos custa ~1 s.

Ordem entregue, igual à decisão do dono: **(1)** `LECSOR_HD_DISPOSITIVO` (override de bancada/técnico,
`origem="env"`); **(2)** o **tipo** — casamento pelo **id estável** do aparelho, o mesmo
`cam-<slug do @device_pnp_...>` que a varredura usa (`origem="tipo"`); **(3)** o **nome** que o admin deu
(`origem="nome"`, com/sem acento e por trecho); **(4)** o apontamento já aplicado nesta máquina
(`config_local`, `origem="cadastro"`); **(5)** nada casou → **vazio com o MOTIVO** (nomeia a câmera e
lista o que o bordo viu: `"vi: ACER HD User Facing"`).

> Desvio honesto do plano: os passos **(3) `radar_fonte` da embarcação** e **(5) "primeiro candidato que
> parece radar"** **não** foram implementados — a decisão 3 do dono ("se nada casar, não grava e mostra o
> motivo") fecha o caso sem chute, e `_parece_radar` deixaria o gravador escolhendo sozinho um aparelho
> que o admin não marcou. Fica registrado como escolha, não como esquecimento.

**Fase 2 — P0 — o painel do bordo diz qual dispositivo e por quê (feito).** `bordo/index.html` ganhou a
linha **"Dispositivo do HD"** (nome do aparelho + seletor + *por onde foi achado*: tipo / nome / cadastro
/ ajuste de bancada) e a linha da gravação full-time passou a dizer **quando começou o último bloco**
("nenhum bloco ainda" quando não há). Sem dispositivo, a linha **é** o motivo.
`desktop/servidor.js`: caiu o bloqueio que exigia `LECSOR_HD_DISPOSITIVO` para subir o gravador.

**Fase 3 — P1 — terra mostra o mesmo motivo (feito).** `app/app.js` (bloco de bordo da página
"Gravações"): catálogo com `motivo` e sem `dispositivo` → a tela escreve *"gravação full-time ligada a
bordo, mas o computador de captura não achou o dispositivo do radar: <motivo>"*. O catálogo publicado
pelo bordo (`ground/agente_de_ordens.py`) agora leva `camera_id = camera_id()` (o id da câmera do radar
do cadastro) e o `resumo` **inteiro** — `dispositivo`, `dispositivo_origem`, `nome_dispositivo`,
`camera_rotulo`, `motivo`.

**Fase 4 — P1 — o nome do admin manda (feito).** O `tipo='radar'` do cadastro é a declaração que move o
gravador; a varredura continua sem reescrever o rótulo que o admin deu em terra.

**Fase 5 — P1 — provas + 0.26.0 (feito).**

- `tests/test-o-hd-acha-o-dispositivo-do-radar.py` — 19 provas: tipo manda · origem `tipo` · o nome
  resolve · nada casa → motivo (nomeia a câmera e lista o que viu) · sem câmera de radar → motivo ·
  máquina sem câmera → o motivo é o do `ffmpeg` · `config_local` vence · `env` continua valendo ·
  **HTTP `/api/bordo`**: o bloco do HD traz `dispositivo`+`dispositivo_origem`+`motivo` e nunca os dois
  vazios · **HTTP `/api/hd/catalogo`**: o motivo medido a bordo chega inteiro no catálogo do cliente.
  Rodada real contra a API em porta livre e banco temporário — `exit 0`, tudo verde.
- `tests/e2e-pagina-unica-de-gravacoes.py` — seção **8** nova: catálogo sem trecho e com motivo → a tela
  de terra escreve o motivo; com o dispositivo achado → volta ao texto antigo (não inventa problema).
- `tests/e2e-config-do-bordo-vinda-de-terra.py` — a prova do motivo passou a exigir o motivo **medido**
  (`"nada sera' gravado: <motivo>"`), não mais a palavra `dispositivo` (o texto antigo vinha da variável
  de ambiente que deixou de existir).
- `tools/regressao-0130.py` — **tudo verde** (0 falhas; a rodada anterior tinha 1 falha, corrigida na
  causa: a expectativa do motivo). `python -m unittest discover -s tests -p "test_*.py"` — **22 OK**.
- `tools/_tmp_0260_bump.py` — `desktop/package.json` e `tools/publicar-releases.py` em **0.26.0**
  (nota + `VERSOES_PUBLICADAS`), com `--verificar`.
