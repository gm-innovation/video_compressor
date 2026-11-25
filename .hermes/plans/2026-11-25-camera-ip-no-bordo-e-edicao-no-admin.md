# Câmera IP: cadastro NO APP DE CAPTURA (IP e senha nunca saem do bordo) e edição de cliente/embarcação/câmera no admin

Pedido do dono (25/11/2026, verbatim):

> preciso poder cadastrar câmeras ip, e como diz a regra, o app de captura precisa visualisar esse ip e fazer
> o apontamento

> estou com o admin aberto e não vejo onde editar as câmeras, embarcações e clientes

Decisão do dono que **manda no desenho** (25/11/2026, verbatim, resposta a D1):

> não entendo nada disso, senha não pode vazar, então tem que tudo ficar no bordo, então não vamos poder
> inserir nem o ip no admin, o cadastro das câmeras ip terão que ser no app de captura

Status: **revisado com a decisão acima — aguardando "aprovado"** (nada implementado).

---

## 1. O que muda no pedido (e por que)

O dono **não quer** o cadastro de câmera IP no admin: endereço e senha ficam **só no app de captura (bordo)**.
Isso simplifica o plano e casa com o que já está no código:

| # | Peça | Onde | Estado |
|---|---|---|---|
| 1 | O bordo publica para o terra **sem endereço** | `_anuncio_bordo` (ground/api.py:4947) envia `id, fluxo_id, rotulo, ativo, embarcacao_id, remover` | **já é assim — não leva IP** |
| 2 | O endereço da câmera nunca vai ao app do cliente | `GET /api/cameras/detalhe` (ground/api.py:3245) recusa fora de `_local()`/operação; a URL `rtsp://…` (3256) só sai aí | **já é assim** |
| 3 | Cadastro local de câmera | `POST /api/cameras` (ground/api.py:4154) aceita `_local()` — é o bordo que grava no banco dele | **existe** |
| 4 | Formulário do cadastro **hoje fica no admin** | admin/admin.js:575-598 — "Câmera: onde ela está e por onde entra" (rótulo, fluxo, **IP da câmera ou gravador**, porta 554, canal) | **existe — sai o IP** (decisão do dono) |
| 5 | Editar câmera (servidor) | `POST /api/cameras/<id>/editar` (ground/api.py:4310), chaves `rotulo, embarcacao_id, ip, porta, protocolo, canal, fluxo_id` | **existe** |
| 6 | Botão "editar" da câmera | admin/admin.js:749-764 — `prompt()` só com o endereço | **existe, mal descoberto** |
| 7 | Criar empresa / criar embarcação | admin/admin.js:2366-2435 ("Empresas e configuração") | **existe (só criar)** |
| 8 | **Editar** empresa / embarcação | — | **NÃO existe** |
| 9 | Entrada do ffmpeg no bordo | `board/agent.py:29-39` — só `-f dshow` (câmera física) ou `-f lavfi` (sintética) | **não abre `rtsp://`** |

**Conclusão medida:** o cadastro de câmera IP **hoje** vive no admin (item 4) e o agente do bordo **não sabe
abrir RTSP** (item 9) — é o buraco. Do lado da segurança, o caminho já está certo: o que o bordo manda ao terra
não tem endereço (item 1) e o endereço só é servido a quem é da máquina de captura (item 2). Falta **tirar o IP
do admin** e **pôr o cadastro no bordo**, com o agente apontando.

Onde está a edição hoje (resposta ao dono): menu **"Empresas e configuração"** → **Abrir** na empresa → cartão
da embarcação → botão **"editar"** na linha da câmera (um `prompt` com o endereço). O grupo **"Avançado (telas
antigas)"** (Clientes / Embarcações / Câmeras) são telas antigas (tabelas), mantidas para não quebrar link
salvo — **não** editam nada.

---

## 2. Fases

### Fase 1 — Cadastro de câmera IP NO APP DE CAPTURA (P0)

- Onde: na tela do bordo (o app instalado no PC de captura), campo "onde ela está e por onde entra" com
  **tipo de entrada** `USB/dshow desta máquina` × `Rede (IP)`; em `Rede`: `ip`, `porta` (554), `protocolo`
  (rtsp padrão) e `canal` (com o exemplo do caminho do gravador).
- **A senha nunca é digitada em formulário** (regra do dono): fica num **arquivo local no PC de captura**
  (`C:\ProgramData\LECSOR\segredos\cam-<id>.txt`) com permissão restrita ao serviço — sem `Usuários` — e a tela
  mostra só **"segredo configurado: sim/não"**. Nada disso vai para o terra.
- O cadastro grava **no banco do próprio bordo** (item 3); para o terra sobe só o que o `_anuncio_bordo` já
  manda (rótulo/fluxo/ativo) — **o IP nunca sobe**.
- (P1) Aviso na tela quando `Rede (IP)` estiver escolhido e o arquivo do segredo não existir.
- **A câmera IP convive com a de HDMI/split (D2)**: não desliga nem substitui nenhuma câmera já existente; as
  duas entram na grade pela mesma regra de `rotulo`.
- (P1) Campo avançado opcional para o **caminho completo** do RTSP, para gravador cujo caminho não é
  `Streaming/Channels/<canal>`.

### Fase 2 — O app de captura APONTA para a câmera IP (P0) — o coração do pedido

- `board/agent.py` ganha a entrada de **rede**: `-rtsp_transport tcp -i rtsp://usuario:$SEGREDO@ip:porta/canal`
  — o `$SEGREDO` lido **em memória, do arquivo local, na hora de montar o comando**; o cadastro local é a
  única fonte do endereço (não existe canal terra→bordo de IP).
- Rede sem rota / senha recusada / canal errado = **erro na tela do bordo e na saúde que sobe ao admin**,
  nunca silêncio.
- Trocar o endereço **no bordo** faz o app **reapontar** (reabrir o envio sem reiniciar), no mesmo caminho que
  já reabre o que mudou na fonte (`fonte_mudou` em ground/api.py:4348).
- (P1) A câmera IP que não responde entra em `erro` com o motivo (timeout, 401, canal inexistente) em vez de
  aparecer como "sem entrada".

### Fase 3 — O bordo mostra o apontamento; o admin vê a câmera sem endereço (P0)

- Na tela do bordo, cada câmera mostra **de onde está puxando** (`USB · câmera X` × `IP 10.0.0.7:554 canal 1`)
  e o estado (apontando / sem rota / senha recusada).
- **No admin, o campo de IP sai do formulário de câmera** (decisão do dono) — o admin segue com rótulo, fluxo,
  alvo/qualidade e transmitir, e a câmera aparece pelo rótulo que o bordo anunciou.

### Fase 4 — Editar cliente / embarcação / câmera no admin (P0)

- **Empresa (cliente)**: editar **nome** e o **identificador** (D3, transação nos filhos, ver seção 4).
- **Embarcação**: editar **nome**, **IMO** e o **identificador**; mostrar/alterar o vínculo com a empresa.
- **Câmera**: trocar o `prompt()` (admin/admin.js:749) por **formulário no cartão** — rótulo, fluxo, ativo,
  alvo/qualidade — **sem endereço** (o endereço é do bordo).
- **Só admin (D4)**: as rotas de configuração passam a exigir `papel == "admin"` (não `PAPEL_ADMIN`, que inclui
  `operador`); a operação segue com operador+admin.
- (P1) O grupo "Avançado (telas antigas)" passa a apontar para a área única (ou sai), para o dono não cair numa
  tela que não edita nada.

### Fase 5 — Provas e publicação (P0)

- e2e novos: (a) cadastro de câmera IP **na tela do bordo** grava o endereço **só no banco do bordo**;
  (b) o `_anuncio_bordo` para o terra **não** leva o IP (asserção no payload); (c) `board/agent.py` monta o
  comando `rtsp://…` com o segredo vindo do arquivo local, sem a senha em nenhum log/tela/API; (d) editar nome
  e identificador de empresa/embarcação pelo formulário novo; (e) o `prompt()` do endereço **não existe mais**;
  (f) o formulário do admin **não** tem campo de IP.
- Suíte `tools/regressao-0130.py` verde e `unittest` OK; bump para 0.18.0, build e release (rito da 0.17.0).

---

## 3. Critério de aceite

1. A câmera IP é cadastrada **no app de captura** (endereço, porta, canal) e **o admin não pede IP em nenhum
   formulário**; o terra **nunca** recebe o endereço.
2. A senha existe **só** no arquivo local do PC de captura (ACL restrita), nunca digitada em formulário, nunca
   no banco do terra, no repositório, no chat, em log ou em resposta de API — a tela mostra só
   "segredo configurado: sim/não".
3. O app de captura **aponta** o ffmpeg para `rtsp://…` a partir do cadastro local e, sem rota/senha/canal,
   mostra **erro** na tela do bordo e na saúde que o admin vê.
4. No admin: editar **empresa**, **embarcação** e **câmera** (rótulo/fluxo/ativo/qualidade) por formulário, sem
   `prompt`; cadastro/edição só com papel **admin**.
5. Provas acima verdes e publicadas (0.18.0).

---

## 4. Decisões do dono (25/11/2026) e o que cada uma obriga

- **D1. "a forma mais segura" + "tudo tem que ficar no bordo" → o endereço E a senha não saem do PC de
  captura.** O cadastro da câmera IP é no app de captura; o terra não recebe IP (o `_anuncio_bordo` já não leva,
  item 1) e nenhuma rota serve o endereço fora da máquina de captura (item 2). A senha é arquivo local com ACL
  restrita — nunca em formulário, banco, repositório, chat, log ou tela.
- **D2. Convive.** A câmera IP **não** substitui a de HDMI/split: as duas ficam na mesma embarcação e podem
  estar na mesma grade (a grade já é por câmera). Ordenação por `rotulo`.
- **D3. Identificador renomeável.** Medido: o `db/schema-fase4.sql` declara `REFERENCES clientes(id)` /
  `embarcacoes(id)` **sem `ON UPDATE CASCADE`** e o banco roda com `PRAGMA foreign_keys = ON`
  (ground/api.py:158) — renomear a chave **quebra** o update se os filhos não forem tratados. Renomear =
  **transação única** atualizando os filhos antes do pai, listando quem referencia
  (`embarcacoes.cliente_id`, `cameras.embarcacao_id`, `usuarios.cliente_id`, e as de `schema-transmissao.sql` /
  `fase6` / `fase7` com `embarcacao_id`), **com auditoria** (`empresa_renomeada`, de → para) e recusa se algo
  falhar. As tabelas de histórico/auditoria mantêm o texto antigo de propósito (trilha imutável).
- **D4. Só admin.** Hoje `PAPEL_ADMIN = ("operador", "admin")` (ground/api.py:146) e **o mesmo** conjunto
  governa as ações de operação (desligar/cancelar/envios), não só o cadastro. A regra "só admin" vale **só para
  as rotas de configuração** (`/api/clientes`, `/api/embarcacoes`, `/api/cameras`,
  `/api/cameras/<id>/editar|nome|alvo|ativo|remover`, `/api/usuarios`); a operação segue com operador+admin.
  Efeito colateral a tratar nas provas: os testes que hoje entram como **operador** para configurar
  (`tests/e2e-licenca-no-admin.py`, `tests/e2e-escopo-no-admin.py`, `tests/e2e-admin-unificado.py`, entre
  outros) passam a precisar do papel admin — **nenhuma** prova pode ficar medindo o operador editando.
