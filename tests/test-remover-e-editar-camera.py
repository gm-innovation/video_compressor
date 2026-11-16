"""Remover camera e editar camera EM OPERACAO (sem perder `ativo`, `alvo` nem historico).

Pedido do dono (16/11/2026): "1. preciso poder remover uma camera que nao esta mais sendo utilizada
2. editar cameras em operacao".

O que este teste exige (API de verdade, banco temporario):
  1. `/editar` muda SO' os campos enviados e preserva `ativo` e `alvo` — o `POST /api/cameras` de hoje e'
     INSERT OR REPLACE e ZERA `ativo`: por isso ele nao serve para editar em operacao;
  2. editar sem nada a mudar -> 200 com `mudou: []` (nao e' erro, mas tambem nao inventa mudanca);
  3. rotulo vazio -> 422; ip e porta invalidos -> 422;
  4. mexer na FONTE (ip/porta) diz em voz alta que so' vale no proximo "Enviar video" (RTSP); mexer so'
     no rotulo NAO mexe no video em curso;
  5. `/remover` tira a camera da operacao: para o envio, apaga o cadastro aqui, publica a remocao para o
     lado terra e a camera some da lista — sem apagar trechos nem auditoria;
  6. remover camera inexistente -> 404; cliente NAO edita nem remove (403).

    python tests/test-remover-e-editar-camera.py
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
SENHA = "teste-1234"


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Sessao:
    def __init__(self, base: str):
        self.base = base
        self.cookie = ""

    def pedir(self, rota: str, corpo=None):
        h = {"Content-Type": "application/json"}
        if self.cookie:
            h["Cookie"] = self.cookie
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(self.base + rota, data=dados,
                                     method="POST" if corpo is not None else "GET", headers=h)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                bruto, codigo, cab = r.read(), r.status, r.headers
        except urllib.error.HTTPError as e:
            bruto, codigo, cab = e.read(), e.code, e.headers
        setc = cab.get("Set-Cookie") if cab else None
        if setc and setc.startswith("sessao="):
            self.cookie = setc.split(";")[0]
        try:
            return codigo, json.loads(bruto.decode("utf-8") or "{}")
        except Exception:
            return codigo, {}


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-camera-"))
    banco = tmp / "pipeline.db"
    porta = porta_livre()
    falhas = []

    def exigir(cond, texto):
        print(("OK   " if cond else "FALHA ") + texto)
        if not cond:
            falhas.append(texto)

    def linha(campo: str, cid: str):
        with sqlite3.connect(str(banco)) as c:
            r = c.execute(f"SELECT {campo} FROM cameras WHERE id=?", (cid,)).fetchone()
        return r[0] if r else None

    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["LECSOR_BIND"] = "0.0.0.0"
    env["LECSOR_TOKEN_INGESTAO"] = "token-de-teste-camera"
    env["LECSOR_SENHA_DEMO"] = SENHA
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY"):
        env.pop(k, None)
    log = (tmp / "api.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta), "--semear-demo"],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"

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
            print((tmp / "api.log").read_text(errors="replace")[-400:])
            return 1

        admin = Sessao(base)
        s, j = admin.pedir("/api/entrar", {"email": "admin@lecsor.test", "senha": SENHA})
        exigir(s == 200 and j.get("ok"), "admin autenticou (http %s)" % s)
        cliente = Sessao(base)
        cliente.pedir("/api/entrar", {"email": "cliente@lecsor.test", "senha": SENHA})

        admin.pedir("/api/cameras", {"id": "cam-rem", "fluxo_id": "cam-rem", "rotulo": "CAM que vai sair",
                                     "embarcacao_id": "bancada", "ativo": 1})
        s, _ = admin.pedir("/api/cameras", {"id": "cam-edit", "fluxo_id": "cam-edit", "rotulo": "CAM de bordo",
                                            "embarcacao_id": "bancada", "ativo": 1,
                                            "ip": "10.0.0.9", "porta": 554})
        exigir(s == 201, "cameras de prova cadastradas (http %s)" % s)

        # ---------------------------------------------------------------- editar (preserva o resto)
        admin.pedir("/api/cameras/cam-edit/alvo", {"alvo": "300k"})
        s, j = admin.pedir("/api/cameras/cam-edit/editar", {"rotulo": "CAM de proa"})
        exigir(s == 200 and j.get("mudou") == ["rotulo"], "editar so' o rotulo (http %s, mudou=%s)" % (s, j.get("mudou")))
        exigir(linha("rotulo", "cam-edit") == "CAM de proa", "o rotulo NOVO esta no banco (%r)" % linha("rotulo", "cam-edit"))
        exigir(j.get("aplicado") is False and "nao mexe na fonte" in (j.get("motivo") or ""),
               "rotulo nao mexe no video em curso (%r)" % (j.get("motivo") or "")[:60])

        # o `POST /api/cameras` (INSERT OR REPLACE) zeraria ativo/alvo; o /editar nao pode
        admin.pedir("/api/cameras/cam-edit/ativo", {"ativo": 0})
        exigir(linha("ativo", "cam-edit") == 0, "cam-edit desativada para a prova (ativo=%r)" % linha("ativo", "cam-edit"))
        s, _ = admin.pedir("/api/cameras/cam-edit/editar", {"rotulo": "CAM de proa 2"})
        exigir(linha("ativo", "cam-edit") == 0, "editar NAO reativa a camera (ativo=%r)" % linha("ativo", "cam-edit"))
        exigir(linha("alvo", "cam-edit") == "300k", "editar NAO apaga o alvo escolhido (alvo=%r)" % linha("alvo", "cam-edit"))

        s, j = admin.pedir("/api/cameras/cam-edit/editar", {"rotulo": "CAM de proa 2"})
        exigir(s == 200 and j.get("mudou") == [], "sem mudanca de verdade -> mudou=[] (http %s)" % s)
        s, _ = admin.pedir("/api/cameras/cam-edit/editar", {"rotulo": "   "})
        exigir(s == 422, "rotulo vazio -> 422 (http %s)" % s)
        s, _ = admin.pedir("/api/cameras/cam-edit/editar", {"ip": "a b"})
        exigir(s == 422, "ip invalido -> 422 (http %s)" % s)
        s, _ = admin.pedir("/api/cameras/cam-edit/editar", {"porta": "70000"})
        exigir(s == 422, "porta fora de 1..65535 -> 422 (http %s)" % s)

        # mexer na fonte: avisa que so' vale no proximo envio (camera por endereco RTSP)
        s, j = admin.pedir("/api/cameras/cam-edit/editar", {"ip": "10.0.0.10"})
        exigir(s == 200 and "RTSP" in (j.get("motivo") or "") and j.get("aplicado") is False,
               "mudar a fonte avisa em voz alta (%r)" % (j.get("motivo") or "")[:70])

        # ---------------------------------------------------------------- remover
        with sqlite3.connect(str(banco)) as c:
            c.execute("""CREATE TABLE IF NOT EXISTS trechos (
                           id INTEGER PRIMARY KEY AUTOINCREMENT, fluxo_id TEXT NOT NULL, arquivo TEXT NOT NULL,
                           host TEXT, segundos_pedidos INTEGER, duracao_s REAL, bytes INTEGER, kbps REAL,
                           sha256 TEXT, quem TEXT, criado_em TEXT NOT NULL)""")
            c.execute("INSERT INTO trechos (fluxo_id, arquivo, quem, criado_em) VALUES ('cam-rem','/tmp/x.mp4','admin','2026-11-16')")
        s, j = admin.pedir("/api/cameras/cam-rem/remover", {})
        exigir(s == 200 and j.get("ok") and j.get("trechos_preservados") is True,
               "camera removida (http %s, lado_terra=%s)" % (s, (j.get("lado_terra") or {}).get("motivo", "ok")))
        exigir(linha("rotulo", "cam-rem") is None, "o cadastro sumiu do banco (nao e' so' desativar)")
        with sqlite3.connect(str(banco)) as c:
            sobrou = c.execute("SELECT count(*) FROM trechos WHERE fluxo_id='cam-rem'").fetchone()[0]
        exigir(sobrou == 1, "os trechos ja' gravados continuam (%d linha)" % sobrou)
        s, j = admin.pedir("/api/cameras")
        ids = [c.get("id") for c in (j.get("cameras") or [])]
        exigir("cam-rem" not in ids, "a camera removida NAO aparece mais na lista")
        s, _ = admin.pedir("/api/cameras/cam-rem/remover", {})
        exigir(s == 404, "remover de novo -> 404 (http %s)" % s)

        # ---------------------------------------------------------------- quem nao pode
        s, _ = cliente.pedir("/api/cameras/cam-edit/editar", {"rotulo": "outro nome"})
        exigir(s in (401, 403), "cliente NAO edita camera (http %s)" % s)
        s, _ = cliente.pedir("/api/cameras/cam-edit/remover", {})
        exigir(s in (401, 403), "cliente NAO remove camera (http %s)" % s)

        print()
        if falhas:
            print("FALHOU: %d verificacao(oes)" % len(falhas))
            for f in falhas:
                print("  -", f)
            return 1
        print("TUDO OK: editar em operacao preserva ativo/alvo; remover tira da operacao sem apagar historico")
        return 0
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
