#!/usr/bin/env python3
"""Regressão: o vídeo JA COMPRIMIDO no PC de captura e' repassado para o lado terra.

Cenario que este teste prova, com DUAS instancias isoladas do mediamtx nesta maquina (nenhuma das
duas e' o lado terra de verdade — o teste nao depende de rede externa):

  A (origem)  = PC de captura: recebe o fluxo comprimido via SRT
  B (destino) = lado terra:    tem de receber o MESMO fluxo, sem reencodar (`-c copy`)

O que e' checado:
  1) sem destino (`LECSOR_DESTINO_SRT` vazio) NADA e' repassado — e' o que impede a VPS de subir para si;
  2) com destino, o fluxo aparece em B e fica `ready`;
  3) o fluxo que chega em B tem o MESMO codec e a MESMA resolucao (prova de que nao houve reencode).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MEDIAMTX = RAIZ / "tools" / "mediamtx" / "mediamtx.exe"
REPASSE = RAIZ / "ground" / "repasse.py"

RTSP_A, SRT_A, API_A = 8556, 8892, 9999
RTSP_B, SRT_B, API_B = 8557, 8893, 9998
FLUXO = "teste-repasse"

falhas: list[str] = []
processos: list[subprocess.Popen] = []
temporario: Path | None = None


def checar(nome: str, condicao: bool, detalhe: str = "") -> None:
    print(("ok   " if condicao else "FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


def config_de(rtsp: int, srt: int, api: int, rtp: int, rtcp: int) -> str:
    # portas de RTP/RTCP e MoQ explicitas e distintas por instancia: sem isso a segunda instancia
    # nao sobe (as duas tentariam :8000/:8001 e :8890/:8891 ao mesmo tempo)
    return (f"logLevel: error\nlogDestinations: [stdout]\n"
            f"rtsp: yes\nrtspAddress: 127.0.0.1:{rtsp}\nrtpAddress: 127.0.0.1:{rtp}\n"
            f"rtcpAddress: 127.0.0.1:{rtcp}\n"
            f"rtmp: no\nhls: no\nwebrtc: no\nmoq: no\n"
            f"srt: yes\nsrtAddress: 127.0.0.1:{srt}\n"
            f"api: yes\napiAddress: 127.0.0.1:{api}\n"
            f"paths:\n  all_others:\n")


def sobe(comando: list[str], **kw) -> subprocess.Popen:
    p = subprocess.Popen(comando, cwd=str(RAIZ),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    processos.append(p)
    return p


def espera_api(porta: int, segundos: int = 20) -> bool:
    limite = time.time() + segundos
    while time.time() < limite:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/v3/paths/list", timeout=2) as r:
                json.loads(r.read().decode())
                return True
        except Exception:
            time.sleep(0.3)
    return False


def fluxo_em(porta: int, nome: str, segundos: int = 45) -> dict | None:
    limite = time.time() + segundos
    while time.time() < limite:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/v3/paths/list", timeout=2) as r:
                itens = json.loads(r.read().decode()).get("items", [])
        except Exception:
            itens = []
        for it in itens:
            if it.get("name") == nome and it.get("ready"):
                return it
        time.sleep(0.5)
    return None


def main() -> int:
    global temporario
    if not MEDIAMTX.exists():
        print(f"sem {MEDIAMTX} — teste pulado (bancada sem o mediamtx)")
        return 0

    temporario = Path(tempfile.mkdtemp(prefix="repasse-"))
    cfg_a = temporario / "a.yml"
    cfg_b = temporario / "b.yml"
    cfg_a.write_text(config_de(RTSP_A, SRT_A, API_A, 8100, 8101), encoding="utf-8")
    cfg_b.write_text(config_de(RTSP_B, SRT_B, API_B, 8102, 8103), encoding="utf-8")

    sobe([str(MEDIAMTX), str(cfg_a)])
    sobe([str(MEDIAMTX), str(cfg_b)])
    checar("as duas instancias do mediamtx subiram", espera_api(API_A) and espera_api(API_B))

    # PC de captura: fluxo sintetico JA COMPRIMIDO (640x360 H264) subindo em SRT
    sobe(["ffmpeg", "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi",
          "-i", "testsrc2=size=640x360:rate=15", "-c:v", "libx264", "-preset", "ultrafast",
          "-tune", "zerolatency", "-g", "15", "-b:v", "500k", "-an", "-f", "mpegts",
          f"srt://127.0.0.1:{SRT_A}?mode=caller&streamid=publish:{FLUXO}"])
    checar("o fluxo comprimido chegou no PC de captura", fluxo_em(API_A, FLUXO) is not None)

    # 1) sem destino: nada sai daqui
    sem_destino = subprocess.run([sys.executable, str(REPASSE), FLUXO],
                                 cwd=str(RAIZ), capture_output=True, text=True, timeout=60,
                                 env={**os.environ, "LECSOR_DESTINO_SRT": ""})
    checar("sem destino o repasse nao sobe nada", sem_destino.returncode == 0
           and fluxo_em(API_B, FLUXO, segundos=6) is None,
           (sem_destino.stdout or "").strip().splitlines()[-1] if sem_destino.stdout else "")

    # 2) com destino: o fluxo tem de aparecer no lado terra
    env = {**os.environ, "LECSOR_ORIGEM_RTSP": f"rtsp://127.0.0.1:{RTSP_A}"}
    repasse = sobe([sys.executable, str(REPASSE), FLUXO, f"127.0.0.1:{SRT_B}"], env=env)
    recebido = fluxo_em(API_B, FLUXO)
    checar("com destino o fluxo chega no lado terra", recebido is not None,
           "" if recebido else "nao apareceu no destino em 45 s")

    # 3) chegou sem reencodar: mesmo codec e mesma resolucao
    if recebido:
        faixa = (recebido.get("tracks2") or [{}])[0]
        props = faixa.get("codecProps") or {}
        checar("mesmo codec e mesma resolucao (prova do -c copy)",
               faixa.get("codec") == "H264" and props.get("width") == 640 and props.get("height") == 360,
               f"codec={faixa.get('codec')} {props.get('width')}x{props.get('height')}")

    try:
        repasse.kill()
    except Exception:
        pass
    return 1 if falhas else 0


if __name__ == "__main__":
    try:
        codigo = main()
    finally:
        for p in processos:
            try:
                p.kill()
            except Exception:
                pass
        if temporario:
            import shutil
            shutil.rmtree(temporario, ignore_errors=True)
        trava = RAIZ / "ground" / ".repasse"
        if trava.exists():
            import shutil
            shutil.rmtree(trava, ignore_errors=True)
    print("\n" + ("REPASSE OK" if codigo == 0 else f"REPASSE COM FALHA: {', '.join(falhas)}"))
    raise SystemExit(codigo)
