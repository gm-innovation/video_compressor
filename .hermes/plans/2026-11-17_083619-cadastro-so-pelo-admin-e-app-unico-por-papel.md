**Status:** aguardando aprovação

# Cadastro de usuário só pelo Admin + um app só, com a tela definida pela role

**Pedido do dono (17/11/2026, verbatim):** *"olha só, estamos tendo muitos problemas, um usuário não pode se
cadastrar, quem cadastra os usuários é o admin, outra coisa, vamos empacotar em um app apenas, o tipo de
app é definido pela role do usuário, faça o plano para isso"*.

**Ordem de execução:** Fase 1 (fechar o cadastro por fora + fazer o usuário criado pelo admin conseguir
entrar) → Fase 2 (consertar quem já está sem credencial e mostrar isso na tela) → Fase 3 (um app só, tela
pela role) → Fase 4 (publicar 1 instalador e migrar as máquinas dos 4 antigos).
Duas decisões suas (abaixo) travam as Fases 3 e 4; as Fases 1 e 2 rodam sem esperar nada.

## Evidência mecânica (levantada em 17/11/2026, cada linha com como foi verificado)

| Fato | Como foi verificado |
|---|---|
| **O cadastro público está ABERTO no Supabase do produto** (`disable_signup: false`, `mailer_autoconfirm: false`) | `GET {LECSOR_SUPABASE_URL}/auth/v1/settings` com a chave anônima do próprio pacote (`desktop/ambiente.json`); a chave não foi impressa em lugar nenhum. Resposta: `disable_signup: False`, `mailer_autoconfirm: False` |
| **O login ADOTA quem o Supabase reconhece, mesmo sem cadastro aqui**: cria a linha local e entra | `ground/api.py:1226-1240` (`/api/entrar`) + `ground/api.py:1866-1893` (`_adotar_do_supabase`, papel nasce `cliente`, menor privilégio) |
| **Usuário criado pelo admin NÃO consegue entrar** (quando o Supabase está configurado) | `ground/api.py:1545-1572` (`POST /api/usuarios`, só admin) grava **só** no banco local com senha sorteada; `grep -rn "criar_usuario"` no repo: a chamada existe **só** em `ground/migrar-login-supabase.py:64`. Como `supabase_auth.entrar` devolve `{"ok": false}` quando o Supabase responde que a credencial não vale (`ground/supabase_auth.py:48-68`) e `ground/api.py:1234-1236` exige `veredito.ok` **e** linha local, o resultado é `401` |
| **A mesma lacuna vale para o primeiro acesso**: a sessão vale na hora, mas a credencial não existe no Supabase | `ground/api.py:1246-1285`: cria o admin local (adota a identidade do Supabase se ela existir) e devolve a sessão; sem `criar_usuario`, o login seguinte com a mesma senha cai em `401` |
| **Hoje há 4 instaladores, cada um com superfície e papel fixos no pacote** | `desktop/construir-instaladores.sh:49-57` (`construir "LECSOR Captura" bancada captura captura 1` … 4 linhas) + `desktop/main.js:11-24` (lê `package.json.superficie`/`papel`) |
| **O pacote já leva TUDO dentro** (ffmpeg, mediamtx, Python portátil, `ground/`, `fronts/`, `admin/`, `app/`, `portal/`, `board/`, `db/`, `analytics/`) | `desktop/package.json` → `extraResources` (13 entradas) |
| **As telas são 3 e já sabem reusar sessão existente** | `desktop/main.js:145-150`: `cliente→/app`, `admin→/admin`, `bancada→/`; `app/app.js:33-34` e `admin/admin.js:80-81` leem `/api/eu` e abrem o que já está logado |
| **Papéis do usuário são só 3** | `db/schema-fase4.sql:41`: `papel TEXT NOT NULL CHECK (papel IN ('cliente','operador','admin'))` |
| **Uma conta de cliente que abre `/admin` vê a tela de "primeiro acesso"** (a tela convida a cadastrar) | `admin/admin.js:81`: `papel === 'cliente'` → `conferirPrimeiroAcesso()`; `admin/admin.js:45-59` mostra o formulário só quando a API diz `precisa` (zero usuários na máquina) |

## Escopo

**Entra:** fechar o cadastro pelo próprio usuário no Supabase **e** no nosso código; fazer o usuário criado
pelo admin conseguir entrar (credencial nos dois lados); tela de usuários do Admin dizendo o estado da
credencial e permitindo redefinir senha; **um** instalador que abre a tela da role do usuário; publicação e
migração dos 4 pacotes antigos.

**Fica FORA (declarado):** remover/reescrever `ground/migrar-login-supabase.py`; mexer em RLS/migrações do
Supabase; login social (Google/Apple/etc.); trocar o Supabase Auth por autenticação própria; desenho novo
das telas (o lado visual das 3 superfícies não muda).

## Decisões que preciso de você

- **D1 — quem vê a captura ("Enviar vídeo")?** Você disse que **a role define o tipo de app**. Hoje não
  existe role para o técnico a bordo (só `cliente`, `operador`, `admin`). Proposta assumida por padrão:
  criar o papel **`tecnico`** (bordo) — só vê "Enviar vídeo" e as câmeras da máquina; o menu "Liberar as
  funções de captura nesta máquina" (0.5.0) continua para ligar a captura **na máquina**.
  **Alternativa:** qualquer usuário cuja máquina tenha a captura liberada vê a tela — sem papel novo.
- **D2 — quem desliga o cadastro público no Supabase?** É a conta do projeto. Padrão assumido: você faz
  pelo painel (passo a passo na Fase 1) e eu confirmo por comando; se preferir que eu faça direto, deposite
  um PAT em `~/.hermes/vps-deploy/supabase-pat.txt` (nunca na conversa) que eu chamo a Management API e
  provo o estado depois.

---

## Fase 1 — Cadastro só pelo Admin (P0), e o usuário criado pelo admin entra (P0)

**Custo:** médio (2 arquivos de código + 1 teste novo + 1 comando no painel). **Dependência:** D2 (o
fechamento no Supabase) — o resto roda sem ninguém.

- **P0 — fechar o cadastro público no Supabase.** Painel do Supabase → projeto do produto → **Authentication
  → Sign In / Providers → Email**: desligar **"Allow new users to sign up"** e salvar. (Passo a passo para
  repassar: *Entrar em supabase.com → abrir o projeto → menu Authentication → Providers → Email →
  desmarcar "Allow new users to sign up" → Save.*)
  **Aceite:** `python tools/conferir-signup.py` → `disable_signup: True` (script novo, só lê a chave do
  pacote e imprime o estado, nunca a chave).
- **P0 — parar de adotar identidade de fora no login.** Em `ground/api.py:1226-1240`, o `/api/entrar` deixa
  de chamar `_adotar_do_supabase`: entra **só** quem já existe **e está ativo** na base local. Se o Supabase
  reconhecer a credencial mas o e-mail não estiver cadastrado aqui → `403` com a mensagem *"esta conta não
  está cadastrada nesta instalação: quem cadastra usuários é o administrador"*. O caminho sem rede continua
  igual (Supabase não respondeu → confere o hash local). `_adotar_do_supabase` fica no arquivo apenas para
  o `/api/primeiro-acesso` (instalação nova, zero usuários, só na própria máquina).
  **Aceite:** teste novo `tests/test-cadastro-so-pelo-admin.py` (servidor real em porta livre, `supabase_auth`
  dublado no próprio processo) → *Supabase reconhece e-mail que não existe localmente ⇒ `403` e **nenhuma**
  linha criada em `usuarios`*.
- **P0 — dar credencial no Supabase ao usuário que o admin cria.** Em `POST /api/usuarios`
  (`ground/api.py:1545-1572`): depois de gravar a linha local, chamar
  `supabase_auth.criar_usuario(email, senha, nome)` (`ground/supabase_auth.py:92`, idempotente, chave de
  serviço **só no servidor**). Falha de rede/serviço ⇒ a resposta passa a trazer
  `"supabase": "falhou"` (a senha inicial já foi entregue e a tela avisa), nunca silêncio.
  **Aceite:** mesmo teste → *usuário criado pelo admin ⇒ `criar_usuario` foi chamado com o mesmo e-mail e a
  mesma senha inicial; `login` desse usuário entra (200 com `papel`)*.
- **P0 — o mesmo para o primeiro acesso.** Em `/api/primeiro-acesso` (`ground/api.py:1246-1285`), depois de
  criar o admin local, chamar `criar_usuario` com a senha digitada, para o login seguinte funcionar.
  **Aceite:** o teste prova `criar_usuario` chamado também nesse caminho.
- **P1 — a tela "primeiro acesso" não pode aparecer para quem não é o dono da máquina.** Em
  `admin/admin.js:81`, conta com `papel === 'cliente'` deixa de cair em `conferirPrimeiroAcesso()`: mostra
  *"esta conta é de cliente: abra a tela do cliente"* (mesma mensagem do login, `admin/admin.js:75`).
  **Aceite:** teste de tela (leitura do JS) + `tests/e2e-desktop.py` verde.
- **P2 — auditoria.** `auditar(...)` com `criar_usuario_supabase` / `adocao_recusada`, para a tela de
  Auditoria mostrar quem tentou entrar sem cadastro. **Aceite:** linha nova aparece em `GET /api/auditoria`.

## Fase 2 — Consertar quem ficou sem credencial e mostrar o estado na tela (P1/P0)

**Custo:** baixo. **Dependência:** nenhuma (roda logo após a Fase 1).

- **P0 — redefinir senha pelo Admin.** Novo `POST /api/usuarios/<id>/senha` (só `admin`): gera senha nova,
  grava o hash local **e** chama `criar_usuario`/atualiza no Supabase, devolvendo a senha **uma vez**.
  `auditar(u, "redefinir_senha", ...)`. **Aceite:** teste prova o duplo registro e o `403` para não-admin.
- **P1 — a lista de usuários mostra a credencial.** `GET /api/usuarios` (`ground/api.py:1152-1158`) ganha
  `supabase: sim/não` por usuário (via `supabase_auth.id_por_email`) e a tela `admin/admin.js` mostra a
  coluna + o botão *"redefinir senha"*. **Aceite:** a lista mostra a coluna e o botão; teste cobre o campo.
- **P2 — texto na tela de Usuários:** *"Quem cadastra usuários é o administrador. Não existe cadastro pelo
  próprio usuário."* **Aceite:** a frase aparece no `admin/index.html`/`admin.js` e o teste checa a string.

## Fase 3 — Um app só; a tela é a da role do usuário (P0/P1/P2)

**Custo:** médio (1 tela nova de entrada, `main.js`, `papeis.json`, instalador). **Dependência:** D1 (papel
do técnico) para a parte da captura; a parte das roles `cliente`/`operador`/`admin` roda sem ela.

- **P0 — tela única de entrada.** Nova pasta `entrada/` (`entrada/index.html` + `entrada/entrada.js`,
  reaproveitando `fronts/vms.css` — nada de visual novo): formulário de e-mail/senha que chama
  `/api/entrar` e **roteia pela role devolvida**: `cliente → /app`, `operador|admin → /admin`,
  `tecnico|captura → /`. Rota `/entrada` em `ground/api.py` (`translate_path`, junto de `/app` e `/admin`,
  linha ~755) e `Cache-Control: no-store` (linha ~749).
  **Aceite:** `GET /entrada` = 200 com o formulário; a tabela de roteamento por papel é lida pelo teste.
- **P0 — um pacote só.** `desktop/main.js`: nova superfície `entrada` (rota `/entrada`) e
  `abrirAoIniciar: ["entrada"]`; `desktop/papeis.json`: papel **`unico`** (base = lado terra, servidor local
  desligado de fábrica, captura ligável pelo menu de 0.5.0); `desktop/construir-instaladores.sh`: **uma**
  linha `construir "LECSOR" entrada unico unico 1` (leva o ambiente; é o mesmo pacote que pode capturar).
  **Aceite:** `bash desktop/construir-instaladores.sh` gera **1** `.exe` em `dist/unico/`;
  `python tests/test-app-unico-por-papel.py` verde.
- **P1 — a captura segue a role (D1).** `db/schema-fase4.sql` + migração: `papel IN
  ('cliente','operador','admin','tecnico')`; `POST /api/usuarios` aceita `tecnico` (sem `cliente_id`);
  `/admin` esconde as telas de sistema para `tecnico` (ele só tem Enviar vídeo), e a tela `/entrada` manda
  o `tecnico` para `/`. **Aceite:** teste prova `tecnico` aceito no cadastro, roteado para `/`, e barrado
  nas rotas de admin.
- **P1 — máquina de captura sem internet continua entrando.** Com a captura liberada nesta máquina
  (`capturaLocal`, 0.5.0), a entrada é servida pelo **servidor local** (`127.0.0.1:<porta>/entrada`) e a
  sessão vale no banco local; com internet, o login local é a rede de proteção que já existe. **Aceite:**
  `python tests/test-captura_liberada_no_app.py` (atualizado) verde, provando o app abrindo `/entrada`
  local e `/` depois do login.
- **P2 — Modo → Recarregar a tela continua funcionando** e o relatório `--verificar` passa a dizer qual
  superfície foi aberta e por qual motivo. **Aceite:** `python tests/e2e-desktop.py` verde.

## Fase 4 — Publicar 1 instalador e migrar as máquinas (P0/P1)

**Custo:** baixo (build + release + limpeza). **Dependência:** Fase 3 aprovada e implementada.

- **P0 — versão e release.** `desktop/package.json` → `0.6.0`; `tools/publicar-releases.py` com a nota
  (*"um aplicativo só: a tela é definida pela role do usuário; cadastro de usuário só pelo administrador"*)
  e `make_latest` string `"true"`; 1 asset em vez de 4.
  **Aceite:** `/releases/latest` com **1** asset `LECSOR-0.6.0-x64.exe`.
- **P0 — lado terra (VPS) na mesma versão.** `scp` de `ground/api.py`, `admin/admin.js`, `entrada/` e
  `fronts/` para `/opt/pipeline/app/` + `systemctl restart --no-block pipeline-api.service` + `md5sum` dos
  dois lados + `/api/saude` 200 + `GET /entrada` 200. **Aceite:** os comandos acima, com a saída no fecho.
- **P1 — testes de instalador atualizados.** `tests/test-instalador-plug-and-play.py` (as 4 linhas
  `construir` viram 1; as seções que checam "existe o instalador do PC de captura"/"do lado terra" passam a
  apontar para a entrada única) e `tests/e2e-desktop.py`. **Aceite:** os dois exit 0.
- **P1 — nota no vault** (`30-decisoes/`) + índice + push do vault. **Aceite:** `sync-vault.sh diff` = IGUAIS.
- **P2 — aviso de migração.** No README/`INSTALAR-PC-DE-CAPTURA.md`: quem tem os pacotes antigos desinstala
  os 4 e instala o novo (mesmo produto, `appId` novo — os antigos convivem por isso). **Aceite:** texto no
  arquivo.

## Arquivos que mudam

`ground/api.py` (entrar, usuarios, primeiro-acesso, /entrada, rota estática) · `ground/supabase_auth.py` (se
faltar `atualizar_senha`) · `admin/admin.js` + `admin/index.html` (usuários, mensagem de cliente) ·
`entrada/index.html` + `entrada/entrada.js` (novos) · `desktop/main.js` · `desktop/papeis.json` ·
`desktop/construir-instaladores.sh` · `desktop/package.json` (0.6.0) · `db/schema-fase4.sql` + migração do
papel `tecnico` · `tools/publicar-releases.py` · `tools/conferir-signup.py` (novo) ·
`tests/test-cadastro-so-pelo-admin.py` (novo) · `tests/test-app-unico-por-papel.py` (novo) ·
`tests/test-instalador-plug-and-play.py` · `tests/e2e-desktop.py` · `README.md` ·
`INSTALAR-PC-DE-CAPTURA.md`.

## Riscos e limites (declarados)

- **Desligar o cadastro no Supabase derruba o auto-cadastro de outros produtos do mesmo projeto** — se
  outro produto usar o mesmo projeto para cadastro público, ele para. Não verifiquei se algum usa.
- **Usuários que hoje existem só no Supabase e nunca entraram** continuam fora depois da Fase 1 (é o
  objetivo), mas entram pelo cadastro do Admin — a Fase 2 mostra quais estão nessa situação.
- **Não medido:** quantos usuários reais existem hoje no Supabase Auth e quantos deles existem na base
  local (não tenho a lista sem a chave de serviço; o `id_por_email` da Fase 2 resolve por usuário).
- **`disable_signup` é estado do projeto, não do código:** se alguém religar no painel, a adoção do
  `/api/entrar` já estará fechada (defesa em profundidade) — e mesmo assim um usuário cadastrado lá fora
  não entra sem o Admin cadastrar aqui.
- **O pacote único perde a "cara" por instalador:** hoje o nome do atalho diz "Captura"/"Admin"; passa a ser
  um só. Se você quiser atalhos diferentes por papel, isso precisa entrar como fase nova.
- **Windows:** os 4 instaladores antigos continuam instalados até serem desinstalados (appIds diferentes) —
  a migração é manual, como declarado na Fase 4.

## Questões abertas (responder com "aprovado" + a decisão, ou pedir a edição)

1. D1 — papel `tecnico` novo (proposto) ou "quem tem a captura liberada na máquina vê a tela"?
2. D2 — você desliga o cadastro público no painel (proposto) ou deposita o PAT para eu fazer?
