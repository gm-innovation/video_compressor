# Câmera IP: cadastro no admin, apontamento pelo app de captura e edição de cliente/embarcação/câmera

Pedido do dono (25/11/2026, verbatim):

> preciso poder cadastrar câmeras ip, e como diz a regra, o app de captura precisa visualisar esse ip e fazer
> o apontamento

> estou com o admin aberto e não vejo onde editar as câmeras, embarcações e clientes

Status: **decisões D1-D4 registradas em 25/11/2026 (seção 4) — plano fechado, aguardando "aprovado" para implementar** (nada implementado ainda).

---

## 1. O que já existe (medido no código, não é hipótese)

| # | Peça | Onde | Estado |
|---|---|---|---|
| 1 | Cadastro de câmera **com IP** | `POST /api/cameras` (ground/api.py:4154) grava `ip, porta, protocolo, canal` na tabela `cameras` | **existe** |
| 2 | Formulário do cadastro | admin/admin.js:575-598 — "Câmera: onde ela está e por onde entra" (rótulo, fluxo, **IP da câmera ou gravador**, porta 554, canal) | **existe** |
| 3 | Editar câmera | `POST /api/cameras/<id>/editar` (ground/api.py:4310) muda rótulo/embarcação/ip/porta/protocolo/canal/fluxo | **existe** |
| 4 | Botão "editar" da câmera | admin/admin.js:749-764 — abre um `prompt()` só com o endereço (`IP:porta`) | **existe, mal descoberto** |
| 5 | Criar empresa / criar embarcação | admin/admin.js:2366-2435 ("Empresas e configuração") | **existe (só criar)** |
| 6 | **Editar** empresa / embarcação | — | **NÃO existe** (só criar; sem editar nome/IMO) |
| 7 | Canal terra→bordo | o "desejo" leva `{camera_id, fluxo_id, desejo, versao, motivo, transmissao_id}` (ground/api.py:605) | **não leva o IP** |
| 8 | Entrada do ffmpeg no bordo | `board/agent.py:29-39` — só `-f dshow` (câmera física desta máquina) ou `-f lavfi` (fonte sintética) | **não abre `rtsp://`** |
| 9 | URL RTSP montada no terra | ground/api.py:3256 (`rtsp://$USUARIO:$SENHA@ip:porta/canal`) — só para a tela de operação | existe do lado terra |

**Conclusão medida:** cadastrar câmera IP no admin **já dá** (o formulário existe), mas o **apontamento não
existe**: o app de captura **nunca recebe o IP** (item 7) e o agente dele **não abre RTSP** (item 8). É esse o
buraco do pedido — não o cadastro.

Onde está a edição hoje (resposta ao dono): menu **"Empresas e configuração"** → **Abrir** na empresa →
cartão da embarcação → botão **"editar"** na linha da câmera (abre um `prompt` com o endereço). O menu ainda
tem um grupo **"Avançado (telas antigas)"** com Clientes / Embarcações / Câmeras — são telas antigas (tabelas),
mantidas só para não quebrar link salvo; **não** editaram nada.

---

## 2. Fases

### Fase 1 — Cadastro de câmera IP no admin (P0)

- No formulário "Câmera: onde ela está e por onde entra": **tipo de entrada** explícito —
  `USB/dshow desta máquina` (o que a varredura acha) × `Rede (IP)` (o que se digita).
- Campo `protocolo` (rtsp padrão; https/onvif como opção) e o campo de **canal** com o exemplo do gravador.
- **Credencial nunca no formulário nem no banco/chat/repo** (regra do dono): o cadastro guarda só o
  endereço e o **identificador do segredo** (o nome do arquivo no PC de captura, ex.: `cam-01`); a senha
  vive **só** no PC de captura, no arquivo de ACL restrita (D1), e chega à tela **apenas** como
  "segredo configurado: sim/não".
- (P1) Aviso na tela quando o IP for de rede e o **arquivo do segredo** não existir no PC de captura (D1).
- **A câmera IP convive com a de HDMI/split (D2)**: o cadastro novo não desliga nem substitui nenhuma câmera
  que já existe na embarcação; as duas entram na grade pela mesma regra de `rotulo`.

### Fase 2 — O app de captura VÊ o IP e APONTA (P0) — o coração do pedido

- **Terra → bordo**: o "desejo" (e o retrato do cadastro que o bordo já busca) passa a levar, por câmera,
  `entrada` (usb|rede), `ip`, `porta`, `protocolo`, `canal` e o **nome da variável** do segredo — **nunca a
  senha**.
- **Bordo**: `board/agent.py` ganha a entrada de **rede** — `-rtsp_transport tcp -i rtsp://usuario:$SEGREDO@ip:porta/canal`
  (a senha lida da **variável de ambiente** do serviço, na hora de montar o comando). Rede sem rota = erro
  **na tela do bordo e na saúde que sobe ao admin**, nunca silêncio.
- Troca de endereço no admin → o bordo **reaponta** (reabrir o envio sem reiniciar o app), pelo mesmo caminho
  do `/api/cameras/<id>/editar` que já reabre o que mudou na fonte.
- (P1) Aviso/limite: uma câmera IP que não responde entra em `erro` com o motivo (timeout, 401, canal
  inexistente) em vez de "sem entrada".

### Fase 3 — O app de captura mostra o apontamento (P0)

- Na tela do bordo, cada câmera mostra **de onde está puxando** (`USB · câmera X` × `IP 10.0.0.7:554 canal 1`)
  e o estado do apontamento (apontando / sem rota / senha recusada).
- (P2) No **admin**, coluna "aponta para" por câmera, para o dono conferir sem ir ao barco.

### Fase 4 — Editar cliente / embarcação / câmera no admin (P0)

- **Empresa (cliente)**: editar **nome** **e o identificador** (D3) — a renomeação da chave vai na transação
  do item D3, com auditoria e recusa se algum filho não puder ser atualizado.
- **Embarcação**: editar **nome**, **IMO** e o **identificador** (mesmo rito do D3); mostrar/alterar o vínculo
  com a empresa.
- **Só admin (D4)**: as rotas de configuração passam a exigir `papel == "admin"` (não `PAPEL_ADMIN`, que inclui
  `operador`); a operação continua com operador+admin.
- **Câmera**: trocar o `prompt()` (admin/admin.js:749) por **formulário no cartão** — rótulo, fluxo, entrada
  (USB/rede), IP, porta, protocolo, canal, ativo — com o mesmo contrato do `editar` que já existe no servidor.
- (P1) O menu "Avançado (telas antigas)" passa a **apontar** para a área única (ou sai), para o dono não cair
  numa tela que não edita nada.

### Fase 5 — Provas e publicação (P0)

- e2e novos: (a) cadastro de câmera IP pelo admin e o **IP chegando ao bordo** (payload, sem a senha em lugar
  nenhum); (b) o agente monta o comando `rtsp://` com o segredo vindo da variável de ambiente; (c) editar
  nome de empresa/embarcação/câmera pelo formulário novo; (d) o `prompt()` não existe mais.
- Suíte `tools/regressao-0130.py` verde e `unittest` OK; bump, build e release (rito da 0.17.0).

---

## 3. Critério de aceite

1. No admin: cadastro de câmera **IP** (com porta/canal), edição de **empresa**, **embarcação** e **câmera**
   por formulário (sem `prompt`).
2. O app de captura **recebe o IP** do cadastro e **aponta** o ffmpeg para `rtsp://…` com a senha vinda da
   **variável de ambiente** do PC de captura — senha que **não** aparece no chat, no banco, no repositório nem
   na tela.
3. Trocar o IP no admin faz o bordo reapontar; falha de rota/senha aparece como **erro na tela do bordo** e na
   saúde que o admin vê.
4. Provas acima verdes e publicadas (0.18.0).

---

## 4. Decisões do dono (25/11/2026) e o que cada uma obriga

- **D1. "a forma mais segura" → o segredo não sai do PC de captura.** O cadastro guarda **só o nome da
  variável** de ambiente; a senha vive **apenas** no PC de captura, num **arquivo com permissão restrita**
  (`C:\ProgramData\LECSOR\segredos\cam-<id>.txt`, ACL só do serviço — sem `Usuários`), lido em memória na hora
  de montar o comando. Nunca no banco, no repositório, no chat, na API (nenhuma rota devolve) nem na tela.
  **Limite honesto:** com RTSP o ffmpeg recebe a URL com a credencial, então ela aparece na linha de comando
  do processo — visível a **admin local** daquela máquina. Vou documentar isso no plano; se o dono quiser
  zero-exposição, a alternativa é um proxy local (o `mediamtx` já vai no pacote) publicando o fluxo em
  `127.0.0.1` e o ffmpeg consumindo de lá, sem credencial na linha de comando.
- **D2. Convive.** A câmera IP **não** substitui a de HDMI/split: as duas aparecem na mesma embarcação e
  podem estar na mesma grade (a grade já é por câmera). Ordenação por `rotulo`.
- **D3. Identificador renomeável.** Medido: o `db/schema-fase4.sql` declara `REFERENCES clientes(id)` /
  `embarcacoes(id)` **sem `ON UPDATE CASCADE`** e o banco roda com `PRAGMA foreign_keys = ON`
  (ground/api.py:158) — então renomear a chave **quebra** o update se os filhos não forem tratados. Renomear
  = **transação única** atualizando os filhos antes do pai, listando as tabelas que referenciam
  (`embarcacoes.cliente_id`, `cameras.embarcacao_id`, `usuarios.cliente_id`, e as de `schema-transmissao.sql`
  /`fase6`/`fase7` que carregam `embarcacao_id`), **com auditoria** (`empresa_renomeada`, de → para) e
  recusa se algo falhar. As de histórico/auditoria mantêm o texto antigo de propósito (trilha imutável).
- **D4. Só admin.** Hoje `PAPEL_ADMIN = ("operador", "admin")` (ground/api.py:146) e **o mesmo** conjunto
  governa as ações de operação (desligar/cancelar/envios), não só o cadastro. Então a regra "só admin" será
  aplicada **só às rotas de configuração** (`/api/clientes`, `/api/embarcacoes`, `/api/cameras`,
  `/api/cameras/<id>/editar|nome|alvo|ativo|remover`, `/api/usuarios`); a operação segue com operador+admin.
  Efeito colateral a tratar nas provas: os testes que hoje entram como **operador** para configurar
  (`tests/e2e-licenca-no-admin.py`, `tests/e2e-escopo-no-admin.py`, `tests/e2e-admin-unificado.py`, entre
  outros) passam a precisar do papel admin — **nenhuma** prova pode ficar medindo o operador editando.
