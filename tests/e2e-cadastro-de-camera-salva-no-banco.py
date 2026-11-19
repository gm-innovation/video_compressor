#!/usr/bin/env python3
"""O CADASTRO DE CAMERA E' SALVO NO BANCO (0.8.0, Fase 1) — prova de ponta a ponta.

Palavras do dono (19/11/2026): "parece que as camaras nao estao sendo salvas no banco de dados".

O que este teste prova (API de verdade + um Supabase DUBLÊ, local, que registra o que recebe):
  1) a camera cadastrada pelo admin entra em `public.cameras` do Supabase (upsert por id);
  2) `embarcacao_id` vai como **uuid** (a ponte `embarcacoes_supabase` traduz 'bancada' -> uuid);
  3) o corpo NAO leva endereco (`ip`/`porta` nunca sobem — regra da migracao 20261111130000);
  4) o cadastro que o BORDO anuncia tambem e' espelhado (o lado terra e' quem tem a chave);
  5) sem chave de servico, /api/saude DIZ que o banco nao esta configurado (falha visivel, nao silenciosa);
  6) remover a camera tira a linha do banco.

    python tests/e2e-cadastro-de-camera-salva-no-banco.py
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RAIZ = pathlib.Path(__file__).resolve().parents[1]
falhas: list[str] = []
TOKEN = "token-de-ingestao-do-teste"
CLIENTE_UUID = "11111111-1111-1111-1111-111111111111"


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def nota(texto):
    print("     " + texto)


def porta_livre(excluir=None) -> int:
    excluir = excluir or set()
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            p = s.getsockname()[1]
        if p not in excluir:
            return p


# --------------------------------------------------------------- Supabase DUBLÊ
class SupabaseFalso(BaseHTTPRequestHandler):
    """Guarda o que o servidor manda — e' assim que se prova que o cadastro SAIU daqui."""

    cameras: dict = {}
    embarcacoes: dict = {}
    pedidos: list = []
    chave_ok = True

    def log_message(self, format, *args):  # noqa: A002  (assinatura do BaseHTTPRequestHandler)
        pass

    def _responde(self, status, corpo):
        dados = json.dumps(corpo).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _autorizado(self) -> bool:
        return (self.headers.get("apikey") == "chave-de-teste"
                and (self.headers.get("Authorization") or "") == "Bearer chave-de-teste")

    def _corpo(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):  # noqa: N802
        if not self._autorizado():
            return self._responde(401, {"message": "chave invalida"})
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        SupabaseFalso.pedidos.append(("GET", u.path, dict(q)))
        if u.path == "/rest/v1/clientes":
            return self._responde(200, [{"id": CLIENTE_UUID}])
        if u.path == "/rest/v1/cameras":
            return self._responde(200, list(SupabaseFalso.cameras.values()))
        if u.path == "/rest/v1/embarcacoes":
            nome = (q.get("nome") or [""])[0].replace("eq.", "")
            achadas = [e for e in SupabaseFalso.embarcacoes.values() if not nome or e["nome"] == nome]
            return self._responde(200, achadas)
        return self._responde(404, {"message": "rota desconhecida"})

    def do_POST(self):  # noqa: N802
        if not self._autorizado():
            return self._responde(401, {"message": "chave invalida"})
        u = urllib.parse.urlparse(self.path)
        d = self._corpo()
        SupabaseFalso.pedidos.append(("POST", u.path, d))
        if u.path == "/rest/v1/embarcacoes":
            novo = {"id": f"emb-{len(SupabaseFalso.embarcacoes) + 1}-uuid", "nome": d.get("nome", ""),
                    "cliente_id": d.get("cliente_id", "")}
            SupabaseFalso.embarcacoes[novo["id"]] = novo
            return self._responde(201, [novo])
        if u.path == "/rest/v1/cameras":
            # upsert por id, como o `Prefer: resolution=merge-duplicates` faz de verdade
            cam = dict(d)
            SupabaseFalso.cameras[cam["id"]] = cam
            return self._responde(201, [cam])
        return self._responde(404, {"message": "rota desconhecida"})

    def do_DELETE(self):  # noqa: N802
        if not self._autorizado():
            return self._responde(401, {"message": "chave invalida"})
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        SupabaseFalso.pedidos.append(("DELETE", u.path, dict(q)))
        alvo = (q.get("id") or [""])[0].replace("eq.", "")
        SupabaseFalso.cameras.pop(alvo, None)
        self.send_response(204)
        self.end_headers()


def sobe_supabase_falso(porta: int) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", porta), SupabaseFalso)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# --------------------------------------------------------------- infra do teste
def pedir(metodo, url, corpo=None, cookie="", token=""):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    cab = {"Content-Type": "application/json"} if dados else {}
    if cookie:
        cab["Cookie"] = f"sessao={cookie}"
    if token:
        cab["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=60) as f:
            b = f.read()
            return f.status, (json.loads(b) if b else {})
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


def sobe_api(banco: pathlib.Path, porta: int, env_extra: dict):
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY",
              "LECSOR_LADO_TERRA_API", "LECSOR_EMBARCACAO", "LECSOR_DESTINO_SRT"):
        env.pop(k, None)
    env.update(env_extra)
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env,
                            stdout=(banco.parent / f"api-{porta}.log").open("wb"),
                            stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError("a API saiu: "
                               + (banco.parent / f"api-{porta}.log").read_text(errors="replace")[-600:])
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/saude", timeout=3):
                return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise RuntimeError("a API nao subiu")


def sessao_de(con, uid, email, papel="admin", cliente_id=""):
    salt = os.urandom(16).hex()
    senha = hashlib.pbkdf2_hmac("sha256", b"senha-de-teste", bytes.fromhex(salt), 200_000).hex()
    con.execute("""INSERT OR REPLACE INTO usuarios (id,email,nome,papel,cliente_id,senha_hash,salt,interacoes,ativo)
                   VALUES (?,?,?,?,?,?,?,200000,1)""", (uid, email, uid, papel, cliente_id or None, senha, salt))
    tok = "tok-" + uid
    exp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(timespec="seconds")
    con.execute("INSERT OR REPLACE INTO sessoes (token,usuario_id,expira_em,user_agent) VALUES (?,?,?,?)",
                (tok, uid, exp, "teste"))
    con.commit()
    return tok


def um(banco, sql, args=()):
    con = sqlite3.connect(str(banco))
    con.row_factory = sqlite3.Row
    try:
        r = con.execute(sql, args).fetchone()
        return dict(r) if r else {}
    finally:
        con.close()


def executa(banco, sql, args=()):
    con = sqlite3.connect(str(banco))
    try:
        con.execute(sql, args)
        con.commit()
    finally:
        con.close()


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-banco-"))
    p_api, p_fake = porta_livre(), porta_livre()
    banco = tmp / "terra.db"
    procs: list = []
    try:
        # a embarcacao JÁ EXISTE no Supabase (o caso real: "Bancada de testes (propria)"): o espelho tem
        # de casar por NOME e reusar o uuid, nunca criar uma segunda embarcacao com o nome do slug.
        SupabaseFalso.embarcacoes["dedec7a2-uuid"] = {"id": "dedec7a2-uuid", "nome": "Bancada de testes",
                                                      "cliente_id": CLIENTE_UUID}
        sobe_supabase_falso(p_fake)
        procs.append(sobe_api(banco, p_api, {
            "LECSOR_SUPABASE_URL": f"http://127.0.0.1:{p_fake}",
            "LECSOR_SUPABASE_SERVICE_KEY": "chave-de-teste",
            "LECSOR_TOKEN_INGESTAO": TOKEN,
            "LECSOR_BIND": "127.0.0.1",
        }))
        base = f"http://127.0.0.1:{p_api}"
        executa(banco, "INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
        executa(banco, "INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES ('bancada','lecsor','Bancada de testes')")
        con = sqlite3.connect(str(banco))
        admin = sessao_de(con, "adm-1", "admin@lecsor.test", "admin")
        con.close()

        _, saude = pedir("GET", base + "/api/saude")
        nota(f"/api/saude supabase: {json.dumps(saude.get('supabase'), ensure_ascii=False)}")
        exigir((saude.get("supabase") or {}).get("configurado") is True,
               "/api/saude diz que o banco esta configurado nesta instalacao")

        # 1) cadastro pelo ADMIN
        st, r = pedir("POST", base + "/api/cameras", {"id": "cam-01", "rotulo": "Proa", "fluxo_id": "cam-01",
                                                      "embarcacao_id": "bancada", "ip": "10.0.0.9", "porta": "554"},
                      cookie=admin)
        exigir(st == 201, f"cadastro pelo admin responde 201 (veio {st})")
        exigir((r.get("supabase") or {}).get("ok") is True,
               f"o cadastro foi gravado no banco (supabase.ok) — {json.dumps(r.get('supabase'), ensure_ascii=False)}")
        no_banco = SupabaseFalso.cameras.get("cam-01") or {}
        exigir(bool(no_banco), "a linha da camera existe no banco (Supabase)")
        exigir(no_banco.get("embarcacao_id") == "dedec7a2-uuid",
               f"embarcacao_id subiu como o UUID da embarcacao EXISTENTE (veio {no_banco.get('embarcacao_id')!r})")
        exigir(len(SupabaseFalso.embarcacoes) == 1,
               f"NAO criou embarcacao duplicada (ha {len(SupabaseFalso.embarcacoes)} no banco)")
        exigir(no_banco.get("rotulo") == "Proa" and no_banco.get("fluxo_id") == "cam-01",
               "rotulo e fluxo_id chegaram certos")
        exigir(no_banco.get("ativo") is True, "ativo chegou como booleano")
        exigir("ip" not in no_banco and "porta" not in no_banco,
               "o corpo NAO leva endereco de camera (ip/porta) para o banco")
        ponte = um(banco, "SELECT * FROM embarcacoes_supabase WHERE slug='bancada'")
        exigir(ponte.get("uuid") == "dedec7a2-uuid",
               f"a ponte embarcacao (texto -> uuid) ficou gravada: {ponte.get('uuid')!r}")

        # 2) cadastro anunciado pelo BORDO (o lado terra espelha)
        st, r = pedir("POST", base + "/api/cameras/anuncio",
                      {"id": "cam-02", "fluxo_id": "cam-02", "rotulo": "Popa", "embarcacao_id": "bancada"},
                      token=TOKEN)
        exigir(st == 201, f"anuncio do bordo responde 201 (veio {st})")
        exigir((r.get("supabase") or {}).get("ok") is True,
               "o cadastro vindo do bordo tambem foi gravado no banco")
        exigir(bool(SupabaseFalso.cameras.get("cam-02")), "a camera do bordo existe no banco")
        exigir(SupabaseFalso.cameras.get("cam-02", {}).get("embarcacao_id") == "dedec7a2-uuid",
               "a camera do bordo reusou o MESMO uuid de embarcacao (sem duplicar embarcacao)")
        exigir(len(SupabaseFalso.embarcacoes) == 1,
               f"o espelho NAO duplica embarcacao: {len(SupabaseFalso.embarcacoes)} no banco")

        # 3) republicar tudo (o botao da tela do admin)
        st, r = pedir("POST", base + "/api/cameras/publicar", {}, cookie=admin)
        exigir(st == 200 and not r.get("fora_do_banco"),
               f"o botao de republicar poe todo o cadastro no banco (fora_do_banco={r.get('fora_do_banco')})")

        # 4) remover a camera tira a linha do banco
        st, r = pedir("POST", base + "/api/cameras/cam-02/remover", {}, cookie=admin)
        exigir(st == 200, f"remover responde 200 (veio {st})")
        exigir("cam-02" not in SupabaseFalso.cameras,
               f"a linha saiu do banco (supabase={json.dumps(r.get('supabase'), ensure_ascii=False)})")

        # 5) sem chave de servico: falha VISIVEL, nao silenciosa
        p2 = porta_livre({p_api, p_fake})
        banco2 = tmp / "sem-chave.db"
        procs.append(sobe_api(banco2, p2, {"LECSOR_BIND": "127.0.0.1"}))
        base2 = f"http://127.0.0.1:{p2}"
        executa(banco2, "INSERT OR REPLACE INTO clientes (id,nome) VALUES ('lecsor','LECSOR')")
        executa(banco2, "INSERT OR REPLACE INTO embarcacoes (id,cliente_id,nome) VALUES ('bancada','lecsor','Bancada')")
        con = sqlite3.connect(str(banco2))
        admin2 = sessao_de(con, "adm-2", "admin2@lecsor.test", "admin")
        con.close()
        _, saude2 = pedir("GET", base2 + "/api/saude")
        exigir((saude2.get("supabase") or {}).get("configurado") is False,
               "sem chave, /api/saude mostra que o banco NAO esta configurado")
        st, r = pedir("POST", base2 + "/api/cameras", {"id": "cam-09", "rotulo": "Sem chave",
                                                       "fluxo_id": "cam-09", "embarcacao_id": "bancada"},
                      cookie=admin2)
        exigir(st == 201, "mesmo sem chave, a camera entra no banco LOCAL (o SQLite opera)")
        exigir((r.get("supabase") or {}).get("ok") is False and "chave" in str((r.get("supabase") or {}).get("motivo", "")),
               f"e o motivo aparece na resposta: {(r.get('supabase') or {}).get('motivo')!r}")
        exigir(bool(um(banco2, "SELECT 1 AS x FROM cameras WHERE id='cam-09'")),
               "a camera esta no SQLite local mesmo com o banco da nuvem fora")
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.3)

    print()
    if falhas:
        print(f"FALHOU: {len(falhas)} verificacao(oes)")
        for f in falhas:
            print("  - " + f)
        return 1
    print("TUDO OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
