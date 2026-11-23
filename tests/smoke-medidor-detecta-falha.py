#!/usr/bin/env python3
"""O MEDIDOR MEDE (prova de que o smoke nao da' "OK" de graca).

O risco de um medidor mal feito e' o pior de todos: ele passa quando o sistema esta' quebrado. Este
teste prova o contrario, com midia de verdade:

  1) sobe o mediamtx e PUBLICA um fluxo sintetico 30 fps de verdade (o mesmo caminho do produto);
  2) mede: o medidor TEM que achar quadros (fps > 25) e banda > 0 — senao nao presta;
  3) CORTA a fonte a mao (mata o publicador) e mede de novo: o medidor TEM que devolver 0 quadros;
  4) derruba o mediamtx e mede: TEM que devolver 0 (nenhum numero inventado).

    python tests/smoke-medidor-detecta-falha.py
"""
from __future__ import annotations

import os
import pathlib
import socket
import subprocess
import sys
import time

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "tools" / "smoke"))

from ambiente import FFMPEG, FFPROBE, MEDIAMTX, sem_janela  # noqa: E402
from medidor import medir_fluxo  # noqa: E402

PORTA = 8655
FLUXO = "sonda-do-medidor"
falhas: list[str] = []


def checar(nome: str, ok: bool, detalhe: str = "") -> None:
    print(("  OK   " if ok else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""), flush=True)
    if not ok:
        falhas.append(nome)


def porta_aberta(porta: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", porta), timeout=0.5):
            return True
    except Exception:  # noqa: BLE001
        return False


def espera(condicao, segundos: float) -> bool:
    fim = time.time() + segundos
    while time.time() < fim:
        if condicao():
            return True
        time.sleep(0.4)
    return False


def fluxo_publicado() -> bool:
    r = subprocess.run([str(FFPROBE), "-v", "error", "-print_format", "json", "-show_streams",
                        f"rtsp://127.0.0.1:{PORTA}/{FLUXO}"], capture_output=True, timeout=40)
    return b'"codec_type": "video"' in (r.stdout or b"") or b'"codec_type":"video"' in (r.stdout or b"")


def main() -> int:
    import json
    import tempfile

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-medidor-"))
    cfg = tmp / "mediamtx.yml"
    cfg.write_text("logLevel: info\n"
                   f"rtspAddress: 127.0.0.1:{PORTA}\n"
                   "rtmp: no\nhls: no\nwebrtc: no\nsrt: no\napi: no\nmetrics: no\n"
                   "paths:\n  all_others:\n", encoding="utf-8")
    log = (tmp / "mediamtx.log").open("wb")
    mt = subprocess.Popen([str(MEDIAMTX), str(cfg)], stdout=log, stderr=subprocess.STDOUT,
                          creationflags=sem_janela())
    pub = None
    try:
        checar("o mediamtx do teste subiu", espera(lambda: porta_aberta(PORTA), 25), f"porta {PORTA}")

        # 2) um fluxo 30 fps DE VERDADE, publicado no tempo real (igual ao bordo)
        t_pub = time.time()
        pub = subprocess.Popen(
            [str(FFMPEG), "-nostdin", "-loglevel", "warning", "-re",
             "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
             "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-g", "30",
             "-pix_fmt", "yuv420p", "-f", "rtsp", "-rtsp_transport", "tcp",
             f"rtsp://127.0.0.1:{PORTA}/{FLUXO}"],
            stdout=log, stderr=subprocess.STDOUT, creationflags=sem_janela())
        checar("a fonte esta' no ar (o flavor de verdade para medir)", espera(fluxo_publicado, 40),
               f"rtsp://127.0.0.1:{PORTA}/{FLUXO}")

        m = medir_fluxo(f"rtsp://127.0.0.1:{PORTA}/{FLUXO}", segundos=6.0, t_publicacao=t_pub)
        print(f"    medido com a fonte no ar: {json.dumps({k: m[k] for k in ('quadros','fps','mbps','latencia_s')})}")
        checar("com a fonte no ar o medidor ENCONTRA quadros", m["quadros"] > 0, f"{m['quadros']} quadros")
        checar("e o fps medido confere com a fonte de 30 fps", m["fps"] >= 25.0, f"{m['fps']} fps")
        checar("e a banda medida e' maior que zero", m["mbps"] > 0.2, f"{m['mbps']} Mbps")
        checar("e a latencia do caminho e' medida (nao e' None)",
               m["latencia_s"] is not None and 0 <= float(m["latencia_s"]) <= 5.0,
               f"{m['latencia_s']} s")

        # 3) CORTA a fonte a mao: o medidor tem que perceber
        pub.terminate()
        pub.wait(timeout=20)
        sumiu = espera(lambda: not fluxo_publicado(), 35)
        checar("a fonte saiu do ar (cortei o publicador a mao)", sumiu, "sem fluxo no mediamtx")
        m2 = medir_fluxo(f"rtsp://127.0.0.1:{PORTA}/{FLUXO}", segundos=4.0)
        print(f"    medido com a fonte MORTA: {json.dumps({k: m2[k] for k in ('quadros','fps','mbps')})}")
        checar("com a fonte MORTA o medidor devolve 0 quadros (nao inventa)", m2["quadros"] == 0,
               f"{m2['quadros']} quadros")
        checar("com a fonte MORTA o medidor devolve 0 Mbps", m2["mbps"] == 0.0, f"{m2['mbps']} Mbps")

        # 4) derruba o mediamtx: idem
        mt.terminate()
        mt.wait(timeout=20)
        espera(lambda: not porta_aberta(PORTA), 20)
        m3 = medir_fluxo(f"rtsp://127.0.0.1:{PORTA}/{FLUXO}", segundos=3.0)
        checar("com o mediamtx DERRUBADO o medidor devolve 0 quadros", m3["quadros"] == 0,
               f"{m3['quadros']} quadros")
    finally:
        for p in (pub, mt):
            if p is not None and p.poll() is None:
                try:
                    p.terminate()
                    p.wait(timeout=10)
                except Exception:  # noqa: BLE001
                    try:
                        p.kill()
                    except Exception:  # noqa: BLE001
                        pass
    print()
    if falhas:
        print(f"FALHOU — {len(falhas)}: " + "; ".join(falhas))
        return 1
    print("OK — o medidor mede de verdade: acha o fluxo quando ha' e devolve zero quando nao ha'")
    return 0


if __name__ == "__main__":
    import os
    import sys
    codigo = main()
    sys.stdout.flush()
    sys.stderr.flush()
    # sai na marra: nenhum filho preso (ffmpeg/mediamtx) pode segurar a prova depois do veredito
    os._exit(codigo)
