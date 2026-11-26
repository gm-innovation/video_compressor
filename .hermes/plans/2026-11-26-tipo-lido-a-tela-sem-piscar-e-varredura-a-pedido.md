# Plano — o tipo da câmera volta a aparecer, a tela para de piscar e a varredura vira um botão

**Pedido do dono (26/11/2026, com dois prints):**

> "eu aplico novo tipo à câmera, mas não está persistindo"
> "quando a página atualiza, parece que remonta toda a página, isso é horrível, eu estou fazendo algo e do
> nada a página 'pisca' e eu perco o que estou fazendo"
> "nesta tela preciso também de um botão para refazer varredura, para que caso tenha sido removida uma
> câmera por engano, ou não estão aparecendo câmeras novas, o app de captura precisa refazer a varredura das
> câmeras, mas apenas inclui as que não estão aparecendo, não remonta tudo pra não perder as configurações
> já feitas"

Estado: **APROVADO pelo dono (26/11/2026, "aprovado") e IMPLEMENTADO — entra como 0.22.0.**

Provas da rodada (todas em `tools/regressao-0130.py`):

| prova | o que mede | resultado |
|---|---|---|
| `tests/test-tipo-lido-do-banco.py` | o tipo aplicado pelo admin volta IGUAL em `/api/empresas`; `radar`/`flir`; fora da lista é recusado | **exit 0** |
| `tests/test-varredura-a-pedido.py` | `varrer` é da embarcação; cada pedido = versão nova; mantém `alvo`/`ativo`/`rotulo`; câmera que sumiu NÃO é apagada; idempotente | **exit 0** |
| `tests/test-tela-sem-piscar-e-varredura.py` | navegador de verdade: a ação refaz só o cartão, o timer de 15 s NÃO repinta (2 ciclos = 40 s), o botão publica o pedido e pedir de novo gera versão nova | **exit 0** (14 checagens) |
| `tests/e2e-admin-unificado.py` | a tela do admin inteira segue funcionando | **rc=0** |
| `tools/regressao-0130.py` | a bateria curada (39 provas antes; **42** com as 3 novas) | **TUDO VERDE (42 provas)** |
| `python -m unittest discover` | as provas de unidade | **22 OK** |

Desvio do plano (com motivo): o ramo do bordo ficou em `aplicar_config_local` (`ground/api.py`) — e não
dentro de `agente_de_ordens.aplicar_config` — porque é a MESMA rota que o agente chama (`POST
/api/config/aplicar`), a validação fica num lugar só e o agente só precisou de uma folga de tempo (90 s,
porque a varredura roda `ffmpeg` de verdade e não cabia nos 40 s). O resto do plano foi seguido.

---

## O que foi MEDIDO (não é leitura de código; é bancada)

### Queixa 1 — "aplico o tipo e não persiste": **a gravação está certa, a LEITURA mente**

Medido na bancada (porta 8771, `tools/_medir_tipo_persiste.py`, 26/11/2026):

| passo | resultado |
|---|---|
| `POST /api/cameras/cam-01-demo/editar` `{"tipo":"radar"}` | **200** `{"ok":true,"id":"cam-01-demo","mudou":["tipo"]}` |
| banco depois (`SELECT id,rotulo,tipo,tipo_definido_pelo_admin`) | `('cam-01-demo', 'PSV (demo) — câmera 1', 'radar', 1)` ✅ gravou |
| `GET /api/cameras` (o outro endpoint) | `('cam-01-demo', 'PSV (demo) — câmera 1', 'radar')` ✅ certo |
| **`GET /api/empresas`** — a árvore que a tela "Empresas e configuração" desenha | `(..., 'cam-01-demo', 'PSV (demo) — câmera 1', 'camera')` ❌ **volta "camera"** |

O tipo fica gravado; **a tela é que lê errado**:

- `arvore_do_painel` monta o `SELECT` **sem a coluna `tipo`** (`ground/api.py:1137-1138`:
  `SELECT id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo FROM cameras`).
- Como a chave não vem, `tipo_da_camera` (`ground/api.py:468-492`) cai no **fallback pelo NOME**
  ("id/rotulo/fluxo_id/local/alvo" dizendo "radar" ou "flir") e devolve `camera`.
- O cartão faz `tipo.value = c.tipo` (`admin/admin.js:3045`) → repinta **"câmera comum"**.
- O botão parece não fazer nada; na verdade fez e a lista desfez (o print mostra os dois: o recado verde
  "tipo gravado: radar" **e** os quatro cartões em "câmera comum").

Por que passou na 0.19.0: o teste do observador mede `pode_o_observador_ver`, que recebe a linha crua
(`SELECT *`) — quem decide o que o observador vê está certo; quem ficou errado foi só a árvore da tela.

### Queixa 2 — "a página pisca e eu perco o que estou fazendo": mecanismo provado, gatilho **não** reproduzido aqui

- O auto-refresh de **15 s** (`admin/admin.js:103`) chama `atualizar()`, que compara a "impressão digital"
  de 9 payloads (`assinaturaTelas`, `admin.js:176-182`) e, se **qualquer** campo mudar, chama `desenhar()`
  (`admin.js:164`) — que **reconstrói a tela inteira**.
- Toda ação do usuário também remonta a tela: `aplicar tipo`, `aplicar qualidade`, `salvar nome`,
  `publicar teto`, `remover` fazem `await atualizar()` → `desenhar()` (`admin.js:3048-3069`, `3021-3026`).
- O freio que existe (`digitandoNaTela()`, `admin.js:106-109`) só vale **enquanto o foco está** num
  INPUT/SELECT; depois de clicar num botão o foco saiu do campo e o freio não pega.
- **Medição honesta:** `tools/_medir_pisca.py` reproduz a assinatura (os mesmos 9 payloads, os mesmos
  campos de ruído) e compara duas leituras com 20 s de intervalo. Resultado na bancada:
  **"NÃO reproduziu: nada que a assinatura olha mudou em 20s"** — a bancada não tem bordo publicando
  saúde/licença nem transmissão no ar. O gatilho que dispara na casa do cliente **não foi reproduzido
  aqui**; o que está provado é o mecanismo (qualquer mudança em qualquer um dos 9 payloads, ou o próprio
  clique, remonta a tela toda).

### Pedido 3 — "botão para refazer varredura": a varredura já é o que ele pede; falta o botão

A varredura já existe (`ground/varredura_do_bordo.py:78 varrer()`) e já faz **exatamente** o que o dono
descreve — não remonta o cadastro:

- o id da câmera nasce do dispositivo (`_id_da_camera`), então re-varrer **não duplica**;
- câmera que já existe: **só o rótulo** pode acompanhar o dispositivo, e **nem isso** quando o admin já
  nomeou (`config_local`) — `varredura_do_bordo.py:155-179`: "`alvo`, `ativo` e a transmissão ficam como o
  admin deixou: a varredura nao briga com a configuracao";
- **não apaga** câmera que sumiu (a lista é `cadastradas` + `atualizadas`, nunca `DELETE`/`ativo=0`);
- radar tem regra própria (casa com a fonte declarada da embarcação, `:125-136`) e não vira câmera.

O que falta é o **gatilho pelo admin**. Hoje a rota `POST /api/varredura` (`ground/api.py:4526`) só roda
**na própria máquina de captura** (loopback / admin), e o painel local do bordo tem o botão
(`bordo/index.html:213`). O terra **não pode** chamar o bordo (regra do dono: "não podemos contar que o
computador de captura a bordo terá porta aberta"; o terra nunca abre conexão para o bordo) — logo o pedido
tem de viajar pela **configuração publicada**, que o bordo já lê
(`ground/agente_de_ordens.py:465 ler_config` / `:502 aplicar_config`).

---

## Fases

### Fase 1 — o tipo volta a ser lido (P0)

- **P0** `arvore_do_painel`: incluir `tipo` no `SELECT ... FROM cameras` (`ground/api.py:1137-1138`). O
  fallback pelo nome em `tipo_da_camera` **fica** (linha antiga sem a coluna continua valendo), só deixa de
  ser usado por falta de coluna.
- **P0** prova de servidor **nova** `tests/test-tipo-lido-do-banco.py`: grava `tipo='radar'` +
  `tipo_definido_pelo_admin=1` no banco e exige `radar` nos **dois** caminhos — `/api/cameras` **e**
  `/api/empresas` (o segundo é o que hoje devolve `camera`).
- **P1** prova de tela: no cartão da câmera, escolher "radar de óleo" → "aplicar tipo" → o `select` do cartão
  **continua** em "radar de óleo" depois do repaint (hoje volta para "câmera comum").
- **P1** cobrir `flir` e o caso de valor fora da lista (o cartão mostra "(fora da lista)").
- **P2** conferir que o `SELECT` novo não mexeu em nada mais (`ORDER BY rotulo`, contagem de câmeras por
  embarcação, `resumo.achadas_pela_varredura`).

### Fase 2 — a tela para de piscar (P0)

- **P0** o auto-refresh **não repinta tela de formulário**: `desenhar()` deixa de ser chamado pelo timer
  quando a tela atual é de configuração (`empresas`, `config`, `hd`, `envios`); o timer atualiza só o
  rótulo "atualizado HH:MM:SS" (e guarda o que leu para o próximo desenho explícito).
- **P0** ação do usuário **não remonta a tela**: "aplicar tipo", "aplicar qualidade", "salvar nome",
  "publicar teto" e "remover" atualizam **só o cartão afetado** em vez de chamar `desenhar()`.
- **P1** o freio deixa de depender do foco: se o usuário mexeu em algum campo desde o último desenho, o
  timer não repinta e aparece "há mudança nova — clique em Atualizar" (hoje `digitandoNaTela()` só pega
  com o foco dentro do campo).
- **P1** campos que mudam sozinhos entram no `RUIDO_TELA` (`admin.js:175`): `ultimo_uso_em`,
  `maquinas_usadas[].ultimo_em`, `quando`/`ultima_varredura`, `saude.atualizado_em`, `config[].atualizado_em`.
- **P2** prova de tela **medida** (é a prova que falta hoje): abrir "Empresas e configuração", mexer num
  `select`, esperar **40 s** (mais de 2 ciclos do timer) e exigir que o cartão não tenha sido substituído
  (impressão do nó antes/depois) e que o valor escolhido continue lá.
- **P2** o botão "⟳ Atualizar" segue sendo o único jeito de repintar a tela de propósito.

### Fase 3 — "refazer varredura" a pedido do admin (P0)

- **P0** chave nova `varrer` em `CHAVES_DE_CONFIG` (`ground/api.py:906`), aceita por `POST /api/config` na
  rota que já existe (o admin publica; o bordo lê — nenhuma conexão do terra para o bordo).
- **P0** o bordo ganha o ramo `varrer` em `ground/agente_de_ordens.py:502 aplicar_config` → chama a
  varredura que já existe (`varredura_do_bordo.varrer()`) e confirma na `config_aplicada_bordo` o que fez
  (`cadastradas` / `atualizadas`), igual ao `transmitir`.
- **P0** botão **"Refazer varredura"** no cartão da embarcação, no desenho do "Publicar teto" (o que foi
  publicado × o que o bordo confirmou), com o texto que o dono pediu: *"só entram as câmeras que ainda não
  aparecem; nada já configurado é mexido"*.
- **P1** a marca de tempo/versão impede repetir o mesmo pedido a cada leitura do bordo.
- **P1** prova **nova** `tests/test-varredura-a-pedido.py`: publicar `varrer` → o agente roda a varredura →
  câmera nova entra; câmera existente **com** `alvo`/`rotulo` do admin **não muda**; câmera que sumiu **não
  é apagada** (o medo do dono: "caso tenha sido removida uma câmera por engano").
- **P2** a varredura automática continua no intervalo de hoje (`LECSOR_ESPERA_DA_VARREDURA`, padrão 300 s,
  `ground/api.py:6291`); o botão é um pedido **extra**, não substitui.

### Fase 4 — provas e regressão (P0/P1)

- **P0** as duas provas novas (`tests/test-tipo-lido-do-banco.py`, `tests/test-varredura-a-pedido.py`)
  entram no `tools/regressao-0130.py`.
- **P0** as duas provas de tela da Fase 1 e da Fase 2 (a espera de 40 s é o coração da prova da queixa 2).
- **P1** `tools/regressao-0130.py` inteiro + `python -m unittest discover -s tests -p "test_*.py"`.
- **P2** ajustar quem hoje fixa o comportamento errado: `tests/e2e-qualidade-e-teto-em-empresas.py` abre
  essa mesma tela e passa a exigir o tipo certo e o cartão preservado.

### Fase 5 — publicar (0.22.0)

- **P0** bump `desktop/package.json` → `0.22.0`; `VERSOES_PUBLICADAS` + `NOTAS["0.22.0"]` em
  `tools/publicar-releases.py` (a nota dizendo, com todas as letras, que o tipo **nunca** deixou de gravar —
  quem mentia era a leitura).
- **P0** build (`desktop/construir-instaladores.sh`), commit, push, `tools/publicar-releases.sh`, deploy do
  lado terra na VPS (`ground/api.py`, `admin/admin.js`, `admin/index.html`, `app/app.js` do `HEAD`, backup
  `.antes-0220`, `py_compile`, restart, `/api/saude` 200) e conferir **o que o servidor entrega**
  (`/api/empresas` com `tipo` = `radar` na câmera marcada).
- **P1** nota no vault (`20-runbooks/2026-11-26-*.md`) + bullet no `index.md`, publicada **no branch
  `master`** do remoto, com `tail /var/log/vault-sync.log` conferido (o cron fica no `master`; a rodada
  anterior ficou 5 h sem publicar por o clone estar numa branch de trabalho).
- **P2** instalar a 0.22.0 no PC de captura real (o app não se auto-atualiza).

---

## Custo estimado

| fase | o que muda | tamanho |
|---|---|---|
| 1 | 1 linha no `SELECT` + 1 prova de servidor + 1 asserção na prova de tela | pequeno |
| 2 | `admin/admin.js`: timer, ações que repintam, freio por estado sujo, ruído + 1 prova de tela com espera | **médio (o maior)** |
| 3 | chave nova no servidor + ramo no agente + botão no cartão + 1 prova | médio |
| 4 | 2 provas no `regressao-0130.py` + rodar tudo | pequeno |
| 5 | bump, build, release, deploy, vault | pequeno |

## Questões abertas (precisam da decisão do dono antes da Fase 2/3)

1. **Onde fica o botão "Refazer varredura"?** No cartão da embarcação em "Empresas e configuração" (mesmo
   lugar do teto) ou junto do "Abrir" da empresa? (A varredura é por embarcação.)
2. **O que a tela faz quando há mudança nova durante a edição?** (a) só avisa "há mudança nova — clique em
   Atualizar" (nada repinta sozinho) ou (b) repinta só os números de leitura (saúde/frota) e nunca o
   formulário?
3. **O pedido de varredura expira?** Se o bordo estiver desligado, o pedido fica na fila e roda quando ele
   voltar (proposta: sim, com a marca de tempo aparecendo no cartão) — confirma?

## Provas que este plano NÃO consegue fechar nesta máquina

- O gatilho real da repintura na casa do cliente (a bancada não tem bordo vivo) — medido e **não
  reproduzido** aqui; fecha na prova de tela com espera (Fase 2, P2) e no PC de captura real.
- A instalação da versão no PC de captura real (o app não se auto-atualiza).
