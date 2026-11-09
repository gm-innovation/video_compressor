#!/usr/bin/env python3
"""Ingestao de video de teste: recebe um ARQUIVO enviado ou um LINK e faz o mesmo
caminho do produto — codifica (libx264/hevc), empacota em MPEG-TS e publica em SRT
no mediamtx, medindo bitrate de entrada x saida (corte) e fps.

Serve para o dono testar compressao e streaming antes das imagens reais das embarcacoes.
Nenhuma credencial de camera entra aqui: a fonte e arquivo local ou link publico.
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, re, shutil, signal, sqlite3, subprocess, sys, threading, time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "db" / "pipeline.db"
ENVIOS = RAIZ / "ground" / "envios"
LOG_DIR = RAIZ / "ground" / "envios" / "log"

def agora() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")

def conexao():
    c = sqlite3.connect(BANCO, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")     # leitura e escrita ao mesmo tempo, sem travar a API
        c.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    return c

def garantir_schema():
    sql = (RAIZ / "db" / "schema-ingestao.sql").read_text(encoding="utf-8")
    with conexao() as c:
        c.executescript(sql)

def hw() -> str:
    gpu = "sem nvidia-smi"
    try:
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=30).stdout.strip() or gpu
    except Exception:
        pass
    try:
        v = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=30).stdout.splitlines()[0]
        v = v.split(" Copyright")[0]
    except Exception:
        v = "ffmpeg"
    return f"{gpu} | {v}"

def sonda(fonte: str) -> dict:
    """Resolucao, fps e bitrate de entrada (o quanto o video original pesa)."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height,r_frame_rate,bit_rate,codec_name",
                            "-show_entries", "format=bit_rate,duration,format_name",
                            "-of", "json", fonte], capture_output=True, text=True, timeout=45)
        d = json.loads(r.stdout or "{}")
    except Exception as e:
        return {"erro": str(e)}
    st = (d.get("streams") or [{}])[0]
    fm = d.get("format") or {}
    taxa = st.get("r_frame_rate") or "0/1"
    try:
        num, den = taxa.split("/"); fps = round(int(num) / max(1, int(den)), 2)
    except Exception:
        fps = None
    kbps = None
    for v in (st.get("bit_rate"), fm.get("bit_rate")):
        try:
            kbps = round(int(v) / 1000, 1); break
        except Exception:
            continue
    return {"resolucao": f"{st.get('width')}x{st.get('height')}" if st.get("width") else "",
            "fps": fps, "bitrate_kbps": kbps, "codec_entrada": st.get("codec_name", ""),
            "duracao_s": round(float(fm.get("duration") or 0), 2) if fm.get("duration") else None}

def _comando(fonte: str, fluxo_id: str, bitrate: str, codec: str, repetir: bool, tipo: str,
             srt_host: str, srt_port: int, audio: bool = False) -> list[str]:
    destino = (f"srt://{srt_host}:{srt_port}?mode=caller&latency=200&pkt_size=1316&streamid=publish:{fluxo_id}")
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning", "-re"]
    if tipo == "arquivo" and repetir:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-i", fonte]
    cmd += ["-c:v", codec, "-preset", "ultrafast", "-tune", "zerolatency",
            "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", "1M",
            "-g", "30", "-pix_fmt", "yuv420p"]
    # Audio do clipe de teste pesa mais que o video comprimido (MP2 padrao ~224 kbps): por padrao
    # vai sem audio, para o numero medido ser o do video; quem quiser mantem a 48 kbps mono.
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "48k", "-ac", "1"]
    else:
        cmd += ["-an"]
    cmd += ["-f", "mpegts", "-progress", "pipe:1", "-nostats", destino]
    return cmd

def alvo_automatico(entrada_kbps: float | None, fator: float = 0.5, piso: int = 250, teto: int = 8000) -> str:
    """Alvo de encode para COMPRIMIR de verdade: fracao do que o video de entrada gasta.
    Clipe leve (0,75 Mbps) recebe alvo abaixo dele; video de camera (8-15 Mbps) cai bem mais."""
    if not entrada_kbps:
        return "1200k"
    return f"{max(piso, min(teto, round(entrada_kbps * fator / 50.0) * 50))}k"


def iniciar(fonte: str, *, rotulo: str, fluxo_id: str | None = None, bitrate: str = "auto",
            codec: str = "libx264", repetir: bool = True, tipo: str | None = None, audio: bool = False,
            embarcacao_id: str = "psv-exemplo", srt_host: str = "127.0.0.1", srt_port: int = 8890,
            registrar_camera: bool = True, abrir_log: bool = True) -> dict:
    """Sobe a ingestao. Devolve o registro (com id) para a tela acompanhar."""
    garantir_schema()
    ENVIOS.mkdir(parents=True, exist_ok=True); LOG_DIR.mkdir(parents=True, exist_ok=True)
    if tipo is None:
        tipo = "arquivo" if re.match(r"^[a-zA-Z]:[\\/]|^/|^\.{1,2}[\\/]", fonte) or Path(fonte).exists() else "url"
    if tipo == "arquivo":
        p = Path(fonte)
        if not p.exists():
            return {"erro": f"arquivo nao encontrado: {fonte}"}
        fonte = str(p.resolve())
    slug = re.sub(r"[^a-z0-9]+", "-", (rotulo or Path(fonte).stem).lower()).strip("-")[:38] or "envio"
    fluxo_id = fluxo_id or f"envio-{slug}"
    fluxo_id = re.sub(r"[^a-zA-Z0-9_\-]", "-", fluxo_id)
    camera_id = fluxo_id
    s = sonda(fonte)
    if not bitrate or bitrate == "auto":
        bitrate = alvo_automatico(s.get("bitrate_kbps"))
    # avisa quando o alvo escolhido gasta MAIS que a entrada (o clipe sai maior do que entrou)
    aviso = ""
    ent = s.get("bitrate_kbps")
    alvo_kbps = float(re.sub(r"[^0-9.]", "", bitrate) or 0) * (1 if bitrate.endswith("k") else 1000)
    if ent and alvo_kbps > ent * 1.05:
        aviso = (f"alvo {bitrate} e MAIOR que a entrada ({ent} kbps): a saida vai gastar mais banda que o video enviado. "
                 f"Para comprimir, use alvo abaixo da entrada (ex.: {alvo_automatico(ent)}) — o numero medido e o total do fluxo (video + audio + MPEG-TS).")
    cmd = _comando(fonte, fluxo_id, bitrate, codec, repetir, tipo, srt_host, srt_port, audio=audio)
    log = LOG_DIR / f"{fluxo_id}-{int(time.time())}.log"
    saida = open(log, "ab", buffering=0) if abrir_log else subprocess.DEVNULL
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=saida, cwd=str(RAIZ))
    with conexao() as c:
        cur = c.execute("""INSERT INTO ingestoes (fluxo_id, camera_id, rotulo, fonte, tipo, repetir, codec,
              bitrate_alvo, resolucao, fps_nativo, bitrate_entrada_kbps, estado, pid, log, criado_em, atualizado_em)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fluxo_id, camera_id, rotulo or slug, fonte, tipo, 1 if repetir else 0, codec, bitrate,
             s.get("resolucao"), s.get("fps"), s.get("bitrate_kbps"), "iniciando", proc.pid, str(log), agora(), agora()))
        ident = cur.lastrowid
        if registrar_camera:
            c.execute("""INSERT INTO cameras (id, embarcacao_id, rotulo, fluxo_id, local, ativo)
                         VALUES (?,?,?,?,?,1)
                         ON CONFLICT(id) DO UPDATE SET rotulo=excluded.rotulo, ativo=1, local='envio'""",
                      (camera_id, embarcacao_id, rotulo or slug, fluxo_id, "envio"))
    threading.Thread(target=_bombear, args=(ident, proc, log), daemon=True).start()
    return {"id": ident, "fluxo_id": fluxo_id, "camera_id": camera_id, "pid": proc.pid,
            "comando": " ".join(cmd), "entrada": s, "alvo": bitrate, "aviso": aviso, "log": str(log)}

def _bombear(ident: int, proc: subprocess.Popen, log: Path):
    """Le o -progress do ffmpeg e mantem a tabela ingestoes atualizada."""
    ultimo, ultima_amostra, inicio, ultima_gravacao = {}, time.time(), time.time(), 0.0
    pendente = {}
    try:
        for linha in proc.stdout:
            k, _, v = linha.decode("utf-8", "replace").strip().partition("=")
            ultimo[k] = v
            if k != "progress":
                continue
            if time.time() - ultima_gravacao < 1.0:
                continue   # grava no banco no maximo 1x por segundo (senao o ffmpeg trava o SQLite)
            ultima_gravacao = time.time()
            try:
                taxa = float(re.sub(r"[^0-9.]", "", ultimo.get("bitrate", "0")) or 0)
                fps = float(ultimo.get("fps", "0") or 0)
                vel = float(re.sub(r"[^0-9.]", "", ultimo.get("speed", "0")) or 0)
                tam = float(ultimo.get("total_size", "0") or 0) / 1e6
                dur = float(ultimo.get("out_time_us", "0") or 0) / 1e6
            except ValueError:
                continue
            with conexao() as c:
                ent = c.execute("SELECT bitrate_entrada_kbps FROM ingestoes WHERE id=?", (ident,)).fetchone()
                ent = (ent or {"bitrate_entrada_kbps": None})["bitrate_entrada_kbps"]
                corte = round((1 - (taxa / ent)) * 100, 2) if ent and taxa else None
                c.execute("""UPDATE ingestoes SET estado='no_ar', bitrate_saida_kbps=?, fps=?, velocidade=?,
                             tamanho_mb=?, duracao_s=?, corte_pct=?, atualizado_em=?, erro=NULL WHERE id=?""",
                          (round(taxa, 1), round(fps, 1), round(vel, 2), round(tam, 1), round(dur, 1),
                           corte, agora(), ident))
            if time.time() - ultima_amostra >= 10:
                ultima_amostra = time.time()
                with conexao() as c:
                    r = c.execute("SELECT * FROM ingestoes WHERE id=?", (ident,)).fetchone()
                    c.execute("""INSERT INTO ingestoes_amostras (ingestao_id, em, taxa_saida_kbps, fps,
                                 velocidade, tamanho_mb, corte_pct) VALUES (?,?,?,?,?,?,?)""",
                              (ident, agora(), r["bitrate_saida_kbps"], r["fps"], r["velocidade"], r["tamanho_mb"], r["corte_pct"]))
    finally:
        codigo = proc.wait()
        with conexao() as c:
            r = c.execute("SELECT * FROM ingestoes WHERE id=?", (ident,)).fetchone()
            if r and r["estado"] != "parado":
                c.execute("UPDATE ingestoes SET estado=?, erro=?, atualizado_em=? WHERE id=?",
                          ("erro" if codigo else "fim", None if codigo == 0 else f"ffmpeg saiu com codigo {codigo}", agora(), ident))
            if r and (r["duracao_s"] or 0) >= 15:
                c.execute("""INSERT INTO medicoes (valor, fonte, data, hardware_versao, comando)
                             VALUES (?,?,?,?,?)""",
                          (f"envio de video: entrada {r['bitrate_entrada_kbps'] or '?'} kbps -> saida "
                           f"{r['bitrate_saida_kbps'] or '?'} kbps; corte {r['corte_pct'] if r['corte_pct'] is not None else '?'}%;"
                           f" fps {r['fps'] or '?'}; {round(time.time()-inicio)} s no ar",
                           f"ground/envios (log {Path(r['log']).name})", dt.date.today().isoformat(), hw(),
                           f"ground/ingestao.py --fonte {r['fonte']} --bitrate {r['bitrate_alvo']}"))

def parar(ident: int, remover_camera: bool = False) -> dict:
    with conexao() as c:
        r = c.execute("SELECT * FROM ingestoes WHERE id=?", (ident,)).fetchone()
        if not r:
            return {"erro": "ingestao nao encontrada"}
        if r["pid"]:
            try:
                os.kill(r["pid"], signal.SIGTERM)
            except Exception:
                try:
                    subprocess.run(["taskkill", "/F", "/PID", str(r["pid"])], capture_output=True)
                except Exception:
                    pass
        c.execute("UPDATE ingestoes SET estado='parado', parado_em=?, atualizado_em=? WHERE id=?", (agora(), agora(), ident))
        if remover_camera and r["camera_id"]:
            c.execute("DELETE FROM cameras WHERE id=?", (r["camera_id"],))
        return {"ok": True, "id": ident, "fluxo_id": r["fluxo_id"]}

def listar(limite: int = 40) -> list[dict]:
    garantir_schema()
    with conexao() as c:
        linhas = [dict(x) for x in c.execute("SELECT * FROM ingestoes ORDER BY id DESC LIMIT ?", (limite,)).fetchall()]
    vivos = _pids_vivos()
    for l in linhas:
        l["vivo"] = bool(l["pid"]) and l["pid"] in vivos
        if l["estado"] in ("no_ar", "iniciando") and not l["vivo"]:
            l["estado"] = "encerrado"
    return linhas

_cache_pids: list = [0.0, set()]


def _pids_vivos() -> set:
    """Uma chamada ao sistema por vez, com cache curto: pedir processo por processo
    fazia a lista de envios demorar (e travar a API) com varias ingestões no ar."""
    if time.time() - _cache_pids[0] < 3:
        return _cache_pids[1]
    pids: set[int] = set()
    try:
        r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=20)
        for linha in r.stdout.splitlines():
            campos = [c.strip('"').strip() for c in linha.split('","')]
            if len(campos) >= 2 and campos[1].isdigit():
                pids.add(int(campos[1]))
    except Exception:
        pids = set()
    _cache_pids[0], _cache_pids[1] = time.time(), pids
    return pids


def _vivo(pid: int) -> bool:
    return bool(pid) and pid in _pids_vivos()

def main() -> int:
    ap = argparse.ArgumentParser(description="Ingestao de video de teste (arquivo ou link) -> SRT")
    ap.add_argument("--fonte", required=True, help="caminho do arquivo ou endereco http(s)")
    ap.add_argument("--rotulo", default="")
    ap.add_argument("--fluxo-id", default=None)
    ap.add_argument("--bitrate", default="auto", help="'auto' = metade da entrada (comprime de verdade) ou ex.: 1200k")
    ap.add_argument("--com-audio", action="store_true", help="mantem o audio do clipe (48 kbps mono)")
    ap.add_argument("--codec", default="libx264")
    ap.add_argument("--sem-repetir", action="store_true")
    ap.add_argument("--embarcacao", default="psv-exemplo")
    a = ap.parse_args()
    r = iniciar(a.fonte, rotulo=a.rotulo or Path(a.fonte).stem, fluxo_id=a.fluxo_id, bitrate=a.bitrate,
                codec=a.codec, repetir=not a.sem_repetir, embarcacao_id=a.embarcacao)
    print(json.dumps(r, ensure_ascii=False, indent=2), flush=True)
    if "erro" in r:
        return 1
    # o CLI fica vivo acompanhando o encode (senao a thread que mede morre com o processo)
    try:
        while _vivo(r["pid"]):
            time.sleep(2)
    except KeyboardInterrupt:
        parar(r["id"])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
