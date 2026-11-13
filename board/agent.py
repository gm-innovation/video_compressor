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
sys.path.insert(0, str(RAIZ / "ground"))
from ferramentas import caminho_banco, caminho_ffmpeg  # noqa: E402  (embutidos no app)

BANCO = caminho_banco()

def hw() -> str:
    gpu = "sem nvidia-smi"
    try:
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=30).stdout.strip() or gpu
    except Exception:
        pass
    v = subprocess.run([caminho_ffmpeg(), "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    return f"{gpu} | {v.split(' Copyright')[0]}"

def entrada_de(c: dict) -> list[str]:
    """Entrada do ffmpeg da camera do perfil: camera FISICA (dshow) ou fonte sintetica (lavfi).

    Camera fisica = ligada direto na maquina (USB / HDMI-captura); o nome tem de ser o que aparece
    em `GET /api/dispositivos` ou em `ffmpeg -list_devices true -f dshow -i dummy`.
    """
    if str(c.get("entrada") or "").lower() in ("camera", "dshow", "fisica", "usb"):
        return ["-f", "dshow", "-rtbufsize", "256M",
                "-framerate", str(int(c.get("fps") or 30)),
                "-video_size", str(c.get("resolucao") or "1280x720"),
                "-i", f"video={c.get('dispositivo') or ''}"]
    return ["-f", "lavfi", "-i", c["fonte"]]


def comando(c: dict) -> list[str]:
    destino = f"srt://{c['srt_host']}:{c['srt_port']}?mode=caller&latency=200&pkt_size=1316"
    if c.get("streamid"):
        destino += f"&streamid=publish:{c['streamid']}"
    cmd = [caminho_ffmpeg(), "-hide_banner", "-loglevel", "warning"]
    if str(c.get("entrada") or "").lower() not in ("camera", "dshow", "fisica", "usb"):
        cmd += ["-re"]          # fonte sintetica/arquivo: entrega no tempo real; camera ao vivo ja' vem assim
    cmd += entrada_de(c)
    if c.get("relogio"):
        # relogio local + numero do quadro queimados na imagem: permite medir a latencia ponta a ponta
        filtro = (r"drawtext=font=Consolas:"
                  r"text='%{localtime\:%T}.%{eif\:mod(t*1000\,1000)\:d\:3} f%{n}':"
                  r"fontsize=34:fontcolor=white:box=1:boxcolor=black@0.6:x=18:y=18")
        cmd += ["-vf", filtro]
    # PTS de saida = relogio de parede (epoch): da para medir a latencia lendo numeros, sem OCR
    cmd += ["-output_ts_offset", f"{time.time():.3f}"]
    cmd += ["-c:v", c["codec"], "-preset", "ultrafast", "-tune", "zerolatency",
            "-b:v", c["bitrate"], "-maxrate", c["bitrate"], "-bufsize", "1M",
            "-g", "30", "-pix_fmt", "yuv420p", "-f", "mpegts", destino]
    return cmd

def marco(c: dict, pid: int, evento: str) -> None:
    """Grava o instante do lancamento do encoder (com ms).

    O relogio queimado no quadro so tem resolucao de 1 s; com o instante do
    lancamento mais o numero do quadro (n/30, encode em tempo real) a latencia
    ponta a ponta fica determinada com ~0,2 s de erro.
    """
    d = RAIZ / "board" / "telemetria"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{c['id']}.json").write_text(json.dumps({
        "id": c["id"], "pid": pid, "evento": evento,
        "iniciado_em": dt.datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "fps": int(c.get("fps") or (str(c["fonte"]).split("rate=")[-1].split(":")[0].split(",")[0]
                                    if "rate=" in str(c.get("fonte") or "") else 30)),
        "comando": " ".join(comando(c)),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

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
                    marco(c, p.pid, "encode iniciado")
                    telemetria(c, "encode iniciado")
                    print(f"[agent] {c['id']} -> srt://{c['srt_host']}:{c['srt_port']} (pid {p.pid})")
                elif st["proc"].poll() is not None:
                    st["reinicios"] += 1
                    st["proc"] = subprocess.Popen(comando(c))
                    marco(c, st["proc"].pid, f"reinicio #{st['reinicios']}")
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
