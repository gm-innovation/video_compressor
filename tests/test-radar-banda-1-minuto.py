#!/usr/bin/env python3
"""Fase 4 do radar: quanto PESA 1 minuto de radar na PPI, em CADA alvo de bitrate.

O dono pediu a prova de banda antes de levar o radar para a embarcacao (Starlink e' caro e limitado):
aqui o sinal REAL de radar (arquivo do dono) e' desenhado em PPI 1.024x1.024 a 30 fps por 60 s de sinal,
UMA vez, e o mesmo material e' codificado com o AJUSTE DO PRODUTO (`ingestao.ajuste_encode`, o mesmo
comando que vai para a rede: `veryfast` + `zerolatency` + `-bf 0` + `-g 30`) em cada alvo.

Provas (medidas no arquivo gerado, nao estimadas):
  1) 1 minuto de radar cru pesa o que a conta diz (1.024x1.024 cinza a 30 fps = 251,7 Mbps);
  2) em cada alvo o arquivo medido fica dentro de 12% do alvo pedido (o alvo e' obedecido);
  3) o tamanho cresce com o alvo (a escolha do dono muda o que sai na rede);
  4) o minuto de radar fica dentro do piso de economia do produto (>= 73% menos que o cru);
  5) a tabela de 1 minuto por alvo (MB/min) e' impressa para o dono decidir quanto o radar pode gastar.

    python tests/test-radar-banda-1-minuto.py
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

RAIZ = pathlib.Path(__file__).resolve().parents[1]
DRQ_REAL = pathlib.Path.home() / "work" / "replicacao" / "seadarq" / "sim" / "fixtures" / "drq" / "20261106164423.drq"
LADO = 1024
ALVOS = ("1500k", "1200k", "1000k", "800k", "500k", "300k")
PISO_COMPRESSAO_PCT = 73.0
CRU_KBPS = LADO * LADO * 8 * 30 / 1000          # 1.024x1.024, 1 byte/pixel, 30 fps, cinza = 251.658 kbps
sys.path.insert(0, str(RAIZ / "ground"))


def livre_gb(caminho: pathlib.Path) -> float:
    return shutil.disk_usage(str(caminho)).free / 2 ** 30


def main() -> int:
    falhas: list[str] = []

    def exigir(cond, texto):
        print(("OK   " if cond else "FALHA ") + texto)
        if not cond:
            falhas.append(texto)

    if not DRQ_REAL.exists():
        print(f"PULADA: sem o arquivo de radar do dono ({DRQ_REAL}) — este teste precisa do sinal real")
        return 0

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-radar-banda-"))
    if livre_gb(tmp) < 4.0:
        print(f"PULADA: pouco espaco em disco ({livre_gb(tmp):.1f} GB livres) para guardar 1 minuto cru")
        return 0

    import ingestao
    import radar_drq

    cru = tmp / "ppi-60s.raw"
    print(f"desenhando 60 s de radar em PPI {LADO}x{LADO} a 30 fps (cru: {CRU_KBPS:.0f} kbps)...")
    t0 = time.time()
    quadros = 0
    # `quadros_ao_vivo` entrega um quadro por vez (nao guarda a gravacao toda na memoria): 1.795 quadros
    # de 1 MB guardados de uma vez seriam ~1,9 GB de RAM a toa.
    with open(cru, "wb") as f:
        for px, _info in radar_drq.quadros_ao_vivo(str(DRQ_REAL), "ppi", "30fps", 30,
                                                   repetir=False, segundos=60):
            f.write(px)
            quadros += 1
    print(f"  {quadros} quadros crus em {time.time() - t0:.1f}s ({cru.stat().st_size} B)\n")

    exigir(quadros > 1500, f"60 s de sinal viraram {quadros} imagens PPI (1 por 1/30 s)")
    exigir(abs(cru.stat().st_size - quadros * LADO * LADO) == 0,
           f"o material cru e' 1 byte por pixel ({cru.stat().st_size} B = {quadros} x {LADO}x{LADO})")
    cru_mb_min = quadros * LADO * LADO / 2 ** 20
    print(f"  1 minuto de radar CRU = {cru_mb_min:.1f} MB ({CRU_KBPS:.1f} kbps)\n")

    tabela = []
    for alvo in ALVOS:
        mp4 = tmp / f"radar-{alvo}.mp4"
        cmd = [str(radar_drq.ffmpeg_do_produto()), "-y", "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{LADO}x{LADO}", "-framerate", "30",
               "-i", str(cru.resolve()),
               *ingestao.ajuste_encode(alvo, 30), str(mp4.resolve())]
        t1 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            exigir(False, f"o ffmpeg do produto codificou o alvo {alvo} ({r.stderr[:200]})")
            continue
        segundos = radar_drq.duracao(str(mp4))
        kb = mp4.stat().st_size / 1024
        kbps = kb * 8 / segundos if segundos else 0
        ganho = 100.0 * (1 - kbps / CRU_KBPS) if CRU_KBPS else 0
        tabela.append((alvo, kbps, kb, segundos, ganho))
        print(f"  {alvo:>6}: {kbps:8.1f} kbps | {kb:8.1f} KB no minuto | ganho {ganho:5.1f}% | "
              f"codificado em {time.time() - t1:.1f}s")

    print()
    exigir(len(tabela) == len(ALVOS), f"os {len(ALVOS)} alvos foram codificados ({len(tabela)})")
    for alvo, kbps, kb, segundos, ganho in tabela:
        alvo_kbps = int(alvo[:-1])
        exigir(abs(kbps - alvo_kbps) <= alvo_kbps * 0.12,
               f"{alvo}: o arquivo medido segue o alvo (medido {kbps:.1f} kbps, alvo {alvo_kbps})")
        exigir(ganho >= PISO_COMPRESSAO_PCT,
               f"{alvo}: 1 min de radar economiza >= {PISO_COMPRESSAO_PCT}% do cru (medido {ganho:.1f}%)")
        exigir(segundos and 55 <= segundos <= 62,
               f"{alvo}: o material medido e' o minuto inteiro ({segundos:.1f}s)")
    if len(tabela) == len(ALVOS):
        kbps_por_alvo = [t[1] for t in tabela]
        exigir(kbps_por_alvo == sorted(kbps_por_alvo, reverse=True),
               "o que sai na rede cresce com o alvo escolhido (nenhum alvo invertido)")
        exigir(abs(kbps_por_alvo[0] - kbps_por_alvo[-1]) > 800,
               f"a escolha do alvo muda mesmo o consumo ({kbps_por_alvo[-1]:.0f} a {kbps_por_alvo[0]:.0f} kbps)")

    print("\n== 1 minuto de radar na PPI (o que o dono leva para o Starlink) ==")
    print(f"{'alvo':>7} | {'kbps':>9} | {'MB por minuto':>13} | {'ganho vs cru':>12}")
    for alvo, kbps, kb, _s, ganho in tabela:
        print(f"{alvo:>7} | {kbps:9.1f} | {kb/1024:13.2f} | {ganho:11.1f}%")

    try:
        cru.unlink()
    except Exception:
        pass
    try:
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass

    print()
    if falhas:
        print(f"FALHAS ({len(falhas)}):")
        for f in falhas:
            print(" -", f)
        return 1
    print("TUDO OK — o peso de 1 minuto de radar esta medido em cada alvo, com o ajuste do produto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
