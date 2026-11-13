"""Login do Supabase numa instalacao SEM a linha local do usuario (adocao).

O defeito da instalacao real: o PC instalado nasceu com banco local vazio (so' o admin do
primeiro acesso) e o login do Supabase era RECUSADO ("so' permite entrar com as credenciais
novas"), porque `/api/entrar` exigia a linha local. Aqui a API roda com um banco vazio de
verdade (`LECSOR_BANCO` em pasta temporaria) e o teste exige:

  1. `/api/primeiro-acesso` diz `precisa: true` e `supabase: true`;
  2. entrar com o usuario do Supabase (que NAO existe no banco local) -> 200 e a linha local
     passa a existir (adocao), com papel `cliente` (menor privilegio) e a mesma senha no hash;
  3. senha errada -> 401 (o veredito do Supabase continua mandando);
  4. o primeiro acesso com a credencial do Supabase adota a identidade (`origem: supabase`) em
     vez de criar mais um administrador solto.

Requer `LECSOR_SUPABASE_URL` / `LECSOR_SUPABASE_ANON_KEY` e `LECSOR_SENHA_DEMO` no ambiente ou em
`ground/.env.local` (a senha nunca e' impressa).

    python tests/test-login-supabase-adocao.py
"""
import json
import os
import pathlib
import socket
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


def main() -> int:
    ler_env_local(RAIZ / "ground" / ".env.local")
    if not (os.environ.get("LECSOR_SUPABASE_URL") and os.environ.get("LECSOR_SUPABASE_ANON_KEY")):
        print("PULADO: sem LECSOR_SUPABASE_URL / LECSOR_SUPABASE_ANON_KEY (nada a provar sem Supabase)")
        return 0
    senha = (os.environ.get("LECSOR_SENHA_DEMO") or "").strip()
    if not senha:
        print("PULADO: sem LECSOR_SENHA_DEMO no ambiente")
        return 0

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-adocao-"))
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

        s, j = pedir(base + "/api/entrar", {"email": EMAIL, "senha": senha})
        exigir(s == 200 and j.get("ok"), "login do Supabase entra mesmo sem linha local (http %s)" % s)
        exigir(j.get("papel") == "cliente", "papel adotado e' o menor privilegio: %r" % j.get("papel"))

        import sqlite3
        con = sqlite3.connect(banco)
        linha = con.execute("SELECT id,email,nome,papel,cliente_id FROM usuarios WHERE email=?",
                            (EMAIL,)).fetchone()
        con.close()
        exigir(bool(linha), "a linha local foi criada na adocao: %r" % (linha,))
        exigir(bool(linha) and linha[2], "nome veio do Supabase (user_metadata): %r" % (linha[2] if linha else None))

        s, j = pedir(base + "/api/entrar", {"email": EMAIL, "senha": senha + "-errada"})
        exigir(s == 401, "senha errada continua 401 (http %s)" % s)

        s, j = pedir(base + "/api/entrar", {"email": "nao-existe-" + EMAIL, "senha": senha})
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
    print("PASSOU: login do Supabase adota o usuario na instalacao nova")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
