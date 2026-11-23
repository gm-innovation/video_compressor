#!/usr/bin/env python3
"""Bordo de bancada do smoke: o AGENTE DE VERDADE olhando a flag, com um atendedor da rota local.

A UNICA substituicao do smoke, declarada:

  Nesta maquina (a de engenharia) nao ha' camera plugada — `ingestao.maquina_de_captura()` e' falso e a
  rota local `POST /api/cameras/ligar` do bordo recusa ("esta maquina nao e' a de captura"). Entao, em
  vez de subir a API do bordo so' para bater nessa parede, este processo serve ESSA rota chamando a
  MESMA FUNCAO DO PRODUTO (`ingestao.ligar_camera` / `ingestao.desligar_camera`). O encode, o SRT, o
  banco e o mediamtx sao os reais; o que muda e' so' quem atende o POST.

Todo o resto e' o produto, sem atalho:
  * a RODADA inteira e' a do produto (`agente_de_ordens.uma_rodada`): flag -> aplicar_flag ->
    atender_pedidos (o HD do radar) -> publicar_catalogo -> config -> saude -> teto. O laco deste
    arquivo so' repete a rodada do produto no ritmo do `--intervalo`; um laco proprio aqui foi um
    DEFEITO (deixava de fora o catalogo e os pedidos do HD — medido em 23/11/2026), entao a unica
    coisa que este processo substitui mesmo e' QUEM atende o POST local.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RAIZ = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "ground"))

import agente_de_ordens as agente            # noqa: E402
import ingestao                              # noqa: E402


class Atendedor(BaseHTTPRequestHandler):
    """`POST /api/cameras/ligar|desligar` chamando a funcao real do produto."""

    protocol_version = "HTTP/1.1"

    def log_message(self, formato, *args):  # noqa: A003
        return

    def _responder(self, codigo: int, corpo: dict) -> None:
        dados = json.dumps(corpo).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_POST(self):  # noqa: N802
        try:  # noqa: SIM105
            tamanho = int(self.headers.get("Content-Length") or 0)
            corpo = json.loads(self.rfile.read(tamanho) or b"{}") if tamanho else {}
        except Exception:  # noqa: BLE001
            corpo = {}
        cam = str(corpo.get("camera_id") or corpo.get("id") or "").strip()
        if not cam:
            return self._responder(422, {"erro": "informe a camera"})
        try:
            if self.path.endswith("/api/cameras/ligar"):
                r = ingestao.ligar_camera(cam)
            elif self.path.endswith("/api/cameras/desligar"):
                r = ingestao.desligar_camera(cam)
            else:
                return self._responder(404, {"erro": f"rota nao atendida: {self.path}"})
        except Exception as e:  # noqa: BLE001
            return self._responder(500, {"erro": f"{type(e).__name__}: {e}"})
        return self._responder(200 if "erro" not in r else 422, r)


def principal() -> int:
    p = argparse.ArgumentParser(description="bordo de bancada do smoke")
    p.add_argument("--local", default="127.0.0.1:0", help="endereco do atendedor da rota local")
    p.add_argument("--terra", default="", help="base do lado terra")
    p.add_argument("--emb", default="", help="embarcacao")
    p.add_argument("--token", default="", help="token de ingestao (Bearer)")
    p.add_argument("--intervalo", type=float, default=2.0)
    p.add_argument("--endereco", default="", help="arquivo onde anunciar o endereco local")
    args = p.parse_args()

    host, _, porta = args.local.partition(":")
    servidor = ThreadingHTTPServer((host or "127.0.0.1", int(porta or 0)), Atendedor)
    servidor.daemon_threads = True
    local = f"http://{host or '127.0.0.1'}:{servidor.server_address[1]}"
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    if args.endereco:
        pathlib.Path(args.endereco).write_text(local, encoding="utf-8")

    base = (args.terra or agente.base_do_lado_terra() or "").rstrip("/")
    token = args.token or os.environ.get("LECSOR_TOKEN_INGESTAO") or ""
    emb = args.emb or os.environ.get("LECSOR_EMBARCACAO") or ""
    print(f"[bordo] local={local} terra={base} emb={emb}", flush=True)
    if not base or not emb:
        print("[bordo] sem lado terra ou sem embarcacao: nada a fazer", flush=True)
        return 2

    while True:
        try:
            # A RODADA E' A DO PRODUTO (flag -> aplicar_flag -> atender_pedidos -> catalogo -> config
            # -> saude -> teto). `espera=0` porque o lado terra responde a flag na hora.
            agente.uma_rodada(base, local, token, emb, 0.0)
        except Exception as e:  # noqa: BLE001
            print(f"[bordo] rodada com erro: {type(e).__name__}: {e}", flush=True)
        time.sleep(max(0.5, args.intervalo))


if __name__ == "__main__":
    raise SystemExit(principal())
