#!/usr/bin/env python3
"""Lado terra: recebe SRT e publica HLS para o portal (versao local da bancada).

Substituivel pelo mediamtx (WebRTC) na fase de producao; aqui roda so com ffmpeg,
para nao depender de Docker, e ja entrega imagem no navegador.
"""
from __future__ import annotations
import json, signal, subprocess, sys, time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RECEIVERS = RAIZ / "ground" / "receivers.json"
STATUS = RAIZ / "ground" / "status.json"
SAIDA = RAIZ / "portal" / "streams"

def comando(porta: int, pasta: Path) -> list[str]:
    pasta.mkdir(parents=True, exist_ok=True)
    return ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
            "-i", f"srt://0.0.0.0:{porta}?mode=listener&latency=200&timeout=20000000",
            "-c", "copy", "-f", "hls", "-hls_time", "1", "-hls_list_size", "6",
            "-hls_flags", "delete_segments+append_list",
            "-hls_segment_filename", str(pasta / "seg%03d.ts"), str(pasta / "index.m3u8")]

def principal() -> int:
    cfg = json.loads(RECEIVERS.read_text(encoding="utf-8"))
    procs: dict[str, dict] = {}
    parar = {"sim": False}
    signal.signal(signal.SIGTERM, lambda *_: parar.update(sim=True))
    signal.signal(signal.SIGINT, lambda *_: parar.update(sim=True))
    print(f"[receiver] {len(cfg)} fluxo(s) SRT -> HLS em {SAIDA}")
    try:
        while not parar["sim"]:
            for c in cfg:
                st = procs.get(c["id"])
                if st is None or st["proc"].poll() is not None:
                    if st and st["proc"].poll() is not None:
                        st["reinicios"] += 1
                        st["ultimo_erro"] = (st["proc"].stderr.read() or b"").decode(errors="replace")[-300:]
                    pasta = SAIDA / c["id"]
                    p = subprocess.Popen(comando(c["srt_port"], pasta))
                    procs[c["id"]] = {"proc": p, "reinicios": (st or {}).get("reinicios", 0),
                                      "iniciado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                      "ultimo_erro": (st or {}).get("ultimo_erro", "")}
            STATUS.write_text(json.dumps({"atualizado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "fluxos": [{"id": c["id"], "rotulo": c["rotulo"], "srt_port": c["srt_port"],
                            "pid": procs[c["id"]]["proc"].pid,
                            "reinicios": procs[c["id"]]["reinicios"],
                            "manifesto": f"streams/{c['id']}/index.m3u8",
                            "manifesto_existe": (SAIDA / c["id"] / "index.m3u8").exists(),
                            "ultimo_erro": procs[c["id"]]["ultimo_erro"]} for c in cfg]},
                ensure_ascii=False, indent=2), encoding="utf-8")
            time.sleep(2)
    finally:
        for st in procs.values():
            st["proc"].terminate()
        print("[receiver] encerrado")
    return 0

if __name__ == "__main__":
    sys.exit(principal())
