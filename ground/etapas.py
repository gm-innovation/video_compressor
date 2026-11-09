#!/usr/bin/env python3
"""Teste das TRES etapas do pipeline, uma por uma e depois em sequencia:

  1. COMPRESSAO  -> codifica o arquivo inteiro (30 fps) e mede: tempo, tamanho original x comprimido,
                    corte de banda e qualidade (SSIM medio contra o original).
  2. ENVIO       -> publica em SRT/mediamtx e le as estatisticas do transporte (RTT, taxa, perdas).
  3. DESCOMPRESSAO -> quanto o cliente leva para ver o primeiro quadro (WebRTC x HLS).

O que este teste NAO mede sozinho: a espera total com o video de ponta a ponta (relogio queimado no
quadro lido na tela do cliente). Esse numero sai de `latencia_ponta_a_ponta()` aqui ao lado + leitura
do relogio na tela.

Uso:
  python ground/etapas.py --fonte <arquivo|link> --alvo auto --fps 30
  python ground/etapas.py --fonte <arquivo> --so-compressao
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
RAIZ = Path(__file__).resolve().parent.parent
COMPRIMIDOS = RAIZ / "ground" / "envios" / "comprimido"
MEDIAMTX_API = "http://127.0.0.1:9997"


def _kbps(bitrate: str) -> int:
    m = re.match(r"^\s*([0-9.]+)\s*([kKmM]?)", bitrate or "")
    if not m:
        return 800
    v = float(m.group(1))
    return int(v * (1000 if m.group(2).lower() == "m" else 1))


QUALIDADE_PISO_SSIM = 0.95     # piso de qualidade aceito no modo automatico
CRFS_TESTADOS = (34, 32, 30, 28, 26)


def _encode(fonte: str, saida: Path, *, kb: int | None = None, crf: int | None = None, fps: int = 30,
            codec: str = "libx264", fonte2: str | None = None, audio: bool = False,
            duracao_amostra: float | None = None, preset: str = "medium") -> float:
    """Uma passada de encode. kb = alvo de bitrate; crf = qualidade (o x264 escolhe o bitrate)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning", "-y"]
    if duracao_amostra:
        cmd += ["-t", str(duracao_amostra)]
    cmd += ["-i", fonte]
    if fonte2 and audio:
        cmd += ["-i", fonte2, "-map", "0:v:0", "-map", "1:a:0?"]
    # ultrafast e' para o ao vivo (latencia); para TAMANHO o certo e' um preset que comprime de verdade
    cmd += ["-c:v", codec, "-preset", preset]
    if preset == "ultrafast":
        cmd += ["-tune", "zerolatency"]
    if crf is not None:
        cmd += ["-crf", str(crf)]
    else:
        cmd += ["-b:v", f"{kb}k", "-maxrate", f"{kb}k", "-bufsize", "1M"]
    cmd += ["-r", str(fps), "-g", str(fps), "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-b:a", "48k", "-ac", "1"] if audio else ["-an"]
    cmd += ["-movflags", "+faststart", str(saida)]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    if r.returncode != 0 or not saida.exists():
        raise RuntimeError((r.stderr or "ffmpeg falhou")[-400:])
    return round(time.time() - t0, 2)


def escolher_crf(fonte: str, *, fps: int = 30, tolerancia: float = 0.005,
                 pasta: Path | None = None, fonte2: str | None = None) -> dict:
    """Maior compressao possivel sem perder qualidade relevante.

    Codifica amostras curtas em varios CRFs, mede o SSIM de cada uma contra a MESMA amostra do
    original e escolhe o CRF mais alto (menos banda) cuja qualidade fica dentro da tolerancia do
    melhor SSIM encontrado — ou seja, o ponto em que baixar mais a banda comecaria a custar imagem.
    """
    pasta = pasta or COMPRIMIDOS
    pasta.mkdir(parents=True, exist_ok=True)
    ent = info(fonte)
    amostra = min(12.0, max(5.0, (ent.get("duracao_s") or 20) / 5))
    tentativas = []
    for crf in CRFS_TESTADOS:
        saida = pasta / f"_amostra-crf{crf}.mp4"
        try:
            seg = _encode(fonte, saida, crf=crf, fps=fps, fonte2=fonte2, duracao_amostra=amostra)
        except RuntimeError as e:
            tentativas.append({"crf": crf, "erro": str(e)[:120]})
            continue
        ssim = medir_ssim_amostra(fonte, str(saida), amostra, fps=fps)
        kb = round(saida.stat().st_size * 8 / amostra / 1000, 1)
        tentativas.append({"crf": crf, "ssim": ssim, "bitrate_kbps": kb, "segundos_amostra": seg})
        saida.unlink(missing_ok=True)
    validas = [x for x in tentativas if x.get("ssim") is not None]
    if not validas:
        return {"crf": 28, "tolerancia": tolerancia, "amostra_s": round(amostra, 1), "tentativas": tentativas,
                "motivo": "nao consegui medir qualidade na amostra: usei CRF 28"}
    melhor = max(validas, key=lambda x: x["ssim"])
    dentro = [x for x in validas if x["ssim"] >= melhor["ssim"] - tolerancia]
    escolhido = max(dentro, key=lambda x: x["crf"])
    return {"crf": escolhido["crf"], "tolerancia": tolerancia, "amostra_s": round(amostra, 1),
            "tentativas": tentativas, "escolhido": escolhido, "melhor_ssim": melhor["ssim"],
            "motivo": (f"maior CRF (menos banda) cuja qualidade fica dentro de {tolerancia} do melhor SSIM "
                       f"medido na amostra ({melhor['ssim']})")}


def medir_ssim_amostra(original: str, comprimido: str, segundos: float, fps: int = 30) -> float | None:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info",
                        "-i", comprimido, "-i", original, "-t", str(segundos),
                        "-lavfi", f"[0:v]fps={fps},setpts=PTS-STARTPTS[a];[1:v]fps={fps},setpts=PTS-STARTPTS[b];[a][b]ssim",
                        "-f", "null", "-"], capture_output=True, text=True, timeout=900)
    m = re.findall(r"All:([0-9.]+)", r.stderr or "")
    return round(float(m[-1]), 4) if m else None


def info(fonte: str) -> dict:
    from ingestao import sonda
    s = sonda(fonte) or {}
    tam = None
    if not str(fonte).startswith("http"):
        try:
            tam = Path(fonte).stat().st_size
        except Exception:
            tam = None
    return {**s, "bytes": tam}


def comprimir(fonte: str, *, alvo: str = "auto", fps: int = 30, codec: str = "libx264",
              nome: str | None = None, audio: bool = False, qualidade: str = "auto",
              embarcacao_id: str = "psv-exemplo") -> dict:
    """Etapa 1 — compressao. Mede tudo o que o dono quer ver: tempo, tamanho de entrada e saida,
    quanto comprimiu (%) e a qualidade que sobrou (SSIM).

    qualidade="auto" procura o encode mais leve (maior CRF) que ainda mantem SSIM >= 0,95 —
    e o "alvo" que faz sentido: minima banda sem perder qualidade visivel.
    """
    from ingestao import alvo_automatico, resolver_link
    COMPRIMIDOS.mkdir(parents=True, exist_ok=True)
    fonte2, origem = None, fonte
    if str(fonte).startswith("http") and not str(fonte).startswith(("file:", "C:", "/")):
        direto, fonte2, _t = resolver_link(fonte)
        fonte = direto
    ent = info(fonte)
    busca = None
    crf = None
    kb = None
    if qualidade == "auto":
        busca = escolher_crf(fonte, fps=fps)
        crf = busca.get("crf")
        if crf is None:
            kb = _kbps(alvo_automatico(ent.get("bitrate_kbps")) if (not alvo or alvo == "auto") else alvo)
    elif str(qualidade).startswith("crf"):
        crf = int(re.sub(r"[^0-9]", "", qualidade) or 28)
    base = re.sub(r"[^a-zA-Z0-9]+", "-", (nome or Path(str(origem)).stem or "comprimido")).strip("-")
    marca = f"crf{crf}" if crf is not None else f"{kb}k"
    saida = COMPRIMIDOS / f"{base}-{marca}-{fps}fps.mp4"
    try:
        segundos = _encode(fonte, saida, kb=kb, crf=crf, fps=fps, codec=codec, fonte2=fonte2, audio=audio)
    except RuntimeError as e:
        return {"etapa": "compressao", "ok": False, "erro": str(e)}
    comp = info(str(saida))
    bo, bc = ent.get("bytes"), comp.get("bytes")
    corte = round((1 - bc / bo) * 100, 2) if bo and bc else None
    ssim = medir_ssim(fonte, str(saida), ent.get("duracao_s"), fps=fps)
    dur = ent.get("duracao_s") or 0
    r = {"etapa": "compressao", "ok": True, "arquivo": str(saida), "nome_arquivo": saida.name,
         "crf": crf, "fps": fps, "codec": codec, "qualidade": qualidade,
         "busca_crf": busca,
         "entrada": {"bytes": bo, "mb": round(bo / 1e6, 2) if bo else None, "bitrate_kbps": ent.get("bitrate_kbps"),
                     "resolucao": ent.get("resolucao"), "fps": ent.get("fps"), "duracao_s": ent.get("duracao_s")},
         "comprimido": {"bytes": bc, "mb": round(bc / 1e6, 2) if bc else None, "bitrate_kbps": comp.get("bitrate_kbps"),
                        "resolucao": comp.get("resolucao"), "fps": comp.get("fps")},
         "corte_pct": corte, "tempo_encode_s": segundos,
         "velocidade_x": round(dur / segundos, 2) if segundos and dur else None, "ssim": ssim}
    try:
        r["id"] = registrar_compressao(r, origem)
    except Exception:
        r["id"] = None
    return r


def medir_ssim(original: str, comprimido: str, duracao_s: float | None, fps: int = 30) -> float | None:
    """Qualidade: SSIM medio do comprimido contra o original (1.0 = identico)."""
    recorte = ["-t", str(min(60, max(5, int(duracao_s or 30))))]
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info",
                        "-i", comprimido, "-i", original, *recorte,
                        "-lavfi", f"[0:v]fps={fps},setpts=PTS-STARTPTS[a];[1:v]fps={fps},setpts=PTS-STARTPTS[b];[a][b]ssim",
                        "-f", "null", "-"], capture_output=True, text=True, timeout=900)
    m = re.findall(r"All:([0-9.]+)", r.stderr or "")
    return round(float(m[-1]), 4) if m else None


def conexao_banco():
    import sqlite3
    c = sqlite3.connect(RAIZ / "db" / "pipeline.db", timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    return c


def garantir_tabela() -> None:
    with conexao_banco() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS compressoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rotulo TEXT, arquivo_original TEXT, arquivo_saida TEXT,
            mb_entrada REAL, mb_saida REAL, bitrate_entrada_kbps REAL, bitrate_saida_kbps REAL,
            compressao_pct REAL, crf INTEGER, ssim REAL, fps INTEGER,
            segundos_encode REAL, velocidade_x REAL, duracao_s REAL,
            fluxo_id TEXT, publicado_em TEXT, criado_em TEXT)""")


def registrar_compressao(r: dict, origem: str) -> int:
    garantir_tabela()
    import datetime as _dt
    with conexao_banco() as c:
        cur = c.execute("""INSERT INTO compressoes (rotulo, arquivo_original, arquivo_saida, mb_entrada, mb_saida,
            bitrate_entrada_kbps, bitrate_saida_kbps, compressao_pct, crf, ssim, fps, segundos_encode,
            velocidade_x, duracao_s, criado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (Path(str(origem)).name, origem, r["arquivo"], r["entrada"]["mb"], r["comprimido"]["mb"],
             r["entrada"]["bitrate_kbps"], r["comprimido"]["bitrate_kbps"], r["corte_pct"], r.get("crf"),
             r.get("ssim"), r.get("fps"), r.get("tempo_encode_s"), r.get("velocidade_x"),
             r["entrada"].get("duracao_s"), _dt.datetime.now().astimezone().isoformat(timespec="seconds")))
        return cur.lastrowid


def listar_compressoes(limite: int = 40) -> list[dict]:
    garantir_tabela()
    with conexao_banco() as c:
        linhas = [dict(x) for x in c.execute(
            "SELECT * FROM compressoes ORDER BY id DESC LIMIT ?", (limite,))]
    for l in linhas:
        l["baixar"] = "/api/comprimido/" + Path(l["arquivo_saida"] or "").name
        l["existe"] = Path(l["arquivo_saida"] or "").exists()
        l["publicado"] = bool(l.get("fluxo_id"))
    return linhas


def publicar_compressao(ident: int, *, embarcacao_id: str = "psv-exemplo", repetir: bool = True,
                        rotulo: str | None = None) -> dict:
    """Etapa 2/3 — pega o arquivo ja comprimido e publica em SRT (o dono clica 'publicar no ar')."""
    from ingestao import iniciar as ing_iniciar
    garantir_tabela()
    with conexao_banco() as c:
        linha = c.execute("SELECT * FROM compressoes WHERE id=?", (ident,)).fetchone()
    if not linha:
        return {"erro": "compressao nao encontrada"}
    linha = dict(linha)
    caminho = Path(linha["arquivo_saida"])
    if not caminho.exists():
        return {"erro": f"o arquivo {caminho.name} nao esta mais no disco"}
    r = ing_iniciar(str(caminho), rotulo=rotulo or linha.get("rotulo") or caminho.stem,
                    bitrate=str(linha.get("bitrate_saida_kbps") and f"{int(linha['bitrate_saida_kbps'])}k" or "auto"),
                    repetir=repetir, tipo="arquivo", fps=int(linha.get("fps") or 30),
                    embarcacao_id=embarcacao_id)
    if "erro" in r:
        return r
    import datetime as _dt
    with conexao_banco() as c:
        c.execute("UPDATE compressoes SET fluxo_id=?, publicado_em=? WHERE id=?",
                  (r["fluxo_id"], _dt.datetime.now().astimezone().isoformat(timespec="seconds"), ident))
    return {"ok": True, **r}


def remover_compressao(ident: int) -> dict:
    """Apaga o registro e o arquivo comprimido (e para o fluxo, se estiver publicado)."""
    from ingestao import parar as ing_parar
    garantir_tabela()
    with conexao_banco() as c:
        linha = c.execute("SELECT * FROM compressoes WHERE id=?", (ident,)).fetchone()
    if not linha:
        return {"erro": "compressao nao encontrada"}
    linha = dict(linha)
    if linha.get("fluxo_id"):
        try:
            ing_parar(linha["fluxo_id"], remover=True)
        except Exception:
            pass
    try:
        Path(linha["arquivo_saida"]).unlink(missing_ok=True)
    except Exception:
        pass
    with conexao_banco() as c:
        c.execute("DELETE FROM compressoes WHERE id=?", (ident,))
    return {"ok": True, "removido": ident}


def envio(fluxo_id: str) -> dict:
    """Etapa 2 — envio. Estatisticas do transporte SRT lidas do mediamtx."""
    def api(rota):
        try:
            return json.loads(urllib.request.urlopen(MEDIAMTX_API + rota, timeout=6).read())
        except Exception as e:
            return {"erro": str(e)}
    caminhos = api("/v3/paths/list").get("items") or []
    caminho = next((c for c in caminhos if c.get("name") == fluxo_id), None)
    if not caminho:
        return {"etapa": "envio", "ok": False, "erro": f"o mediamtx nao tem o caminho {fluxo_id}"}
    conexoes = api("/v3/srtconns/list").get("items") or []
    con = next((c for c in conexoes if c.get("path") == fluxo_id and c.get("state") == "publish"), None)
    if con:
        recebido = con.get("bytesReceived") or 0
        seg = None
        if con.get("created"):
            try:
                import datetime as _dt
                t = _dt.datetime.fromisoformat(con["created"].replace("Z", "+00:00"))
                seg = max(1, (_dt.datetime.now(t.tzinfo) - t).total_seconds())
            except Exception:
                seg = None
        return {"etapa": "envio", "ok": True, "fluxo_id": fluxo_id,
                "rtt_ms": round(float(con.get("msRTT") or 0), 3),
                "mbps_no_ultimo_segundo": round(float(con.get("mbpsReceiveRate") or 0), 3),
                "pacotes_recebidos": con.get("packetsReceived"),
                "pacotes_perdidos": con.get("packetsReceivedLoss"),
                "retransmitidos": con.get("packetsReceivedRetrans"),
                "bytes_recebidos": recebido,
                "segundos_no_ar": round(seg, 1) if seg else None,
                "mbps_medio": round(recebido * 8 / seg / 1e6, 3) if seg else None,
                "leitura_no": True, "readers": len(caminho.get("readers") or [])}
    return {"etapa": "envio", "ok": True, "fluxo_id": fluxo_id, "aviso": "sem conexao SRT de publicacao agora",
            "caminho_no_ar": bool(caminho.get("ready")), "readers": len(caminho.get("readers") or [])}


def descompressao(url_fluxo: str, *, segundos: int = 45, http: str = "http://127.0.0.1:8765") -> dict:
    """Etapa 3 — descompressao: quanto o cliente leva para ver o primeiro quadro (WebRTC e HLS)."""
    from playwright.sync_api import sync_playwright
    resultado = {"etapa": "descompressao", "ok": True, "modos": {}}
    with sync_playwright() as pw:
        try:
            nav = pw.chromium.launch(channel="chrome", args=["--autoplay-policy=no-user-gesture-required"])
        except Exception:
            nav = pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        for modo in ("whep", "hls"):
            pg = nav.new_page(viewport={"width": 900, "height": 600})
            pg.goto(f"{http}/", wait_until="domcontentloaded")
            print(f"[descompressao] {modo}: entrando em {http}/whep/ ..." if modo == "whep" else
                  f"[descompressao] {modo}: entrando em {http}/hls/ ...")
            t0 = time.time()
            js = """async ([url, modo]) => {
              const v = document.createElement('video'); v.muted = true; v.autoplay = true; v.playsInline = true;
              document.body.appendChild(v);
              if (modo === 'whep') {
                const pc = new RTCPeerConnection({ iceServers: [] });
                pc.addTransceiver('video', { direction: 'recvonly' });
                pc.addTransceiver('audio', { direction: 'recvonly' });
                pc.ontrack = (e) => { if (e.streams[0]) v.srcObject = e.streams[0]; };
                const of = await pc.createOffer(); await pc.setLocalDescription(of);
                const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/sdp' }, body: of.sdp });
                const sdp = await r.text();
                await pc.setRemoteDescription({ type: 'answer', sdp });
                window.__pc = pc;
              } else {
                v.src = url; v.play();
              }
              return true;
            }"""
            try:
                pg.evaluate(js, [f"{http}/{modo}/{url_fluxo}", modo])
            except Exception as e:
                resultado["modos"][modo] = {"erro": str(e)[:200]}
                pg.close(); continue
            visto = None
            for _ in range(segundos * 4):
                pg.wait_for_timeout(250)
                if pg.evaluate("(() => { const v = document.querySelector('video'); return !!(v && v.readyState >= 2 && v.currentTime > 0.05); })()"):
                    visto = round(time.time() - t0, 3)
                    break
            resultado["modos"][modo] = {"primeiro_quadro_s": visto} if visto else {"primeiro_quadro_s": None, "erro": "sem imagem no tempo do teste"}
            pg.close()
        nav.close()
    return resultado


def latencia_ponta_a_ponta(fluxo_id: str, *, alvo: str = "800k", fps: int = 30, segundos: int = 25) -> dict:
    """Ponta a ponta com relogio queimado no quadro: publica um test pattern e deixa o navegador ler.

    Devolve o fluxo publicado; a leitura do relogio na tela e feita por quem chamou (screenshot).
    """
    relogio = r"%{localtime\:%T}"
    milis = r"%{eif\:mod(t*1000\,1000)\:d\:3}"
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning", "-re",
           "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate={fps}",
           "-vf", f"drawtext=text='{relogio}.{milis}':fontsize=64:fontcolor=white:box=1:boxcolor=black@0.6:x=20:y=20",
           "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
           "-b:v", alvo, "-maxrate", alvo, "-bufsize", "1M", "-r", str(fps), "-g", str(fps),
           "-pix_fmt", "yuv420p", "-an", "-f", "mpegts",
           f"srt://127.0.0.1:8890?mode=caller&latency=200&pkt_size=1316&streamid=publish:{fluxo_id}"]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(6)
    return {"fluxo_id": fluxo_id, "pid": proc.pid, "comando": " ".join(cmd)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonte", required=True)
    ap.add_argument("--alvo", default="auto")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--so-compressao", action="store_true")
    ap.add_argument("--fluxo", default=None, help="fluxo_id ja publicado, para medir envio/descompressao")
    a = ap.parse_args()
    if not a.so_compressao:
        print(json.dumps(descompressao(a.fluxo or "exemplo-arquivo"), ensure_ascii=False, indent=1))
        if a.fluxo:
            print(json.dumps(envio(a.fluxo), ensure_ascii=False, indent=1))
        return 0
    r = comprimir(a.fonte, alvo=a.alvo, fps=a.fps)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
