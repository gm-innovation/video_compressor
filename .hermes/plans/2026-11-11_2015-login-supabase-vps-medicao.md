# Login no Supabase, publicação na VPS e medição terra→bordo (11/11/2026)

**Aprovação:** respostas do dono em 11/11/2026 — "login no supabase com os mesmos usuários e senha
que já estamos utilizando", "sim, tudo na vps", "sim, faça a medição". Escopo aprovado.

**Repo:** `C:\Users\EngenhariaGoogleMari\lecsor-pipeline-video` (branch `main`)

## 1. Login pelo Supabase Auth (mesmos usuários e senha)

- `ground/supabase_auth.py` (novo): fala com o Supabase Auth **pelo servidor** (`token?grant_type=password`
  com a chave anônima; `admin/users` com a de serviço). O navegador continua sem falar com o Supabase.
- `ground/api.py` `/api/entrar`: consulta o Supabase **antes** do hash local. Veredito `None`
  (Supabase não configurado ou rede fora) cai no hash local — a bancada sem credencial continua entrando.
  Recusa do Supabase **não** cai para o local (senha trocada lá vale aqui).
- `ground/migrar-login-supabase.py` (novo): cria no Auth os usuários do banco local com a senha de
  `LECSOR_SENHA_DEMO` (idempotente; nunca imprime nem grava senha no repositório).
- Chaves do Supabase no ambiente da VPS (`LECSOR_SUPABASE_URL/_ANON_KEY/_SERVICE_KEY`), server-side.

## 2. Tudo na VPS

- Código do app (ground/, app/, admin/, fronts/) sincronizado na VPS; serviço reiniciado.
- Causa corrigida de dois defeitos que só apareciam lá: `ground/ingestao.py` estava velho (o `api.py`
  novo importa `desligar_camera`), e o `.env.local` da VPS estava com CRLF (valor com `\r` no processo).

## 3. Medição do Cenário 2 (terra→bordo)

- `ground/terra-teste.sh` (novo): publicador da terra (4K→720p30 3000k com relógio queimado).
- Resultado em `ground/EVIDENCIA-cenario2-terra-bordo.md`: 3,156 Mbps entregues, 30,0 fps, latência
  ≈2 s, SSIM 0,9989 no ponto de operação; RTT do enlace não medido (4G descarta ICMP).

## 4. Câmera excluída não volta (causa)

- `ground/api.py`: as câmeras de `ground/receivers.json` só são semeadas em **instalação nova**
  (tabela `cameras` vazia). Era isso que ressuscitava `cam-01`/`cam-02` a cada reinício da VPS.

## Testes

- `tests/test-login-supabase.py` (novo) e `tests/test-camera-semear-uma-vez.py` (novo) + `tests/suite.py`.
