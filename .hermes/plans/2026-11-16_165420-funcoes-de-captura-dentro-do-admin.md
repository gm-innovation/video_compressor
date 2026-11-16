# Funções de captura DENTRO do Admin (o Admin não vira o app de captura) — plano

**Status:** aprovado pelo dono ("prossiga", 16/11/2026) e **implementado** — fases 1, 2 e 3 (P0).
Ver "Estado da implementacao" no fim.

## Pedido do dono (16/11/2026, verbatim)

> "sim, mas deve liberar as funções de captura, não mudar para o app de captura. não existe 'as duas únicas
> opções...' estamos desenvolvendo o produto, nós criamos as opções"

Contexto do dono (mesmo dia): "eu utilizo o admin pra cadastrar e configurar as câmeras, a captura vai ser
utilizado por técnicos a bordo, ninguém acessa o meu admin". O que aconteceu na prática: no app **Admin**
já instalado, o item *Servidor local → Papel desta instalação → "Usar como PC de captura (esta máquina)"*
trocou a base para o servidor local e o app **perdeu o login** do lado terra, caindo na tela "LECSOR ·
primeiro acesso" (`admin/index.html:37`) porque o banco **local** desta máquina nasce vazio
(`admin/admin.js:17`).

## Regra de ouro deste plano

1. O **Admin continua Admin**: mesma janela, mesmo login/permissões do lado terra, mesmas telas de cadastro
   e configuração de câmera. Nada de "trocar de app" nem de "primeiro acesso" local para usar captura.
2. As **funções de captura** (listar as câmeras/webcam **desta** máquina, escolher fonte e qualidade,
   comprimir e **repassar** o fluxo para o lado terra) passam a existir **no próprio Admin**.
3. O pacote **LECSOR Captura** (hoje `superficie=bancada`, `papel=captura`) **continua existindo** para os
   técnicos a bordo — este plano não o altera, só deixa de ser o único lugar com captura.
4. As opções de menu/estado do produto **nós** definimos: as duas atuais ("usar como PC de captura" /
   "usar como lado terra") deixam de ser as únicas e deixam de ser destrutivas para a sessão.

## Estado verificado (16/11/2026, por leitura de código, não por suposição)

| Fato | Onde |
|---|---|
| O pacote do Admin já leva o servidor local inteiro, `portal/`, `admin/` e `ffmpeg/ffprobe` | `desktop/dist/admin/win-unpacked/resources/{servidor,ffmpeg}` (verificado) |
| Pacote Admin 0.4.1: `superficie=admin`, `papel=terra` → fábrica aponta para o lado terra e **não** sobe servidor local | `app.asar/package.json` + `papeis.json` (lido) |
| Pacote Captura 0.4.1: `superficie=bancada`, `papel=captura` → `base=127.0.0.1:8765` + `servidorLocal.ligado=true` | idem |
| "Enviar vídeo" do Admin pede os dispositivos para `location.origin` | `admin/admin.js:1049` (`fetch('/api/dispositivos')`) |
| A API decide quem enxerga a máquina pelo IP da chamada: `127.0.0.1`/`::1` = "esta máquina" | `ground/api.py:583` `_local()`, `:1019-1026` |
| **A API não manda nenhum cabeçalho CORS** (grep por `Access-Control-Allow-Origin`: nenhuma ocorrência) | `ground/api.py` |
| O item de papel troca `base` e liga o servidor local, **sem** preservar a sessão do lado terra | `desktop/main.js:274-286` |
| `config.json` de fábrica dos 4 pacotes: `base=http://187.127.60.250:8085`, `destinoSrt=187.127.60.250:8890`, `servidorLocal.ligado=false` | `app.asar/config.json` (lido) |
| Banco **local** de uma instalação nova não tem usuário nenhum → login normal nunca funcionaria | `admin/admin.js:17`; API só deixa criar o primeiro acesso na própria máquina (`ground/api.py:1198`) |

## Desenho proposto (duas opções técnicas para a Fase 1 — escolher na revisão)

**(a) O Admin fala com os dois servidores, cada um para o que é seu.** A janela continua carregada do lado
terra (`base=http://187.127.60.250:8085`, login e permissões intactos) e as chamadas de captura
(`/api/dispositivos`, envio, repasse) vão para `http://127.0.0.1:8765`. Para isso o servidor local precisa
responder CORS **restrito** (origem do lado terra do próprio cliente + `127.0.0.1`), já que hoje não manda
cabeçalho nenhum.

**(b) Ponte no aplicativo.** O `main.js`/`preload.js` (que já é nosso) reescreve só as rotas de captura para
o loopback — nenhuma alteração de CORS, mas mexe em `preload.js` e no caminho das chamadas.

Recomendação: **(a)**, porque mantém a regra do produto ("credencial e chave nunca no cliente") e a
permissão de captura continua sendo decidida pelo `_local()` do servidor local; o CORS fica fechado nas
origens do próprio lado terra.

## Fases (com prioridade marcada)

### Fase 1 — P0 — O Admin enxerga as câmeras desta máquina
- Escolher (a) ou (b) acima; implementar o mínimo: a tela "Enviar vídeo" do Admin, aberta no lado terra,
  lista o dispositivo desta máquina e deixa escolher a fonte.
- **Prova:** no Admin apontado para o lado terra, o seletor mostra a webcam desta máquina e o
  `pedido_de` deixa de ser `outra_maquina` (`ground/api.py:1026`).

### Fase 2 — P0 — Menu que libera a captura sem trocar app nem pedir cadastro
- O menu "Servidor local" passa a ter **"Liberar as funções de captura nesta máquina"**: sobe o servidor
  local, mantém `base` no lado terra, **não** cria `ajuste_manual`, **não** troca a superfície e **não**
  abre tela de primeiro acesso.
- Os itens atuais continuam para quem realmente quer o outro papel (técnico a bordo / lado terra), agora
  com aviso claro do que muda.
- **Prova:** Admin logado no lado terra passa a listar câmeras e a transmitir; nenhuma tela de cadastro
  aparece; `config.base` continua o lado terra e `servidorLocal.ligado=true`.

### Fase 3 — P0 — Uma tela "Enviar vídeo" só, com a qualidade por câmera
- O "Enviar vídeo" do Admin recebe as mesmas funções do pacote de captura (fonte + alvo/qualidade por
  câmera da lista fechada 1500k…300k) e a tela de teste atual ganha outro nome (**"Teste de vídeo
  (bancada)"**) para acabar com a confusão de dois lugares com o mesmo nome.
- **Prova:** a tela do Admin mostra o mesmo seletor de qualidade por câmera da captura; nenhuma tela do
  produto se chama "Enviar vídeo" sendo outra coisa.

### Fase 4 — P1 — Repasse desta máquina para o lado terra pelo Admin
- Quem captura pelo Admin repassa o fluxo para `destinoSrt` (fábrica `187.127.60.250:8890`) e o lado terra
  mede o que chegou (kbps/SSIM), igual ao caminho de hoje do pacote de captura.
- **Prova:** fluxo iniciado no Admin aparece no lado terra com kbps medido e o alvo escolhido por câmera.

### Fase 5 — P2 — Instalador e teste de regressão
- O instalador do Admin nasce com o servidor local pronto e **sem** exigir cadastro local; o papel de
  fábrica continua `terra` (ninguém é empurrado para captura).
- Suite: acrescentar as verificações das Fases 1–4 ao `tests/suite.py` e ao plug-and-play.
- **Prova:** instalação limpa → Admin abre logado no lado terra, lista as câmeras da máquina e transmite.

## Riscos e travas

- **CORS aberto demais é proibido:** liberar só as origens do próprio lado terra do cliente e `127.0.0.1`.
- **A porta do servidor local não vai para a rede:** `LECSOR_BIND` continua `127.0.0.1` (o `_local()` decide
  por IP; expor a porta daria captura sem login a quem estivesse na rede).
- **Duas identidades no mesmo app:** a sessão do lado terra e o servidor local não podem se misturar; a
  permissão de captura continua sendo "esta máquina" (`_local()`), não o papel do usuário do lado terra.
- **Não reabrir** o caminho "primeiro acesso" local como forma de resolver captura (foi o que o dono
  apontou como errado).

## Incógnitas declaradas (não medidas)

- Se o navegador embutido (Electron) aceita a chamada cross-origin do lado terra para o loopback **mesmo**
  com o cabeçalho CORS — só o teste da Fase 1 responde (se recusar, cai na opção (b), a ponte no app).
- Se `will-navigate`/`sandbox` (`desktop/main.js:159-172`) interfere nas chamadas de captura vindas da
  página do lado terra.

## Estado da implementacao (16/11/2026)

Opcao escolhida para a Fase 1: **(a) + aviso do aplicativo** — o servidor local responde CORS restrito
nas rotas de captura E o aplicativo diz a interface para onde ir (`preload.js` -> `enderecoDaCaptura`,
lido de `LECSOR_CAPTURA_BASE`), porque a pagina vem do lado terra e a chamada vai para o loopback.

| Fase | P | O que ficou | Onde |
|---|---|---|---|
| 1 | P0 | CORS **restrito**: so' nas rotas de captura e so' para as origens declaradas (`LECSOR_CORS_ORIGENS`; padrao = lado terra do produto + loopback). Origem nao declarada fica sem cabecalho; rota de cadastro/login nunca ganha CORS; pre-voo fora das rotas de captura responde 405 | `ground/api.py` (`ROTAS_CAPTURA`, `origens_captura()`, `eh_rota_de_captura()`, `_cors()`, `do_OPTIONS()`) |
| 1 | P0 | A interface passa a saber onde esta a captura desta maquina e roteia **so'** as rotas de captura (dispositivos, ingestao, compressao, envios) para o servidor local; cadastro/login/cameras/usuarios continuam no lado terra, com a mesma sessao | `desktop/preload.js`, `admin/admin.js` (`BASE_CAPTURA`, `urlDeCaptura()`, `fetchCaptura()`) |
| 2 | P0 | Menu "Liberar as funcoes de captura nesta maquina (sem trocar de app)": sobe o servidor local, **nao** troca a base, **nao** cria usuario local, **nao** abre "primeiro acesso". Desligar para o servidor local quando o papel nao e' o PC de captura | `desktop/main.js`, `desktop/configuracao.js` (`capturaLocal`) |
| 3 | P0 | A tela "Enviar video" do Admin ganhou a **qualidade por camera** (lista fechada 1500k…300k, vale no ar) e o painel de teste passou a se chamar **"Teste de video (bancada)"** | `admin/admin.js` |
| 4 | P1 | **PENDENTE** — repasse medido no lado terra a partir do Admin | — |
| 5 | P2 | **PENDENTE** — suite/plug-and-play com as fases 1–3 (parcialmente coberto por `tests/test_captura_no_admin.py`) | — |

### Prova (executada)

`python tests/test_captura_no_admin.py` -> **CAPTURA_NO_ADMIN_OK** (20 verificacoes):
- servidor de verdade na porta livre respondendo CORS a origem declarada, sem CORS a origem nao
  declarada, sem CORS em rota de cadastro, 405 no pre-voo fora das rotas de captura;
- `resolver()` do `configuracao.js`: com `capturaLocal` ligado a base continua o lado terra (as telas
  nao mudam), sem `capturaLocal` o comportamento antigo fica igual, e o pacote do tecnico a bordo
  continua apontando para o servidor local;
- rotas de captura x rotas de cadastro e a presenca do menu, do preload e do roteamento na tela.

Regressao: `tests/test-config-endereco.py`, `tests/test-alvo-e-perfil-por-camera.py`,
`tests/test-selecao-de-qualidade.py` e `tests/test-instalador-plug-and-play.py` — 2 expectativas do
plug-and-play estavam **desatualizadas desde a 0.4.1** (`construir "LECSOR Captura" admin ...`, quando o
pacote do PC de captura passou a nascer na superficie `bancada`); corrigidas no proprio teste.

### Nao feito / declarado

- `/api/cameras/<id>/ligar|desligar` continua no lado terra (e' cadastro + operacao da camera); se o
  dono quiser ligar/desligar camera pela tela do Admin com a captura liberada, entra na Fase 4.
- O navegador embutido aceitar a chamada cross-origin so' se prova na maquina do dono (instalador novo).
- Fase 4 (repasse medido) e Fase 5 (suite) pendentes.
