# Qualidade de envio (2 / 2,5 / 3 Mbps) + o bloco de qualidade de volta no "Configuração do bordo"

**Status:** aguardando aprovação
**Data:** 26/11/2026
**Pedido do dono (26/11/2026, verbatim):** "inclua no plano mais possibilidades de qualidade de envio, 2mbps, 2,5mbps e 3mbps" · "outra coisa, o bloco de seleção de qualidade de envio sumiu da tela de configuração de bordo" (print do admin na tela "Configuração do bordo", 08:43).

---

## Goal

1. **Mais qualidades de envio:** a lista fechada de banda passa a ter **3 Mbps, 2,5 Mbps e 2 Mbps**, além de 1,5 / 1,2 / 1 / 0,8 / 0,5 / 0,3 Mbps.
2. **Tudo em "Empresas e configuração" (e a tela "Configuração do bordo" sai):** o **teto** da embarcação e a **qualidade de envio** por câmera passam a ser ajustados no cartão da embarcação e no cartão da câmera; o item de menu "Configuração do bordo" deixa de existir (decisão do dono, 26/11/2026: "precisamos deixar tudo mais simples").

**Ordem de execução:** Fase 1 (servidor → telas) → Fase 2 → Fase 3 → Fase 4 (prova) → Fase 5 (publicação). A Fase 2 só depende da lista da Fase 1 estar no mesmo tamanho nos dois lados; a Fase 3 não depende de ninguém e pode subir primeiro, se o dono quiser a tela legível antes.

**Decisões do dono (26/11/2026):** **(a)** o bloco que volta é **só a qualidade de envio** — nome, tipo e ligar/desligar continuam no cartão da câmera; **(b)** a ordem exibida é **da maior para a menor** (3,0 → 0,3 Mbps); **(c)** em aberto — ele perguntou "o que poderia editar?" (ver *Questões abertas*); **(d)** a correção da coluna "No bordo" (Fase 3) **entra** nesta rodada. Ele levantou ainda o pedido do **analytics** (seção *Pedido registrado*).

---

## Evidência (fato | como foi verificado)

| Fato | Como foi verificado |
|---|---|
| A lista do produto hoje para em **1500 kbps (1,5 Mbps)** | `ground/api.py:907` → `VALORES_DE_ALVO = ("1500","1200","1000","800","500","300")` e `ground/api.py:2386` → `ALVOS_DE_QUALIDADE = ("1500k","1200k","1000k","800k","500k","300k")` |
| O servidor **recusa** valor fora da lista (é lista fechada, não faixa) | `ground/api.py:943` devolve `"alvo fora da lista do produto"`; `tests/e2e-config-do-bordo-vinda-de-terra.py:193` publica `99999` e espera HTTP 400 |
| A mesma lista está copiada em **4 lugares só no admin** | `admin/admin.js:1426` (`LISTA_ALVO`), `:2010` (`ALVOS_DA_BANDA`), `:2689` (`ALVOS_DE_ENVIO`), `:716` (lista colada no seletor do "Enviar vídeo") |
| A lista também está fixada em testes | `tests/test_captura_no_admin.py:308` (compara a string `const LISTA_ALVO = [...]`), `tests/e2e-tela-limpa-do-admin.py:45` (`BANDAS = [...]`) |
| O **bloco "Banda por câmera" existia** na tela "Configuração do bordo" até a 0.20.0 | `git show ea96b35^:admin/admin.js` linhas 2027-2055: `<h2>Banda por câmera</h2>`, um `select` por câmera com rótulo **em Mbps** (`(Number(v)/1000).toFixed(1).replace('.', ',') + ' Mbps'`) + botão **Publicar** + estado *aplicado (vN) / aguardando o bordo / RECUSADO: motivo* |
| O bloco **saiu** na 0.20.0 e virou uma nota | `admin/admin.js:2027-2035` (hoje): `<h2>Por câmera: no cartão da câmera</h2>` + nota "Qualidade de envio, ligar/desligar a transmissão, nome e TIPO … ficam na área 'Empresas e configuração' … o mesmo ajuste não se repete aqui" — remoção feita no plano único de 25/11/2026 (commit `ea96b35`) por ser "duplicado" |
| **Nenhuma prova de tela cobria aquele bloco** — por isso ele saiu sem quebrar teste | `grep -rln "Banda por c" tests/ tools/` → vazio |
| A qualidade **continua** existindo só no cartão da câmera | `admin/admin.js:3048-3059` (`data-papel="alvo"`, opções de `ALVOS_DE_ENVIO`), que publica a chave `alvo_kbps` por `/api/config` |
| O bloco de **baixo** (a tabela da tela) é só leitura — nenhuma coluna se edita (dono, 26/11/2026: "não tem como editar nada") | `admin/admin.js:2064-2073`: a tabela recebe `{ Câmera, Chave, Valor, Publicado, Quando, No bordo }` e o valor de cada célula é texto; não existe `<input>`/`<select>` nem `data-papel` em nenhuma coluna |
| A coluna "No bordo" chama de **RECUSADO** o que é **confirmação** (visto no print de 26/11/2026) | `admin/admin.js:2069` → `if (a.motivo) return 'RECUSADO: ' + a.motivo;`. E os textos de confirmação viajam como `motivo`: `ground/api.py:1015` ("alvo aplicado (vale no proximo inicio do envio)"), `ground/agente_de_ordens.py:498` ("no ar por publicacao do admin"), "teto local do bordo em 900 s". No print, as 3 linhas de `alvo_kbps` e as 3 de `transmitir` saem todas como "RECUSADO" |
| A distinção **aplicado × recusado** existe na origem e se **perde** no caminho | `ground/api.py:1054` `guardar_config_aplicada(...)` recebe `aplicadas` e `recusadas` em **duas listas** e grava as duas no MESMO campo `motivo`; a tabela `config_aplicada_bordo` (`db/schema-transmissao.sql:196-205`) **não tem** coluna de ok/recusado |

**Conclusão da evidência:** o pedido 1 é um acréscimo de 3 valores em **6 listas** (2 no servidor + 4 no admin) e nos testes que fixam a lista antiga; o pedido 2 é **restaurar** um bloco de SELEÇÃO que existe no histórico (`ea96b35^`) e que nunca teve prova de tela — é a razão de ele ter desaparecido sem ninguém notar. A tabela de baixo **não é** o lugar da seleção: ela é o registro do que foi publicado e não tem campo editável (conferido no print de 26/11/2026); o que ela tem é um defeito próprio — rotular de "RECUSADO" toda confirmação do bordo (Fase 3).

---

## Fase 1 — A lista de qualidade

**P0 — servidor (senão nada funciona):** `ground/api.py` — `VALORES_DE_ALVO` (`:907`) e `ALVOS_DE_QUALIDADE` (`:2386`) ganham `3000`, `2500`, `2000` **no começo**, mantendo a ordem decrescente que as telas usam.
- *Aceite:* publicar `alvo_kbps=3000`, `2500` e `2000` em `/api/config` responde **201**; `99999` continua respondendo **400**.

**P1 — as telas do admin:** `admin/admin.js` — `LISTA_ALVO` (`:1426`), `ALVOS_DA_BANDA` (`:2010`), `ALVOS_DE_ENVIO` (`:2689`) e a lista colada do "Enviar vídeo" (`:716`) ganham os mesmos três valores, na mesma ordem.
- *Aceite:* abrir cada um dos quatro seletores mostra 3,0 / 2,5 / 2,0 Mbps além dos atuais.

**P2 — lista com uma fonte só:** as quatro cópias do admin passam a ler **uma** constante (`ALVOS_DE_ENVIO`), com um teste que compara essa constante com a lista do servidor — hoje a divergência entre elas é exatamente o defeito que fez o valor "2500k de antes da lista" aparecer como "(fora da lista)" no cartão (`admin/admin.js:716`).

**Custo:** edição de constantes + 1 teste de igualdade. **Dependência:** nenhuma.

---

## Fase 2 — Tudo em "Empresas e configuração" e a tela "Configuração do bordo" sai

**Decisão do dono (26/11/2026):** "não daria pra mudar para essa outra tela e remover configuração do bordo? precisamos deixar tudo mais simples". A tela só existe no admin (item de menu `admin/index.html:94`; mapa em `admin/admin.js:261/304`) e nada no cliente depende dela — o que ela tem de único é o **teto de transmissão da embarcação** (`teto_s`), que passa para o cartão da EMBARCAÇÃO em "Empresas e configuração", ao lado de "editar embarcação" (`admin.js:2887-2909`). A tabela `config_bordo` do banco **não muda**: ela é o transporte da configuração, não a tela (o `greps` de `config_bordo` em `tests/e2e-admin-unificado.py` e `tools/smoke/jornadas/j8` é da tabela).

**P0 — mover o TETO da embarcação para o cartão da embarcação:** o campo "Teto (minutos)" + "Publicar teto" (hoje em `admin.js:2043-2057`) vai para o cartão da embarcação, junto de "editar embarcação" (`admin.js:2887-2909`); a chave continua `teto_s` com `camera_id=''` e o mesmo `POST /api/config`.
- *Aceite:* publicar o teto pelo cartão da embarcação grava `teto_s` e o bordo confirma (a mesma prova que a tela antiga cumpria).

**P0 — o seletor da qualidade aparece EM BRANCO (defeito visto no print de 26/11/2026):** no cartão da câmera, `select[data-papel="alvo"]` (`admin/admin.js:3048`) é renderizado sem o valor escolhido à vista, enquanto o seletor do tipo, ao lado, mostra "câmera comum". O bloco novo da Fase 2 nasce com o valor visível (`2000/2500/3000 kbps`) e o cartão da câmera segue igual.
- *Aceite:* no print, o seletor da qualidade mostra o valor atual (ex.: "1500 kbps") em vez da caixa branca.

**P0 — "excluir câmera" (pedido do dono): o BOTÃO não existe, a ROTA existe.** `grep -n "excluir" admin/admin.js` → **0 ocorrências** no admin; mas `POST /api/cameras/<id>/remover` existe no servidor e é **testada** (`ground/api.py:4705`, só ADMIN ou a própria máquina de captura; `tests/test-remover-e-editar-camera.py`: "remover tira da operação sem apagar histórico"). Ou seja: falta o botão no cartão, não a operação. Só entra depois da decisão dele (*Questões abertas*): "excluir" = desativar (o que já existe) ou remover de verdade (a rota pronta, com histórico preservado).

**P1 — remover a tela:** apagar o item de menu (`admin/index.html:94`), o mapa `config_bordo` (`admin/admin.js:261/304`) e o corpo `telaConfigDoBordo` (`admin.js:2012`), depois de mover o teto; o "volta para a tela" depois de publicar (`admin.js:2053`) sai junto, e o único teste que clica nela (`tests/e2e-tela-do-captura-so-cadastra.py:178`) aponta para o novo lugar. A tabela `config_bordo`, as rotas `/api/config` e as provas que falam com elas **ficam como estão**.

**P2 — não perder de novo:** o teto entra com `id="cfg-teto-<embarcação>"` no cartão da embarcação (a prova de tela fixa por `input[id^=cfg-teto-]`, porque o id leva o id da embarcação e uma empresa pode ter várias) e a qualidade segue com `data-papel="alvo"` no cartão da câmera.

**Custo:** mover o teto (1 campo + 1 botão) + a qualidade no cartão da câmera + apagar a tela (menu, mapa e corpo `telaConfigDoBordo`) + ajustar 1 teste. **Dependência:** Fase 1 P1.

---

## Fase 3 — A coluna "No bordo" dizendo a verdade

Hoje a tabela chama de **RECUSADO** tudo o que o bordo manda como `motivo` — inclusive as confirmações (`admin/admin.js:2069`). O print de 26/11/2026 mostra as 3 linhas de `alvo_kbps` e as 3 de `transmitir` como "RECUSADO: alvo aplicado…" / "RECUSADO: no ar por publicacao do admin": o alvo **foi aceito** e a tela diz o contrário. A distinção existe na origem e se perde na gravação (`ground/api.py:1054` junta `aplicadas` + `recusadas` no mesmo campo; `config_aplicada_bordo` não tem a coluna).

**A remoção da tela (Fase 2) FECHA este defeito:** o único lugar que pintava tudo de "RECUSADO" era o `estado` da linha daquela tabela (`admin/admin.js:2069`) — a tabela sai com a tela. O cartão da câmera mostra o motivo **cru**, sem rótulo de recusa (`admin.js:3031`: `publicado ao bordo: … | o bordo aplicou: alvo_kbps=500 [alvo aplicado (vale no proximo inicio do envio)]`) — conferido no código.

**P0 — conferir que não sobrou rótulo mentiroso:** depois da Fase 2, `grep -n "RECUSADO" admin/admin.js` → **0 ocorrências**; o motivo continua visível no cartão, sem juízo de valor.

**P1 — o dado do servidor fica como está:** `guardar_config_aplicada` (`ground/api.py:1054`) continua juntando `aplicadas` + `recusadas` no mesmo `motivo`; sem a tela, não há mais por que mexer no esquema (nada é apagado, nada migra).

**Custo:** nenhum (fechada pela remoção da tela na Fase 2). **Dependência:** Fase 2.

---

## Fase 4 — Prova

**P0 — prova de tela nova:** `tests/e2e-qualidade-e-teto-em-empresas.py` (Playwright, no padrão das provas de admin): entra no admin, abre **"Empresas e configuração" → "Abrir"** na empresa, confere que o **teto** está no cartão da embarcação (`input[id^=cfg-teto-]`) e que cada cartão de câmera oferece **3000/2500/2000** (o menu nunca em branco), publica **3,0 Mbps pelo cartão da câmera** e **o teto pelo cartão da embarcação** conferindo o banco, e, no mesmo teste, que a tela "Configuração do bordo" **não existe mais** no menu (`button.item[data-tela="config_bordo"]` → 0) e que o servidor aceita `3000k` e recusa `4000k`.

**P1 — atualizar quem fixa a lista antiga:** `tests/test_captura_no_admin.py:308`, `tests/e2e-tela-limpa-do-admin.py:45` e `tests/e2e-admin-configura-e-bordo-obedece.py` (800/500) passam a refletir a lista nova.

**P2 — bancada inteira verde:** `python tools/regressao-0130.py` (**37 provas**) e `python -m unittest discover -s tests -p "test_*.py"` (**22 testes**) — a prova nova entra na lista de `PROVAS` do `regressao-0130.py`, como as demais.

**Custo:** 1 prova nova + 3 ajustes. **Dependência:** Fases 1 e 2.

---

## Fase 5 — Publicação

**P0 — fechar a rodada:** bump para **0.21.0** (`desktop/package.json` + `VERSOES_PUBLICADAS`/`NOTAS` em `tools/publicar-releases.py`), `construir-instaladores.sh`, commit + `git push origin main`, `publicar-releases.sh`.

**P1 — lado terra na VPS:** o `ground/api.py` com a lista nova vai para `/opt/pipeline/app` (deploy por arquivo, backup `.antes-0210`, `py_compile`, restart do `pipeline-api.service`).

**P2 — instalar no PC de captura real:** o app não se auto-atualiza; a lista nova só vale no bordo depois de instalar o instalador da 0.21.0 na máquina de captura.

---

## Rodada em andamento (NÃO é deste pedido, mas sai no mesmo bump)

O clone está com alterações provadas e ainda **não commitadas** — elas precisam entrar no mesmo commit para não ficarem só nesta máquina:

- `app/app.js` — o **aviso da gravação pronta** voltou para a GRADE (`pintarAvisoDeGravacao()`), perdido quando a tela "Transmitir" saiu do cliente na 0.20.0; mais a coluna **Estado** na tela Gravações.
- `tools/smoke/ambiente.py` + `tools/smoke/jornadas/j2|j4|j5|j8|j10` — `iniciar_transmissao()` (a jornada encerra a sessão que a anterior deixou de pé antes de pedir de novo).
- **Pendência com decisão dele:** o ramo `encerrar` de `_executar_saida` (`ground/api.py:554`) encerra a sessão mas **não apaga** a gravação quando o cliente sai da tela — é a regra "os arquivos serão apagados quando ele sair" medida pela J5, e a falha é anterior a esta rodada.

---

## Riscos e limites (declarados)

- A lista é **fechada** de propósito (produto): o servidor recusa fora dela — a UI é espelho, e a Fase 1 P0 vem antes de tudo.
- As **6 cópias** da lista (2 servidor + 4 admin) são risco de divergência; a Fase 1 P2 só resolve se o teste comparar de verdade. `desktop/dist/**` são artefatos de build (não se editam à mão).
- **3 Mbps não é medido** nesta rodada: sobe a banda de cada câmera e o teto de "≥80 % de redução" do produto não é re-medido aqui.
- Câmera com `alvo` antigo fora da lista (ex.: `2500k` de antes) continua exibida como "(fora da lista)" no cartão — comportamento mantido de propósito.
- O bloco restaurado **não** recoloca "ligar/desligar transmissão" na tela de config: isso continua no cartão da câmera, salvo decisão dele em contrário (ver abaixo).

## Onde se edita a câmera hoje (REPRODUZIDO na bancada, 26/11/2026)

O dono disse "não tem nada disso, só dá pra editar o nome da embarcação". A sonda `tools/_sonda_abrir_empresa.py` (nova, bancada com `--semear-demo`) abriu a empresa pelo botão **"Abrir"** e contou na tela: **2 cartões de câmera, 2 campos de nome, 2 seletores de tipo, 2 seletores de qualidade e ZERO botão de excluir**; print em `%LOCALAPPDATA%\hermes\cache\scratch\print-abrir-empresa.png`.

**O cartão da câmera EXISTE e é alcançável** — mas só depois de clicar "Abrir" na empresa (`admin/admin.js:2764`), e ele fica **abaixo** do cadastro de embarcação, da licença e da saúde. Dentro dele:

| O que | Onde | Fato verificado |
|---|---|---|
| **Nome** da câmera | campo no cartão + botão "salvar nome" | `input.nome-camera` (`admin/admin.js:2998`); salvar publica para o PC de captura (`admin.js:3007`) — o print mostra o campo e o botão |
| **Tipo** (câmera / radar / FLIR) | seletor "aplicar tipo" no mesmo cartão | `select[data-papel="tipo"]` (`admin.js:3060`); no print sai como "câmera comum" |
| **Qualidade de envio** | seletor "aplicar qualidade" | `select[data-papel="alvo"]` (`admin.js:3048`) — **e é aqui que o print mostra o defeito: o seletor aparece EM BRANCO**, sem o valor escolhido à vista |
| **Ligar/desligar** | botão "desativar" | já existe (desativar/ativar, `admin.js:3036-3044`) |
| **Excluir câmera** | **o botão não existe no admin** | `grep -n "excluir" admin/admin.js` → **0 ocorrências**; a OPERAÇÃO existe e é testada: `POST /api/cameras/<id>/remover` (`ground/api.py:4705`, só ADMIN ou a máquina de captura; `tests/test-remover-e-editar-camera.py`: tira da operação sem apagar histórico) |
| **Habilitar câmera por recurso (analytics) e autorizar quem acessa** | **não existe** | hoje o acesso é por papel (`PAPEIS_DE_USUARIO`) e por escopo de empresa/embarcação (`escopo_do_cliente()`), nunca por recurso de câmera |

**Consequência para este plano:** (1) o nome **já** se edita no cartão da câmera — o que falta é o cartão ser encontrável a partir da tela "Configuração do bordo" (é o que a Fase 2 resolve, com o bloco por câmera subindo na tela junto do TIPO, que é o que decide o observador); (2) o seletor da qualidade **em branco** do print entra como P0 na Fase 2; (3) "excluir câmera" é pedido dele cujo **botão** não existe no admin (a rota existe no servidor e é testada) — precisa da decisão da seção *Questões abertas* antes de virar botão.

## Estado da implementação (assinado em 26/11/2026, antes do bump)

- **Fase 1 — FEITA:** `ground/api.py` `VALORES_DE_ALVO` = 3000/2500/2000/1500/1200/1000/800/500/300 e `ALVOS_DE_QUALIDADE` com os mesmos em `k`; o admin passou a ter **uma** constante (`ALVOS_DE_ENVIO` + `ALVOS_DE_ENVIO_K`, no topo do `admin/admin.js`) e as 4 listas antigas derivam dela (`:716`, `:722`, `:1432 LISTA_ALVO`, `:1556`); `ALVOS_DA_BANDA` (código morto) e a segunda declaração de `ALVOS_DE_ENVIO` foram removidas. A escada de sugestão do servidor (`ground/api.py:3488`) passou a sair de `VALORES_DE_ALVO` — antes era cópia parada em 1500k.
- **Fase 2 — FEITA:** o TETO foi para o cartão da embarcação (`areaDaEmpresa` busca `GET /api/config` por embarcação; o cartão renderiza `input#cfg-teto-<emb>`, "Publicar teto" e o estado) e a tela "Configuração do bordo" **saiu** (`admin/index.html` sem o item de menu; `SUBS`/despacho/corpo `telaConfigDoBordo` removidos). O seletor da qualidade do cartão da câmera **não abre mais em branco**.
- **Fase 3 — FECHADA pela Fase 2:** `grep -n "RECUSADO" admin/admin.js` → 0; nenhum esquema mudou (`guardar_config_aplicada` fica como está).
- **Fase 4 — FEITA:** `tests/test-lista-de-alvos-igual-ao-servidor.py` (novo, paridade estática) e `tests/e2e-qualidade-e-teto-em-empresas.py` (novo, navegador) — os dois entraram em `PROVAS` do `tools/regressao-0130.py` (**39 provas**); ajustados `tests/test-selecao-de-qualidade.py` (9 níveis; 4000k recusado), `tests/test-qualidade-chega-ao-lado-terra.py` (teto agora 3000k; 2300k recusado), `tests/e2e-tela-limpa-do-admin.py` (BANDAS), `tests/e2e-tela-do-captura-so-cadastra.py` (seção 4 reescrita: o teto no cartão da embarcação), `tests/test_captura_no_admin.py` e o texto do `test-instalador-plug-and-play.py`.
- **Fase 5 — EM ANDAMENTO:** bump 0.21.0 (`desktop/package.json`, `VERSOES_PUBLICADAS`, nota `NOTAS["0.21.0"]`), provas e build/publicação/deploy.

## Pedido registrado (não é desta rodada)

O dono (26/11/2026) registrou o que vem depois: quando entrar a **contagem de pessoas e os analytics**, o sistema precisa saber **quais câmeras estão habilitadas** para cada recurso e **quem está autorizado** a acessar. Não é escopo desta rodada (o bloco desta rodada é só a qualidade de envio) e **não há campo** hoje para isso — precisa de decisão de produto antes de virar plano.

## Questões abertas

1. **(c) a única coluna que faria sentido editar na tabela de baixo é "Valor"** — ela republicaria as chaves de `CHAVES_DE_CONFIG` (`ground/api.py:906`: `alvo_kbps`, `teto_s`, `gravacao_continua`, `transmitir`, `rotulo`), ou seja, exatamente o que o bloco de cima e o cartão da câmera já fazem; as colunas Publicado/Quando/No bordo são histórico. O plano assume **tabela só leitura** — ele confirma ou quer o "Valor" editável ali?
2. O `rotulo` (nome) é uma das chaves publicáveis por `/api/config`; confirmar que o nome continua sendo editado **só** pelo campo do cartão (`admin.js:2998`) e não vira campo da tabela.
3. **"Excluir câmera"**: desativar (que já existe e tira a câmera da tela do cliente, mantendo o histórico) resolve, ou ele quer **apagar de verdade**? Se for apagar, precisa responder também o que acontece com o histórico/trilha da câmera (o princípio dele é "nada é apagado", vale para logs).
