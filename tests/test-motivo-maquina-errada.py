#!/usr/bin/env python3
"""Motivo de falha que APONTA A MAQUINA CERTA: `dshow` desconhecido = "nao e' a de captura".

Medido em 19/11/2026 (base do lado terra, `ingestoes` 186-191): o log real traz
    [in#0] Unknown input format: 'dshow'
    Error opening input file video=@device_pnp_\\\\?\\usb#vid_534d&pid_2109...
    Error opening input files: Invalid argument
e o codigo era 234 (= -22, EINVAL). Sem traduzir, a tela mostrava a linha crua do ffmpeg e ninguem sabia
que o problema era a CAPTURA ter sido pedida na maquina errada (o lado terra, sem dshow).

    python tests/test-motivo-maquina-errada.py

Provas:
  1) aquele log exato vira o recado da maquina errada (fala do PC de bordo);
  2) log de camera OCUPADA (i/o error) continua com o recado antigo (nao trocou o que ja' funcionava);
  3) log sem assinatura nenhuma continua sem motivo inventado (None).
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "ground"))

falhas: list[str] = []


def exigir(cond, texto):
    print(("OK   " if cond else "FALHA ") + texto)
    if not cond:
        falhas.append(texto)


LOG_19_11 = """ffmpeg version 6.1-essentials
[dshow @ 000001] "USB Video Device" (video)
[in#0 @ 000002] Unknown input format: 'dshow'
[in#0 @ 000002] Error opening input file video=@device_pnp_\\\\?\\usb#vid_534d&pid_2109&mi_00#7&2f0d0c88&0&0000#{65e8773d-8f56-11d0-a3b7-00a0c9223196}\\global.
[in#0 @ 000002] Error opening input files: Invalid argument
"""

LOG_OCUPADA = """ffmpeg version 6.1-essentials
[dshow @ 000001] Could not open video device 'USB Video Device'
[dshow @ 000001] I/O error
"""


def main() -> int:
    import ingestao

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-motivo-"))
    p1 = tmp / "erro-dshow.log"
    p1.write_text(LOG_19_11, encoding="utf-8")
    m1 = ingestao._motivo_da_falha(234, p1, {}) or ""
    exigir("nao e' a de captura" in m1 or "nao e a de captura" in m1,
           f"o log de dshow desconhecido diz que a maquina nao e' a de captura ({m1[:80]!r})")
    exigir("bordo" in m1, f"e manda a captura para o bordo ({m1[:110]!r})")

    p2 = tmp / "erro-ocupada.log"
    p2.write_text(LOG_OCUPADA, encoding="utf-8")
    m2 = ingestao._motivo_da_falha(1, p2, {}) or ""
    exigir("em uso por outro envio" in m2 or "camera nao abriu" in m2,
           f"camera ocupada continua com o recado antigo ({m2[:80]!r})")

    p3 = tmp / "erro-generico.log"
    p3.write_text("ffmpeg version 6.1\nConversion failed!\n", encoding="utf-8")
    m3 = ingestao._motivo_da_falha(1, p3, {}) or ""
    exigir("nao e' a de captura" not in m3 and "Conversion failed" in m3,
           f"log sem assinatura NAO vira 'maquina errada' (o recado generico continua: {m3[:70]!r})")

    print()
    if falhas:
        print(f"FALHOU — {len(falhas)} prova(s)")
        return 1
    print("OK — o motivo aponta a maquina certa (e nao mexe no que ja' funcionava)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
