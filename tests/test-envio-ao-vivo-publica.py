"""O envio AO VIVO (tela Enviar video) tem que publicar o cadastro da camera no lado terra.

Furo real medido em 2026-11-13: o fluxo do PC de captura chegava no lado terra (`vivo-cam-01` e
`vivo-cam-02` online no mediamtx, bytes recebidos) e o app do CLIENTE continuava vazio — porque quem
sobe o fluxo por essa tela nunca avisava o lado terra. O anuncio vivia so' no caminho do repasse.

Aqui rodam o lado terra de verdade (um servidor HTTP de teste que exige o token) e a ingestao de
verdade (`ground/ingestao.py`, fonte sintetica do ffmpeg, sem camera):
  1. `iniciar()` publica o cadastro no lado terra — 201 e o corpo com id/fluxo/rotulo;
  2. o corpo NAO leva endereco, porta, protocolo nem credencial (regra do produto);
  3. sem o token certo o lado terra recusa (401) e o envio segue, dizendo na tela que nao publicou.

    python tests/test-envio-ao-vivo-publica.py
"""
import json
import os
import pathlib
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "ground"))
TOKEN = "token-de-teste-ao-vivo"
FLUXO = "cam-teste-vivo"


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LadoTerra(BaseHTTPRequestHandler):
    recebidos = []
    token = TOKEN

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        corpo = json.loads(self.rfile.read(n) or b"{}")
        autorizado = (self.headers.get("Authorization") or "") == "Bearer " + self.token
        LadoTerra.recebidos.append({"rota": self.path, "corpo": corpo, "autorizado": autorizado})
        if not autorizado:
            self.send_response(401)
        else:
            self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": autorizado, "id": corpo.get("id", ""),
                                     "embarcacao_id": corpo.get("embarcacao_id", "")}).encode())

    def log_message(self, *a):
        pass


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-ao-vivo-"))
    porta = porta_livre()
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), LadoTerra)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()

    os.environ["LECSOR_BANCO"] = str(tmp / "pipeline.db")
    os.environ["LECSOR_LADO_TERRA_API"] = f"http://127.0.0.1:{porta}"
    os.environ["LECSOR_TOKEN_INGESTAO"] = TOKEN
    os.environ["LECSOR_EMBARCACAO"] = "bancada"
    os.environ["PYTHONIOENCODING"] = "utf-8"

    falhas = []

    def exigir(cond, texto):
        print(("OK   " if cond else "FALHA ") + texto)
        if not cond:
            falhas.append(texto)

    import ingestao

    # banco novo, com o MESMO schema que a API aplica no boot (o teste roda a ingestao sozinha)
    import sqlite3
    con = sqlite3.connect(os.environ["LECSOR_BANCO"])
    esquemas = [RAIZ / "db" / "schema.sql"] + sorted(
        p for p in (RAIZ / "db").glob("schema*.sql") if p.name != "schema.sql")
    for esquema in esquemas:
        con.executescript(esquema.read_text(encoding="utf-8"))
    con.execute("INSERT OR IGNORE INTO embarcacoes (id,cliente_id,nome,imo,estado)"
                " VALUES ('bancada','lecsor','Bancada de testes','','em operacao')")
    con.commit()
    con.close()

    r = ingestao.iniciar("lavfi:testsrc2", rotulo="Cam de teste", tipo="sintetica", fluxo_id=FLUXO,
                         registrar_camera=True, abrir_log=True, embarcacao_id="bancada",
                         srt_host="127.0.0.1", srt_port=porta_livre())
    if r.get("erro"):
        print("FALHA o envio nao subiu:", r["erro"])
        return 1
    try:
        envios = [x for x in LadoTerra.recebidos if x["rota"].startswith("/api/cameras/anuncio")]
        exigir(len(envios) == 1, "o envio ao vivo publicou o cadastro no lado terra (%d chamada(s))" % len(envios))
        corpo = envios[0]["corpo"] if envios else {}
        exigir(corpo.get("id") == FLUXO and corpo.get("fluxo_id") == FLUXO,
               "publicou com o id proprio do fluxo: %r" % corpo.get("id"))
        exigir(corpo.get("embarcacao_id") == "bancada", "publicou na embarcacao do bordo: %r" % corpo.get("embarcacao_id"))
        exigir(bool(corpo.get("rotulo")), "publicou com rotulo: %r" % corpo.get("rotulo"))
        proibidos = [k for k in ("ip", "porta", "protocolo", "canal", "senha", "usuario", "url") if k in corpo]
        exigir(not proibidos, "o cadastro publicado NAO leva endereco/credencial (achou %s)" % proibidos)
        exigir("publicado no lado terra" in (r.get("aviso") or ""),
               "a tela recebe o recado de publicado: %r" % (r.get("aviso") or "")[:90])

        # token errado: o lado terra recusa e o envio CONTINUA, dizendo na tela que nao publicou
        LadoTerra.recebidos.clear()
        LadoTerra.token = "outro-token"
        os.environ["LECSOR_TOKEN_INGESTAO"] = "token-errado"
        r2 = ingestao.iniciar("lavfi:testsrc2", rotulo="Cam de teste 2", tipo="sintetica",
                              fluxo_id=FLUXO + "-2", registrar_camera=True, abrir_log=True,
                              embarcacao_id="bancada", srt_host="127.0.0.1", srt_port=porta_livre())
        exigir(not r2.get("erro"), "o envio sobe mesmo quando o lado terra recusa o cadastro")
        exigir("NAO tem esta camera" in (r2.get("aviso") or ""),
               "a tela diz que o lado terra nao tem a camera: %r" % (r2.get("aviso") or "")[:90])
        for ident in (r.get("id"), r2.get("id")):
            if ident:
                ingestao.parar(ident, remover_camera=True)
    finally:
        try:
            ingestao.parar(r["id"], remover_camera=True)
        except Exception:
            pass
        servidor.shutdown()

    print()
    if falhas:
        print("FALHOU: %d verificacao(oes)" % len(falhas))
        return 1
    print("PASSOU: o envio ao vivo publica o cadastro da camera no lado terra, sem endereco nem credencial")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
