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
import subprocess
import sys
import tempfile
from pathlib import Path

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


def _comando(d: dict, segundos: float, alvo_arq: Path, original_arq: Path,
             bitrate: str | None = None) -> list[str]:
    alvo = str(bitrate or d.get("bitrate_alvo") or "1500k")
    fps = int(d.get("fps") or d.get("fps_nativo") or 30)
    codec = str(d.get("codec") or "libx264")
    return (["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning", "-y"]
            + _fonte_args(d)
            + ["-filter_complex", "[0:v]split=2[a][b]"]
            # ramo A: o ajuste que o fluxo usa na rede
            + ["-map", "[a]", "-t", str(segundos), "-c:v", codec, "-preset", "ultrafast",
               "-tune", "zerolatency", "-b:v", alvo, "-maxrate", alvo, "-bufsize", "1M",
               "-r", str(fps), "-g", str(fps), "-pix_fmt", "yuv420p", "-an", str(alvo_arq)]
            # ramo B: o original reconstruido SEM PERDA (x264 -qp 0 e' matematicamente exato)
            + ["-map", "[b]", "-t", str(segundos), "-c:v", "libx264", "-preset", "ultrafast",
               "-qp", "0", "-pix_fmt", "yuv420p", "-an", str(original_arq)])


def medir(fluxo_id: str, segundos: float = SEGUNDOS_PADRAO, bitrate: str | None = None) -> dict:
    """Mede o SSIM do ajuste ATUAL do fluxo contra o original sem perda. Guarda e devolve o numero.

    `bitrate` mede outro ajuste sem mudar o fluxo (e' assim que se escolhe o alvo do lado vivo: o
    menor bitrate que ainda passa do piso de qualidade).
    """
    garantir_tabela()
    with conexao_banco() as c:
        r = c.execute("""SELECT * FROM ingestoes WHERE fluxo_id=?
                         ORDER BY CASE estado WHEN 'no_ar' THEN 0 WHEN 'no ar' THEN 0 ELSE 1 END, id DESC
                         LIMIT 1""", (fluxo_id,)).fetchone()
    if not r:
        return {"erro": f"fluxo nao encontrado: {fluxo_id}"}
    d = dict(r)
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
    return {"ok": True, "fluxo_id": fluxo_id, "ssim": ssim, "piso": PISO_QUALIDADE_SSIM,
            "piso_aceito": PISO_QUALIDADE_ACEITO, "passa": bool(ssim >= PISO_QUALIDADE_ACEITO),
            "ajuste": str(bitrate or d.get("bitrate_alvo") or ""), "resolucao": d.get("resolucao"),
            "segundos": segundos, "mb_alvo": mb_alvo, "mb_original": mb_orig,
            "compressao_pct": compressao, "medido_em": quando,
            "explica": ("o original do ramo sem perda tem o mesmo conteudo que o ramo que vai na rede: "
                        "o SSIM mede o que o cliente recebe")}


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
                     bitrate: str | None = None) -> dict:
    """Mede se a ultima medicao estiver velha OU se for de outro ajuste (usada ao subir o envio).

    Comparar o ajuste importa: se o bitrate mudou, o SSIM antigo nao vale mais para o fluxo que
    vai entrar no ar.
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
    return medir(fluxo_id, segundos=segundos, bitrate=bitrate)
