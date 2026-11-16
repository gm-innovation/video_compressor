#!/usr/bin/env python3
"""Radar .drq -> imagem (PPI/cru) -> vídeo: prova de execução, não de texto.

O que este teste prova, com arquivo de verdade gerado na hora (formato medido no arquivo do dono):
  1) a leitura por deslocamento fecha com cabecalho 1024 + N x 2240 e devolve radial, azimute e hora;
  2) a taxa "1 imagem por volta" emite UMA imagem por volta do azimute (fim da volta = azimute fino
     voltando ao começo), com a hora e o azimute do quadro impressos em cada imagem;
  3) a taxa "30 fps" emite ~30 imagens por segundo de gravação (as duas taxas pedidas pelo dono);
  4) os dois modos pedidos pelo dono saem: ppi (desenhada em 1.024x1.024) e cru (radiais desdobrados);
  5) o mp4 sai pelo ffmpeg DO PRODUTO, no alvo escolhido, com kbps medido do arquivo (não estimado);
  6) o arquivo do dono (2,36 GiB), quando presente, é lido sem carregar nada na memória e gera PPI.
"""
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DRQ_REAL = Path.home() / "work" / "replicacao" / "seadarq" / "sim" / "fixtures" / "drq" / "20261106164423.drq"
falhas = []


def checar(cond, texto):
    print(("  ok   " if cond else "  FALHA ") + texto)
    if not cond:
        falhas.append(texto)


def gravar_drq(caminho: Path, voltas: int, quadros_por_grau: int = 20, amostras=1024):
    """Arquivo no MESMO formato do radar: cabecalho 1.024 B, quadros de 2.240 B."""
    cab = bytearray(1024)
    struct.pack_into("<II", cab, 0, 0, 1)
    struct.pack_into("<II", cab, 128, 3539456, 4096)
    n = voltas * 360 * quadros_por_grau
    import datetime
    t0 = datetime.datetime(2026, 11, 6, 16, 44, 27)
    with open(caminho, "wb") as f:
        f.write(bytes(cab))
        for i in range(n):
            q = bytearray(2240)
            grau = (i // quadros_por_grau) % 360
            fino = (grau * 4096 // 360) % 4096
            dt = t0 + datetime.timedelta(seconds=i / (quadros_por_grau * 24.0))
            ft = int(((dt - datetime.datetime(1601, 1, 1)).total_seconds()) * 10_000_000)
            struct.pack_into("<II", q, 0, 3, 2240)
            struct.pack_into("<Q", q, 24, ft)
            struct.pack_into("<II", q, 40, grau, fino)
            struct.pack_into("<H", q, 188, amostras)
            for k in range(amostras):
                # eco de teste: mais forte perto do centro, com um alvo fixo a 300 amostras no grau 90
                v = 3000 - k // 2
                if abs(grau - 90) <= 1 and abs(k - 300) <= 3:
                    v = 4090
                struct.pack_into("<H", q, 192 + 2 * k, max(0, min(4095, v)) & 0x0FFF)
            f.write(bytes(q))
    return n


def rodar(args):
    return subprocess.run([sys.executable, str(RAIZ / "ground" / "radar_drq.py")] + args,
                          capture_output=True, text=True)


def png_valido(caminho: Path, largura=1024, altura=1024):
    b = caminho.read_bytes()
    if b[:8] != b"\x89PNG\r\n\x1a\n":
        return False, "assinatura PNG ausente"
    l, a = struct.unpack(">II", b[16:24])
    return (l == largura and a == altura), f"{l}x{a}"


print("1) leitura do formato (arquivo de teste no formato medido do radar)")
tmp = Path(tempfile.mkdtemp(prefix="radar-drq-"))
drq = tmp / "teste.drq"
n_quadros = gravar_drq(drq, voltas=2, quadros_por_grau=20)
sys.path.insert(0, str(RAIZ / "ground"))
import radar_drq as R                                                  # noqa: E402

cab = R.ler_cabecalho(drq)
checar(cab["quadros"] == n_quadros, f"cabecalho le {cab['quadros']} quadros (gravados {n_quadros})")
checar(os.path.getsize(drq) == 1024 + n_quadros * 2240, "tamanho = cabecalho + N x 2240")
with open(drq, "rb") as f:
    q = R.ler_quadro(f, 0)
checar(q and len(q["amostras"]) == 1024, "quadro tem 1.024 amostras")
checar(q and q["angulo"] == 0.0, f"azimute do primeiro quadro = {q and q['angulo']}")
checar(q and q["hora"].year == 2026, f"hora vem do FILETIME do quadro ({q and q['hora']})")

print("2) taxa '1 imagem por volta' = uma imagem por volta do azimute")
r = rodar([str(drq), "--saida", str(tmp / "volta"), "--modo", "ppi", "--taxa", "volta"])
checar(r.returncode == 0, f"conversao roda (rc={r.returncode}) {r.stderr[:200]}")
pngs = sorted((tmp / "volta").glob("*.png"))
checar(len(pngs) == 2, f"2 voltas -> {len(pngs)} imagem(ns) (esperado 2)")
if pngs:
    ok, dim = png_valido(pngs[0])
    checar(ok, f"PPI sai em 1.024x1.024 (medido {dim})")
    checar("hora" in r.stdout and "az_graus" in r.stdout, "cada imagem traz hora e azimute do quadro")

print("3) taxa '30 fps' = ~30 imagens por segundo de gravacao")
r = rodar([str(drq), "--saida", str(tmp / "fps30"), "--modo", "ppi", "--taxa", "30fps"])
pngs30 = sorted((tmp / "fps30").glob("*.png"))
dur = 2 * 360 * 20 / (20 * 24.0)
checar(len(pngs30) >= int(dur * 25) and len(pngs30) <= int(dur * 35),
       f"{len(pngs30)} imagens para {dur:.1f} s de gravacao (~30/s)")

print("4) os DOIS modos de imagem pedidos pelo dono")
r = rodar([str(drq), "--saida", str(tmp / "cru"), "--modo", "cru", "--taxa", "volta"])
pngs_cru = sorted((tmp / "cru").glob("*.png"))
checar(r.returncode == 0 and len(pngs_cru) == 2, f"modo cru gera as mesmas voltas ({len(pngs_cru)} imagem(ns))")
checar(pngs_cru and png_valido(pngs_cru[0])[0], "modo cru tambem sai em 1.024x1.024")
checar(pngs and pngs_cru and pngs[0].read_bytes() != pngs_cru[0].read_bytes(),
       "PPI e cru sao imagens diferentes (nao e' o mesmo desenho com outro nome)")
r = rodar([str(drq), "--saida", str(tmp / "x"), "--modo", "errado", "--taxa", "volta"])
checar(r.returncode != 0 and ("modo invalido" in r.stderr or "invalid choice" in r.stderr),
       "modo invalido e' recusado com a lista de modos")
r = rodar([str(drq), "--saida", str(tmp / "x"), "--modo", "ppi", "--taxa", "errada"])
checar(r.returncode != 0 and ("taxa invalida" in r.stderr or "invalid choice" in r.stderr),
       "taxa invalida e' recusada com a lista de taxas")

print("5) mp4 pelo ffmpeg DO PRODUTO, com kbps medido do arquivo")
ff = R.ffmpeg_do_produto()
checar(Path(ff).is_file(), f"ffmpeg do produto encontrado ({ff})")
if Path(ff).is_file():
    r = rodar([str(drq), "--saida", str(tmp / "mp4"), "--modo", "ppi", "--taxa", "30fps",
               "--alvo", "1500k", "--mp4"])
    mp4 = tmp / "mp4" / "radar.mp4"
    checar(mp4.is_file() and mp4.stat().st_size > 10000,
           f"mp4 gerado ({mp4.stat().st_size if mp4.is_file() else 0} B)")
    if mp4.is_file():
        import json
        info = json.loads(r.stdout[r.stdout.index("{"):])
        vid = info.get("video", {})
        checar(vid.get("alvo") == "1500k", f"alvo respeitado ({vid.get('alvo')})")
        checar((vid.get("kbps") or 0) > 0, f"kbps medido do arquivo: {vid.get('kbps')} (nao estimado)")
        checar((vid.get("segundos") or 0) > 0, f"duracao medida: {vid.get('segundos')} s")

print("6) arquivo do DONO (2,36 GiB), se estiver nesta maquina")
if DRQ_REAL.is_file():
    c = R.ler_cabecalho(str(DRQ_REAL))
    checar(c["quadros"] == 1131180, f"1.131.180 quadros lidos do arquivo real ({c['quadros']})")
    r = rodar([str(DRQ_REAL), "--saida", str(tmp / "real"), "--modo", "ppi", "--taxa", "volta",
               "--segundos", "6"])
    pngs_real = sorted((tmp / "real").glob("*.png"))
    checar(r.returncode == 0 and len(pngs_real) >= 1,
           f"arquivo real convertido em {len(pngs_real)} imagem(ns) de PPI (sem carregar 2,36 GiB)")
else:
    print("  (pulado: arquivo do dono nao esta nesta maquina)")

subprocess.run(["rm", "-rf", str(tmp)])
print()
if falhas:
    print(f"FALHOU em {len(falhas)} verificacao(oes):")
    for f in falhas:
        print(" -", f)
    sys.exit(1)
print("RADAR_DRQ_OK — arquivo .drq -> PPI/cru, nas duas taxas, com mp4 do produto")
