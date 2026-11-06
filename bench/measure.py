#!/usr/bin/env python3
"""Medicao da Fase 0-A: corte de banda, VMAF e velocidade de encode.

Cada numero gravado carrega os quatro campos exigidos pelo projeto:
valor, fonte, data, hardware/versao + comando (senao e hipotese, nao medicao).
"""
from __future__ import annotations
import argparse, csv, datetime as dt, json, platform, re, shutil, subprocess, sys, time
from pathlib import Path

CONFIGURACOES = [
    {"codec": "libx264",     "preset": "veryfast", "param": "-crf 23",              "rotulo": "x264 CRF23"},
    {"codec": "libx264",     "preset": "veryfast", "param": "-crf 28",              "rotulo": "x264 CRF28"},
    {"codec": "libx265",     "preset": "ultrafast","param": "-crf 28",              "rotulo": "x265 CRF28"},
    {"codec": "h264_nvenc",  "preset": "p4",       "param": "-cq 28 -rc vbr",       "rotulo": "NVENC H.264 CQ28"},
    {"codec": "hevc_nvenc",  "preset": "p4",       "param": "-cq 28 -rc vbr",       "rotulo": "NVENC HEVC CQ28"},
]

def rodar(cmd: list[str], timeout: int = 900):
    t0 = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p, time.perf_counter() - t0

def versao_ferramenta(nome: str) -> str:
    try:
        p = subprocess.run([nome, "-version"], capture_output=True, text=True, timeout=60)
        return (p.stdout or p.stderr).splitlines()[0].strip()
    except Exception as e:  # noqa: BLE001
        return f"indisponivel ({e})"

def hardware() -> dict:
    info = {"so": f"{platform.system()} {platform.release()}", "cpu": platform.processor() or "nao informado"}
    if shutil.which("nvidia-smi"):
        p = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=60)
        info["gpu"] = (p.stdout or "").strip() or "nao informado"
    else:
        info["gpu"] = "sem nvidia-smi"
    return info

def sonda_entrada(caminho: Path) -> dict:
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate,bit_rate,nb_frames,pix_fmt",
                        "-show_entries", "format=duration,size", "-of", "json", str(caminho)],
                       capture_output=True, text=True, timeout=120)
    d = json.loads(p.stdout)
    st = d["streams"][0]; fm = d.get("format", {})
    num, den = (st.get("r_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den or 1)
    largura, altura = int(st["width"]), int(st["height"])
    # bitrate cru (sem compressao) para 4:2:0 8 bits: W*H*1.5 bytes por quadro * fps * 8 bits
    bpp = 1.5
    bruto_bps = largura * altura * bpp * fps * 8
    return {
        "arquivo": str(caminho), "largura": largura, "altura": altura, "fps": round(fps, 3),
        "pix_fmt": st.get("pix_fmt"), "quadros": int(st.get("nb_frames") or 0),
        "duracao_s": round(float(fm.get("duration") or 0), 3), "tamanho_bytes": int(fm.get("size") or 0),
        "bitrate_cru_bps": round(bruto_bps), "bitrate_cru_mbps": round(bruto_bps / 1e6, 1),
    }

def bitrate_do_arquivo(caminho: Path) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=bit_rate", "-of", "json", str(caminho)],
                       capture_output=True, text=True, timeout=120)
    return float(json.loads(p.stdout)["format"].get("bit_rate") or 0)

def vmaf(original: Path, distorcido: Path, largura: int, altura: int) -> float | None:
    filtro = (f"[0:v]scale={largura}:{altura}:flags=bicubic[dist];"
              f"[1:v]scale={largura}:{altura}:flags=bicubic[ref];[dist][ref]libvmaf")
    cmd = ["ffmpeg", "-hide_banner", "-i", str(distorcido), "-i", str(original), "-lavfi", filtro,
           "-f", "null", "-"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    m = re.search(r"VMAF score:\s*([0-9.]+)", p.stderr)
    if not m:
        return None
    return round(float(m.group(1)), 2)

def principal() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entrada", required=True, help="clipe de referencia (video proprio)")
    ap.add_argument("--json", default="saida/resultado-fase0.json")
    ap.add_argument("--csv", default="saida/medicoes.csv")
    ap.add_argument("--pasta", default="saida")
    a = ap.parse_args()

    entrada = Path(a.entrada).resolve()
    pasta = Path(a.pasta); pasta.mkdir(parents=True, exist_ok=True)
    fonte = sonda_entrada(entrada)
    hw = hardware()
    agora = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    versoes = {"ffmpeg": versao_ferramenta("ffmpeg"), "ffprobe": versao_ferramenta("ffprobe")}

    medicoes = []
    for cfg in CONFIGURACOES:
        saida = pasta / f"cod-{cfg['codec']}-{cfg['rotulo'].split()[-1]}.mp4"
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(entrada),
               "-c:v", cfg["codec"], "-preset", cfg["preset"]] + cfg["param"].split() + [str(saida)]
        registro = {"fase": "0-A", "codec": cfg["codec"], "preset": cfg["preset"],
                    "parametros": cfg["param"], "rotulo": cfg["rotulo"],
                    "valor_bruto_mbps": fonte["bitrate_cru_mbps"],
                    "fonte": f"clip proprio: {entrada.name}",
                    "data": agora, "hardware": hw, "versoes": versoes,
                    "comando": " ".join(cmd)}
        try:
            p, dt_s = rodar(cmd)
            if p.returncode != 0 or not saida.exists():
                registro.update(erro=(p.stderr or "falha no ffmpeg").strip()[:400], status="erro")
            else:
                bps = bitrate_do_arquivo(saida)
                dur = fonte["duracao_s"] or 1
                registro.update(
                    status="ok", arquivo_saida=str(saida.name), bitrate_cod_bps=round(bps),
                    bitrate_cod_mbps=round(bps / 1e6, 3),
                    corte_pct=round((1 - bps / fonte["bitrate_cru_bps"]) * 100, 2),
                    segundos_encode=round(dt_s, 2), vezes_tempo_real=round(dur / dt_s, 2),
                    tamanho_bytes=saida.stat().st_size,
                )
                registro["vmaf"] = vmaf(entrada, saida, fonte["largura"], fonte["altura"])
        except subprocess.TimeoutExpired:
            registro.update(status="erro", erro="tempo esgotado no encode")
        medicoes.append(registro)
        print(f"[{registro.get('status')}] {cfg['rotulo']:16s} "
              f"{registro.get('bitrate_cod_mbps','-')} Mbps  corte {registro.get('corte_pct','-')}%  "
              f"{registro.get('vezes_tempo_real','-')}x  VMAF {registro.get('vmaf','-')}")

    resultado = {"fase": "0-A", "gerado_em": agora, "entrada": fonte, "hardware": hw,
                 "versoes": versoes, "medicoes": medicoes,
                 "observacao": ("Clip sintetico (video proprio gerado por ffmpeg) - o corte medido aqui nao substitui "
                                "o numero sobre video real de camera, que entra na Fase 0-B.")}
    Path(a.json).parent.mkdir(parents=True, exist_ok=True)
    Path(a.json).write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(a.csv, "w", newline="", encoding="utf-8") as f:
        campos = ["rotulo", "codec", "preset", "parametros", "valor_bruto_mbps", "bitrate_cod_mbps",
                  "corte_pct", "vmaf", "segundos_encode", "vezes_tempo_real", "status", "data"]
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for m in medicoes:
            w.writerow(m)
    print(f"\n[ok] {a.json}\n[ok] {a.csv}")
    return 0

if __name__ == "__main__":
    sys.exit(principal())
