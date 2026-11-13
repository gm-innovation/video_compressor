"""Mede as alavancas de EFICIENCIA da bancada (Fase 4 do plano): da' para melhorar a imagem sem
subir banda?

Mede, nesta maquina, e imprime o fato — inclusive quando o fato e' "nao funciona":
  1. `h264_nvenc` (encoder de hardware) existe? funciona? (com o motivo exato da recusa)
  2. quantos canais 1080p30 esta CPU aguenta no preset que o produto usa (`veryfast`) — e' o teto
     real de quantas cameras podem subir de alvo sem faltar quadro;
  3. ROI por mapa de QP: o x264 aceita zona por TEMPO (`-x264-params zones=...`)? e por REGIAO?

    python tests/medir-aceleracao.py
"""
import pathlib
import re
import shutil
import subprocess
import sys
import time

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "ground"))
from ferramentas import caminho_ffmpeg  # noqa: E402
import ingestao  # noqa: E402

FF = caminho_ffmpeg()


def rodar(args, timeout=300):
    return subprocess.run([FF, "-hide_banner", *args], capture_output=True, text=True,
                          timeout=timeout, errors="replace")


def main() -> int:
    print("ffmpeg:", FF)
    enc = rodar(["-encoders"])
    texto = enc.stdout + enc.stderr
    existe = {n: bool(re.search(rf"\b{n}\b", texto)) for n in ("h264_nvenc", "hevc_nvenc", "libx264")}
    print("encoders presentes:", existe)

    gpu = shutil.which("nvidia-smi")
    if gpu:
        d = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                           capture_output=True, text=True, errors="replace")
        print("GPU:", (d.stdout or d.stderr).strip()[:120])
    else:
        print("GPU: sem nvidia-smi nesta maquina")

    print()
    print("== 1. encoder de hardware (nvenc) ==")
    if existe["h264_nvenc"]:
        r = rodar(["-loglevel", "warning", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30",
                   "-t", "2", "-c:v", "h264_nvenc", "-b:v", "2500k", "-f", "null", "-"])
        if r.returncode == 0:
            print("h264_nvenc: FUNCIONA nesta maquina (1080p30, 2 s)")
        else:
            motivo = [x for x in (r.stderr or "").splitlines() if "nvenc" in x.lower()]
            print("h264_nvenc: NAO FUNCIONA nesta maquina")
            for x in motivo[:2]:
                print("   ", x.strip()[:180])
    else:
        print("h264_nvenc: nao existe neste ffmpeg")

    print()
    print("== 2. quantos canais 1080p30 esta CPU aguenta (preset do produto: %s) ==" % ingestao.PRESET_ENCODE)
    ajuste = ingestao.ajuste_encode("2500k", 30)
    cmd = ["-loglevel", "info", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30", "-t", "6"] + ajuste + ["-f", "null", "-"]
    t0 = time.time()
    r = rodar(cmd)
    gasto = time.time() - t0
    linha = " ".join((r.stderr or "").splitlines()[-3:])
    quadro = re.findall(r"frame=\s*(\d+)", r.stderr or "")
    fps_real = re.findall(r"fps=\s*([0-9.]+)", r.stderr or "")
    velocidade = (float(quadro[-1]) / gasto) if quadro and gasto else None
    print("quadros:", quadro[-1] if quadro else "?", "| arquivo de %s s em %.1f s" % ("6", gasto),
          "| fps de encode: %s" % (fps_real[-1] if fps_real else "?"))
    if velocidade:
        print("velocidade de encode: %.1f x tempo real -> esta CPU aguenta ~%d canal(is) 1080p30 "
              "no preset %s" % (velocidade / 30.0, max(1, int(velocidade / 30.0)), ingestao.PRESET_ENCODE))

    print()
    print("== 3. ROI (gastar bits onde importa) ==")
    r = rodar(["-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-t", "2",
               "-c:v", "libx264", "-x264-params", "zones=0,15,q=20", "-b:v", "1500k", "-f", "null", "-"])
    print("x264 'zones' (prioridade por TEMPO, nao por regiao):", "aceito" if r.returncode == 0 else "recusado")
    if r.returncode != 0:
        print("   ", (r.stderr or "").strip().splitlines()[-1][:180] if r.stderr else "sem mensagem")
    print("mapa de QP por REGIAO (ROI espacial): nao ha opcao no libx264 nem no h264_nvenc deste ffmpeg —")
    print("   o plano de ROI por mapa de QP depende de um encoder que aceite o mapa (ou de pre-processar")
    print("   a imagem), e isso NAO foi medido; o que existe hoje e' zona por tempo (acima).")

    print()
    print("MEDIDO: os numeros acima sao desta maquina (bancada), nao da VPS nem do PC do cliente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
