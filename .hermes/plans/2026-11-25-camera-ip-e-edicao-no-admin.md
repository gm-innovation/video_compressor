# Câmera IP: cadastro no admin, apontamento pelo app de captura e edição de cliente/embarcação/câmera

Pedido do dono (25/11/2026, verbatim):

> preciso poder cadastrar câmeras ip, e como diz a regra, o app de captura precisa visualisar esse ip e fazer
> o apontamento

> estou com o admin aberto e não vejo onde editar as câmeras, embarcações e clientes

Status: **aguardando "aprovado"** (nada implementado).

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
  endereço e o **nome da variável de ambiente** que o PC de captura deve ter (ex.: `LECSOR_CAM_CAM01_SENHA`),
  com a senha digitada **no PC de captura**, por variável de ambiente do serviço — como já é a regra.
- (P1) Aviso na tela quando o IP for de rede e a variável do segredo não estiver declarada no cadastro.

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

- **Empresa (cliente)**: editar **nome** (e o identificador com trava — ele é chave de várias tabelas).
- **Embarcação**: editar **nome** e **IMO**; mostrar/alterar o vínculo com a empresa.
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

## 4. Decisões que preciso do dono (responder 1-4)

- **D1.** Câmera IP: a senha fica em **variável de ambiente no PC de captura** (`LECSOR_CAM_<ID>_SENHA`), uma
  por câmera? (a regra diz: credencial nunca em chat/e-mail/repositório)
- **D2.** A câmera IP **substitui** a câmera por HDMI/split na mesma embarcação, ou convive com ela (as duas
  podem aparecer juntas na grade)?
- **D3.** O identificador da empresa/embarcação (chave primária) pode ser **renomeado** ou fica travado depois
  de criado (só o nome de exibição muda)?
- **D4.** Editar continua exigindo **operador/admin** (como hoje) e a captura segue **só cadastrando**?
