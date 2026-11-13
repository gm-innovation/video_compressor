"""O fluxo que o PC de captura envia tem que APARECER no lado terra.

O defeito da instalacao real: o fluxo chegava (mediamtx online, bytes recebidos) e o cliente nao
via nada — `GET /api/cameras` so' listava linha da tabela `cameras`, e o bordo nao escreve no banco
do lado terra. Aqui a API roda com banco temporario e o teste exige o caminho inteiro:

  1. antes do anuncio, o cliente NAO ve camera nenhuma (o fluxo nao existe para ele);
  2. `POST /api/cameras/anuncio` sem token -> 401 e sem `fluxo_id` -> 422;
  3. com o token do bordo -> 201 e a camera passa a existir para o CLIENTE (ligada a embarcacao);
  4. anunciar de novo e' idempotente (atualiza, nao duplica).

    python tests/test-fluxo-no-lado-terra.py
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
TOKEN = "token-de-teste-do-bordo"
SENHA = "teste-1234"
FLUXO = "vivo-usb-video"


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Sessao:
    """Cliente HTTP que guarda o cookie de sessao (o login e' por cookie HttpOnly)."""

    def __init__(self, base: str):
        self.base = base
        self.cookie = ""

    def pedir(self, rota: str, corpo=None, token: str | None = None):
        cabecalhos = {"Content-Type": "application/json"}
        if self.cookie:
            cabecalhos["Cookie"] = self.cookie
        if token:
            cabecalhos["Authorization"] = f"Bearer {token}"
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(self.base + rota, data=dados,
                                     method="POST" if corpo is not None else "GET", headers=cabecalhos)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
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
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-terra-"))
    banco = tmp / "pipeline.db"
    porta = porta_livre()
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["LECSOR_BIND"] = "127.0.0.1"
    env["LECSOR_TOKEN_INGESTAO"] = TOKEN
    env["LECSOR_SENHA_DEMO"] = SENHA
    env["PYTHONIOENCODING"] = "utf-8"
    # sem Supabase: o login aqui e' o hash local (bancada sem rede), que e' o que queremos provar
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY"):
        env.pop(k, None)
    log = (tmp / "api.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta), "--semear-demo"],
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

        bordo = Sessao(base)
        s, j = bordo.pedir("/api/cameras/anuncio", {"fluxo_id": FLUXO})
        exigir(s == 401, "anuncio SEM token e' recusado (http %s)" % s)
        s, j = bordo.pedir("/api/cameras/anuncio", {}, token=TOKEN)
        exigir(s == 422, "anuncio sem fluxo_id e' recusado (http %s)" % s)

        cliente = Sessao(base)
        s, j = cliente.pedir("/api/entrar", {"email": "cliente@lecsor.test", "senha": SENHA})
        exigir(s == 200 and j.get("ok"), "cliente de teste autenticou (http %s)" % s)
        s, j = cliente.pedir("/api/cameras")
        antes = {c["id"] for c in j.get("cameras", [])}
        exigir(s == 200 and FLUXO not in antes,
               "antes do anuncio o cliente NAO ve o fluxo (viu %s)" % sorted(antes))

        s, j = bordo.pedir("/api/cameras/anuncio", {"fluxo_id": FLUXO, "rotulo": "Cameras do PC de captura"},
                           token=TOKEN)
        exigir(s == 201 and j.get("ok") and j.get("id") == FLUXO,
               "anuncio com token cria a camera (http %s, id %s)" % (s, j.get("id")))

        s, j = cliente.pedir("/api/cameras")
        achou = next((c for c in j.get("cameras", []) if c["id"] == FLUXO), None)
        exigir(bool(achou), "o CLIENTE passa a ver o fluxo que chega do bordo")
        exigir(bool(achou) and achou.get("embarcacao_id") == "bancada",
               "a camera ficou ligada a uma embarcacao (contrato): %r" % (achou or {}).get("embarcacao_id"))

        con = sqlite3.connect(banco)
        n = con.execute("SELECT count(*) FROM cameras WHERE id=?", (FLUXO,)).fetchone()[0]
        con.close()
        s, j = bordo.pedir("/api/cameras/anuncio", {"fluxo_id": FLUXO, "rotulo": "rotulo novo"}, token=TOKEN)
        con = sqlite3.connect(banco)
        n2 = con.execute("SELECT count(*) FROM cameras WHERE id=?", (FLUXO,)).fetchone()[0]
        rot = con.execute("SELECT rotulo FROM cameras WHERE id=?", (FLUXO,)).fetchone()
        con.close()
        exigir(n == 1 and n2 == 1, "anunciar de novo NAO duplica (antes %d, depois %d)" % (n, n2))
        exigir(bool(rot) and rot[0] == "rotulo novo", "anunciar de novo ATUALIZA o rotulo: %r" % (rot[0] if rot else None))

        # ----------------------------------------------------------------------------------------
        # Parte 2 — o CADASTRO feito no PC de captura tem que aparecer no cliente SEM esperar fluxo.
        # Defeito do dono: "cadastrei cam-01 e cam-02 no app de captura e o app do cliente nao mostra
        # nada" — a linha existia so' no banco do bordo.
        # ----------------------------------------------------------------------------------------
        porta_bordo = porta_livre()
        env_bordo = dict(env)
        env_bordo["LECSOR_BANCO"] = str(tmp / "bordo.db")
        env_bordo["LECSOR_LADO_TERRA_API"] = base          # o "lado terra" aqui e' a API de teste
        env_bordo["LECSOR_EMBARCACAO"] = "bancada"
        log_bordo = (tmp / "bordo.log").open("wb")
        bordo_proc = subprocess.Popen(
            [sys.executable, str(RAIZ / "ground" / "api.py"), str(porta_bordo), "--semear-demo"],
            cwd=str(RAIZ), env=env_bordo, stdout=log_bordo, stderr=subprocess.STDOUT)
        base_bordo = f"http://127.0.0.1:{porta_bordo}"
        try:
            for _ in range(60):
                time.sleep(0.5)
                try:
                    with urllib.request.urlopen(base_bordo + "/api/saude", timeout=2):
                        break
                except Exception:
                    continue
            else:
                exigir(False, "a API do PC de captura nao subiu; log em %s" % (tmp / "bordo.log"))
                raise SystemExit(1)

            captura = Sessao(base_bordo)
            s, j = captura.pedir("/api/entrar", {"email": "admin@lecsor.test", "senha": SENHA})
            exigir(s == 200 and j.get("ok"), "admin do PC de captura autenticou (http %s)" % s)
            s, j = captura.pedir("/api/cameras", {"id": "cam-01", "fluxo_id": "cam-01",
                                                  "rotulo": "CAM 01", "ip": "192.168.0.50",
                                                  "porta": "554", "embarcacao_id": "bancada"})
            exigir(s == 201 and (j.get("lado_terra") or {}).get("ok"),
                   "cadastrar cam-01 no PC de captura publica no lado terra (http %s, lado_terra=%s)"
                   % (s, (j.get("lado_terra") or {}).get("motivo") or (j.get("lado_terra") or {}).get("ok")))

            s, j = cliente.pedir("/api/cameras")
            cam01 = next((c for c in j.get("cameras", []) if c["id"] == "cam-01"), None)
            exigir(bool(cam01), "o CLIENTE ve a camera cam-01 cadastrada no bordo (viu %s)"
                   % sorted(c["id"] for c in j.get("cameras", [])))
            exigir(bool(cam01) and cam01.get("embarcacao_id") == "bancada",
                   "cam-01 ficou na embarcacao do bordo: %r" % (cam01 or {}).get("embarcacao_id"))
            exigir(not (cam01 or {}).get("ip") and not (cam01 or {}).get("porta"),
                   "o cadastro publico NAO leva endereco da camera (ip=%r porta=%r)"
                   % ((cam01 or {}).get("ip"), (cam01 or {}).get("porta")))

            # cam-02 registrada ANTES desta correcao: existe so' no banco do bordo; o botao/rota de
            # publicar tem que leva-la ao lado terra sem recadastrar.
            con = sqlite3.connect(tmp / "bordo.db")
            con.execute("INSERT OR REPLACE INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo)"
                        " VALUES ('cam-02','bancada','CAM 02','cam-02','',1)")
            con.commit()
            con.close()
            s, j = captura.pedir("/api/cameras/publicar", {})
            exigir(s == 200 and "cam-02" in (j.get("publicadas") or []),
                   "publicar o cadastro existente alcanca cam-02 (http %s, %s)" % (s, j))
            s, j = cliente.pedir("/api/cameras")
            exigir(any(c["id"] == "cam-02" for c in j.get("cameras", [])),
                   "o CLIENTE passa a ver a cam-02 registrada antes da correcao")
        finally:
            bordo_proc.terminate()
            try:
                bordo_proc.wait(timeout=10)
            except Exception:
                bordo_proc.kill()
            log_bordo.close()
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
    print("PASSOU: o fluxo enviado pelo bordo aparece no lado terra para o cliente")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
