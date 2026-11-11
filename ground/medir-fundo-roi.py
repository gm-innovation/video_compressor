"""Teste real: teto de compressão (1080p/4K -> HD) e efeito de remover fundo e usar ROI.

Medição 1: 1080p (6 Mbps) e 4K (20 Mbps) convertidos para HD 720p30 em 1000k / 1500k / 3000k.
Medição 2: fundo MONOCROMÁTICO (cor única) x fundo DETALHADO (cena real): tamanho do arquivo na
           MESMA qualidade (CRF 26) com o quadro inteiro e com tudo fora da ROI virando cor lisa.
Medição 3: ROI em bitrate fixo (1500k): qualidade dentro da ROI com o quadro inteiro x com o
           fora-da-ROI achatado (que é o que faz o encoder gastar os bits onde interessa).

Todas as contas saem do ffmpeg/ffprobe; nada é estimado.
"""
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
D = RAIZ / "medicoes-hd"
D.mkdir(exist_ok=True)
CLIPE = RAIZ / "envios" / "YTDown.com_YouTube_Media_2XD0YOg0KFo_Setting-up-a-Makito-X4-Video-Decoder_001_10.mp4"
SEG = "12"
ROI = "crop=1152:432:384:324"  # retangulo central: 60% da largura x 40% da altura


def sh(cmd: str, timeout: int = 1200) -> str:
    p = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, timeout=timeout)
    return (p.stdout + p.stderr).strip()


def kb(arquivo: Path) -> float:
    valor = sh(f'ffprobe -v error -select_streams v:0 -show_entries stream=bit_rate '
               f'-of default=nw=1:nk=1 "{arquivo}"').splitlines()[0]
    return float(valor or 0) / 1000


def tam(arquivo: Path) -> int:
    return int(sh(f'stat -c%s "{arquivo}"') or 0)


def dim(arquivo: Path, campo: str) -> str:
    return sh(f'ffprobe -v error -select_streams v:0 -show_entries stream={campo} '
              f'-of default=nw=1:nk=1 "{arquivo}"').splitlines()[0]


def ssim(saida: Path, referencia: Path, filtro: str = "") -> str:
    """SSIM entre a saída e a referência; `filtro` (ex.: crop) é aplicado nas DUAS."""
    if filtro:
        lavfi = f"[0:v]{filtro},setpts=PTS-STARTPTS[a];[1:v]{filtro},setpts=PTS-STARTPTS[b];[a][b]ssim"
    else:
        lavfi = "[0:v]setpts=PTS-STARTPTS[a];[1:v]setpts=PTS-STARTPTS[b];[a][b]ssim"
    texto = sh(f'ffmpeg -hide_banner -nostdin -i "{saida}" -i "{referencia}" -lavfi "{lavfi}" '
               f'-f null - 2>&1 | grep -o "All:[0-9.]*" | tail -1')
    return texto.replace("All:", "") or "?"


def rodar(entrada: Path, saida: Path, filtros: str, modo: str) -> None:
    if saida.exists():
        return
    sh(f'ffmpeg -y -hide_banner -loglevel error -nostdin -i "{entrada}" -t {SEG} {filtros} -r 30 '
       f'{modo} -pix_fmt yuv420p -an "{saida}"')


def qp0(entrada: Path, saida: Path) -> Path:
    if not saida.exists():
        sh(f'ffmpeg -y -hide_banner -loglevel error -nostdin -i "{entrada}" -t {SEG} '
           f'-c:v libx264 -preset veryfast -qp 0 -pix_fmt yuv420p -an "{saida}"')
    return saida


print("== Medicao 1: teto de compressao convertendo para HD 720p30 ==")
for nome, fonte, tag in [("1080p 6 Mbps", D / "b-1080p-6000k.mp4", "1080"),
                         ("4K 20 Mbps", D / "c-4k-20000k.mp4", "4k")]:
    if not fonte.exists():
        print(f"  (fonte ausente: {fonte.name})")
        continue
    entrada = kb(fonte)
    ref720 = D / f"{tag}-ref720.mp4"
    if not ref720.exists():
        sh(f'ffmpeg -y -hide_banner -loglevel error -nostdin -i "{fonte}" -vf "scale=-2:720" -r 30 '
           f'-c:v libx264 -preset veryfast -qp 0 -pix_fmt yuv420p "{ref720}"')
    print(f"\n  {nome} (entrada medida: {entrada:.0f} kbps)")
    for alvo in ("1000k", "1500k", "3000k"):
        saida = D / f"m1-{tag}-{alvo}.mp4"
        rodar(fonte, saida, '-vf "scale=-2:720"',
              f"-c:v libx264 -preset medium -b:v {alvo} -maxrate {alvo} -bufsize {int(alvo[:-1]) * 2}k")
        print(f"    HD {alvo:>6}: {kb(saida):7.0f} kbps | compressao {100 * (1 - kb(saida) / entrada):5.1f}%"
              f" | SSIM {ssim(saida, ref720)}")

print("\n== Medicao 2: fundo monocromatico x fundo detalhado, mesma qualidade (CRF 26) ==")
mono = D / "m2-mono-fonte.mp4"
if not mono.exists():
    sh(f'ffmpeg -y -hide_banner -loglevel error -nostdin -f lavfi -i "color=c=0x2b3a4a:s=1920x1080:r=30" '
       f'-i "{CLIPE}" -filter_complex "[1:v]scale=800:450[s];[0:v][s]overlay=x=\'120+180*sin(t/3)\':y=315" '
       f'-t {SEG} -c:v libx264 -preset veryfast -qp 0 -pix_fmt yuv420p "{mono}"')
detalhado = D / "m2-detalhado-fonte.mp4"
if not detalhado.exists():
    sh(f'ffmpeg -y -hide_banner -loglevel error -nostdin -i "{CLIPE}" -t {SEG} -vf "scale=-2:1080" -r 30 '
       f'-c:v libx264 -preset veryfast -qp 0 -pix_fmt yuv420p "{detalhado}"')
achata = ('-filter_complex "color=c=0x2b3a4a:s=1920x1080:r=30[bg];'
          '[0:v]crop=1152:432:384:324[roi];[bg][roi]overlay=384:324"')
for rotulo, fonte in [("mono", mono), ("detalhado", detalhado)]:
    cheio = D / f"m2-{rotulo}-cheio-crf26.mp4"
    liso = D / f"m2-{rotulo}-fundo-liso-crf26.mp4"
    rodar(fonte, cheio, '-vf "scale=-2:1080"', "-c:v libx264 -preset medium -crf 26")
    rodar(fonte, liso, achata, "-c:v libx264 -preset medium -crf 26")
    ganho = 100 * (1 - tam(liso) / tam(cheio)) if tam(cheio) else 0
    print(f"  {rotulo:10}: quadro inteiro {tam(cheio) / 1024:7.0f} KB ({kb(cheio):7.0f} kbps) | "
          f"fora da ROI liso {tam(liso) / 1024:7.0f} KB ({kb(liso):7.0f} kbps) | ganho {ganho:5.1f}%")

print("\n== Medicao 3: ROI em bitrate fixo — onde os bits vao parar (1500k) ==")
for rotulo, fonte in [("mono", mono), ("detalhado", detalhado)]:
    refer = qp0(fonte, D / f"m3-{rotulo}-ref-qp0.mp4")
    cheio = D / f"m3-{rotulo}-cheio-1500k.mp4"
    liso = D / f"m3-{rotulo}-fundo-liso-1500k.mp4"
    rodar(fonte, cheio, '-vf "scale=-2:1080"', "-c:v libx264 -preset medium -b:v 1500k -maxrate 1500k -bufsize 3000k")
    rodar(fonte, liso, achata, "-c:v libx264 -preset medium -b:v 1500k -maxrate 1500k -bufsize 3000k")
    print(f"  {rotulo:10}: SSIM quadro inteiro {ssim(cheio, refer)} | SSIM SO na ROI {ssim(cheio, refer, ROI)}"
          f" | com fora-da-ROI liso, SSIM na ROI {ssim(liso, refer, ROI)}")
    print(f"              {dim(cheio, 'width')}x{dim(cheio, 'height')} e {kb(cheio):.0f} kbps nos dois lados")
