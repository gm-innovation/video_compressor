"""A MEDICAO de qualidade (SSIM) do fluxo ao vivo tem que CHEGAR ao lado terra.

Furo do dono: "a cam02 esta perdendo bastante qualidade, e ainda NAO TENHO MEDICAO DE SSIM". O SSIM
do produto exige o original e o comprimido lado a lado — a fonte crua so' existe no PC de captura —
entao o lado terra NUNCA calcula esse numero sozinho: ele precisa RECEBER. Ate' aqui a medicao rodava
no bordo e morria no banco local: `medicoes_qualidade` do lado terra tinha 0 linhas.

Este teste roda a API do lado terra de verdade (banco temporario, --semear-demo) e exige:
  1. `repasse.publicar_qualidade` (o caminho do bordo) leva o SSIM ao lado terra com o token;
  2. sem token -> 401; sem ssim -> 422; ssim fora de 0..1 -> 422;
  3. a medicao entra em `medicoes_qualidade` e NAO leva endereco nem credencial de camera;
  4. `GET /api/qualidade` so' sai para a operacao e mostra o ultimo numero, a idade e o piso,
     com o alvo sugerido quando o SSIM fica abaixo do piso.

    python tests/test-qualidade-chega-ao-lado-terra.py
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
sys.path.insert(0, str(RAIZ / "ground"))
TOKEN = "token-de-teste-qualidade"
SENHA = "teste-1234"
FLUXO = "vivo-cam-02"


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ip_local() -> str:
    """IP de rede da propria maquina (para falar com a API por fora do loopback)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 53))
            return s.getsockname()[0]
    except Exception:
        return ""


class Sessao:
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
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-qualidade-"))
    banco = tmp / "pipeline.db"
    porta = porta_livre()
    env = dict(os.environ)
    env["LECSOR_BANCO"] = str(banco)
    env["LECSOR_BIND"] = "0.0.0.0"
    env["LECSOR_TOKEN_INGESTAO"] = TOKEN
    env["LECSOR_SENHA_DEMO"] = SENHA
    env["PYTHONIOENCODING"] = "utf-8"
    for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY"):
        env.pop(k, None)
    log = (tmp / "api.log").open("wb")
    proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta), "--semear-demo"],
                            cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{porta}"
    falhas, puladas = [], []

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
            print("FALHA a API do lado terra nao subiu; log em", tmp / "api.log")
            return 1

        bordo = Sessao(base)
        s, _ = bordo.pedir("/api/qualidade/anuncio", {"fluxo_id": FLUXO, "ssim": 0.99})
        exigir(s == 401, "medicao SEM token e' recusada (http %s)" % s)
        s, _ = bordo.pedir("/api/qualidade/anuncio", {"fluxo_id": FLUXO}, token=TOKEN)
        exigir(s == 422, "medicao sem ssim e' recusada (http %s)" % s)
        s, _ = bordo.pedir("/api/qualidade/anuncio", {"fluxo_id": FLUXO, "ssim": 42}, token=TOKEN)
        exigir(s == 422, "ssim fora de 0..1 e' recusado (http %s)" % s)
        # endereco/credencial de camera NAO existem nesta rota: mandar de proposito nao vira coluna
        s, j = bordo.pedir("/api/qualidade/anuncio",
                           {"fluxo_id": FLUXO, "ssim": 0.9871, "ajuste": "1500k", "resolucao": "1920x1080",
                            "fps": 30, "ip": "192.168.0.50", "senha": "nao-deve-entrar",
                            "fonte": "dshow:@device_pnp_x"}, token=TOKEN)
        exigir(s == 201 and j.get("ok"), "medicao com token entra (http %s, ssim %s)" % (s, j.get("ssim")))
        con = sqlite3.connect(banco)
        linha = con.execute("SELECT fluxo_id, ssim, ajuste FROM medicoes_qualidade WHERE fluxo_id=?",
                            (FLUXO,)).fetchone()
        colunas = [r[1] for r in con.execute("PRAGMA table_info(medicoes_qualidade)")]
        con.close()
        exigir(bool(linha) and abs(float(linha[1]) - 0.9871) < 1e-6,
               "a medicao ficou gravada no lado terra (ssim %s)" % (linha[1] if linha else None))
        exigir(not [c for c in colunas if c in ("ip", "senha", "usuario", "porta", "url")],
               "a tabela da qualidade NAO tem coluna de endereco/credencial (%s)" % colunas)

        # ---------------------------------------------------------------- a medicao do bordo sobe
        os.environ["LECSOR_LADO_TERRA_API"] = base
        os.environ["LECSOR_TOKEN_INGESTAO"] = TOKEN
        import repasse
        r = repasse.publicar_qualidade({"fluxo_id": FLUXO, "ssim": 0.9812, "ajuste": "1500k",
                                         "resolucao": "1920x1080", "fps": 30, "segundos": 8,
                                         "fonte": "dshow:@device_pnp_x", "medido_em": "2026-11-13T18:00:00-03:00"})
        exigir(r.get("ok"), "o caminho do bordo (repasse.publicar_qualidade) publica a medicao: %s"
               % (r.get("motivo") or r.get("erro") or "ok"))
        con = sqlite3.connect(banco)
        n = con.execute("SELECT count(*) FROM medicoes_qualidade WHERE fluxo_id=?", (FLUXO,)).fetchone()[0]
        fonte = con.execute("SELECT fonte FROM medicoes_qualidade WHERE fluxo_id=? ORDER BY id DESC LIMIT 1",
                            (FLUXO,)).fetchone()
        con.close()
        exigir(n == 2, "as duas medicoes ficaram no lado terra (%d)" % n)
        exigir(bool(fonte) and "@device_pnp" in fonte[0],
               "a medicao publicada leva a fonte da camera (e' ela que identifica a mesma camera): %r"
               % (fonte[0] if fonte else None))

        # ---------------------------------------------------------------- quem pode LER o numero
        operacao = Sessao(base)
        s, j = operacao.pedir("/api/entrar", {"email": "operacao@lecsor.test", "senha": SENHA})
        exigir(s == 200 and j.get("ok"), "operacao autenticou (http %s)" % s)
        s, j = operacao.pedir("/api/qualidade")
        fluxo = next((f for f in j.get("fluxos", []) if f["fluxo_id"] == FLUXO), None)
        exigir(s == 200 and bool(fluxo), "a operacao ve a medicao do fluxo (http %s)" % s)
        exigir(bool(fluxo) and abs(float(fluxo["ssim"]) - 0.9812) < 1e-6,
               "a tela mostra o ULTIMO ssim medido (%s)" % (fluxo or {}).get("ssim"))
        exigir(bool(fluxo) and isinstance(fluxo.get("idade_s"), int),
               "a medicao vem com a idade em segundos (qualidade sem 'medida quando' nao vale): %s"
               % (fluxo or {}).get("idade_s"))
        exigir(j.get("piso_aceito") is not None and j.get("piso_qualidade") is not None,
               "a tela recebe os pisos de qualidade (aceito %s / ssim %s)"
               % (j.get("piso_aceito"), j.get("piso_qualidade")))
        exigir(bool(fluxo) and fluxo.get("passa") is True,
               "0.9812 esta ACIMA do piso aceito (piso %s) e a tela diz isso (passa=%s)"
               % (j.get("piso_aceito"), (fluxo or {}).get("passa")))
        # agora um numero ABAIXO do piso: e' o caso do dono ("a cam02 esta perdendo qualidade")
        s, _ = bordo.pedir("/api/qualidade/anuncio", {"fluxo_id": FLUXO, "ssim": 0.95, "ajuste": "1500k"},
                           token=TOKEN)
        exigir(s == 201, "a segunda medicao (abaixo do piso) entrou (http %s)" % s)
        s, j = operacao.pedir("/api/qualidade")
        fluxo = next((f for f in j.get("fluxos", []) if f["fluxo_id"] == FLUXO), None)
        exigir(bool(fluxo) and abs(float(fluxo["ssim"]) - 0.95) < 1e-6,
               "a tela passa a mostrar o ULTIMO numero (0.95): %s" % (fluxo or {}).get("ssim"))
        exigir(bool(fluxo) and fluxo.get("passa") is False,
               "0.95 esta ABAIXO do piso aceito e a tela diz isso (passa=%s)" % (fluxo or {}).get("passa"))

        # a sugestao do proximo alvo: alvo atual 1500k -> 2300k (1,5x arredondado na centena)
        captura = Sessao(base)
        s, j = captura.pedir("/api/entrar", {"email": "admin@lecsor.test", "senha": SENHA})
        exigir(s == 200 and j.get("ok"), "admin autenticou (http %s)" % s)
        s, j = captura.pedir("/api/cameras", {"id": FLUXO, "fluxo_id": FLUXO, "rotulo": "CAM 02",
                                              "embarcacao_id": "bancada", "alvo": "1500k"})
        exigir(s == 201, "admin gravou o alvo da cam-02 (http %s)" % s)
        s, j = operacao.pedir("/api/qualidade")
        fluxo = next((f for f in j.get("fluxos", []) if f["fluxo_id"] == FLUXO), None)
        exigir(bool(fluxo) and fluxo.get("alvo_atual") == "1500k",
               "a qualidade mostra o alvo atual da camera: %r" % (fluxo or {}).get("alvo_atual"))
        exigir(bool(fluxo) and fluxo.get("alvo_sugerido") == "2300k",
               "com SSIM abaixo do piso a tela sugere o proximo alvo: %r" % (fluxo or {}).get("alvo_sugerido"))

        s, j = captura.pedir("/api/cameras/%s/alvo" % FLUXO, {"alvo": "nao-e-numero"})
        exigir(s == 422, "alvo invalido e' recusado (http %s)" % s)
        s, j = captura.pedir("/api/cameras/%s/alvo" % FLUXO, {"alvo": "2300"})
        exigir(s == 200 and j.get("alvo") == "2300k", "alvo gravado por numero vira kbps: %r" % j.get("alvo"))
        con = sqlite3.connect(banco)
        gravado = con.execute("SELECT alvo FROM cameras WHERE id=?", (FLUXO,)).fetchone()
        con.close()
        exigir(bool(gravado) and gravado[0] == "2300k", "o alvo ficou no cadastro da camera: %r"
               % (gravado[0] if gravado else None))

        # ------------------------------------------------- o cliente nunca ve a metrica da operacao
        lan = ip_local()
        if lan and lan != "127.0.0.1":
            cliente = Sessao(f"http://{lan}:{porta}")
            s, j = cliente.pedir("/api/entrar", {"email": "cliente@lecsor.test", "senha": SENHA})
            exigir(s == 200 and j.get("ok"), "cliente autenticou de FORA da maquina (http %s)" % s)
            s, j = cliente.pedir("/api/qualidade")
            exigir(s == 403, "de fora da maquina, o CLIENTE nao le a metrica da operacao (http %s)" % s)
        else:
            puladas.append("sem interface de rede: a checagem do papel 'cliente' nao foi executada")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        log.close()

    print()
    for p in puladas:
        print("PULADA:", p)
    if falhas:
        print("FALHOU: %d verificacao(oes) — log em %s" % (len(falhas), tmp / "api.log"))
        return 1
    print("PASSOU: a medicao de SSIM do fluxo ao vivo chega ao lado terra, com idade e alvo sugerido")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
