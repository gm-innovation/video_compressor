"""Login do Supabase numa instalacao SEM a linha local do usuario: NAO adota (0.6.0).

Historico: ate' a 0.5.0 `/api/entrar` ADOTAVA a identidade — quem existisse no Supabase entrava no PC
instalado como `cliente`, mesmo sem ninguem ter cadastrado ali. O dono corrigiu em 17/11/2026
(verbatim): *"um usuário não pode se cadastrar, quem cadastra os usuários é o admin"*. Desde a 0.6.0 a
resposta e' **403 e NENHUMA linha nasce** no banco local.

Este teste substitui o antigo `test-login-supabase-adocao.py`, que exigia justamente o contrario e
ficou vermelho quando o contrato virou — prova desatualizada nao serve como prova.

O que ele mede (API de verdade, banco vazio de verdade em pasta temporaria):

  1. `/api/primeiro-acesso` numa instalacao vazia: `precisa: true`, `usuarios: 0` e `supabase: true`;
  2. `/api/entrar` com credencial VALIDA do Supabase que nao existe no banco local -> **403**, com a
     mensagem dizendo que quem cadastra e' o administrador, e **0 usuarios** no banco local depois;
  3. senha errada continua 401 e e-mail desconhecido continua 401 (o veredito do Supabase manda);
  4. a credencial do caso 2 existe mesmo no Supabase (senao a prova nao diria nada) — e mesmo assim
     nao e' adotada.

Requer `LECSOR_SUPABASE_URL` / `LECSOR_SUPABASE_ANON_KEY` e `LECSOR_SENHA_DEMO` no ambiente ou em
`ground/.env.local` (a senha nunca e' impressa).

    python tests/test-login-supabase-nao-adota.py
"""
import json
import os
import pathlib
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parents[1]
EMAIL = "operacao@lecsor.test"


def ler_env_local(caminho: pathlib.Path) -> None:
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip().lstrip("\ufeff")
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        k, v = linha.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pedir(url: str, corpo: dict | None = None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method="POST" if corpo is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            return e.code, {}


def conta_existe_no_supabase(email: str) -> bool:
    """A credencial do caso de teste e' um usuario REAL do Supabase? (sem imprimir segredo)."""
    url = (os.environ.get("LECSOR_SUPABASE_URL") or "").rstrip("/")
    anon = os.environ.get("LECSOR_SUPABASE_ANON_KEY") or ""
    if not (url and anon):
        return False
    req = urllib.request.Request(
        url + "/auth/v1/token?grant_type=password",
        data=json.dumps({"email": email, "password": os.environ["LECSOR_SENHA_DEMO"]}).encode(),
        method="POST", headers={"apikey": anon, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20):
            return True
    except Exception:
        return False


def main() -> int:
    ler_env_local(RAIZ / "ground" / ".env.local")
    if not (os.environ.get("LECSOR_SUPABASE_URL") and os.environ.get("LECSOR_SUPABASE_ANON_KEY")):
        print("PULADO: sem LECSOR_SUPABASE_URL / LECSOR_SUPABASE_ANON_KEY (nada a provar sem Supabase)")
        return 0
    senha = (os.environ.get("LECSOR_SENHA_DEMO") or "").strip()
    if not senha:
        print("PULADO: sem LECSOR_SENHA_DEMO no ambiente")
        return 0

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-nao-adota-"))
    banco = tmp / "pipeline.db"
    porta = porta_livre()
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["LECSOR_BIND"] = "127.0.0.1"
    env["PYTHONIOENCODING"] = "utf-8"
    log = (tmp / "api.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"
    falhas = []

    def exigir(cond, texto):
        print(("OK   " if cond else "FALHA ") + texto)
        if not cond:
            falhas.append(texto)

    def usuarios_locais() -> int:
        con = sqlite3.connect(banco)
        try:
            return con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        finally:
            con.close()

    try:
        for _ in range(60):
            time.sleep(0.5)
            try:
                with urllib.request.urlopen(base + "/api/saude", timeout=2):
                    break
            except Exception:
                continue
        else:
            print("FALHA a API nao subiu; log em", tmp / "api.log")
            return 1

        s, j = pedir(base + "/api/primeiro-acesso")
        exigir(s == 200 and j.get("precisa") is True and j.get("usuarios") == 0,
               "instalacao vazia: precisa=%s usuarios=%s" % (j.get("precisa"), j.get("usuarios")))
        exigir(j.get("supabase") is True, "a instalacao enxerga o Supabase (login de verdade)")
        exigir(conta_existe_no_supabase(EMAIL),
               "a credencial do caso existe mesmo no Supabase (%s)" % EMAIL)

        antes = usuarios_locais()
        s, j = pedir(base + "/api/entrar", {"email": EMAIL, "senha": senha})
        texto = json.dumps(j, ensure_ascii=False).lower()
        exigir(s == 403, "credencial do Supabase SEM cadastro local e' RECUSADA (http %s)" % s)
        exigir("admin" in texto or "cadastr" in texto,
               "a resposta diz que quem cadastra e' o administrador: %r" % (j.get("erro") or j)[:90])
        exigir(usuarios_locais() == antes == 0,
               "NENHUMA linha nasce no banco local (adocao desligada): %s -> %s" % (antes, usuarios_locais()))

        s, _ = pedir(base + "/api/entrar", {"email": EMAIL, "senha": senha + "-errada"})
        exigir(s == 401, "senha errada continua 401 (http %s)" % s)

        s, _ = pedir(base + "/api/entrar", {"email": "nao-existe-" + EMAIL, "senha": senha})
        exigir(s == 401, "e-mail desconhecido continua 401 (http %s)" % s)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        log.close()

    print()
    if falhas:
        print("FALHOU: %d verificacao(oes) — log em %s" % (len(falhas), tmp / "api.log"))
        return 1
    print("PASSOU: o login NAO adota identidade de fora — quem cadastra e' o administrador (0.6.0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
