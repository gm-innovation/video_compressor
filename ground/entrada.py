#!/usr/bin/env python3
"""Quanto a fonte "vale" em banda bruta — o que entra, antes de comprimir.

Duas situacoes, e a tela precisa dizer QUAL e a de cada linha:

* **Fonte ja comprimida** (arquivo MP4, camera RTSP/H.264): a entrada e MEDIDA (`ffprobe`/registro de
  compressao). E aqui que "banda economizada" e a economia real do re-encode.
* **Fonte crua** (webcam dshow, `testsrc2`): nao existe fluxo comprimido de entrada; o que existe e o
  bruto equivalente a resolucao e quadros por segundo. A regra do projeto e' `W x H x fps x bits-por-pixel / 8`
  (1080p30 em 4:2:0 8 bits = 746,5 Mbps). Isso NAO quer dizer que o link levou 746 Mbps: quer dizer que
  mandar esse video cru custaria isso — por isso a origem vai rotulada na tela.
"""
from __future__ import annotations

import re

BITS_POR_PIXEL_420 = 12.0   # 4:2:0 8 bits: 1,5 amostra/pixel x 8 bits
BITS_POR_PIXEL_422 = 16.0   # 4:2:2 8 bits (caso do 4:2:2 10-bit do alvo, se medido)
BITS_POR_PIXEL_RGB = 24.0   # RGB 8 bits


def resolucao_em_pixels(resolucao: str | None) -> tuple[int, int] | None:
    m = re.match(r"^\s*(\d+)\s*[xX×]\s*(\d+)\s*$", str(resolucao or ""))
    if not m:
        return None
    largura, altura = int(m.group(1)), int(m.group(2))
    return (largura, altura) if largura and altura else None


def entrada_teorica_kbps(resolucao: str | None, fps: float | None,
                         bits_por_pixel: float = BITS_POR_PIXEL_420) -> float | None:
    """Banda bruta equivalente da fonte crua, em kbps. None quando nao da' para saber resolucao/fps."""
    pixels = resolucao_em_pixels(resolucao)
    try:
        quadros = float(fps or 0)
    except (TypeError, ValueError):
        quadros = 0.0
    if not pixels or quadros <= 0:
        return None
    largura, altura = pixels
    return largura * altura * quadros * bits_por_pixel / 1000.0


def origem_da_entrada(resolucao: str | None, fps: float | None, medido: bool) -> str:
    """Rotulo curto para a tela dizer se a entrada foi medida ou e' o bruto teorico."""
    if medido:
        return "medida na fonte"
    pixels = resolucao_em_pixels(resolucao)
    if not pixels:
        return "sem medida"
    return f"bruto teorico {pixels[0]}x{pixels[1]}@{int(fps or 0)} (4:2:0 8 bits)"
