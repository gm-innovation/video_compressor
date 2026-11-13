"""Duas cameras com cenas diferentes NAO podem sair com o mesmo alvo — e o perfil tem que parar de
jogar qualidade fora.

Medido no lado terra em 2026-11-13: `vivo-cam-01` e `vivo-cam-02` chegavam os DOIS em H.264
**Baseline** e alvos praticamente iguais (1485 e 1500 kbps), com nitidez diferente (blur 4,60 x 5,77).
Duas causas reais:
  1. `-preset ultrafast` do x264 desliga o CABAC e o fluxo cai para Baseline: no MESMO bitrate
     entrega menos qualidade (o fluxo de bancada da VPS, esse, sai High);
  2. o alvo era um numero unico para a tela inteira, e a medicao media 3000k enquanto o fluxo subia
     em 1500k (o SSIM mostrado era de outro ajuste).

Este teste exige:
  1. o ajuste do envio usa perfil High (CABAC) e o preset vem de um lugar so';
  2. a MEDICAO usa exatamente o mesmo ajuste do fluxo (senao o numero nao vale);
  3. alvo POR CAMERA: cam-02 com 2500k sai 2500k e cam-01 com 1500k sai 1500k;
  4. camera sem alvo gravado continua no padrao de antes (sem regressao);
  5. o alvo NAO sai no cadastro publicado ao lado terra (nao e' dado de cliente).

    python tests/test-alvo-e-perfil-por-camera.py
"""
import json
import os
import pathlib
import socket
import sqlite3
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "ground"))
TOKEN = "token-de-teste-alvo"


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LadoTerra(BaseHTTPRequestHandler):
    recebidos = []

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        corpo = json.loads(self.rfile.read(n) or b"{}")
        LadoTerra.recebidos.append({"rota": self.path, "corpo": corpo,
                                    "autorizado": (self.headers.get("Authorization") or "") == "Bearer " + TOKEN})
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "id": corpo.get("id", ""),
                                     "embarcacao_id": corpo.get("embarcacao_id", "")}).encode())

    def log_message(self, *a):
        pass


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-alvo-"))
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

    con = sqlite3.connect(os.environ["LECSOR_BANCO"])
    esquemas = [RAIZ / "db" / "schema.sql"] + sorted(
        p for p in (RAIZ / "db").glob("schema*.sql") if p.name != "schema.sql")
    for esquema in esquemas:
        con.executescript(esquema.read_text(encoding="utf-8"))
    con.execute("INSERT OR IGNORE INTO embarcacoes (id,cliente_id,nome,imo,estado)"
                " VALUES ('bancada','lecsor','Bancada de testes','','em operacao')")
    con.execute("INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo)"
                " VALUES ('cam-01','bancada','CAM 01','vivo-cam-01','',1,'1500k')")
    con.execute("INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo)"
                " VALUES ('cam-02','bancada','CAM 02','vivo-cam-02','',1,'2500k')")
    con.execute("INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo)"
                " VALUES ('cam-03','bancada','CAM 03','vivo-cam-03','',1,'')")
    con.commit()
    con.close()

    import ingestao
    import qualidade

    # ---------------------------------------------------------------- 1. perfil e preset do encode
    ajuste = ingestao.ajuste_encode("1500k", 30)
    junto = " ".join(ajuste)
    exigir("-profile:v high" in junto, "o encode do envio pede perfil HIGH (CABAC ligado): %s" % junto)
    exigir("veryfast" in junto and "ultrafast" not in junto,
           "o preset saiu do ultrafast (que desliga o CABAC e joga o fluxo para Baseline): %s" % junto)
    exigir("-b:v 1500k" in junto and "-g 30" in junto,
           "o bitrate pedido e o GOP de 1 s continuam iguais (sem regressao): %s" % junto)
    exigir("-bf 0" in junto, "sem quadros B: a latencia nao sobe por causa do perfil: %s" % junto)
    exigir(ingestao.PRESET_ENCODE == "veryfast", "o preset vem de um lugar so' (LECSOR_PRESET): %s"
           % ingestao.PRESET_ENCODE)

    # ------------------------------------------------- 2. a medicao mede o MESMO ajuste do fluxo
    falso = {"tipo": "sintetica", "fonte": "lavfi:testsrc2", "resolucao": "1920x1080",
             "fps": 30, "bitrate_alvo": "2500k", "codec": "libx264"}
    cmd_bordo = ingestao._comando("lavfi:testsrc2", "vivo-cam-02", "2500k", "libx264", False, "sintetica",
                                  "127.0.0.1", 8890, fps=30, resolucao="1920x1080")
    cmd_med = qualidade._comando(falso, 4.0, tmp / "alvo.mp4", tmp / "original.mkv")
    ramo_a = " ".join(cmd_med[cmd_med.index("[a]"):cmd_med.index(str(tmp / "alvo.mp4"))])
    exigir(" ".join(ingestao.ajuste_encode("2500k", 30)) in ramo_a,
           "a medicao usa o MESMO ajuste do fluxo (High/veryfast/2500k): %s" % ramo_a)
    exigir("baseline" not in " ".join(cmd_bordo).lower(), "nenhum comando pede Baseline")
    exigir(" ".join(ingestao.ajuste_encode("2500k", 30)) in " ".join(cmd_bordo),
           "o comando do envio e' o do ajuste compartilhado (um lugar so')")

    # ---------------------------------------------------------------- 3. alvo POR CAMERA no ar
    exigir(ingestao.alvo_da_camera("vivo-cam-02") == "2500k",
           "o alvo gravado da cam-02 e' lido: %r" % ingestao.alvo_da_camera("vivo-cam-02"))
    exigir(ingestao.alvo_da_camera("vivo-cam-03") is None,
           "camera sem alvo gravado devolve None (cai no padrao de antes)")

    def subir(fluxo, rotulo):
        return ingestao.ao_vivo(tipo="sintetica", rotulo=rotulo, fluxo_id=fluxo, bitrate="auto",
                                embarcacao_id="bancada", srt_host="127.0.0.1", srt_port=porta_livre())

    r2 = subir("vivo-cam-02", "CAM 02")
    r1 = subir("vivo-cam-01", "CAM 01")
    try:
        for r, fluxo, esperado in ((r2, "vivo-cam-02", "2500k"), (r1, "vivo-cam-01", "1500k")):
            if r.get("erro"):
                exigir(False, "o envio de %s nao subiu: %s" % (fluxo, r["erro"]))
                continue
            exigir(r.get("alvo") == esperado, "%s subiu com o alvo DA CAMERA (%s): %r"
                   % (fluxo, esperado, r.get("alvo")))
            exigir("-b:v %s" % esperado in (r.get("comando") or ""),
                   "o comando de %s leva esse alvo: %s" % (fluxo, (r.get("comando") or "")[-140:]))
        exigir(r2.get("alvo") != r1.get("alvo"),
               "as duas cameras NAO saem com o mesmo alvo (era o que aparecia como 'a cam-02 pior')")

        # o cadastro publicado NAO leva o alvo (e' ajuste interno da operacao, nao dado de cliente)
        envios = [x for x in LadoTerra.recebidos if x["rota"].startswith("/api/cameras/anuncio")]
        exigir(bool(envios), "o envio publicou o cadastro (%d chamada(s))" % len(envios))
        proibidos = [k for k in ("alvo", "ip", "porta", "protocolo", "canal", "senha", "usuario")
                     if envios and k in (envios[0]["corpo"] or {})]
        exigir(not proibidos, "o cadastro publicado NAO leva alvo nem endereco/credencial (achou %s)" % proibidos)

        # ------------------------------------------------- 4. o envio ao vivo MEDE e PUBLICa o SSIM
        # Era o furo do dono ("ainda nao tenho medicao de SSIM"): a medicao do envio ao vivo rodava
        # ANTES de o fluxo existir em `ingestoes` e respondia "fluxo nao encontrado" — nunca media.
        medidas = [x for x in LadoTerra.recebidos if x["rota"] == "/api/qualidade/anuncio"]
        exigir(len(medidas) >= 1, "o envio ao vivo mediu o SSIM e publicou no lado terra (%d chamada(s))"
               % len(medidas))
        por_fluxo = {x["corpo"].get("fluxo_id"): x for x in medidas}
        exigir(all(x["autorizado"] for x in medidas), "a medicao sobe autenticada pelo token de ingestao")
        cam02 = por_fluxo.get("vivo-cam-02", {})
        exigir(float((cam02.get("corpo") or {}).get("ssim") or 0) > 0.9,
               "a cam-02 chegou com SSIM medido: %r" % ((cam02.get("corpo") or {}).get("ssim")))
        exigir((cam02.get("corpo") or {}).get("ajuste") == "2500k",
               "a medicao e' do ajuste que VAI para a rede (2500k): %r"
               % ((cam02.get("corpo") or {}).get("ajuste")))
        exigir(not [k for k in ("ip", "porta", "senha", "usuario") if k in (cam02.get("corpo") or {})],
               "a medicao publicada nao leva endereco nem credencial de camera")
    finally:
        for r in (r2, r1):
            if r.get("id"):
                try:
                    ingestao.parar(r["id"], remover_camera=False)
                except Exception:
                    pass
        servidor.shutdown()

    print()
    if falhas:
        print("FALHOU: %d verificacao(oes)" % len(falhas))
        return 1
    print("PASSOU: perfil High no ar, medicao com o mesmo ajuste e alvo por camera (sem regressao)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
