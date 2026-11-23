# PC de captura: ativou a chave e pronto — sem login, varrendo e publicando (plano)

Estado: **aguardando "aprovado"** do dono. Nada implementado.

## O que o dono relatou (23/11/2026, verbatim)

> "inseri a chave de acesso no app no computador de captura, depois me pede email e senha, mas não aceita
> nenhum que já tenho. após o reconhecimento da licença não deveria precisar fazer mais nada no app de
> captura, ele já deveria fazer a varredura e enviar as informações, no lado terra, eu já deveria receber no
> painel admin as informações das câmeras e entradas de vídeo, finalizar as configurações e poder acessar
> pelo painel cliente"

## O que já está medido (não é opinião — foi lido no código ou medido na VPS)

| Fato | Onde foi verificado |
|---|---|
| O app **decide de onde vem a entrada** pelo estado da máquina: banco **local com usuários** → login **local**; banco local **vazio** e lado terra respondendo → login do **lado terra** | `desktop/main.js:185-200`, `desktop/configuracao.js:104-111` (`enderecoDaEntrada`) |
| O login do servidor **local** só aceita quem está no **cadastro desta máquina**: o e-mail é buscado em `usuarios` **local** e, se a senha é aceita pelo Supabase mas o e-mail não está no cadastro local, a resposta é **403 "esta conta nao esta cadastrada nesta instalacao: quem cadastra usuarios e' o administrador"** — é o sintoma "não aceita nenhum que já tenho" quando a entrada caiu no servidor local | `ground/api.py:3030`, `3041-3044`, `3060-3065` |
| O login do **lado terra** funciona: `admin@lecsor.test` → **200** com `papel: admin` | medido na VPS em 23/11/2026 |
| O **envio** (varredura + ordens + catálogo) **não depende de login**: quem faz é o `ground/agente_de_ordens.py`, subido pelo app, e ele só precisa da **embarcação** (que vem da **licença**, `desktop/servidor.js:110-113`) e do **token de ingestão** (que vem do `ambiente.json` do pacote) | `desktop/servidor.js:217-229`, `ground/agente_de_ordens.py` (usa só `Authorization: Bearer <token>`) |
| A varredura é **rota local** da máquina (`/api/varredura`) e o anúncio das câmeras ao lado terra é o `repasse.publicar_cadastro` (com o token) | `ground/api.py:54-58`, `references/ponte-tela-local-e-lado-terra.md` |
| A tela de captura roda **sem login**: o servidor local responde `/api/eu` com `local: true` e é esse campo que libera os controles de captura | `references/ponte-tela-local-e-lado-terra.md` |
| A sessão é **um cookie por host** (`sessao`): dois usuários no mesmo navegador/host = o segundo derruba o primeiro | `ground/api.py:3069`, `3152` |

**Conclusão do diagnóstico:** o produto faz o certo quando o app **não** cai no login local (aí a entrada é a
do lado terra e a senha do dono entra). O que produz a reclamação é a entrada ter caído no **cadastro local**
daquela máquina — e, mais fundo, o app **pedir login** num PC de captura, quando o desenho do dono
(19/11/2026: *"instalar o app… inserir a chave da licença"*) é **não pedir mais nada**.

## Fase 1 — o PC de captura é autônomo: chave, licença e mais nada (P0)

Dono, 23/11/2026 (D2): *"no pc de captura ninguém precisa abrir nada, tudo deve ser feito no admin e cliente,
o app de captura deve ser autônomo, faz as varreduras locais e fica verificando as flags de terra e enviando
as respostas e fazendo as atuações"*. Logo: **nenhuma tela de login** e **nenhuma tela de admin/cliente** no
PC de captura.

- **P0** — Com licença ativa, a **única** tela do app é o painel de bordo (estado da máquina), **sem login**:
  o app abre já em modo autônomo (mediamtx + api + agente de ordens + varredura + laço de flags).
  O login **não** é mais a porta de entrada na máquina de captura.
- **P0** — O app sobe o modo autônomo sozinho **ao abrir e no boot do Windows**, sem depender de ninguém
  entrar em tela nenhuma, e religa o que cair (o `subir()` já re-sobe até 3×; falta o boot e a ausência de
  dependência de sessão).
- **P0** — O painel de bordo mostra o que ficou pronto: embarcação da licença, **token do instalador presente
  ou ausente** (D1), agente no ar, última varredura, última publicação, última flag obedecida e saúde do
  bordo — o que hoje só existe em log. É leitura, não operação: ninguém configura nada por ali.
- **P0** — Se a máquina **já tem** cadastro local (instalação antiga), isso deixa de importar: o modo
  autônomo com licença vale igual; a tela só informa. Era esse caso que produzia o "não aceita nenhum que já
  tenho".
- **P1** — A tela da chave continua acessível **pelo próprio app** (trocar a chave quando o barco mudar), e
  a senha do banco local do PC de captura deixa de ser exigida para o app operar.

## Fase 2 — o bordo publica sozinho, e o admin vê (P0)

- **P0** — **Token de ingestão no PC de captura — DECIDIDO (D1, dono 23/11/2026): fica no instalador.**
  A licença traz a **embarcação**; o token continua vindo do `ambiente.json` do pacote e a ativação da chave
  passa a **só conferir se ele existe** (e a dizer isso na tela do bordo). O instalador de cada barco sai
  com o token dentro — logo, o build de release precisa levar o `ambiente.json` com o token da embarcação
  (conferir no `construir-instaladores.sh` e no `baixar-servidor.sh` o caso "pacote sem token").
- **P0** — A **varredura** e o **anúncio** das câmeras (`repasse.publicar_cadastro` → `/api/cameras/anuncio`)
  acontecem sozinhos depois da ativação, com **reenvio enquanto falhar**, e o resultado aparece **na tela** e
  em `/api/saude` (não só no log do repasse).
- **P0** — No **painel admin**, o barco recém-ativado aparece com as câmeras/entradas de vídeo anunciadas,
  **sem** ninguém cadastrar nada à mão.
- **P1** — O admin **finaliza a configuração** (alvo por câmera, ligar/desligar, teto de transmissão) e a
  tela do cliente já mostra o que foi publicado.

## Fase 3 — provas (P0/P1)

- **P0** — Prova de ponta a ponta nova (bancada): instalar/abrir o app do PC de captura com licença ativa →
  **nenhum login** → varredura → anúncio chega ao lado terra → o admin vê as câmeras → configura o alvo →
  o cliente abre a tela dele e vê o vídeo. Entra no `tools/smoke/` como jornada nova (J11) e roda no
  veredito com número (sem medida = "NÃO MEDIDA", nunca "OK").
- **P0** — Regressão da área: `tools/regressao-0100.py` (as 20 provas), `tests/test-licenca-do-bordo.py`,
  `tests/test_captura_liberada_no_app.py`, `tests/e2e-varredura-do-bordo.py`.
- **P1** — Nota no vault + changelog; build/release (patch) com o conserto.

## Decisões do dono (fechadas em 23/11/2026)

- **D1 = o token continua no instalador.**
- **D2 = no PC de captura ninguém abre nada:** admin e cliente operam no lado terra; o app de captura é
  autônomo — varre local, olha as flags do terra, envia as respostas e faz as atuações.
- Não sobrou pergunta aberta. Plano pronto para "aprovado".

## O que NÃO vou fazer sem "aprovado"

Nada de código: este plano só descreve. A correção de verdade é do app do bordo (`desktop/main.js`,
`desktop/servidor.js`, `admin/`, `licenca/`) + o lado terra (`ground/api.py`), com build e release novos —
e o app instalado no barco **não se atualiza sozinho**.
