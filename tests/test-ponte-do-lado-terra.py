#!/usr/bin/env python3
"""A ponte do lado terra: a tela do app e' servida pelo servidor LOCAL.

Por que este teste existe (dono, 18/11/2026): no PC de captura o Admin nao listava as cameras. Medido:
o Chromium do app BLOQUEIA o pedido de uma pagina vinda do lado terra (IP publico) para
`http://127.0.0.1:8765` — "Failed to fetch" — mesmo com o servidor local respondendo 200 no `curl` e com
CORS certo. A correcao e' o servidor local servir a TELA (mesma origem das rotas de captura) e encaminhar
ao lado terra tudo o que NAO e' captura.

Este teste sobe (a) um lado terra FALSO em porta propria e (b) o `ground/api.py` de verdade apontado para
ele com `LECSOR_LADO_TERRA_API`. Prova, sem depender da VPS:

  1. `/api/saude` continua sendo DESTA maquina (nao vai ao lado terra);
  2. a pagina `/` vem do lado terra (encaminhada) e o css tambem;
  3. o status e o corpo do lado terra sao repassados como vieram (`/api/cameras` = 401);
  4. `/api/eu` volta do lado terra mas com `local: true` — e' o que libera os botoes de camera aqui;
  5. as rotas de captura NAO sao encaminhadas (respondem local, com a lista de cameras da maquina).

Uso: python tests/test-ponte-do-lado-terra.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
falhas = []


def checar(condicao: bool, texto: str) -> None:
    print(("  ok    — " if condicao else "  FALHA — ") + texto)
    if not condicao:
        falhas.append(texto)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pegar(url: str, timeout: float = 10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


class Terra(BaseHTTPRequestHandler):
    """Lado terra falso: responde o minimo para provar que o encaminhamento e' fiel."""

    def _responder(self, status: int, corpo: str, tipo: str = "application/json; charset=utf-8") -> None:
        b = corpo.encode()
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("X-Veio-Do-Terra", "sim")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        caminho = self.path.split("?")[0]
        if caminho in ("/", "/admin/", "/entrada", "/app"):
            return self._responder(200, "<!doctype html><title>PAGINA-DO-TERRA</title>terra", "text/html")
        if caminho == "/fronts/vms.css":
            return self._responder(200, "body{}", "text/css")
        if caminho == "/api/cameras":
            return self._responder(401, '{"erro": "entre no sistema"}')
        if caminho == "/api/eu":
            return self._responder(200, '{"autenticado": true, "nome": "do lado terra", "local": false}')
        return self._responder(200, '{"caminho": "' + caminho + '"}')

    def log_message(self, *a):
        pass


def subir_terra() -> tuple[ThreadingHTTPServer, str]:
    porta = porta_livre()
    s = ThreadingHTTPServer(("127.0.0.1", porta), Terra)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"http://127.0.0.1:{porta}"


def subir_local(lado_terra: str) -> tuple[subprocess.Popen, str]:
    porta = porta_livre()
    temp = tempfile.mkdtemp(prefix="ponte-")
    env = dict(os.environ)
    env["LECSOR_LADO_TERRA_API"] = lado_terra
    env["LECSOR_BANCO"] = str(Path(temp) / "pipeline.db")
    env["LECSOR_GRAVACOES_DIR"] = str(Path(temp) / "gravacoes")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{porta}"
    for _ in range(30):
        if pegar(base + "/api/saude")[0] == 200:
            return proc, base
        time.sleep(0.5)
    proc.terminate()
    raise SystemExit("o servidor local nao subiu para o teste")


def principal() -> int:
    terra, lado_terra = subir_terra()
    local_proc, base = subir_local(lado_terra)
    try:
        print("ponte do lado terra — servidor local servindo a TELA e encaminhando o resto")
        status, corpo = pegar(base + "/api/saude")
        checar(status == 200 and '"banco"' in corpo, "a saude continua sendo a DESTA maquina (nao vai ao lado terra)")

        status, corpo = pegar(base + "/")
        checar(status == 200 and "PAGINA-DO-TERRA" in corpo, "a pagina do lado terra e' servida pelo servidor local")

        status, corpo = pegar(base + "/admin/")
        checar(status == 200 and "PAGINA-DO-TERRA" in corpo, "a tela do Admin tambem vem do lado terra, por aqui")

        status, _ = pegar(base + "/fronts/vms.css")
        checar(status == 200, "o css do lado terra e' repassado (a tela nao abre sem ele)")

        status, corpo = pegar(base + "/api/cameras")
        checar(status == 401 and "entre no sistema" in corpo, "status e corpo do lado terra voltam como vieram (401 do cadastro)")

        status, corpo = pegar(base + "/api/eu")
        checar(status == 200 and '"autenticado": true' in corpo, "quem sou eu vem do lado terra (a sessao e' de la)")
        checar(json.loads(corpo).get("local") is True, "mas `local` e' TRUE: o pedido veio pela ponte DESTA maquina (libera a camera)")

        status, corpo = pegar(base + "/api/dispositivos")
        checar(status == 200 and ("video" in corpo or "dispositivos" in corpo),
               "as rotas de captura NAO sao encaminhadas: respondem aqui, com as cameras desta maquina")
    finally:
        local_proc.terminate()
        terra.shutdown()

    if falhas:
        print(f"\nPONTE_FALHOU — {len(falhas)} checagem(ns) vermelha(s)")
        return 1
    print("\nPONTE_DO_LADO_TERRA_OK — a tela vem do lado terra servida por esta maquina, com a captura local.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
