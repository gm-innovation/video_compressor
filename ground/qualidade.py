#!/usr/bin/env python3
"""Qualidade do video que esta no ar (SSIM), medida com a fonte real.

O SSIM exige o ORIGINAL e o COMPRIMIDO lado a lado. Num fluxo vivo a fonte (webcam/dshow) aceita
UM processo por vez, entao a medicao abre a fonte UMA vez e divide os quadros em dois ramos com o
filtro `split` do ffmpeg:

- ramo A: o MESMO ajuste que o fluxo usa na rede (`libx264 -b:v <alvo> ...`, o bitrate registrado);
- ramo B: gravacao SEM PERDA (`libx264 -qp 0`) — e' o original reconstruido exatamente.

O SSIM entre B (original) e A (o que vai na rede) e' a qualidade que o cliente recebe. Como a fonte
fica ocupada durante a medicao (8 s), ela roda com o fluxo PARADO; com a webcam em uso a funcao
recusa dizendo qual fluxo esta segurando o dispositivo.

O resultado fica em `medicoes_qualidade`, com o ajuste usado e a hora — a tela mostra o numero com
a idade, porque qualidade so vale junto com "medida quando".
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(os.path.dirname(os.path.abspath(__file__))))
import ingestao  # noqa: E402
from etapas import PISO_QUALIDADE_ACEITO, PISO_QUALIDADE_SSIM, medir_ssim_amostra  # noqa: E402
from producao import FUSO, agora, conexao_banco  # noqa: E402

SEGUNDOS_PADRAO = 8.0


def garantir_tabela() -> None:
    """Tabela das medicoes de qualidade. Idempotente: pode chamar em toda requisicao."""
    with conexao_banco() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS medicoes_qualidade (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fluxo_id TEXT NOT NULL, ssim REAL, ajuste TEXT, res_coluna TEXT,
                        resolucao TEXT, fps REAL, segundos REAL, mb_alvo REAL, mb_original REAL,
                        compressao_pct REAL, fonte TEXT, medido_em TEXT NOT NULL)""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_qualidade_fluxo ON medicoes_qualidade (fluxo_id, id)")


def _fonte_args(d: dict) -> list[str]:
    """Argumentos de entrada do ffmpeg para a MESMA fonte do fluxo (dshow, gerador ou arquivo)."""
    tipo = (d.get("tipo") or "").lower()
    fonte = d.get("fonte") or ""
    res = d.get("resolucao") or "1280x720"
    fps = int(d.get("fps") or d.get("fps_nativo") or 30)
    if tipo == "camera" or fonte.startswith("dshow:"):
        disp = fonte.split(":", 1)[1] if fonte.startswith("dshow:") else ingestao.DISPOSITIVO_PADRAO
        return ingestao._args_fonte_viva("camera", disp, res, fps)
    if tipo == "sintetica" or fonte.startswith("lavfi:"):
        return ingestao._args_fonte_viva("sintetica", None, res, fps)
    return ["-re", "-i", fonte]


sys.path.insert(0, str(Path(__file__).resolve().parent))
from ferramentas import caminho_ffmpeg  # noqa: E402


def _comando(d: dict, segundos: float, alvo_arq: Path, original_arq: Path,
             bitrate: str | None = None) -> list[str]:
    alvo = str(bitrate or d.get("bitrate_alvo") or "1500k")
    fps = int(d.get("fps") or d.get("fps_nativo") or 30)
    codec = str(d.get("codec") or "libx264")
    return ([caminho_ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "warning", "-y"]
            + _fonte_args(d)
            + ["-filter_complex", "[0:v]split=2[a][b]"]
            # ramo A: o MESMO ajuste que o fluxo usa na rede — vem do mesmo lugar que o ffmpeg do
            # envio usa (ingestao.ajuste_encode): se os dois divergirem, o SSIM mede outro encoder
            + ["-map", "[a]", "-t", str(segundos)]
            + ingestao.ajuste_encode(alvo, fps, codec)
            + ["-an", str(alvo_arq)]
            # ramo B: o original reconstruido SEM PERDA (x264 -qp 0 e' matematicamente exato)
            + ["-map", "[b]", "-t", str(segundos), "-c:v", "libx264", "-preset", "ultrafast",
               "-qp", "0", "-pix_fmt", "yuv420p", "-an", str(original_arq)])


def medir(fluxo_id: str, segundos: float = SEGUNDOS_PADRAO, bitrate: str | None = None,
          dados: dict | None = None) -> dict:
    """Mede o SSIM do ajuste ATUAL do fluxo contra o original sem perda. Guarda e devolve o numero.

    `bitrate` mede outro ajuste sem mudar o fluxo (e' assim que se escolhe o alvo do lado vivo: o
    menor bitrate que ainda passa do piso de qualidade). `dados` e' a fonte a usar quando o fluxo
    AINDA NAO esta' no banco — e' o caso do envio ao vivo: a medicao roda ANTES de subir o ffmpeg (a
    fonte precisa estar livre), e antes disso nenhuma linha existe em `ingestoes`. Sem isso a medicao
    do primeiro envio respondia "fluxo nao encontrado" e o dono ficava SEM SSIM do fluxo ao vivo.
    """
    garantir_tabela()
    with conexao_banco() as c:
        r = c.execute("""SELECT * FROM ingestoes WHERE fluxo_id=?
                         ORDER BY CASE estado WHEN 'no_ar' THEN 0 WHEN 'no ar' THEN 0 ELSE 1 END, id DESC
                         LIMIT 1""", (fluxo_id,)).fetchone()
    if not r and not dados:
        return {"erro": f"fluxo nao encontrado: {fluxo_id}"}
    d = dict(r) if r else dict(dados or {})
    ocupado = _quem_segura(d)
    if ocupado:
        return {"erro": (f'a fonte do fluxo "{fluxo_id}" esta em uso por "{ocupado.get("rotulo")}" '
                         f'(id {ocupado.get("id")}): a medicao precisa da fonte livre. Pare o envio, '
                         f'meça e ligue de novo.'),
                "ocupada_por": ocupado, "fluxo_id": fluxo_id}
    segundos = max(4.0, min(30.0, float(segundos or SEGUNDOS_PADRAO)))
    pasta = Path(tempfile.mkdtemp(prefix="qualidade-"))
    alvo_arq, original_arq = pasta / "alvo.mp4", pasta / "original.mkv"
    try:
        cmd = _comando(d, segundos, alvo_arq, original_arq, bitrate=bitrate)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=segundos + 180, errors="replace")
        if p.returncode != 0 or not alvo_arq.exists() or not original_arq.exists():
            ultima = ((p.stderr or "").strip().splitlines() or ["sem detalhe"])[-1][:240]
            return {"erro": f"nao consegui medir a qualidade: {ultima}", "fluxo_id": fluxo_id}
        ssim = medir_ssim_amostra(str(original_arq), str(alvo_arq), segundos, fps=int(d.get("fps") or 30))
        mb_alvo = round(alvo_arq.stat().st_size / 1e6, 2)
        mb_orig = round(original_arq.stat().st_size / 1e6, 2)
        compressao = round((1 - mb_alvo / mb_orig) * 100, 2) if mb_orig else None
    finally:
        for f in (alvo_arq, original_arq):
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            pasta.rmdir()
        except Exception:
            pass
    if ssim is None:
        return {"erro": "a medicao rodou mas o ffmpeg nao devolveu o SSIM", "fluxo_id": fluxo_id}
    quando = agora()
    with conexao_banco() as c:
        c.execute("""INSERT INTO medicoes_qualidade (fluxo_id, ssim, ajuste, resolucao, fps, segundos,
                     mb_alvo, mb_original, compressao_pct, fonte, medido_em)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                  (fluxo_id, ssim, str(bitrate or d.get("bitrate_alvo") or ""), d.get("resolucao"),
                   d.get("fps") or d.get("fps_nativo"), segundos, mb_alvo, mb_orig, compressao,
                   d.get("fonte"), quando))
    medicao = {"fluxo_id": fluxo_id, "ssim": ssim, "ajuste": str(bitrate or d.get("bitrate_alvo") or ""),
               "resolucao": d.get("resolucao"), "fps": d.get("fps") or d.get("fps_nativo"),
               "segundos": segundos, "mb_alvo": mb_alvo, "mb_original": mb_orig,
               "compressao_pct": compressao, "fonte": d.get("fonte"), "medido_em": quando}
    # o numero sobe para o lado terra junto do cadastro: o SSIM e' medido aqui (na maquina que tem a
    # fonte) e a tela do lado terra mostra a idade da medicao. Best-effort: medir e' informacao.
    recado = ""
    try:
        import repasse
        r = repasse.publicar_qualidade(medicao, destino=f"{d.get('srt_host') or ''}:{d.get('srt_port') or ''}"
                                       if d.get("srt_host") else None)
        recado = ("medicao publicada no lado terra" if r.get("ok")
                  else f"o lado terra ainda NAO tem esta medicao ({r.get('motivo') or r.get('erro')})")
    except Exception as e:
        recado = f"nao publiquei a medicao no lado terra ({type(e).__name__}: {e})"
    print(f"[qualidade] {fluxo_id}: {recado}", flush=True)
    return {"ok": True, "fluxo_id": fluxo_id, "ssim": ssim, "piso": PISO_QUALIDADE_SSIM,
            "piso_aceito": PISO_QUALIDADE_ACEITO, "passa": bool(ssim >= PISO_QUALIDADE_ACEITO),
            "ajuste": str(bitrate or d.get("bitrate_alvo") or ""), "resolucao": d.get("resolucao"),
            "segundos": segundos, "mb_alvo": mb_alvo, "mb_original": mb_orig,
            "compressao_pct": compressao, "medido_em": quando, "lado_terra": recado,
            "explica": ("o original do ramo sem perda tem o mesmo conteudo que o ramo que vai na rede: "
                        "o SSIM mede o que o cliente recebe")}


def _nitidez(caminho: str, segundos: float) -> float | None:
    """Nitidez do clipe sem referencia (blurdetect do ffmpeg): quanto MAIOR, mais borrado.

    Serve para comparar duas imagens da MESMA cena quando nao ha como ter SSIM (o SSIM exige o
    original): foi assim que se mediu que a cam-02 chegava mais borrada que a cam-01 no mesmo bitrate.
    """
    cmd = [caminho_ffmpeg(), "-hide_banner", "-nostats", "-i", caminho, "-t", str(segundos),
           "-vf", "blurdetect", "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=segundos + 180, errors="replace")
    except Exception:
        return None
    m = re.findall(r"blur mean:\s*([0-9.]+)", (r.stderr or "") + (r.stdout or ""))
    return round(float(m[-1]), 4) if m else None


def comparar_alvos(fluxo_id: str, alvos: Sequence[str] = ("1500k", "2500k", "4000k"),
                   segundos: float = 6.0, pasta_saida: str | None = None) -> dict:
    """Grava a MESMA cena em varios alvos e devolve SSIM + nitidez de cada um.

    E' o teste que transforma "a cam-02 esta perdendo qualidade" em numero: a fonte e' aberta UMA vez
    e dividida em ramos (um por alvo) + um ramo SEM PERDA, que e' a referencia. Os clipes ficam numa
    pasta para o dono ver lado a lado e apontar qual alvo "ainda serve" — o numero sozinho nao decide.
    """
    garantir_tabela()
    with conexao_banco() as c:
        r = c.execute("SELECT * FROM ingestoes WHERE fluxo_id=? ORDER BY id DESC LIMIT 1", (fluxo_id,)).fetchone()
    if not r:
        return {"erro": f"fluxo nao encontrado: {fluxo_id}"}
    d = dict(r)
    ocupado = _quem_segura(d)
    if ocupado:
        return {"erro": f'a fonte de "{fluxo_id}" esta em uso por "{ocupado.get("rotulo")}": pare o envio para comparar',
                "ocupada_por": ocupado}
    alvos = [str(a) for a in alvos if str(a or "").strip()]
    if not alvos:
        return {"erro": "informe pelo menos um alvo (ex.: 1500k)"}
    segundos = max(4.0, min(30.0, float(segundos or 6.0)))
    fps = int(d.get("fps") or d.get("fps_nativo") or 30)
    pasta = Path(pasta_saida) if pasta_saida else Path(tempfile.mkdtemp(prefix="comparar-alvos-"))
    pasta.mkdir(parents=True, exist_ok=True)
    original = pasta / "original-sem-perda.mkv"
    # um ramo por alvo + o ramo sem perda: a fonte (webcam/gerador) abre UMA vez so'
    rotulos = [f"a{i}" for i in range(len(alvos))]
    mapa = "".join(f"[{x}]" for x in rotulos) + "[o]"
    cmd = ([caminho_ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "warning", "-y"]
           + _fonte_args(d)
           + ["-filter_complex", f"[0:v]split={len(alvos) + 1}{mapa}"])
    for rotulo, alvo in zip(rotulos, alvos):
        clipe = pasta / f"alvo-{re.sub(r'[^0-9a-zA-Z]', '', alvo)}.mp4"
        cmd += ["-map", f"[{rotulo}]", "-t", str(segundos)] + ingestao.ajuste_encode(alvo, fps, str(d.get("codec") or "libx264")) + ["-an", str(clipe)]
    cmd += ["-map", "[o]", "-t", str(segundos), "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0",
            "-pix_fmt", "yuv420p", "-an", str(original)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=segundos * len(alvos) + 240,
                           errors="replace")
        if p.returncode != 0 or not original.exists():
            return {"erro": "nao consegui comparar os alvos: "
                            + ((p.stderr or "").strip().splitlines() or ["sem detalhe"])[-1][:240]}
    except Exception as e:
        return {"erro": f"nao consegui comparar os alvos ({type(e).__name__}: {e})"}
    linhas = []
    for alvo in alvos:
        clipe = pasta / f"alvo-{re.sub(r'[^0-9a-zA-Z]', '', alvo)}.mp4"
        if not clipe.exists():
            linhas.append({"alvo": alvo, "erro": "clipe nao gravado"})
            continue
        linhas.append({"alvo": alvo,
                       "ssim": medir_ssim_amostra(str(original), str(clipe), segundos, fps=fps),
                       "nitidez_blur": _nitidez(str(clipe), segundos),
                       "mb": round(clipe.stat().st_size / 1e6, 2),
                       "clipe": str(clipe)})
    csv = pasta / "comparacao.csv"
    csv.write_text("alvo,ssim,nitidez_blur,mb,clipe\n" + "\n".join(
        f"{x.get('alvo')},{x.get('ssim')},{x.get('nitidez_blur')},{x.get('mb')},{x.get('clipe')}"
        for x in linhas), encoding="utf-8")
    return {"ok": True, "fluxo_id": fluxo_id, "pasta": str(pasta), "csv": str(csv),
            "original": str(original), "alvos": linhas,
            "medido_em": agora(),
            "explica": ("mesma cena e mesma fonte em todos os alvos: o ramo 'original-sem-perda' e' a "
                        "referencia do SSIM. 'nitidez_blur' e' a nitidez sem referencia (maior = mais "
                        "borrado). O alvo escolhido aqui e' o que a tela grava na camera.")}


def _quem_segura(d: dict) -> dict | None:
    """Devolve o fluxo que esta segurando a fonte (so a camera/dshow e' exclusiva)."""
    if (d.get("tipo") or "") != "camera" and not str(d.get("fonte") or "").startswith("dshow:"):
        return None
    with conexao_banco() as c:
        for r in c.execute("""SELECT id, fluxo_id, rotulo, pid, estado FROM ingestoes
                              WHERE estado IN ('no_ar','no ar') ORDER BY id DESC LIMIT 40"""):
            x = dict(r)
            if x.get("pid") and ingestao._processo_vivo(int(x["pid"])):
                return x
    return None


def ultima(fluxo_id: str) -> dict | None:
    garantir_tabela()
    with conexao_banco() as c:
        r = c.execute("""SELECT * FROM medicoes_qualidade WHERE fluxo_id=?
                         ORDER BY id DESC LIMIT 1""", (fluxo_id,)).fetchone()
    return dict(r) if r else None


def medir_se_preciso(fluxo_id: str, validade_s: float = 600.0, segundos: float = SEGUNDOS_PADRAO,
                     bitrate: str | None = None, dados: dict | None = None) -> dict:
    """Mede se a ultima medicao estiver velha OU se for de outro ajuste (usada ao subir o envio).

    Comparar o ajuste importa: se o bitrate mudou, o SSIM antigo nao vale mais para o fluxo que
    vai entrar no ar. `dados` descreve a fonte quando o fluxo ainda nao esta' no banco (envio ao vivo).
    """
    from datetime import datetime
    u = ultima(fluxo_id)
    if u and u.get("medido_em"):
        try:
            idade = (datetime.now(FUSO) - datetime.fromisoformat(u["medido_em"])).total_seconds()
            mesmo_ajuste = (bitrate is None) or (str(u.get("ajuste") or "") == str(bitrate))
            if idade < validade_s and mesmo_ajuste:
                return {"ok": True, "pulado": True, "ssim": u["ssim"], "medido_em": u["medido_em"],
                        "idade_s": round(idade, 1), "ajuste": u.get("ajuste")}
        except Exception:
            pass
    return medir(fluxo_id, segundos=segundos, bitrate=bitrate, dados=dados)
