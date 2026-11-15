"""O botao "Baixar 1 minuto" do app do cliente prova que a compressao informada e' REAL.

Pedido do dono (15/11/2026): "no app do cliente um botao para baixar um trecho de 1 minuto do video que
chega na vps/terra. quero comprovar que o tamanho que o admin ou captura esta informando (mbps), para
ter a prova de que realmente a porcentagem de compressao informada e' real".

O que este teste exige, com mediamtx + publicador + API rodando DE VERDADE (tudo em porta livre e
banco temporario):
  1. `/api/fluxos/<fluxo>/trecho` entrega um MP4 do video COMO ELE CHEGA, sem reencodar (`-c copy`);
  2. o arquivo mede ~o tempo pedido e o kbps que ele prova bate com o bitrate do fluxo no ar;
  3. o atestado poe o MEDIDO (bytes x 8 / segundos) ao lado do DECLARADO pelo PC de captura, com
     `bate: true` quando os numeros conferem e `bate: false` quando NAO conferem (e' o caso que o dono
     quer poder contestar);
  4. a compressao informada pelo bordo e' RECALCULADA aqui: `compressao_pct_calculada` x
     `compressao_pct_declarada`, com veredito;
  5. `sha256` do arquivo baixado e' o mesmo do atestado (o comprovante e' daquele arquivo);
  6. fluxo de outro cliente -> 403; fluxo fora do ar -> 404; id de trecho invalido -> 404/422;
  7. teto de uso: o quarto trecho do mesmo usuario na janela -> 429 (o botao nao vira gravador).

    python tests/test-trecho-1-minuto.py
"""
import hashlib
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
TOKEN = "token-de-teste-trecho"
SENHA = "teste-1234"
FLUXO = "trecho-de-prova"
KBPS_FONTE = 1500
SEGUNDOS = 10


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def esperar(url: str, tentativas: int = 80, pausa: float = 0.5) -> bool:
    for _ in range(tentativas):
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(pausa)
    return False


class Sessao:
    """Cliente HTTP com cookie de sessao; `baixar` devolve corpo cru + cabecalhos (para o MP4)."""

    def __init__(self, base: str):
        self.base = base
        self.cookie = ""

    def _cabecalhos(self, token: str | None = None) -> dict:
        h = {"Content-Type": "application/json"}
        if self.cookie:
            h["Cookie"] = self.cookie
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    def pedir(self, rota: str, corpo=None, token: str | None = None):
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(self.base + rota, data=dados,
                                     method="POST" if corpo is not None else "GET",
                                     headers=self._cabecalhos(token))
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
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

    def baixar(self, rota: str, timeout: int = 180):
        req = urllib.request.Request(self.base + rota, headers=self._cabecalhos())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()


def ip_na_rede() -> str | None:
    """IP da maquina na rede local (o cliente remoto entraria por ele)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        return ip if not ip.startswith("127.") else None
    except Exception:
        return None


def achar_ferramenta(nome: str) -> str | None:
    for p in (RAIZ / "tools" / "ffmpeg" / nome, RAIZ / "tools" / nome):
        if p.exists():
            return str(p)
    import shutil
    return shutil.which(nome)


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-trecho-"))
    banco = tmp / "pipeline.db"
    trechos_dir = tmp / "trechos"
    porta_api = porta_livre()
    porta_rtsp = porta_livre()
    porta_mtx_api = porta_livre()
    falhas, puladas = [], []

    mediamtx = RAIZ / "tools" / "mediamtx" / "mediamtx.exe"
    ffmpeg = achar_ferramenta("ffmpeg.exe") or achar_ferramenta("ffmpeg")
    if not mediamtx.exists() or not ffmpeg:
        print("PULADA: sem mediamtx/ffmpeg no repositorio (tools/) — este teste precisa dos dois")
        return 0

    conf = tmp / "mediamtx.yml"
    # rtspTransports: [tcp] e' obrigatorio: o modo UDP abre :8000/:8001 (RTP/RTCP) e, com qualquer
    # coisa nessas portas, o mediamtx RECUSA subir — foi assim que este teste falhou duas vezes.
    # As demais portas vao para portas livres para o teste nunca depender de sobra de outro processo.
    porta_metricas, porta_pprof, porta_playback = porta_livre(), porta_livre(), porta_livre()
    conf.write_text(f"""logLevel: error
rtspAddress: 127.0.0.1:{porta_rtsp}
rtspTransports: [tcp]
api: yes
apiAddress: 127.0.0.1:{porta_mtx_api}
metricsAddress: 127.0.0.1:{porta_metricas}
pprofAddress: 127.0.0.1:{porta_pprof}
playbackAddress: 127.0.0.1:{porta_playback}
hls: no
webrtc: no
srt: no
rtmp: no
playback: no
paths:
  all_others:
""", encoding="utf-8")

    log_mtx = (tmp / "mediamtx.log").open("wb")
    mtx = subprocess.Popen([str(mediamtx), str(conf)], cwd=str(RAIZ / "tools" / "mediamtx"),
                           stdout=log_mtx, stderr=subprocess.STDOUT)
    log_pub = (tmp / "publicador.log").open("wb")
    pub = None
    proc = None
    log = None

    def exigir(cond, texto):
        print(("OK   " if cond else "FALHA ") + texto)
        if not cond:
            falhas.append(texto)

    try:
        if not esperar(f"http://127.0.0.1:{porta_mtx_api}/v3/paths/list"):
            print("FALHA o mediamtx de teste nao subiu; log em", tmp / "mediamtx.log")
            print("  motivo no log:", (tmp / "mediamtx.log").read_text(errors="replace")[-300:].strip())
            return 1
        # publicador: o MESMO ajuste do produto (High, zerolatency, 1500k) para o alvo do teste
        pub = subprocess.Popen([
            str(ffmpeg), "-hide_banner", "-loglevel", "warning", "-re",
            "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-profile:v", "high",
            "-bf", "0", "-b:v", f"{KBPS_FONTE}k", "-maxrate", f"{KBPS_FONTE}k", "-bufsize", "1M",
            "-g", "30", "-pix_fmt", "yuv420p",
            "-f", "rtsp", "-rtsp_transport", "tcp", f"rtsp://127.0.0.1:{porta_rtsp}/{FLUXO}",
        ], cwd=str(tmp), stdout=log_pub, stderr=subprocess.STDOUT)

        env = dict(os.environ)
        env["LECSOR_BANCO"] = str(banco)
        # 0.0.0.0 para o teste poder falar tambem como CLIENTE REMOTO (127.0.0.2 nao e' loopback para a
        # API): sem isso a trava "camera de outro cliente" nao seria exercitada de verdade
        env["LECSOR_BIND"] = "0.0.0.0"
        env["LECSOR_TOKEN_INGESTAO"] = TOKEN
        env["LECSOR_SENHA_DEMO"] = SENHA
        env["LECSOR_PORTA_RTSP"] = str(porta_rtsp)
        env["LECSOR_PORTA_MEDIAMTX_API"] = str(porta_mtx_api)
        env["LECSOR_TRECHOS_DIR"] = str(trechos_dir)
        env["PYTHONIOENCODING"] = "utf-8"
        for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY"):
            env.pop(k, None)
        log = (tmp / "api.log").open("wb")
        proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(porta_api), "--semear-demo"],
                                cwd=str(RAIZ), env=env, stdout=log, stderr=subprocess.STDOUT)
        base = f"http://127.0.0.1:{porta_api}"

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

        # o fluxo do teste precisa estar NO AR antes de pedir o trecho
        pronto = False
        for _ in range(40):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{porta_mtx_api}/v3/paths/list", timeout=2) as r:
                    itens = json.loads(r.read()).get("items", [])
                pronto = any(p.get("name") == FLUXO and p.get("ready") for p in itens)
            except Exception:
                pronto = False
            if pronto:
                break
            time.sleep(0.5)
        if not pronto:
            print("FALHA o fluxo de teste nao ficou no ar (mediamtx/publicador); log em", tmp / "publicador.log")
            return 1

        admin = Sessao(base)
        s, j = admin.pedir("/api/entrar", {"email": "admin@lecsor.test", "senha": SENHA})
        exigir(s == 200 and j.get("ok"), "admin autenticou (http %s)" % s)
        s, j = admin.pedir("/api/cameras", {"id": FLUXO, "fluxo_id": FLUXO, "rotulo": "CAM de prova",
                                            "embarcacao_id": "bancada", "ativo": 1})
        exigir(s == 201, "a camera do fluxo foi cadastrada (http %s)" % s)

        # ---------------------------------------------------------------- 1o trecho: so' o medido
        s, cab, corpo = admin.baixar(f"/api/fluxos/{FLUXO}/trecho?segundos={SEGUNDOS}")
        exigir(s == 200 and len(corpo) > 12 and corpo[4:8] == b"ftyp",
               "o trecho veio como MP4 (http %s, %d bytes)" % (s, len(corpo)))
        exigir(cab.get("Content-Type", "").startswith("video/mp4"), "Content-Type de video (%s)" % cab.get("Content-Type"))
        exigir(int(cab.get("X-Lecsor-Bytes", 0)) == len(corpo),
               "X-Lecsor-Bytes bate com o corpo (%s x %d)" % (cab.get("X-Lecsor-Bytes"), len(corpo)))
        id1 = int(cab.get("X-Lecsor-Trecho-Id") or 0)
        exigir(id1 > 0, "o trecho ganhou id para o comprovante (%s)" % id1)
        sha1 = cab.get("X-Lecsor-Sha256") or ""
        exigir(sha1 == hashlib.sha256(corpo).hexdigest(),
               "sha256 do cabecalho e' o do arquivo baixado")
        s, at1 = admin.pedir(f"/api/trechos/{id1}/atestado")
        med = (at1.get("medido_no_arquivo") or {})
        dur = float(med.get("duracao_s") or 0)
        kbps_arq = float(med.get("kbps") or 0)
        exigir(abs(dur - SEGUNDOS) <= 2.0,
               "o arquivo mede ~%ds do fluxo ao vivo (medido %.1f s)" % (SEGUNDOS, dur))
        exigir(abs(kbps_arq - KBPS_FONTE) <= KBPS_FONTE * 0.15,
               "o arquivo prova o kbps do fluxo no ar (~%d, medido %.1f)" % (KBPS_FONTE, kbps_arq))
        exigir(med.get("sha256") == sha1, "o atestado e' do MESMO arquivo que foi baixado")
        dec = at1.get("declarado_pelo_pc_de_captura") or {}
        con = at1.get("contas") or {}
        exigir(dec.get("kbps_saida") is None and con.get("bate") is None,
               "sem o bordo declarar o kbps, o atestado NAO inventa comparacao (%r)" % con.get("bate"))
        exigir("nao informou" in (at1.get("leitura") or "") or "nao ha com o que comparar" in (at1.get("leitura") or ""),
               "sem declaracao o atestado diz isso em voz alta: %r" % (at1.get("leitura") or "")[:80])

        # ------------------------------------------------- o bordo anuncia o que ele mediu (kbps real)
        mb_alvo = round(kbps_arq * 1000 / 8 * 60 / 1e6, 2)      # o que o comprimido ocuparia em 60 s
        mb_original = round(mb_alvo * 5, 2)                      # original 5x maior = 80% de compressao
        s, _ = admin.pedir("/api/qualidade/anuncio",
                           {"fluxo_id": FLUXO, "ssim": 0.9812, "ajuste": f"{KBPS_FONTE}k",
                            "resolucao": "1280x720", "fps": 30, "segundos": 60,
                            "mb_alvo": mb_alvo, "mb_original": mb_original, "compressao_pct": 80.0},
                           token=TOKEN)
        exigir(s == 201, "o bordo anunciou a medicao com os numeros dele (http %s)" % s)

        s, cab2, corpo2 = admin.baixar(f"/api/fluxos/{FLUXO}/trecho?segundos={SEGUNDOS}")
        id2 = int(cab2.get("X-Lecsor-Trecho-Id") or 0)
        s, at2 = admin.pedir(f"/api/trechos/{id2}/atestado")
        con2 = at2.get("contas") or {}
        dec2 = at2.get("declarado_pelo_pc_de_captura") or {}
        exigir(dec2.get("origem") == "medicao de qualidade anunciada pelo bordo",
               "o atestado diz DE ONDE veio o declarado: %r" % dec2.get("origem"))
        exigir(con2.get("bate") is True,
               "o medido no arquivo bate com o declarado pelo bordo (%s x %s, dif %s%%)"
               % ((at2.get("medido_no_arquivo") or {}).get("kbps"), dec2.get("kbps_saida"), con2.get("diferenca_pct")))
        exigir(con2.get("compressao_pct_calculada") is not None and abs(con2["compressao_pct_calculada"] - 80.0) <= 1.0,
               "a compressao foi RECALCULADA aqui: %s%% (informada 80%%)" % con2.get("compressao_pct_calculada"))
        exigir(con2.get("bate_compressao") is True,
               "a porcentagem informada confere com a recalculada (%r)" % con2.get("bate_compressao"))

        # --------------------------------------------------- bordo mentindo: o atestado contesta
        s, _ = admin.pedir("/api/qualidade/anuncio",
                           {"fluxo_id": FLUXO, "ssim": 0.99, "ajuste": "3000k", "segundos": 60,
                            "mb_alvo": round(3000 * 1000 / 8 * 60 / 1e6, 2),
                            "mb_original": round(3000 * 1000 / 8 * 60 / 1e6 * 2, 2), "compressao_pct": 50.0},
                           token=TOKEN)
        s, cab3, corpo3 = admin.baixar(f"/api/fluxos/{FLUXO}/trecho?segundos={SEGUNDOS}")
        id3 = int(cab3.get("X-Lecsor-Trecho-Id") or 0)
        s, at3 = admin.pedir(f"/api/trechos/{id3}/atestado")
        con3 = at3.get("contas") or {}
        exigir(con3.get("bate") is False,
               "com o bordo declarando 3000k e chegando ~1500k o atestado diz que NAO bate (bate=%r)"
               % con3.get("bate"))
        exigir("FORA da tolerancia" in (at3.get("leitura") or ""),
               "a leitura do atestado avisa em texto: %r" % (at3.get("leitura") or "")[:90])

        # ---------------------------------------------------------------- teto de uso
        s, cab4, _ = admin.baixar(f"/api/fluxos/{FLUXO}/trecho?segundos={SEGUNDOS}")
        exigir(s == 429, "o quarto trecho do mesmo usuario na janela e' recusado (http %s)" % s)

        # ---------------------------------------------------------------- o que NAO pode passar
        s, _ = admin.pedir("/api/cameras/tc-psv/trecho")
        exigir(s == 404, "camera/fluxo que nao existe -> 404 (http %s)" % s)
        s, _ = admin.pedir("/api/trechos/abc/atestado")
        exigir(s == 422, "id de trecho nao numerico -> 422 (http %s)" % s)
        s, _ = admin.pedir("/api/trechos/987654/atestado")
        exigir(s == 404, "trecho inexistente -> 404 (http %s)" % s)
        s, _, _ = admin.baixar(f"/api/fluxos/{FLUXO}/trecho?segundos=5")
        exigir(s == 422, "pedido abaixo de 10 s e' recusado, nao arredondado calado (http %s)" % s)
        s, _, _ = admin.baixar(f"/api/fluxos/{FLUXO}/trecho?segundos=600")
        exigir(s == 422, "pedido acima de 60 s e' recusado (http %s)" % s)
        s, _, _ = admin.baixar(f"/api/fluxos/{FLUXO}/trecho?segundos=abc")
        exigir(s == 422, "segundos nao numerico -> 422 (http %s)" % s)

        # ---------------------------------------------------------------- isolamento por cliente
        # A API trata 127.0.0.1/::1 como bancada; e o Windows normaliza QUALQUER 127.x para 127.0.0.1.
        # Para falar como CLIENTE REMOTO e' preciso entrar pelo IP da propria maquina na rede — so' assim
        # a trava "camera de outro cliente" e' exercitada de verdade (e nao contornada como bancada).
        s, j = admin.pedir("/api/cameras/anuncio", {"fluxo_id": "fluxo-do-vizinho", "rotulo": "Camera do vizinho",
                                                   "embarcacao_id": "psv-exemplo"}, token=TOKEN)
        exigir(s == 201, "camera de outro cliente foi cadastrada para o teste (http %s)" % s)
        ip = ip_na_rede()
        if not ip:
            puladas.append("isolamento por cliente: a maquina nao tem IP de rede para o cliente remoto")
        else:
            base_rede = f"http://{ip}:{porta_api}"
            cliente = Sessao(base_rede)
            s, j = cliente.pedir("/api/entrar", {"email": "cliente@lecsor.test", "senha": SENHA})
            exigir(s == 200 and j.get("ok"), "cliente autenticou de fora do loopback (http %s)" % s)
            s, _, _ = cliente.baixar("/api/fluxos/fluxo-do-vizinho/trecho")
            exigir(s == 403, "cliente NAO baixa trecho de camera de outro cliente (http %s)" % s)
            s, cabC, corpoC = cliente.baixar(f"/api/fluxos/{FLUXO}/trecho?segundos={SEGUNDOS}")
            exigir(s == 200 and len(corpoC) > 10000,
                   "o cliente baixa o trecho da camera DELE pela rede (http %s, %d bytes)" % (s, len(corpoC)))

        con = sqlite3.connect(banco)
        cols = [r[1] for r in con.execute("PRAGMA table_info(trechos)")]
        n = con.execute("SELECT COUNT(*) FROM trechos").fetchone()[0]
        con.close()
        exigir(n >= 4, "os trechos ficaram registrados para auditoria (%d linhas)" % n)
        con = sqlite3.connect(banco)
        quem = [r[0] for r in con.execute("SELECT DISTINCT quem FROM trechos")]
        con.close()
        exigir(any("@" in str(q) for q in quem), "o registro guarda QUEM baixou (%s)" % quem)
        exigir(not [c for c in cols if c in ("ip", "senha", "usuario_camera", "porta", "url")],
               "o registro do trecho nao tem coluna de endereco/credencial (%s)" % cols)
    finally:
        for p in (pub, proc, mtx):
            if p:
                try:
                    p.terminate()
                    p.wait(timeout=10)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
        for f in (log_mtx, log_pub, log):
            try:
                if f:
                    f.close()
            except Exception:
                pass

    print()
    for p in puladas:
        print("PULADA:", p)
    if falhas:
        print("FALHOU: %d verificacao(oes) — log em %s" % (len(falhas), tmp / "api.log"))
        return 1
    print("PASSOU: o trecho de 1 minuto prova o tamanho/bitrate que chega ao lado terra e a compressao informada")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
