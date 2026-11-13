#!/usr/bin/env python3
"""Ingestao de video de teste: recebe um ARQUIVO enviado ou um LINK e faz o mesmo
caminho do produto — codifica (libx264/hevc), empacota em MPEG-TS e publica em SRT
no mediamtx, medindo bitrate de entrada x saida (corte) e fps.

Serve para o dono testar compressao e streaming antes das imagens reais das embarcacoes.
Nenhuma credencial de camera entra aqui: a fonte e arquivo local ou link publico.
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, re, shutil, signal, socket, sqlite3, subprocess, sys, threading, time, unicodedata
from pathlib import Path

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from ferramentas import caminho_banco, caminho_ffmpeg, caminho_ffprobe  # noqa: E402  (embutidos no app)


RAIZ = Path(__file__).resolve().parent.parent
BANCO = caminho_banco()
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
        # colunas novas em banco que ja existia (CREATE TABLE IF NOT EXISTS nao altera tabela pronta)
        for coluna, tipo in (("srt_host", "TEXT"),):
            try:
                c.execute(f"ALTER TABLE ingestoes ADD COLUMN {coluna} {tipo}")
            except sqlite3.OperationalError:
                pass

def hw() -> str:
    gpu = "sem nvidia-smi"
    try:
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=30).stdout.strip() or gpu
    except Exception:
        pass
    try:
        v = subprocess.run([caminho_ffmpeg(), "-version"], capture_output=True, text=True, timeout=30).stdout.splitlines()[0]
        v = v.split(" Copyright")[0]
    except Exception:
        v = "ffmpeg"
    return f"{gpu} | {v}"

# Link de PAGINA (YouTube, Vimeo...) nao e o video: o ffmpeg nao abre. Resolvemos pelo yt-dlp.
MEDIA_RE = re.compile(r"\.(mp4|mkv|mov|webm|m4v|m3u8|mpd|ts|mts|avi|flv|wmv|mpg|mpeg)(\?|$)", re.I)
CDN_RE = re.compile(r"(googlevideo\.com|vimeocdn\.com|cloudfront\.net|akamai|backblazeb2\.com|blob\.core\.windows\.net)", re.I)


def _yt_dlp() -> str | None:
    achado = shutil.which("yt-dlp")
    if achado:
        return achado
    for c in (Path.home() / ".local" / "bin" / "yt-dlp.exe", Path.home() / ".local" / "bin" / "yt-dlp"):
        if c.exists():
            return str(c)
    return None


def resolver_link(url: str, timeout: int = 240) -> tuple[str, str | None, str]:
    """Devolve (url_do_video, url_do_audio_ou_None, titulo). Link direto de midia passa como esta."""
    if MEDIA_RE.search(url) or CDN_RE.search(url):
        return url, None, ""
    exe = _yt_dlp()
    if not exe:
        raise RuntimeError("esse link e de uma PAGINA (YouTube, Vimeo...), nao do video: o ffmpeg nao abre. "
                           "Use um link direto (.mp4/.m3u8) ou instale o yt-dlp no servidor de captura.")
    r = subprocess.run([exe, "--no-warnings", "--no-playlist",
                        "-f", "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b", "-g", url],
                       capture_output=True, text=True, timeout=timeout)
    urls = [l for l in (r.stdout or "").strip().splitlines() if l.startswith("http")]
    if not urls:
        ultimo = ((r.stderr or "").strip().splitlines() or ["o site nao devolveu video"])[-1][:200]
        raise RuntimeError("nao consegui resolver o link: " + ultimo)
    titulo = ""
    try:
        t2 = subprocess.run([exe, "--no-warnings", "--no-playlist", "--print", "title", url],
                            capture_output=True, text=True, timeout=90)
        titulo = (t2.stdout or "").strip().splitlines()[0] if (t2.stdout or "").strip() else ""
    except Exception:
        titulo = ""
    return urls[0], (urls[1] if len(urls) > 1 else None), titulo


def sonda(fonte: str) -> dict:
    """Resolucao, fps e bitrate de entrada (o quanto o video original pesa)."""
    try:
        r = subprocess.run([caminho_ffprobe(), "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height,r_frame_rate,bit_rate,codec_name",
                            "-show_entries", "format=bit_rate,duration,format_name,size",
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
    # bit_rate do ffprobe em fluxo remoto (DASH/AV1 do YouTube) vem errado: o honesto e tamanho/duracao
    try:
        tam, dur = int(fm.get("size") or 0), float(fm.get("duration") or 0)
        if tam > 0 and dur > 0:
            kbps = round(tam * 8 / dur / 1000, 1)
    except Exception:
        kbps = None
    if not kbps:
        for v in (st.get("bit_rate"), fm.get("bit_rate")):
            try:
                kbps = round(int(v) / 1000, 1); break
            except Exception:
                continue
    return {"resolucao": f"{st.get('width')}x{st.get('height')}" if st.get("width") else "",
            "fps": fps, "bitrate_kbps": kbps, "codec_entrada": st.get("codec_name", ""),
            "duracao_s": round(float(fm.get("duration") or 0), 2) if fm.get("duration") else None}

def _comando(fonte: str, fluxo_id: str, bitrate: str, codec: str, repetir: bool, tipo: str,
             srt_host: str, srt_port: int, audio: bool = False, fonte2: str | None = None,
             fps: int = 30, arquivo_saida: str | None = None, copiar: bool = False,
             dispositivo: str | None = None, resolucao: str = "1920x1080") -> list[str]:
    destino = (f"srt://{srt_host}:{srt_port}?mode=caller&latency=200&pkt_size=1316&streamid=publish:{fluxo_id}")
    cmd = [caminho_ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "warning"]
    if tipo in ("camera", "sintetica"):
        # FONTE VIVA: a webcam (ou o gerador) entrega no tempo real — nada de -re nem de laço,
        # o envio e' CONTINUO, igual a operacao. Sem -t: so para quando o dono mandar parar.
        cmd += _args_fonte_viva(tipo, dispositivo, resolucao, fps)
    else:
        cmd += ["-re"]
        if tipo == "arquivo" and repetir:
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", fonte]
    if fonte2 and audio:   # yt-dlp entrega video e audio em enderecos separados: junta os dois
        cmd += ["-i", fonte2, "-map", "0:v:0", "-map", "1:a:0?"]
    if copiar:
        # arquivo JA comprimido que vai direto para o ar: sem re-codificar (nao gastar banda a toa)
        cmd += ["-c:v", "copy"]
    else:
        cmd += ["-c:v", codec, "-preset", "ultrafast", "-tune", "zerolatency",
                "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", "1M",
                "-r", str(fps), "-g", str(fps), "-pix_fmt", "yuv420p"]   # 30 fps: menos de 30 fica ruim, 60 gasta banda
    # Audio do clipe de teste pesa mais que o video comprimido (MP2 padrao ~224 kbps): por padrao
    # vai sem audio, para o numero medido ser o do video; quem quiser mantem a 48 kbps mono.
    if copiar:
        cmd += ["-c:a", "copy"]        # arquivo comprimido: audio vai como esta (se houver)
    elif audio:
        cmd += ["-c:a", "aac", "-b:a", "48k", "-ac", "1"]
    else:
        cmd += ["-an"]
    cmd += ["-f", "mpegts", "-progress", "pipe:1", "-nostats", destino]
    if arquivo_saida:
        # guarda o MESMO encode em arquivo (sem recodificar) para o dono baixar e comparar
        cmd += ["-c", "copy", "-f", "mpegts", arquivo_saida]
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
            registrar_camera: bool = True, abrir_log: bool = True, fps: int = 30,
            guardar_arquivo: bool = False, copiar: bool = False,
            dispositivo: str | None = None, resolucao: str = "1920x1080") -> dict:
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
    base_nome = unicodedata.normalize("NFKD", (rotulo or Path(fonte).stem).lower())
    base_nome = "".join(ch for ch in base_nome if not unicodedata.combining(ch))
    slug = re.sub(r"[^a-z0-9]+", "-", base_nome).strip("-")[:38] or "envio"
    fluxo_id = fluxo_id or f"envio-{slug}"
    fluxo_id = re.sub(r"[^a-zA-Z0-9_\-]", "-", fluxo_id)
    camera_id = fluxo_id
    fonte2 = None
    origem_pagina = ""
    if tipo == "url" and not MEDIA_RE.search(fonte) and not CDN_RE.search(fonte):
        direto, fonte2, titulo = resolver_link(fonte)
        origem_pagina = fonte       # o que o dono colou (fica na tela e no banco)
        fonte = direto              # endereco do CDN (so vai para o log)
        if titulo and (not rotulo or rotulo == "vídeo por link"):
            rotulo = titulo
    if tipo == "camera" and not (dispositivo or DISPOSITIVO_PADRAO):
        # sem dispositivo nao existe captura: recusar na borda e' melhor que subir um dshow vazio
        return {"erro": "escolha a camera na lista (nenhum dispositivo de captura foi informado)"}
    if tipo == "camera":
        # guarda o seletor unico: a coluna `fonte` e' a identidade da camera (duas cameras de
        # mesmo nome passam a ter linhas distintas e uma nao bloqueia a outra)
        dispositivo = _normalizar_dispositivo(dispositivo)
    if tipo in ("camera", "sintetica"):
        # fonte viva: nao ha arquivo para sondar. A resolucao vem do pedido e o alvo e' fixo
        # (o numero medido passa a ser o do envio CONTINUO, lido do -progress do ffmpeg).
        s = {"resolucao": _resolucao_valida(resolucao, "1920x1080" if tipo == "sintetica" else "1280x720"),
             "fps": float(fps or 30), "bitrate_kbps": None,
             "dispositivo": (dispositivo or DISPOSITIVO_PADRAO) if tipo == "camera" else "testsrc2"}
        repetir = False
        if not bitrate or bitrate == "auto":
            bitrate = "2500k" if tipo == "sintetica" else "1500k"
    else:
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
    arquivo_saida = str(ENVIOS / "log" / f"{fluxo_id}-{int(time.time())}.ts") if guardar_arquivo else None
    cmd = _comando(fonte, fluxo_id, bitrate, codec, repetir, tipo, srt_host, srt_port, audio=audio,
                   fonte2=fonte2, fps=fps, arquivo_saida=arquivo_saida, copiar=copiar,
                   dispositivo=dispositivo, resolucao=resolucao)
    log = LOG_DIR / f"{fluxo_id}-{int(time.time())}.log"
    saida = open(log, "ab", buffering=0) if abrir_log else subprocess.DEVNULL
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=saida, cwd=str(RAIZ))
    with conexao() as c:
        cur = c.execute("""INSERT INTO ingestoes (fluxo_id, camera_id, rotulo, fonte, tipo, repetir, codec,
              bitrate_alvo, resolucao, fps_nativo, bitrate_entrada_kbps, estado, pid, log, srt_host,
              criado_em, atualizado_em)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fluxo_id, camera_id, rotulo or slug,
             origem_pagina or (f"dshow:{dispositivo or DISPOSITIVO_PADRAO}" if tipo == "camera"
                               else (f"lavfi:testsrc2:{resolucao}" if tipo == "sintetica" else fonte)),
             tipo, 1 if repetir else 0, codec, bitrate,
             s.get("resolucao"), s.get("fps"), s.get("bitrate_kbps"), "iniciando", proc.pid, str(log),
             srt_host, agora(), agora()))
        ident = cur.lastrowid
        if tipo in ("camera", "sintetica"):
            # a resolucao real da webcam so se sabe DEPOIS que ela publica: sonda o caminho uma vez
            threading.Thread(target=_sondar_publicado, args=(ident, fluxo_id), daemon=True).start()
        if registrar_camera:
            c.execute("""INSERT INTO cameras (id, embarcacao_id, rotulo, fluxo_id, local, ativo)
                         VALUES (?,?,?,?,?,1)
                         ON CONFLICT(id) DO UPDATE SET rotulo=excluded.rotulo, ativo=1, local='envio'""",
                      (camera_id, embarcacao_id, rotulo or slug, fluxo_id, "envio"))
    threading.Thread(target=_bombear, args=(ident, proc, log), daemon=True).start()
    return {"id": ident, "fluxo_id": fluxo_id, "camera_id": camera_id, "pid": proc.pid,
            "comando": " ".join(cmd), "entrada": s, "alvo": bitrate, "aviso": aviso, "log": str(log),
            "pagina": origem_pagina, "fps_alvo": fps, "arquivo_saida": arquivo_saida}

def _motivo_da_falha(codigo: int, log: Path, r: dict) -> str | None:
    """Motivo curto quando o envio NAO subiu, para a tela poder avisar em vez de so ficar preta.

    O ffmpeg sai com codigo 0 mesmo quando nao codificou nada, entao o codigo sozinho nao serve:
    olhamos o log e o proprio registro (nenhum kbps medido = nenhum quadro saiu).
    """
    try:
        texto = Path(log).read_text(encoding="utf-8", errors="replace") if log else ""
    except Exception:
        texto = ""
    baixo = texto.lower()
    # PRIMEIRO o link: "I/O error" aqui quase sempre vem do muxer/soquete SRT (a rede caiu ou o IP
    # publico mudou), NAO da camera — culpar a camera fazia o dono procurar defeito onde nao tinha.
    if ("wsagetoverlappedresult" in baixo or "error submitting a packet to the muxer" in baixo
            or "error muxing a packet" in baixo or "[srt" in baixo or "srt.ks" in baixo):
        return ("o link com o servidor caiu no meio do envio (a camera esta bem): "
                "tentando reconectar sozinho")
    if "could not run filter" in baixo or "device already" in baixo or "device is not available" in baixo \
            or "unspecified error" in baixo or "i/o error" in baixo:
        return ("a camera nao abriu: pode estar em uso por outro envio ou desconectada — "
                "mande parar o outro envio e ligue de novo")
    if "nothing was encoded" in baixo or "no filtered frames" in baixo:
        return "a fonte nao entregou nenhum quadro (camera ocupada ou desconectada)"
    if "no such file" in baixo or "not found" in baixo:
        return "fonte nao encontrada"
    if codigo and codigo != 0:
        ultimas = [x.strip() for x in texto.strip().splitlines() if x.strip()][-1:] or [""]
        return f"ffmpeg saiu com codigo {codigo}: {ultimas[0][:160]}"
    if not r.get("bitrate_saida_kbps"):
        return "o envio terminou sem nenhum dado medido (nenhum quadro foi enviado)"
    return None


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
                motivo = _motivo_da_falha(codigo, log, dict(r) if r is not None else {})
                # o ffmpeg as vezes sai com codigo 0 sem ter codificado NADA (camera ja em uso, por
                # exemplo): sem isso a tela pintava um quadro preto e nenhum aviso de erro.
                # O "AND estado<>'parado'" e' atomico de proposito: quem desligou a camera pela tela
                # marcou 'parado' e esse recado NAO pode ser sobrescrito por 'erro' (corrida real —
                # a linha virava 'erro', o remetente achava que foi queda de rede e reabria sozinho).
                c.execute("UPDATE ingestoes SET estado=?, erro=?, atualizado_em=? WHERE id=? AND estado<>'parado'",
                          ("erro" if motivo else "fim", motivo, agora(), ident))
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
        # marca ANTES de matar: o vigia do remetente olha o estado no banco para saber se a queda
        # foi da rede (reabre) ou se foi a tela que desligou (nao reabre). A ordem evita corrida.
        c.execute("UPDATE ingestoes SET estado='parado', parado_em=?, atualizado_em=? WHERE id=?", (agora(), agora(), ident))
        if r["pid"]:
            try:
                os.kill(r["pid"], signal.SIGTERM)
            except Exception:
                try:
                    subprocess.run(["taskkill", "/F", "/PID", str(r["pid"])], capture_output=True)
                except Exception:
                    pass
        if remover_camera and r["camera_id"]:
            c.execute("DELETE FROM cameras WHERE id=?", (r["camera_id"],))
        # parar de verdade = soltar o dispositivo: sem isso a webcam ficava presa e o proximo
        # envio respondia "camera em uso", obrigando a desligar/ligar na mao.
        disp = None
        if (r["fonte"] or "").startswith("dshow:"):
            disp = r["fonte"].split("dshow:", 1)[1]
        livre = liberar_camera(disp) if disp else {"liberados": 0}
        return {"ok": True, "id": ident, "fluxo_id": r["fluxo_id"], **livre}


def desligar_camera(camera_id: str) -> dict:
    """Desliga a camera pela tela: para o envio vivo dessa camera e solta o dispositivo.

    Ninguem precisa desconectar nada fisicamente — e' o mesmo efeito de "desligar a camera".
    """
    with conexao() as c:
        cam = c.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
        if not cam:
            return {"erro": "camera nao encontrada"}
        linha = c.execute("""SELECT * FROM ingestoes WHERE fluxo_id=?
                              AND estado IN ('no_ar','no ar','iniciando') ORDER BY id DESC LIMIT 1""",
                          (cam["fluxo_id"],)).fetchone()
        if not linha:
            linha = c.execute("SELECT * FROM ingestoes WHERE fluxo_id=? ORDER BY id DESC LIMIT 1",
                              (cam["fluxo_id"],)).fetchone()
    parados = []
    if linha and linha["estado"] not in ("parado", "fim"):
        parados.append(parar(linha["id"])["id"])
    disp = None
    if linha and (linha["fonte"] or "").startswith("dshow:"):
        disp = linha["fonte"].split("dshow:", 1)[1]
    livre = liberar_camera(disp)
    return {"ok": True, "camera_id": camera_id, "fluxo_id": cam["fluxo_id"], "parados": parados,
            "liberados": livre.get("liberados", 0), "dispositivo": livre.get("dispositivo")}


def ligar_camera(camera_id: str) -> dict:
    """Liga a camera pela tela, reusando o ultimo envio dela (mesmo ajuste, mesma origem).

    A camera volta sozinha: antes de abrir, solta quem estiver segurando o dispositivo.
    """
    with conexao() as c:
        cam = c.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
        if not cam:
            return {"erro": "camera nao encontrada"}
        ult = c.execute("SELECT * FROM ingestoes WHERE fluxo_id=? ORDER BY id DESC LIMIT 1",
                        (cam["fluxo_id"],)).fetchone()
    if cam["ip"]:
        return {"erro": "esta camera e por endereco (RTSP) e precisa de credencial: use Enviar video"}
    d = dict(ult) if ult else {}
    fonte = d.get("fonte") or ""
    if fonte.startswith("live:sintetica") or d.get("tipo") == "sintetica":
        return ao_vivo(tipo="sintetica", rotulo=cam["rotulo"], fluxo_id=cam["fluxo_id"],
                       bitrate=d.get("bitrate_alvo") or "auto",
                       srt_host=d.get("srt_host") or "187.127.60.250",
                       srt_port=int(d.get("srt_port") or 8890),
                       embarcacao_id=cam["embarcacao_id"])
    if not fonte.startswith("live:camera") and not fonte.startswith("dshow:"):
        return {"erro": "esta camera nunca foi transmitida daqui: use Enviar video para ligar o envio"}
    disp = d.get("dispositivo") or (fonte.split("dshow:", 1)[1] if "dshow:" in fonte else DISPOSITIVO_PADRAO)
    return ao_vivo(tipo="camera", dispositivo=disp, rotulo=cam["rotulo"], fluxo_id=cam["fluxo_id"],
                   resolucao=d.get("resolucao") or "1280x720", fps=int(d.get("fps_alvo") or 30),
                   bitrate=d.get("bitrate_alvo") or "3000k",
                   srt_host=d.get("srt_host") or "187.127.60.250", srt_port=int(d.get("srt_port") or 8890),
                   embarcacao_id=cam["embarcacao_id"])

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

# ---------------------------------------------------------------------------
# Fontes SEM camera IP: webcam do proprio notebook (dshow) e fonte sintetica
# (testsrc2). Servem para testar compressao e streaming na bancada sem depender
# de camera de embarcacao e sem credencial nenhuma.
# ---------------------------------------------------------------------------
DISPOSITIVO_PADRAO = os.environ.get("LECSOR_DISPOSITIVO", "").strip()


def _normalizar_dispositivo(nome: str | None) -> str:
    """Devolve o seletor que vai em `video=` do dshow, tirando o prefixo se vier pronto.

    O NOME amigavel nao identifica a camera: duas webcams USB iguais aparecem com o mesmo nome
    ("USB Video Device"), e o registro de "camera em uso" casava por nome — cadastrar a primeira
    fazia a segunda ser recusada como se fosse a mesma. O "Alternative name" (@device_pnp_...) e'
    unico por dispositivo e e' o que identifica de verdade.
    """
    t = (nome or "").strip()
    if t.startswith("video="):
        t = t[len("video="):].strip()
    return t


def listar_dispositivos() -> dict:
    """Webcams e microfones que o ffmpeg enxerga (dshow do Windows).

    NUNCA inventa dispositivo: sem camera a lista volta vazia, com o motivo. O nome padrao so' vem
    de LECSOR_DISPOSITIVO (variavel de ambiente) — antes era um nome fixo no codigo (a webcam da
    bancada) e aparecia em QUALQUER maquina sem camera, como se a camera existisse.
    """
    d = {"video": [], "audio": [], "padrao": "", "maquina": socket.gethostname()}
    try:
        r = subprocess.run([caminho_ffmpeg(), "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                           capture_output=True, text=True, timeout=60, errors="replace")
    except FileNotFoundError:
        d.update(erro="ffmpeg nao encontrado nesta maquina (PATH)",
                 motivo="instale o ffmpeg e deixe `ffmpeg` no PATH: sem ele nada e' listado nem capturado")
        return d
    except Exception as e:
        d.update(erro=str(e), motivo="nao foi possivel consultar as cameras desta maquina")
        return d
    video, audio, dispositivos = [], [], []
    pendente = None          # (tipo, nome) aguardando o "Alternative name" da linha seguinte
    for linha in (r.stderr or "").splitlines():
        m_alt = re.search(r'Alternative name "([^"]+)"', linha)
        if m_alt:
            # o Alternative name (@device_pnp_...) e' UNICO por dispositivo: e' ele que separa
            # duas webcams de mesmo nome. Antes a linha era descartada e as duas viravam uma so'.
            if pendente and pendente[0] == "video":
                dispositivos.append({"video": pendente[1], "seletor": m_alt.group(1)})
            pendente = None
            continue
        m = re.search(r'"([^"]+)"\s*\((video|audio)\)', linha)
        if m:
            (video if m.group(2) == "video" else audio).append(m.group(1))
            pendente = (m.group(2), m.group(1))
    # duas cameras com o mesmo nome recebem rotulo distinto na tela: "USB Video Device (1)/(2)"
    total = {}
    for x in dispositivos:
        total[x["video"]] = total.get(x["video"], 0) + 1
    visto = {}
    for i, x in enumerate(dispositivos):
        n = x["video"]
        visto[n] = visto.get(n, 0) + 1
        x["rotulo"] = n if total[n] == 1 else f"{n} ({visto[n]})"
        x["indice"] = i
    d.update(video=video, audio=audio, dispositivos=dispositivos,
             padrao=(video[0] if video else DISPOSITIVO_PADRAO),
             padrao_seletor=((dispositivos[0]["seletor"] if dispositivos else "")))
    if not video:
        d["motivo"] = ("o ffmpeg nao encontrou camera nesta maquina: confira o driver, a porta USB "
                       "e se o dispositivo aparece no Gerenciador de Dispositivos")
    return d


def _args_fonte_viva(tipo: str, dispositivo: str | None, resolucao: str, fps: int) -> list[str]:
    if tipo == "sintetica":
        return ["-f", "lavfi", "-i", f"testsrc2=size={resolucao or '1920x1080'}:rate={fps or 30}"]
    # -video_size EXPLICITO: sem ele a webcam entrega o que quiser e o registro ficava SEM resolucao
    # (guardava o nome do dispositivo), o que zerava a entrada/compressao na tela.
    return ["-f", "dshow", "-rtbufsize", "256M", "-framerate", str(fps or 30),
            "-video_size", _resolucao_valida(resolucao, "1280x720"),
            "-i", f'video={_normalizar_dispositivo(dispositivo or DISPOSITIVO_PADRAO)}']


def _resolucao_valida(txt: str | None, padrao: str = "1280x720") -> str:
    """Devolve 'LARGURAxALTURA'. Fonte viva nao tem arquivo para sondar: se o que veio nao for
    uma resolucao (ex.: o nome do dispositivo da webcam), usa o padrao pedido."""
    m = re.match(r"^\s*(\d{2,5})\s*[xX]\s*(\d{2,5})\s*$", txt or "")
    return f"{m.group(1)}x{m.group(2)}" if m else padrao


def capturar(*, tipo: str = "camera", dispositivo: str | None = None, resolucao: str = "1920x1080",
             fps: int = 30, segundos: int = 10, rotulo: str | None = None) -> dict:
    """Grava um clipe de teste de uma fonte viva (webcam ou sintetica) para o disco.

    Daqui em diante o clipe segue o MESMO caminho do produto: comprimir -> medir (corte e SSIM)
    -> publicar em SRT. Assim a compressao e o streaming sao testados sem camera de embarcacao.
    """
    if tipo not in ("camera", "sintetica"):
        return {"erro": "tipo de captura invalido: use 'camera' (webcam) ou 'sintetica'"}
    segundos = max(3, min(120, int(segundos or 10)))
    ENVIOS.mkdir(parents=True, exist_ok=True)
    origem_dir = ENVIOS / "originais"; origem_dir.mkdir(parents=True, exist_ok=True)
    base = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", (rotulo or tipo).lower()))
    base = "".join(ch for ch in base if not unicodedata.combining(ch)).strip("-")[:38] or tipo
    destino = origem_dir / f"captura-{base}-{dt.datetime.now().strftime('%H%M%S')}.mp4"
    cmd = ([caminho_ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "warning", "-y"]
           + _args_fonte_viva(tipo, dispositivo, resolucao, fps)
           + ["-t", str(segundos), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
              "-pix_fmt", "yuv420p", "-r", str(fps), "-an", str(destino)])
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=segundos + 120, errors="replace")
    if r.returncode != 0 or not destino.exists() or destino.stat().st_size == 0:
        destino.unlink(missing_ok=True)
        return {"erro": "nao consegui capturar a fonte viva: " + ((r.stderr or "").strip().splitlines() or ["sem detalhe"])[-1][:200]}
    s = sonda(str(destino))
    return {"ok": True, "arquivo": str(destino), "nome": destino.name, "tipo": tipo,
            "dispositivo": (dispositivo or DISPOSITIVO_PADRAO) if tipo == "camera" else "testsrc2",
            "segundos": round(time.time() - t0, 1), "resolucao": s.get("resolucao"), "fps": s.get("fps"),
            "mb": round(destino.stat().st_size / 1e6, 2), "bitrate_kbps": s.get("bitrate_kbps")}


def ao_vivo(*, tipo: str = "camera", dispositivo: str | None = None, resolucao: str = "1920x1080",
            fps: int = 30, rotulo: str | None = None, fluxo_id: str | None = None, bitrate: str = "auto",
            embarcacao_id: str = "bancada", srt_host: str = "127.0.0.1", srt_port: int = 8890) -> dict:
    """""Envio CONTINUO de uma fonte viva (webcam do notebook ou fonte sintetica), igual a operacao.

    Sem duracao determinada e sem laço de arquivo: o ffmpeg le a camera e publica em SRT ate
    alguem parar. A imagem e a REAL da webcam (nao ha clipe, nao ha tela preta sintetizada).
    """
    if tipo not in ("camera", "sintetica"):
        return {"erro": "fonte ao vivo invalida: use 'camera' (webcam) ou 'sintetica'"}
    if tipo == "camera" and not (dispositivo or "").strip():
        disp = listar_dispositivos()
        dispositivo = disp.get("padrao_seletor") or disp.get("padrao") or DISPOSITIVO_PADRAO
    if tipo == "camera":
        # identidade pelo seletor unico (@device_pnp_...), nunca pelo nome amigavel: e' o que
        # permite DUAS cameras USB iguais conviverem (a 2a deixava de ser recusada como duplicata)
        dispositivo = _normalizar_dispositivo(dispositivo)
    nome = (rotulo or "").strip() or ("webcam do notebook" if tipo == "camera" else "teste sintetico")
    # a webcam do Windows (dshow) so abre UMA vez: dois envios da mesma camera brigam pelo dispositivo
    # e o segundo fica com quadro preto. Melhor recusar com recado claro do que pintar tela preta.
    if tipo == "camera":
        # a webcam sempre volta sozinha: se algum processo anterior ficou preso segurando o
        # dispositivo (a rede caiu e o ffmpeg nao soltou a camera), libera ANTES de abrir de novo.
        livre = liberar_camera(dispositivo)
        if livre.get("liberados"):
            print(f"[envios] liberei a webcam \"{livre['dispositivo']}\": {livre['liberados']} processo(s) parado(s)",
                  flush=True)
        ocupado = _camera_em_uso(dispositivo)
        if ocupado:
            return {"erro": (f'a webcam "{dispositivo}" ja esta em uso pelo fluxo "{ocupado["rotulo"]}" '
                             f'(id {ocupado["id"]}). Pare esse envio antes de transmitir de novo.'),
                    "ocupada_por": ocupado}
    slug_vivo = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", nome.lower())).strip("-")[:30].strip("-")
    ident = fluxo_id or f"vivo-{slug_vivo or tipo}"
    # ajuste que VAI para o ar (mesma regra do iniciar); a medicao precisa ser do mesmo ajuste
    alvo_vivo = str(bitrate or "auto")
    if alvo_vivo in ("", "auto"):
        alvo_vivo = ("3000k" if tipo == "camera" else alvo_automatico(None))
    # Mede a QUALIDADE (SSIM) do MESMO ajuste antes de entrar no ar: a fonte ainda esta livre e a
    # tela mostra o numero com a hora. Se a medicao falhar, o envio segue — qualidade e informacao,
    # nao pode impedir a operacao.
    try:
        import qualidade as _qualidade  # import tardio: qualidade tambem usa a ingestao
        m = _qualidade.medir_se_preciso(ident, validade_s=600, segundos=8, bitrate=alvo_vivo)
        if m.get("ok") and m.get("ssim") is not None:
            extra = " (medicao reaproveitada)" if m.get("pulado") else f" em {m.get('segundos')}s ajuste {m.get('ajuste')}"
            print(f"[qualidade] {ident}: SSIM {m.get('ssim')}{extra}", flush=True)
        else:
            print(f"[qualidade] {ident}: nao medida: {m.get('erro')}", flush=True)
    except Exception as e:
        print(f"[qualidade] {ident}: nao medida ({type(e).__name__}: {e})", flush=True)
    return iniciar(f"live:{tipo}", rotulo=nome, fluxo_id=ident,
                   bitrate=bitrate, tipo=tipo, repetir=False, dispositivo=dispositivo, resolucao=resolucao,
                   fps=fps, embarcacao_id=embarcacao_id, srt_host=srt_host, srt_port=srt_port)


def liberar_camera(dispositivo: str | None = None, espera: float = 1.5) -> dict:
    """Solta a webcam: mata quem estiver segurando o dispositivo (no Windows o dshow abre UMA vez).

    Caso real que motivou isto: a rede caiu, o ffmpeg ficou preso com o soquete SRT morto e
    continuou segurando a camera — o envio seguinte respondia "camera em uso" e a camera
    so voltava desligando e ligando na mao. Aqui ela volta sozinha, sem ninguem mexer no cabo.
    """
    nome = _normalizar_dispositivo(dispositivo or DISPOSITIVO_PADRAO)
    if os.name != "nt" or not nome:
        return {"dispositivo": nome, "liberados": 0, "pids": []}
    # o seletor @device_pnp_... tem ? e # (curingas do -like): [ ] precisam de escape literal
    literal = nome.replace("[", "[[]").replace("]", "[]]")
    alvo = "*video=" + literal + "*"
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine "
          "-and $_.CommandLine -like '" + alvo + "' } | ForEach-Object { try { Stop-Process -Id "
          "$_.ProcessId -Force -ErrorAction Stop; $_.ProcessId } catch {} }")
    pids: list[int] = []
    try:
        bruto = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=30).stdout
        pids = [int(x) for x in (bruto or b"").decode("utf-8", "ignore").split() if x.strip().isdigit()]
    except Exception:
        pids = []
    if pids:
        time.sleep(espera)  # o Windows leva um instante para soltar o dispositivo apos o kill
    return {"dispositivo": nome, "liberados": len(pids), "pids": pids}


def _camera_em_uso(dispositivo: str | None, validade_s: int = 12) -> dict | None:
    """Diz se algum envio VIVO ainda esta segurando a mesma webcam (dshow nao compartilha o dispositivo)."""
    alvo = f"dshow:{_normalizar_dispositivo(dispositivo or DISPOSITIVO_PADRAO)}"
    with conexao() as c:
        for r in c.execute("""SELECT id, fluxo_id, rotulo, estado, atualizado_em, fonte, pid FROM ingestoes
                              WHERE tipo='camera' AND fonte=? ORDER BY id DESC LIMIT 10""", (alvo,)):
            d = dict(r)
            if d["estado"] not in ("no_ar", "no ar", "iniciando"):
                continue
            # o processo tem que estar VIVO: depois de reiniciar a API o registro fica 'no_ar' mas o
            # ffmpeg morreu junto, e sem isso a camera parecia ocupada para sempre.
            if not _processo_vivo(d.get("pid")):
                continue
            try:
                idade = time.time() - dt.datetime.fromisoformat(d["atualizado_em"]).timestamp()
            except Exception:
                idade = 0
            if idade <= validade_s:
                return d
    return None


def _processo_vivo(pid) -> bool:
    if not pid:
        return False
    try:
        # texto=False + decodificacao tolerante: a saida do tasklist neste Windows vem na pagina
        # OEM (cp850/cp1252) e o text=True levantava UnicodeDecodeError numa thread interna,
        # sujando o log a cada chamada.
        bruto = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
                               capture_output=True, timeout=5).stdout
        saida = (bruto or b"").decode("utf-8", "ignore") or (bruto or b"").decode("cp850", "ignore")
        return str(int(pid)) in saida
    except Exception:
        try:
            os.kill(int(pid), 0)
            return True
        except OSError:
            return False


def limpar_vivos_mortos() -> int:
    """Marca como parado o envio que ficou 'no_ar' mas cujo ffmpeg morreu (ex.: reinicio da API).

    Sem isso a camera parecia ocupada para sempre e o proximo envio era recusado sem motivo real.
    """
    n = 0
    with conexao() as c:
        # .fetchall() ANTES de escrever: ler e escrever na MESMA conexao com o cursor aberto
        # faz o SQLite tentar subir de leitura para escrita e devolver 'database is locked'
        # na hora, sem respeitar o busy_timeout — era isso que derrubava a API no boot.
        linhas = c.execute("""SELECT id, pid, rotulo FROM ingestoes
                               WHERE estado IN ('no_ar','no ar','iniciando')""").fetchall()
        for r in linhas:
            if not _processo_vivo(r["pid"]):
                c.execute("""UPDATE ingestoes SET estado='erro',
                             erro=COALESCE(erro,'o envio caiu quando o servico foi reiniciado'),
                             atualizado_em=? WHERE id=?""", (agora(), r["id"]))
                n += 1
    if n:
        print(f"[envios] {n} envio(s) vivo(s) marcados como parados no inicio (processo morto)", flush=True)
    return n


def _sondar_publicado(ident: int, fluxo_id: str) -> None:
    """Corrige a resolucao/fps do fluxo vivo com o que o mediamtx REALMENTE publicou.

    Sem isso a linha guardava o NOME do dispositivo no lugar da resolucao, e o bruto equivalente
    (usado para dizer compressao e banda economizada) ficava sem base de calculo.
    """
    for espera in (3, 3, 4, 5, 6, 8, 10):
        time.sleep(espera)
        try:
            saida = subprocess.run([caminho_ffprobe(), "-v", "error", "-select_streams", "v:0",
                                    "-show_entries", "stream=width,height,avg_frame_rate", "-of", "json",
                                    f"rtsp://127.0.0.1:8554/{fluxo_id}"],
                                   capture_output=True, text=True, timeout=15).stdout
            st = (json.loads(saida or "{}").get("streams") or [{}])[0]
            if not (st.get("width") and st.get("height")):
                continue
            fps = None
            taxa = st.get("avg_frame_rate") or ""
            if "/" in taxa and taxa != "0/0":
                cima, _, baixo = taxa.partition("/")
                try:
                    fps = round(float(cima) / float(baixo or 1), 2)
                except Exception:
                    fps = None
            with conexao() as c:
                c.execute("UPDATE ingestoes SET resolucao=?, fps_nativo=COALESCE(?, fps_nativo) WHERE id=?",
                          (f"{st['width']}x{st['height']}", fps, ident))
            print(f"[envios] {fluxo_id}: resolucao publicada {st['width']}x{st['height']}@{fps} fps", flush=True)
            return
        except Exception:
            continue
