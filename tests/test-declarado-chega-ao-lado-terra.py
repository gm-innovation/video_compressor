"""O que o PC de captura DECLARA do envio tem de chegar ao lado terra, junto com o video.

Pedido do dono (15/11/2026): "precisamos ter esses comparativos, precisamos de todas as informacoes, e
ate onde eu sei, ja fizemos as alteracoes no app de captura pra ele enviar as informacoes junto com o
video". A tela mostrava `declarado pelo PC de captura: nao informado` porque os numeros do envio nasciam
na tabela `ingestoes` DO BORDO e nunca saiam de la: o lado terra nao tinha com o que comparar.

O que este teste exige, com mediamtx + publicador + API rodando DE VERDADE (portas livres, banco
temporario):

  1. `POST /api/envios/anuncio` (token de ingestao) grava a declaracao do envio na tabela `ingestoes`
     do LADO TERRA — kbps de entrada, kbps de saida, corte, alvo, codec, resolucao, fps e o carimbo;
  2. sem token (ou com token errado) a rota RECUSA (401) e a tentativa fica registrada, com o motivo:
     "nada chegou" deixa de ser indistinguivel de "tentou e foi recusado";
  3. `GET /api/declarado` mostra o que o bordo declara por fluxo, com hora/idade, e quem tentou sem
     conseguir; so' operacao/admin veem (o cliente nao);
  4. o atestado do trecho de 1 minuto passa a ter os DOIS lados: o medido no arquivo x o declarado pelo
     PC de captura, com `bate: true` quando confere e `bate: false` quando o bordo informa um kbps que
     nao corresponde ao que chega (e' o caso que o dono quer poder contestar);
  5. a compressao informada e' recalculada no lado terra com o kbps de ENTRADA declarado;
  6. a medicao de qualidade REAPROVEITADA (cache) tambem e' publicada: antes, medicao recente = nenhuma
     publicacao, e o lado terra ficava com 0 linhas;
  7. o comprovante que sai para o cliente NAO leva endereco/IP de quem declarou.

    python tests/test-declarado-chega-ao-lado-terra.py
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
TOKEN = "token-de-teste-declarado"
SENHA = "teste-1234"
FLUXO = "declarado-de-prova"
KBPS_SAIDA = 1500          # o que o publicador manda para a rede
KBPS_ENTRADA = 6000        # o que o bordo declara receber da camera (antes de comprimir)
CORTE_PCT = 75.0           # 6000 -> 1500
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


def checar_publicacao_no_cache(banco: pathlib.Path) -> tuple[bool, str]:
    """Prova, sem subir a API, que a medicao REAPROVEITADA tambem sobe para o lado terra.

    Era o furo do "medicoes_qualidade = 0 linhas": `medir_se_preciso` devolvia a medicao recente sem
    republicar, e o lado terra nunca sabia do numero. Aqui entra uma medicao fresca no banco e a
    funcao tem de dizer `pulado: True` E chamar `repasse.publicar_qualidade` com os mesmos numeros.
    """
    os.environ["LECSOR_BANCO"] = str(banco)
    sys.path.insert(0, str(RAIZ / "ground"))
    for m in ("ferramentas", "ingestao", "qualidade", "repasse"):
        sys.modules.pop(m, None)
    import qualidade  # noqa: E402
    import repasse  # noqa: E402

    qualidade.garantir_tabela()
    with qualidade.conexao_banco() as c:
        c.execute("""INSERT INTO medicoes_qualidade (fluxo_id, ssim, ajuste, resolucao, fps, segundos,
                     mb_alvo, mb_original, compressao_pct, fonte, medido_em)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                  (FLUXO, 0.9821, "1500k", "1280x720", 30, 8, 1.4, 5.6, 75.0, "dshow:cam",
                   qualidade.agora()))
    capturado = {}

    def falso(medicao, destino=None):
        capturado.update(medicao)
        capturado["_destino"] = destino
        return {"ok": True, "resposta": {"ok": True}}

    original = repasse.publicar_qualidade
    repasse.publicar_qualidade = falso
    try:
        r = qualidade.medir_se_preciso(FLUXO, validade_s=600, segundos=8, bitrate="1500k")
    finally:
        repasse.publicar_qualidade = original
    if not r.get("pulado"):
        return False, f"a medicao fresca NAO foi reaproveitada: {r}"
    if not capturado:
        return False, "a medicao reaproveitada NAO foi publicada no lado terra (cache engoliu)"
    if float(capturado.get("ssim") or 0) != 0.9821 or float(capturado.get("compressao_pct") or 0) != 75.0:
        return False, f"publicou numeros diferentes do cache: {capturado}"
    if not r.get("lado_terra"):
        return False, "a resposta nao conta se publicou no lado terra"
    return True, f"pulado=%s e publicou SSIM {capturado.get('ssim')} (destino {capturado.get('_destino')!r})" % r.get("pulado")


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-declarado-"))
    banco = tmp / "pipeline.db"
    trechos_dir = tmp / "trechos"
    porta_api, porta_rtsp, porta_mtx_api = porta_livre(), porta_livre(), porta_livre()
    falhas, puladas = [], []

    mediamtx = RAIZ / "tools" / "mediamtx" / "mediamtx.exe"
    ffmpeg = achar_ferramenta("ffmpeg.exe") or achar_ferramenta("ffmpeg")
    if not mediamtx.exists() or not ffmpeg:
        print("PULADA: sem mediamtx/ffmpeg no repositorio (tools/) — este teste precisa dos dois")
        return 0

    conf = tmp / "mediamtx.yml"
    # rtspTransports: [tcp] e' obrigatorio: o modo UDP abre :8000/:8001 (RTP/RTCP) e, com qualquer
    # coisa nessas portas, o mediamtx RECUSA subir (ja' quebrou o suite duas vezes por isso).
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
    pub = proc = log = None

    def exigir(cond, texto):
        print(("OK   " if cond else "FALHA ") + texto)
        if not cond:
            falhas.append(texto)

    try:
        if not esperar(f"http://127.0.0.1:{porta_mtx_api}/v3/paths/list"):
            print("FALHA o mediamtx de teste nao subiu; log em", tmp / "mediamtx.log")
            print("  motivo no log:", (tmp / "mediamtx.log").read_text(errors="replace")[-300:].strip())
            return 1
        pub = subprocess.Popen([
            str(ffmpeg), "-hide_banner", "-loglevel", "warning", "-re",
            "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-profile:v", "high",
            "-bf", "0", "-b:v", f"{KBPS_SAIDA}k", "-maxrate", f"{KBPS_SAIDA}k", "-bufsize", "1M",
            "-g", "30", "-pix_fmt", "yuv420p",
            "-f", "rtsp", "-rtsp_transport", "tcp", f"rtsp://127.0.0.1:{porta_rtsp}/{FLUXO}",
        ], cwd=str(tmp), stdout=log_pub, stderr=subprocess.STDOUT)

        env = dict(os.environ)
        env["LECSOR_BANCO"] = str(banco)
        env["LECSOR_BIND"] = "0.0.0.0"     # o cliente remoto (IP da rede) tambem e' exercitado
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
        if not esperar(base + "/api/saude", tentativas=60):
            print("FALHA a API do lado terra nao subiu; log em", tmp / "api.log")
            return 1

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
            print("FALHA o fluxo de teste nao ficou no ar; log em", tmp / "publicador.log")
            return 1

        admin = Sessao(base)
        s, j = admin.pedir("/api/entrar", {"email": "admin@lecsor.test", "senha": SENHA})
        exigir(s == 200 and j.get("ok"), "admin autenticou (http %s)" % s)
        # a camera entra pelo caminho do BORDO (anuncio autenticado), como no produto
        s, j = admin.pedir("/api/cameras/anuncio", {"id": FLUXO, "fluxo_id": FLUXO, "rotulo": "CAM declarada",
                                                   "embarcacao_id": "bancada", "ativo": 1}, token=TOKEN)
        exigir(s == 201, "a camera do fluxo foi anunciada pelo caminho do bordo (http %s)" % s)

        # ------------------------------------------------------------------ 1) tentativa RECUSADA
        s, j = admin.pedir("/api/envios/anuncio", {"fluxo_id": FLUXO, "bitrate_saida_kbps": KBPS_SAIDA},
                           token="token-errado")
        exigir(s == 401, "declaracao sem o token de ingestao e' recusada (http %s)" % s)
        s, j = admin.pedir("/api/declarado")
        sem = j.get("sem_declaracao") or []
        t = next((x.get("ultima_tentativa") or {} for x in sem if x.get("fluxo_id") == FLUXO), {})
        exigir(j.get("declarado") == [], "o lado terra ainda NAO tem declaracao nenhuma (%r)" % j.get("declarado"))
        exigir(bool(t) and t.get("aceito") == 0 and "token" in (t.get("motivo") or ""),
               "a tentativa recusada ficou registrada com o motivo: %r" % t)
        s, cab0, _ = admin.baixar(f"/api/fluxos/{FLUXO}/trecho?segundos={SEGUNDOS}")
        id0 = int(cab0.get("X-Lecsor-Trecho-Id") or 0)
        s, at0 = admin.pedir(f"/api/trechos/{id0}/atestado")
        dec0 = at0.get("declarado_pelo_pc_de_captura") or {}
        exigir("RECUSADO" in (dec0.get("origem") or ""),
               "o atestado diz que o bordo tentou e foi RECUSADO, em vez de 'nada': %r" % (dec0.get("origem") or "")[:90])
        exigir("nao ha com o que comparar" in (at0.get("leitura") or ""),
               "sem declaracao o atestado nao inventa comparacao")

        # ------------------------------------------------------------------ 2) declaracao de verdade
        carimbo = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        declaracao = {"fluxo_id": FLUXO, "camera_id": FLUXO, "rotulo": "CAM declarada", "tipo": "camera",
                      "codec": "libx264", "resolucao": "1280x720", "fps": 30, "bitrate_alvo": f"{KBPS_SAIDA}k",
                      "bitrate_entrada_kbps": KBPS_ENTRADA, "bitrate_saida_kbps": KBPS_SAIDA,
                      "corte_pct": CORTE_PCT, "velocidade": 1.0, "tamanho_mb": 12.0, "duracao_s": 60,
                      "estado": "no_ar", "fonte": "dshow:cam-01", "carimbo": carimbo, "motivo": "no ar"}
        s, j = admin.pedir("/api/envios/anuncio", declaracao, token=TOKEN)
        exigir(s == 201 and j.get("ok"), "o bordo declarou o envio com o token (http %s)" % s)
        exigir(j.get("bitrate_saida_kbps") == KBPS_SAIDA and j.get("bitrate_entrada_kbps") == KBPS_ENTRADA,
               "a resposta confirma os numeros gravados (%r)" % {k: j.get(k) for k in ("bitrate_saida_kbps", "bitrate_entrada_kbps")})

        s, j = admin.pedir("/api/declarado")
        d = next((x for x in (j.get("declarado") or []) if x.get("fluxo_id") == FLUXO), None)
        exigir(bool(d), "GET /api/declarado mostra a declaracao do fluxo (%r)" % (j.get("declarado") or [])[:1])
        if d:
            exigir(d.get("bitrate_entrada_kbps") == KBPS_ENTRADA and d.get("bitrate_saida_kbps") == KBPS_SAIDA
                   and abs(float(d.get("corte_pct") or 0) - CORTE_PCT) < 0.01,
                   "declarado com entrada/saida/corte (%s/%s/%s)" % (d.get("bitrate_entrada_kbps"),
                                                                     d.get("bitrate_saida_kbps"), d.get("corte_pct")))
            exigir(d.get("declarado_em") and d.get("recebido_em") and d.get("idade_s") is not None,
                   "declarado_em/recebido_em/idade_s presentes (%s / %s / %s)" % (d.get("declarado_em"),
                                                                                  d.get("recebido_em"), d.get("idade_s")))
            exigir((d.get("qualidade") or {}) == {} or (d.get("qualidade") or {}).get("ssim") is None,
                   "sem medicao de qualidade ainda, o campo nao vem inventado (%r)" % d.get("qualidade"))
            exigir(not (d.get("sem_declaracao")), "o fluxo declarado nao aparece como 'sem declaracao'")

        # a medicao de qualidade (SSIM) tambem sobe — e' o outro lado do comparativo
        mb_alvo = round(KBPS_SAIDA * 1000 / 8 * 60 / 1e6, 2)
        mb_original = round(KBPS_ENTRADA * 1000 / 8 * 60 / 1e6, 2)
        s, _ = admin.pedir("/api/qualidade/anuncio",
                           {"fluxo_id": FLUXO, "ssim": 0.9812, "ajuste": f"{KBPS_SAIDA}k",
                            "resolucao": "1280x720", "fps": 30, "segundos": 60, "mb_alvo": mb_alvo,
                            "mb_original": mb_original, "compressao_pct": CORTE_PCT}, token=TOKEN)
        exigir(s == 201, "o bordo anunciou a medicao de qualidade (http %s)" % s)

        # ------------------------------------------------------------------ 3) o atestado com os DOIS lados
        s, cab1, corpo1 = admin.baixar(f"/api/fluxos/{FLUXO}/trecho?segundos={SEGUNDOS}")
        exigir(s == 200 and corpo1[4:8] == b"ftyp", "o trecho veio como MP4 (http %s)" % s)
        id1 = int(cab1.get("X-Lecsor-Trecho-Id") or 0)
        s, at1 = admin.pedir(f"/api/trechos/{id1}/atestado")
        dec = at1.get("declarado_pelo_pc_de_captura") or {}
        con = at1.get("contas") or {}
        med = at1.get("medido_no_arquivo") or {}
        exigir(dec.get("kbps_saida") == KBPS_SAIDA and dec.get("kbps_entrada") == KBPS_ENTRADA,
               "o atestado traz o kbps declarado pelo bordo (%s x %s)" % (dec.get("kbps_saida"), dec.get("kbps_entrada")))
        exigir(dec.get("declarado_em") == carimbo, "o atestado traz QUANDO o bordo declarou (%r)" % dec.get("declarado_em"))
        exigir("declaracao do PC de captura recebida aqui" in (dec.get("origem") or ""),
               "o atestado diz de onde veio o declarado: %r" % (dec.get("origem") or "")[:90])
        exigir(con.get("bate") is True,
               "medido no arquivo x declarado BATEM (%s kbps x %s kbps, dif %s%%)"
               % (med.get("kbps"), dec.get("kbps_saida"), con.get("diferenca_pct")))
        exigir(con.get("compressao_pct_calculada") is not None
               and abs(float(con["compressao_pct_calculada"]) - CORTE_PCT) <= 2.0,
               "a compressao foi recalculada com o kbps de ENTRADA declarado: %s%%" % con.get("compressao_pct_calculada"))
        exigir(con.get("bate_compressao") is True, "a compressao informada confere com a recalculada")
        exigir(dec.get("ssim") is not None and dec.get("medido_em"),
               "o SSIM declarado aparece com a hora da medicao (%s em %s)" % (dec.get("ssim"), dec.get("medido_em")))
        exigir("dentro da tolerancia" in (at1.get("leitura") or ""),
               "a leitura em texto fecha o comparativo: %r" % (at1.get("leitura") or "")[:110])
        exigir("declarado_por" not in dec and "\"ip\"" not in json.dumps(at1),
               "o comprovante do cliente NAO leva quem declarou (IP) nem o campo ip")

        # ------------------------------------------------------------------ 4) bordo mentindo: contesta
        s, _ = admin.pedir("/api/envios/anuncio", {**declaracao, "bitrate_saida_kbps": 3000,
                                                   "corte_pct": 50.0, "carimbo": carimbo}, token=TOKEN)
        exigir(s == 201, "o bordo declarou outro kbps (http %s)" % s)
        s, cab2, _ = admin.baixar(f"/api/fluxos/{FLUXO}/trecho?segundos={SEGUNDOS}")
        id2 = int(cab2.get("X-Lecsor-Trecho-Id") or 0)
        s, at2 = admin.pedir(f"/api/trechos/{id2}/atestado")
        con2 = at2.get("contas") or {}
        exigir(con2.get("bate") is False,
               "declarando 3000k e chegando ~%dk o atestado diz que NAO bate (bate=%r)" % (KBPS_SAIDA, con2.get("bate")))
        exigir("FORA da tolerancia" in (at2.get("leitura") or ""),
               "e avisa em texto: %r" % (at2.get("leitura") or "")[:110])

        # ------------------------------------------------------------------ 5) o cache nao engole
        ok, detalhe = checar_publicacao_no_cache(banco)
        exigir(ok, "medicao reaproveitada tambem e' publicada no lado terra (%s)" % detalhe)

        # ------------------------------------------------------------------ 6) o que NAO pode passar
        cliente = Sessao(base)
        s, j = cliente.pedir("/api/entrar", {"email": "cliente@lecsor.test", "senha": SENHA})
        exigir(s == 200, "cliente autenticou (http %s)" % s)
        s, _ = cliente.pedir("/api/declarado")
        exigir(s == 403, "o cliente NAO ve o quadro do que o bordo declara (http %s)" % s)
        s, _ = cliente.pedir("/api/envios/anuncio", declaracao)
        exigir(s == 401, "sessao de navegador NAO declara envio sem o token de ingestao (http %s)" % s)
        s, _ = admin.pedir("/api/envios/anuncio", {"bitrate_saida_kbps": 1500}, token=TOKEN)
        exigir(s == 422, "declaracao sem fluxo_id -> 422 (http %s)" % s)
        s, _ = admin.pedir("/api/envios/anuncio", {"fluxo_id": "nao-existe-mesmo",
                                                   "bitrate_saida_kbps": 1500}, token=TOKEN)
        exigir(s == 201, "fluxo desconhecido tambem pode se declarar (o lado terra so' registra) (http %s)" % s)

        # ------------------------------------------------------------------ 7) no banco, o que ficou
        con = sqlite3.connect(banco)
        con.row_factory = sqlite3.Row
        cols_env = [r[1] for r in con.execute("PRAGMA table_info(ingestoes)")]
        cols_an = [r[1] for r in con.execute("PRAGMA table_info(anuncios_recebidos)")]
        linha = con.execute("""SELECT * FROM ingestoes WHERE fluxo_id=?""", (FLUXO,)).fetchone()
        aceitas = con.execute("SELECT COUNT(*) FROM anuncios_recebidos WHERE aceito=1").fetchone()[0]
        recusadas = con.execute("SELECT COUNT(*) FROM anuncios_recebidos WHERE aceito=0").fetchone()[0]
        con.close()
        exigir(all(c in cols_env for c in ("declarado_em", "declarado_por", "recebido_em")),
               "ingestoes do lado terra ganhou as colunas da declaracao (%s)" % cols_env)
        exigir(linha is not None and linha["bitrate_saida_kbps"] == 3000,
               "a ultima declaracao do fluxo ficou gravada no lado terra (%s)"
               % (dict(linha)["bitrate_saida_kbps"] if linha else None))
        exigir(all(c in cols_an for c in ("em", "rota", "fluxo_id", "aceito", "motivo", "ip")),
               "anuncios_recebidos guarda a tentativa, o motivo e o ip (%s)" % cols_an)
        exigir(aceitas >= 3 and recusadas >= 1,
               "tentativas registradas: %d aceitas e %d recusadas" % (aceitas, recusadas))
        exigir(not [x for x in cols_env if "senha" in x or "usuario" in x],
               "nada de credencial nas colunas da declaracao (%s)" % cols_env)
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
    print("PASSOU: o declarado do PC de captura chega ao lado terra e fecha o comparativo com o medido")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
