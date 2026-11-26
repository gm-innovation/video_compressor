"""Selecao de qualidade POR CAMERA — a tela escolhe a taxa de envio de cada camera.

Pedido do dono (16/11/2026): "vamos fazer um sistema de selecao de qualidade, as imagens de cada camera
podem ser enviadas a 1500k/1200k/1000k/800k/500k/300k, a selecao deve ser individual, cada camera pode
ter uma taxa de envio selecionavel".

O que este teste exige (API de verdade, banco temporario, sem camera e sem mediamtx — o alvo se prova
na lista e na reabertura, nao precisa de video):
  1. os NOVE niveis da lista sao aceitos: 3000k/2500k/2000k/1500k/1200k/1000k/800k/500k/300k;
  2. a lista e' FECHADA: 4000k, 1500, 1k, abc -> 422, e a resposta diz quais sao os validos;
  3. a selecao e' INDIVIDUAL: mudar uma camera nao mexe na outra (o banco prova);
  4. a resposta diz em voz alta se valeu NO AR (`aplicado`) e, quando nao valeu, POR QUE (`motivo`);
  5. alvo vazio = padrao da tela (tambem e' uma escolha valida);
  6. o `alvo` NAO sai na lista que o cliente ve (`/api/cameras`) — so' na visao da operacao
     (`/api/cameras/detalhe`) e no banco;
  7. cliente e visitante -> 403; camera inexistente -> 404.

    python tests/test-selecao-de-qualidade.py
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
NIVEIS = ["3000k", "2500k", "2000k", "1500k", "1200k", "1000k", "800k", "500k", "300k"]


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Sessao:
    def __init__(self, base: str):
        self.base = base
        self.cookie = ""

    def cabecalhos(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.cookie:
            h["Cookie"] = self.cookie
        return h

    def pedir(self, rota: str, corpo=None):
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(self.base + rota, data=dados,
                                     method="POST" if corpo is not None else "GET",
                                     headers=self.cabecalhos())
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
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-alvo-"))
    banco = tmp / "pipeline.db"
    porta = porta_livre()
    falhas = []

    def exigir(cond, texto):
        print(("OK   " if cond else "FALHA ") + texto)
        if not cond:
            falhas.append(texto)

    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["LECSOR_BIND"] = "0.0.0.0"
    env["LECSOR_TOKEN_INGESTAO"] = "token-de-teste-alvo"
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

        for cam in ("cam-a", "cam-b"):
            s, _ = admin.pedir("/api/cameras", {"id": cam, "fluxo_id": cam, "rotulo": cam.upper(),
                                                "embarcacao_id": "bancada", "ativo": 1})
            exigir(s == 201, "camera %s cadastrada (http %s)" % (cam, s))

        # 1) os seis niveis (na MESMA camera, um a um)
        for n in NIVEIS:
            s, j = admin.pedir("/api/cameras/cam-a/alvo", {"alvo": n})
            exigir(s == 200 and j.get("alvo") == n, "nivel %s aceito (http %s, alvo=%r)" % (n, s, j.get("alvo")))

        # 2) a lista e' fechada
        s, j = admin.pedir("/api/cameras/cam-a/alvo", {"alvo": "4000k"})
        exigir(s == 422 and j.get("alvos") == NIVEIS,
               "4000k (acima do teto da lista) e' RECUSADO e a resposta traz a lista (%s)" % j.get("alvos"))
        for ruim in ("1500", "1k", "abc", "1500kk"):
            s, _ = admin.pedir("/api/cameras/cam-a/alvo", {"alvo": ruim})
            exigir(s == 422, "%r fora da lista -> 422 (http %s)" % (ruim, s))

        # 3) individual: uma camera nao muda a outra
        admin.pedir("/api/cameras/cam-a/alvo", {"alvo": "300k"})
        admin.pedir("/api/cameras/cam-b/alvo", {"alvo": "1200k"})
        with sqlite3.connect(str(banco)) as c:
            alvos = dict(c.execute("SELECT id, alvo FROM cameras WHERE id IN ('cam-a','cam-b')").fetchall())
        exigir(alvos.get("cam-a") == "300k" and alvos.get("cam-b") == "1200k",
               "a escolha e' INDIVIDUAL: cam-a=%r cam-b=%r" % (alvos.get("cam-a"), alvos.get("cam-b")))

        # 4) a resposta diz se valeu no ar e por que nao
        s, j = admin.pedir("/api/cameras/cam-a/alvo", {"alvo": "800k"})
        exigir(j.get("aplicado") is False and "nao estava no ar" in (j.get("motivo") or ""),
               "fora do ar: resposta diz que vale quando subir (%r)" % (j.get("motivo") or "")[:70])
        # 5) vazio = padrao da tela
        s, j = admin.pedir("/api/cameras/cam-a/alvo", {"alvo": ""})
        exigir(s == 200 and j.get("alvo") == "" and j.get("aplicado") is False,
               "alvo vazio volta ao padrao da tela (http %s, alvo=%r)" % (s, j.get("alvo")))
        admin.pedir("/api/cameras/cam-a/alvo", {"alvo": "1500k"})

        # 6) o alvo NAO vai para o que o cliente ve
        s, j = admin.pedir("/api/cameras")
        lista = j.get("cameras") or []
        campos = set()
        for c in lista:
            campos |= set(c.keys())
        exigir(lista and not (campos & {"alvo", "ip", "porta", "protocolo", "canal"}),
               "na lista de cameras NAO sai alvo/endereco (campos extra: %s)" % sorted(campos & {"alvo", "ip", "porta"}))
        s, j = admin.pedir("/api/cameras/detalhe")
        det = {c["id"]: c for c in (j.get("cameras") or [])}
        exigir((det.get("cam-a") or {}).get("alvo") == "1500k",
               "a OPERACAO ve o alvo no detalhe (%r)" % (det.get("cam-a") or {}).get("alvo"))

        # 7) quem nao pode
        s, _ = cliente.pedir("/api/cameras/cam-a/alvo", {"alvo": "500k"})
        exigir(s in (401, 403), "cliente NAO define alvo (http %s)" % s)
        s, _ = admin.pedir("/api/cameras/nao-existe/alvo", {"alvo": "800k"})
        exigir(s == 404, "camera inexistente -> 404 (http %s)" % s)

        print()
        if falhas:
            print("FALHOU: %d verificacao(oes)" % len(falhas))
            for f in falhas:
                print("  -", f)
            return 1
        print("TUDO OK: selecao de qualidade por camera (lista fechada, individual, so avisa)")
        return 0
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
