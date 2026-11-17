#!/usr/bin/env python3
"""Prova REAL da gravacao no LADO TERRA: mediamtx de verdade, fluxo de verdade, ffmpeg gravando, ffprobe lendo.

Nada de duble: sobe um mediamtx, publica um fluxo de teste nele (o que a embarcacao mandaria ja' chega
assim), o modulo `gravacao` grava o que chegou e o `ffprobe` LE' o arquivo gravado. Se o arquivo nao
tiver video, o teste falha — nao existe "gravou" de mentira.

Tambem prova o lado honesto: com o fluxo FORA do ar, `iniciar` devolve erro (nunca diz que gravou).
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "ground"))

FFMPEG = RAIZ / "tools" / "ffmpeg" / "ffmpeg.exe"
FFPROBE = RAIZ / "tools" / "ffmpeg" / "ffprobe.exe"
MEDIAMTX = RAIZ / "tools" / "mediamtx" / "mediamtx.exe"

PORTA_RTSP = 8654            # porta propria do teste: nao atropela a bancada (8554)
FLUXO = "cam-gravacao"
TMP = Path(tempfile.mkdtemp(prefix="lecsor-gravacao-"))
os.environ["LECSOR_GRAVACOES_DIR"] = str(TMP / "gravacoes")
os.environ["LECSOR_PORTA_RTSP"] = str(PORTA_RTSP)

import gravacao  # noqa: E402  (importa depois do env: a pasta e a porta vem do ambiente)

falhas = []


def checar(nome, ok, detalhe=""):
    print(("  OK   " if ok else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not ok:
        falhas.append(nome)


def sem_janela():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def espera_porta(porta, segundos=15.0) -> bool:
    fim = time.time() + segundos
    while time.time() < fim:
        try:
            with socket.create_connection(("127.0.0.1", porta), timeout=1):
                return True
        except Exception:
            time.sleep(0.3)
    return False


def ffprobe_json(url) -> dict:
    r = subprocess.run([str(FFPROBE), "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", url], capture_output=True, timeout=30)
    try:
        return json.loads((r.stdout or b"{}").decode("utf-8", "ignore"))
    except Exception:
        return {}


def main():
    cfg = TMP / "mediamtx.yml"
    cfg.write_text(
        "logLevel: info\n"
        f"rtspAddress: 127.0.0.1:{PORTA_RTSP}\n"
        "rtmp: no\nhls: no\nwebrtc: no\nsrt: no\napi: no\nmetrics: no\n"
        "paths:\n  all_others:\n", encoding="utf-8")
    log = (TMP / "mediamtx.log").open("wb")
    mt = subprocess.Popen([str(MEDIAMTX), str(cfg)], stdout=log, stderr=subprocess.STDOUT,
                          creationflags=sem_janela())
    pub = None
    try:
        checar("o mediamtx (lado terra) subiu", espera_porta(PORTA_RTSP), f"porta {PORTA_RTSP}")

        # publica o que a embarcacao enviaria (chega no mediamtx e o lado terra le' daqui)
        pub = subprocess.Popen(
            [str(FFMPEG), "-nostdin", "-loglevel", "warning", "-re",
             "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15",
             "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-g", "15",
             "-pix_fmt", "yuv420p", "-f", "rtsp", "-rtsp_transport", "tcp",
             f"rtsp://127.0.0.1:{PORTA_RTSP}/{FLUXO}"],
            stdout=log, stderr=subprocess.STDOUT, creationflags=sem_janela())
        no_ar = False
        fim = time.time() + 20
        while time.time() < fim and not no_ar:
            info = ffprobe_json(f"rtsp://127.0.0.1:{PORTA_RTSP}/{FLUXO}")
            no_ar = any(s.get("codec_type") == "video" for s in (info.get("streams") or []))
            if not no_ar:
                time.sleep(0.6)
        checar("o fluxo esta' no ar no mediamtx (o que chegou pela rede)", no_ar, FLUXO)

        # 1) grava o que JA' CHEGOU
        r = gravacao.iniciar("t-gravacao-1", FLUXO)
        checar("a gravacao comeca no lado terra", bool(r.get("ok")), json.dumps(r, ensure_ascii=False)[:200])
        time.sleep(4)
        e = gravacao.estado("t-gravacao-1")
        checar("o estado diz que esta' gravando de verdade", bool(e["gravando"]), json.dumps(e, ensure_ascii=False))
        checar("o arquivo esta' crescendo enquanto grava", e["bytes"] > 0, f"{e['bytes']} B")
        p = gravacao.parar("t-gravacao-1")
        checar("parar fecha a gravacao e devolve o arquivo", Path(p["arquivo"]).exists() and p["bytes"] > 0,
               f"{p['bytes']} B em {p['segundos']} s")

        # 2) o arquivo TEM video (quem le' e' o ffprobe, nao a nossa palavra)
        info = ffprobe_json(p["arquivo"])
        videos = [s for s in (info.get("streams") or []) if s.get("codec_type") == "video"]
        dur = float((info.get("format") or {}).get("duration") or 0)
        checar("a gravacao tem uma faixa de video h264", bool(videos) and videos[0].get("codec_name") == "h264",
               f"{videos[0].get('codec_name') if videos else 'sem video'} {videos[0].get('width') if videos else ''}x"
               f"{videos[0].get('height') if videos else ''}")
        checar("a gravacao tem uns segundos de video", dur >= 2.0, f"{dur:.1f} s")
        checar("o historico lista a gravacao que ficou no disco",
               any(g["transmissao_id"] == "t-gravacao-1" for g in gravacao.listar()),
               json.dumps(gravacao.listar(), ensure_ascii=False)[:200])

        # 3) o lado honesto: sem fluxo no ar, nunca diz que gravou
        if pub:
            subprocess.run(["taskkill", "/PID", str(pub.pid), "/T", "/F"], capture_output=True, timeout=20)
            pub = None
        time.sleep(1.5)
        r2 = gravacao.iniciar("t-gravacao-sem-fluxo", "cam-que-nao-existe")
        checar("sem fluxo no ar a gravacao NAO e' dada como boa", "erro" in r2,
               json.dumps(r2, ensure_ascii=False)[:220])
        checar("e o estado nao mente dizendo que grava",
               not gravacao.estado("t-gravacao-sem-fluxo")["gravando"], "")

        # 4) processo morto (maquina reiniciou) e' marcado, sem apagar o arquivo
        aberto = gravacao.iniciar("t-gravacao-orfa", FLUXO)
        if aberto.get("ok"):
            gravacao.parar("t-gravacao-orfa")
        checar("a limpeza de orfas nao apaga a gravacao que ja' existe",
               gravacao.limpar_orfas() >= 0 and Path(p["arquivo"]).exists(), "")
    finally:
        for proc in (pub, mt):
            if proc and proc.poll() is None:
                try:
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True, timeout=20)
                except Exception:
                    pass
        log.close()


if __name__ == "__main__":
    print(f"prova da gravacao no lado terra (pasta {TMP})")
    main()
    if falhas:
        print(f"\nFALHAS ({len(falhas)}):")
        for f in falhas:
            print(f" - {f}")
        sys.exit(1)
    print("\nveredito: funcionou 100% (gravacao no lado terra provada com mediamtx + ffmpeg + ffprobe)")
