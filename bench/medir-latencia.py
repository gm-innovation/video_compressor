#!/usr/bin/env python3
"""Mede a latencia ponta a ponta (bordo -> terra -> leitor) pelo relogio queimado no quadro.

Como o numero e' obtido (tudo medido no mesmo computador, relogio do sistema):

  1. o agente de bordo queima no quadro o relogio de parede com milissegundos
     ("HH:MM:SS.mmm fN"); ligar com "relogio": true no board/perfis/<perfil>.json;
  2. este script abre UMA conexao continua no fluxo do lado terra e carimba a hora
     de chegada de CADA quadro (linha do showinfo do ffmpeg);
  3. no mesmo puxao ele salva alguns quadros como PNG (indices fixos) para leitura;
  4. le-se o relogio queimado nesses quadros (leitura unica visual: e' o que o olho
     ve na tela) e a latencia de cada um e' chegada - relogio queimado.

Erro tipico: +-0,1 s (resolucao do relogio queimado 1/30 s + carimbo da linha).
No HLS os quadros chegam em rajada por segmento: a latencia da rajada e' a que o
jogador HLS sente, por isso ela aparece melhor no pior caso.

Uso:
  python bench/medir-latencia.py "rtsp://127.0.0.1:8554/cam-01" [segundos]
  python bench/medir-latencia.py "http://127.0.0.1:8888/cam-01/index.m3u8" 20
  # depois de ler o relogio nas imagens salvas:
  python bench/medir-latencia.py --calcular latencia-rtsp.json --leituras 15:48:30.000,15:48:36.000 --postar

Ordem: sem "--calcular", mede; com "--calcular", fecha a conta (e opcionalmente
registra no banco do sistema, que exige valor, fonte, data, hardware_versao, comando).
"""
from __future__ import annotations
import json, re, subprocess, sys, time, urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "bench" / "saida"
RX = re.compile(r"n:\s*(\d+).*?pts_time:([0-9.]+)")
QUADROS = (300,)              # ajustavel por linha de comando (--n)


def nome_transporte(url: str) -> str:
    return "rtsp" if url.startswith("rtsp") else ("hls" if "m3u8" in url else "outro")


def medir(url: str, segundos: float = 18.0, n_quadro: int = 300) -> dict:
    """Puxa o fluxo, carimba a chegada de cada quadro e guarda o quadro pedido em imagem.

    360 quadros em JPEG: leve o bastante para nao atrapalhar o carimbo, e o indice do
    arquivo acompanha o "n" do showinfo (o image2 comeca em 1).
    """
    SAIDA.mkdir(parents=True, exist_ok=True)
    t = nome_transporte(url)
    for arq in SAIDA.glob(f"_q-{t}-[0-9]*.jpg"):   # so os numerados desta rodada; as amostras antigas ficam
        arq.unlink()
    limite = n_quadro + 60
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "info", "-i", url, "-frames:v", str(limite),
           "-vf", "showinfo", "-q:v", "4", "-y", str(SAIDA / f"_q-{t}-%04d.jpg")]
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                         errors="replace", bufsize=1, cwd=str(RAIZ))
    chegadas = []
    try:
        for linha in p.stderr:
            m = RX.search(linha)
            if m:
                chegadas.append({"n": int(m.group(1)), "t": round(time.time(), 3), "pts": float(m.group(2))})
    finally:
        p.terminate()
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
    arqs = sorted(SAIDA.glob(f"_q-{t}-[0-9]*.jpg"))     # so os numerados: as amostras ja lidas ficam
    cheg_n = next((x for x in chegadas if x["n"] == n_quadro), None)
    destino = None
    if len(arqs) > n_quadro:
        destino = SAIDA / f"_q-{t}-n{n_quadro}.jpg"
        arqs[n_quadro].replace(destino)     # o arquivo de indice n+1 e' o quadro n
    for a in arqs:
        if a.exists():
            a.unlink()
    arq = SAIDA / f"latencia-{t}.json"
    dados = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {"transporte": t, "url": url, "amostras": []}
    dados["amostras"] = [a for a in dados.get("amostras", []) if a.get("n") != n_quadro]
    dados["amostras"].append({"n": n_quadro, "png": str(destino) if destino else None,
                              "chegada": cheg_n["t"] if cheg_n else None,
                              "chegada_iso": (time.strftime("%H:%M:%S", time.localtime(cheg_n["t"])) +
                                              f".{int(cheg_n['t']*1000)%1000:03d}") if cheg_n else None,
                              "comando": " ".join(cmd)})
    dados["amostras"].sort(key=lambda a: a["n"])
    dados["quadros_carimbados"] = len(chegadas)
    arq.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[medir] {t}: {len(chegadas)} quadros carimbados | n={n_quadro} chegou "
          f"{dados['amostras'][-1]['chegada_iso']} | imagem: {destino}")
    return dados


def hms(s: str) -> float:
    h, m, seg = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(seg)


def calcular(arquivo: str, leituras: list[str], postar: bool, comando: str) -> dict:
    cam = RAIZ / "bench" / "saida" / arquivo
    if not cam.exists():
        cam = Path(arquivo)
    d = json.loads(cam.read_text(encoding="utf-8"))
    linhas = []
    for amostra, leitura in zip(d["amostras"], leituras):
        q = hms(leitura)
        chegada = amostra.get("chegada")
        if chegada is None:
            linhas.append({"n": amostra["n"], "quadro": leitura, "erro": "sem carimbo de chegada"})
            continue
        lt = time.localtime(chegada)
        # segundos do dia da chegada, com os milesimos (o strftime so da o segundo inteiro)
        chegada_sod = lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec + (chegada - int(chegada))
        lat = chegada_sod - q
        if lat < -43200:            # leitura caiu no dia seguinte (perto da meia-noite)
            lat += 86400
        linhas.append({"n": amostra["n"], "quadro": leitura, "chegada_iso": amostra.get("chegada_iso"),
                       "latencia_s": round(lat, 3)})
    vals = sorted(x["latencia_s"] for x in linhas if "latencia_s" in x)
    d["leitura_quadro"] = linhas
    d["latencia_s"] = ({"n": len(vals), "min": vals[0], "mediana": vals[len(vals)//2], "max": vals[-1],
                        "transporte": d["transporte"]} if vals else None)
    cam.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(d["latencia_s"], ensure_ascii=False))
    if postar and vals:
        corpo = {"valor": f"latencia ponta a ponta bordo->terra->leitor por {d['transporte'].upper()}: "
                          f"{vals[0]:.2f} a {vals[-1]:.2f} s (mediana {vals[len(vals)//2]:.2f} s) em {len(vals)} amostras",
                 "fonte": f"bench/medir-latencia.py ({d['transporte']})",
                 "hardware_versao": "NVIDIA GeForce RTX 4050 Laptop GPU, driver 551.76 | ffmpeg 9.0.1 | mediamtx v1.21.3",
                 "data": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                 "comando": comando, "fase_id": "fase-2"}
        req = urllib.request.Request("http://127.0.0.1:8765/api/medicoes",
                                    data=json.dumps(corpo, ensure_ascii=False).encode(),
                                    headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                print("registrado no banco:", r.status, r.read().decode()[:160])
        except Exception as e:
            print("falha ao registrar no banco:", e)
    return d


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--calcular":
        args = dict(zip(sys.argv[2::2], sys.argv[3::2]))
        leituras = [x.strip() for x in args.get("--leituras", "").split(",") if x.strip()]
        calcular(args.get("--arquivo", ""), leituras, "--postar" in sys.argv,
                 args.get("--comando", "ffmpeg -i <url> -vf showinfo,select=... -f null -"))
    elif len(sys.argv) >= 2:
        args = dict(zip(sys.argv[2::2], sys.argv[3::2]))
        medir(sys.argv[1], float(args.get("--segundos", 18)), int(args.get("--n", 300)))
    else:
        print(__doc__); sys.exit(2)
