# Plano único — organizar o cliente e o admin (0.20.0): tirar o que não serve, dizer o que é, o TIPO da câmera, o gravado a bordo, o "Ver ao vivo" e os dashboards

Data: 25/11/2026 · Repo: `lecsor-pipeline-video` · Base medida: `main` = `b611a46` (v0.19.0)
Status: **AGUARDANDO APROVAÇÃO** (só implementa com "aprovado")
Este arquivo substitui `2026-11-25-tela-do-cliente-tempo-relatorios-transmitir-escopo-e-gravado-a-bordo.md` e `2026-11-25-admin-config-do-bordo-edicao-tipo-gravado-e-dashboards.md`.

## 1. O que o dono pediu (verbatim, 25/11/2026)

**Cliente**
> eu falei que quem define o tempo máximo é o admin, não o cliente

> pra que serve esse relatório? não serve pra nada

> tela "Transmitir" também sem utilidade

> que tipo de cliente é esse? só acessa uma embarcação, várias embarcações, todas de uma empresa, todas de todas as empresas?

> onde eu consigo acessar as imagens gravadas a bordo?

> e essa, qual a embarcação? não está aparecendo lá

**Admin**
> você precisa olhar também "Configuração de bordo" do admin, há blocos duplicados e , não consigo editar as câmeras, excluir, renomear, etc...

> quando eu puder renomear, o sistema saberá qual imagem é do radar de óleo e/ou câmera flir para que petrobrás/ibama possam acessar.

> ainda não consigo acessar as imagens na área do admin, precisa resolver isso

> achei o botão escondido, praticamente no rodapé, e como escolho quais câmeras e de quais empresas ou embarcações quero acompanhar?

> o admin tem acesso a todas as embarcações, precisa poder selecionar a embarcação, mas não aparece nenhum botão de escolha

> o cliente não consegue acessar o gravado a bordo e o admin não consegue visualizar as imagens ao vivo

> tanto o dashboard do admin quanto o do app de captura continuam horríveis, precisa ser algo mais próximo desse do Dock Check

## 2. O que foi medido (evidência)

### 2.1 CLIENTE — "Tempo de transmissão": o cliente NÃO deve configurar
- Menu `configuracao` ("Tempo de transmissão", `app/index.html`) → `desenharConfiguracao()` (`app/app.js`) → `POST /api/transmissao/config`.
- O mecanismo do admin **já existe**: `tempo_maximo_do_produto()` (`ground/api.py:597`) lê a chave **`teto_s`** de `CHAVES_DE_CONFIG` (`:881`); com teto, a rota **recusa** (`403` "o tempo de transmissao e' definido pelo administrador").
- Nos prints o seletor está clicável e o **"Gravar" ativo** → `tempo_maximo_do_produto()` devolveu vazio naquele ambiente: **o admin não fixou o teto**, então o cliente escolhe.
- O admin **já** fixa o teto: "Configuração do bordo" (`admin/admin.js:2078-2085`, `POST /api/config` com `teto_s` em minutos).

### 2.2 CLIENTE — "Relatórios" e "Transmitir": sem função / redundantes
- `relatorios` (`app/app.js:894`): tabela de câmeras + `S.analises` — as tabelas `analytics_*` **não têm quem escreva** (o agente de bordo não existe).
- `transmissao` → `desenharTransmissao()` (`app/app.js:1286`): lista por câmera + a tabela "Histórico das transmissões desta embarcação" (`:1345`) — o controle de transmissão (iniciar/parar/reconectar, contagem, gravar) **mora na GRADE** (`visualizar`), que é a tela que o dono usa.

### 2.3 CLIENTE — o TIPO de cliente e a EMBARCAÇÃO não aparecem
- O servidor **já calcula os 4 escopos** (`ground/api.py:3521-3545`): `todas_as_empresas` (observador/tipo 4), `todas_as_embarcacoes_da_empresa` (3), `algumas_embarcacoes_da_empresa` (2), `uma_embarcacao_da_empresa` (1) — mas isso só sai na rota do **ADMIN** (`GET /api/usuarios/<id>/embarcacoes`); `/api/eu` (`ground/api.py:2758`) devolve só `email`/`nome`/`papel`/`local`.
- A embarcação existe em **um único** lugar da tela: o `<select id="embarcacao">` do cabeçalho (`app/index.html:64`, rótulo em `app/app.js:58`). O `<h1>` diz só "Transmissões ao vivo" e o subtítulo "Monitoramento em tempo real das câmeras selecionadas" (`app/index.html:60-61`); os cartões da grade mostram **só o nome da câmera** ("USB Video (1)", "Bancada — câmera 1 · 1280x720").

### 2.4 CLIENTE — o gravado a bordo está fora de alcance
- A gravação **de bordo** (HD do PC de captura, full-time) é publicada como catálogo e vista na tela **"Radar de óleo (HD)"** (`radar_hd`): `GET /api/hd/catalogo` → `POST /api/hd/pedir` → o bordo envia → `GET /api/hd/baixar`.
- **O item está invisível**: na 0.19.0 eu o escondi quando a embarcação não tem câmera `tipo === 'radar'` (`app/app.js:126-128`) — e o `tipo` só nasce no bordo; na bancada não há radar → o item sumiu.
- E mesmo com o item visível não haveria o que listar: o `publicar_catalogo` **sai cedo** com a gravação contínua desligada (`ground/agente_de_ordens.py:382`), ela **nasce desligada** e **nada no admin a liga** → `hd_catalogo` vazio.

### 2.5 ADMIN — "Configuração do bordo" com blocos duplicados
- `telaConfigDoBordo` (`admin/admin.js:2010-2109`): bloco 1 "Banda por câmera" (por câmera: `<select>` de `alvo_kbps` + **Publicar** + **Ligar/Desligar transmissão**), bloco 2 "Teto de transmissão da embarcação", bloco 3 (tabela final) "desejada × aplicada" que **repete todas as chaves de todas as câmeras**.
- E quase tudo isso **já existe** no cartão da câmera da área "Empresas e configuração" (`cartaoDaCamera`, `admin.js:2635`): nome, ativar/desativar, qualidade, desligar envio, remover.

### 2.6 ADMIN — editar/excluir/renomear existem; **falta o TIPO**
- `cartaoDaCamera` já tem nome (`POST /api/cameras/<id>/nome`), ativar/desativar (`/ativo`), qualidade, desligar envio e **remover** (`/remover`), com `pode_configurar(u)`: `admin/api.py:4569` (nome), `:4534` (remover), `:4598` (editar).
- **FALTA o `tipo`**: nenhum seletor e nenhuma rota do admin para gravá-lo — a coluna `cameras.tipo` (`camera|radar|flir`) só é escrita **pelo bordo** (cadastro da câmera de rede e anúncio).
- **ARMADILHA MEDIDA:** o anúncio do bordo (`POST /api/cameras/anuncio`) grava com `ON CONFLICT(id) DO UPDATE SET …, tipo=excluded.tipo` — o tipo do bordo **sobrescreve** o do admin no anúncio seguinte.
- O observador (Petrobras/IBAMA) já filtra por **tipo** (`tipo_da_camera()`/`pode_o_observador_ver()`, 0.19.0); só falta o admin poder **declarar** o tipo.

### 2.7 ADMIN — o gravado a bordo existe no backend e **não tem tela**
- O backend já atende o admin: `GET /api/hd/catalogo` aceita admin (`api.py:3237`, `_pode_operar` + `embarcacao_id`), `POST /api/hd/pedir` e `GET /api/hd/baixar` (`PAPEL_ADMIN` baixa, `:3253`).
- Quem usa: **só o app do cliente** (`app/app.js:1600/1606/877`). O `admin/admin.js` tem **0** ocorrências de `/api/hd/` e o menu (`admin/index.html:76-100`) não tem o item.

### 2.8 ADMIN — o "Ver ao vivo": botão no rodapé, sem seletor e sem imagem
- O botão sai **no fim** do bloco da embarcação (`admin/admin.js:2287`), depois da tabela de fluxos.
- `abrirAoVivo(emb, cams)` (`admin.js:2176`) recebe **as câmeras de UMA embarcação** (`emb.cameras`) e a janela (`#ao-vivo`) **não tem seletor nenhum**; trocar de embarcação = fechar e achar o outro botão. Reproduzido no navegador: a janela abre (6 players, sem erro de console) — mas abre **preta**.
- **Não há imagem** porque só entra fluxo na câmera `c.no_ar` (`admin.js:2203`) e o bordo só transmite com alguém assistindo; o admin **não** liga transmissão (D3: "só quem visualiza é o cliente") → sem uma sessão de cliente aberta, o admin **nunca** vê imagem ao vivo.
- **DECISÃO EM ABERTO (dono):** como o admin vê imagem ao vivo? (o admin abrir sessão como o cliente, ou o bordo aceitar uma ordem de "ligar agora" do admin — hoje as duas coisas não existem).

### 2.9 Os dashboards
- **Admin — "Monitoramento (frota)"** (`telaFrota`, `admin.js:2212-2291`): 4 cartões de contagem (Embarcações / Com problema / Em atenção / Ok), depois um `caixa-form` por embarcação com 4 números (CPU/mem/disco/rede) + tabela de fluxos + "Ver ao vivo". Sem gráfico, sem diagnóstico de conexões, sem lista de alertas.
- **Bordo** (`bordo/index.html`): fileira de 4 números + 4 curvas (CPU/mem/disco/rede) + blocos "O que está acontecendo agora" / "Licença" / "Envio para o lado terra" + modo TV.
- **Referência do dono (Dock Check)**, o que ele quer: cabeçalho com título + "atualizado há X · auto-refresh 30s" + **Atualizar**/**Minimizar**; fileira de KPI (ícone + rótulo + número grande + barra de progresso); "Dispositivos por Projeto" (barras); "Distribuição Geral" (rosca com o centro); "Disponibilidade (7 dias)" (Uptime / Incidentes / Tempo Médio) + "Incidentes por dia" (linha); "Diagnóstico de Conexões" (cartões de estado); lista com selos **Crítico/Atenção/Operacional**; "Alertas (N)".

## 3. Fases (prioridade marcada dentro de cada fase)

### Fase 1 — Cliente: tirar o que não é dele e dizer o que é (P0)
- **P0** — `configuracao` ("Tempo de transmissão"), `relatorios` ("Relatórios") e `transmissao` ("Transmitir") saem do menu e do despacho do cliente; o grupo "Transmissão" deixa de existir. O controle de transmissão continua na GRADE (nada de função perdida).
- **P0** — o servidor recusa `POST /api/transmissao/config` para o papel `cliente` com `403` ("o tempo de transmissão é definido pelo administrador"), independentemente de haver teto — a defesa fica no servidor, não só no menu.
- **P0** — `/api/eu` passa a devolver o **escopo** do cliente (reaproveitando `ground/api.py:3521-3545`; o observador devolve `todas_as_empresas`).
- **P0** — a **embarcação** fica visível: entra no cabeçalho junto do escopo e no **card de cada câmera** da grade (câmera · embarcação), para o observador saber sempre onde está.
- **P1** — o chip da conta passa a mostrar o tipo por extenso: "Cliente · 1 embarcação" / "Cliente · algumas embarcações da empresa" / "Cliente · todas as embarcações da empresa" / "Observador (Petrobras/IBAMA) · todas as empresas".

### Fase 2 — O gravado a bordo, para o cliente e para o admin (P0)
- **P0** — cliente: o item volta a aparecer **sempre** e passa a se chamar **"Imagens gravadas a bordo"** (reverter o P2 da 0.19.0); quando não há catálogo, a tela **diz o motivo** em vez de sumir.
- **P0** — admin: nova tela **"Imagens gravadas a bordo"** (grupo Operação): escolhe empresa → embarcação → lista o catálogo (`GET /api/hd/catalogo?embarcacao_id=…`), pede o trecho (`POST /api/hd/pedir`), acompanha e baixa (`GET /api/hd/baixar?id=…`).
- **P1** — manter "Radar de óleo (HD)" como apelido quando a embarcação TEM radar.
- **P1** — registrar a causa-raiz do catálogo vazio: a gravação contínua nasce desligada e **nada no admin a liga** (hoje só o env `LECSOR_GRAVACAO_CONTINUA` no PC de captura).

### Fase 3 — Admin: configuração e câmeras (P0)
- **P0** — `telaConfigDoBordo` perde a duplicação: sai o bloco "Banda por câmera"; a tela fica só com o da EMBARCAÇÃO (o **teto de transmissão** `teto_s`) e o resumo "desejada × aplicada" **somente leitura**.
- **P0** — `cartaoDaCamera` ganha o seletor **Tipo**: `Câmera comum` / `Radar de óleo` / `FLIR (térmica)`, gravado por `POST /api/cameras/<id>/editar` (campo `tipo`) e auditado.
- **P0** — **o admin MANDA no tipo**: o anúncio do bordo passa a gravar `tipo` (e `rotulo`) **só na criação** ou quando a coluna estiver vazia — *o bordo propõe, o admin decide*.
- **P1** — o selo do tipo no cartão, ao lado dos de estado; a coluna "Tipo" do cliente e o filtro do observador leem o mesmo dado.

### Fase 4 — Admin: "Ver ao vivo" e os dashboards (P0/P1)
- **P0** — o "Ver ao vivo" sobe para o **topo** do bloco da embarcação e a janela ganha **seletor dentro dela**: **empresa → embarcação → câmeras** (caixa de seleção por câmera; padrão: todas as da embarcação).
- **P1** — dashboard do admin (frota) no padrão Dock Check: cabeçalho com "atualizado há X · auto-refresh 30s" + **Atualizar**/**Minimizar**; KPI (Embarcações / Câmeras no ar de total / Computadores de captura / Gravações / Alertas) com barra; "Câmeras por embarcação"; "Distribuição Geral"; "Disponibilidade (7 dias)"; "Diagnóstico de Conexões" (terra→bordo, bordo→terra); lista de embarcações com selos **Crítico/Atenção/Operacional**; "Alertas (N)".
- **P1** — dashboard do app de captura na mesma linguagem (KPI com barra, curvas mantidas, "Diagnóstico de Conexões", cartões de processo transmitindo/gravando, lista de câmeras com selo de tipo e estado).
- **P2** — "Mapa de Operações": fora de escopo enquanto não houver coordenada da embarcação no cadastro (não se inventa marcador). Modo TV do bordo mantido.

### Fase 5 — Verificação (P0)
- **P0** — `node --check` + `py_compile`; suíte `tools/regressao-0130.py` verde.
- **P0** — provas novas: menu do cliente sem as três telas; `/api/eu` com o escopo; `POST /api/transmissao/config` → **403** para `cliente`; `editar` com `tipo` grava e o anúncio do bordo **não** sobrescreve; o admin lista e baixa o HD; `telaConfigDoBordo` não publica mais `alvo_kbps`.
- **P0** — smoke de ponta a ponta sem regressão nova; prints antes/depois (menu do cliente, cartão da câmera, HD do admin, os dois dashboards).

## 4. Fora de escopo (registrado)
- Ligar a gravação contínua a bordo pelo admin (depende da decisão da Fase 2-P1).
- O mapa (sem coordenada); J5/J10 (saída da tela); agente de bordo (analytics/marcas — o dado não existe).

## 5. Critério de pronto
Menu do cliente **sem** "Tempo de transmissão", "Relatórios" e "Transmitir", e **com** "Imagens gravadas a bordo"; o **tipo** e a **embarcação** visíveis na tela do cliente; "Configuração do bordo" sem duplicação; cartão da câmera com **editar/excluir/renomear e o TIPO**, com o tipo do admin prevalecendo sobre o anúncio do bordo; tela do admin para as **imagens gravadas a bordo**; "Ver ao vivo" com seletor empresa → embarcação → câmeras; os dois dashboards no padrão Dock Check; 35+ provas verdes; smoke sem regressão nova.
