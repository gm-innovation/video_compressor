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
import datetime as dt
import argparse, json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from entrada import entrada_teorica_kbps as _entrada_teorica_kbps, origem_da_entrada as _origem_da_entrada  # noqa: E402

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


# Piso travado pelo dono (09/11/2026): nada abaixo disto e aceito.
PISO_COMPRESSAO_PCT = 73.0     # economia minima de banda (firme)
PISO_QUALIDADE_SSIM = 0.9733   # semelhanca nominal pedida pelo dono
MARGEM_QUALIDADE_SSIM = 0.002  # margem: 0,9720 e' aceitavel quando a compressao melhora
PISO_QUALIDADE_ACEITO = round(PISO_QUALIDADE_SSIM - MARGEM_QUALIDADE_SSIM, 4)  # 0,9713
CRFS_TESTADOS = (36, 34, 32, 30, 28, 26)


def _encode(fonte: str, saida: Path, *, kb: int | None = None, crf: int | None = None, fps: int = 30,
            codec: str = "libx264", fonte2: str | None = None, audio: bool = False,
            duracao_amostra: float | None = None, preset: str = "medium",
            inicio: float = 0.0) -> float:
    """Uma passada de encode. kb = alvo de bitrate; crf = qualidade (o x264 escolhe o bitrate)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning", "-y"]
    if inicio:
        cmd += ["-ss", str(inicio)]
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


def escolher_crf(fonte: str, *, fps: int = 30, pasta: Path | None = None, fonte2: str | None = None,
                 tolerancia: float = 0.005) -> dict:
    """CRF de partida: o maior CRF (menos banda) cuja qualidade fica dentro da tolerancia do melhor
    SSIM medido numa amostra curta do MEIO do video (o comeco costuma ser mais duro que a media)."""
    pasta = pasta or COMPRIMIDOS
    pasta.mkdir(parents=True, exist_ok=True)
    ent = info(fonte)
    dur = ent.get("duracao_s") or 20
    amostra = min(15.0, max(5.0, dur / 5))
    inicio = max(0.0, dur * 0.4) if dur > amostra * 2.5 else 0.0
    tentativas = []
    for crf in CRFS_TESTADOS:
        saida = pasta / f"_amostra-crf{crf}.mp4"
        try:
            seg = _encode(fonte, saida, crf=crf, fps=fps, fonte2=fonte2, duracao_amostra=amostra, inicio=inicio)
        except RuntimeError as e:
            tentativas.append({"crf": crf, "erro": str(e)[:120]})
            continue
        ssim = medir_ssim_amostra(fonte, str(saida), amostra, fps=fps, inicio=inicio)
        tentativas.append({"crf": crf, "ssim": ssim,
                           "bitrate_kbps": round(saida.stat().st_size * 8 / amostra / 1000, 1),
                           "segundos_amostra": seg, "inicio_s": round(inicio, 1)})
        saida.unlink(missing_ok=True)
    validas = [x for x in tentativas if x.get("ssim") is not None]
    if not validas:
        return {"crf": 32, "tolerancia": tolerancia, "tentativas": tentativas,
                "motivo": "nao consegui medir a amostra: usei CRF 32 de partida"}
    melhor = max(validas, key=lambda x: x["ssim"])
    dentro = [x for x in validas if x["ssim"] >= melhor["ssim"] - tolerancia]
    escolhido = max(dentro, key=lambda x: x["crf"])
    return {"crf": escolhido["crf"], "tolerancia": tolerancia, "amostra_s": round(amostra, 1),
            "inicio_s": round(inicio, 1), "tentativas": tentativas, "escolhido": escolhido,
            "melhor_ssim": melhor["ssim"],
            "motivo": f"ponto de partida: maior CRF dentro de {tolerancia} do melhor SSIM da amostra"}


def medir_ssim_amostra(original: str, comprimido: str, segundos: float, fps: int = 30,
                       inicio: float = 0.0) -> float | None:
    # o -ss vai ANTES do segundo -i: e o original que precisa comecar na mesma janela da amostra
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info", "-i", comprimido]
                        + (["-ss", str(inicio)] if inicio else []) +
                        ["-i", original, "-t", str(segundos),
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
        porta = {"piso_compressao_pct": PISO_COMPRESSAO_PCT, "piso_ssim": PISO_QUALIDADE_SSIM}
        crf = busca.get("crf")
        if crf is None:
            kb = _kbps(alvo_automatico(ent.get("bitrate_kbps")) if (not alvo or alvo == "auto") else alvo)
    elif str(qualidade).startswith("crf"):
        crf = int(re.sub(r"[^0-9]", "", qualidade) or 28)
    base = re.sub(r"[^a-zA-Z0-9]+", "-", (nome or Path(str(origem)).stem or "comprimido")).strip("-")
    dur = ent.get("duracao_s") or 0
    tentativas_pisos = []

    def _tenta(crf_t, kb_t):
        marca = f"crf{crf_t}" if crf_t is not None else f"{kb_t}k"
        alvo_arq = COMPRIMIDOS / f"{base}-{marca}-{fps}fps.mp4"
        seg_t = _encode(fonte, alvo_arq, kb=kb_t, crf=crf_t, fps=fps, codec=codec, fonte2=fonte2, audio=audio)
        comp_t = info(str(alvo_arq))
        corte_t = round((1 - comp_t["bytes"] / ent["bytes"]) * 100, 2) if ent.get("bytes") else None
        ssim_t = medir_ssim(fonte, str(alvo_arq), dur, fps=fps)
        passar, _motivos = passa_pisos(corte_t, ssim_t)
        tentativas_pisos.append({"crf": crf_t, "kb": kb_t, "mb": round(comp_t["bytes"] / 1e6, 2),
                                 "bitrate_kbps": comp_t.get("bitrate_kbps"), "corte_pct": corte_t,
                                 "ssim": ssim_t, "segundos": seg_t, "passa": passar})
        return alvo_arq, comp_t, corte_t, ssim_t, seg_t, passar

    # o dono travou os pisos: mede o ARQUIVO INTEIRO e, se nao bateu, desce o CRF degrau a degrau
    # (a amostra nao decide isso sozinha: ela e' mais otimista que a media do video)
    candidatos, escolhida = ([crf] if crf is None else [crf, crf - 1, crf - 2, crf - 3]), None
    for c in candidatos:
        saida_c, comp_c, corte_c, ssim_c, seg_c, passa_c = _tenta(c, kb)
        if passa_c:
            escolhida = (c, saida_c, comp_c, corte_c, ssim_c, seg_c, passa_c)
            break
        if escolhida is None:
            escolhida = (c, saida_c, comp_c, corte_c, ssim_c, seg_c, passa_c)
        else:
            # preferencia: quem mantem o piso de qualidade e comprime mais; se nenhum mantem, a melhor imagem
            melhor_ssim = escolhida[4] if escolhida[4] is not None else 0
            if ((ssim_c or 0) >= PISO_QUALIDADE_ACEITO and (corte_c or 0) > (escolhida[3] or 0)) or \
               ((ssim_c or 0) < PISO_QUALIDADE_ACEITO and (ssim_c or 0) > melhor_ssim):
                escolhida = (c, saida_c, comp_c, corte_c, ssim_c, seg_c, passa_c)
    # arquivo que fica: o da tentativa escolhida (as outras somem)
    for tt in tentativas_pisos:
        if tt["crf"] != escolhida[0]:
            (COMPRIMIDOS / f"{base}-crf{tt['crf']}-{fps}fps.mp4").unlink(missing_ok=True)
    crf, saida, comp, corte, ssim, segundos, passa = escolhida
    bo, bc = ent.get("bytes"), comp.get("bytes")
    r = {"etapa": "compressao", "ok": True, "arquivo": str(saida), "nome_arquivo": saida.name,
         "crf": crf, "fps": fps, "codec": codec, "qualidade": qualidade,
         "busca_crf": busca, "tentativas_pisos": tentativas_pisos,
         "entrada": {"bytes": bo, "mb": round(bo / 1e6, 2) if bo else None, "bitrate_kbps": ent.get("bitrate_kbps"),
                     "resolucao": ent.get("resolucao"), "fps": ent.get("fps"), "duracao_s": ent.get("duracao_s")},
         "comprimido": {"bytes": bc, "mb": round(bc / 1e6, 2) if bc else None, "bitrate_kbps": comp.get("bitrate_kbps"),
                        "resolucao": comp.get("resolucao"), "fps": comp.get("fps")},
         "corte_pct": corte, "tempo_encode_s": segundos,
         "velocidade_x": round(dur / segundos, 2) if segundos and dur else None, "ssim": ssim}
    # portoes do dono: economia minima de banda E qualidade minima
    r["piso_compressao_pct"] = PISO_COMPRESSAO_PCT
    r["piso_ssim"] = PISO_QUALIDADE_SSIM
    r["piso_ssim_aceito"] = PISO_QUALIDADE_ACEITO
    r["margem_ssim"] = MARGEM_QUALIDADE_SSIM
    r["passa_pisos"] = bool(passa)
    if not r["passa_pisos"]:
        falta = []
        if corte is None or corte < PISO_COMPRESSAO_PCT:
            falta.append(f"compressao {corte}% < {PISO_COMPRESSAO_PCT}%")
        if ssim is None or ssim < PISO_QUALIDADE_ACEITO:
            falta.append(f"qualidade {ssim} < {PISO_QUALIDADE_ACEITO} (nominal {PISO_QUALIDADE_SSIM} com margem de {MARGEM_QUALIDADE_SSIM})")
        r["aviso_pisos"] = "nao atingiu o piso exigido: " + "; ".join(falta)
    if isinstance(busca, dict) and "passa_pisos" in busca:
        r["busca_respeitou_pisos"] = busca["passa_pisos"]
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
            fluxo_id TEXT, publicado_em TEXT, criado_em TEXT, passa_pisos INTEGER,
            piso_comp REAL, piso_ssim REAL)""")
        # bancos antigos: acrescenta as colunas novas
        cols = {l[1] for l in c.execute("PRAGMA table_info(compressoes)")}
        for nome, tipo in (("passa_pisos", "INTEGER"), ("piso_comp", "REAL"), ("piso_ssim", "REAL")):
            if nome not in cols:
                c.execute(f"ALTER TABLE compressoes ADD COLUMN {nome} {tipo}")


def registrar_compressao(r: dict, origem: str) -> int:
    garantir_tabela()
    import datetime as _dt
    with conexao_banco() as c:
        cur = c.execute("""INSERT INTO compressoes (rotulo, arquivo_original, arquivo_saida, mb_entrada, mb_saida,
            bitrate_entrada_kbps, bitrate_saida_kbps, compressao_pct, crf, ssim, fps, segundos_encode,
            velocidade_x, duracao_s, criado_em, passa_pisos, piso_comp, piso_ssim)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (Path(str(origem)).name, origem, r["arquivo"], r["entrada"]["mb"], r["comprimido"]["mb"],
             r["entrada"]["bitrate_kbps"], r["comprimido"]["bitrate_kbps"], r["corte_pct"], r.get("crf"),
             r.get("ssim"), r.get("fps"), r.get("tempo_encode_s"), r.get("velocidade_x"),
             r["entrada"].get("duracao_s"), _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
             1 if r.get("passa_pisos") else 0, r.get("piso_compressao_pct"), r.get("piso_ssim")))
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
    # o arquivo JA esta comprimido: vai para o ar sem re-codificar (o que gastaria banda a toa)
    r = ing_iniciar(str(caminho), rotulo=rotulo or linha.get("rotulo") or caminho.stem,
                    bitrate="copy", repetir=repetir, tipo="arquivo", fps=int(linha.get("fps") or 30),
                    embarcacao_id=embarcacao_id, copiar=True, registrar_camera=False,
                    fluxo_id=f"comp-{ident}")
    if "erro" in r:
        return r
    import datetime as _dt
    with conexao_banco() as c:
        c.execute("UPDATE compressoes SET fluxo_id=?, publicado_em=? WHERE id=?",
                  (r["fluxo_id"], _dt.datetime.now().astimezone().isoformat(timespec="seconds"), ident))
    return {"ok": True, **r}


def passa_pisos(compressao_pct: float | None, ssim: float | None) -> tuple[bool, list[str]]:
    """Os dois portoes do dono, com margem: >=73% de economia e qualidade >=0,9733 - margem.

    A compressao e' piso firme (banda); a qualidade aceita a margem de proposito: 0,9720 esta
    dentro do ruido de medicao e nao justifica recusar uma compressao de 78% (pedido do dono).
    """
    falta = []
    if compressao_pct is None or compressao_pct < PISO_COMPRESSAO_PCT:
        falta.append(f"compressao {compressao_pct}% < {PISO_COMPRESSAO_PCT}%")
    if ssim is None or ssim < PISO_QUALIDADE_ACEITO:
        falta.append(f"qualidade {ssim} < {PISO_QUALIDADE_ACEITO} "
                     f"(nominal {PISO_QUALIDADE_SSIM} com margem de {MARGEM_QUALIDADE_SSIM})")
    return (not falta), falta


def metricas_ao_vivo() -> dict:
    """Numeros do streaming AGORA: compressao, velocidade de envio, banda consumida e economizada.

    Fonte: o proprio remetente. O ffmpeg de envio publica o -progress e a ingestao grava taxa, fps,
    total enviado e tempo no ar na linha da ingestao 1x por segundo (coluna `atualizado_em` diz se o
    envio esta vivo agora). A entrada vem da fonte original: do registro da compressao quando o fluxo
    saiu de um arquivo comprimido, senao do proprio registro de ingestao.
    """
    agora = time.time()
    with conexao_banco() as c:
        linhas, vistas = [], set()
        # inclui o envio que FALHOU nos ultimos minutos: o operador precisa ver o motivo, nao so o silencio
        corte_erro = (dt.datetime.now().astimezone() - dt.timedelta(minutes=10)).isoformat(timespec="seconds")
        for r in c.execute("""SELECT * FROM ingestoes
                               WHERE estado IN ('no_ar','no ar')
                                  OR (estado='erro' AND atualizado_em >= ?)
                               ORDER BY id DESC LIMIT 60""", (corte_erro,)):
            d = dict(r)
            if d["fluxo_id"] in vistas:
                continue
            vistas.add(d["fluxo_id"])
            linhas.append(d)
        originais = {x["fluxo_id"]: dict(x) for x in c.execute(
            "SELECT fluxo_id, bitrate_entrada_kbps, compressao_pct, ssim, mb_entrada, mb_saida "
            "FROM compressoes WHERE fluxo_id IS NOT NULL")}
    def _segundos(iso):
        try:
            import datetime as _dt
            return agora - _dt.datetime.fromisoformat(iso).timestamp()
        except Exception:
            return None
    fluxos, total = [], {"entrada_mbps": 0.0, "saida_mbps": 0.0, "economia_mbps": 0.0,
                         "mb_enviados": 0.0, "fluxos": 0}
    for d in linhas:
        comp = originais.get(d["fluxo_id"]) or {}
        medida_kbps = comp.get("bitrate_entrada_kbps") or d.get("bitrate_entrada_kbps")
        # fonte crua (webcam/sintetica) nao tem entrada medida: usa o bruto equivalente a resolucao e fps
        entrada_kbps = medida_kbps or _entrada_teorica_kbps(d.get("resolucao"), d.get("fps") or d.get("fps_nativo"))
        entrada = (entrada_kbps or 0) / 1000.0
        saida = (d.get("bitrate_saida_kbps") or 0) / 1000.0
        idade = _segundos(d.get("atualizado_em") or "")
        d.update({
            "entrada_mbps": round(entrada, 3), "saida_mbps": round(saida, 3),
            "economia_mbps": round(max(0.0, entrada - saida), 3),
            "erro": d.get("erro"),
            "entrada_fonte": _origem_da_entrada(d.get("resolucao"), d.get("fps") or d.get("fps_nativo"),
                                                bool(medida_kbps)),
            "compressao_pct": round((1 - saida / entrada) * 100, 2) if (entrada and saida) else None,
            "compressao_arquivo_pct": comp.get("compressao_pct"), "ssim": comp.get("ssim"),
            "mbps_agora": round(saida, 3), "fps_agora": d.get("fps"),
            "mb_enviados": d.get("tamanho_mb"), "segundos_no_ar": d.get("duracao_s"),
            "vivo": bool(idade is not None and idade < 6), "idade_s": round(idade, 1) if idade is not None else None,
        })
        _r = envio(d["fluxo_id"])
        srt = (_r.get("envio") or _r) if isinstance(_r, dict) else {}
        d["perdidos"] = srt.get("pacotes_perdidos"); d["leitores"] = srt.get("readers")
        d["rtt_ms"] = srt.get("rtt_ms")
        fluxos.append(d)
        if d["vivo"]:
            total["entrada_mbps"] += entrada; total["saida_mbps"] += saida
            total["economia_mbps"] += d["economia_mbps"]; total["mb_enviados"] += d.get("tamanho_mb") or 0
            total["fluxos"] += 1
    for k, v in list(total.items()):
        if isinstance(v, float):
            total[k] = round(v, 3)
    total["compressao_pct"] = (round((1 - total["saida_mbps"] / total["entrada_mbps"]) * 100, 2)
                               if total["entrada_mbps"] else None)
    return {"em": _agora(), "fluxos": fluxos, "total": total}


def _agora() -> str:
    import datetime as _dt
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


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


def registrar_ponta_a_ponta(fluxo_id: str, ms: float, caminho: str = "ponta a ponta") -> None:
    """Guarda uma medicao ponta a ponta (relogio queimado lido na tela) para o painel de tempo real."""
    import producao as _prod
    _prod.registrar_latencia(fluxo_id, float(ms), caminho)


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
