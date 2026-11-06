#!/usr/bin/env python3
"""Agente de bordo (versao de bancada): le o perfil, codifica N cameras e publica em SRT.

- respeita o perfil por embarcacao (bitrate/resolucao por camera)
- watchdog: reinicia o encode que cair
- grava telemetria no banco com os 5 campos exigidos (valor, fonte, data, hardware_versao, comando)
"""
from __future__ import annotations
import datetime as dt, json, os, socket, sqlite3, subprocess, sys, time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "db" / "pipeline.db"

def hw() -> str:
    gpu = "sem nvidia-smi"
    try:
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=30).stdout.strip() or gpu
    except Exception:
        pass
    v = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    return f"{gpu} | {v.split(' Copyright')[0]}"

def comando(c: dict) -> list[str]:
    destino = f"srt://{c['srt_host']}:{c['srt_port']}?mode=caller&latency=200&pkt_size=1316"
    return ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-re",
            "-f", "lavfi", "-i", c["fonte"],
            "-c:v", c["codec"], "-preset", "ultrafast", "-tune", "zerolatency",
            "-b:v", c["bitrate"], "-maxrate", c["bitrate"], "-bufsize", "1M",
            "-g", "30", "-pix_fmt", "yuv420p", "-f", "mpegts", destino]

def telemetria(c: dict, evento: str) -> None:
    if not BANCO.exists():
        return
    dados = {
        "valor": f"{c['id']}: {evento} — encode {c['codec']} a {c['bitrate']}",
        "fonte": "board/agent.py",
        "data": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "hardware_versao": hw(),
        "comando": " ".join(comando(c)),
        "fase_id": "fase-2",
    }
    with sqlite3.connect(BANCO) as cx:
        cx.execute("""INSERT INTO medicoes (valor,fonte,data,hardware_versao,comando,fase_id)
                      VALUES (:valor,:fonte,:data,:hardware_versao,:comando,:fase_id)""", dados)

def principal() -> int:
    perfil = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "board" / "perfis" / "bancada.json"
    cameras = json.loads(Path(perfil).read_text(encoding="utf-8"))
    procs: dict[str, dict] = {}
    parar = {"sim": False}
    def encerrar(*_):
        parar["sim"] = True
    import signal
    signal.signal(signal.SIGTERM, encerrar); signal.signal(signal.SIGINT, encerrar)
    print(f"[agent] {len(cameras)} camera(s) do perfil {Path(perfil).name}")
    try:
        while not parar["sim"]:
            for c in cameras:
                st = procs.get(c["id"])
                if st is None:
                    p = subprocess.Popen(comando(c))
                    procs[c["id"]] = {"proc": p, "reinicios": 0}
                    telemetria(c, "encode iniciado")
                    print(f"[agent] {c['id']} -> srt://{c['srt_host']}:{c['srt_port']} (pid {p.pid})")
                elif st["proc"].poll() is not None:
                    st["reinicios"] += 1
                    st["proc"] = subprocess.Popen(comando(c))
                    telemetria(c, f"reinicio #{st['reinicios']} apos queda")
                    print(f"[agent] {c['id']} reiniciado (#{st['reinicios']})")
            time.sleep(2)
    finally:
        for st in procs.values():
            st["proc"].terminate()
        print("[agent] encerrado")
    return 0

if __name__ == "__main__":
    sys.exit(principal())
