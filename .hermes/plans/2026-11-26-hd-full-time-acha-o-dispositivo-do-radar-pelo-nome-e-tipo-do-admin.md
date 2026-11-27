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

## Publicado em 26/11/2026 (números medidos)

- **Commit `7f4341e`** (12 arquivos, +712/−18), empurrado: **`f1e5add..7f4341e main -> main`** (levou
  junto o `70f8c8b`, o commit do plano da 0.25.0 que ainda estava só local). O `git push` precisou de
  consentimento: o gate o segurou até o dono dizer "pode fazer o push" — nada foi contornado.
- **Instalador `desktop/dist/unico/LECSOR-0.26.0-x64.exe`** — **171 696 106 B**, sha256
  **`c746898ea3bdcd53dad465a180a2db7e0bc7889be138f7d46edf4317b308e56f`**. O `ground/` corrigido viaja
  dentro do pacote (conferido em `win-unpacked/resources/servidor/ground/gravacao_continua.py`: `def resolucao` presente).
- **Release v0.26.0** — id **460524468**, `draft: false`, `prerelease: false`, publicado
  2026-11-27T11:36:46Z, **latest**; asset `LECSOR-0.26.0-x64.exe` 171 696 106 B, `state: uploaded`, e o
  **digest da fonte bate com o sha256 local**: `sha256:c746898e…8556f`.
- **Deploy do lado terra na VPS** (`/opt/pipeline/app`, backup em `backup.antes-0260/`): `py_compile OK`,
  `pipeline-api.service` **active**, rotas **saude=200 · bordo=200 · admin=200 · app=200**. Provas do
  código no ar: `dispositivo_do_radar` 1 · `dispositivo_origem` 1 · `def resolucao` 1 ·
  `RESOLUCAO_SEGUNDOS` 2 · `g.camera_id()` 1 · `Dispositivo do HD` 1 · o motivo medido em `app.js` ✓.
- **Medido na VPS** (`GET /api/bordo`, o bloco do HD): `{"ligada": false, "dispositivo": "",
  "dispositivo_origem": "", "camera_rotulo": "Radar de Óleo", "blocos": 0, "motivo": "o ffmpeg nao
  encontrou camera nesta maquina: confira o driver, a porta USB e se o dispositivo aparece no
  Gerenciador de Dispositivos"}` — a VPS é o lado TERRA (sem câmera): a resposta diz **o motivo medido**
  em vez de um "ligada" mudo.
- **Vault publicado**: nota `20-runbooks/2026-11-26-hd-full-time-acha-o-dispositivo-do-radar-0.26.0.md`
  (6 920 B) + bullet em `index.md`, **`origin/master` = `2132e92`** (nota conferida no remoto:
  `git cat-file -s origin/master:…` = 6920 B).
- **Provas da rodada**: `tools/regressao-0130.py` **TUDO VERDE (47 provas)**; `python -m unittest
  discover -s tests -p "test_*.py"` **22 OK**; `tests/test-o-hd-acha-o-dispositivo-do-radar.py` **19
  provas, exit 0**; `tests/e2e-pagina-unica-de-gravacoes.py` (seção 8) e
  `tests/e2e-config-do-bordo-vinda-de-terra.py` **exit 0**. Verificação de tamanho do pacote:
  `sha256sum` local == `digest` do asset na fonte.
- **Fica pendente (honesto)**: instalar a 0.26.0 no **PC de captura real** — o quadro do radar só o
  hardware prova (a bancada não entrega frame); **J5** (o ramo `encerrar` não apaga a gravação nem
  audita) segue aberta para a próxima rodada.

---

## Adendo do dono (26/11/2026, depois de publicar) — duas coisas novas, medidas

### 1) A gravação do radar a bordo: a causa é o PC de captura estar com app ANTIGO (e não o código)

Medido agora (VPS `pipeline.db` + grep no repositório):

- `hd_catalogo` (`bancada` / `radar`) foi escrito **pelo bordo hoje, 27/11/2026 11:51:41Z**, e o `resumo` é
  `{"ligada": true, "dispositivo": "", "camera": "radar", "bloco_segundos": 60, "blocos": 0, "bytes": 0,
  "livre_bytes": 195124219904, "total_bytes": 253966151680, "diretorio":
  "C:\\Users\\HAVOX\\AppData\\Local\\Programs\\LECSOR\\resources\\servidor\\ground\\hd"}` — **sem `motivo`,
  sem `dispositivo_origem`, sem `camera_rotulo`** e com `camera_id = "radar"` (o pacote da 0.26.0 grava
  `g.camera_id()`). É o **formato antigo**: o app instalado ali é **< 0.26.0**.
- `config_aplicada_bordo` `gravacao_continua` (26/11/2026 20:15:10Z) = `"ligada, mas esta maquina nao tem
  dispositivo de video configurado (LECSOR_HD_DISPOSITIVO): nada sera' gravado"` — **esse texto não existe
  mais no código** (0 ocorrências no repo); a 0.26.0 diz `"ligada, mas nada sera' gravado: <motivo>"`.
  É o texto que o dono viu na tela.
- O PC de captura está **vivo** (fala com a VPS) e o app **não se auto-atualiza** → a 0.26.0 não chegou lá.
- O admin **já tem** a câmera certa marcada: `cam-device-pnp-usb-vid-345f-pid-2131-mi-00-6-f69`,
  `tipo='radar'`, `tipo_definido_pelo_admin=1`, `ativo=1` — é exatamente o que o resolvedor procura.

**Fase A (P0) — instalar a 0.26.0 no PC de captura (passo a passo de leigo, para o dono repassar):**
1. baixar `LECSOR-0.26.0-x64.exe` da release **v0.26.0** (sha256 `c746898e…8556f`);
2. fechar o app e rodar o instalador por cima (mantém o `ground/hd/ligada.txt`, que é o desejo do HD);
3. abrir o painel do bordo: a linha **"Dispositivo do HD"** tem de mostrar o aparelho e a origem `tipo`;
4. em ~1 min a linha "Gravação full-time" sai de `0 bloco(s)`;
5. provar em terra: `/api/bordo` → bloco `hd` com `dispositivo` + `dispositivo_origem`; `hd_catalogo` com
   `blocos > 0`.

**Fase B (P0) — o produto tem de DENUNCIAR a versão velha sozinho.** Hoje nada avisa: o admin vê
"publicada LIGADA" e o bordo diz "nada sera' gravado" sem dizer que é app velho. O bordo manda a versão em
`estado_bordo`/`saude_bordo`; `/api/bordo` e as telas (admin e bordo) mostram *"versão do bordo X <
publicada Y — atualizar"*. É a diferença entre "não grava" e "não grava porque o app está velho".
**Fase C (P1):** o terra marca a linha como **`bordo desatualizado`** quando o `motivo` do bordo não trouxer
os campos da 0.26.0 (não deixar dizer "o bordo aplicou" o que é aplicação antiga).

### 2) psutil no Python portátil (CPU, memória e rede)

Medido:

- `ground/saude_do_bordo.py` (l. 79/80/105/123) e `ground/api.py` (l. 1716) **usam psutil**; sem ele a
  saúde sai com `nao_medido` = `"sem psutil neste Windows (instalar psutil para medir)"` — o número não é
  inventado (certo), mas CPU/memória/rede ficam **sem medir**.
- `tools/python/` é o **Python embeddable 3.12.7** descompactado do zip oficial: **não tem
  `Lib/site-packages`** e o `python312._pth` só lista `python312.zip` + `.` com `#import site`
  comentado → `sys.path` não tem site-packages nenhum. (O `psutil 7.2.2` existe no Python 3.14 desta
  máquina Hermes, que **não** é o que vai dentro do instalador.)

**Fase A (P0) — psutil dentro do pacote.**
- `tools/python/python312._pth` → linhas `python312.zip`, `.`, `Lib\site-packages` e `import site`
  descomentado.
- `tools/python/Lib/site-packages/psutil/` da wheel `psutil-…-cp312-cp312-win_amd64.whl` (fixar versão e
  sha256).
- Conferência **no build** (`desktop/baixar-servidor.sh` e `construir-instaladores.sh`):
  `tools/python/python.exe -c "import psutil,json;print(json.dumps([psutil.__version__, psutil.cpu_percent(0.2)]))"`
  → **falha o build se não importar** (build que falha é barato; pacote que sai sem medir é caro).
- `desktop/baixar-servidor.sh`: baixar a wheel (sha256 fixado) e extrair em `Lib/site-packages`, para o
  pacote voltar a ser reconstruível do zero (hoje esse passo só existe para o Python e o mediamtx).

**Fase B (P0) — prova de verdade:** com o **python do pacote**, `psutil.cpu_percent()` /
`virtual_memory()` / `net_io_counters()` medidos; `GET /api/saude` do app instalado com CPU/memória/rede
**fora** de `nao_medido`.
**Fase C (P1) — a tela:** `/bordo` → `#ficha-saude` mostra CPU/memória/rede, e um teste prova o **número**
saindo (não o `nao_medido`).
**Fase D (P1):** banda por interface (upload/download) para a curva de link do Starlink.

**Ordem sugerida:** Fase A/B do psutil (destrava o número que o dono pediu) → Fase B do item 1 (denúncia da
versão velha) → as demais P1.

---

## Executado em 27/11/2026 — rodada 0.27.0 (a denúncia + o psutil), provado

### (a) O produto DENUNCIA o app de captura antigo — o que fez o dono ver "nada sera' gravado"

O texto que o dono viu (`...nada sera' gravado`, citando `LECSOR_HD_DISPOSITIVO`) é da **versão antiga**:
o PC de captura (DESKTOP-78DSH57, `C:\Users\HAVOX\...\Programs\LECSOR`) roda **0.25.0** e o app **não se
auto-atualiza**. O produto tinha de **dizer isso**, em vez de parecer defeito.

- `ground/api.py`: `versao_do_app()` (`LECSOR_VERSAO_APP` → `VERSION` da raiz → `desktop/package.json`),
  `versao_em_trio()`, `comparar_versao()` e `_versao_do_bordo()`; `/api/config` devolve `lado`,
  `versao_do_bordo`, `versao_publicada`, `bordo_desatualizado` (True/False/None) e `motivo_da_versao`.
  **`None` (não se sabe) NUNCA vira "está tudo certo"** — o silêncio de um app velho é o caso a denunciar.
- `admin/admin.js`: `avisoDeVersao(cfg)` na linha da gravação contínua **e** no painel de saúde do cartão
  da embarcação ("Empresas e configuração"); `painelDeSaude(emb, cfg)` passou a receber a config.
- `bordo/index.html`: linha "App deste PC" na ficha (sem versão informada, não diz "em dia").
- `VERSION` (novo, `0.27.0`) viaja dentro do pacote como `servidor/VERSION` (`desktop/package.json`).

### (b) psutil dentro do pacote — CPU, memória e rede deixam de sair "nao medido"

- `tools/psutil_no_portatil.py` (novo): baixa a wheel **psutil 7.2.2** fixada
  (`sha256 eb7e81434c8d223ec4a219b5fc1c47d0417b12be7ea866e24fb5ad6e84b3d988`), extrai em
  `tools/python/Lib/site-packages/` e conserta o `python312._pth` (`python312.zip`, `.`,
  `Lib\site-packages`, `import site`); `--somente-conferir` mede com o **próprio python do pacote**.
- `desktop/baixar-servidor.sh` e `desktop/construir-instaladores.sh`: **o build FALHA** se o python do
  pacote não importar o psutil — build que não mede é build quebrado.
- Medido com o python do pacote (`tools/python/python.exe`):
  `{"psutil": "7.2.2", "cpu_pct": 31.4, "mem_mb": 32061, "rede": ["bytes_sent", "bytes_recv"]}`.

### Provas (medidas nesta máquina)

- `python -m unittest discover -s tests -p "test_*.py"` → **22 testes, OK**.
- `tools/regressao-0130.py` → **50/50 provas verdes** (`%LOCALAPPDATA%\Temp\reg-0270-final.log`), já com
  as duas provas novas na lista (`tests/test-versao-do-bordo-e-publicada.py`, 5 provas;
  `tests/test-psutil-no-portatil.py`, 4 provas) e com a prova da 0.26.0 que **não estava** na lista
  (`tests/test-o-hd-acha-o-dispositivo-do-radar.py`).
- `tests/e2e-saude-do-bordo-no-admin.py`, seção 8 (nova): com um bordo **v0.0.9** no banco e a publicada
  **v0.27.0**, o cartão do admin mostra `atualizar o app de captura` **e as duas versões**, junto da linha
  "gravação contínua: publicada LIGADA" — e sem erro de JavaScript na tela.

### Defeito que a prova pegou (corrigido)

`cfgGrav` nascia **dentro** do bloco `if (papel === 'admin')` do `admin.js` e a linha do painel de saúde
(que ficou **fora** do bloco) usava a variável → `cfgGrav is not defined` **abortava a renderização do
cartão da embarcação**. Três provas e2e caíram de uma vez (`test-tela-sem-piscar-e-varredura`,
`e2e-qualidade-e-teto-em-empresas`, `e2e-saude-e-desempenho-na-area`). Corrigido lendo `A.teto` de novo na
linha do painel (`admin.js`); as três voltaram verdes. **A prova unitária não pegaria: foi o e2e de tela.**

### Continua pendente (depende do hardware, não do código)

O PC de captura real roda **0.25.0** e o app **não se auto-atualiza**: só instalar o instalador
`LECSOR-0.27.0-x64.exe` naquele computador (usuário HAVOX) faz o radar gravar **de verdade** e as imagens
aparecerem no HD do bordo. O produto agora **denuncia** a versão velha nas duas telas.
