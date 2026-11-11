"""Medição real: comprimir uma fonte que JÁ chega comprimida (1080p / 4K) para HD.

Caso A: clipe 1080p do YouTube (1,676 Mbps) -> HD 720p30 a 3000k
Caso B: o mesmo clipe reencodado a 1080p/6 Mbps (simula câmera comum) -> HD 720p30 a 3000k
Caso C: sintético 4K a 20 Mbps -> HD 720p30 a 3000k

Mede: bitrate de entrada, bitrate de saída, compressão e SSIM (contra a fonte reduzida a 720p).
"""
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
SAIDA = RAIZ / "medicoes-hd"
SAIDA.mkdir(exist_ok=True)
FONTE = RAIZ / "envios" / "YTDown.com_YouTube_Media_2XD0YOg0KFo_Setting-up-a-Makito-X4-Video-Decoder_001_10.mp4"
SEG = "15"


def sh(cmd: str, timeout: int = 900) -> str:
    proc = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, timeout=timeout)
    return (proc.stdout + proc.stderr).strip()


def bitrate_kbps(arquivo: Path) -> float:
    saida = sh(f'ffprobe -v error -select_streams v:0 -show_entries stream=bit_rate '
               f'-show_entries format=bit_rate -of default=nw=1:nk=1 "{arquivo}"')
    valores = [float(v) for v in saida.split() if v.replace(".", "").isdigit()]
    return max(valores) / 1000 if valores else 0.0


def ssim(saida: Path, referencia: Path) -> float:
    texto = sh(f'ffmpeg -hide_banner -nostdin -i "{saida}" -i "{referencia}" '
               f'-lavfi "[0:v][1:v]ssim=stats_file=-" -f null - 2>&1 | tail -2')
    achado = re.search(r"All:\s*([0-9.]+)", texto)
    return float(achado.group(1)) if achado else float("nan")


def preparar_fonte(nome: str, filtro: str, bitrate: str, origem: Path) -> Path:
    destino = SAIDA / nome
    if destino.exists():
        return destino
    sh(f'ffmpeg -y -hide_banner -loglevel error -nostdin -i "{origem}" -t {SEG} '
       f'-vf "{filtro}" -r 30 -c:v libx264 -preset veryfast -b:v {bitrate} -maxrate {bitrate} '
       f'-bufsize {int(bitrate[:-1]) * 2}k -pix_fmt yuv420p -an "{destino}"')
    return destino


def comprimir_hd(origem: Path, destino: Path, bitrate: str = "3000k") -> None:
    sh(f'ffmpeg -y -hide_banner -loglevel error -nostdin -i "{origem}" -t {SEG} '
       f'-vf "scale=-2:720" -r 30 -c:v libx264 -preset medium -b:v {bitrate} -maxrate {bitrate} '
       f'-bufsize {int(bitrate[:-1]) * 2}k -pix_fmt yuv420p -an "{destino}"')


def referencia_720(origem: Path, destino: Path) -> Path:
    if not destino.exists():
        sh(f'ffmpeg -y -hide_banner -loglevel error -nostdin -i "{origem}" -t {SEG} '
           f'-vf "scale=-2:720" -r 30 -c:v libx264 -preset veryfast -qp 0 -pix_fmt yuv420p -an "{destino}"')
    return destino


resultados = []

# Caso A — fonte 1080p já comprimida (1,676 Mbps)
a = preparar_fonte("a-1080p-1676k.mp4", "scale=-2:1080", "1676k", FONTE)
comprimir_hd(a, SAIDA / "a-hd-3000k.mp4")
resultados.append(("A) fonte 1080p ja comprimida (1.676 kbps)", a, SAIDA / "a-hd-3000k.mp4"))

# Caso B — o mesmo conteúdo a 1080p/6 Mbps (câmera comum)
b = preparar_fonte("b-1080p-6000k.mp4", "scale=-2:1080", "6000k", FONTE)
comprimir_hd(b, SAIDA / "b-hd-3000k.mp4")
resultados.append(("B) fonte 1080p a 6 Mbps (camara comum)", b, SAIDA / "b-hd-3000k.mp4"))

# Caso C — sintético 4K a 20 Mbps
c = SAIDA / "c-4k-20000k.mp4"
if not c.exists():
    sh(f'ffmpeg -y -hide_banner -loglevel error -nostdin -f lavfi -i '
       f'"testsrc2=size=3840x2160:rate=30" -t {SEG} -c:v libx264 -preset veryfast -b:v 20000k '
       f'-maxrate 20000k -bufsize 40000k -pix_fmt yuv420p "{c}"')
comprimir_hd(c, SAIDA / "c-hd-3000k.mp4")
resultados.append(("C) fonte 4K a 20 Mbps", c, SAIDA / "c-hd-3000k.mp4"))

print(f"{'caso':44} {'entrada':>10} {'saida':>9} {'compressao':>11} {'ssim':>7}")
for rotulo, fonte, comprimido in resultados:
    entrada, saida = bitrate_kbps(fonte), bitrate_kbps(comprimido)
    taxa = 100 * (1 - saida / entrada) if entrada else float("nan")
    indice = ssim(comprimido, referencia_720(fonte, SAIDA / (fonte.stem + "-ref720.mp4")))
    print(f"{rotulo:44} {entrada:9.0f}k {saida:8.0f}k {taxa:10.1f}% {indice:7.4f}")
    if not (taxa == taxa):
        sys.exit("medicao invalida")
