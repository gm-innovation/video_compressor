# Admin unificado por cliente + as câmeras do bordo aparecendo e configuráveis

Pedido do dono (23/11/2026, verbatim):

> na área do admin, preciso poder configurar cada cliente/embarcação/câmeras de forma unificada e simples,
> hoje eu tenho muitas páginas: clientes/embarcações/câmeras/licenças/produção/tempo real/enviar
> vídeos/usuários/configurações do bordo, tudo isso poderia ser uma área só, de configuração por cliente e
> de embarcações pra baixo tuddo vinculado ao cliente... e está ainda truncado, parece que está tudo
> funcionando do lado da captura mas as câmeras não aparecem do lado do admin, pelo menos não com o nome
> que a varredura pegou, e não consigo configurar e ligar as câmeras

Estado: **plano — nada implementado** (a regra da casa: só implementa com "aprovado").

---

## 1. O que eu conferi no sistema que está NO AR (não é suposição)

Tudo abaixo foi lido do banco e das rotas da **VPS** (`/opt/pipeline/app`, `db/pipeline.db`) e dos arquivos
deste repositório, em 23/11/2026.

**1.1 As câmeras da varredura CHEGARAM ao lado terra** — o problema não é o envio delas:

- `GET /api/cameras` (a rota que o admin lê) devolve **23 câmeras**; `GET /api/cameras/detalhe`, **24**.
- As 5 entradas que a varredura do bordo criou estão lá, **com o nome do dispositivo**, todas na
  embarcação `bancada`:

  | id no lado terra | rótulo (nome que a varredura pegou) |
  |---|---|
  | `cam-device-pnp-usb-vid-1bcf-pid-2c99-01-65e8773d` | USB Video Device |
  | `cam-device-pnp-usb-vid-0408-pid-403d-mi-00-7-210` | ACER HD User Facing |
  | `cam-device-pnp-usb-vid-534d-pid-2109-mi-00-6-253` | USB Video (2) |
  | `cam-device-pnp-usb-vid-534d-pid-2109-mi-00-6-37f` | USB Video (1) |
  | `cam-device-pnp-usb-vid-0001-pid-a001-mi-00-6-21c` | AFN-USB |

- A saúde do bordo está viva: `saude_bordo` com **20.149 linhas** e `estado_bordo` com **18 linhas
  atualizadas HOJE às 19:17:47** — o PC de captura está de pé, olhando terra e respondendo.
- `desejo_camera` (a flag que o bordo obedece) tem 18 linhas, todas com `desejo=parar` e
  `motivo="ninguem esta' assistindo"`; `manual` está **vazio** em todas.

**1.2 Por que, então, "não aparece no admin" e "está truncado" — dois defeitos reais de TELA:**

- A lista de câmeras do admin é **UMA tabela de 12 colunas** (Câmera, Fluxo, Situação, Stand-by, Endereço,
  Como o agente pega, Encoder, Qualidade (SSIM), Declarado, Qualidade enviada, Espectadores, Ação) e as 23
  linhas são jogadas juntas, **sem nenhum filtro por cliente ou embarcação** — as 5 da varredura ficam
  misturadas com ~15 câmeras de bancada de sessões antigas (`cam-01`, `cam-01-demo`, `cam-09`,
  `vivo-cam-01`, `vivo-cam1-11-18`, `vps-webcam-bancada`, …).
- Toda tabela do admin vai dentro de `.rolagem { overflow:auto; max-height:52vh }` (`fronts/admin.css:8`) →
  com 12 colunas e 23 linhas a tela corta **na horizontal e na vertical** dentro de uma caixinha: é o
  "está ainda truncado". O nome da câmera e o botão de ação nunca aparecem juntos.
- Na VPS, `GET /api/cameras/prontidao` responde `maquina_de_captura: false` e `dispositivos: []` (a VPS não
  tem entrada de vídeo) → a coluna "Stand-by (PC de captura)" diz **"a bordo (quem informa é o PC de
  captura)"** para todas, e o admin **não vê qual dispositivo a varredura achou** naquele bordo.

**1.3 Por que "não consigo configurar e ligar":**

- **Configurar**: as tabelas do caminho de configuração estão **vazias** — `config_bordo` 0 linhas,
  `config_aplicada_bordo` 0 linhas, `config_local` 0 linhas. A tela "Configuração do bordo" não tem o que
  mostrar, e não existe (ainda) uma tela que publique chave/valor por câmera dentro do fluxo do cliente.
- **Ligar**: existe caminho pronto no produto (`POST /api/cameras/ligar` grava `desejo_camera.manual='ligar'`
  e o terra honra em `_desejo_das_cameras()`: *"o operador ligou esta camera na mao"*; testado hoje com
  `manual` vazio, ou seja **ninguém ligou ainda**), mas o botão **só existe na tela "Tempo real"** — não
  existe na tela de Câmeras nem em nenhum lugar "por cliente". Para o dono, "a câmera" e "o lugar de
  configurar" são a mesma coisa, e não são hoje.

**1.4 A hierarquia existe no banco, mas o admin não a segue:**

- `clientes` 3 linhas (`lecsor`, `armador-demo`, `armador-e2e`), `embarcacoes` 2 (`bancada`,
  `psv-exemplo`), `usuarios` 4, `usuario_embarcacoes` **0 linhas** (ninguém tem escopo por embarcação
  atribuído).
- No menu do admin há **16 telas** em 2 grupos; as 8 que o dono citou (clientes, embarcações, câmeras,
  licenças, produção, tempo real, enviar vídeo, usuários, configuração do bordo) são **páginas separadas**,
  cada uma listando tudo de todos os clientes.

---

## 2. O que eu quero construir (e o que NÃO muda)

**A ideia em uma frase:** o admin passa a ter **o cliente como raiz** — entra-se por um cliente e tudo
(embarcações, câmeras, licença, configuração do bordo, produção, tempo real, usuários) fica **dentro
daquele cliente**, com as embarcações abaixo e as câmeras abaixo de cada embarcação.

Regras que o desenho respeita (não são escolha de UI, são regras do produto já decididas):

1. **Nada muda no caminho do vídeo**: o bordo continua autônomo, publicando saúde/estado/varredura e
   **olhando a flag** (`/api/estado-desejado`, `/api/config-desejada`). Nada de porta aberta no bordo.
2. **Nada de credencial**: a tela nunca mostra nem pede senha de câmera/DVR (regra de sempre); o que ela
   mostra por câmera continua sendo rótulo, endereço de operação (quando houver), estado e o que o bordo
   declarou.
3. **Quem opera é a operação/admin**: o cliente olha. "Ligar/desligar na mão" segue sendo ato da operação
   (`manual`), auditado.
4. **Nada é apagado**: as câmeras de bancada não somem do banco; elas **saem do caminho do cliente**
   (filtro), e a auditoria continua.

---

## 3. Fases

### Fase 1 — A área única por cliente (P0)

**Entrega:** uma tela nova `Clientes e configuração` que vira a casa do admin, e o menu enxuga para 3
entradas: **Clientes e configuração** · **Projeto** (o que já existe: fases/medições/decisões/evidências/
documentos) · **Sistema** (saúde do sistema, auditoria).

**P0 — o que é obrigatório nesta fase**

1. Entrar em **Empresas** → lista de empresas (com nº de embarcações, câmeras e "no ar") **e o botão
   "Nova empresa"** (hoje o cadastro existe em página separada) — criar a empresa é o primeiro passo.
2. Clicar na empresa → **página da empresa**: a lista das **embarcações dela** e o botão "Nova embarcação
   (vinculada a esta empresa)". Nada de embarcação solta: ela nasce dentro de uma empresa.
3. Clicar na embarcação → **página da embarcação**, e é aqui que a vida acontece, em 4 áreas:
   **① Chave (licença)** — gera/ver a chave DAQUELA embarcação (nº de PCs, status, último uso);
   **② Câmeras** (aba única = câmeras + tempo real + produção, ver Fase 2);
   **③ Configuração do bordo** (o que desce para o PC de captura, ver Fase 3);
   **④ Saúde do bordo** (o retrato que o PC de captura já publica).
4. **"Enviar vídeo"** (os envios por link/arquivo da bancada) vira um bloco dentro da embarcação, não uma
   página de todos os clientes.
5. **"Usuários" fica fora** desta árvore (decisão do dono), numa página própria, **com o vínculo a
   empresa e/ou embarcação** por usuário (é o que dá escopo 1/2/3 e o caso Petrobras).
6. As telas antigas continuam acessíveis (a URL antiga cai na área equivalente dentro da empresa/
   embarcação) — nada quebra para quem tem link salvo.
7. A tela diz **de qual empresa/embarcação** é cada número que mostra (hoje um número sem dono é o
   que faz o dono achar que "não aparece").

**P1** — busca por nome de cliente/embarcação/câmera no topo; o "último estado" por cliente na lista.
**P2** — o mesmo desenho servindo o **cliente** (a tela do cliente é a mesma árvore, só que travada no
cliente dele e sem os botões de operação).

### Fase 2 — Câmeras, tempo real e produção numa coisa só, dentro da embarcação (P0)

**Entrega:** a aba **Câmeras** da embarcação (a MESMA coisa que tempo real e produção, decisão do dono) —
as câmeras que a **varredura** do bordo achou aparecem com o **nome do dispositivo** e cada uma carrega,
junto, situação, vídeo e número de produção, com as ações na mesma linha.

**P0**

1. Agrupar por **embarcação** (não mais uma tabela de 12 colunas para tudo): por câmera mostrar
   **nome (rótulo da varredura)**, id do dispositivo, situação (`no ar` / `fora do ar` / `desativada`),
   o que o bordo declarou (encoder/bitrate resolvido) e **Ligar / Desligar** (o desejo, `manual`),
   **Configurar** e **Ativo/Desativado** — sem tabela que corta: o detalhe abre num painel.
2. Marcar visualmente a origem: **"achada pela varredura"** (id `cam-device-pnp-*` / `local=bordo`) ×
   **"cadastrada na mão"** × **"de bancada/teste"**.
3. Quando a máquina do admin não é a de captura, a tela **pede ao bordo** o stand-by daquela câmera (o
   bordo já publica `estado_bordo`; falta a tela cruzar isso por câmera) em vez de escrever "a bordo".
4. "Ligar/desligar" daqui para o bordo, com o retorno **da ordem na cara** (aceita/recusada e por quê) —
   reaproveitando `POST /api/cameras/ligar|desligar` que já existe.
5. Nada de truncamento: 1 câmera = 1 cartão (nome grande, ações visíveis), com um contador no topo
   (`5 achadas pela varredura · 2 no ar`).

**P1** — filtro "mostrar as de bancada/teste" (desligado por padrão) para as 15 câmeras velhas saírem do
caminho; renomear a câmera (só o rótulo, sem mexer no id).
**P2** — ordenar e agrupar por "achada pela varredura primeiro".

### Fase 3 — A configuração que sai do admin e chega ao bordo (P1)

**Entrega:** a aba **Configuração do bordo** dentro do cliente funciona de verdade (hoje: 0 linhas em
`config_bordo`).

1. Publicar chave/valor por câmera e por embarcação (`POST /api/config` já existe; a tela publica em lote).
2. **O nome da câmera desce para o bordo e passa a valer lá** (é o pedido literal do dono: *"a captura pega
   as informações e replica no app de captura, inclusive os nomes das câmeras"*). O bordo precisa aplicar a
   chave do nome no **cadastro local** da câmera (não só publicar o nome dele para cá) e o painel do bordo
   (/bordo) tem de mostrar o nome novo.
3. Mostrar **desejada × aplicada** (`config_aplicada_bordo` hoje vazio) — inclusive o que o bordo
   **recusou**, com motivo.
4. O **alvo de qualidade** (`1500k…300k`) sai da tabela gigante e passa a viver no cartão daquela câmera.
5. Mostrar o que o **próprio bordo** se configurou (`config_local`, hoje vazio) e o painel do bordo
   (`/bordo`) como o bordo o vê — é o "como esta máquina se configurou sozinha" que já existe a bordo.

### Fase 4 — Escopo, licença e limpeza (P1)

1. **Licença por embarcação dentro do cliente**: emitir/ver a chave (com os 4 últimos dígitos na lista e a
   chave inteira sob clique do admin, como já é a regra), `maquinas_max`, status, último uso.
2. **Usuários por cliente/embarcação**: quem é admin, operação e cliente; atribuir embarcações
   (`usuario_embarcacoes` está com 0 linhas) para os 4 escopos do dono (1 embarcação / N / todas da
   empresa / todas as empresas-Petrobras).
3. **Separação bancada × produção**: uma marca clara (ex.: cliente interno `LECSOR (interno)` e
   embarcação `bancada`) para os dados de teste não aparecerem na configuração de um cliente real.

### Fase 5 — Prova (P0, fecha a rodada)

1. Teste ponta a ponta novo: **a varredura do bordo cria a câmera → ela aparece na área do CLIENTE certo
   com o nome do dispositivo → clicar em Ligar → o desejo chega ao bordo → o bordo liga e reporta "no ar"
   → a tela mostra "no ar"**. Sem medida = não é OK (a regra do smoke).
2. Regressão (`tools/regressao-0100.py` + `tests/regressao-smoke.py`) verde.
3. Ver o **navegador de verdade** na tela nova (preview/print) — é a prova que o dono cobra para "não está
   mais truncado".
4. Publicação: `main` + release + deploy do terra + nota no vault, com o antes/depois por número.

---

## 4. Decisões FECHADAS pelo dono (23/11/2026) — o fluxo, na ordem da vida real

> "o correto é eu criar a empresa caso ainda não tenha sido criada, depois embarcação vinculada àquela
> empresa, gero a chave na embarcação, na embarcação aparecem as câmeras encontradas na varredura, configuro
> as câmeras e a captura pega as informações e replica no app de captura, inclusive os nomes das câmeras. a
> tela de usuários pode ficar fora, mas preciso vincular o usuário à empresa e/ou embarcação, petrobrás, etc.
> tempo real, produção e câmeras é a mesma coisa, não precisa dividir"

**O caminho vira o menu do admin, nesta ordem:**

1. **Empresa** (cliente): cria primeiro, se ainda não existir (`lecsor`, `armador-demo`, …).
2. **Embarcação** vinculada àquela empresa: cria abaixo dela.
3. **Chave gerada NA EMBARCAÇÃO** (a licença é por embarcação — é o que já é hoje).
4. **Na embarcação aparecem as câmeras que a varredura achou** (com o id do dispositivo e o nome do
   dispositivo) — o PC de captura que tem aquela licença publica a varredura para aquela embarcação.
5. **Configurar as câmeras ali** (nome inclusive) e **a captura pega as informações e replica no app de
   captura** — configuração desce de terra para o bordo (pelo caminho que o bordo já olha:
   `/api/config-desejada`; o bordo aplica e confirma em `/api/config-aplicada`). **O nome que o admin der é
   o nome que passa a valer no PC de captura.**

**Fechado também:**

| # | Decisão |
|---|---|
| D1 | **A câmera é o que a varredura achou.** O admin não inventa câmera: ele configura a que apareceu (nome, taxa, ativo) — o nome escolhido replica no bordo. |
| D2 | **A embarcação da câmera é a da licença daquela máquina** (automática) — é a embarcação em cujo contexto a varredura chega. |
| D4 | **"Câmeras", "Tempo real" e "Produção" são UMA coisa só** (uma aba, um lugar): a câmera com situação, o que o bordo declarou, o vídeo ao vivo e os números de produção juntos na mesma linha/cartão. Não dividir. |
| D5 | **A tela "Usuários" fica FORA** da área do cliente, **mas** o usuário passa a ser vinculado a **empresa e/ou embarcação** (é o que dá o escopo 1/2/3 e o caso Petrobras — todas as empresas). |
| D6 | **A tela que o dono viu truncada é a de câmeras** (medida: tabela de 12 colunas com 23 linhas dentro de `.rolagem{max-height:52vh}`) — morre na Fase 2, virando cartão por câmera. |
| D3 | Fica valendo o desenho: bancada/teste não some do banco, mas **não aparece no caminho de um cliente real** (as ~15 câmeras velhas vivem na empresa interna `LECSOR (interno)` / `bancada`). |

**Único ponto que eu ainda proponho (aprovar junto com o plano):** a lista fechada de chaves de
configuração por câmera nesta rodada = **nome/rótulo**, **qualidade de envio** (`1500k…300k`), **ativo** e
**desligar/ligar na mão** (o `manual`). Qualquer outra chave entra depois, quando aparecer.

---

## 5. Critério de aceite (o que o dono vê quando estiver pronto)

1. O caminho é um só, na ordem que o dono descreveu: **criar a empresa → criar a embarcação dentro dela →
   gerar a chave na embarcação → as câmeras da varredura aparecem ali → configurar** (tudo numa área; as
   páginas viram abas dentro da empresa/embarcação; "Usuários" fica fora, com vínculo a empresa/embarcação).
2. A câmera que a **varredura** achou aparece **com o nome do dispositivo**, marcada como achada pela
   varredura, e dá para **configurar (nome inclusive) e ligar** ali mesmo, com o resultado na cara — e o
   **nome que o dono der volta para o PC de captura** (replicado lá, como ele pediu).
3. Nenhuma tela cortada: a lista de câmeras não é mais uma tabela larga de 12 colunas dentro de uma caixa
   de 52vh.
4. Nenhuma credencial em tela; nada apagado (as de bancada só saem do caminho).
5. Prova com número (teste ponta a ponta + regressão + tela real) e publicação (GitHub + VPS + release +
   nota no vault).
