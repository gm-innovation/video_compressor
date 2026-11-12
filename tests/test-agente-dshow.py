#!/usr/bin/env python3
"""Regressão: o agente de bordo aceita CÂMERA FÍSICA (ligada direto na máquina), não só fonte sintética.

Antes (até 12/11/2026) o `board/agent.py` fixava `-f lavfi -i <fonte>`: só dava para testar com
`testsrc2`. Agora o perfil pode dizer `"entrada": "camera"` com `"dispositivo": "<nome>"` e o agente
captura do dshow — é o caso do PC de captura com as câmeras no USB.

O que este teste prova:
  1) o comando do perfil de câmera é dshow com o dispositivo pedido, sem `lavfi`;
  2) o perfil sintético continua lavfi (nada quebrou);
  3) `marco()` (telemetria do encode) aceita perfil de câmera, que não tem o campo `fonte`;
  4) se HOUVER câmera física nesta máquina, o agente sobe de verdade e o fluxo aparece no mediamtx.
     Sem câmera, a etapa de hardware é declaradamente pulada (não é falha).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "board"))
sys.path.insert(0, str(RAIZ / "ground"))

MEDIAMTX = RAIZ / "tools" / "mediamtx" / "mediamtx.exe"
RTSP, SRT, API = 8560, 8895, 9991

falhas: list[str] = []
processos: list[subprocess.Popen] = []


def checar(nome: str, condicao: bool, detalhe: str = "") -> None:
    print(("ok   " if condicao else "FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(nome)


import agent  # noqa: E402


def main() -> int:
    # 1) perfil de câmera -> dshow
    camera = {"id": "cam-teste-dshow", "entrada": "camera", "dispositivo": "Webcam Teste",
              "resolucao": "1280x720", "fps": 30, "codec": "libx264", "bitrate": "3000k",
              "srt_host": "127.0.0.1", "srt_port": 8890, "streamid": "cam-01"}
    cmd = agent.comando(camera)
    checar("perfil de camera usa dshow com o dispositivo pedido",
           "-i" in cmd and "video=Webcam Teste" in cmd and "dshow" in cmd and "lavfi" not in cmd
           and "-rtbufsize" in cmd,
           " ".join(cmd[cmd.index("-f"):cmd.index("-i") + 2]))

    # 2) perfil sintetico continua lavfi
    sintetica = {"id": "cam-09", "fonte": "testsrc2=size=640x360:rate=30", "codec": "libx264",
                 "bitrate": "500k", "srt_host": "127.0.0.1", "srt_port": 8890, "streamid": "cam-09"}
    cmd2 = agent.comando(sintetica)
    checar("perfil sintetico continua lavfi", "lavfi" in cmd2 and "dshow" not in cmd2)

    # 3) telemetria aceita perfil de camera (sem campo `fonte`)
    try:
        agent.marco(camera, 0, "teste")
        checar("telemetria (marco) aceita perfil de camera",
               (RAIZ / "board" / "telemetria" / "cam-teste-dshow.json").exists())
    except Exception as e:
        checar("telemetria (marco) aceita perfil de camera", False, f"{type(e).__name__}: {e}")

    # 4) hardware: só roda se existir câmera física nesta máquina
    import ingestao
    dispositivos = (ingestao.listar_dispositivos() or {}).get("video") or []
    if not dispositivos or not MEDIAMTX.exists():
        print(f"     (etapa de hardware pulada: {len(dispositivos)} camera(s) e "
              f"{'mediamtx presente' if MEDIAMTX.exists() else 'sem mediamtx'})")
        return 1 if falhas else 0

    temporario = Path(tempfile.mkdtemp(prefix="agente-dshow-"))
    cfg = temporario / "m.yml"
    cfg.write_text(f"logLevel: error\nlogDestinations: [stdout]\nrtsp: yes\nrtspAddress: 127.0.0.1:{RTSP}\n"
                   f"rtpAddress: 127.0.0.1:8110\nrtcpAddress: 127.0.0.1:8111\nrtmp: no\nhls: no\n"
                   f"webrtc: no\nmoq: no\nsrt: yes\nsrtAddress: 127.0.0.1:{SRT}\n"
                   f"api: yes\napiAddress: 127.0.0.1:{API}\npaths:\n  all_others:\n", encoding="utf-8")
    perfil = temporario / "perfil.json"
    perfil.write_text(json.dumps([{**camera, "dispositivo": dispositivos[0], "srt_port": SRT,
                                   "bitrate": "1000k", "streamid": "teste-dshow"}]), encoding="utf-8")

    mt = subprocess.Popen([str(MEDIAMTX), str(cfg)], cwd=str(RAIZ),
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processos.append(mt)
    for _ in range(40):
        try:
            import urllib.request
            urllib.request.urlopen(f"http://127.0.0.1:{API}/v3/paths/list", timeout=2).read()
            break
        except Exception:
            time.sleep(0.3)
    ag = subprocess.Popen([sys.executable, str(RAIZ / "board" / "agent.py"), str(perfil)],
                          cwd=str(RAIZ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processos.append(ag)

    pronto = False
    limite = time.time() + 40
    while time.time() < limite and not pronto:
        try:
            import urllib.request
            itens = json.loads(urllib.request.urlopen(
                f"http://127.0.0.1:{API}/v3/paths/list", timeout=2).read().decode()).get("items", [])
            pronto = any(i.get("name") == "teste-dshow" and i.get("ready") for i in itens)
        except Exception:
            pass
        time.sleep(0.5)
    checar(f"agente publicou a camera real ({dispositivos[0]}) no mediamtx", pronto,
           "" if pronto else "nao apareceu em 40 s (camera ocupada? permissao do Windows?)")
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
        t = RAIZ / "board" / "telemetria" / "cam-teste-dshow.json"   # so' o arquivo deste teste
        if t.exists():
            t.unlink()
    print("\n" + ("AGENTE DSHow OK" if codigo == 0 else f"AGENTE DSHow COM FALHA: {', '.join(falhas)}"))
    raise SystemExit(codigo)
