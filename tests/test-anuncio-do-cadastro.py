#!/usr/bin/env python3
"""O anúncio do cadastro ao lado terra: o que faz a câmera aparecer no cliente.

Por que este teste existe (dono, 18/11/2026): ele cadastrou as câmeras no PC de captura, deixou no ar,
e elas não apareceram em "Tempo real", "Produção" nem na tela do cliente. O vídeo chegava no lado terra
(os fluxos apareciam "no ar, sem cadastro") e o cadastro não saía — e a falha existia SÓ no arquivo de
log `ground/envios/log/repasse-<fluxo>.log`, sem nada na tela.

A causa medida: o servidor do PC de captura subia SEM `LECSOR_TOKEN_INGESTAO`/`LECSOR_EMBARCACAO` (o
app lia `ambiente.json` na raiz e o instalador grava em `ground/ambiente.json`). Este teste sobe um
lado terra FALSO e o `ground/api.py` de verdade e prova:

  1. sem token: a saúde declara o anúncio fora do ar, a tela diz o motivo por câmera
     (`/api/publicacao`) e publicar devolve 0 de N — nada de silêncio;
  2. com token: o cadastro chega ao lado terra (com fluxo, rótulo e embarcação; nunca endereço, porta
     ou credencial) — e chega SOZINHO quando o servidor sobe, sem ninguém clicar em nada.

Cada caso usa banco e arquivo de estado próprios (nada de herdar tentativa de rodada anterior).
Uso: python tests/test-anuncio-do-cadastro.py
"""
import json
import os
import socket
import sqlite3
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
falhas: list = []
recebidos: list = []          # o que o lado terra falso recebeu em /api/cameras/anuncio
TOKEN = "token-de-teste-do-anuncio"


def checar(condicao: bool, texto: str) -> None:
    print(("  ok    — " if condicao else "  FALHA — ") + texto)
    if not condicao:
        falhas.append(texto)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pegar(url: str, dados: dict | None = None, timeout: float = 10):
    corpo = json.dumps(dados).encode() if dados is not None else None
    req = urllib.request.Request(url, data=corpo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:  # noqa: BLE001
        return 0, {"erro": f"{type(e).__name__}: {e}"}


class Terra(BaseHTTPRequestHandler):
    """Lado terra falso: aceita o anúncio e guarda o que recebeu (para o teste conferir)."""

    def _json(self, status: int, corpo: dict) -> None:
        b = json.dumps(corpo).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length") or 0)
        cru = self.rfile.read(tamanho) if tamanho else b"{}"
        try:
            corpo = json.loads(cru or b"{}")
        except Exception:
            corpo = {}
        if self.path.split("?")[0] == "/api/cameras/anuncio":
            if (self.headers.get("Authorization") or "") != "Bearer " + TOKEN:
                return self._json(401, {"erro": "token de ingestao invalido"})
            recebidos.append(corpo)
            return self._json(200, {"ok": True, "id": corpo.get("id") or corpo.get("fluxo_id"),
                                    "embarcacao_id": corpo.get("embarcacao_id") or ""})
        return self._json(404, {"erro": "rota desconhecida"})

    def do_GET(self):
        return self._json(200, {"ok": True, "lado": "terra-falso"})

    def log_message(self, *a):
        pass


def subir_terra():
    porta = porta_livre()
    s = ThreadingHTTPServer(("127.0.0.1", porta), Terra)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"http://127.0.0.1:{porta}"


def ambiente_do_caso(prefixo: str, lado_terra: str, *, token: str, embarcacao: str = "bancada") -> dict:
    temp = Path(tempfile.mkdtemp(prefix=prefixo))
    env = dict(os.environ)
    env["LECSOR_LADO_TERRA_API"] = lado_terra
    env["LECSOR_BANCO"] = str(temp / "pipeline.db")
    env["LECSOR_GRAVACOES_DIR"] = str(temp / "gravacoes")
    env["LECSOR_REPASSE_ESTADO"] = str(temp / "estado.json")   # estado só deste caso
    env.pop("LECSOR_DESTINO_SRT", None)
    if token:
        env["LECSOR_TOKEN_INGESTAO"] = token
    else:
        env.pop("LECSOR_TOKEN_INGESTAO", None)
    if embarcacao:
        env["LECSOR_EMBARCACAO"] = embarcacao
    else:
        env.pop("LECSOR_EMBARCACAO", None)
    return env


def subir_local(env: dict, lado_terra_em_si: bool = False):
    porta = porta_livre()
    if lado_terra_em_si:
        # a instalacao cujo papel E' o lado terra: o `ambiente.json` do pacote traz o endereco dela
        # propria, na mesma porta em que ela atende (e' assim que a VPS sobe: `api.py 8085`)
        env["LECSOR_LADO_TERRA_API"] = f"http://127.0.0.1:{porta}"
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta)],
                            cwd=str(RAIZ), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{porta}"
    for _ in range(40):
        if pegar(base + "/api/saude")[0] == 200:
            return proc, base
        time.sleep(0.5)
    proc.terminate()
    raise SystemExit("o servidor local nao subiu para o teste")


def cadastrar_no_banco(env: dict, fluxo: str, rotulo: str, embarcacao: str = "") -> None:
    """A câmera entra direto no banco desta instalação (o cadastro pela tela é provado em outro teste).

    Aqui o que importa é o que acontece DEPOIS do cadastro: o anúncio ao lado terra. Sem embarcação no
    cadastro, quem manda é a do pacote (`LECSOR_EMBARCACAO`) — é o que este teste confere.
    """
    caminho = Path(env["LECSOR_BANCO"])
    for _ in range(20):
        if caminho.exists():
            break
        time.sleep(0.5)
    c = sqlite3.connect(str(caminho), timeout=10)
    try:
        c.execute("INSERT OR REPLACE INTO cameras (id, rotulo, fluxo_id, embarcacao_id, ativo, local) "
                  "VALUES (?, ?, ?, ?, 1, 1)", (fluxo, rotulo, fluxo, embarcacao))
        c.commit()
    finally:
        c.close()


def principal() -> int:
    terra, lado_terra = subir_terra()
    print("anúncio do cadastro — a câmera do PC de captura chega ao lado terra (e a tela diz quando não)")

    # ---------------------------------------------------------------- 1) sem token: falha VISÍVEL
    env1 = ambiente_do_caso("anuncio-sem-", lado_terra, token="", embarcacao="")
    local1, base1 = subir_local(env1)
    try:
        _, saude = pegar(base1 + "/api/saude")
        an = saude.get("anuncio") or {}
        checar(an.get("de_pe") is False, "sem token, a saude diz que o anuncio NAO esta de pe")
        checar(any("token" in f for f in (an.get("faltando") or [])),
               "e diz exatamente o que falta (token de ingestao)")
        cadastrar_no_banco(env1, "sem-token-1", "Câmera sem token")
        _, r = pegar(base1 + "/api/publicacao", dados={})
        checar(r.get("publicadas") == 0 and (r.get("total") or 0) >= 1,
               "publicar devolve 0 de N (nao finge que publicou)")
        alvo = next((l for l in (r.get("cameras") or []) if l.get("fluxo_id") == "sem-token-1"), None)
        checar(bool(alvo) and alvo.get("publicado") is False and bool(alvo.get("motivo")),
               "a tela mostra a camera como NAO publicada, com o motivo escrito")
        checar(not recebidos, "e nada foi anunciado ao lado terra (o teste nao mente por acaso)")
    finally:
        local1.terminate()

    # ---------------------------------------------------------------- 2) com token: publica de verdade
    recebidos.clear()
    env2 = ambiente_do_caso("anuncio-com-", lado_terra, token=TOKEN)
    local2, base2 = subir_local(env2)
    try:
        _, saude = pegar(base2 + "/api/saude")
        an = saude.get("anuncio") or {}
        checar(an.get("de_pe") is True and an.get("token") is True and an.get("embarcacao") == "bancada",
               "com token, a saude diz que o anuncio esta de pe, com a embarcacao do pacote")
        cadastrar_no_banco(env2, "cam-01-anuncio", "Câmera 1 do anúncio")
        _, r = pegar(base2 + "/api/publicacao", dados={})
        checar((r.get("publicadas") or 0) >= 1 and r.get("ok") is True,
               "publicar agora devolve sucesso com o total certo")
        checar(any(c.get("fluxo_id") == "cam-01-anuncio" and c.get("embarcacao_id") == "bancada"
                   for c in recebidos),
               "o anuncio chega ao lado terra com o fluxo e a embarcacao")
        checar(any(c.get("rotulo") == "Câmera 1 do anúncio" for c in recebidos),
               "o anuncio leva o rotulo (a tela do cliente mostra o nome da camera)")
        checar(not any(any(k in c for k in ("ip", "porta", "senha", "captura", "usuario"))
                       for c in recebidos),
               "e NUNCA leva endereco, porta ou credencial de camera")
        alvo = next((l for l in (r.get("cameras") or []) if l.get("fluxo_id") == "cam-01-anuncio"), None)
        checar(bool(alvo) and alvo.get("publicado") is True,
               "a tela de publicacao mostra a camera como publicada")
    finally:
        local2.terminate()

    # ---------------------------------------------------------------- 3) sobe sozinho (sem clique)
    recebidos.clear()
    local3, _ = subir_local(env2)     # mesmo banco e mesmo ambiente do caso 2
    try:
        for _ in range(60):
            if recebidos:
                break
            time.sleep(0.5)
        checar(any(c.get("fluxo_id") == "cam-01-anuncio" for c in recebidos),
               "o cadastro sobe SOZINHO ao subir o servidor (ninguem precisa clicar)")
    finally:
        local3.terminate()

    # ------------------------------------------- 4) esta maquina E' o lado terra: nao publica para si
    recebidos.clear()
    env4 = ambiente_do_caso("anuncio-terra-", "", token=TOKEN)
    local4, base4 = subir_local(env4, lado_terra_em_si=True)
    try:
        _, saude = pegar(base4 + "/api/saude")
        an = saude.get("anuncio") or {}
        checar(an.get("sou_o_lado_terra") is True and an.get("de_pe") is True,
               "no proprio lado terra, o anuncio se declara DESNECESSARIO (de pe) em vez de erro")
        cadastrar_no_banco(env4, "cam-do-terra", "Câmera do lado terra")
        _, r = pegar(base4 + "/api/publicacao", dados={})
        alvo = next((l for l in (r.get("cameras") or []) if l.get("fluxo_id") == "cam-do-terra"), None)
        checar(bool(alvo) and alvo.get("publicado") is True and "lado terra" in str(alvo.get("motivo") or ""),
               "e a tela mostra a camera como OK, dizendo que aqui o cadastro local ja' e' o do lado terra")
        checar(not recebidos, "sem anunciar para si mesmo (nenhum pedido sai para o lado terra falso)")
    finally:
        local4.terminate()
        terra.shutdown()

    if falhas:
        print(f"\nANUNCIO_FALHOU — {len(falhas)} checagem(ns) vermelha(s)")
        return 1
    print("\nANUNCIO_DO_CADASTRO_OK — sem token a tela diz o motivo; com token o cadastro chega ao lado "
          "terra sozinho.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
