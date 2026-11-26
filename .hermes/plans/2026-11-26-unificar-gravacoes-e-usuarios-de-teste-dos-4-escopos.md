# Unificar "Gravações" + "Radar de óleo (HD)" numa página só, e criar os 4 tipos de cliente para testar

**Estado: PROPOSTO — aguardando o dono (nada é implementado sem "aprovado").**
Rodada prevista: **0.24.0**. Repo: `lecsor-pipeline-video` (branch `main`).

## Pedido (verbatim, 26/11/2026, com print do app do cliente)

> as telas "Gravações" e "Radar de óleo (HD)" podem ser uma página apenas "Gravações"
> preciso de usuários de todos os tipos de clientes para testar, essa que estamos utilizando
> aparentemente é de clientes que têm acesso a apenas uma embarcação

## Diagnóstico medido (26/11/2026 — banco REAL da VPS, somente leitura)

Medido em `/opt/pipeline/app/db/pipeline.db` (script `foto-banco-vps.py`, só nomes/ids/papéis):

| Medida | O que é hoje |
|---|---|
| Empresas (`clientes`) | `lecsor` (LECSOR interno) e `armador-demo` (Armador Exemplo) |
| Embarcações | `bancada` (lecsor) e `psv-exemplo` (armador-demo) — **uma por empresa** |
| Vínculos (`usuario_embarcacoes`) | **ZERO linhas** |
| Usuários | `admin@lecsor.test` (admin), `operacao@lecsor.test` (operador), `cliente@lecsor.test`, `cliente@armador-demo.test` — **nenhum observador** |
| Câmeras | `bancada`: 3 câmeras + **1 radar**; `psv-exemplo`: 2 câmeras, **sem radar** |
| HD do bordo (`hd_catalogo`, `hd_pedidos`) | **0 e 0** (nenhum PC de captura publicando) |
| Gravações em terra (`gravacoes`) | 1 linha |
| Login | Supabase Auth (`supabase_auth.entrar`), projeto `gscfcobpejxhtyzwfrjp.supabase.co` **no ar**, com os mesmos 4 usuários |

**Por que a conta dele parece "de uma embarcação"** — não é defeito de escopo, é falta de dado.
O escopo é **derivado** dos vínculos (`escopo_do_cliente`, `ground/api.py:597`):

```
observador   -> todas_as_empresas                (tipo 4)
0 vínculos   -> todas_as_embarcacoes_da_empresa  (tipo 3)
1 vínculo    -> uma_embarcacao_da_empresa        (tipo 1)
2+ vínculos  -> algumas_embarcacoes_da_empresa   (tipo 2)
```

A conta em uso é **tipo 3** (zero vínculos) — mas a empresa dela tem **uma só** embarcação, então
"todas as da empresa" e "uma embarcação" dão no mesmo. Com 1 embarcação por empresa e nenhum
observador cadastrado, **nenhum dos 4 tipos é distinguível hoje**.

## Parte 1 — Uma página só, chamada "Gravações"

Hoje, no app do cliente (`app/index.html:29-42`) o menu tem **dois** itens e **duas** telas:

| Item do menu | Tela | De onde vêm os dados | Rota |
|---|---|---|---|
| 🎬 Gravações | `gravacoes` (`app/app.js:856`) | o que já chegou **em terra** nas transmissões (`S.transmissao.historico` com `gravacao.tem`) | `GET /api/gravacoes/<transmissao_id>` |
| 🛰 Radar de óleo (HD) / Imagens gravadas a bordo | `radar_hd` (`app/app.js:885`) | o **HD do PC de captura a bordo** (catálogo + pedidos) | `POST /api/hd/pedir`, `GET /api/hd/baixar` |

Detalhes que a unificação tem de respeitar:

- O rótulo do item 2 **muda sozinho** conforme a embarcação ter câmera `radar` (`atualizar()`, `app.js:137-143`) — com a unificação isso desaparece do menu.
- `tabelaEmPalco()` **limpa** o palco a cada desenho (`app.js:770`): para dois blocos na mesma página é preciso um desenho de **blocos** (título + tabela), não duas chamadas seguidas.
- O filtro de data (`#hd-filtro`, `app/index.html:76-82`: `hd-de`, `hd-ate`, `filtrar`, `ver tudo`, `hd-resumo`) hoje só aparece em `radar_hd`.
- **Observador** (Petrobras/IBAMA): `abrirObservador()` esconde todo item fora de `['visualizar','radar_hd']` (`app.js:88`) e `ground/api.py:496` só libera **radar/FLIR**. Ele **não** é dono das sessões de transmissão → o bloco "gravado em terra" não deve aparecer para ele.

### Fases

**Fase 1 — menu com um item e a página com dois blocos** (P0)
- Um único `<button data-tela="gravacoes">🎬 Gravações</button>`; o item `radar_hd` sai do menu.
- A página "Gravações" desenha **dois blocos** no mesmo palco, nesta ordem:
  1. **"Gravado a bordo (HD do PC de captura)"** — a tabela do HD com pedir/baixar (o que era a tela `radar_hd`), com o filtro de data ao lado;
  2. **"Gravado em terra (transmissões)"** — a tabela das gravações que chegaram (o que era a tela `gravacoes`).
- (P1) o filtro de data passa a valer para os dois blocos; (P2) o título do bloco 1 vira "Radar de óleo (HD)" quando a embarcação tem radar, mantendo "Imagens gravadas a bordo" quando não tem.

**Fase 2 — observador** (P0)
- `['visualizar','radar_hd']` → `['visualizar','gravacoes']`; ele vê o bloco 1 (com a coluna Embarcação, que já existe) e **não** vê o bloco 2. (P1) o título da tela para ele fala de radar, não de "transmissões".

**Fase 3 — provas** (P0)
- `tests/test-unificar-gravacoes.py` (nome com hífen, rodado **por caminho**): o HTML/menu tem **um** item de gravações e nenhum `radar_hd`; o desenho monta os dois blocos; o observador não recebe o bloco de terra; as rotas `/api/hd/*` e `/api/gravacoes/*` continuam respondendo.
- `tests/e2e-gravacoes-unificadas.py` (Playwright, `channel="chrome"`, cliques por `evaluate`): entrar como cliente, abrir "Gravações" e ver os dois blocos na mesma página.
- (P1) regressão inteira (`tools/regressao-0130.py`) e `unittest discover` verdes.

**Fase 4 — publicar** (P1)
- Bump **0.24.0** (`tools/_tmp_0240_bump.py`), commit, push, `desktop/construir-instaladores.sh`, release no GitHub, deploy do lado terra na VPS (`deploy-0240.sh`, backup por arquivo), nota no vault + `index.md`.

## Parte 2 — Usuários de teste dos 4 tipos de cliente

O que falta **não** é código de escopo (a regra existe e funciona): é **dado** — empresas com
mais de uma embarcação, radar na segunda empresa e um observador.

### Dados de teste que o plano cria na VPS (tudo com "TESTE" no nome)

- `armador-demo` passa a ter **3 embarcações**: a `psv-exemplo` + **2 novas de teste**
  ("PSV Exemplo II (teste)", "PSV Exemplo III (teste)"), com câmeras sintéticas de teste;
- **radar** em pelo menos uma delas, para o observador ter radar em **duas empresas** (`bancada` já tem);
- blocos sintéticos em `hd_catalogo` (radar, datas de hoje) e **1 gravação sintética** em `transmissoes`/`gravacoes`,
  para as duas tabelas da página nova **não** nascerem vazias.

### Usuários (um por tipo)

| Usuário | Papel | Empresa | Vínculos | Tipo que deve aparecer |
|---|---|---|---|---|
| `cliente-1-embarcacao@demo.test` | cliente | armador-demo | 1 (`psv-exemplo`) | **1** — uma embarcação da empresa |
| `cliente-2-embarcacoes@demo.test` | cliente | armador-demo | 2 (`psv-exemplo`, `psv-exemplo-2`) | **2** — algumas embarcações da empresa |
| `cliente-todas-da-empresa@demo.test` | cliente | armador-demo | 0 | **3** — todas as da empresa (as 3) |
| `observador@demo.test` | **observador** | — | — | **4** — radar/FLIR de todas as empresas |

### Fases

**Fase 5 — script de semente, idempotente** (P0)
- `tools/seed-usuarios-de-teste.py`, rodado na VPS por `scp` + `python3` (nunca heredoc por terminal):
  cria embarcações/câmeras/radar/blocos/gravação e os 4 usuários; rodar duas vezes **não** duplica;
  imprime **relatório sem senha** (o e-mail e o tipo de cada um, e o que cada um passa a enxergar).
- (P1) `--limpar` remove tudo o que foi criado (para não deixar lixo de teste na VPS).
- Senhas: o script **não** entrega senha em chat; a senha inicial aparece **uma única vez** no
  painel do admin ("redefinir senha", `POST /api/usuarios/<id>/senha`), ou fica num arquivo do
  cofre na VPS (`chmod 600`), conforme a decisão D4 abaixo.

**Fase 6 — prova dos 4 escopos** (P0)
- Teste contra o servidor de verdade: entrar com cada um dos 4 usuários e medir o que cada um
  enxerga em `/api/embarcacoes`, `/api/cameras` e `/api/hd/catalogo` (tipo 1 = 1 embarcação;
  tipo 2 = 2; tipo 3 = 3; tipo 4 = radar de 2 empresas, e **só** radar/FLIR).

**Fase 7 — validação na tela** (P1)
- Você redefine as senhas pelo painel e entra no app com cada usuário, conferindo a página
  "Gravações" nova com os 4 escopos.

## O que NÃO muda

- As rotas `/api/hd/catalogo|pedir|baixar` e `/api/gravacoes/*` (o que muda é só **onde** a tela as mostra).
- A regra de escopo do servidor (vinculo não amplia empresa: embarcação de outra empresa é recusada).
- O admin continua sem tela de HD (saiu na 0.23.0, por decisão sua).
- Nada de credencial de câmera/DVR: os dados de teste são sintéticos e só de estrutura.

## Riscos medidos

- A página nova precisa de um desenho de blocos porque `tabelaEmPalco` limpa o palco — mexer nisso sem prova faz a tela "piscar" (já aconteceu na 0.22.0).
- Criar usuário provisiona **também** no Supabase Auth (`_provisionar_no_supabase`): se a rede faltar, a resposta diz o que faltou — e o usuário não entra até a senha ser redefinida.
- Dados de teste na VPS ficam em produção de demonstração: por isso o prefixo "TESTE" e o `--limpar`.

## Decisões que preciso do dono (D1–D4)

- **D1.** Página unificada = um item "Gravações" com **dois blocos** (bordo primeiro, terra depois) — ou uma **tabela só** misturando as duas origens? *(recomendo dois blocos)*
- **D2.** Criar os usuários e os dados de teste **na VPS** (onde você testa) ou só na bancada local? *(recomendo VPS)*
- **D3.** Posso criar esses dados de teste na VPS (2 embarcações novas + radar na 2ª empresa + blocos de HD + 1 gravação sintéticas), tudo com "TESTE" e com `--limpar`? *(recomendo sim)*
- **D4.** Senhas: você redefine pelo painel (a senha aparece uma vez na sua tela — **recomendo**, nada passa por chat) ou quer as iniciais num arquivo de cofre na VPS?

## O que foi feito (26/11/2026)

- Diagnóstico medido no banco real e no Supabase Auth (só leitura): `foto-banco-vps.py`, `mede-supabase-auth.py`.
- Este plano. **Nada implementado ainda.**

## Resultado — implementado e provado (26/11/2026)

**Decisões do dono:** D1 dois blocos · D2 na VPS · D3 sim, com "TESTE" · D4 senha só pelo painel. Autorização: **"aprovado"**.

**Parte 1 — a página única** (`app/app.js`, `app/index.html`, aplicados por `tools/_tmp_0240_gravacoes.py`, que aborta se a âncora não for exatamente uma):

- Um item de menu só (**"Gravações"**); o item `radar_hd` saiu do HTML e do `app.js`.
- A página desenha **dois blocos** (`section.bloco-gravacao`): **gravado a bordo** (o HD do PC de captura; o título diz *"Gravado a bordo · Radar de óleo (HD)"* quando a embarcação tem radar) e **gravado em terra**.
- O **observador** recebe **só o bloco do bordo** (`if (S.papel !== 'observador')`) — e a tabela dele ganha a coluna **Embarcação**.
- O filtro de data e hora vale nos dois blocos; o desenho é por blocos (`montarTabela`/`blocosEmPalco`) para o ciclo de 5 s **não** remontar o palco (o defeito de "piscar" da 0.22.0).
- A jornada de smoke **J6** passou a abrir `data-tela=gravacoes` e a medir o **bloco do bordo**.

**Parte 2 — os 4 tipos de cliente** (`tools/seed-usuarios-de-teste.py`, idempotente, com `--limpar`): a semente cria na VPS as embarcações `teste-psv-2` e `teste-psv-3` (a empresa de exemplo passa a ter 3), o radar `teste-radar-psv2`/`teste-radar-psv3`, a embarcação `teste-emb-lecsor` na **outra** empresa com o radar `teste-radar-lecsor` (é o que dá ao observador **duas empresas de verdade**), os blocos do catálogo do HD de cada uma e **uma gravação em terra**; e os quatro usuários `cliente-1-embarcacao@demo.test` (1 vínculo), `cliente-2-embarcacoes@demo.test` (2), `cliente-todas-da-empresa@demo.test` (0) e `observador@demo.test` — a senha inicial é aleatória e **nunca** impressa (o dono redefine no painel).

**Achado da prova dos 4 tipos (corrigido):** `GET /api/hd/catalogo` no papel `cliente` filtrava **só** por `cliente_id` — quem tinha UMA embarcação enxergava o HD das **outras** da mesma empresa. Passou a usar a regra única `pode_ver_embarcacao` (`ground/api.py`, ~`:3512`).

**Provas (todas verdes):** `tests/e2e-pagina-unica-de-gravacoes.py` (**novo**, 20 verificações em navegador real), `tests/test-os-4-tipos-de-cliente.py` (**novo**, 22 verificações contra o servidor de verdade), `tests/e2e-observador-do-radar.py` (ajustado: o observador vê **1 bloco**), `tests/e2e-tela-do-radar-hd-do-cliente.py` (ajustado: o filtro continua estreitando a lista), `tools/regressao-0130.py` → **TUDO VERDE (46 provas)** e `python -m unittest discover` → **22 OK**.
