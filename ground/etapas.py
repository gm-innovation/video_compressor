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
              nome: str | None = None, audio: bool = False) -> dict:
    """Etapa 1 — compressao. Codifica o arquivo INTEIRO de uma vez e mede tamanho e qualidade."""
    from ingestao import alvo_automatico, resolver_link
    COMPRIMIDOS.mkdir(parents=True, exist_ok=True)
    fonte2 = None
    origem = fonte
    if not str(fonte).startswith(("file:", "C:", "/")) and str(fonte).startswith("http"):
        direto, fonte2, _t = resolver_link(fonte)
        fonte = direto
    ent = info(fonte)
    bitrate = alvo_automatico(ent.get("bitrate_kbps")) if (not alvo or alvo == "auto") else alvo
    kb = _kbps(bitrate)
    base = re.sub(r"[^a-zA-Z0-9]+", "-", (nome or Path(str(origem)).stem or "comprimido")).strip("-")
    saida = COMPRIMIDOS / f"{base}-{kb}k-{fps}fps.mp4"
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning", "-y", "-i", fonte]
    if fonte2 and audio:
        cmd += ["-i", fonte2, "-map", "0:v:0", "-map", "1:a:0?"]
    cmd += ["-c:v", codec, "-preset", "ultrafast", "-tune", "zerolatency",
            "-b:v", f"{kb}k", "-maxrate", f"{kb}k", "-bufsize", "1M",
            "-r", str(fps), "-g", str(fps), "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-b:a", "48k", "-ac", "1"] if audio else ["-an"]
    cmd += ["-movflags", "+faststart", str(saida)]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    segundos = round(time.time() - t0, 2)
    if r.returncode != 0 or not saida.exists():
        return {"etapa": "compressao", "ok": False, "erro": (r.stderr or "ffmpeg falhou")[-400:]}

    comp = info(str(saida))
    bo, bc = ent.get("bytes"), comp.get("bytes")
    corte = round((1 - bc / bo) * 100, 2) if bo and bc else None
    ssim = medir_ssim(fonte, str(saida), ent.get("duracao_s"))
    dur = comp.get("duracao_s") or ent.get("duracao_s") or 0
    return {"etapa": "compressao", "ok": True, "arquivo": str(saida), "nome_arquivo": saida.name,
            "alvo": f"{kb}k", "fps": fps, "codec": codec,
            "entrada": {"bytes": bo, "mb": round(bo / 1e6, 2) if bo else None, "bitrate_kbps": ent.get("bitrate_kbps"),
                        "resolucao": ent.get("resolucao"), "fps": ent.get("fps"), "duracao_s": ent.get("duracao_s")},
            "comprimido": {"bytes": bc, "mb": round(bc / 1e6, 2) if bc else None, "bitrate_kbps": comp.get("bitrate_kbps"),
                           "resolucao": comp.get("resolucao"), "fps": comp.get("fps")},
            "corte_pct": corte, "tempo_encode_s": segundos,
            "velocidade_x": round(dur / segundos, 2) if segundos and dur else None,
            "ssim": ssim}


def medir_ssim(original: str, comprimido: str, duracao_s: float | None) -> float | None:
    """Qualidade: SSIM medio do comprimido contra o original (1.0 = identico)."""
    recorte = ["-t", str(min(60, max(5, int(duracao_s or 30))))]
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info",
                        "-i", comprimido, "-i", original, *recorte,
                        "-lavfi", f"[0:v]scale={640}:-2,setpts=PTS-STARTPTS[a];[1:v]scale={640}:-2,setpts=PTS-STARTPTS[b];[a][b]ssim",
                        "-f", "null", "-"], capture_output=True, text=True, timeout=900)
    m = re.findall(r"All:([0-9.]+)", r.stderr or "")
    return round(float(m[-1]), 4) if m else None


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
