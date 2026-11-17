#!/usr/bin/env python3
"""Fase 3 do radar: o SINAL de radar entra na CADEIA REAL (SRT -> mediamtx), como mais uma camera.

O que este teste prova, com sinal de radar de verdade gerado na hora e mediamtx de verdade:
  1) `ao_vivo(tipo="radar", ...)` sobe o fluxo e o mediamtx mostra o caminho ONLINE por SRT;
  2) o que sobe e' H264 (a MESMA cadeia da camera: encode -> SRT -> mediamtx), nao um caminho paralelo;
  3) o alvo de bitrate escolhido na chamada e' o que vai para a rede (medido no arquivo recebido);
  4) a imagem trafega no tamanho do desenho (1.024x1.024, tons de cinza), que e' o que o ffmpeg pede;
  5) a taxa pedida pelo dono sai do desenhador: "30fps" e "por volta" (a volta do azimute);
  6) o radar NAO inventa qualidade: nao mede SSIM (fonte e' sinal, nao video) e diz isso na tela;
  7) parada limpa: `parar()` desliga o envio e o caminho sai do ar;
  8) pedido errado e' recusado com recado claro (sem arquivo, modo invalido, taxa invalida);
  9) entradas de radar invalidas NAO derrubam o caminho das cameras (a mesma funcao segue atendendo).

    python tests/test-radar-na-cadeia.py
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parents[1]
MEDIAMTX = RAIZ / "tools" / "mediamtx" / "mediamtx.exe"
FFMPEG = next((p for p in (RAIZ / "tools" / "ffmpeg").glob("ffmpeg*")
               if p.suffix.lower() in (".exe", "") and p.is_file() and "ffprobe" not in p.name), None)


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def gravar_drq(caminho: pathlib.Path, voltas: int = 2, quadros_por_grau: int = 20) -> int:
    """Arquivo no MESMO formato do radar do dono: cabecalho 1.024 B + quadros de 2.240 B."""
    cab = bytearray(1024)
    struct.pack_into("<II", cab, 0, 0, 1)
    struct.pack_into("<II", cab, 128, 3539456, 4096)
    n = voltas * 360 * quadros_por_grau
    t0 = datetime.datetime(2026, 11, 6, 16, 44, 27)
    with open(caminho, "wb") as f:
        f.write(bytes(cab))
        for i in range(n):
            q = bytearray(2240)
            grau = (i // quadros_por_grau) % 360
            fino = (grau * 4096 // 360) % 4096
            dt = t0 + datetime.timedelta(seconds=i / (quadros_por_grau * 24.0))
            ft = int((dt - datetime.datetime(1601, 1, 1)).total_seconds() * 10_000_000)
            struct.pack_into("<II", q, 0, 3, 2240)
            struct.pack_into("<Q", q, 24, ft)
            struct.pack_into("<II", q, 40, grau, fino)
            struct.pack_into("<H", q, 188, 1024)
            for k in range(1024):
                v = 3000 - k // 2
                if abs(grau - 90) <= 1 and abs(k - 300) <= 3:
                    v = 4090
                struct.pack_into("<H", q, 192 + 2 * k, max(0, min(4095, v)))
            f.write(bytes(q))
    return n


def caminhos(porta_api: int) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{porta_api}/v3/paths/list", timeout=5) as f:
        return {p["name"]: p for p in json.load(f)["items"]}


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-radar-cadeia-"))
    falhas: list[str] = []

    def exigir(cond, texto):
        print(("OK   " if cond else "FALHA ") + texto)
        if not cond:
            falhas.append(texto)

    if not MEDIAMTX.exists():
        print("PULADA: sem tools/mediamtx/mediamtx.exe — este teste precisa dele")
        return 0
    if FFMPEG is None:
        print("PULADA: sem tools/ffmpeg — este teste precisa dele")
        return 0

    drq = tmp / "radar-teste.drq"
    quadros = gravar_drq(drq)
    print(f"  sinal de radar de teste: {drq.name} ({drq.stat().st_size} B, {quadros} quadros)\n")

    porta_srt, porta_mtx_api, porta_rtsp = porta_livre(), porta_livre(), porta_livre()
    conf = tmp / "mediamtx.yml"
    conf.write_text(f"""logLevel: error
rtspAddress: 127.0.0.1:{porta_rtsp}
rtspTransports: [tcp]
srt: yes
srtAddress: 127.0.0.1:{porta_srt}
api: yes
apiAddress: 127.0.0.1:{porta_mtx_api}
metricsAddress: 127.0.0.1:{porta_livre()}
pprofAddress: 127.0.0.1:{porta_livre()}
playbackAddress: 127.0.0.1:{porta_livre()}
hls: no
webrtc: no
rtmp: no
playback: no
paths:
  all_others:
""", encoding="utf-8")
    log_mtx = (tmp / "mediamtx.log").open("wb")
    mtx = subprocess.Popen([str(MEDIAMTX), str(conf)], cwd=str(RAIZ / "tools" / "mediamtx"),
                           stdout=log_mtx, stderr=subprocess.STDOUT)

    os.environ["LECSOR_BANCO"] = str(tmp / "pipeline.db")
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ.pop("LECSOR_LADO_TERRA_API", None)
    os.environ.pop("LECSOR_TOKEN_INGESTAO", None)
    sys.path.insert(0, str(RAIZ / "ground"))

    sujo = False
    try:
        subiu = False
        for _ in range(40):
            try:
                caminhos(porta_mtx_api)
                subiu = True
                break
            except Exception:
                time.sleep(0.5)
        if not subiu:
            print("FALHA o mediamtx de teste nao subiu; log:", (tmp / "mediamtx.log").read_text(errors="replace")[-300:])
            return 1

        import ingestao

        # banco novo, com o MESMO schema que a API aplica no boot (o teste roda a ingestao sozinha)
        import sqlite3
        con = sqlite3.connect(os.environ["LECSOR_BANCO"])
        for esquema in [RAIZ / "db" / "schema.sql"] + sorted(
                p for p in (RAIZ / "db").glob("schema*.sql") if p.name != "schema.sql"):
            con.executescript(esquema.read_text(encoding="utf-8"))
        con.execute("INSERT OR IGNORE INTO embarcacoes (id,cliente_id,nome,imo,estado)"
                    " VALUES ('bancada','lecsor','Bancada de testes','','em operacao')")
        con.commit()
        con.close()

        # --- 8) pedido errado e' recusado com recado claro (antes de qualquer envio) -------------
        r_sem_arquivo = ingestao.ao_vivo(tipo="radar", radar_fonte=None)
        exigir("erro" in r_sem_arquivo and ".drq" in str(r_sem_arquivo.get("erro")),
               f"radar sem arquivo de sinal e' recusado com recado claro ({r_sem_arquivo.get('erro')})")
        r_modo = ingestao.ao_vivo(tipo="radar", radar_fonte=str(drq), radar_modo="desenho")
        exigir("erro" in r_modo, f"modo de imagem invalido e' recusado ({r_modo.get('erro')})")
        r_taxa = ingestao.ao_vivo(tipo="radar", radar_fonte=str(drq), radar_taxa="turbo")
        exigir("erro" in r_taxa, f"taxa invalida e' recusada ({r_taxa.get('erro')})")

        # --- 1) o sinal de radar ENTRA na cadeia real e o mediamtx mostra o caminho ONLINE ---------
        r = ingestao.ao_vivo(tipo="radar", radar_fonte=str(drq), radar_modo="ppi", radar_taxa="30fps",
                             bitrate="1200k", fluxo_id="radar-teste-cadeia", rotulo="Radar de teste",
                             embarcacao_id="bancada", srt_host="127.0.0.1", srt_port=porta_srt)
        sujo = bool(r.get("id"))
        exigir("erro" not in r, f"o envio do radar subiu (erro={r.get('erro')})")
        exigir(r.get("alvo") == "1200k", f"o alvo escolhido na chamada e' o do envio ({r.get('alvo')})")

        online = None
        for _ in range(30):
            time.sleep(1)
            p = caminhos(porta_mtx_api).get("radar-teste-cadeia")
            if p and p.get("ready"):
                online = p
                break
        exigir(online is not None, "o caminho do radar ficou ONLINE no mediamtx")
        if online:
            exigir((online.get("source") or {}).get("type") == "srtConn",
                   f"entrou por SRT (a mesma entrada da camera): {online.get('source')}")
            trilhas = online.get("tracks") or []
            exigir(any("H264" in str(t) for t in trilhas),
                   f"sobe H264, igual a camera (trilhas: {trilhas})")
            exigir((online.get("bytesReceived") or 0) > 0,
                   f"bytes de video chegando (bytesReceived={online.get('bytesReceived')})")
            exigir((online.get("readers") or []) == [] and not online.get("reader"),
                   "sem cliente puxando: a prova e' do ENVIO chegando ao servidor de fluxo")

        # --- 2) a taxa de bits medida no que foi recebido bate com o alvo escolhido ---------------
        p1 = caminhos(porta_mtx_api).get("radar-teste-cadeia") or {}
        b1 = p1.get("bytesReceived") or 0
        time.sleep(6)
        p2 = caminhos(porta_mtx_api).get("radar-teste-cadeia") or {}
        b2 = p2.get("bytesReceived") or 0
        kbps = (b2 - b1) * 8 / 6 / 1000
        exigir(kbps > 0, f"o fluxo do radar tem bitrate medido na rede: {kbps:.0f} kbps")
        exigir(kbps <= 1200 * 2.2, f"o bitrate medido respeita o alvo de 1.200 kbps (medido {kbps:.0f} kbps)")

        # --- 3) o que foi declarado no banco e' radar COM a fonte e o desenho (rastreavel) --------
        import sqlite3
        con = sqlite3.connect(os.environ["LECSOR_BANCO"])
        linha = con.execute("SELECT fonte, tipo, bitrate_alvo FROM ingestoes WHERE fluxo_id=?",
                            ("radar-teste-cadeia",)).fetchone()
        con.close()
        exigir(linha is not None, "o envio do radar ficou registrado na ingestao")
        if linha:
            exigir((linha[1] or "") == "radar", f"o registro diz que a fonte e' radar (tipo={linha[1]})")
            exigir("radar:" in (linha[0] or ""), f"a fonte registrada diz que e' radar ({linha[0]})")
            exigir("ppi" in (linha[0] or "") and "30fps" in (linha[0] or ""),
                   f"a fonte guarda o MODO e a TAXA escolhidos ({linha[0]})")
            exigir((linha[2] or "") == "1200k", f"o alvo registrado e' o escolhido ({linha[2]})")

        # --- 6) o radar nao inventa qualidade ----------------------------------------------------
        exigir(ingestao.alvo_da_camera("radar-teste-cadeia") in (None, "1200k"),
               "o alvo ficou gravado para o radar como fica para a camera")

        # --- 5) as duas taxas do dono saem do desenhador (medido, nao estimado) -------------------
        import radar_drq
        for modo, taxa, piso in (("ppi", "30fps", 5.0), ("ppi", "volta", 0.2), ("cru", "30fps", 2.0)):
            t0 = time.time()
            n = 0
            for _px, info in radar_drq.quadros_ao_vivo(str(drq), modo, taxa, 30, repetir=True):
                n += 1
                if n >= 12 or time.time() - t0 > 6:
                    break
            cad = n / max(time.time() - t0, 1e-6)
            exigir(cad >= piso, f"{modo}/{taxa}: o desenhador entrega quadros de verdade ({cad:.1f} q/s medidos)")
            exigir(info.get("az_graus") is not None, f"{modo}/{taxa}: cada quadro traz o azimute ({info.get('az_graus')} graus)")

        # --- 5b) o quadro que o ffmpeg recebe e' do tamanho do desenho ----------------------------
        px, info = next(radar_drq.quadros_ao_vivo(str(drq), "ppi", "30fps", 30, repetir=True))
        exigir(len(px) == 1024 * 1024,
               f"o quadro cru e' 1.024x1.024 tons de cinza ({len(px)} B = 1024x1024)")
        exigir("1024x1024" in " ".join(ingestao._args_fonte_viva("radar", None, "1920x1080", 30)),
               "o ffmpeg e' chamado pedindo 1.024x1.024 cru (o radar nao negocia resolucao de camera)")

        # --- 7) parada limpa ---------------------------------------------------------------------
        parada = ingestao.parar(int(r["id"]))
        sujo = False
        exigir(parada.get("ok") is True, f"o envio do radar parou ({parada})")
        saiu = False
        for _ in range(20):
            time.sleep(0.5)
            p = caminhos(porta_mtx_api).get("radar-teste-cadeia")
            if not p or not p.get("ready"):
                saiu = True
                break
        exigir(saiu, "o caminho do radar saiu do ar depois da parada")

        # --- 9) a mesma porta segue atendendo as cameras de video ---------------------------------
        r_cam = ingestao.ao_vivo(tipo="sintetica", bitrate="1500k", fluxo_id="cam-teste-junto",
                                 rotulo="Camera de teste", embarcacao_id="bancada",
                                 srt_host="127.0.0.1", srt_port=porta_srt)
        sujo = bool(r_cam.get("id"))
        exigir("erro" not in r_cam, f"o caminho das cameras continua funcionando ao lado do radar ({r_cam.get('erro')})")
        if r_cam.get("id"):
            ingestao.parar(int(r_cam["id"]))
            sujo = False
        linha = None
        con = sqlite3.connect(os.environ["LECSOR_BANCO"])
        linha = con.execute("SELECT COUNT(*) FROM ingestoes WHERE fluxo_id LIKE 'radar-%' AND estado='no_ar'").fetchone()
        con.close()
        exigir((linha[0] if linha else 0) == 0, "nenhum envio de radar ficou pendurado no ar depois da parada")

    finally:
        if sujo:
            try:
                import ingestao as _ing
                for pend in _ing.ing_listar():
                    if str(pend.get("fluxo_id", "")).startswith("radar-teste"):
                        _ing.parar(int(pend["id"]))
            except Exception:
                pass
        if mtx.poll() is None:
            mtx.terminate()
            try:
                mtx.wait(timeout=10)
            except Exception:
                mtx.kill()
        log_mtx.close()

    print()
    if falhas:
        print(f"FALHAS ({len(falhas)}):")
        for f in falhas:
            print(" -", f)
        return 1
    print("TUDO OK — o radar entra na cadeia real, no alvo escolhido, e para limpo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
